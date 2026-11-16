"""Casilla Solar PV (Valencina de la Concepción, Sevilla), route A: hierarchy in layer names.
import os

Source: 54.1 ANEXO URBANÍSTICO CASILLA rev1, page 37 (Implantación General Ortofoto, 1:6,500, 147 PDF layers).
Station layers `0_CT Nº1` … `Nº14` hold each CT's trackers (outline box + module cross-lines); CT symbols on
`00 - Transformadores`, labels `CT n`. Combiner boxes and inverters are not drawn on this sheet.
"""
import sys, json, pickle, collections, re, shutil, csv
from pathlib import Path
import numpy as np
import pymupdf as fitz
from scipy import ndimage
from shapely.geometry import box, Point, LineString, mapping
from shapely.ops import unary_union, linemerge
from pyproj import Transformer, CRS as PCRS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit
from pvgeo.rollup import rollup

SRC = Path(os.environ.get("CASILLA_PDF", "src/casilla.pdf"))
W = Path(os.environ.get("CASILLA_WORK", "."))   # p37.pkl, trackers.pkl, anchor.json
OUT = Path(os.environ.get("CASILLA_OUT", "out/casilla"))
PAGE = 37
C = 2.29284                    # m per pt, model viewport measure (1:6,500)
CRS = "EPSG:25829"             # ETRS89 / UTM 29N (Valencina, west of 6° W)
ANCHOR_EN = (758593.10, 4149382.19)
PRINTED = dict(modules=140812, trackers=1678, wp=350, mwp=49.3)
MOD_PER_STRING = 28
PFX = "54.1_19 Rexf - Implantación1|"


def frame(x, y):
    return x * C, -y * C


