"""PS IM2 Bufali-Palomar I y II (Bufali, Valencia), 11.3 MWp: route A/B hybrid.

Source: PROYECTO PLANTA FV PS IM2 BUFALI-PALOMAR I Y II.pdf (GVA public consultation), drawings pp. 236-250,
123 CAD layers. General layout p. 238 (1:2,000, 0.70554 m/pt) holds the 655 structures (ND_MESAS_ESTRUCTURA,
one 15x2V structure = 30 modules = 1 string). One stringing sheet per inverter (pp. 239-244, 1:500/1:750)
colours each string box's structures (raster fills) and labels it `area.inv.n STRINGS-SBCxx`.
Order of the pipeline (run from the work dir):
  extract.py   structures, CAJA legend colours, labels, symbols per sheet
  assign.py    each inverter sheet registered onto p. 238 by structure-centre translation vote (rms 3-12 cm)
  colours2.py  structure fill colour sampled on a render of each sheet
  groups.py    same-colour connected groups -> labels (Hungarian, distance + count), leftovers merged by colour
  build_bufali.py  this file: assemble, georeference on the three printed coordinates, export
"""
import os, sys, json, pickle, collections, re, csv
from pathlib import Path
import numpy as np
import pymupdf as fitz
from shapely.geometry import Polygon, Point, LineString, MultiLineString
from shapely.ops import unary_union
from pyproj import Transformer, CRS as PCRS
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit
from pvgeo.rollup import rollup

SRC = Path(os.environ.get("BUFALI_PDF", "bufali.pdf"))
W = Path(os.environ.get("BUFALI_WORK", "."))
OUT = Path(os.environ.get("BUFALI_OUT", "out/bufali_palomar"))
KEY = 238
C = 0.70554
CRS = "EPSG:25830"                       # "Coordenadas UTM Huso 30 ETRS89" (printed)
# printed on p. 238 (rounded to the metre); sheet points = centre of the drawn symbol (displayed pt)
GCP = {"CIT01": ((665.46, 644.30), (714823.0, 4307278.0)),
       "CIT02": ((973.68, 613.76), (715042.0, 4307300.0)),
       "CEM":   ((1320.40, 562.40), (715285.0, 4307336.0))}
PRINTED = dict(structures=655, strings=655, modules=19650, wp=575, inverters=6,
               strings_per_inverter={"1.1": 109, "1.2": 108, "1.3": 93, "2.1": 102, "2.2": 130, "2.3": 113})
STATION = {1: "CIT01", 2: "CIT02"}


