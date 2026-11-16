"""Hierarchy from labelled stringing sheets (PVcase-style multi-sheet packages).

Design tools such as PVcase print the electrical hierarchy as text: a label
per string (`14-2-3` = inverter 14, combiner 2, string 3) at the end of its
wiring polyline, and a label per combiner box (`DCB 14-2`). Here the hierarchy
is read, not derived:

- string labels are matched one-to-one to the nearest string polyline;
- modules go to the nearest string polyline (the wiring runs over them);
- combiner labels are matched to the nearest combiner-box symbol;
- each station is the inverter symbol that the combiner home-run cables
  converge on.

Every sheet is moved into the key sheet's frame with register.json, so all
sheets end up in one map. Labels are read with their own character boxes,
so labels the PDF merged into one text run are split correctly.
"""

from __future__ import annotations

import re
import statistics as st
from collections import Counter, defaultdict

from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.ops import unary_union

from . import layermap
from .hierarchy import Feature, Issue, Result, _axes
from .layermap import FEATURE_ROLES
from .vector import Obj


def sheet_to_key(reg: dict, page: int) -> list[float]:
    """Affine parameters [a, b, d, e, xoff, yoff] from sheet pt to key pt."""
    s = reg["sheets"][str(page)]
    kk, ck = reg["key"]["m_per_pt"], reg["key"]["clip"]
    ks, cs = s["m_per_pt"], s["clip"]
    ox, oy = s["offset_m"]
    a = ks / kk
    return [a, 0, 0, a, ck[0] + (ox - cs[0] * ks) / kk, ck[1] + (oy - cs[1] * ks) / kk]


def labels(page, layer_rx: re.Pattern, text_rx: re.Pattern) -> list[tuple[dict, tuple]]:
    """(groups, bbox) for every regex match in text on matching layers, using
    character boxes so merged text runs split into separate labels."""
    out = []
    for t in page.get_texttrace():
        if not layer_rx.search(t.get("layer") or ""):
            continue
        chars = t["chars"]
        text = "".join(chr(c[0]) for c in chars)
        for m in text_rx.finditer(text):
            cb = [chars[i][3] for i in range(m.start(), m.end()) if chars[i][3]]
            if not cb:
                continue
            bb = (min(b[0] for b in cb), min(b[1] for b in cb), max(b[2] for b in cb), max(b[3] for b in cb))
            g = {k: (int(v) if v.isdigit() else v) for k, v in m.groupdict().items() if v is not None}
            out.append((g, bb))
    return out


def _greedy(points, geoms, max_d):
    """One-to-one nearest assignment, closest pairs first."""
    if not points or not geoms:
        return {}
    tree = STRtree(geoms)
    pairs = []
    for i, p in enumerate(points):
        for j in tree.query(p.buffer(max_d)):
            pairs.append((geoms[j].distance(p), i, int(j)))
    pairs.sort()
    used_p, used_g, out = set(), set(), {}
    for dist, i, j in pairs:
        if dist <= max_d and i not in used_p and j not in used_g:
            out[i] = j
            used_p.add(i)
            used_g.add(j)
    return out


def _objs(page) -> list[Obj]:
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        out.append(Obj(layer=d.get("layer") or "", kind=d.get("type") or "", rect=(r.x0, r.y0, r.x1, r.y1),
                       items=d["items"], fill=d.get("fill"), color=d.get("color"),
                       width=d.get("width") or 0.0, closed=bool(d.get("closePath"))))
    return out


