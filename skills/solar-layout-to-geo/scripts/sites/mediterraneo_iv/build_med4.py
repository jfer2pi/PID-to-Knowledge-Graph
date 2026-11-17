"""PSFV Mediterráneo IV (Monforte del Cid, Alicante), 40.55 MWp: route C (flattened), CTs from a colour inset.

Run from the work dir after extract_med4.py and ct46_inverters.py.
Read: structures by type (p. 12 grey quads; sizes match the legend), 8 CT skids, which CT each structure belongs to
(inset coloured by CT) where the inset shows it, the CT4.6 block's 30 string inverters and their outlined groups (p. 11),
8 CT coordinates printed on p. 8. Derived: CT of structures outside the inset (nearest CT-coloured structure; the
nearest-CT-symbol rule agrees for all of them), strings as columns of each structure, CT4.6 structures outside every
outline (nearest outlined neighbour), inverter points (label position).
"""
import os, sys, json, pickle, collections, csv
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon, Point, LineString, MultiLineString
from pyproj import Transformer, CRS as PCRS
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pvgeo import writers
from pvgeo.transform import fit
from pvgeo.rollup import rollup

OUT = Path(os.environ.get("MED4_OUT", "out/mediterraneo_iv"))
C = 1.76378                          # m/pt, p. 12 model viewport (1:5,000)
CRS = "EPSG:25830"                   # "COORDENADAS UTM ETRS89 H30"
CT_EN = {"CT4.1": (703246.36, 4252175.94), "CT4.2": (703779.02, 4252600.52), "CT4.3": (704020.08, 4252918.49),
         "CT4.4": (703732.86, 4252933.50), "CT4.5": (703903.94, 4253012.69), "CT4.6": (703402.77, 4252967.92),
         "CT4.7": (704051.21, 4253213.03), "CT4.8": (703720.79, 4253238.49)}          # p. 8 table
INVERTERS_PER_CT = {"CT4.1": 21, "CT4.2": 26, "CT4.3": 25, "CT4.4": 28, "CT4.5": 25, "CT4.6": 30, "CT4.7": 15}  # p. 22
PRINTED = {"8x6D1V14": 1, "2Vx6D1V14": 8, "4D1V7": 164, "4D1V14": 105, "6D1V14": 105, "2D1V14": 139, "2Hx6D1V14": 3,
           "S_4H7": 73, "modules": 54852, "mwp": 40.55, "ct46_strings": 336}


def fr(x, y):
    return x * C, -y * C


