"""PSFV Mediterráneo IV: structures, CT symbols and the CT colour inset from p. 12 (Disposición general, trazado de MT).

p. 12 is flattened (no layers). Structures are grey quads whose size gives the type (legend: xD-1V-14 columns etc.);
the inset at the bottom right repeats the plant at about 0.41x with every structure stroked in its CT's colour
(legend CT4.1 ... CT4.8). The inset is registered onto the main view by a similarity fit on structure column edges.
Writes med4_extract.pkl in the working directory.
"""
import os, pickle, collections
import numpy as np
import pymupdf as fitz
from scipy.spatial import cKDTree
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

PDF = os.environ.get("MED4_PDF", "med4.pdf")
PAGE = 12
INSET = fitz.Rect(870, 780, 1115, 1075)
CT_COL = {(1.0, 0.5, 0.0): "CT4.1", (0.0, 0.25, 1.0): "CT4.2", (1.0, 0.87, 0.5): "CT4.3", (0.75, 0.0, 1.0): "CT4.4",
          (0.0, 0.5, 1.0): "CT4.5", (1.0, 0.0, 1.0): "CT4.6", (0.36, 0.72, 0.0): "CT4.7", (0.87, 0.0, 0.22): "CT4.8"}
# drawn size (pt, w x h) -> type, strings, modules per string, columns across, rows
TYPES = [((5.6, 10.6), "2D-1V-14", 2, 28, 2, 1), ((11.1, 10.6), "4D-1V-14", 4, 28, 4, 1),
         ((16.65, 10.6), "6D-1V-14", 6, 28, 6, 1), ((11.1, 5.35), "4D-1V-7", 2, 28, 2, 1),
         ((16.65, 21.65), "2Vx6D-1V-14", 12, 28, 6, 2), ((9.5, 2.95), "S_4H7", 1, 28, 1, 1)]


def col(x):
    return tuple(round(v, 2) for v in (x.get("color") or ()))


def find_cts(p, dr, main=True):
    """hatched CT skid symbols: dense clusters of short orange/pink strokes, named by the nearest CT4.x label"""
    from scipy.optimize import linear_sum_assignment
    inside = (lambda r: r.x1 < 870) if main else (lambda r: r in INSET and r.y1 < 1070)
    lo, hi = ((1.2, 2.6), (2.8, 4.2)) if main else ((0.5, 0.9), (1.1, 1.6))
    pcs, P = [], []
    for x in dr:
        c = tuple(round(v, 2) for v in (x.get("fill") or x.get("color") or ()))
        r = x["rect"]
        if c in [(1.0, 0.5, 0.0), (0.87, 0.0, 0.22), (1.0, 0.0, 0.25)] and max(r.width, r.height) < (4 if main else 1.7) and inside(r):
            P.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)); pcs.append(r)
    P = np.array(P); pr = cKDTree(P).query_pairs(0.7 if main else 0.3, output_type="ndarray")
    n, lab = connected_components(sp.coo_matrix((np.ones(len(pr)), (pr[:, 0], pr[:, 1])), shape=(len(P), len(P))), directed=False)
    sym = []
    for k in range(n):
        idx = np.where(lab == k)[0]
        if len(idx) < 40:
            continue
        U = fitz.Rect(pcs[idx[0]])
        for i in idx:
            U |= pcs[i]
        w, h = sorted([U.width, U.height])
        if lo[0] < w < lo[1] and hi[0] < h < hi[1]:
            sym.append(((U.x0 + U.x1) / 2, (U.y0 + U.y1) / 2, len(idx)))
    labels = [(w[4], ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) for w in p.get_text("words")
              if w[4].startswith("CT4.") and inside(fitz.Rect(w[:4])) and w[1] < 1070]
    names = sorted(set(l[0] for l in labels))
    Cm = np.array([[min(np.hypot(sy[0] - l[1][0], sy[1] - l[1][1]) for l in labels if l[0] == nm) for nm in names] for sy in sym])
    r_, c_ = linear_sum_assignment(Cm)
    return {names[b]: dict(xy=sym[a][:2], pieces=sym[a][2], label_dist_pt=float(Cm[a, b])) for a, b in zip(r_, c_)
            if Cm[a, b] < (25 if main else 12)}


