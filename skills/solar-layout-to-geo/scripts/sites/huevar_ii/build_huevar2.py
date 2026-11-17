"""Huévar II (Huévar del Aljarafe, Sevilla), 49.65 MWp: route C with printed box labels.

Source: 01_POV Proyecto de ejecución_HII (Sin datos).pdf (Junta de Andalucía public consultation, 344 pp.),
p. 199 "Planta de ubicación de inversores + trafos", 1:3,500, flattened (no layers, no viewports).
Read: 2,448 trackers (black quads 3.6 x 21.6 pt), 252 string boxes (black = 20 inputs / 10 trackers,
red = 18 inputs / 9 trackers), every box's "X-Y" label (subcampo-box), 14 inverter-station symbols + "INV.xx".
Derived: which trackers each box collects (minimum total distance within box capacity; the drawing shows the
groups only as dashed separators), 2 strings of 26 modules per tracker (memoria), the placement (one point).
"""
import os, sys, json, pickle, collections, re, csv
from pathlib import Path
import numpy as np
import pymupdf as fitz
from shapely.geometry import Polygon, Point, box as sbox
from shapely.affinity import scale as sscale
from pyproj import Transformer, CRS as PCRS
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit
from pvgeo.rollup import rollup

SRC = Path(os.environ.get("HUEVAR2_PDF", "huevar2.pdf"))
OUT = Path(os.environ.get("HUEVAR2_OUT", "out/huevar_ii"))
PAGE = 199
C = 3500 * 0.0254 / 72            # 1:3,500 on an A1 sheet (title block, scale bar); tracker = 26.7 m
CRS = "EPSG:25829"                # memoria: ETRS89 huso 29
PLANT_EN = (740429.06, 4140133.99)  # memoria pp. 12 and 24 "coordenadas de la planta fotovoltaica"
PRINTED = dict(trackers=2448, modules=127296, subcampos=14, boxes=252, per_subcampo={"*": 162, "": 180})
CELLS = Path(os.environ.get("HUEVAR2_CELLS", "cells.npy"))
STAR = {3, 4, 5, 6}               # subcampos printed with * (162 trackers, 18-input boxes)