def build_multi(doc, reg: dict, lmap: dict, with_modules: bool = False) -> Result:
    res = Result()
    naming = lmap["naming"]
    rules = lmap["roles"]
    text_rules = {r["role"]: (re.compile(r["pattern"]), re.compile(r["text"])) for r in rules if r.get("text")}
    if "string_label" not in text_rules:
        res.issues.append(Issue("error", "no_string_labels", "layer_map needs a string_label rule with a text regex"))
        return res
    geo_rules = [r for r in rules if not r.get("text")]
    kk = reg["key"]["m_per_pt"]

    strings: dict[str, dict] = {}            # id -> {groups, geom, label_pt, page, modules}
    boxes: dict[str, dict] = {}              # combiner id -> {point, page}
    station_pts: dict = {}
    site: dict = defaultdict(list)
    mod_counts_unassigned = 0
    pages_seen = []

    for pstr in sorted(reg["sheets"], key=int):
        pn = int(pstr)
        page = doc[pn - 1]
        A = sheet_to_key(reg, pn)
        ks = reg["sheets"][pstr]["m_per_pt"]
        clip = reg["sheets"][pstr]["clip"]
        inside = box(*clip)
        objs = [o for o in _objs(page) if inside.intersects(box(*o.rect))]
        roles = {layer: layermap.classify(layer, geo_rules) for layer in {o.layer for o in objs}}
        by_role = defaultdict(list)
        for o in objs:
            if roles[o.layer][0]:
                by_role[roles[o.layer][0]].append(o)
        pages_seen.append(pn)

        # strings
        sgeoms, sobj = [], []
        for o in by_role.get("string", []):
            ls = [l for l in o.lines() if l.length > 0]
            if ls:
                sgeoms.append(MultiLineString(ls) if len(ls) > 1 else ls[0])
        slabels = labels(page, *text_rules["string_label"])
        pts = [Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, b in slabels]
        match = _greedy(pts, sgeoms, 3.0 / ks)          # within 3 m of the polyline
        matched_geoms = {}
        for i, (g, bb) in enumerate(slabels):
            sid_key = (g.get("station"), g.get("inv", 1), g.get("cb"), g.get("string"))
            sid = layermap.name(naming["string"], station=sid_key[0], inv=sid_key[1], cb=sid_key[2],
                                string=sid_key[3])
            if sid in strings:
                d = Point(*affine_transform(pts[i], A).coords[0]).distance(strings[sid]["label"])
                if d * kk > 5:
                    res.issues.append(Issue("warning", "string_label_conflict",
                                            f"{sid} labelled on page {strings[sid]['page']} and page {pn} "
                                            f"{d * kk:.0f} m apart (registration or a duplicate label)"))
                continue
            j = match.get(i)
            strings[sid] = {"key": sid_key, "page": pn, "label": affine_transform(pts[i], A),
                            "line": affine_transform(sgeoms[j], A) if j is not None else None,
                            "mods": []}
            if j is not None:
                matched_geoms[j] = sid
            else:
                res.issues.append(Issue("warning", "string_without_polyline",
                                        f"{sid} (page {pn}): no string wiring within 3 m of its label",
                                        [round(v, 1) for v in affine_transform(box(*bb), A).bounds]))
        # A string can be drawn as several polylines (wiring zigzag plus return
        # conductor). Attach each unlabelled polyline to the labelled string it
        # runs alongside: the one covering most of its length within a third of
        # a module width.
        mpolys = [p for o in by_role.get("module", []) for p in o.polygons()]
        if mpolys:
            med_area = st.median(p.area for p in mpolys)
            mpolys = [p for p in mpolys if 0.5 * med_area < p.area < 2 * med_area]
        mod_w = st.median(_axes(p)[3] for p in mpolys[:500]) if mpolys else 1.0 / ks
        owner = dict(matched_geoms)                      # geom index -> string id
        orphans = [k for k in range(len(sgeoms)) if k not in owner and sgeoms[k].length > 0]
        if orphans and owner:
            lab_idx = list(owner)
            ltree = STRtree([sgeoms[k] for k in lab_idx])
            tol = mod_w / 3
            for k in orphans:
                g = sgeoms[k]
                best, best_len = None, 0.0
                for j in ltree.query(g.buffer(tol)):
                    h = sgeoms[lab_idx[j]]
                    if g.length == 0 or h.length == 0:
                        continue
                    # share of either line that runs along the other (one is often
                    # a short return conductor inside the string's full run)
                    frac = max(g.intersection(h.buffer(tol)).length / g.length,
                               h.intersection(g.buffer(tol)).length / h.length)
                    if frac > best_len:
                        best, best_len = lab_idx[j], frac
                if best is not None and best_len > 0.5:
                    owner[k] = owner[best]
        unowned = [k for k in range(len(sgeoms)) if k not in owner and sgeoms[k].length > 0]
        if unowned:
            res.issues.append(Issue("warning", "string_polyline_without_label",
                                    f"page {pn}: {len(unowned)} string polylines belong to no labelled string",
                                    [round(v, 1) for v in affine_transform(
                                        unary_union([sgeoms[k] for k in unowned]).envelope, A).bounds]))

        # modules -> string of the nearest string polyline
        if mpolys and owner:
            idx = list(owner)
            tree = STRtree([sgeoms[k] for k in idx])
            lim = 0.6 * mod_w
            for p in mpolys:
                c = p.centroid
                k = idx[int(tree.nearest(c))]
                if sgeoms[k].distance(c) <= lim:
                    strings[owner[k]]["mods"].append(affine_transform(p, A))
                else:
                    mod_counts_unassigned += 1

        # combiner boxes
        if "combiner_label" in text_rules:
            clabels = labels(page, *text_rules["combiner_label"])
            bgeoms = [p for o in by_role.get("combiner", []) for p in (o.polygons() or [box(*o.rect)])]
            bgeoms = [g for g in bgeoms if g.area > 0]
            cpts = [Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, b in clabels]
            cm = _greedy(cpts, bgeoms, 6.0 / ks)
            for i, (g, bb) in enumerate(clabels):
                cid = layermap.name(naming["combiner"], station=g.get("station"), inv=g.get("inv", 1), cb=g.get("cb"))
                if cid in boxes:
                    continue
                j = cm.get(i)
                pt = bgeoms[j].centroid if j is not None else cpts[i]
                boxes[cid] = {"point": affine_transform(pt, A), "page": pn,
                              "source": "box_symbol" if j is not None else "label"}

        # station: inverter symbol blob where home-run cables converge
        inv_objs = by_role.get("inverter", [])
        sts = Counter(g.get("station") for g, _ in slabels)
        if inv_objs and sts:
            st_no = sts.most_common(1)[0][0]
            u = unary_union([box(*o.rect).buffer(1.0 / ks) for o in inv_objs])
            blobs = [b for b in getattr(u, "geoms", [u]) if b.area > (3.0 / ks) ** 2]
            hr = [Point(c) for o in by_role.get("homerun_cable", []) for l in o.lines() for c in l.coords]
            if blobs:
                if hr:
                    score = [sum(1 for p in hr if b.distance(p) < 2.0 / ks) for b in blobs]
                    b = blobs[max(range(len(blobs)), key=lambda i: score[i])]
                    src = "inverter_symbol"
                else:
                    cen = unary_union([strings[s]["label"] for s in strings if strings[s]["page"] == pn]).centroid
                    b = min(blobs, key=lambda b: affine_transform(b, A).distance(cen))
                    src = "inverter_symbol_nearest"
                if st_no not in station_pts:
                    station_pts[st_no] = (affine_transform(b.centroid, A), src, pn)

        # site features, in key frame
        for o in objs:
            role = roles[o.layer][0]
            if role in FEATURE_ROLES:
                polys = o.polygons()
                geoms = polys if polys else [l for l in o.lines() if l.length > 0]
                site[role] += [affine_transform(g, A) for g in geoms]

    # ---------------- assemble ----------------
    if mod_counts_unassigned:
        res.issues.append(Issue("note", "modules_unassigned",
                                f"{mod_counts_unassigned} module outlines are not on any labelled string"))
    nmods = Counter(len(s["mods"]) for s in strings.values() if s["mods"])
    usual = nmods.most_common(1)[0][0] if nmods else None
    res.stats["modules_per_string"] = usual
    by_cb = defaultdict(list)
    for sid, s in strings.items():
        by_cb[s["key"][:3]].append(sid)
    string_feats, cb_feats, inv_children = [], [], defaultdict(list)
    for (station, inv, cb), sids in sorted(by_cb.items(), key=lambda z: tuple(-1 if v is None else v for v in z[0])):
        cid = layermap.name(naming["combiner"], station=station, inv=inv, cb=cb)
        feats = []
        for sid in sorted(sids, key=lambda s: strings[s]["key"][3] or 0):
            s = strings[sid]
            if s["mods"]:
                geom = unary_union(s["mods"]).minimum_rotated_rectangle
            elif s["line"] is not None:
                geom = s["line"].buffer(0.5 / kk).minimum_rotated_rectangle
            else:
                geom = s["label"].buffer(0.5 / kk)
            props = {"id": sid, "level": "string", "parent": cid, "station": station, "inverter": inv,
                     "combiner": cb, "string": s["key"][3], "n_modules": len(s["mods"]),
                     "derived": False, "sheet_page": s["page"]}
            if usual and s["mods"] and len(s["mods"]) != usual:
                props["partial"] = True
                res.issues.append(Issue("note", "string_module_count",
                                        f"{sid}: {len(s['mods'])} modules (most strings have {usual})",
                                        [round(v, 1) for v in geom.bounds]))
            feats.append(Feature("strings", geom, props))
            if with_modules:
                for m in s["mods"]:
                    res.features["modules"].append(Feature("modules", m, {"string": sid, "combiner": cid}))
        cgeom = unary_union([f.geom for f in feats])
        bx = boxes.get(cid)
        cprops = {"id": cid, "level": "combiner", "station": station, "inverter": inv, "combiner": cb,
                  "n_strings": len(feats), "n_modules": sum(f.props["n_modules"] for f in feats)}
        if bx:
            cprops["box_x_pt"], cprops["box_y_pt"] = round(bx["point"].x, 2), round(bx["point"].y, 2)
            res.features["combiner_boxes"].append(Feature("combiner_boxes", bx["point"], {
                "id": cid, "level": "combiner_box", "station": station, "combiner": cb, "source": bx["source"]}))
        else:
            res.issues.append(Issue("warning", "combiner_box_not_found", f"{cid}: no combiner label/box found"))
        cf = Feature("combiners", cgeom, cprops)
        cb_feats.append(cf)
        string_feats += feats
        inv_children[(station, inv)].append(cf)
    for cid in set(boxes) - {f.props["id"] for f in cb_feats}:
        res.issues.append(Issue("warning", "combiner_without_strings", f"{cid}: box labelled but no strings"))

    inv_feats, st_feats = [], []
    by_station = defaultdict(list)
    for (station, inv), cbs in sorted(inv_children.items(), key=lambda z: tuple(-1 if v is None else v for v in z[0])):
        iid = layermap.name(naming["inverter"], station=station, inv=inv)
        for c in cbs:
            c.props["parent"] = iid
        f = Feature("inverters", unary_union([c.geom for c in cbs]), {
            "id": iid, "level": "inverter", "station": station, "inverter": inv, "n_combiners": len(cbs),
            "n_strings": sum(c.props["n_strings"] for c in cbs), "n_modules": sum(c.props["n_modules"] for c in cbs)})
        inv_feats.append(f)
        by_station[station].append(f)
    for station, invs in sorted(by_station.items()):
        sid = layermap.name(naming["station"], station=station)
        if station in station_pts:
            pt, src, pn = station_pts[station]
        else:
            pt, src = unary_union([f.geom for f in invs]).centroid, "array_centroid"
            res.issues.append(Issue("warning", "station_location_fallback",
                                    f"{sid}: no inverter symbol found; placed at the array centroid"))
        for f in invs:
            f.props["parent"] = sid
        st_feats.append(Feature("stations", pt, {
            "id": sid, "level": "station", "station": station, "location_source": src,
            "n_inverters": len(invs), "n_combiners": sum(f.props["n_combiners"] for f in invs),
            "n_strings": sum(f.props["n_strings"] for f in invs), "n_modules": sum(f.props["n_modules"] for f in invs)}))

    # numbering gaps (combiners per inverter, strings per combiner)
    for (station, inv), cbs in inv_children.items():
        nums = sorted(c.props["combiner"] for c in cbs if isinstance(c.props["combiner"], int))
        miss = sorted(set(range(1, nums[-1] + 1)) - set(nums)) if nums else []
        if miss:
            res.issues.append(Issue("warning", "combiner_numbering_gap",
                                    f"inverter {station}-{inv}: combiners {miss} have no strings"))
    for (station, inv, cb), sids in by_cb.items():
        nums = sorted(strings[s]["key"][3] for s in sids if isinstance(strings[s]["key"][3], int))
        miss = sorted(set(range(1, nums[-1] + 1)) - set(nums)) if nums else []
        if miss:
            res.issues.append(Issue("warning", "string_numbering_gap",
                                    f"combiner {station}-{cb}: strings {miss} not found"))

    site_feats = []
    for role, geoms in site.items():
        polys = [g for g in geoms if g.geom_type == "Polygon"]
        lines = [g for g in geoms if g.geom_type != "Polygon"]
        if polys:
            site_feats.append(Feature("site", unary_union([p.buffer(0) for p in polys]), {"role": role}))
        if lines:
            site_feats.append(Feature("site", unary_union(lines), {"role": role}))

    res.features["stations"] = st_feats
    res.features["inverters"] = inv_feats
    res.features["combiners"] = cb_feats
    res.features["strings"] = string_feats
    res.features["site"] = site_feats
    res.stats.update({"pages": pages_seen, "stations": len(st_feats), "inverters": len(inv_feats),
                      "combiners": len(cb_feats), "strings": len(string_feats),
                      "modules": sum(f.props["n_modules"] for f in string_feats)})
    # cross-check against totals printed on the key sheet (PVcase data block)
    text = " ".join(doc[reg["key_page"] - 1].get_text().split())
    for label, rx, got in (("modules", r"Total No\.? of Modules:?\s*([\d.,]+)", res.stats["modules"]),
                           ("inverters", r"Total No\.? of Inverters:?\s*([\d.,]+)", len(inv_feats))):
        m = re.search(rx, text, re.I)
        if m:
            want = int(re.sub(r"[.,]", "", m.group(1)))
            res.stats[f"printed_{label}"] = want
            if want == got:
                res.issues.append(Issue("note", "matches_printed_total",
                                        f"{label}: {got} extracted = {want} printed on page {reg['key_page']}"))
            else:
                res.issues.append(Issue("warning", "differs_from_printed_total",
                                        f"{label}: {got} extracted, {want} printed on page {reg['key_page']}"))
    res.rows = rows_from(res)
    return res


