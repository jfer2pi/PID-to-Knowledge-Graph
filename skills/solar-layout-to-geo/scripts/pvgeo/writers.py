"""Write features as GeoJSON, KML/KMZ and Shapefile.

GeoJSON and KML are WGS84 lon/lat (as both formats require). Shapefiles are in
the projected CRS of the georeferencing fit, with a .prj, which is what GIS and
CAD users expect for measuring.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.geometry.polygon import orient

# KML colours are aabbggrr
STYLE = {
    "stations": ("ff0000ff", "ff0000ff"),
    "inverters": ("ffffaa00", "33ffaa00"),
    "combiners": ("ff00a5ff", "4000a5ff"),
    "combiner_boxes": ("ff00a5ff", "ff00a5ff"),
    "strings": ("ff32cd32", "2032cd32"),
    "tables": ("ff888888", "10888888"),
    "modules": ("ffcc6600", "20cc6600"),
    "site": ("ff2222dd", "00000000"),
}


def project(geom, fn):
    """Apply fn((n,2) array) -> (n,2) array to every coordinate."""
    return shapely.transform(geom, fn)


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def write_geojson(path: Path, feats: list[tuple], crs_name: str | None = None) -> None:
    """feats: list of (geometry, props) already in the output CRS."""
    fc = {"type": "FeatureCollection",
          "features": [{"type": "Feature", "geometry": mapping(g),
                        "properties": {k: _clean(v) for k, v in p.items()}} for g, p in feats]}
    if crs_name:
        fc["crs"] = {"type": "name", "properties": {"name": crs_name}}
    path.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")


def _kml_coords(coords) -> str:
    return " ".join(f"{x:.8f},{y:.8f},0" for x, y, *_ in coords)


def _kml_geom(g) -> str:
    t = g.geom_type
    if t == "Point":
        return f"<Point><coordinates>{g.x:.8f},{g.y:.8f},0</coordinates></Point>"
    if t == "LineString":
        return f"<LineString><tessellate>1</tessellate><coordinates>{_kml_coords(g.coords)}</coordinates></LineString>"
    if t == "Polygon":
        inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{_kml_coords(r.coords)}</coordinates>"
                        f"</LinearRing></innerBoundaryIs>" for r in g.interiors)
        return (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_kml_coords(g.exterior.coords)}"
                f"</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>")
    if hasattr(g, "geoms"):
        return "<MultiGeometry>" + "".join(_kml_geom(p) for p in g.geoms if not p.is_empty) + "</MultiGeometry>"
    return ""


def write_kmz(path: Path, layers: dict[str, list[tuple]], title: str) -> None:
    """layers: name -> list of (geometry in lon/lat, props). One folder per layer."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"<name>{escape(title)}</name>"]
    for name, (line, fill) in STYLE.items():
        out.append(f'<Style id="{name}"><LineStyle><color>{line}</color><width>1.5</width></LineStyle>'
                   f'<PolyStyle><color>{fill}</color></PolyStyle>'
                   f'<IconStyle><color>{line}</color><scale>0.8</scale></IconStyle></Style>')
    for name, feats in layers.items():
        if not feats:
            continue
        out.append(f"<Folder><name>{escape(name)}</name>")
        for g, p in feats:
            label = p.get("id") or p.get("layer") or ""
            ext = "".join(f'<Data name="{escape(str(k))}"><value>{escape(str(_clean(v)))}</value></Data>'
                          for k, v in p.items() if v is not None)
            out.append(f"<Placemark><name>{escape(str(label))}</name><styleUrl>#{name}</styleUrl>"
                       f"<ExtendedData>{ext}</ExtendedData>{_kml_geom(g)}</Placemark>")
        out.append("</Folder>")
    out.append("</Document></kml>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", "\n".join(out))


def write_shapefile(path: Path, feats: list[tuple], wkt: str) -> None:
    """One shapefile per geometry family. Field names are cut to 10 characters."""
    import shapefile

    if not feats:
        return
    fam = feats[0][0].geom_type
    if any(g.geom_type.replace("Multi", "") != fam.replace("Multi", "") for g, _ in feats):
        groups = {}
        for g, p in feats:
            groups.setdefault(g.geom_type.replace("Multi", ""), []).append((g, p))
        for gt, fs in groups.items():
            write_shapefile(path.with_name(f"{path.stem}_{gt.lower()}{path.suffix}"), fs, wkt)
        return
    shp_type = {"Point": shapefile.POINT, "LineString": shapefile.POLYLINE,
                "Polygon": shapefile.POLYGON}[fam.replace("Multi", "")]
    keys, kinds = [], {}
    for _, p in feats:
        for k, v in p.items():
            if k not in kinds:
                keys.append(k)
                kinds[k] = "N" if isinstance(_clean(v), (int, float)) and not isinstance(v, bool) else "C"
            elif kinds[k] == "N" and not (v is None or isinstance(_clean(v), (int, float))):
                kinds[k] = "C"
    short, used = {}, set()
    for k in keys:
        s = k[:10]
        i = 1
        while s in used:
            s = f"{k[:8]}{i:02d}"
            i += 1
        used.add(s)
        short[k] = s
    w = shapefile.Writer(str(path.with_suffix("")), shapeType=shp_type)
    for k in keys:
        if kinds[k] == "N":
            ints = all(isinstance(_clean(p.get(k)), int) or p.get(k) is None for _, p in feats)
            w.field(short[k], "N", 18, 0 if ints else 6)
        else:
            w.field(short[k], "C", 254)
    for g, p in feats:
        if shp_type == shapefile.POINT:
            w.point(g.x, g.y)
        elif shp_type == shapefile.POLYLINE:
            parts = [list(l.coords) for l in getattr(g, "geoms", [g])]
            w.line([[(x, y) for x, y, *_ in pt] for pt in parts])
        else:
            rings = []
            for poly in getattr(g, "geoms", [g]):
                poly = orient(poly, sign=-1.0)  # shapefile: outer ring clockwise
                rings.append([(x, y) for x, y, *_ in poly.exterior.coords])
                rings += [[(x, y) for x, y, *_ in r.coords] for r in poly.interiors]
            w.poly(rings)
        rec = []
        for k in keys:
            v = _clean(p.get(k))
            rec.append(None if v is None else (v if kinds[k] == "N" else str(v)[:254]))
        w.record(*rec)
    w.close()
    path.with_suffix(".prj").write_text(wkt, encoding="utf-8")

STYLE.setdefault("station_areas", ("ff000000", "10000000"))
STYLE.setdefault("inverter_areas", ("ff0000ff", "1a0000ff"))
STYLE.setdefault("combiner_areas", ("ff00a5ff", "4000a5ff"))
STYLE.setdefault("circuit_areas", ("ff00ff00", "3300ff00"))
