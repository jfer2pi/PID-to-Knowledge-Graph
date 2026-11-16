"""Transformer correction: match each sheet's transformer symbol to the same symbol in the key plan.

The key plan draws every station's transformer at true size (2.5 m), as does the 1:1,200 sheet, so their
centres agree to about 0.1 m. Run after register_ac.py; writes cache/ctin_match.json with a shift per sheet.

usage: python ctin_match.py <layered sheet with key-plan layers> 1 2 ... 10
"""
import os, sys, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import numpy as np
import pymupdf as fitz
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial import cKDTree
from load import load, disp
import register_ac as RG

KEY_TRAFO_LAYER = "KEYPLAN|TRAFO"      # key-plan xref layer holding the transformer hatch


def key_trafos(sheet):
    s = disp(load(sheet))
    K = fitz.Rect(*RG.KEY)
    P = np.array([((g["D"].x0 + g["D"].x1) / 2, (g["D"].y0 + g["D"].y1) / 2) for g in s["dr"]
                  if g.get("layer", "").endswith(KEY_TRAFO_LAYER) and K.contains(g["D"])])
    lab = fcluster(linkage(P, "single"), 1.5, "distance")
    T = np.array([P[lab == k].mean(0) for k in np.unique(lab)])
    return np.c_[(T[:, 0] - RG.KEY[0]) * RG.CK, -(T[:, 1] - RG.KEY[1]) * RG.CK]


def detail_trafo(H):
    """densest olive hatch: mean-shift in a 6.4 pt window"""
    P = np.array(H["E"]["olive"]); t = cKDTree(P)
    cnt = np.array([len(t.query_ball_point(p, 3.0)) for p in P])
    c = P[np.argmax(cnt)]
    for _ in range(10):
        Q = P[np.max(abs(P - c), 1) < 3.2]; c = Q.mean(0)
    return c, len(Q)


def main(layered, sheets):
    keyM = key_trafos(layered)
    reg = json.load(open(f"{WORK}/cache/register.json"))
    out = {}
    for i in sheets:
        H = pickle.load(open(f"{WORK}/cache/H{i:02d}.pkl", "rb")); R = reg[str(i)]; C = R["m_per_pt"]
        c, n = detail_trafo(H)
        X, Y = c[0] * C + R["dX"], -c[1] * C + R["dY"]
        k = int(np.argmin(np.hypot(keyM[:, 0] - X, keyM[:, 1] - Y)))
        out[str(i)] = dict(trafo_pt=[float(c[0]), float(c[1])], trafo_n=int(n), key_ctin=k,
                           shift=[float(keyM[k, 0] - X), float(keyM[k, 1] - Y)])
        print(i, "shift %.2f %.2f m" % tuple(out[str(i)]["shift"]))
    json.dump(dict(key_trafo_m=keyM.tolist(), sheets=out), open(f"{WORK}/cache/ctin_match.json", "w"), indent=1)


if __name__ == "__main__":
    main(int(sys.argv[1]), [int(a) for a in sys.argv[2:]])
