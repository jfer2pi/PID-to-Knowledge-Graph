"""Roll the hierarchy up from its children.

Rule: when the finest drawn level (strings, else tables) carries the ids of its parents, every parent
level those ids determine must exist in the output, as an area polygon and as a record point. Levels that
already exist as polygons are left alone; missing ones are built here and flagged as derived.

Area = union of the children, closed at a radius just over half the typical gap between neighbouring
children of the same parent (bridges row gaps, not aisles or other groups), then clipped so it never
covers another group's child. Point = the drawn symbol if a point layer already has it, else a point
inside the area (shapely representative point), flagged derived.

Works in a projected (metre) frame.
"""
from __future__ import annotations

import collections
from typing import Iterable

import numpy as np
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

LEVELS = ["station", "inverter", "combiner", "circuit"]          # top down
LAYER_OF = {"station": "stations", "inverter": "inverters", "combiner": "combiners", "circuit": "circuits"}
MIT = dict(join_style=2, mitre_limit=10)


def _is_area(g) -> bool:
    return g is not None and g.geom_type in ("Polygon", "MultiPolygon")


def finest_children(layers: dict) -> tuple[str, list]:
    for name in ("strings", "tables"):
        fs = [(g, p) for g, p in layers.get(name, []) if _is_area(g)]
        if fs:
            return name, fs
    return "", []


def closing_radius(children: list, key_of, cap: float = 3.0) -> float:
    """just over half the typical gap between neighbouring rows of the same group.

    Children closer than 0.35 m (strings inside one table, tables along a row) are merged into blocks first. For each block, the nearest
    block of the same group is measured separately side by side (overlapping in y) and stacked (overlapping
    in x); the larger of the two medians is the row gap, whichever way the rows run."""
    groups = {}
    for g, p in children:
        groups.setdefault(key_of(p), []).append(g)
    rng = np.random.default_rng(0)
    keys = list(groups)
    gx, gy = [], []
    for gi in rng.choice(len(keys), size=min(len(keys), 80), replace=False):
        blob = unary_union([g.buffer(0.175, **MIT) for g in groups[keys[gi]]])
        blocks = list(getattr(blob, "geoms", [blob]))
        if len(blocks) < 2:
            continue
        tree = STRtree(blocks)
        for i in rng.choice(len(blocks), size=min(len(blocks), 40), replace=False):
            b = blocks[i].bounds
            bx = by = None
            for j in tree.query(blocks[i].buffer(cap * 4)):
                if j == i:
                    continue
                c = blocks[j].bounds
                d = blocks[i].distance(blocks[j]) + 0.35
                if c[1] < b[3] and c[3] > b[1]:
                    bx = d if bx is None else min(bx, d)
                elif c[0] < b[2] and c[2] > b[0]:
                    by = d if by is None else min(by, d)
            if bx is not None:
                gx.append(bx)
            if by is not None:
                gy.append(by)
    meds = [float(np.median(v)) for v in (gx, gy) if v]
    if not meds:
        return 0.5
    return float(min(cap, max(0.2, 0.52 * max(meds))))


def _group_key(p: dict, level: str, use=None) -> tuple | None:
    """ancestor ids down to `level` (only levels in `use`, the ones the children carry); None when absent"""
    if not p.get(level):
        return None
    k = []
    for lv in LEVELS:
        if (use is None or lv in use) and p.get(lv) not in (None, ""):
            k.append(str(p[lv]))
        if lv == level:
            break
    return tuple(k)


def _existing_ids(layers: dict, level: str, use=None) -> dict:
    """map of group key -> (id, geometry) for parent features already present (areas first)"""
    out = {}
    feats = layers.get(f"{level}_areas", []) + layers.get(LAYER_OF[level], [])
    for g, p in feats:
        k = _group_key({**p, level: p.get(level) or p.get("name") or p.get("id")}, level, use)
        if k and k in out and _is_area(out[k][1]):
            continue
        if k:
            out[k] = (p.get("id"), g)
            out.setdefault((str(p.get("id")),), (p.get("id"), g))
    return out