def role_geoms(doc, reg: dict, lmap: dict, role: str) -> list:
    """All geometries of one role from every registered sheet, in key pt."""
    geo_rules = [r for r in lmap["roles"] if not r.get("text")]
    out = []
    for pstr in reg["sheets"]:
        pn = int(pstr)
        A = sheet_to_key(reg, pn)
        clip = box(*reg["sheets"][pstr]["clip"])
        for o in _objs(doc[pn - 1]):
            if layermap.classify(o.layer, geo_rules)[0] != role or not clip.intersects(box(*o.rect)):
                continue
            polys = o.polygons()
            geoms = [p.buffer(0) for p in polys] if polys else [l for l in o.lines() if l.length > 0]
            out += [affine_transform(g, A) for g in geoms if not g.is_empty]
    return out


def rows_from(res: Result) -> list[dict]:
    """Depth-first hierarchy rows (station > inverter > combiner > string)."""
    kids = defaultdict(list)
    for lay in ("inverters", "combiners", "strings"):
        for f in res.features[lay]:
            kids[f.props.get("parent")].append(f)
    rows = []

    def walk(f, path):
        p = path + [f.props["id"]]
        c = f.geom.centroid
        row = {k: v for k, v in f.props.items() if not k.endswith("_pt")}
        row.update({"path": " > ".join(p), "x_pt": round(c.x, 2), "y_pt": round(c.y, 2)})
        row.setdefault("parent", path[-1] if path else None)
        rows.append(row)
        for ch in kids.get(f.props["id"], []):
            walk(ch, p)

    for f in res.features["stations"]:
        walk(f, [])
    return rows