def main():
    E = pickle.load(open("med4_extract.pkl", "rb")); I = pickle.load(open("ct46_inverters.pkl", "rb"))
    S = E["structures"]
    cen = np.array([((s["rect"][0] + s["rect"][2]) / 2, (s["rect"][1] + s["rect"][3]) / 2) for s in S])
    # CT outside the inset: nearest structure that the inset colours
    known = [i for i, s in enumerate(S) if s["ct"]]
    tk = cKDTree(cen[known])
    names = sorted(E["cts"]); P = np.array([E["cts"][k]["xy"] for k in names])
    ct, ct_src, disagree = {}, {}, 0
    for i, s in enumerate(S):
        if s["ct"]:
            ct[i], ct_src[i] = s["ct"], "inset colour (read)"
        else:
            a = S[known[tk.query(cen[i])[1]]]["ct"]; b = names[int(np.argmin(np.hypot(*(P - cen[i]).T)))]
            disagree += a != b
            ct[i], ct_src[i] = a, "outside the inset: nearest coloured structure (derived)"
    inv, inv_src = {}, {}
    for n, v in I["members"].items():
        for i in v:
            inv[i], inv_src[i] = n, "outlined group on p. 11 (read)"
            ct[i] = "CT4.6"
    m46 = [i for i in inv]
    t46 = cKDTree(cen[m46])
    for i in range(len(S)):
        if ct[i] == "CT4.6" and i not in inv:
            inv[i] = inv[m46[t46.query(cen[i])[1]]]; inv_src[i] = "CT4.6 outside every outline: nearest group (derived)"
    # features
    feats = collections.defaultdict(list); rows = []
    for k, d in E["cts"].items():
        xy = fr(*d["xy"])
        feats["stations"].append((Point(xy), dict(id=k, station=k, transformers=2 if d["pieces"] > 80 else 1,
                                                    inverters_unifilar=INVERTERS_PER_CT.get(k, ""), location_source="drawn skid (p. 12)",
                                                    derived=False)))
        rows.append(dict(id=k, level="station", parent="", station=k, X=xy[0], Y=xy[1], location_source="drawn skid", derived=False,
                         n_inverters=INVERTERS_PER_CT.get(k, "")))
    for n, xy in sorted(I["inv_xy"].items()):
        iv = f"INV-06-{n:02d}"; e = fr(*xy)
        feats["inverters"].append((Point(e), dict(id=iv, station="CT4.6", inverter=iv, location_source="label INV-06-nn (p. 11)",
                                                   derived=False)))
        rows.append(dict(id=iv, level="inverter", parent="CT4.6", station="CT4.6", inverter=iv, X=e[0], Y=e[1],
                         location_source="label position (p. 11)", derived=False))
    order = sorted(range(len(S)), key=lambda i: (ct[i], -round(cen[i][1] / 6), cen[i][0]))
    count = collections.Counter()
    for i in order:
        s = S[i]; k = ct[i]; count[k] += 1
        tid = f"{k}-T{count[k]:03d}"
        q = [fr(*pt) for pt in s["quad"]]
        poly = Polygon(q)
        iv = f"INV-06-{inv[i]:02d}" if i in inv else ""
        par = iv or k
        feats["structures"].append((poly, dict(id=tid, station=k, inverter=iv, type=s["type"], strings=s["strings"],
                                                modules=s["strings"] * s["mps"], ct_source=ct_src[i],
                                                inverter_source=inv_src.get(i, ""), derived=ct_src[i].endswith("(derived)"))))
        # strings = column cells; 4D-1V-7 strings span two columns
        (x0, y0), (x1, y1) = np.min(q, axis=0), np.max(q, axis=0)
        cols, nrows = s["cols"], s["rows"]
        per = cols * nrows // s["strings"]
        cells = [(r, c) for r in range(nrows) for c in range(cols)]
        for j in range(s["strings"]):
            grp = cells[j * per:(j + 1) * per]
            cs = [c for _, c in grp]; r = grp[0][0]
            gx0 = x0 + min(cs) * (x1 - x0) / cols; gx1 = x0 + (max(cs) + 1) * (x1 - x0) / cols
            gy1 = y1 - r * (y1 - y0) / nrows; gy0 = y1 - (r + 1) * (y1 - y0) / nrows
            g = Polygon([(gx0, gy0), (gx1, gy0), (gx1, gy1), (gx0, gy1)])
            sid = f"{tid}-S{j + 1}"
            pr = dict(id=sid, station=k, string=sid, structure=tid, modules=s["mps"], geometry="derived (structure column)",
                      derived=True)
            if iv:
                pr["inverter"] = iv
            feats["strings"].append((g, pr))
            rows.append(dict(id=sid, level="string", parent=par, station=k, inverter=iv, string=sid, structure=tid, type=s["type"],
                             n_modules=s["mps"], X=g.centroid.x, Y=g.centroid.y, location_source="column of a drawn structure",
                             derived=True))
    segs = [(fr(*a), fr(*b)) for a, b in E["site"]["mv_cable"]]
    if segs:
        feats["mv_cable"].append((MultiLineString(segs), dict(id="mv_cable", note="traza de MT subterránea (p. 12)")))
    der, notes = rollup({"strings": feats["strings"], "stations": feats["stations"], "inverters": feats["inverters"]})
    feats.update(der)
    by = collections.Counter(s["type"] for s in S)
    strings_ct = collections.Counter()
    for g, p in feats["strings"]:
        strings_ct[p["station"]] += 1
    tot = dict(structures=len(S), by_type=dict(by), strings=len(feats["strings"]), modules=28 * len(feats["strings"]),
               strings_per_ct=dict(sorted(strings_ct.items())), ct_from_inset=len(known), ct_derived=len(S) - len(known),
               ct_rule_disagreements=int(disagree), ct46_inverters=len(I["members"]),
               ct46_strings_in_outlines=sum(I["strings"].values()),
               ct46_strings_per_inverter={f"INV-06-{n:02d}": v for n, v in sorted(I["strings"].items())},
               inset_registration=E["reg"], p11_registration=I["reg"])
    return feats, rows, tot, notes


