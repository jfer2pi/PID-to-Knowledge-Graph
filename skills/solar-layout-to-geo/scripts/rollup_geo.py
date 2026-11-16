#!/usr/bin/env python3
"""Add the parent levels a delivered site is missing, derived from its children.

Reads   <site>/gis/*.geojson (WGS84) and the CRS from <site>/config/transform.json
Writes  only what is missing: <level>_areas.geojson / .shp and record points (<level>s or
        <level>s_derived), rebuilds <site>/gis/<site>.kmz with every layer, and
        <site>/qa/rollup_report.md. Existing layers are never changed.

usage:  python rollup_geo.py <converted_layouts/site> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pvgeo.rollup import rollup  # noqa: E402
from pvgeo.writers import STYLE, project, write_geojson, write_kmz, write_shapefile  # noqa: E402

ORDER = ["site", "station_areas", "inverter_areas", "inverters", "combiner_areas", "combiners", "circuit_areas",
         "circuits", "combiner_boxes", "stations", "stations_derived", "inverters_derived", "combiners_derived",
         "tables", "strings"]
STYLE.setdefault("station_areas", ("ff000000", "10000000"))
STYLE.setdefault("inverter_areas", ("ff0000ff", "1a0000ff"))
STYLE.setdefault("combiner_areas", ("ff00a5ff", "4000a5ff"))
STYLE.setdefault("circuit_areas", ("ff00ff00", "3300ff00"))
STYLE.setdefault("circuits", ("ff00ffff", "00000000"))


def find_crs(site: Path) -> str:
    for p in (site / "config/transform.json", site / "georef/transform.json"):
        if p.exists():
            return json.loads(p.read_text())["crs"]
    sys.exit("error: no config/transform.json with the projected CRS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from pyproj import CRS, Transformer
    from shapely.geometry import shape

    crs = find_crs(a.site)
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    to_m = lambda xy: np.c_[fwd.transform(xy[:, 0], xy[:, 1])]
    to_ll = lambda xy: np.c_[inv.transform(xy[:, 0], xy[:, 1])]
    gis = a.site / "gis"
    layers = {}
    for p in sorted(gis.glob("*.geojson")):
        fs = json.loads(p.read_text(encoding="utf-8"))["features"]
        layers[p.stem] = [(project(shape(f["geometry"]), to_m), f["properties"]) for f in fs if f.get("geometry")]
    new, notes = rollup(layers)
    print(f"{a.site.name}: " + ("; ".join(notes) if notes else "nothing missing"))
    if a.dry_run or not new:
        return 0
    wkt = CRS.from_user_input(crs).to_wkt("WKT1_ESRI")
    (a.site / "shp").mkdir(exist_ok=True)
    for name, fs in new.items():
        write_geojson(gis / f"{name}.geojson", [(project(g, to_ll), p) for g, p in fs])
        write_shapefile(a.site / "shp" / f"{name}.shp", fs, wkt)
        layers[name] = fs
    kmz = {n: [(project(g, to_ll), p) for g, p in layers[n]] for n in ORDER if n in layers}
    kmz.update({n: [(project(g, to_ll), p) for g, p in fs] for n, fs in layers.items() if n not in kmz and n != "modules"})
    old = list(gis.glob("*.kmz"))
    write_kmz(old[0] if old else gis / f"{a.site.name}.kmz", kmz, a.site.name)
    (a.site / "qa").mkdir(exist_ok=True)
    (a.site / "qa/rollup_report.md").write_text(
        "# Parent levels derived from children\n\n"
        "Only levels or parents that were missing were added; existing layers are unchanged.\n\n"
        + "\n".join(f"- {n}" for n in notes)
        + "\n\nAreas: union of the children closed at just over half the typical row gap, clipped so they never "
          "cover another group's child. Points: inside the area, flagged `derived` (no symbol drawn or read).\n",
        encoding="utf-8")
    print(f"  wrote {', '.join(new)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
