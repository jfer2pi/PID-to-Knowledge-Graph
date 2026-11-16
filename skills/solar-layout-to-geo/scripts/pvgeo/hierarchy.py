"""Build the PV hierarchy from layer-classified vector objects.

    station > inverter > combiner > string  (> table > module)

Modules come from module layers whose names carry station/inverter/combiner
numbers (the usual way CAD teams colour an array by combiner). Tables come
from table layers; modules are assigned to the table that contains them.
Strings are not drawn on layout sheets: they are derived by chunking each
table's modules, row by row, into runs of `modules_per_string`. That ordering
is geometric, not the as-built string schedule, so string ids are flagged as
derived.

All geometry here is in sheet points (y down). Conversion to metres and to a
real CRS happens later.
"""

from __future__ import annotations

import json
import math
import re
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from shapely import STRtree
from shapely.geometry import MultiPolygon, Point, box
from shapely.ops import linemerge, unary_union

from . import layermap
from .layermap import FEATURE_ROLES


@dataclass
class Issue:
    severity: str            # error | warning | note
    code: str
    message: str
    bbox_pt: list[float] | None = None


@dataclass
class Feature:
    layer: str               # output layer: stations, inverters, combiners, strings, tables, modules, site
    geom: object             # shapely geometry, sheet points
    props: dict


@dataclass
class Result:
    features: dict[str, list[Feature]] = field(default_factory=lambda: defaultdict(list))
    rows: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    suggested_reassign: list[dict] = field(default_factory=list)


def _axes(poly):
    """Unit vectors (u along the long side, v along the short side), u pointing
    right and v pointing down the sheet, plus the side lengths."""
    mrr = poly.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    (u, lu), (v, lv) = ((e1, l1), (e2, l2)) if l1 >= l2 else ((e2, l2), (e1, l1))
    u = (u[0] / lu, u[1] / lu) if lu else (1.0, 0.0)
    v = (v[0] / lv, v[1] / lv) if lv else (0.0, 1.0)
    if u[0] < 0 or (abs(u[0]) < 1e-9 and u[1] < 0):
        u = (-u[0], -u[1])
    if v[1] < 0 or (abs(v[1]) < 1e-9 and v[0] < 0):
        v = (-v[0], -v[1])
    return u, v, lu, lv


def _bbox(g) -> list[float]:
    return [round(v, 1) for v in g.bounds]