def rollup(layers: dict, levels: Iterable[str] = LEVELS) -> tuple[dict, list[str]]:
    """Build only what is missing.

    For each level the children name: an area for every parent that has no area feature yet, and a record
    point for every parent that has no feature at all. A level whose groups are the same sets of children as
    its inverter (one inverter per station) gets no station area: it would duplicate the inverter area.
    New layers: '<level>_areas' (areas), '<level>s' (points, when the level had no layer) or
    '<level>s_derived' (points added to a level that had some)."""
    src, kids = finest_children(layers)
    new, notes = {}, []
    if not kids:
        return new, ["no polygon children (strings or tables); nothing to roll up"]
    geoms = [g for g, _ in kids]
    tree = STRtree(geoms)
    members = {}
    use = {lv for lv in LEVELS if any(p.get(lv) not in (None, "") for _, p in kids)}
    for level in levels:
        keyed = [(i, _group_key(p, level, use)) for i, (_, p) in enumerate(kids)]
        groups = collections.defaultdict(list)
        for i, k in keyed:
            if k:
                groups[k].append(i)
        if not groups:
            continue
        members[level] = {frozenset(v) for v in groups.values()}
        have = layers.get(LAYER_OF[level], []) + layers.get(f"{level}_areas", [])
        existing = _existing_ids(layers, level, use)
        def found(k):
            return existing.get(k) or existing.get((k[-1],))
        # same membership as a lower level (computed later in the loop): check against all other levels
        missing_area = [k for k in groups if not (found(k) and _is_area(found(k)[1]))]
        missing_any = [k for k in groups if not found(k)]
        if missing_area:
            r = closing_radius([kids[i] for i, k in keyed if k], lambda p: _group_key(p, level, use))
            feats = []
            for k in missing_area:
                ix = groups[k]
                own = set(ix)
                poly = unary_union([geoms[i] for i in ix]).buffer(r, **MIT).buffer(-r, **MIT)
                others = [geoms[j] for j in tree.query(poly) if j not in own and geoms[j].intersection(poly).area > 1e-6]
                if others:
                    poly = poly.difference(unary_union(others).buffer(0.05, **MIT))
                poly = poly.buffer(0)
                gid = (found(k) or (None,))[0] or "-".join(k)
                p0 = kids[ix[0]][1]
                props = {lv: p0.get(lv) for lv in LEVELS[:LEVELS.index(level) + 1] if p0.get(lv) not in (None, "")}
                nm = sum(int(kids[i][1].get("n_modules") or 0) for i in ix)
                props.update(id=gid, level=f"{level}_area", **{f"n_{src}": len(ix)}, area_m2=round(poly.area, 1),
                             parts=len(getattr(poly, "geoms", [poly])), derived=f"area: union of its {src} closed at {r:.2f} m")
                if nm:
                    props["n_modules"] = nm
                feats.append((poly, props, frozenset(ix)))
            new[f"{level}_areas"] = feats
        if missing_any:
            area_of = {p["id"]: g for g, p, _ in new.get(f"{level}_areas", [])}
            area_of.update({p.get("id"): g for g, p in have if _is_area(g)})
            pts = []
            for k in missing_any:
                ix = groups[k]
                gid = "-".join(k)
                a = area_of.get(gid) or unary_union([geoms[i] for i in ix])
                p0 = kids[ix[0]][1]
                props = {lv: p0.get(lv) for lv in LEVELS[:LEVELS.index(level) + 1] if p0.get(lv) not in (None, "")}
                props.update(id=gid, level=level, derived="point: inside the area of its children (no symbol drawn or read)")
                pts.append((a.representative_point(), props))
            new[LAYER_OF[level] if not layers.get(LAYER_OF[level]) else LAYER_OF[level] + "_derived"] = pts
            notes.append(f"{level}: {len(pts)} missing record points derived")
    # drop area levels that duplicate another level's membership (e.g. one inverter per station)
    for level in levels:
        name = f"{level}_areas"
        if name not in new:
            continue
        # only a station that is a single inverter is a duplicate; combiner and inverter areas are always kept
        lower = ["inverter"] if level == "station" and "inverter" in members else []
        dup_of = [lv for lv in lower if any(m in members[lv] for _, _, m in new[name])]
        keep = [(g, p) for g, p, m in new[name] if not any(m in members[lv] for lv in lower)]
        dropped = len(new[name]) - len(keep)
        if keep:
            new[name] = keep
            multi = sum(1 for _, p in keep if p["parts"] > 1)
            notes.append(f"{level}: {len(keep)} missing areas derived ({multi} in several parts)"
                         + (f"; {dropped} skipped as identical to {', '.join(dup_of)}" if dropped else ""))
        else:
            del new[name]
            notes.append(f"{level}: areas not built, identical to the {', '.join(dup_of)} areas")
    return new, notes