def export(feats, rows, tot, notes):
    for dd in ("gis", "shp", "hierarchy", "qa", "config"):
        (OUT / dd).mkdir(parents=True, exist_ok=True)
    ids = sorted(CT_EN)
    st = {p["id"]: g for g, p in feats["stations"]}
    src = np.array([st[k].coords[0] for k in ids]); dst = np.array([CT_EN[k] for k in ids])
    T = fit(src, dst, "similarity", CRS, C, ids=ids)
    T.note = "Similarity fit on the 8 CT coordinates printed on p. 8 (ETRS89 UTM 30N), at the centres of the drawn CT skids (p. 12)."
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    proj = lambda g: writers.project(g, lambda xy: np.c_[T.apply(xy[:, 0], xy[:, 1])])
    ll = lambda g: writers.project(g, lambda xy: np.c_[to_ll.transform(xy[:, 0], xy[:, 1])])
    wkt = PCRS.from_user_input(CRS).to_wkt("WKT1_ESRI")
    kmz = {}
    for L in ["mv_cable", "station_areas", "inverter_areas", "stations", "inverters", "structures", "strings"]:
        fs = feats.get(L, [])
        if not fs:
            continue
        pf = [(proj(g), p) for g, p in fs]; lf = [(ll(g), p) for g, p in pf]
        writers.write_geojson(OUT / f"gis/{L}.geojson", lf)
        writers.write_shapefile(OUT / f"shp/{L}.shp", pf, wkt)
        kmz[L] = lf
    writers.STYLE.setdefault("mv_cable", ("ff0000ff", "00000000"))
    writers.STYLE.setdefault("structures", ("ff00a5ff", "4000a5ff"))
    writers.write_kmz(OUT / "gis/mediterraneo_iv.kmz", kmz, "PSFV Mediterráneo IV")
    lvl = ["station", "inverter", "string"]
    rows = sorted(rows, key=lambda r: lvl.index(r["level"]))
    path = {}
    for r in rows:
        path[r["id"]] = (path.get(r["parent"], "") + " > " if r["parent"] else "") + r["id"]
    cols = ["id", "level", "parent", "path", "station", "inverter", "structure", "type", "string", "n_inverters", "n_modules",
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
    (OUT / "hierarchy/hierarchy.json").write_text(json.dumps(dict(site="PSFV Mediterráneo IV", crs=CRS,
                                                                  stations=[node(r) for r in kids[""]]), indent=1))
    (OUT / "config/transform.json").write_text(T.to_json())
    with open(OUT / "config/gcps.csv", "w") as f:
        f.write("id,x_frame_m,y_frame_m,easting,northing,source\n")
        for k, s_, d_ in zip(ids, src, dst):
            f.write(f"{k},{s_[0]:.2f},{s_[1]:.2f},{d_[0]},{d_[1]},printed on p. 8; CT skid centre on p. 12\n")
    (OUT / "qa/build_stats.json").write_text(json.dumps(dict(tot=tot, notes=notes, transform=json.loads(T.to_json()),
                                                             residuals=T.residuals, rmse=T.rmse_m), indent=1, default=str))
    return T


if __name__ == "__main__":
    feats, rows, tot, notes = main()
    T = export(feats, rows, tot, notes)
    print(json.dumps({k: v for k, v in tot.items() if "registration" not in k}, indent=1)); print(notes)
    print("rmse", T.rmse_m, "scale", T.scale, "rot", T.rotation_deg); print([(r["id"], round(r["r"], 2)) for r in T.residuals])
