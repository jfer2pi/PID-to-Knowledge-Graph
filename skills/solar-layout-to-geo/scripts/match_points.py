#!/usr/bin/env python3
"""Turn surveyed coordinates printed in the document into control points.

Projects often print a few surveyed points, such as trench-stream crossings,
substation corners or access points, on separate sheets that do not show
where they sit on the layout. If you know what kind of point they are, they
can be found on the drawing: each is an intersection of two feature roles,
e.g. the DC home-run trench crossing a stream.

This script lists every intersection of the role pairs you give (--pair
A:B, repeatable), then searches for the placement that puts the most
surveyed points on an intersection. Each placement is a similarity
transform whose scale and rotation stay within tolerance of a true-scale,
north-up drawing. Matched points are written as GCPs. Unmatched points are
reported with the position the fit predicts for them, so you can check them
on the drawing.

known.csv columns: id, easting, northing (in --crs), optional note.

Writes <work>/gcps.csv (id, sheet_x_pt, sheet_y_pt, easting, northing, note)
and <work>/georef/match_report.md.

Usage:
    python match_points.py work/site --known known.csv --crs EPSG:25829 \\
        --pair homerun_cable:stream --pair mv_cable:stream
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_map, source  # noqa: E402
from pvgeo.transform import fit  # noqa: E402


def geoms_for(work: Path, lmap: dict, role: str) -> list:
    reg_p = work / "register.json"
    import pymupdf
    if lmap.get("mode") == "labels" and reg_p.exists():
        from pvgeo.labelled import role_geoms
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        return role_geoms(pymupdf.open(source(work)["pdf"]), reg, lmap, role)
    from _common import load_page
    from pvgeo import layermap
    objs, _, _ = load_page(work)
    out = []
    for o in objs:
        if layermap.classify(o.layer, lmap["roles"])[0] == role:
            polys = o.polygons()
            out += [p.buffer(0) for p in polys] if polys else [l for l in o.lines() if l.length > 0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--known", type=Path, required=True)
    ap.add_argument("--crs", required=True)
    ap.add_argument("--pair", action="append", required=True, help="ROLE_A:ROLE_B, repeatable")
    ap.add_argument("--scale-tol", type=float, default=0.03)
    ap.add_argument("--rot-tol", type=float, default=3.0, help="degrees")
    ap.add_argument("--inlier-m", type=float, default=4.0)
    args = ap.parse_args()

    from shapely.geometry import Point
    from shapely.ops import unary_union

    lmap = load_map(args.work)
    k = json.loads((args.work / "layout" / "sheet.json").read_text(encoding="utf-8"))["m_per_pt"]
    known = list(csv.DictReader(args.known.open(encoding="utf-8-sig")))
    K = np.array([[float(r["easting"]), float(r["northing"])] for r in known])

    cands, cache = [], {}
    for pair in args.pair:
        a, b = pair.split(":")
        for r in (a, b):
            if r not in cache:
                cache[r] = geoms_for(args.work, lmap, r)
                print(f"  {r}: {len(cache[r])} geometries", flush=True)
        from shapely import STRtree
        Bg = cache[b]
        tree = STRtree(Bg)
        for g in cache[a]:
            hits = tree.query(g, predicate="intersects")
            if len(hits) == 0:
                continue
            i = g.intersection(unary_union([Bg[h] for h in hits]))
            parts = list(getattr(i, "geoms", [i])) if not i.is_empty else []
            for p in parts:
                c = p.centroid
                X, Y = c.x * k, -c.y * k
                if all(math.hypot(X - u[0], Y - u[1]) > 6 for u in cands):
                    cands.append((X, Y, pair))
    print(f"{len(cands)} candidate intersections")
    if len(cands) < 2 or len(K) < 2:
        sys.exit("error: need at least 2 candidates and 2 known points")
    C = np.array([[c[0], c[1]] for c in cands])

    best = None
    for i, j in itertools.permutations(range(len(K)), 2):
        dk = K[j] - K[i]
        Lk = math.hypot(*dk)
        for a, b in itertools.permutations(range(len(C)), 2):
            dc = C[b] - C[a]
            Lc = math.hypot(*dc)
            if Lc == 0 or abs(Lk / Lc - 1) > args.scale_tol:
                continue
            rot = math.degrees(math.atan2(dk[1], dk[0]) - math.atan2(dc[1], dc[0]))
            rot = (rot + 180) % 360 - 180
            if abs(rot) > args.rot_tol:
                continue
            t = fit(C[[a, b]], K[[i, j]], "similarity", args.crs, k)
            Ainv = np.linalg.inv(np.array([[t.a, t.b], [t.d, t.e]]))
            pred = (K - np.array([t.c, t.f])) @ Ainv.T          # known -> sheet metres
            d = np.linalg.norm(pred[:, None, :] - C[None, :, :], axis=2)
            nearest = d.argmin(axis=1)
            inl = [(q, int(nearest[q])) for q in range(len(K)) if d[q, nearest[q]] < args.inlier_m]
            used = {c for _, c in inl}
            if len(used) < len(inl):
                continue
            rms = math.sqrt(np.mean([d[q, c] ** 2 for q, c in inl]))
            key = (len(inl), -rms)
            if best is None or key > best[0]:
                best = (key, inl, pred)
    if best is None:
        sys.exit("error: no placement within the scale/rotation tolerance; check the CRS, the pairs or the scale")
    (n_in, _), inl, pred = best
    src = np.array([C[c] for _, c in inl])
    dst = np.array([K[q] for q, _ in inl])
    t = fit(src, dst, "similarity" if len(inl) >= 2 else "translation", args.crs, k)
    Ainv = np.linalg.inv(np.array([[t.a, t.b], [t.d, t.e]]))
    pred = (K - np.array([t.c, t.f])) @ Ainv.T

    rows, rep = [], ["# Control points matched from printed coordinates", "",
                     f"- candidates: {len(cands)} intersections of {', '.join(args.pair)}",
                     f"- matched {len(inl)} of {len(K)} known points; scale {t.scale:.4f}, rotation "
                     f"{t.rotation_deg:+.2f} deg, RMSE {'n/a' if t.rmse_m is None else f'{t.rmse_m:.2f} m'}", "",
                     "| id | matched | via | sheet x, y (pt) | residual / distance (m) |", "|---|---|---|---|---|"]
    matched = {q: c for q, c in inl}
    res_by = {r["id"]: r["r"] for r in t.residuals}
    for q, r in enumerate(known):
        if q in matched:
            X, Y = C[matched[q]]
            rows.append({"id": r["id"], "sheet_x_pt": round(X / k, 3), "sheet_y_pt": round(-Y / k, 3),
                         "easting": r["easting"], "northing": r["northing"],
                         "note": f"{r.get('note', '')} [{cands[matched[q]][2]}]".strip()})
            rep.append(f"| {r['id']} | yes | {cands[matched[q]][2]} | {X / k:.1f}, {-Y / k:.1f} | "
                       f"{res_by.get(str(len(rows)), float('nan')):.2f} |")
        else:
            X, Y = pred[q]
            dmin = min(math.hypot(X - c[0], Y - c[1]) for c in C)
            rep.append(f"| {r['id']} | no | predicted | {X / k:.1f}, {-Y / k:.1f} | nearest candidate {dmin:.0f} m |")
    rep += ["", "Unmatched points: open a preview at the predicted position. If the drawing shows the feature "
            "there, add the point to gcps.csv with the sheet position read from the preview."]
    with (args.work / "gcps.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "sheet_x_pt", "sheet_y_pt", "easting", "northing", "note"])
        w.writeheader()
        w.writerows(rows)
    (args.work / "georef").mkdir(exist_ok=True)
    (args.work / "georef" / "match_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[2:]))
    print(f"-> {args.work / 'gcps.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
