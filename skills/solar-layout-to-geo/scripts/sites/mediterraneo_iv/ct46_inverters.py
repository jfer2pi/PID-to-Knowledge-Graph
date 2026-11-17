"""PSFV Mediterráneo IV, CT4.6 study block: string inverters and their structures from p. 11 (Trazado nivel 1 BT, 1:1,500).

Each inverter's structures are outlined in a colour by string count (legend: 8 yellow, 12 pink, 14 green) and labelled
INV-06-nn. p. 11 is registered onto p. 12 by a translation vote on structure centres (scale from the viewports: 1:1,500
vs 1:5,000). Every p. 12 structure inside an outline goes to that outline's inverter. Adds 'inverter' to the CT4.6
structures in med4_extract.pkl and writes ct46_inverters.pkl.
"""
import os, pickle, collections, re
import numpy as np
import pymupdf as fitz
from shapely.geometry import LineString, Point, box
from shapely.ops import polygonize, unary_union
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment

PDF = os.environ.get("MED4_PDF", "med4.pdf")
OUTLINE = {(1.0, 0.0, 0.25): 12, (0.18, 0.72, 0.0): 14, (1.0, 0.5, 0.87): 8}   # legend "AGRUPACIONES"
K = 1.76378 / 0.52911                                                           # p. 11 pt per p. 12 pt


def main():
    E = pickle.load(open("med4_extract.pkl", "rb"))
    p = fitz.open(PDF)[10]
    dr = p.get_drawings()
    col = lambda x: tuple(round(v, 2) for v in (x.get("color") or x.get("fill") or ()))
    # structures on p. 11 (grey quads, as on p. 12)
    S11 = []
    for x in dr:
        if col(x) == (0.6, 0.6, 0.6) and x["rect"].x1 < 1140:
            for it in x["items"]:
                if it[0] == "qu":
                    r = it[1].rect
                    if 15 < min(r.width, r.height) and max(r.width, r.height) < 80:
                        S11.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    S11 = np.unique(np.round(np.array(S11), 2), axis=0)
    S12 = np.array([((s["rect"][0] + s["rect"][2]) / 2, (s["rect"][1] + s["rect"][3]) / 2) for s in E["structures"]])
    M = S12 * K
    D = (S11[None, :, :] - M[:, None, :]).reshape(-1, 2)
    H = collections.Counter(map(tuple, np.round(D).astype(int)))
    t = np.array(H.most_common(1)[0][0], float)
    tr = cKDTree(S11)
    for _ in range(4):
        dd, ii = tr.query(M + t); ok = dd < 3
        t = t + np.median(S11[ii[ok]] - (M[ok] + t), axis=0)
    dd, ii = tr.query(M + t)
    reg = dict(K=K, t=t.tolist(), matched=int((dd < 1.5).sum()), rms_pt=float(np.sqrt(np.mean(dd[dd < 1.5] ** 2))))
    # group outlines -> faces
    segs, segcol = [], []
    for x in dr:
        c = col(x)
        if c in OUTLINE and x["rect"].x1 < 1140 and max(x["rect"].width, x["rect"].height) > 5:
            for it in x["items"]:
                if it[0] == "l" and abs(it[1] - it[2]) > 0.05:
                    segs.append(LineString([(it[1].x, it[1].y), (it[2].x, it[2].y)])); segcol.append(c)
                elif it[0] in ("re", "qu"):
                    r = it[1] if it[0] == "re" else it[1].rect
                    segs.append(box(*r).exterior); segcol.append(c)
    faces = [f for f in polygonize(unary_union(segs)) if f.area > 50]
    # face colour = colour of the outline segments along it
    from shapely.strtree import STRtree
    st = STRtree(segs)
    fcol = []
    for f in faces:
        v = collections.Counter(segcol[i] for i in st.query(f.exterior.buffer(0.3)) if segs[i].intersection(f.exterior.buffer(0.3)).length > 1)
        fcol.append(v.most_common(1)[0][0] if v else None)
    labels = []
    for w in p.get_text("words"):
        m = re.fullmatch(r"INV-06-(\d{2})", w[4])
        if m and w[0] < 1140:
            labels.append((int(m[1]), Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)))
    labels = list({l[0]: l for l in labels}.values())
    # structures (p. 12 CT4.6 ones) -> face
    ct46 = [i for i, s in enumerate(E["structures"]) if s["ct"] == "CT4.6" or s.get("ct") is None]
    sface = {}
    for i in range(len(E["structures"])):
        q = Point(*(M[i] + t))
        for k, f in enumerate(faces):
            if f.contains(q):
                sface[i] = k; break
    used = sorted(set(sface.values()))
    # faces <-> labels: one to one by distance (labels sit inside or on the top edge of their group)
    Cm = np.array([[faces[k].distance(l[1]) for l in labels] for k in used])
    r_, c_ = linear_sum_assignment(Cm)
    finv = {used[a]: (labels[b][0], float(Cm[a, b])) for a, b in zip(r_, c_)}
    # a group cut into two faces by a crossing outline: leftover faces join the nearest label
    for a, k in enumerate(used):
        if k not in finv:
            b = int(np.argmin(Cm[a])); finv[k] = (labels[b][0], float(Cm[a, b]))
            print("  extra face", k, "-> INV-06-%02d" % labels[b][0], "%.1f pt" % Cm[a, b], "structures", sum(1 for v in sface.values() if v == k))
    out = collections.defaultdict(list)
    for i, k in sface.items():
        if k in finv:
            out[finv[k][0]].append(i)
    # inverter symbol position: the label point mapped back to p. 12 frame
    inv_xy = {n: tuple(((np.array(l.coords[0]) - t) / K)) for n, l in labels}
    strings = {n: sum(E["structures"][i]["strings"] for i in v) for n, v in out.items()}
    col_of = {finv[k][0]: OUTLINE.get(fcol[k]) for k in finv}
    pickle.dump(dict(reg=reg, members=dict(out), inv_xy=inv_xy, strings=strings, legend_strings=col_of), open("ct46_inverters.pkl", "wb"))
    print("reg", reg, "faces", len(faces), "used", len(used), "labels", len(labels))
    print("inverters with structures", len(out), "strings", sum(strings.values()))
    print(sorted((n, strings[n], col_of.get(n)) for n in strings))
    print("CT of member structures", collections.Counter(E["structures"][i]["ct"] for v in out.values() for i in v))


if __name__ == "__main__":
    main()
