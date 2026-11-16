"""the route D site: provisional georeference and export in the converted_layouts structure."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, json, pickle, collections, csv, shutil, math
from pathlib import Path
import numpy as np
from shapely.geometry import Point, mapping
from shapely.ops import unary_union
from pyproj import Transformer, CRS as PCRS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit

W = Path(WORK)
OUT = Path(OUT)
CRS = os.environ.get("SITE_CRS", "EPSG:32630")                       # projected CRS of the site, set per site
ANCHOR = tuple(float(v) for v in os.environ.get("SITE_ANCHOR_LONLAT", "0,0").split(","))   # published plant point, lon,lat
LAYERS = ["site", "inverter_areas", "combiner_areas", "circuit_areas", "stations", "inverters", "combiners", "circuits", "tables", "strings"]
writers.STYLE.setdefault("circuits", ("ff00ffff", "00000000"))
writers.STYLE.update(inverter_areas=("ff0000ff", "1a0000ff"), combiner_areas=("ff00a5ff", "4000a5ff"), circuit_areas=("ff00ff00", "3300ff00"))


def main():
    A = pickle.load(open(W / "cache/assembled.pkl", "rb"))
    feats, rows, qa, disc = A["feats"], A["rows"], A["qa"], A["disc"]
    for d in ("gis", "shp", "hierarchy", "qa", "qa/sheets", "config"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    # provisional transform: plant centroid (all tables) -> published plant point
    allt = unary_union([g for g, _ in feats["tables"]])
    cx, cy = allt.centroid.x, allt.centroid.y
    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    E0, N0 = to_utm.transform(*ANCHOR)
    T = fit(np.array([[cx, cy]]), np.array([[E0, N0]]), "translation", CRS, 1.0, ids=["GEM plant point"])
    T.note = ("Provisional: plant centroid (centroid of all tables) placed on the GEM / WRI plant point "
              f"({ANCHOR[1]}, {ANCHOR[0]}). Scale 1 and drawing north = grid north assumed. Correct with the georeferencer KMZ mode.")
    def proj(g):
        return writers.project(g, lambda xy: np.c_[T.apply(xy[:, 0], xy[:, 1])])
    def ll(g):
        return writers.project(g, lambda xy: np.c_[to_ll.transform(xy[:, 0], xy[:, 1])])
    wkt = PCRS.from_user_input(CRS).to_wkt("WKT1_ESRI")
    kmz_layers = {}
    for L in LAYERS:
        fs = [(g, p) for g, p in feats.get(L, []) if g is not None and not g.is_empty]
        pf = [(proj(g), p) for g, p in fs]
        lf = [(ll(g), p) for g, p in pf]
        writers.write_geojson(OUT / f"gis/{L}.geojson", lf)
        writers.write_shapefile(OUT / f"shp/{L}.shp", pf, wkt)
        kmz_layers[L] = lf
    writers.write_kmz(OUT / "gis/route_d_site.kmz", kmz_layers, "the route D site (provisional placement)")
    # hierarchy
    path_of = {}
    for r in rows:
        path_of[r["id"]] = (path_of.get(r["parent"], "") + " > " if r["parent"] else "") + r["id"]
    cols = ["id", "level", "parent", "path", "station", "inverter", "combiner", "circuit", "string", "table", "row", "rows",
            "n_combiners", "n_circuits", "n_tables", "n_strings", "n_modules", "location_source", "derived",
            "x_frame_m", "y_frame_m", "easting", "northing", "lon", "lat"]
    with open(OUT / "hierarchy/hierarchy.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            e, n = T.apply(r["X"], r["Y"])
            lo, la = to_ll.transform(e, n)
            o = {k: r.get(k, "") for k in cols}
            o.update(path=path_of[r["id"]], x_frame_m=round(float(r["X"]), 2), y_frame_m=round(float(r["Y"]), 2),
                     easting=round(float(e), 2), northing=round(float(n), 2), lon=round(lo, 7), lat=round(la, 7))
            w.writerow(o)
    # nested json
    kids = collections.defaultdict(list)
    for r in rows:
        kids[r["parent"]].append(r)
    def node(r):
        e, n = T.apply(r["X"], r["Y"]); lo, la = to_ll.transform(e, n)
        d = {k: (v if not isinstance(v, (np.floating, np.integer)) else v.item()) for k, v in r.items() if k not in ("X", "Y") and v not in ("", None)}
        d.update(lon=round(lo, 7), lat=round(la, 7))
        ch = [node(c) for c in kids.get(r["id"], [])]
        if ch:
            d["children"] = ch
        return d
    tree = dict(site="the route D site", crs=CRS, placement="provisional", stations=[node(r) for r in kids[""]])
    (OUT / "hierarchy/hierarchy.json").write_text(json.dumps(tree, indent=1))
    # config
    (OUT / "config/transform.json").write_text(T.to_json())
    with open(OUT / "config/gcps.csv", "w") as f:
        f.write("id,x_frame_m,y_frame_m,easting,northing,lon,lat,source\n")
        f.write(f"GEM plant point,{cx:.2f},{cy:.2f},{E0:.2f},{N0:.2f},{ANCHOR[0]},{ANCHOR[1]},"
                "GEM Global Solar Power Tracker (plant centroid assumed)\n")
    shutil.copy(W / "cache/register.json", OUT / "config/sheet_placement_blockfit.json")
    shutil.copy(W / "cache/ctin_match.json", OUT / "config/sheet_placement_transformer.json")
    return T, (cx, cy), (E0, N0), allt


if __name__ == "__main__":
    T, c, en, allt = main()
    print("centroid", c, "->", en, "area", round(allt.area))