def main():
    d = fitz.open(SRC); p = d[PAGE - 1]
    dr = pickle.load(open(W / "p37.pkl", "rb"))
    tr = pickle.load(open(W / "trackers.pkl", "rb"))
    anchor = json.load(open(W / "anchor.json"))
    # --- stations: CT symbol clusters, named by the nearest "CT n" label
    P = np.array([((g["rect"].x0 + g["rect"].x1) / 2, (g["rect"].y0 + g["rect"].y1) / 2) for g in dr
                  if g.get("layer", "") == PFX + "00 - Transformadores"])
    step = 0.25
    H, _, _ = np.histogram2d(P[:, 1], P[:, 0], bins=[np.arange(0, 842 + step, step), np.arange(0, 1191 + step, step)])
    lab, n = ndimage.label(ndimage.binary_dilation(H > 0, np.ones((5, 5))))
    sym = [((c[1] + 0.5) * step, (c[0] + 0.5) * step) for c in ndimage.center_of_mass(H, lab, range(1, n + 1))]
    words = p.get_text("words")
    labels = []
    for k, w in enumerate(words):
        if w[4] == "CT" and k + 1 < len(words) and re.fullmatch(r"\d{1,2}", words[k + 1][4]):
            labels.append((int(words[k + 1][4]), ((w[0] + words[k + 1][2]) / 2, (w[1] + w[3]) / 2)))
    from scipy.optimize import linear_sum_assignment
    Cm = np.array([[np.hypot(s[0] - l[1][0], s[1] - l[1][1]) for l in labels] for s in sym])
    r, c = linear_sum_assignment(Cm)
    st_pt = {labels[b][0]: sym[a] for a, b in zip(r, c)}
    lab_dist = {labels[b][0]: float(Cm[a, b] * C) for a, b in zip(r, c)}
    # --- trackers per CT layer, strings derived
    feats = collections.defaultdict(list)
    rows = []
    n_trk = n_str = n_mod = 0
    for ct in range(1, 15):
        T = tr[ct]["T"]; mr = tr[ct]["rows"]
        sid = f"CT-{ct:02d}"
        # numbering: west to east by column, north to south within a column
        cols = sorted(range(len(T)), key=lambda k: (round(T[k][0] / 3.0), T[k][1]))
        n_ct_trk = len(T); n_ct_str = 0; n_ct_mod = 0
        for num, k in enumerate(cols, 1):
            t = T[k]
            x0, y1 = frame(t[0], t[1]); x1, y0 = frame(t[2], t[3])
            poly = box(x0, y0, x1, y1)
            mods = 2 * mr[k]
            ns = mods // MOD_PER_STRING
            tid = f"{sid}-T{num:03d}"
            feats["trackers"].append((poly, dict(id=tid, level="tracker", station=sid, n_modules=mods, n_strings=ns,
                                                 width_m=round(x1 - x0, 2), length_m=round(y1 - y0, 1),
                                                 source=f"layer 0_CT Nº{ct}")))
            rows.append(dict(id=tid, level="tracker", parent=sid, station=sid, tracker=tid, n_strings=ns, n_modules=mods,
                             X=poly.centroid.x, Y=poly.centroid.y, location_source="tracker outline", derived=""))
            L = (y1 - y0) / ns
            for s in range(ns):
                sp = box(x0, y1 - (s + 1) * L, x1, y1 - s * L)          # S1 at the north end
                sname = f"{tid}-S{s + 1}"
                feats["strings"].append((sp, dict(id=sname, level="string", station=sid, tracker=tid, n_modules=MOD_PER_STRING,
                                                  derived="string split: 28 modules, thirds of the tracker from the north end")))
                rows.append(dict(id=sname, level="string", parent=tid, station=sid, tracker=tid, string=sname,
                                 n_modules=MOD_PER_STRING, X=sp.centroid.x, Y=sp.centroid.y,
                                 location_source="part of its tracker", derived="string split (28 modules) and geometry"))
            n_ct_str += ns; n_ct_mod += mods
        sx, sy = frame(*st_pt[ct])
        feats["stations"].append((Point(sx, sy), dict(id=sid, level="station", n_trackers=n_ct_trk, n_strings=n_ct_str,
                                                      n_modules=n_ct_mod, label_offset_m=round(lab_dist[ct], 1))))
        rows.append(dict(id=sid, level="station", parent="", station=sid, n_trackers=n_ct_trk, n_strings=n_ct_str,
                         n_modules=n_ct_mod, X=sx, Y=sy, location_source="CT symbol (layer 00 - Transformadores)", derived=""))
        n_trk += n_ct_trk; n_str += n_ct_str; n_mod += n_ct_mod
    # --- context lines: plant contour, service roads
    for role, layer in (("site", "0_Contorno Planta"), ("roads", "0_Caminos servicio")):
        segs = []
        for g in dr:
            if g.get("layer") == PFX + layer:
                for it in g["items"]:
                    if it[0] == "l":
                        segs.append(LineString([frame(it[1].x, it[1].y), frame(it[2].x, it[2].y)]))
        if not segs:
            continue
        if role == "site":
            # dashed contour as drawn: one multi-line feature (closing the dashes merges it with the floodplain)
            from shapely.geometry import MultiLineString
            m = linemerge(unary_union(segs))
            feats["site"].append((MultiLineString(list(getattr(m, "geoms", [m]))),
                                  dict(id="plant-contour", level="site", source="layer 0_Contorno Planta, dashed as drawn")))
        else:
            m = linemerge(unary_union(segs))
            for k, ln in enumerate(getattr(m, "geoms", [m])):
                if ln.length > 5:
                    feats[role].append((ln, dict(id=f"{role}-{k + 1}", level=role, source=f"layer {layer}")))
    # --- roll-up: only what the children determine and the layout lacks
    derived, notes = rollup({"strings": feats["strings"], "stations": feats["stations"]})
    feats.update(derived)
    return feats, rows, dict(trackers=n_trk, strings=n_str, modules=n_mod), notes, anchor


