"""Route C: hierarchy from flattened sheets, by drawing style.

Some project PDFs are assembled from plots with no layers and no hierarchy
labels (e.g. PDFsam-merged execution projects). The plant is still drawn
consistently:

- each inverter block outlined in its own colour and labelled ("01", "14*");
- trackers as identical rectangles;
- inverter stations as identical filled symbols tagged "INV.xx";
- combiner boxes as symbols on another sheet (usually the grounding plan),
  one symbol style per box type (e.g. 20-input and 18-input boxes).

Objects are identified by style (type, colour, size, item count) declared in
layer_map.json. Other sheets are moved onto the key sheet by matching a symbol
style both draw (translation vote). Trackers go to blocks by containment.
Trackers go to combiner boxes by a minimum-distance assignment that respects
each box type's capacity, which comes from the string schematics. Strings are
derived: N per tracker, split along the tracker. Box numbers, the tracker
assignment and the strings are derived and flagged as such.
"""

from __future__ import annotations

import re
import statistics as st
from collections import Counter, defaultdict

import numpy as np
from shapely import STRtree
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union

from . import layermap
from .hierarchy import Feature, Issue, Result, _axes
from .labelled import labels, rows_from

def _close(a, b, tol=0.02):
    return a is not None and b is not None and len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def match_style(x: dict, s: dict) -> bool:
    if "type" in s and x.get("type") != s["type"]:
        return False
    if "color" in s and not _close(x.get("color"), s["color"]):
        return False
    if "fill" in s and not _close(x.get("fill"), s["fill"]):
        return False
    if "n_items" in s and len(x["items"]) != s["n_items"]:
        return False
    if "items" in s and not all(i[0] == s["items"] for i in x["items"]):
        return False
    if "size_pt" in s:
        w, h = x["rect"].width, x["rect"].height
        W, H = s["size_pt"]
        tol = s.get("tol", 0.3)
        ok = abs(w - W) <= tol and abs(h - H) <= tol
        if not ok and s.get("rotatable", True):
            ok = abs(w - H) <= tol and abs(h - W) <= tol
        if not ok:
            return False
    if "min_size_pt" in s and max(x["rect"].width, x["rect"].height) < s["min_size_pt"]:
        return False
    for f in s.get("exclude_fills", []):
        if _close(x.get("fill"), f) or _close(x.get("color"), f):
            return False
    if s.get("saturated_or_black"):
        import colorsys
        col = x.get("fill") or x.get("color")
        if not col or len(col) != 3:
            return False
        h, sat, v = colorsys.rgb_to_hsv(*col)
        if not (sat > 0.3 or v < 0.05):
            return False
    return True


def _geom(x: dict, as_lines: bool = False):
    """Polygon for quads/rects/closed fills, else the line work. as_lines
    returns the raw segments (outlines drawn as thick filled strokes)."""
    polys, pts, lines = [], [], []
    for it in x["items"]:
        if it[0] == "qu":
            q = it[1]
            polys.append(Polygon([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]))
        elif it[0] == "re":
            polys.append(box(*it[1]))
        elif it[0] in ("l", "c"):
            a, b = (it[1], it[2]) if it[0] == "l" else (it[1], it[4])
            lines.append(LineString([(a.x, a.y), (b.x, b.y)]))
            pts += [(a.x, a.y), (b.x, b.y)]
    if as_lines:
        return unary_union(lines + [LineString(p.exterior.coords) for p in polys]) if (lines or polys) else None
    if polys:
        return unary_union(polys)
    if "f" in (x.get("type") or "") and len(pts) >= 3:
        p = Polygon(pts)
        return p if p.is_valid else p.buffer(0)
    return unary_union(lines) if lines else None


def _translation_vote(a: list[Point], b: list[Point], tol: float = 1.0):
    """Translation t with b + t ~ a for most pairs (symbols drawn on both pages)."""
    votes = Counter()
    cand = []
    for p in a:
        for q in b:
            d = (p.x - q.x, p.y - q.y)
            cand.append(d)
            votes[(round(d[0] / tol), round(d[1] / tol))] += 1
    (kx, ky), n = votes.most_common(1)[0]
    sel = [d for d in cand if round(d[0] / tol) == kx and round(d[1] / tol) == ky]
    return (st.median(d[0] for d in sel), st.median(d[1] for d in sel)), n