def main():
    d = fitz.open(SRC); p = d[KEY - 1]; m = p.rotation_matrix
    R = pickle.load(open(W / "extract.pkl", "rb")); reg = json.load(open(W / "register.json"))
    G = pickle.load(open(W / "groups.pkl", "rb"))
    fr = lambda P: (P.x * C, -P.y * C)
    # --- structures on the key sheet, as drawn quads
    quads = []
    for x in p.get_drawings():
        if x.get("layer") != "ND_MESAS_ESTRUCTURA":
            continue
        r = x["rect"]
        if not (5 < max(r.width, r.height) * 1 and 20 < max(r.width, r.height) < 30):
            continue
        pts = []
        for it in x["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "re":
                q = it[1]; pts += [q.tl, q.tr, q.br, q.bl]
            elif it[0] == "qu":
                q = it[1]; pts += [q.ul, q.ur, q.lr, q.ll]
        P = np.array([fr(pt * m) for pt in pts])
        poly = Polygon(P).convex_hull if len(P) >= 3 else None
        if poly is not None and poly.area > 20:
            quads.append(poly)
    # dedupe by centre
    cen = np.array([q.centroid.coords[0] for q in quads])
    keep, seen = [], set()
    for i, c in enumerate(cen):
        k = (round(c[0], 0), round(c[1], 0))
        if k not in seen:
            seen.add(k); keep.append(i)
    quads = [quads[i] for i in keep]; cen = cen[keep]
    # the legend's sample structure (and line samples) sit far from the plant: keep what is near the array
    nn = cKDTree(cen).query(cen, k=2)[0][:, 1]
    legend = [i for i in range(len(quads)) if nn[i] > 60]
    quads = [q for i, q in enumerate(quads) if i not in legend]; cen = np.delete(cen, legend, axis=0)
    tree = cKDTree(cen)
    lo, hi = cen.min(0) - 150, cen.max(0) + 150
    near = lambda a_: lo[0] < a_[0] < hi[0] and lo[1] < a_[1] < hi[1]
    # --- assignment from the inverter sheets
    lab = {}; conflicts = []
    for pn in range(239, 245):
        mm = fitz.Matrix(*R[pn]["rotm"]); Cs = R[pn]["main"][1]; t = np.array(reg[str(pn)]["t"])
        for i, (a, inv, sbc, n) in G[pn].items():
            r = R[pn]["structs"][i]
            c = fitz.Point((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) * mm
            xy = np.array([c.x * Cs, -c.y * Cs]) + t
            dd, j = tree.query(xy)
            if dd > 1.0:
                conflicts.append(f"p{pn} structure {i} has no key-sheet match ({dd:.1f} m)"); continue
            new = (a, inv, sbc)
            if j in lab and lab[j] != new:
                conflicts.append(f"structure {j} labelled {lab[j]} and {new}")
            lab[j] = new
    # SBC32/SBC33 print "2.1.17" but sit on the inverter 2.2 sheet; the summary table (2.2 = 130) needs them there
    notes = []
    fix = {s: (2, 2) for s in (32, 33)}
    for j, (a, inv, s) in list(lab.items()):
        if s in fix and (a, inv) != fix[s]:
            lab[j] = (*fix[s], s)
    notes.append("SBC32 and SBC33 are labelled '2.1.17' on the inverter 2.2 sheet (p. 243); the summary table needs them "
                 "in inverter 2.2 (6x16 + 2x17 = 130) and inverter 2.1 adds up to 102 without them: assigned to 2.2.")
    unl = [j for j in range(len(quads)) if j not in lab]
    # --- string boxes (cyan squares) from the sheets, named by one-to-one assignment to their group's label
    boxes = []
    for pn in range(239, 245):
        page = d[pn - 1]; mm = page.rotation_matrix; Cs = R[pn]["main"][1]; t = np.array(reg[str(pn)]["t"])
        main_r = fitz.Rect(*R[pn]["main"][0])
        sq = [x["rect"] for x in page.get_drawings() if x.get("layer") == "ND_CAJAS DE CONEXION" and x["type"] == "fs"
              and 2.5 < max(x["rect"].width, x["rect"].height) * Cs < 4.5 and (x["rect"] * mm).x1 < 1760]
        pts = []
        for r in sq:
            c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) * mm
            q = np.array([c.x * Cs, -c.y * Cs]) + t
            if not any(np.hypot(*(q - b)) < 1.0 for b in pts):
                pts.append(q)
        labels = []
        for tx, bb in R[pn]["words"]:
            g = re.match(r"\s*(\d)\.(\d)\.(\d+)\s*STRINGS-SBC(\d+)", tx)
            if g:
                c = fitz.Point((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) * mm
                labels.append((int(g[4]), np.array([c.x * Cs, -c.y * Cs]) + t))
        if not pts or not labels:
            continue
        Cm = np.array([[np.hypot(*(b - l[1])) for l in labels] for b in pts])
        ri, ci = linear_sum_assignment(Cm)
        for a_, b_ in zip(ri, ci):
            boxes.append((labels[b_][0], pts[a_], float(Cm[a_, b_]), pn))
    box_of = {}
    for s, q, dist, pn in boxes:
        if s not in box_of or dist < box_of[s][1]:
            box_of[s] = (q, dist)
    # --- features
    feats = collections.defaultdict(list); rows = []
    for a in (1, 2):
        xy = np.array(fr(fitz.Point(*GCP[STATION[a]][0])))
        feats["stations"].append((Point(xy), dict(id=STATION[a], station=STATION[a], kind="CIT 1x5,000 kVA, 3x INGECON 1600TL",
                                                    location_source="drawn symbol (p. 238)", derived=False)))
        rows.append(dict(id=STATION[a], level="station", parent="", station=STATION[a], X=xy[0], Y=xy[1],
                         location_source="drawn symbol", derived=False))
    xy = np.array(fr(fitz.Point(*GCP["CEM"][0])))
    feats["buildings"].append((Point(xy), dict(id="CEM", kind="centro de entrega y medida", derived=False)))
    by_sbc = collections.defaultdict(list)
    for j, (a, inv, s) in lab.items():
        by_sbc[(a, inv, s)].append(j)
    for (a, inv, s), js in sorted(by_sbc.items()):
        st = STATION[a]; iv = f"INV{a}.{inv}"; cb = f"SBC{s:02d}"
        js = sorted(js, key=lambda j: (-round(cen[j][1] / 4), cen[j][0]))     # rows top-down, then west-east
        if s in box_of:
            q, dist = box_of[s]
            feats["combiners"].append((Point(q), dict(id=cb, station=st, inverter=iv, combiner=cb, n_strings=len(js),
                                                       location_source="drawn box (ND_CAJAS DE CONEXION)", derived=False)))
            bx, by = q
        else:
            bx, by = unary_union([quads[j] for j in js]).representative_point().coords[0]
        rows.append(dict(id=cb, level="combiner", parent=iv, station=st, inverter=iv, combiner=cb, n_strings=len(js),
                         n_modules=30 * len(js), X=bx, Y=by, location_source="drawn box" if s in box_of else "group centre",
                         derived=s not in box_of))
        for k, j in enumerate(js, 1):
            sid = f"{cb}-S{k:02d}"
            feats["strings"].append((quads[j], dict(id=sid, station=st, inverter=iv, combiner=cb, string=sid, modules=30,
                                                     geometry="drawn structure", numbering="derived (rows top-down, W-E)",
                                                     derived=False)))
            rows.append(dict(id=sid, level="string", parent=cb, station=st, inverter=iv, combiner=cb, string=sid,
                             n_modules=30, X=cen[j][0], Y=cen[j][1], location_source="drawn structure",
                             derived="numbering"))
    for j in unl:
        feats["unassigned_structures"].append((quads[j], dict(id=f"U{j}", note="no string-box colour on any inverter sheet")))
    # inverters: no drawn position (inside the CIT skid); records point at the station, areas from rollup
    invs = sorted({(a, inv) for a, inv, _ in lab.values()})
    for a, inv in invs:
        xy = np.array(fr(fitz.Point(*GCP[STATION[a]][0])))
        rows.append(dict(id=f"INV{a}.{inv}", level="inverter", parent=STATION[a], station=STATION[a], inverter=f"INV{a}.{inv}",
                         X=xy[0], Y=xy[1], location_source="station skid (inverters are inside it)", derived=True))
    # site lines from the key sheet
    for L, role in (("ND_VALLADO", "fence"), ("ND_CARRETERAS INTERNAS", "roads"), ("ND_AREA FOTOVOLTAICA", "pv_area"),
                    ("ND_LAMT EXISTENTE", "existing_mv_line")):
        segs = []
        for x in p.get_drawings():
            if x.get("layer") != L:
                continue
            for it in x["items"]:
                if it[0] == "l":
                    a_, b_ = fr(it[1] * m), fr(it[2] * m)
                    if a_ != b_ and near(a_) and near(b_):
                        segs.append((a_, b_))
        if segs:
            feats[role].append((MultiLineString(segs), dict(id=role, layer=L)))
    der, rn = rollup({"strings": feats["strings"], "stations": feats["stations"], "combiners": feats["combiners"]})
    feats.update(der); notes += rn
    tot = dict(legend_samples_dropped=len(legend), structures=len(quads), assigned=len(lab), unassigned=len(unl), strings=len(feats["strings"]),
               modules=30 * len(feats["strings"]), combiners=len(by_sbc), combiner_boxes_drawn=len(box_of), boxes_missing=sorted(set(s for _,_,s in lab.values())-set(box_of)),
               inverters=len(invs),
               per_inverter={f"{a}.{i}": sum(1 for v in lab.values() if v[:2] == (a, i)) for a, i in invs})
    return feats, rows, tot, notes, conflicts


def export(feats, rows, tot, notes, conflicts):
    for dd in ("gis", "shp", "hierarchy", "qa", "config"):
        (OUT / dd).mkdir(parents=True, exist_ok=True)
    ids = list(GCP)
    src = np.array([[GCP[k][0][0] * C, -GCP[k][0][1] * C] for k in ids]); dst = np.array([GCP[k][1] for k in ids])
    T = fit(src, dst, "similarity", CRS, C, ids=ids)
    T.note = ("Similarity fit on the three coordinates printed on p. 238 (CIT01, CIT02, CEM; ETRS89 UTM 30N, rounded to "
              "the metre) at the centres of their drawn symbols.")
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    proj = lambda g: writers.project(g, lambda xy: np.c_[T.apply(xy[:, 0], xy[:, 1])])
    ll = lambda g: writers.project(g, lambda xy: np.c_[to_ll.transform(xy[:, 0], xy[:, 1])])
    wkt = PCRS.from_user_input(CRS).to_wkt("WKT1_ESRI")
    order = ["fence", "pv_area", "roads", "existing_mv_line", "station_areas", "inverter_areas", "combiner_areas",
             "stations", "inverters", "combiners", "buildings", "strings", "unassigned_structures"]
    kmz = {}
    for L in order:
        fs = feats.get(L, [])
        if not fs:
            continue
        pf = [(proj(g), p) for g, p in fs]; lf = [(ll(g), p) for g, p in pf]
        writers.write_geojson(OUT / f"gis/{L}.geojson", lf)
        writers.write_shapefile(OUT / f"shp/{L}.shp", pf, wkt)
        kmz[L] = lf
    for k, v in {"fence": ("ffffff00", "00000000"), "pv_area": ("ff0080ff", "00000000"), "roads": ("ff7f7f7f", "00000000"),
                 "existing_mv_line": ("ff000000", "00000000")}.items():
        writers.STYLE.setdefault(k, v)
    writers.write_kmz(OUT / "gis/bufali_palomar.kmz", kmz, "PS IM2 Bufali-Palomar I y II")
    path = {}
    order_rows = sorted(rows, key=lambda r: ["station", "inverter", "combiner", "string"].index(r["level"]))
    for r in order_rows:
        path[r["id"]] = (path.get(r["parent"], "") + " > " if r["parent"] else "") + r["id"]
    cols = ["id", "level", "parent", "path", "station", "inverter", "combiner", "string", "n_strings", "n_modules",
            "location_source", "derived", "x_frame_m", "y_frame_m", "easting", "northing", "lon", "lat"]
    with open(OUT / "hierarchy/hierarchy.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in order_rows:
            e, n_ = T.apply(r["X"], r["Y"]); lo, la = to_ll.transform(e, n_)
            o = {k: r.get(k, "") for k in cols}
            o.update(path=path[r["id"]], x_frame_m=round(r["X"], 2), y_frame_m=round(r["Y"], 2), easting=round(float(e), 2),
                     northing=round(float(n_), 2), lon=round(lo, 7), lat=round(la, 7))
            w.writerow(o)
    kids = collections.defaultdict(list)
    for r in order_rows:
        kids[r["parent"]].append(r)
    def node(r):
        e, n_ = T.apply(r["X"], r["Y"]); lo, la = to_ll.transform(e, n_)
        dct = {k: v for k, v in r.items() if k not in ("X", "Y") and v not in ("", None)}
        dct.update(lon=round(lo, 7), lat=round(la, 7))
        ch = [node(c) for c in kids.get(r["id"], [])]
        if ch:
            dct["children"] = ch
        return dct
    (OUT / "hierarchy/hierarchy.json").write_text(json.dumps(dict(site="PS IM2 Bufali-Palomar I y II", crs=CRS,
                                                                  stations=[node(r) for r in kids[""]]), indent=1))
    (OUT / "config/transform.json").write_text(T.to_json())
    with open(OUT / "config/gcps.csv", "w") as f:
        f.write("id,x_frame_m,y_frame_m,easting,northing,source\n")
        for k, s_, d_ in zip(ids, src, dst):
            f.write(f"{k},{s_[0]:.2f},{s_[1]:.2f},{d_[0]},{d_[1]},printed on p. 238 (rounded to 1 m); symbol centre\n")
    return T


if __name__ == "__main__":
    feats, rows, tot, notes, conflicts = main()
    T = export(feats, rows, tot, notes, conflicts)
    pickle.dump(dict(tot=tot, notes=notes, conflicts=conflicts, layers={k: len(v) for k, v in feats.items()},
                     T=json.loads(T.to_json()), residuals=T.residuals, rmse=T.rmse_m), open(W / "assembled.pkl", "wb"))
    print(json.dumps(tot, indent=1)); print(notes); print(conflicts[:10], len(conflicts))
    print({k: len(v) for k, v in feats.items()}); print("rmse", T.rmse_m, T.residuals, "scale", T.scale, "rot", T.rotation_deg)
