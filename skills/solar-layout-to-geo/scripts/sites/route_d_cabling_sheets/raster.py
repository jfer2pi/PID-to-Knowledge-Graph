"""Circuits from a colour raster: green N1 cables, cut at level-1 boards (TA)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import numpy as np
import pymupdf as fitz
from scipy import ndimage
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import pdf

PX = 4.0  # pixels per pt


def render(i, clip):
    fitz.TOOLS.set_aa_level(0)
    p = fitz.open(pdf(i))[0]
    pix = p.get_pixmap(matrix=fitz.Matrix(PX, PX), clip=fitz.Rect(clip), alpha=False)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
    fitz.TOOLS.set_aa_level(8)
    return a


def is_green(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g > 200) & (r < 120) & (b < 90)


def is_purple(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (b > 220) & (r > 150) & (g > 90) & (g < 170)


def green_mask(a, k=16):
    G = ndimage.binary_dilation(is_green(a), np.ones((3, 3)))
    return bridge(G, k)


def bridge(mask, k):
    """fill gaps up to k px between mask pixels along rows and columns"""
    out = mask.copy()
    for axis in (0, 1):
        m = mask
        fwd = ndimage.maximum_filter1d(m.astype(np.uint8), k + 1, axis=axis, origin=-(k // 2)) > 0
        bwd = ndimage.maximum_filter1d(m.astype(np.uint8), k + 1, axis=axis, origin=(k // 2)) > 0
        out |= fwd & bwd
    return out


def circuits(i, clip, tas, k=16):
    a = render(i, clip)
    G = green_mask(a, k)
    # cut at TA boxes (+2 px)
    x0, y0 = clip[0], clip[1]
    for t in tas:
        c0 = int((t[0] - x0) * PX) - 3; c1 = int((t[2] - x0) * PX) + 3
        r0 = int((t[1] - y0) * PX) - 3; r1 = int((t[3] - y0) * PX) + 3
        G[max(r0, 0):r1, max(c0, 0):c1] = False
    lab, n = ndimage.label(G, structure=np.ones((3, 3)))
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    return lab, sizes, a


def label_at(lab, clip, x, y, r=3):
    c = int((x - clip[0]) * PX); rr = int((y - clip[1]) * PX)
    R = int(r * PX)
    win = lab[max(rr - R, 0):rr + R + 1, max(c - R, 0):c + R + 1]
    v = win[win > 0]
    if not len(v):
        return 0
    # nearest labelled pixel
    ys, xs = np.nonzero(win)
    cy, cx = rr - max(rr - R, 0), c - max(c - R, 0)
    j = np.argmin((ys - cy) ** 2 + (xs - cx) ** 2)
    return int(win[ys[j], xs[j]])


def touching(lab, clip, t, pad=4):
    x0, y0 = clip[0], clip[1]
    c0 = int((t[0] - x0) * PX) - 3 - pad; c1 = int((t[2] - x0) * PX) + 3 + pad
    r0 = int((t[1] - y0) * PX) - 3 - pad; r1 = int((t[3] - y0) * PX) + 3 + pad
    win = lab[max(r0, 0):r1, max(c0, 0):c1]
    return set(np.unique(win[win > 0]).tolist())