def export(feats, rows, totals, notes, anchor):
    for dd in ("gis", "shp", "hierarchy", "qa", "config"):
        (OUT / dd).mkdir(parents=True, exist_ok=True)
    src = np.array([anchor["anchor_frame_m"]]); dst = np.array([ANCHOR_EN])
    T = fit(src, dst, "translation", CRS, 1.0, ids=["printed plant coordinate"])
    T.note = ("Provisional: the printed plant coordinate (X 758593.10, Y 4149382.19, ETRS89 29N) placed at the centre of the "
              "location circle on sheet 1 (page 35), carried to this sheet through the 14 CT symbols (0.1-0.7 m residuals). "
              "Scale 1 and drawing north = grid north. Correct with the georeferencer KMZ mode.")
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    proj = lambda g: writers.project(g, lambda xy: np.c_[T.apply(xy[:, 0], xy[:, 1])])
    ll = lambda g: writers.project(g, lambda xy: np.c_[to_ll.transform(xy[:, 0], xy[:, 1])])
    wkt = PCRS.from_user_input(CRS).to_wkt("WKT1_ESRI")
    order = ["site", "roads", "station_areas", "stations", "trackers", "strings"]
    kmz = {}
    for L in order:
        fs = feats.get(L, [])
        if not fs:
            continue
        pf = [(proj(g), p) for g, p in fs]; lf = [(ll(g), p) for g, p in pf]
        writers.write_geojson(OUT / f"gis/{L}.geojson", lf)
        writers.write_shapefile(OUT / f"shp/{L}.shp", pf, wkt)
        kmz[L] = lf
    writers.STYLE.setdefault("roads", ("ff7f7f7f", "00000000"))
    writers.STYLE.setdefault("trackers", ("ff00a5ff", "4000a5ff"))
    writers.write_kmz(OUT / "gis/casilla.kmz", kmz, "Casilla Solar PV (provisional placement)")
    # hierarchy
    path = {}
    for r in rows:
        path[r["id"]] = (path.get(r["parent"], "") + " > " if r["parent"] else "") + r["id"]
    cols = ["id", "level", "parent", "path", "station", "tracker", "string", "n_trackers", "n_strings", "n_modules",
            "location_source", "derived", "x_frame_m", "y_frame_m", "easting", "northing", "lon", "lat"]
    with open(OUT / "hierarchy/hierarchy.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows:
            e, n_ = T.apply(r["X"], r["Y"]); lo, la = to_ll.transform(e, n_)
            o = {k: r.get(k, "") for k in cols}
            o.update(path=path[r["id"]], x_frame_m=round(r["X"], 2), y_frame_m=round(r["Y"], 2), easting=round(float(e), 2),
                     northing=round(float(n_), 2), lon=round(lo, 7), lat=round(la, 7))
            w.writerow(o)
    kids = collections.defaultdict(list)
    for r in rows:
        kids[r["parent"]].append(r)
    def node(r):
        e, n_ = T.apply(r["X"], r["Y"]); lo, la = to_ll.transform(e, n_)
        dct = {k: v for k, v in r.items() if k not in ("X", "Y") and v not in ("", None)}
        dct.update(lon=round(lo, 7), lat=round(la, 7))
        ch = [node(c) for c in kids.get(r["id"], [])]
        if ch:
            dct["children"] = ch
        return dct
    (OUT / "hierarchy/hierarchy.json").write_text(json.dumps(dict(site="Casilla Solar PV", crs=CRS, placement="provisional",
                                                                  stations=[node(r) for r in kids[""]]), indent=1))
    (OUT / "config/transform.json").write_text(T.to_json())
    (OUT / "config/gcps.csv").write_text("id,x_frame_m,y_frame_m,easting,northing,source\n"
                                         f"printed plant coordinate,{anchor['anchor_frame_m'][0]:.2f},{anchor['anchor_frame_m'][1]:.2f},"
                                         f"{ANCHOR_EN[0]},{ANCHOR_EN[1]},memoria p.5 and every sheet; placed at the location-circle centre (sheet 1)\n")
    shutil.copy(W / "anchor.json", OUT / "config/anchor_from_sheet1.json")
    return T


if __name__ == "__main__":
    feats, rows, tot, notes, anchor = main()
    pickle.dump(dict(feats=feats, rows=rows, tot=tot, notes=notes), open(W / "assembled.pkl", "wb"))
    T = export(feats, rows, tot, notes, anchor)
    print(tot, notes, {k: len(v) for k, v in feats.items()})
