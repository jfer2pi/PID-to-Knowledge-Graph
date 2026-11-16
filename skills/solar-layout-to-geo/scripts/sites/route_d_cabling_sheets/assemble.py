"""the route D site: assemble the ten sheets in the key-plan frame, georeference (provisional), export."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, json, pickle, collections, csv, math, shutil
from pathlib import Path
import numpy as np
from shapely.geometry import Point, Polygon, LineString, box, mapping, MultiPoint
from shapely.ops import unary_union
from scipy import ndimage
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit
import register_ac as RG
import raster

W = Path(WORK)
OUT = Path(OUT)
SITE = "route_d_site"
CRS = os.environ.get("SITE_CRS", "EPSG:32630")                       # projected CRS of the site, set per site
ANCHOR_LONLAT = tuple(float(v) for v in os.environ.get("SITE_ANCHOR_LONLAT", "0,0").split(","))   # published plant point, lon,lat
MOD_PER_TABLE, STR_PER_TABLE, MOD_PER_STR = 40, 2, 20


def olive_ctin(H):
    """CTIN symbol: the densest cluster of olive strokes in the detail view."""
    P = np.array(H["E"]["olive"])
    if not len(P):
        return None
    from scipy.cluster.hierarchy import fcluster, linkage
    lab = fcluster(linkage(P, "single"), 4.0, "distance")
    k = collections.Counter(lab).most_common(1)[0][0]
    Q = P[lab == k]
    return tuple(Q.mean(0)), len(Q)


def resolve_names(H, ctin, disc):
    """final (n1, ta) per connector: one connector per table, fallback for unnamed connectors,
    and the board each circuit physically reaches when leader and table disagree."""
    D, rid = H["D"], H["rid"]
    names = {a: dict(v) for a, v in H["dot_name"].items()}
    # 1. two connectors on one table: keep one (a dot split where cables cross it)
    seen = {}
    for a in sorted(names):
        key = tuple(np.round(H["tab"][a][0], 1))
        if key in seen:
            disc.append(f"CTIN-{ctin:02d}: two connectors on one table at row {H['lab_row'].get(rid[a])}; counted once")
            del names[a]
        else:
            seen[key] = a
    # 2. connectors with no circuit (cable hidden by a board symbol): nearest named connector on the row
    tx = [((t[0] + t[2]) / 2, (t[1] + t[3]) / 2) for t in H["E"]["ta_raw"]]
    for a in range(len(D)):
        if a in names or a not in H["tab"]:
            continue
        key = tuple(np.round(H["tab"][a][0], 1))
        if key in seen and seen[key] != a:
            continue
        cands = [b for b in names if rid[b] == rid[a]]
        if not cands:
            continue
        b = min(cands, key=lambda b: abs(D[b, 0] - D[a, 0]))
        names[a] = dict(names[b], inferred=True); seen[key] = a
    # 3. board per circuit
    n_boards = len(H["E"]["ta_raw"])
    tab = {e["n1"]: e["ta"] for e in H["table"]}
    exact = H["table_src"] == "text"
    by_n1 = collections.defaultdict(collections.Counter)
    for a, v in names.items():
        by_n1[v["n1"]][v["ta"]] += 1
    comp_boards = collections.defaultdict(collections.Counter)
    for a, v in names.items():
        for q in H["comp_ta"].get(H["dot_comp"].get(a), [])[:1]:
            comp_boards[v["n1"]][q] += 1
    votes = collections.defaultdict(collections.Counter)
    for n1, c in by_n1.items():
        ta = c.most_common(1)[0][0]
        for q in comp_boards[n1]:
            votes[q][ta] += 1
    final = {}
    for n1, c in by_n1.items():
        lead = c.most_common(1)[0][0]
        t = tab.get(n1)
        if t is None or lead == t:
            final[n1] = lead if lead <= n_boards + 1 else (t or lead); continue
        if lead > n_boards + 1:
            final[n1] = t; disc.append(f"CTIN-{ctin:02d} N1-{n1:02d}: leader read TA{lead:02d} (impossible), table TA{t:02d} used"); continue
        phys = None
        for q in comp_boards[n1]:
            others = votes[q].copy(); others[lead] -= 1
            others = +others
            if others:
                phys = others.most_common(1)[0][0]
        pick = phys if phys in (lead, t) else (t if exact else lead)
        final[n1] = pick
        disc.append(f"CTIN-{ctin:02d} N1-{n1:02d}: drawing label says TA{ctin:02d}-1-{lead:02d}, circuit table says TA{ctin:02d}-1-{t:02d}"
                    f" ({'text' if exact else 'OCR'}); the cable reaches the board shared with "
                    f"{'TA%02d' % phys if phys else 'no other circuit'}; used TA{ctin:02d}-1-{pick:02d}")
    for a, v in names.items():
        v["ta"] = final[v["n1"]]
    return names


def main():
    reg = json.load(open(W / "cache/register.json"))
    cm = json.load(open(W / "cache/ctin_match.json"))
    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)

    feats = collections.defaultdict(list)      # layer -> [(geom in key frame m, props)]
    rows_h = []                                  # hierarchy rows (key frame for now)
    qa = {}
    disc = []
    for i in range(1, 11):
        H = pickle.load(open(W / f"cache/H{i:02d}.pkl", "rb"))
        R = reg[str(i)]
        C = R["m_per_pt"]
        names = resolve_names(H, i, disc)
        sx_, sy_ = cm["sheets"][str(i)]["shift"]
        dX, dY = R["dX"] + sx_, R["dY"] + sy_
        K = lambda x, y: (x * C + dX, -y * C + dY)
        ctin = i
        cid = f"CTIN-{ctin:02d}"
        inv = f"INV{ctin:02d}"
        # station
        tp = cm["sheets"][str(i)]["trafo_pt"]
        sx, sy = K(*tp)
        oc = (tp, cm["sheets"][str(i)]["trafo_n"])
        # boards: one-to-one naming from every circuit that touches each board symbol
        from scipy.optimize import linear_sum_assignment
        bv = collections.defaultdict(collections.Counter)
        for a, v in names.items():
            for q in H["comp_ta"].get(H["dot_comp"].get(a), []):
                bv[q][v["ta"]] += 1
        tas_all = sorted({v["ta"] for v in names.values()})
        qs = list(range(len(H["E"]["ta_raw"])))
        Cm = np.zeros((len(qs), len(tas_all)))
        for q in qs:
            for b_, ta in enumerate(tas_all):
                Cm[q, b_] = -bv[q][ta]
        boards = {}
        if len(qs) and len(tas_all):
            ra, cb = linear_sum_assignment(Cm)
            for q, b_ in zip(ra, cb):
                if Cm[q, b_] < 0:
                    t = H["E"]["ta_raw"][q]
                    bx, by = K((t[0] + t[2]) / 2, (t[1] + t[3]) / 2)
                    boards[tas_all[b_]] = [(bx, by, q)]
        # connections (one fused tap per table)
        conns = collections.defaultdict(list)
        for a, nm in names.items():
            t, src = H["tab"][a]
            conns[(nm["n1"], nm["ta"])].append(dict(a=a, t=t, src=src, how="leader" if not (nm.get("inferred") or nm.get("from_table")) else ("same-row" if nm.get("inferred") else "table"),
                                                    row=H["lab_row"].get(H["rid"][a]), dot=tuple(H["D"][a])))
        # combiners present = boards with at least one circuit
        tas_used = sorted({ta for (_, ta) in conns})
        n_tab = sum(len(v) for v in conns.values())
        rows_h.append(dict(id=cid, level="station", parent="", station=cid, inverter="", combiner="", circuit="", string="",
                           n_combiners=len(tas_used), n_circuits=len(conns), n_tables=n_tab, n_strings=n_tab * STR_PER_TABLE,
                           n_modules=n_tab * MOD_PER_TABLE, X=sx, Y=sy, location_source="CTIN symbol", derived=""))
        rows_h.append(dict(id=inv, level="inverter", parent=cid, station=cid, inverter=inv, combiner="", circuit="", string="",
                           board=f"TA{ctin:02d}-2", n_combiners=len(tas_used), n_circuits=len(conns), n_tables=n_tab,
                           n_strings=n_tab * STR_PER_TABLE, n_modules=n_tab * MOD_PER_TABLE, X=sx, Y=sy,
                           location_source="CTIN symbol (level-2 board TA%02d-2 at the station)" % ctin, derived=""))
        feats["stations"].append((Point(sx, sy), dict(id=cid, level="station", n_tables=n_tab, n_modules=n_tab * MOD_PER_TABLE)))
        feats["inverters"].append((Point(sx, sy), dict(id=inv, level="inverter", station=cid, board=f"TA{ctin:02d}-2",
                                                       n_combiners=len(tas_used), n_strings=n_tab * STR_PER_TABLE)))
        for ta in tas_used:
            comb = f"TA{ctin:02d}-1-{ta:02d}"
            cid_ = f"{inv}-{comb}"
            circs = sorted(n1 for (n1, t_) in conns if t_ == ta)
            nt = sum(len(conns[(n1, ta)]) for n1 in circs)
            if ta in boards:
                bx, by, q = boards[ta][0]
                src_b = "board symbol"
            else:
                pts = [K(*c["dot"]) for n1 in circs for c in conns[(n1, ta)]]
                bx, by = np.mean(pts, 0); src_b = "centroid of its tables (board symbol not named)"
            if ta in boards and len(boards[ta]) > 1:
                disc.append(f"{cid}: two board symbols named {comb}")
            rows_h.append(dict(id=cid_, level="combiner", parent=inv, station=cid, inverter=inv, combiner=comb, circuit="", string="",
                               n_circuits=len(circs), n_tables=nt, n_strings=nt * STR_PER_TABLE, n_modules=nt * MOD_PER_TABLE,
                               X=bx, Y=by, location_source=src_b, derived=""))
            feats["combiners"].append((Point(bx, by), dict(id=cid_, level="combiner", name=comb, inverter=inv, station=cid,
                                                           n_circuits=len(circs), n_strings=nt * STR_PER_TABLE)))
            for n1 in circs:
                cs = conns[(n1, ta)]
                # order from the board outward: rows nearest the board first, then distance along the row
                cs.sort(key=lambda c: (abs(c["dot"][1] - (by - dY) / -C) // 9, abs(c["dot"][0] - (bx - dX) / C)))
                circ = f"N1-{n1:02d}"
                cir_id = f"{cid_}-{circ}"
                rows_named = sorted({c["row"] for c in cs if c["row"]})
                hows = collections.Counter(c["how"] for c in cs)
                pts = [K(*c["dot"]) for c in cs]
                line = LineString([(bx, by)] + pts) if pts else None
                rows_h.append(dict(id=cir_id, level="circuit", parent=cid_, station=cid, inverter=inv, combiner=comb, circuit=circ, string="",
                                   rows=" ".join(rows_named), n_tables=len(cs), n_strings=len(cs) * STR_PER_TABLE,
                                   n_modules=len(cs) * MOD_PER_TABLE, X=np.mean([p[0] for p in pts]), Y=np.mean([p[1] for p in pts]),
                                   location_source="centroid of its tables", derived="name: " + ", ".join(f"{k} {v}" for k, v in hows.items())))
                feats["circuits"].append((line, dict(id=cir_id, level="circuit", name=circ, combiner=comb, inverter=inv,
                                                     rows=" ".join(rows_named), n_tables=len(cs))))
                for k, c in enumerate(cs, 1):
                    t = c["t"]
                    x0, y0 = K(t[0], t[3]); x1, y1 = K(t[2], t[1])
                    poly = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                    tid = f"{cir_id}-T{k:02d}"
                    feats["tables"].append((poly, dict(id=tid, level="table", circuit=circ, combiner=comb, inverter=inv, station=cid,
                                                       row=c["row"], n_modules=MOD_PER_TABLE, n_strings=STR_PER_TABLE,
                                                       geometry_source=c["src"], name_source=c["how"])))
                    # two strings per table: upper and lower module row (derived)
                    ym = (poly.bounds[1] + poly.bounds[3]) / 2
                    halves = [box(poly.bounds[0], ym, poly.bounds[2], poly.bounds[3]), box(poly.bounds[0], poly.bounds[1], poly.bounds[2], ym)]
                    for s, hp in enumerate(halves, 1):
                        sid = f"{tid}-S{s}"
                        rows_h.append(dict(id=sid, level="string", parent=cir_id, station=cid, inverter=inv, combiner=comb, circuit=circ,
                                           string=sid, table=tid, row=c["row"], n_modules=MOD_PER_STR, X=hp.centroid.x, Y=hp.centroid.y,
                                           location_source="half of its table", derived="string split (2 per fused tap, 20 modules) and geometry"))
                        feats["strings"].append((hp, dict(id=sid, level="string", table=tid, circuit=circ, combiner=comb, inverter=inv,
                                                          n_modules=MOD_PER_STR, derived=True)))
        # block outline from the key plan highlight
        Y = RG.key_mask(i)
        res_k = RG.CK / raster.PX
        lab_, n_ = ndimage.label(Y)
        if n_:
            from skimage import measure
            big = (lab_ == (np.argmax(ndimage.sum(Y, lab_, range(1, n_ + 1))) + 1))
            cont = max(measure.find_contours(big.astype(float), 0.5), key=len)
            ring = [(c[1] * res_k, -c[0] * res_k) for c in cont]
            poly = Polygon(ring).simplify(0.8)
            feats["site"].append((poly, dict(id=f"BLOCK-{ctin:02d}", level="block", station=cid,
                                             source="key plan highlight (1:15,000)")))
        qa[i] = dict(H["qa"], ctin_symbol_points=oc[1] if oc else 0, table_src=H["table_src"],
                     table_fixes=len(H.get("table_fixes", [])), reg_iou=R["iou"], reg_inside=R["tables_inside"])
    feats, rows_h = drop_foreign(feats, rows_h, disc)
    return feats, rows_h, qa, disc


def drop_foreign(feats, rows_h, disc):
    """a table whose centre lies outside its own key-plan block and inside another block belongs to the neighbour"""
    blocks = {p["station"]: g.buffer(4.0) for g, p in feats["site"]}
    bad = set()
    for g, p in feats["tables"]:
        c = g.centroid
        own = blocks.get(p["station"])
        if own is not None and not own.contains(c) and any(b.contains(c) for s, b in blocks.items() if s != p["station"]):
            bad.add(p["id"])
            disc.append(f"{p['station']}: table {p['id']} lies in a neighbouring block (seen in this sheet's view); dropped")
    if not bad:
        return feats, rows_h
    feats["tables"] = [(g, p) for g, p in feats["tables"] if p["id"] not in bad]
    feats["strings"] = [(g, p) for g, p in feats["strings"] if p["table"] not in bad]
    rows_h = [r for r in rows_h if not (r["level"] == "string" and r.get("table") in bad)]
    # recount parents
    cnt = collections.Counter()
    for g, p in feats["tables"]:
        for k in ("station", "inverter", "combiner"):
            pass
    by_t = collections.Counter(); 
    for g, p in feats["tables"]:
        by_t[("circuit", f"{p['inverter']}-{p['combiner']}-{p['circuit']}")] += 1
        by_t[("combiner", f"{p['inverter']}-{p['combiner']}")] += 1
        by_t[("inverter", p["inverter"])] += 1
        by_t[("station", p["station"])] += 1
    for r in rows_h:
        if r["level"] in ("circuit", "combiner", "inverter", "station"):
            n = by_t[(r["level"], r["id"])]
            r.update(n_tables=n, n_strings=n * STR_PER_TABLE, n_modules=n * MOD_PER_TABLE)
    for L in ("stations", "inverters", "combiners", "circuits"):
        for g, p in feats[L]:
            lvl = p["level"]
            n = by_t[(lvl, p["id"])]
            if "n_tables" in p: p["n_tables"] = n
            if "n_modules" in p: p["n_modules"] = n * MOD_PER_TABLE
            if "n_strings" in p: p["n_strings"] = n * STR_PER_TABLE
    return feats, rows_h


if __name__ == "__main__":
    feats, rows_h, qa, disc = main()
    pickle.dump(dict(feats=feats, rows=rows_h, qa=qa, disc=disc), open(W / "cache/assembled.pkl", "wb"))
    lv = collections.Counter(r["level"] for r in rows_h)
    print(dict(lv), {k: len(v) for k, v in feats.items()})
