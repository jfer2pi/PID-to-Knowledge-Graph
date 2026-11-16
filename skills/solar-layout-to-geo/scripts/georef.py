#!/usr/bin/env python3
"""Fit the sheet -> map transform from ground control points (GCPs).

GCP file: a CSV with one row per point. Columns:

    id                      any label
    feature                 a hierarchy id (ST10, INV10-01, INV10-01-CB05, ...) or
                            site:<layer role> (centre of that site feature, e.g.
                            site:site_boundary) - the sheet position is looked up
      or sheet_x_pt,sheet_y_pt   the sheet position in PDF points (y down), e.g.
                            read from preview.py or crop.py
    easting,northing        map coordinates in --crs
      or lon,lat            WGS84 degrees (reprojected to --crs)

Good GCPs are things you can identify both on the drawing and on imagery or
the asset register: inverter stations (the as-built coordinates are often in
the O&M documents), fence corners, gates, the substation, building corners
from the base map. Use 3 or more spread around the site, so the fit is
over-determined and the residuals mean something.

Methods: translation (1 point, provisional only), similarity (2+, default),
affine (3+, scanned sheets only). See pvgeo/transform.py.

Writes <work>/georef/transform.json and gcps_used.csv with per-point
residuals.

Usage:
    python georef.py work/my-site --gcps gcps.csv --crs EPSG:27700
    python georef.py work/my-site --gcps gcps.csv            # lon/lat GCPs: UTM picked automatically
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as stats
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pvgeo.transform import fit  # noqa: E402


def lookup(work: Path) -> dict:
    """Sheet-metre positions of every hierarchy item and site feature."""
    lay = work / "layout"
    out = {}
    for name in ("stations", "inverters", "combiners", "strings"):
        p = lay / f"{name}.geojson"
        if not p.exists():
            continue
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            pr = f["properties"]
            out[pr["id"]] = (pr["x_pt"], pr["y_pt"])
    p = lay / "site.geojson"
    if p.exists():
        from shapely.geometry import shape
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            role = f["properties"]["role"]
            if f"site:{role}" not in out:
                b = shape(f["geometry"]).bounds
                out[f"site:{role}"] = ("bbox", b)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--gcps", type=Path, required=True)
    ap.add_argument("--crs", help="projected CRS of easting/northing and of the fit, e.g. EPSG:27700")
    ap.add_argument("--method", choices=["auto", "translation", "similarity", "affine"], default="auto")
    ap.add_argument("--rotation", type=float, default=0.0,
                    help="translation only: grid rotation in degrees, counter-clockwise (default 0)")
    args = ap.parse_args()

    from pyproj import CRS, Transformer

    meta = json.loads((args.work / "layout" / "sheet.json").read_text(encoding="utf-8"))
    k = meta["m_per_pt"]
    feats = lookup(args.work)
    rows = list(csv.DictReader(args.gcps.open(encoding="utf-8-sig")))
    if not rows:
        sys.exit("error: no rows in the GCP file")

    crs = args.crs
    if not crs:
        if "lon" not in rows[0]:
            sys.exit("error: easting/northing given without --crs")
        from pyproj.aoi import AreaOfInterest
        from pyproj.database import query_utm_crs_info
        lon = stats.mean(float(r["lon"]) for r in rows)
        lat = stats.mean(float(r["lat"]) for r in rows)
        info = query_utm_crs_info(datum_name="WGS 84", area_of_interest=AreaOfInterest(lon, lat, lon, lat))
        crs = f"EPSG:{info[0].code}"
        print(f"no --crs given: using {crs} ({info[0].name})")
    to_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    ids, src, dst, used = [], [], [], []
    for i, r in enumerate(rows, 1):
        gid = r.get("id") or str(i)
        if r.get("feature"):
            v = feats.get(r["feature"].strip())
            if v is None:
                sys.exit(f"error: GCP {gid}: feature {r['feature']!r} not found in layout/")
            if v[0] == "bbox":
                b = v[1]
                X, Y = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                x_pt, y_pt = X / k, -Y / k
            else:
                x_pt, y_pt = v
        else:
            x_pt, y_pt = float(r["sheet_x_pt"]), float(r["sheet_y_pt"])
        if r.get("easting") not in (None, ""):
            E, N = float(r["easting"]), float(r["northing"])
        else:
            E, N = to_crs.transform(float(r["lon"]), float(r["lat"]))
        ids.append(gid)
        src.append((x_pt * k, -y_pt * k))
        dst.append((E, N))
        used.append({"id": gid, "feature": r.get("feature", ""), "sheet_x_pt": round(x_pt, 3),
                     "sheet_y_pt": round(y_pt, 3), "easting": round(E, 3), "northing": round(N, 3)})
    src_a, dst_a = np.array(src), np.array(dst)
    method = args.method
    if method == "auto":
        method = "translation" if len(src) == 1 else "similarity"
    t = fit(src_a, dst_a, method, crs, k, ids, rotation_deg=args.rotation)

    notes = []
    if method == "translation":
        notes.append("PROVISIONAL: one control point, scale and rotation assumed. Position is only as good "
                     "as that point; add 3+ GCPs and refit before using the output.")
    if method != "translation" and abs(t.scale - 1) > 0.02:
        notes.append(f"fitted scale {t.scale:.4f} differs from 1 by more than 2%: check the drawing scale "
                     "(layer_map.json scale) and look for a wrong control point")
    if abs(t.rotation_deg) > 3 and method != "translation":
        notes.append(f"rotation {t.rotation_deg:.2f} deg: fine if the CAD grid is rotated from north, "
                     "otherwise suspect a control point")
    rs = [r["r"] for r in t.residuals]
    if len(rs) >= 3:
        med = stats.median(rs)
        for r in t.residuals:
            if r["r"] > max(3 * med, 2.0):
                notes.append(f"GCP {r['id']}: residual {r['r']:.1f} m is an outlier; re-check it")
    t.note = " | ".join(notes)

    out = args.work / "georef"
    out.mkdir(exist_ok=True)
    (out / "transform.json").write_text(t.to_json(), encoding="utf-8")
    with (out / "gcps_used.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(used[0]) + ["dE", "dN", "r"])
        w.writeheader()
        for u, r in zip(used, t.residuals):
            w.writerow({**u, "dE": round(r["dE"], 3), "dN": round(r["dN"], 3), "r": round(r["r"], 3)})

    print(f"{method} fit to {crs} from {len(src)} GCPs")
    print(f"  scale {t.scale:.5f}   rotation {t.rotation_deg:+.3f} deg   "
          f"RMSE {'n/a' if t.rmse_m is None else f'{t.rmse_m:.2f} m'}")
    for r in t.residuals:
        print(f"  {r['id']:<14} dE {r['dE']:+8.2f}  dN {r['dN']:+8.2f}  r {r['r']:7.2f} m")
    for n in notes:
        print("  note:", n)
    print(f"-> {out / 'transform.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