def main():
    d = fitz.open(SRC); p = d[PAGE - 1]
    dr = p.get_drawings()
    fr = lambda x, y: (x * C, -y * C)
    blk = lambda x: tuple(round(v, 3) for v in (x.get("color") or ()))
    trk, trk_r = [], []
    for x in dr:
        r = x["rect"]
        if x["type"] == "s" and blk(x) == (0, 0, 0) and 3.4 < r.width < 3.9 and 21.3 < r.height < 21.9:
            q = x["items"][0][1]
            trk.append(Polygon([fr(pt.x, pt.y) for pt in (q.ul, q.ur, q.lr, q.ll)])); trk_r.append(r)
    tc = np.array([t.centroid.coords[0] for t in trk])
    boxes = []
    for x in dr:
        r = x["rect"]
        if x["type"] == "fs" and len(x["items"]) == 24 and 3.7 < r.height < 4.4 and 6.8 < r.width < 8.3:
            col = "red" if tuple(round(v, 2) for v in x["fill"]) == (1, 0, 0) else "black"
            c = fr((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            if not any(np.hypot(c[0] - b[0][0], c[1] - b[0][1]) < 1 for b in boxes):
                boxes.append((c, col))
    # labels "X-Y" with character positions
    labels = []
    for b in p.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                txt = "".join(ch["c"] for ch in s["chars"])
                for m in re.finditer(r"(\d{1,2})-\s*(\d{1,2})", txt):
                    ch = s["chars"][m.start():m.end()]
                    x0 = min(c["bbox"][0] for c in ch); x1 = max(c["bbox"][2] for c in ch)
                    y0 = min(c["bbox"][1] for c in ch); y1 = max(c["bbox"][3] for c in ch)
                    labels.append((int(m[1]), int(m[2]), fr((x0 + x1) / 2, (y0 + y1) / 2)))
    # legend samples: boxes far from every tracker
    tt = cKDTree(tc)
    boxes = [b for b in boxes if tt.query(b[0])[0] < 40]
    # box <-> label, one to one (a label printed twice is a candidate twice)
    B = np.array([b[0] for b in boxes]); L = np.array([l[2] for l in labels])
    Cm = np.hypot(B[:, None, 0] - L[None, :, 0], B[:, None, 1] - L[None, :, 1])
    ri, ci = linear_sum_assignment(Cm)
    named = {}
    for a, b in zip(ri, ci):
        k = labels[b][:2]
        if k in named:
            continue
        named[k] = dict(xy=B[a], col=boxes[a][1], dist=float(Cm[a, b]), label_xy=L[b])
    notes = []
    far = {k: round(v["dist"], 1) for k, v in named.items() if v["dist"] > 25}
    if far:
        notes.append(f"box-label pairs over 25 m apart (check): {far}")
    wrong_col = [k for k, v in named.items() if (v["col"] == "red") != (k[0] in STAR)]
    if wrong_col:
        notes.append(f"box colour disagrees with its subcampo type: {wrong_col}")
    # stations
    st_sym = []
    for x in dr:
        r = x["rect"]
        if x["type"] in ("f", "fs") and tuple(round(v, 2) for v in (x.get("fill") or ())) == (0, 0, 0) and len(x["items"]) == 24 \
                and 4.4 < min(r.width, r.height) < 5.0 and 10.6 < max(r.width, r.height) < 11.4:
            st_sym.append(fr((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    st_sym = [s for s in st_sym if tt.query(s)[0] < 60]
    inv_lab = []
    for w in p.get_text("words"):
        m = re.fullmatch(r"INV\.(\d{2})", w[4])
        if m:
            inv_lab.append((int(m[1]), fr((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)))
    S = np.array(st_sym); IL = np.array([l[1] for l in inv_lab])
    Cs = np.hypot(S[:, None, 0] - IL[None, :, 0], S[:, None, 1] - IL[None, :, 1])
    r2, c2 = linear_sum_assignment(Cs)
    station = {inv_lab[b][0]: S[a] for a, b in zip(r2, c2)}
    # trackers -> boxes within capacity, minimum total distance (tracker centre to box); same subcampo only
    keys = sorted(named)
    cap = {k: (9 if named[k]["col"] == "red" else 10) for k in keys}
    slots = [k for k in keys for _ in range(cap[k])]
    SX = np.array([named[k]["xy"] for k in slots])
    D = np.hypot(tc[:, None, 0] - SX[None, :, 0], tc[:, None, 1] - SX[None, :, 1])
    # the dashed "agrupación de 9/10 trackers" rectangles (cells.py): a box's group is the cell holding its label
    cells = np.load(CELLS) if CELLS.exists() else None
    if cells is not None:
        def cell(xy):
            px, py = int(xy[0] / C * 2), int(-xy[1] / C * 2)
            return int(cells[py, px]) if 0 <= py < cells.shape[0] and 0 <= px < cells.shape[1] else 0
        def rcell(r):   # majority cell under the tracker (centres can sit on a dashed separator)
            sub = cells[int(r.y0 * 2):int(r.y1 * 2) + 1, int(r.x0 * 2):int(r.x1 * 2) + 1].ravel(); sub = sub[sub > 0]
            return collections.Counter(sub.tolist()).most_common(1)[0][0] if len(sub) else -1
        tcell = np.array([rcell(r) for r in trk_r]); bcell = np.array([cell(named[k]["label_xy"]) for k in slots])
        D = D + 1000.0 * (tcell[:, None] != bcell[None, :])
    ra, ca = linear_sum_assignment(D)
    assign = {int(a): slots[b] for a, b in zip(ra, ca)}
    dist = {int(a): float(D[a, b]) for a, b in zip(ra, ca)}
    # features
    feats = collections.defaultdict(list); rows = []
    for s, xy in sorted(station.items()):
        sid = f"CT{s:02d}"
        feats["stations"].append((Point(xy), dict(id=sid, station=sid, inverter=f"INV{s:02d}", kind="inverter station",
                                                    location_source="drawn symbol + INV.xx label", derived=False)))
        rows.append(dict(id=sid, level="station", parent="", station=sid, X=xy[0], Y=xy[1], location_source="drawn symbol",
                         derived=False))
        rows.append(dict(id=f"INV{s:02d}", level="inverter", parent=sid, station=sid, inverter=f"INV{s:02d}", X=xy[0],
                         Y=xy[1], location_source="station symbol", derived=False))
    by_box = collections.defaultdict(list)
    for t, k in assign.items():
        by_box[k].append(t)
    for k in keys:
        s, n = k; sid = f"CT{s:02d}"; iv = f"INV{s:02d}"; cb = f"{s}.{n}"
        ts = sorted(by_box[k], key=lambda t: (tc[t][0], -tc[t][1]))
        xy = named[k]["xy"]
        feats["combiners"].append((Point(xy), dict(id=cb, station=sid, inverter=iv, combiner=cb,
                                                    kind="caja string 18 entradas" if named[k]["col"] == "red" else "caja string 20 entradas",
                                                    n_trackers=len(ts), location_source="drawn box + 'X-Y' label", derived=False)))
        rows.append(dict(id=cb, level="combiner", parent=iv, station=sid, inverter=iv, combiner=cb, n_trackers=len(ts),
                         n_strings=2 * len(ts), n_modules=52 * len(ts), X=xy[0], Y=xy[1], location_source="drawn box",
                         derived=False))
        for i, t in enumerate(ts, 1):
            tid = f"{cb}-T{i:02d}"
            feats["trackers"].append((trk[t], dict(id=tid, station=sid, inverter=iv, combiner=cb, tracker=tid,
                                                    box_assignment="derived (capacity, distance)", derived=True)))
            g = trk[t]; (x0, y0, x1, y1) = g.bounds
            ym = (y0 + y1) / 2
            for j, half in enumerate((g.intersection(sbox(x0 - 1, ym, x1 + 1, y1 + 1)), g.intersection(sbox(x0 - 1, y0 - 1, x1 + 1, ym))), 1):
                sid2 = f"{tid}-S{j}"
                feats["strings"].append((half, dict(id=sid2, station=sid, inverter=iv, combiner=cb, string=sid2, modules=26,
                                                    geometry="derived (half tracker)", derived=True)))
                c = half.centroid
                rows.append(dict(id=sid2, level="string", parent=cb, station=sid, inverter=iv, combiner=cb, string=sid2,
                                 n_modules=26, X=c.x, Y=c.y, location_source="half of a drawn tracker", derived=True))
    # site: fence (pink) outline segments
    segs = []
    for x in dr:
        if tuple(round(v, 3) for v in (x.get("fill") or ())) == (1.0, 0.498, 1.0) and x["type"] == "fs":
            r = x["rect"]; segs.append(fr((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    fence = np.array([sg for sg in segs if tt.query(sg)[0] < 120])
    der, rn = rollup({"strings": feats["strings"], "stations": feats["stations"], "combiners": feats["combiners"]},
                     levels=["inverter", "combiner"])
    feats.update(der); notes += rn
    per_sc = collections.Counter(assign[t][0] for t in assign)
    tot = dict(trackers_outside_their_box_cell=int(sum(1 for v in dist.values() if v >= 1000)), trackers=len(trk), trackers_assigned=len(assign), boxes=len(named), boxes_black=sum(v["col"] == "black" for v in named.values()),
               boxes_red=sum(v["col"] == "red" for v in named.values()), stations=len(station), strings=len(feats["strings"]),
               modules=26 * len(feats["strings"]), trackers_per_subcampo=dict(sorted(per_sc.items())),
               max_tracker_box_m=round(max(v % 1000 for v in dist.values()), 1), median_tracker_box_m=round(float(np.median([v % 1000 for v in dist.values()])), 1))
    return feats, rows, tot, notes, fence


def export(feats, rows, tot, notes, fence):
    for dd in ("gis", "shp", "hierarchy", "qa", "config"):
        (OUT / dd).mkdir(parents=True, exist_ok=True)
    centre = (fence.min(0) + fence.max(0)) / 2
    T = fit(np.array([centre]), np.array([PLANT_EN]), "translation", CRS, C, ids=["plant coordinate (memoria)"])
    T.note = ("Provisional: the memoria's plant coordinate (ETRS89 UTM 29, X 740429.06 Y 4140133.99) placed at the centre "
              "of the fence's bounding box; scale 1, drawing north = grid north. Correct with the georeferencer KMZ mode.")
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    proj = lambda g: writers.project(g, lambda xy: np.c_[T.apply(xy[:, 0], xy[:, 1])])
    ll = lambda g: writers.project(g, lambda xy: np.c_[to_ll.transform(xy[:, 0], xy[:, 1])])
    wkt = PCRS.from_user_input(CRS).to_wkt("WKT1_ESRI")
    kmz = {}
    for L in ["inverter_areas", "combiner_areas", "stations", "combiners", "trackers", "strings"]:
        fs = feats.get(L, [])
        if not fs:
            continue
        pf = [(proj(g), p) for g, p in fs]; lf = [(ll(g), p) for g, p in pf]
        writers.write_geojson(OUT / f"gis/{L}.geojson", lf)
        writers.write_shapefile(OUT / f"shp/{L}.shp", pf, wkt)
        kmz[L] = lf
    writers.STYLE.setdefault("trackers", ("ff00a5ff", "4000a5ff"))
    writers.write_kmz(OUT / "gis/huevar_ii.kmz", kmz, "Huévar II (provisional placement)")
    lvl = ["station", "inverter", "combiner", "string"]
    rows = sorted(rows, key=lambda r: lvl.index(r["level"]))
    path = {}
    for r in rows:
        path[r["id"]] = (path.get(r["parent"], "") + " > " if r["parent"] else "") + r["id"]
    cols = ["id", "level", "parent", "path", "station", "inverter", "combiner", "string", "n_trackers", "n_strings", "n_modules",
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
    (OUT / "hierarchy/hierarchy.json").write_text(json.dumps(dict(site="Huévar II", crs=CRS, placement="provisional",
                                                                  stations=[node(r) for r in kids[""]]), indent=1))
    (OUT / "config/transform.json").write_text(T.to_json())
    (OUT / "config/gcps.csv").write_text("id,x_frame_m,y_frame_m,easting,northing,source\n"
                                         f"plant coordinate,{centre[0]:.2f},{centre[1]:.2f},{PLANT_EN[0]},{PLANT_EN[1]},"
                                         "memoria pp.12/24, placed at the fence bounding-box centre (provisional)\n")
    return T


if __name__ == "__main__":
    feats, rows, tot, notes, fence = main()
    T = export(feats, rows, tot, notes, fence)
    (OUT / "qa/build_stats.json").write_text(json.dumps(dict(tot=tot, notes=notes, transform=json.loads(T.to_json())), indent=1))
    print(json.dumps(tot, indent=1)); print(notes); print({k: len(v) for k, v in feats.items()})
