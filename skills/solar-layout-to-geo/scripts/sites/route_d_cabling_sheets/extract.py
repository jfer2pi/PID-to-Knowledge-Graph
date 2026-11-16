"""the route D site: per-sheet extraction by drawing style (works on layered and flattened sheets).

Everything is in displayed page points (rotation applied), y down.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, re, pickle, collections
import numpy as np
import pymupdf as fitz
from scipy import ndimage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load, disp, viewports, pdf

KEY = fitz.Rect(890, 20, 1170, 222)       # key plan box, same on every sheet

GREY = (0.5, 0.5, 0.5)
RED = (1.0, 0.0, 0.0)
YELLOW = (1.0, 1.0, 0.0)
OLIVE = (0.87, 0.87, 0.0)
GREEN = (0.25, 1.0, 0.0)
PURPLE = (0.75, 0.5, 1.0)
LABEL = (1.0, 1.0, 0.5)


class _C(tuple):
    def __eq__(self, o):
        return o is not None and len(o) == len(self) and all(abs(a - b) < 0.03 for a, b in zip(self, o))
    __hash__ = tuple.__hash__


def col(g, fill=False):
    c = g.get("fill") if fill else g.get("color")
    return _C(round(x, 2) for x in c) if c else None


def cluster(pts, tol):
    """merge points closer than tol; returns centres"""
    from scipy.cluster.hierarchy import fcluster, linkage
    if len(pts) < 2:
        return list(pts)
    P = np.asarray(pts)
    lab = fcluster(linkage(P, "single"), tol, "distance")
    return [tuple(P[lab == k].mean(0)) for k in np.unique(lab)]


def dedup_boxes(bs, tol=1.0):
    out = []
    for b in sorted(bs):
        if not any(abs(b[0] - o[0]) < tol and abs(b[1] - o[1]) < tol and abs(b[2] - o[2]) < tol for o in out):
            out.append(b)
    return out


def tables_from_cells(dr, region, px=4):
    """Rasterise thin grey strokes, close cell interiors, return table boxes (pt)."""
    x0, y0, x1, y1 = region
    W, H = int((x1 - x0) * px) + 2, int((y1 - y0) * px) + 2
    im = np.zeros((H, W), np.uint8)
    import cv2
    for g in dr:
        if g["type"] != "s" or col(g) != GREY or not (0.05 < (g.get("width") or 0) < 0.2):
            continue
        R = g["D"]
        if not (R.x0 >= x0 and R.x1 <= x1 and R.y0 >= y0 and R.y1 <= y1):
            continue
        for it in g["Di"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                cv2.line(im, (int((a.x - x0) * px), int((a.y - y0) * px)), (int((b.x - x0) * px), int((b.y - y0) * px)), 1, 1)
            elif it[0] in ("re", "qu"):
                r = it[1].rect if it[0] == "qu" else it[1]
                cv2.rectangle(im, (int((r.x0 - x0) * px), int((r.y0 - y0) * px)), (int((r.x1 - x0) * px), int((r.y1 - y0) * px)), 1, 1)
    # fill cell interiors: cells are ~9x17 px; a close of 3 px fills the grid but keeps table gaps (>2 px)?
    filled = ndimage.binary_fill_holes(im > 0)
    filled = ndimage.binary_opening(filled, np.ones((3, 3)))
    lab, n = ndimage.label(filled)
    out = []
    for sl in ndimage.find_objects(lab):
        h = (sl[0].stop - sl[0].start) / px
        w = (sl[1].stop - sl[1].start) / px
        out.append((x0 + sl[1].start / px, y0 + sl[0].start / px, x0 + sl[1].stop / px, y0 + sl[0].stop / px, w, h))
    return out


def extract(i):
    s = disp(load(i))
    dr = s["dr"]
    vps = viewports(s)
    det = [v for v in vps if 0.38 < v["C"] < 0.5]
    m_per_pt = det[0]["C"] if det else None
    clip = det[0]["clip"] if det else None
    layered = bool(det)
    E = dict(sheet=i, layered=layered, m_per_pt=m_per_pt, clip=tuple(clip) if clip else None)

    def inside(R):
        if KEY.intersects(R) or R.x0 >= 950:
            return False
        return clip is None or clip.intersects(R)

    # tables
    tabs = []
    if layered:
        for g in dr:
            if g.get("layer", "").endswith("GEN-MODULOS") and inside(g["D"]):
                R = g["D"]; tabs.append((R.x0, R.y0, R.x1, R.y1))
    else:
        reg = (20, 20, 950, 830)
        tabs = []
        for x0, y0, x1, y1, w, h in tables_from_cells(dr, reg):
            if not (7.5 < h < 9.6) or w < 40:
                continue
            n = max(1, round((w + 0.66) / 48.08))
            tw = (w - (n - 1) * 0.66) / n
            for k in range(n):
                a = x0 + k * (tw + 0.66)
                tabs.append((a, y0, a + tw, y1))
    E["tables_raw"] = tabs
    # dots: red fused connectors
    reds = []
    for g in dr:
        R = g["D"]
        if not inside(R) or R.width > 2.2 or R.height > 2.2:
            continue
        if (g["type"] in ("f", "fs") and col(g, True) == RED) or (g["type"] == "s" and col(g) == RED):
            reds.append(((R.x0 + R.x1) / 2, (R.y0 + R.y1) / 2))
    E["red_raw"] = reds
    E["dots"] = cluster(reds, 1.3)
    # TA boxes (level-1 boards), yellow fill
    tas = []
    for g in dr:
        R = g["D"]
        if g["type"] in ("f", "fs") and col(g, True) == YELLOW and inside(R) and 1.5 < min(R.width, R.height) < 3.5 and 3.5 < max(R.width, R.height) < 6:
            tas.append((R.x0, R.y0, R.x1, R.y1))
    E["ta_raw"] = dedup_boxes(tas)
    # row label boxes
    labs = []
    for g in dr:
        R = g["D"]
        if g["type"] in ("f", "fs") and col(g, True) == LABEL and 25 < R.width < 35 and 8 < R.height < 12 and not KEY.intersects(R) and R.x0 < 950:
            labs.append((R.x0, R.y0, R.x1, R.y1))
    E["label_raw"] = dedup_boxes(labs)
    # CTIN symbol strokes (olive)
    E["olive"] = [((g["D"].x0 + g["D"].x1) / 2, (g["D"].y0 + g["D"].y1) / 2) for g in dr if col(g) == OLIVE and inside(g["D"])]
    # cables
    def segs(colour):
        out = []
        for g in dr:
            if g["type"] == "s" and col(g) == colour and inside(g["D"]) and (g.get("width") or 0) > 0.3:
                for it in g["Di"]:
                    if it[0] == "l":
                        out.append((it[1].x, it[1].y, it[2].x, it[2].y))
                    elif it[0] == "c":
                        out.append((it[1].x, it[1].y, it[4].x, it[4].y))
        return out
    E["green"] = segs(GREEN)
    E["purple"] = segs(PURPLE)
    E["words"] = s["words"]
    return E


if __name__ == "__main__":
    for i in map(int, sys.argv[1:]):
        E = extract(i)
        print(i, "layered" if E["layered"] else "flat", "tables", len(E["tables_raw"]), "dots", len(E["dots"]),
              "TA", len(E["ta_raw"]), "labels", len(E["label_raw"]), "olive", len(E["olive"]),
              "green", len(E["green"]), "purple", len(E["purple"]))
        pickle.dump(E, open(f"{WORK}/cache/E{i:02d}.pkl", "wb"))