def main():
    p = fitz.open(PDF)[PAGE - 1]
    dr = p.get_drawings()
    S = []
    for x in dr:
        r = x["rect"]
        if col(x) != (0.6, 0.6, 0.6) or len(x["items"]) != 1 or x["items"][0][0] != "qu" or r.x1 > 1150 or r in INSET:
            continue
        best = min(TYPES, key=lambda t: abs(r.width - t[0][0]) + abs(r.height - t[0][1]))
        if abs(r.width - best[0][0]) + abs(r.height - best[0][1]) > 0.5:
            continue
        q = x["items"][0][1]
        S.append(dict(quad=[(pt.x, pt.y) for pt in (q.ul, q.ur, q.lr, q.ll)], type=best[1], strings=best[2], mps=best[3],
                      cols=best[4], rows=best[5], rect=tuple(r)))
    # de-duplicate
    seen, SS = set(), []
    for s in S:
        k = (round(s["rect"][0], 1), round(s["rect"][1], 1), s["type"])
        if k not in seen:
            seen.add(k); SS.append(s)
    S = SS
    # main vertical edges (midpoints)
    Vm = []
    for s in S:
        x0, y0, x1, y1 = s["rect"]
        for k in range(s["cols"] + 1):
            Vm.append((x0 + k * (x1 - x0) / s["cols"], (y0 + y1) / 2))
    Vm = np.array(Vm)
    # inset coloured vertical segments
    Vi, Ci = [], []
    for x in dr:
        c = col(x)
        if c not in CT_COL or not (x["rect"] in INSET) or x["rect"].y1 > 1070:
            continue
        for it in x["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) < 0.15 and 1.8 < abs(a.y - b.y) < 4.6:
                    Vi.append(((a.x + b.x) / 2, (a.y + b.y) / 2)); Ci.append(CT_COL[c])
            elif it[0] in ("qu", "re"):          # small structures (S_4H7) are stroked boxes in the inset
                r = it[1].rect if it[0] == "qu" else it[1]
                if 0.8 < max(r.width, r.height) < 12:
                    Vi.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)); Ci.append(CT_COL[c])
        # some CTs are drawn as filled structures in the inset: vote with the fill centre
        fc = tuple(round(v, 2) for v in (x.get("fill") or ()))
    for x in dr:
        fc = tuple(round(v, 2) for v in (x.get("fill") or ()))
        if x["type"] in ("f", "fs") and fc in CT_COL and x["rect"] in INSET and x["rect"].y1 < 1070 and 1.0 < max(x["rect"].width, x["rect"].height) < 12:
            r = x["rect"]; Vi.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)); Ci.append(CT_COL[fc])
    Vi = np.array(Vi)
    # main <-> inset: similarity on the CT symbols both draw (hatched skids), named by their labels
    cts = find_cts(p, dr, main=True)
    cts_in = find_cts(p, dr, main=False)
    common = sorted(set(cts) & set(cts_in))
    src = np.array([cts[k]["xy"] for k in common]); dst = np.array([cts_in[k]["xy"] for k in common])
    n_ = len(common)
    A = np.zeros((2 * n_, 4)); L = np.zeros(2 * n_)
    A[0::2] = np.c_[src[:, 0], -src[:, 1], np.ones(n_), np.zeros(n_)]
    A[1::2] = np.c_[src[:, 1], src[:, 0], np.zeros(n_), np.ones(n_)]
    L[0::2], L[1::2] = dst[:, 0], dst[:, 1]
    a_, b_, tx, ty = np.linalg.lstsq(A, L, rcond=None)[0]
    sc, th, t = float(np.hypot(a_, b_)), float(np.arctan2(b_, a_)), np.array([tx, ty])
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    res = np.hypot(*((sc * src @ R.T + t) - dst).T)
    reg = dict(scale=sc, rot_deg=float(np.degrees(th)), t=t.tolist(), points=common, residual_pt=res.round(3).tolist())
    # CT per structure: vote of inset segments inside the mapped structure (slightly grown)
    Ci = np.array(Ci)
    for s in S:
        x0, y0, x1, y1 = s["rect"]
        c = (sc * np.array([[(x0 + x1) / 2, (y0 + y1) / 2]]) @ R.T + t)[0]
        hw, hh = sc * (x1 - x0) / 2 + 0.2, sc * (y1 - y0) / 2 + 0.2
        m = (np.abs(Vi[:, 0] - c[0]) <= hw) & (np.abs(Vi[:, 1] - c[1]) <= hh)
        v = collections.Counter(Ci[m].tolist())
        s["ct"] = v.most_common(1)[0][0] if v else None
        s["ct_votes"] = dict(v)
    # site lines
    def lines(color, minlen=0):
        segs = []
        for x in dr:
            if col(x) == color and x["rect"].x1 < 870 or (col(x) == color and x["rect"].y1 < 780 and x["rect"].x1 < 1150):
                for it in x["items"]:
                    if it[0] == "l" and abs(it[1] - it[2]) >= minlen:
                        segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        return segs
    site = dict(mv_cable=lines((1.0, 0.0, 0.25), 0.5))
    pickle.dump(dict(structures=S, cts=cts, reg=reg, site=site), open("med4_extract.pkl", "wb"))
    print("structures", len(S), collections.Counter(s["type"] for s in S))
    print("ct", collections.Counter(s["ct"] for s in S))
    print("no-CT structures", [(s["type"], [round(v) for v in s["rect"]]) for s in S if not s["ct"]][:10])
    print("mixed votes", sum(1 for s in S if len(s["ct_votes"]) > 1))
    print("reg", reg); print("cts", {k: (tuple(round(v, 1) for v in d["xy"]), d["pieces"], round(d["label_dist_pt"], 1)) for k, d in cts.items()})


if __name__ == "__main__":
    main()
