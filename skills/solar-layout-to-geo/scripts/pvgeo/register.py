"""Register detail sheets onto a key sheet (the general layout).

Design packages often split a plant over many sheets: one per inverter block,
each a zoomed viewport at its own scale. The sheets share no coordinates, but
they all draw the same streams, roads and module rows in the same colours.

Each sheet's model viewport gives its scale (metres per PDF point). With the
scale known and every sheet drawn north-up, only a translation is unknown. It
is found by rasterising the shared colour classes of both sheets at the same
metres-per-pixel and cross-correlating them (normalised, per colour channel),
with a sub-pixel refinement of the peak.

Frames:
- sheet pt: PDF points of a page, origin top-left, y down
- raster metres: metres from the top-left corner of that page's model viewport
- key pt: PDF points of the key page; all output geometry lives here
"""

from __future__ import annotations

import colorsys
import re
from collections import Counter

import numpy as np

PAPER_MM_PER_PT = 0.3528


def model_viewport(doc, page) -> tuple[float, list[float]] | None:
    """(metres per pt, clip [x0, y0, x1, y1] in top-left page coordinates) of
    the largest measured viewport that is not the paper viewport."""
    obj = " ".join(doc.xref_object(page.xref).split())
    vps = re.findall(r"/BBox \[ ([\d. -]+) \] /Measure .*?/X \[ << /C ([\d.]+)", obj)
    best = None
    H = page.rect.height
    for bb, c in vps:
        c = float(c)
        if abs(c - PAPER_MM_PER_PT) < 0.002:
            continue
        x0, y0, x1, y1 = (float(v) for v in bb.split())
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        area = (x1 - x0) * (y1 - y0)
        if best is None or area > best[0]:
            best = (area, c, [x0, H - y1, x1, H - y0])
    if best is None:
        return None
    m = best[1] / 1000.0 if best[1] > 50 else best[1]
    return m, best[2]


def _rgb(x) -> tuple | None:
    col = x.get("fill") if "f" in (x.get("type") or "") else x.get("color")
    return tuple(round(c, 3) for c in col) if col else None


def _saturated(rgb) -> bool:
    if len(rgb) != 3:
        return False
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return s > 0.3 and v > 0.25


def colour_counts(drawings, clip) -> Counter:
    c = Counter()
    for x in drawings:
        r = x["rect"]
        if r.x1 < clip[0] or r.x0 > clip[2] or r.y1 < clip[1] or r.y0 > clip[3]:
            continue
        rgb = _rgb(x)
        if rgb and _saturated(rgb):
            c[rgb] += 1
    return c


def _points(x):
    pts = []
    for it in x["items"]:
        k = it[0]
        if k == "l":
            pts += [it[1], it[2]]
        elif k == "c":
            pts += [it[1], it[4]]
        elif k == "qu":
            q = it[1]
            pts += [q.ul, q.ur, q.lr, q.ll, q.ul]
        elif k == "re":
            r = it[1]
            pts += [r.tl, r.tr, r.br, r.bl, r.tl]
    return pts


def rasterise(drawings, clip, m_per_pt, colours, res=1.0) -> np.ndarray:
    """One channel per colour; filled shapes filled, strokes drawn 1 px wide."""
    from PIL import Image, ImageDraw

    w = int((clip[2] - clip[0]) * m_per_pt / res) + 1
    h = int((clip[3] - clip[1]) * m_per_pt / res) + 1
    chans = {c: Image.new("L", (w, h), 0) for c in colours}
    draws = {c: ImageDraw.Draw(im) for c, im in chans.items()}
    for x in drawings:
        rgb = _rgb(x)
        if rgb not in chans:
            continue
        r = x["rect"]
        if r.x1 < clip[0] or r.x0 > clip[2] or r.y1 < clip[1] or r.y0 > clip[3]:
            continue
        xy = [((p.x - clip[0]) * m_per_pt / res, (p.y - clip[1]) * m_per_pt / res) for p in _points(x)]
        if len(xy) < 2:
            continue
        if "f" in x["type"] and len(xy) >= 3:
            draws[rgb].polygon(xy, fill=255)
        else:
            draws[rgb].line(xy, fill=255, width=1)
    return np.stack([np.asarray(chans[c], dtype=np.float32) / 255.0 for c in colours])


class KeyCorrelator:
    """Pre-computed FFTs of the key raster, reused for every sheet."""

    def __init__(self, key: np.ndarray, max_shape: tuple[int, int]):
        self.key = key
        H, W = key.shape[1:]
        self.shape = (H + max_shape[0], W + max_shape[1])
        self.Fk = [np.fft.rfft2(ch, self.shape) for ch in key]
        self.Fk2 = np.fft.rfft2((key ** 2).sum(axis=0), self.shape)

    def match(self, tpl: np.ndarray) -> dict:
        H, W = self.key.shape[1:]
        h, w = tpl.shape[1:]
        num = np.zeros(self.shape)
        for ch, Fk in zip(tpl, self.Fk):
            num += np.fft.irfft2(Fk * np.conj(np.fft.rfft2(ch - ch.mean(), self.shape)), self.shape)
        energy = np.fft.irfft2(self.Fk2 * np.conj(np.fft.rfft2(np.ones((h, w)), self.shape)), self.shape)
        score = num / np.sqrt(np.maximum(energy, 1e-6))
        score[:, W:] = -np.inf
        score[H:, :] = -np.inf
        iy, ix = np.unravel_index(np.argmax(score), score.shape)
        best = score[iy, ix]

        def sub(a, b, c):
            den = a - 2 * b + c
            return 0.0 if not np.isfinite(den) or den == 0 else 0.5 * (a - c) / den

        dy = sub(score[iy - 1, ix], best, score[iy + 1, ix]) if 0 < iy < H - 1 else 0.0
        dx = sub(score[iy, ix - 1], best, score[iy, ix + 1]) if 0 < ix < W - 1 else 0.0
        masked = score.copy()
        masked[max(iy - 15, 0):iy + 16, max(ix - 15, 0):ix + 16] = -np.inf
        second = np.max(masked)
        return {"offset_px": [float(ix + dx), float(iy + dy)], "score": float(best),
                "peak_ratio": float(best / second) if second > 0 else float("inf")}
