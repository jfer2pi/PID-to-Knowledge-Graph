#!/usr/bin/env python3
"""Export the georeferenced layout and hierarchy.

Applies <work>/georef/transform.json to the sheet-space layers in
<work>/layout/ and writes <work>/out/:

    <layer>.geojson         WGS84 lon/lat (RFC 7946): stations, inverters,
                            combiners, strings, tables, site (+ modules if built)
    <plant>.kmz             Google Earth: one folder per layer, attributes kept
    shp/<layer>.shp         Shapefiles in the projected CRS of the fit, with .prj
    hierarchy.csv           every station, inverter, combiner and string with its
                            parent, path, counts, easting/northing and lon/lat
    hierarchy.json          the same as a nested tree
    georef_report.md        transform, residuals and caveats

Usage:
    python export_geo.py work/my-site [--name "My Site"] [--formats geojson kmz shp]
                                      [--kmz-layers stations inverters combiners strings site]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pvgeo.transform import Transform  # noqa: E402
from pvgeo.writers import project, write_geojson, write_kmz, write_shapefile  # noqa: E402

LAYERS = ["stations", "inverters", "combiners", "combiner_boxes", "strings", "tables", "site", "modules"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--name", help="plant name for file names (default: work dir name)")
    ap.add_argument("--formats", nargs="+", default=["geojson", "kmz", "shp"], choices=["geojson", "kmz", "shp"])
    ap.add_argument("--kmz-layers", nargs="+", default=["stations", "inverters", "combiners", "combiner_boxes", "strings", "site"])
    args = ap.parse_args()

    from pyproj import CRS, Transformer
    from shapely.geometry import shape

    lay = args.work / "layout"
    tpath = args.work / "georef" / "transform.json"
    if not tpath.exists():
        sys.exit("error: no georef/transform.json; run georef.py first")
    t = Transform.from_json(tpath.read_text(encoding="utf-8"))
    crs = CRS.from_user_input(t.crs)
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    name = args.name or args.work.name
    out = args.work / "out"
    out.mkdir(exist_ok=True)

    def to_map(a):
        E, N = t.apply(a[:, 0], a[:, 1])
        return np.c_[E, N]

    def to_lonlat(a):
        lon, lat = to_ll.transform(a[:, 0], a[:, 1])
        return np.c_[lon, lat]

    kmz_layers = {}
    mapped_all = {}
    for ln in LAYERS:
        p = lay / f"{ln}.geojson"
        if not p.exists():
            continue
        feats = json.loads(p.read_text(encoding="utf-8"))["features"]
        mapped = [(project(shape(f["geometry"]), to_map), f["properties"]) for f in feats]
        mapped_all[ln] = mapped
        ll = [(project(g, to_lonlat), pr) for g, pr in mapped]
        if "geojson" in args.formats:
            write_geojson(out / f"{ln}.geojson", ll)
        if "shp" in args.formats:
            (out / "shp").mkdir(exist_ok=True)
            write_shapefile(out / "shp" / f"{ln}.shp", mapped, crs.to_wkt("WKT1_ESRI"))
        if ln in args.kmz_layers:
            kmz_layers[ln] = ll
        print(f"  {ln:<10} {len(feats):>7} features")
    # parents the children determine but the layout lacks (only what is missing)
    from pvgeo.rollup import rollup
    derived, notes = rollup(mapped_all)
    for ln, mapped in derived.items():
        ll = [(project(g, to_lonlat), pr) for g, pr in mapped]
        if "geojson" in args.formats:
            write_geojson(out / f"{ln}.geojson", ll)
        if "shp" in args.formats:
            (out / "shp").mkdir(exist_ok=True)
            write_shapefile(out / "shp" / f"{ln}.shp", mapped, crs.to_wkt("WKT1_ESRI"))
        kmz_layers[ln] = ll
        print(f"  {ln:<10} {len(mapped):>7} features (derived from children)")
    for n_ in notes:
        print(f"  roll-up: {n_}")
    if "kmz" in args.formats:
        write_kmz(out / f"{name}.kmz", kmz_layers, name)

    # hierarchy with coordinates: stations at their station point, others at the area centroid
    k = t.m_per_pt
    rows = list(csv.DictReader((lay / "hierarchy.csv").open(encoding="utf-8")))
    xs = np.array([float(r["x_pt"]) * k for r in rows])
    ys = np.array([-float(r["y_pt"]) * k for r in rows])
    E, N = t.apply(xs, ys)
    lon, lat = to_ll.transform(E, N)
    cols = list(rows[0].keys()) + ["easting", "northing", "lon", "lat"]
    with (out / "hierarchy.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r, e, n, lo, la in zip(rows, E, N, lon, lat):
            w.writerow({**r, "easting": round(e, 2), "northing": round(n, 2), "lon": round(lo, 7), "lat": round(la, 7)})
    pos = {r["id"]: (round(lo, 7), round(la, 7)) for r, lo, la in zip(rows, lon, lat)}
    tree = json.loads((lay / "hierarchy.json").read_text(encoding="utf-8"))

    def add(nodes):
        for nd in nodes:
            nd["lon"], nd["lat"] = pos.get(nd["id"], (None, None))
            add(nd.get("children", []))

    add(tree)
    (out / "hierarchy.json").write_text(json.dumps(tree, indent=1), encoding="utf-8")
    shutil.copy(lay / "qa_report.md", out / "qa_report.md")

    rep = ["# Georeferencing report", "",
           f"- CRS of the fit: {t.crs} ({crs.name})",
           f"- method: {t.method}, scale {t.scale:.5f}, rotation {t.rotation_deg:+.3f} deg, "
           f"RMSE {'n/a' if t.rmse_m is None else f'{t.rmse_m:.2f} m'}",
           f"- sheet scale: {k:.5f} m per PDF point", "",
           "| GCP | dE (m) | dN (m) | residual (m) |", "|---|---|---|---|"]
    rep += [f"| {r['id']} | {r['dE']:+.2f} | {r['dN']:+.2f} | {r['r']:.2f} |" for r in t.residuals]
    if t.note:
        rep += ["", "**Notes**", ""] + [f"- {n}" for n in t.note.split(" | ")]
    if notes:
        rep += ["", "**Parent levels derived from children (only where missing)**", ""] + [f"- {n_}" for n_ in notes]
    rep += ["", "Strings are derived from the drawn modules (row by row within each table), not read "
            "from a string schedule. Station points come from the station tags on the drawing.", ""]
    (out / "georef_report.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