def _cluster_by_gap(vals: list[float], gap: float) -> list[int]:
    """Index of the 1-D cluster each value falls in (clusters split at gaps > gap)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    lab = [0] * len(vals)
    k = 0
    for j, i in enumerate(order):
        if j and vals[i] - vals[order[j - 1]] > gap:
            k += 1
        lab[i] = k
    return lab


def _words(rects: list[tuple], pad: float):
    """Merge glyph boxes into word boxes."""
    if not rects:
        return []
    u = unary_union([box(*r).buffer(pad) for r in rects])
    return [g.buffer(-pad).envelope.bounds if g.area else g.bounds for g in getattr(u, "geoms", [u])]


def build(objs, spans, lmap: dict, page_size: tuple[float, float], with_modules: bool = False) -> Result:
    res = Result()
    rules = lmap["roles"]
    naming = lmap["naming"]
    roles: dict[str, tuple[str | None, dict]] = {}
    for layer in {o.layer for o in objs}:
        roles[layer] = layermap.classify(layer, rules)
    res.stats["layers_by_role"] = dict(Counter(r for r, _ in roles.values() if r))

    # manual reassignment of modules drawn on the wrong layer
    W, H = page_size
    reassign = []
    for r in lmap.get("reassign", []):
        x0, y0, x1, y1 = r["bbox_norm"]
        reassign.append((re.compile(r["layer_pattern"]), box(x0 * W, y0 * H, x1 * W, y1 * H),
                         (r["to"].get("station"), r["to"].get("inv"), r["to"].get("cb")), [0]))

    # ---------------- modules ----------------
    seen: dict[tuple, int] = {}
    mods_poly, mods_key = [], []
    dup_by_layer: Counter = Counter()
    for o in objs:
        role, g = roles[o.layer]
        if role != "module":
            continue
        key = (g.get("station"), g.get("inv"), g.get("cb"))
        rules_here = [r for r in reassign if r[0].search(o.layer)]
        for p in o.polygons():
            c = p.centroid
            k = (round(c.x, 1), round(c.y, 1))
            if k in seen:
                dup_by_layer[o.layer] += 1
                continue
            seen[k] = len(mods_poly)
            mods_poly.append(p)
            kk = key
            for pat, area, to, n in rules_here:
                if area.contains(c):
                    kk = to
                    n[0] += 1
                    break
            mods_key.append(kk)
    for pat, _, to, n in reassign:
        res.issues.append(Issue("note" if n[0] else "warning", "reassigned_modules",
                                f"reassign rule {pat.pattern} -> {to}: {n[0]} modules moved"))
    for layer, n in dup_by_layer.items():
        res.issues.append(Issue("warning", "duplicate_modules",
                                f"{layer}: {n} module outlines drawn twice (kept once)"))
    if not mods_poly:
        res.issues.append(Issue("error", "no_modules", "no module layer matched; edit layer_map.json"))
        return res
    res.stats["modules"] = len(mods_poly)
    ax = [_axes(p) for p in mods_poly[:: max(1, len(mods_poly) // 2000)]]
    mod_long = st.median(a[2] for a in ax)
    mod_short = st.median(a[3] for a in ax)
    res.stats["module_size_pt"] = [round(mod_long, 3), round(mod_short, 3)]

    # ---------------- tables ----------------
    tpolys = []
    for o in objs:
        if roles[o.layer][0] == "table":
            tpolys.extend((p, o.layer) for p in o.polygons())
    if tpolys:
        med = st.median(p.area for p, _ in tpolys)
        tseen, tables = set(), []
        for p, layer in tpolys:
            k = (round(p.centroid.x, 1), round(p.centroid.y, 1))
            if p.area < 0.25 * med or k in tseen:
                continue
            tseen.add(k)
            tables.append((p, layer))
    else:
        tables = []
        res.issues.append(Issue("note", "no_table_layer",
                                "no table layer: tables reconstructed from touching modules"))

    centroids = [p.centroid for p in mods_poly]
    mod_table = [-1] * len(mods_poly)
    if tables:
        tree = STRtree([p for p, _ in tables])
        mi, ti = tree.query(centroids, predicate="intersects")
        for m, t in zip(mi.tolist(), ti.tolist()):
            if mod_table[m] < 0:
                mod_table[m] = t
    orphans = [i for i, t in enumerate(mod_table) if t < 0]
    if orphans:
        pad = 0.3 * mod_short
        u = unary_union([mods_poly[i].buffer(pad) for i in orphans])
        blobs = list(getattr(u, "geoms", [u]))
        btree = STRtree(blobs)
        bi = btree.query([centroids[i] for i in orphans], predicate="intersects")
        base = len(tables)
        for b in blobs:
            tables.append((b.buffer(-pad), "(reconstructed)"))
        for m_local, b in zip(bi[0].tolist(), bi[1].tolist()):
            mod_table[orphans[m_local]] = base + b
        if tpolys:
            res.issues.append(Issue("warning", "modules_outside_tables",
                                    f"{len(orphans)} modules lie outside every table outline; "
                                    f"grouped into {len(blobs)} reconstructed tables",
                                    _bbox(unary_union([mods_poly[i] for i in orphans]).envelope)))
    res.stats["tables"] = len(tables)

    # ---------------- strings ----------------
    groups: dict[tuple, list[int]] = defaultdict(list)          # (combiner key, table) -> modules
    for i, (k, t) in enumerate(zip(mods_key, mod_table)):
        groups[(k, t)].append(i)
    ordered: dict[tuple, list[list[int]]] = {}                  # group -> module rows, each ordered
    row_lengths: Counter = Counter()
    for gk, idx in groups.items():
        u, v, _, _ = _axes(tables[gk[1]][0])
        a = [centroids[i].x * u[0] + centroids[i].y * u[1] for i in idx]
        b = [centroids[i].x * v[0] + centroids[i].y * v[1] for i in idx]
        lab = _cluster_by_gap(b, 0.5 * mod_short)
        rows = defaultdict(list)
        for j, l in enumerate(lab):
            rows[l].append(j)
        mrows = [[idx[j] for j in sorted(rows[l], key=lambda j: a[j])] for l in sorted(rows)]
        ordered[gk] = mrows
        row_lengths.update(len(r) for r in mrows)

    nps = lmap["strings"].get("modules_per_string", "auto")
    if nps in (None, "auto"):
        nps = row_lengths.most_common(1)[0][0]
        res.issues.append(Issue("note", "modules_per_string_inferred",
                                f"modules per string inferred as {nps} (most common module-row length); "
                                "set strings.modules_per_string in layer_map.json if the string schedule differs"))
    nps = int(nps)
    res.stats["modules_per_string"] = nps

    # ---------------- combiners -> inverters -> stations ----------------
    by_cb: dict[tuple, list[tuple]] = defaultdict(list)
    for gk in ordered:
        by_cb[gk[0]].append(gk)
    table_cbs: dict[int, set] = defaultdict(set)
    for (k, t) in ordered:
        table_cbs[t].add(k)
    shared = [t for t, ks in table_cbs.items() if len(ks) > 1]
    if shared:
        res.issues.append(Issue("warning", "table_shared_by_combiners",
                                f"{len(shared)} tables hold modules of more than one combiner",
                                _bbox(unary_union([tables[t][0] for t in shared]).envelope)))
    empty_tables = [t for t in range(len(tables)) if t not in table_cbs]
    if empty_tables:
        res.issues.append(Issue("warning", "tables_without_modules",
                                f"{len(empty_tables)} table outlines contain no module from any module layer "
                                "(modules on an unmapped layer, or tables not populated)",
                                _bbox(unary_union([tables[t][0] for t in empty_tables]).envelope)))

    cb_mod_counts = Counter()
    for k, gks in by_cb.items():
        cb_mod_counts[k] = sum(len(m) for gk in gks for m in ordered[gk])
    modal_cb = Counter(cb_mod_counts.values()).most_common(1)[0][0]

    string_feats, cb_feats, table_feats = [], [], []
    split_cbs: list[tuple] = []
    inv_children: dict[tuple, list] = defaultdict(list)
    table_ids = {}
    for t, (p, layer) in enumerate(tables):
        table_ids[t] = layermap.name(naming["table"], table=t + 1)

    for k in sorted(by_cb, key=lambda k: tuple(-1 if v is None else v for v in k)):
        station, inv, cb = k
        has_ids = station is not None and inv is not None
        cb_id = (layermap.name(naming["combiner"], station=station, inv=inv, cb=cb)
                 if has_ids and cb is not None else f"UNASSIGNED-{len(cb_feats) + 1}")
        gks = by_cb[k]
        # order tables: by table-row band (top-down), then left to right
        tcent = {gk: tables[gk[1]][0].centroid for gk in gks}
        tshort = st.median(_axes(tables[gk[1]][0])[3] for gk in gks)
        band = _cluster_by_gap([tcent[gk].y for gk in gks], 0.6 * tshort)
        gks = [gk for _, gk in sorted(zip(band, gks), key=lambda z: (z[0], tcent[z[1]].x))]
        sn = 0
        cb_strings = []
        for gk in gks:
            seq = [i for row in ordered[gk] for i in row]
            for s0 in range(0, len(seq), nps):
                chunk = seq[s0:s0 + nps]
                sn += 1
                s_id = (layermap.name(naming["string"], station=station, inv=inv, cb=cb, string=sn)
                        if has_ids and cb is not None else f"{cb_id}-S{sn:02d}")
                geom = unary_union([mods_poly[i] for i in chunk]).minimum_rotated_rectangle
                props = {"id": s_id, "level": "string", "parent": cb_id, "station": station,
                         "inverter": inv, "combiner": cb, "string": sn, "table": table_ids[gk[1]],
                         "n_modules": len(chunk), "derived": True}
                if len(chunk) != nps:
                    props["partial"] = True
                    res.issues.append(Issue("warning", "partial_string",
                                            f"{s_id}: {len(chunk)} modules (expected {nps})", _bbox(geom)))
                cb_strings.append(Feature("strings", geom, props))
                if with_modules:
                    for j, i in enumerate(chunk, 1):
                        res.features["modules"].append(Feature("modules", mods_poly[i], {
                            "string": s_id, "combiner": cb_id, "position": j, "table": table_ids[gk[1]]}))
        cgeom = unary_union([f.geom for f in cb_strings])
        n_mod = cb_mod_counts[k]
        cprops = {"id": cb_id, "level": "combiner", "station": station, "inverter": inv, "combiner": cb,
                  "n_strings": len(cb_strings), "n_tables": len(gks), "n_modules": n_mod,
                  "label_x_pt": round(cgeom.centroid.x, 2), "label_y_pt": round(cgeom.centroid.y, 2)}
        if n_mod != modal_cb:
            res.issues.append(Issue("note", "combiner_size_differs",
                                    f"{cb_id}: {n_mod} modules (most combiners have {modal_cb})", _bbox(cgeom)))
        parts = unary_union([tables[gk[1]][0].buffer(3 * tshort) for gk in gks])
        n_parts = len(getattr(parts, "geoms", [parts]))
        if n_parts > 1:
            cprops["n_parts"] = n_parts
            split_cbs.append((cb_id, k, n_parts, _bbox(cgeom)))
        f = Feature("combiners", cgeom, cprops)
        cb_feats.append(f)
        string_feats.extend(cb_strings)
        inv_children[(station, inv)].append(f)
        for gk in gks:
            p, layer = tables[gk[1]]
            table_feats.append(Feature("tables", p, {
                "id": table_ids[gk[1]], "combiner": cb_id, "source_layer": layer,
                "n_modules": sum(len(r) for r in ordered[gk]), "module_rows": len(ordered[gk])}))
    for t in empty_tables:
        p, layer = tables[t]
        table_feats.append(Feature("tables", p, {"id": table_ids[t], "combiner": None,
                                                 "source_layer": layer, "n_modules": 0}))

    # gaps in combiner numbering
    gaps: dict[int, list] = defaultdict(list)       # combiner number -> inverters missing it
    maxes = Counter(max((c.props["combiner"] or 0) for c in cbs) for cbs in inv_children.values())
    usual_max = maxes.most_common(1)[0][0] if maxes else 0
    for (station, inv), cbs in inv_children.items():
        nums = sorted(c.props["combiner"] for c in cbs if c.props["combiner"] is not None)
        if not nums:
            continue
        inner = sorted(set(range(1, nums[-1] + 1)) - set(nums))
        trailing = list(range(nums[-1] + 1, usual_max + 1))
        for m in inner + trailing:
            gaps[m].append((station, inv))
        if inner:
            res.issues.append(Issue("warning", "combiner_numbering_gap",
                                    f"inverter {station}-{inv}: combiner numbers {inner} not found"))
        if trailing:
            res.issues.append(Issue("note", "fewer_combiners",
                                    f"inverter {station}-{inv}: {len(nums)} combiners, most inverters have "
                                    f"{usual_max}"))
    # a combiner drawn in separate parts, while another inverter misses that same
    # combiner number, is almost always a CAD layer mix-up
    W, H = page_size
    for cb_id, (station, inv, cb), n_parts, bb in split_cbs:
        hint = ""
        cands = [(s, i) for s, i in gaps.get(cb, []) if (s, i) != (station, inv)]
        if cands:
            hint = (f"; inverter(s) {', '.join(f'{s}-{i}' for s, i in cands)} lack combiner {cb}: "
                    "likely their modules were drawn on this layer")
            own = [c.geom for c in inv_children[(station, inv)] if c.props["id"] != cb_id]
            me = next(c for c in cb_feats if c.props["id"] == cb_id)
            tsh = st.median(_axes(t[0])[3] for t in tables[:200])
            blobs = unary_union([g.buffer(3 * tsh) for g in getattr(me.geom, "geoms", [me.geom])])
            # rows of neighbouring inverters touch, so compare distances to each
            # inverter's array centroid rather than to its nearest edge
            for blob in getattr(blobs, "geoms", [blobs]):
                part = me.geom.intersection(blob)
                c = part.centroid
                d_own = unary_union(own).centroid.distance(c) if own else float("inf")
                for s, i in cands:
                    other = unary_union([c2.geom for c2 in inv_children.get((s, i), [])])
                    if not other.is_empty and other.centroid.distance(c) < 0.75 * d_own:
                        x0, y0, x1, y1 = part.buffer(0.5 * tsh).bounds
                        rule = {"layer_pattern": next(
                                    (o.layer for o in objs if roles[o.layer][0] == "module"
                                     and roles[o.layer][1].get("station") == station
                                     and roles[o.layer][1].get("inv") == inv
                                     and roles[o.layer][1].get("cb") == cb), ""),
                                "bbox_norm": [round(x0 / W, 4), round(y0 / H, 4),
                                              round(x1 / W, 4), round(y1 / H, 4)],
                                "to": {"station": s, "inv": i, "cb": cb}}
                        res.suggested_reassign.append(rule)
                        hint += (f". Suggested fix (check on the drawing, then add to layer_map.json "
                                 f"\"reassign\"): {json.dumps(rule)}")
        res.issues.append(Issue("warning", "combiner_in_separate_parts",
                                f"{cb_id} is drawn in {n_parts} separate areas{hint}", bb))

    inv_feats = []
    by_station: dict = defaultdict(list)
    for (station, inv), cbs in sorted(inv_children.items(), key=lambda z: tuple(-1 if v is None else v for v in z[0])):
        if station is None or inv is None:
            continue
        inv_id = layermap.name(naming["inverter"], station=station, inv=inv)
        for c in cbs:
            c.props["parent"] = inv_id
        g = unary_union([c.geom for c in cbs])
        f = Feature("inverters", g, {
            "id": inv_id, "level": "inverter", "station": station, "inverter": inv,
            "n_combiners": len(cbs), "n_strings": sum(c.props["n_strings"] for c in cbs),
            "n_modules": sum(c.props["n_modules"] for c in cbs)})
        inv_feats.append(f)
        by_station[station].append(f)

    st_points = locate_stations(objs, roles, by_station, lmap, res)
    st_feats = []
    for station, invs in sorted(by_station.items()):
        st_id = layermap.name(naming["station"], station=station)
        pt, src = st_points.get(station, (None, None))
        if pt is None:
            pt, src = unary_union([f.geom for f in invs]).centroid, "array_centroid"
            res.issues.append(Issue("warning", "station_location_fallback",
                                    f"{st_id}: station tag not found; point placed at the array centroid. "
                                    "Find the station on the drawing and add it to stations.json",
                                    _bbox(unary_union([f.geom for f in invs]).envelope)))
        for f in invs:
            f.props["parent"] = st_id
            f.props["station_x_pt"], f.props["station_y_pt"] = round(pt.x, 2), round(pt.y, 2)
        st_feats.append(Feature("stations", pt, {
            "id": st_id, "level": "station", "station": station, "location_source": src,
            "n_inverters": len(invs), "n_combiners": sum(f.props["n_combiners"] for f in invs),
            "n_strings": sum(f.props["n_strings"] for f in invs),
            "n_modules": sum(f.props["n_modules"] for f in invs)}))

    res.features["stations"] = st_feats
    res.features["inverters"] = inv_feats
    res.features["combiners"] = cb_feats
    res.features["strings"] = string_feats
    res.features["tables"] = table_feats
    res.features["site"] = site_features(objs, roles)

    # hierarchy rows (top-down, depth-first)
    kids: dict = defaultdict(list)
    for lay in ("inverters", "combiners", "strings"):
        for f in res.features[lay]:
            kids[f.props.get("parent")].append(f)

    def walk(f, path):
        p = path + [f.props["id"]]
        c = f.geom.centroid
        row = {k: v for k, v in f.props.items() if not k.endswith("_pt")}
        row.update({"path": " > ".join(p), "x_pt": round(c.x, 2), "y_pt": round(c.y, 2)})
        row.setdefault("parent", path[-1] if path else None)
        res.rows.append(row)
        for ch in kids.get(f.props["id"], []):
            walk(ch, p)

    for f in st_feats:
        walk(f, [])
    for f in cb_feats:
        if f.props["id"].startswith("UNASSIGNED"):
            walk(f, [])
    res.stats.update({"stations": len(st_feats), "inverters": len(inv_feats),
                      "combiners": len(cb_feats), "strings": len(string_feats)})
    return res


def locate_stations(objs, roles, by_station, lmap, res) -> dict:
    """Station points from inverter tags drawn as glyphs.

    Method `stacked_tags`: a station with two inverters is tagged with two
    stacked labels (e.g. INV10-01 over INV10-02) that share a left edge. The
    pair's centre is taken as the station location.
    """
    out: dict = {}
    glyphs: dict = defaultdict(list)          # (station, inv or None) -> glyph boxes
    for o in objs:
        role, g = roles[o.layer]
        if role == "inverter_label" and "station" in g and "f" in o.kind:
            glyphs[(g["station"], g.get("inv"))].append(o.rect)
    sizes = [r[3] - r[1] for rs in glyphs.values() for r in rs]
    if lmap["stations"].get("method") == "stacked_tags" and sizes:
        gh = st.median(sizes)
        words = {key: _words([r for r in rs if (r[2] - r[0]) < 3 * gh and (r[3] - r[1]) < 3 * gh], 0.35 * gh)
                 for key, rs in glyphs.items()}
        by_st: dict = defaultdict(dict)
        for (s, inv), ws in words.items():
            by_st[s][inv] = ws
        widths = []
        cand = {}
        for s, per_inv in by_st.items():
            # Pair tags of two different inverters of the station (INV10-01 over
            # INV10-02). Combiner tags of one inverter are also stacked, so a pair
            # within one layer is only allowed when the station has a single
            # label layer.
            invs = list(per_inv)
            combos = ([(per_inv[a], per_inv[b]) for i, a in enumerate(invs) for b in invs[i + 1:]]
                      if len(invs) > 1 else [(per_inv[invs[0]], per_inv[invs[0]])])
            pairs = []
            for wa, wb in combos:
                for a in wa:
                    for b in wb:
                        dy = abs(b[1] - a[1])
                        if a is not b and abs(a[0] - b[0]) < 0.5 * gh and 3 * gh < dy < 8 * gh:
                            pairs.append((a, b))
            cand[s] = pairs
            widths += [p[0][2] - p[0][0] for p in pairs]
        wmed = st.median(widths) if widths else None
        for s, pairs in cand.items():
            if not pairs:
                continue
            a, b = min(pairs, key=lambda p: abs((p[0][2] - p[0][0]) - wmed))
            out[s] = (box(*a).union(box(*b)).envelope.centroid, "station_tag")
    # manual overrides written after a visual check
    from pathlib import Path
    import json
    ov = lmap.get("_work")
    if ov:
        p = Path(ov) / lmap["stations"].get("override_file", "stations.json")
        if p.exists():
            for k, v in json.loads(p.read_text(encoding="utf-8")).items():
                out[int(k)] = (Point(v["x_pt"], v["y_pt"]), v.get("source", "manual"))
    return out


def site_features(objs, roles) -> list[Feature]:
    by: dict = defaultdict(list)
    for o in objs:
        role, _ = roles[o.layer]
        if role in FEATURE_ROLES:
            by[(role, o.layer)].append(o)
    feats = []
    for (role, layer), os_ in sorted(by.items()):
        kind = FEATURE_ROLES[role]
        if kind == "point":
            u = unary_union([box(*o.rect).buffer(1.0) for o in os_])
            for g in getattr(u, "geoms", [u]):
                feats.append(Feature("site", g.centroid, {"role": role, "layer": layer}))
        elif kind == "polygon":
            polys = [p for o in os_ for p in o.polygons()]
            if polys:
                feats.append(Feature("site", unary_union(polys), {"role": role, "layer": layer}))
        else:
            lines = [l for o in os_ for l in o.lines() if l.length > 0]
            if lines:
                merged = linemerge(lines)
                feats.append(Feature("site", merged, {"role": role, "layer": layer}))
    return feats


def multipolygon(g):
    if g.geom_type == "Polygon":
        return MultiPolygon([g])
    if g.geom_type == "GeometryCollection":
        return MultiPolygon([p for p in g.geoms if p.geom_type == "Polygon"])
    return g


__all__ = ["build", "Result", "Feature", "Issue", "np"]