def build_styles(doc, lmap: dict, with_modules: bool = False) -> Result:
    from scipy.optimize import linear_sum_assignment

    res = Result()
    naming = lmap["naming"]
    styles = lmap["styles"]
    key = int(lmap["key_page"])
    pages = sorted({int(p) for s in styles for p in (s["page"] if isinstance(s["page"], list) else [s["page"]])})
    found: dict[str, list] = defaultdict(list)       # role -> [(geom in key pt, style)]
    texts: dict[str, list] = defaultdict(list)       # role -> [(groups, bbox in key pt)]
    offsets = {key: (0.0, 0.0)}
    raw = {}
    for pn in pages:
        drs = doc[pn - 1].get_drawings()
        raw[pn] = defaultdict(list)
        for s in styles:
            if "text" in s:
                continue
            spages = s["page"] if isinstance(s["page"], list) else [s["page"]]
            if pn not in [int(v) for v in spages]:
                continue
            for x in drs:
                if match_style(x, s):
                    g = _geom(x, as_lines=s["role"] == "block_outline" or s["role"] in layermap.FEATURE_ROLES)
                    if g is not None and not g.is_empty:
                        raw[pn][s["role"]].append((g, s))
        del drs
    # register non-key pages onto the key page by a symbol both draw
    reg_role = lmap.get("register_by", "station_symbol")
    kp = [g.centroid for g, _ in raw[key].get(reg_role, [])]
    for pn in pages:
        if pn == key:
            continue
        sp = [g.centroid for g, _ in raw[pn].get(reg_role, [])]
        if kp and sp:
            t, n = _translation_vote(kp, sp)
            offsets[pn] = t
            res.issues.append(Issue("note", "page_registered",
                                    f"page {pn} -> key page {key}: shift {t[0]:+.1f}, {t[1]:+.1f} pt from "
                                    f"{n} matching '{reg_role}' symbols"))
            if n < min(3, len(kp)):
                res.issues.append(Issue("warning", "weak_registration",
                                        f"page {pn}: only {n} '{reg_role}' symbols agree on the shift"))
        else:
            offsets[pn] = (0.0, 0.0)
            res.issues.append(Issue("warning", "page_not_registered",
                                    f"page {pn}: no '{reg_role}' symbols to register with; assumed same frame"))
    for pn in pages:
        dx, dy = offsets[pn]
        for role, items in raw[pn].items():
            if pn != key and role == reg_role:
                continue
            found[role] += [(translate(g, dx, dy), s) for g, s in items]
    for s in styles:
        if "text" not in s:
            continue
        pn = int(s["page"])
        dx, dy = offsets.get(pn, (0.0, 0.0))
        for g, bb in labels(doc[pn - 1], re.compile(s.get("layer", ".*")), re.compile(s["text"])):
            texts[s["role"]].append((g, (bb[0] + dx, bb[1] + dy, bb[2] + dx, bb[3] + dy)))

    trackers = [g for g, _ in found["tracker"]]
    res.stats["trackers"] = len(trackers)
    if not trackers:
        res.issues.append(Issue("error", "no_trackers", "no object matched the tracker style"))
        return res
    tcent = [g.centroid for g in trackers]

    # ---------------- blocks: faces of outline objects holding one block label ----------------
    blabels = [(g, Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) for g, b in texts["block_label"]]
    ttree = STRtree(tcent)
    blocks = {}                                     # station -> polygon
    for g, _ in found["block_outline"]:
        segs = list(getattr(g, "geoms", [g]))
        if not segs:
            continue
        for face in polygonize(unary_union(segs)):
            inside = [(gr, p) for gr, p in blabels if face.contains(p)]
            if len(inside) != 1:
                continue
            n_tr = len(ttree.query(face, predicate="contains"))
            if n_tr < int(lmap.get("min_trackers_per_block", 10)):
                continue
            stn = inside[0][0]["station"]
            # the block outline holds all of the block's trackers; a road or
            # fence face may hold the label but only part of them, or more
            # area. Most trackers wins, then the smallest area.
            score = (n_tr, -face.area)
            if stn not in blocks or score > blocks[stn][0]:
                blocks[stn] = (score, face)
    blocks = {k: v[1] for k, v in blocks.items()}
    missing_blocks = sorted({gr["station"] for gr, _ in blabels} - set(blocks))
    if missing_blocks:
        res.issues.append(Issue("warning", "block_outline_not_found",
                                f"blocks {missing_blocks}: no outline encloses the label and its trackers"))
    bids = sorted(blocks)
    bpolys = [blocks[b] for b in bids]
    tr_block = []
    lim = 10.0 / lmap["_m_per_pt"]
    for c in tcent:
        hit = [b for b, p in zip(bids, bpolys) if p.contains(c)]
        if not hit:
            d = [(p.distance(c), b) for b, p in zip(bids, bpolys)]
            dmin, b = min(d) if d else (1e9, None)
            hit = [b] if dmin <= lim else []
        tr_block.append(hit[0] if hit else None)
    orphan_tr = sum(1 for b in tr_block if b is None)
    if orphan_tr:
        res.issues.append(Issue("warning", "trackers_outside_blocks", f"{orphan_tr} trackers in no block"))

    # expected trackers per block from the label suffix (e.g. "14*" = 162)
    exp = lmap.get("expect_trackers", {})
    suffix = {}
    for t in texts["block_label"]:
        g = t[0]
        suffix[g["station"]] = g.get("suffix", "") or ""
    per_block = Counter(b for b in tr_block if b is not None)
    for b in bids:
        want = exp.get(suffix.get(b, ""))
        if want is not None:
            if per_block[b] == want:
                res.issues.append(Issue("note", "matches_printed_total",
                                        f"block {b:02d}: {per_block[b]} trackers = {want} printed"))
            else:
                res.issues.append(Issue("warning", "differs_from_printed_total",
                                        f"block {b:02d}: {per_block[b]} trackers, {want} printed",
                                        [round(v, 1) for v in blocks[b].bounds]))

    # ---------------- combiners: to blocks, then trackers to combiners ----------------
    cbs = []
    for g, s in found["combiner"]:
        c = g.centroid
        hit = [b for b, p in zip(bids, bpolys) if p.contains(c)]
        if not hit:
            d = [(p.distance(c), b) for b, p in zip(bids, bpolys)]
            dmin, b = min(d) if d else (1e9, None)
            hit = [b] if dmin <= lim else []
        cbs.append({"pt": c, "cap": int(s.get("capacity", 0)), "type": s.get("name", ""), "block": hit[0] if hit else None})
    res.stats["combiners_found"] = len(cbs)
    nps = lmap["strings"].get("per_tracker", 2)
    mps = lmap["strings"].get("modules_per_string")
    tr_cb = [None] * len(trackers)
    cb_by_block = defaultdict(list)
    for i, c in enumerate(cbs):
        cb_by_block[c["block"]].append(i)
    if None in cb_by_block:
        res.issues.append(Issue("warning", "combiners_outside_blocks",
                                f"{len(cb_by_block[None])} combiner symbols in no block"))
    for b in bids:
        ti = [i for i, bb in enumerate(tr_block) if bb == b]
        ci = cb_by_block.get(b, [])
        if not ci:
            res.issues.append(Issue("warning", "block_without_combiners", f"block {b:02d}: no combiner symbols"))
            continue
        caps = [cbs[i]["cap"] or int(np.ceil(len(ti) / len(ci))) for i in ci]
        types = Counter(cbs[i]["type"] for i in ci)
        if sum(caps) != len(ti):
            usual = Counter(caps).most_common(1)[0][0]
            short = (len(ti) - sum(caps)) / usual
            res.issues.append(Issue("warning", "combiner_capacity_mismatch",
                                    f"block {b:02d}: {len(ti)} trackers but {len(ci)} boxes ({dict(types)}) hold "
                                    f"{sum(caps)}" + (f"; about {short:.0f} box(es) missing from the drawing"
                                                     if short > 0 else ""),
                                    [round(v, 1) for v in blocks[b].bounds]))
        slots = [k for k, cap in zip(ci, caps) for _ in range(cap)]
        # if boxes are missing, add spare capacity to the boxes so every tracker is assigned
        while len(slots) < len(ti):
            slots += ci
        D = np.array([[tcent[t].distance(cbs[k]["pt"]) for k in slots] for t in ti])
        r, c = linear_sum_assignment(D)
        for rr, cc in zip(r, c):
            tr_cb[ti[rr]] = slots[cc]

    # ---------------- assemble hierarchy ----------------
    station_pts = {}
    slabels = [(g, Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) for g, b in texts["station_label"]]
    syms = [g.centroid for g, _ in found["station_symbol"]]
    from .labelled import _greedy
    m = _greedy([p for _, p in slabels], syms, 60.0 / lmap["_m_per_pt"])
    for i, (g, p) in enumerate(slabels):
        if i in m:
            station_pts[g["station"]] = (syms[m[i]], "station_symbol")
    # number boxes in each block top-down then left-right (derived numbering)
    str_feats, cb_feats, inv_feats, st_feats, tab_feats = [], [], [], [], []
    for b in bids:
        ci = sorted(cb_by_block.get(b, []), key=lambda k: (round(cbs[k]["pt"].y / 8), cbs[k]["pt"].x))
        cb_ids = []
        for n, k in enumerate(ci, 1):
            cid = layermap.name(naming["combiner"], station=b, inv=1, cb=n)
            trs = [t for t, kk in enumerate(tr_cb) if kk == k]
            trs.sort(key=lambda t: (tcent[t].x, tcent[t].y))
            feats = []
            sn = 0
            for tn, t in enumerate(trs, 1):
                g = trackers[t]
                tid = layermap.name(naming.get("table", "T{table:05d}"), station=b, inv=1, cb=n, table=t + 1)
                tab_feats.append(Feature("tables", g, {"id": tid, "combiner": cid, "station": b,
                                                       "n_strings": nps, "derived": True}))
                u, v, lu, lv = _axes(g)
                c0 = g.centroid
                for j in range(nps):
                    sn += 1
                    off = (j + 0.5) / nps - 0.5
                    cx, cy = c0.x + v[0] * off * lv, c0.y + v[1] * off * lv
                    hw, hl = lv / nps / 2, lu / 2
                    corners = [(cx + su * hl * u[0] + sv * hw * v[0], cy + su * hl * u[1] + sv * hw * v[1])
                               for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                    sid = layermap.name(naming["string"], station=b, inv=1, cb=n, string=sn)
                    feats.append(Feature("strings", Polygon(corners), {
                        "id": sid, "level": "string", "parent": cid, "station": b, "inverter": 1, "combiner": n,
                        "string": sn, "table": tid, "n_modules": mps or 0, "derived": True}))
            cprops = {"id": cid, "level": "combiner", "station": b, "inverter": 1, "combiner": n,
                      "box_type": cbs[k]["type"], "capacity": cbs[k]["cap"], "n_trackers": len(trs),
                      "n_strings": len(feats), "n_modules": sum(f.props["n_modules"] for f in feats),
                      "derived": True, "box_x_pt": round(cbs[k]["pt"].x, 2), "box_y_pt": round(cbs[k]["pt"].y, 2)}
            if cbs[k]["cap"] and len(trs) != cbs[k]["cap"]:
                cprops["over_capacity"] = len(trs) - cbs[k]["cap"]
            area = unary_union([f.geom for f in feats]) if feats else cbs[k]["pt"].buffer(1)
            cb_feats.append(Feature("combiners", area, cprops))
            res.features["combiner_boxes"].append(Feature("combiner_boxes", cbs[k]["pt"], {
                "id": cid, "level": "combiner_box", "station": b, "box_type": cbs[k]["type"]}))
            str_feats += feats
            cb_ids.append(cid)
        iid = layermap.name(naming["inverter"], station=b, inv=1)
        mine = [f for f in cb_feats if f.props["station"] == b]
        for f in mine:
            f.props["parent"] = iid
        inv_feats.append(Feature("inverters", blocks[b], {
            "id": iid, "level": "inverter", "station": b, "inverter": 1, "n_combiners": len(mine),
            "n_trackers": per_block[b], "n_strings": sum(f.props["n_strings"] for f in mine),
            "n_modules": sum(f.props["n_modules"] for f in mine)}))
        sid = layermap.name(naming["station"], station=b)
        inv_feats[-1].props["parent"] = sid
        pt, src = station_pts.get(b, (blocks[b].centroid, "block_centroid"))
        if src == "block_centroid":
            res.issues.append(Issue("warning", "station_location_fallback", f"{sid}: no INV tag/symbol found"))
        st_feats.append(Feature("stations", pt, {
            "id": sid, "level": "station", "station": b, "location_source": src, "n_inverters": 1,
            "n_combiners": len(mine), "n_strings": inv_feats[-1].props["n_strings"],
            "n_modules": inv_feats[-1].props["n_modules"]}))

    site = defaultdict(list)
    for role in layermap.FEATURE_ROLES:
        for g, _ in found.get(role, []):
            site[role].append(g)
    res.features["site"] = [Feature("site", unary_union(gs), {"role": r}) for r, gs in site.items() if gs]
    res.features["stations"] = st_feats
    res.features["inverters"] = inv_feats
    res.features["combiners"] = cb_feats
    res.features["strings"] = str_feats
    res.features["tables"] = tab_feats
    res.issues.append(Issue("note", "derived_levels",
                            f"read from the drawing: blocks, trackers, stations, combiner box positions and types. "
                            f"Derived: box numbering (top-down, left-right), tracker-to-box assignment (minimum "
                            f"distance within box capacity), {nps} strings per tracker split along its length"
                            + (f", {mps} modules per string from the schematics" if mps else "")))
    res.stats["modules_per_string"] = mps
    res.stats.update({"stations": len(st_feats), "inverters": len(inv_feats), "combiners": len(cb_feats),
                      "strings": len(str_feats), "tables": len(tab_feats),
                      "modules": sum(f.props["n_modules"] for f in str_feats), "pages": pages})
    res.rows = rows_from(res)
    return res
