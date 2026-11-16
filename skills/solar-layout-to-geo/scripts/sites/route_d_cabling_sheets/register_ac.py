"""Place each 1:1200 detail sheet in the common key-plan frame (1:15,000, identical on all sheets).

Key frame metres: X = (x_pt - KX0) * CK, Y = -(y_pt - KY0) * CK.
Detail sheet metres: X = x_pt * C, Y = -y_pt * C. Unknown: a translation per sheet.
Found by maximising IoU between the sheet's highlighted block (yellow in its key plan)
and its tables rasterised at the key-plan pixel size, then refined at 0.25 m against
the block outline edges.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, pickle, json
import numpy as np
from scipy import ndimage, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster

W = WORK
KEY = (890, 20, 1170, 222)
CK = 5.29362
C_DEFAULT = 0.4216


def key_mask(i):
    a = raster.render(i, KEY)
    Y = (a[..., 0] > 200) & (a[..., 1] > 200) & (a[..., 2] < 180)
    Y = ndimage.binary_closing(Y, np.ones((3, 3)))
    Y = ndimage.binary_fill_holes(Y)
    return Y  # px at raster.PX per pt


def detail_tables_m(H):
    C = H["E"]["m_per_pt"] or C_DEFAULT
    out = []
    for a, (t, src) in H["tab"].items():
        out.append((t[0] * C, -t[3] * C, t[2] * C, -t[1] * C))
    return np.array(out), C


def rasterise(boxes, x0, y1, res, shape):
    im = np.zeros(shape, np.float32)
    for b in boxes:
        c0 = int((b[0] - x0) / res); c1 = int(np.ceil((b[2] - x0) / res))
        r0 = int((y1 - b[3]) / res); r1 = int(np.ceil((y1 - b[1]) / res))
        im[max(r0, 0):max(r1, 0), max(c0, 0):max(c1, 0)] = 1
    return im


def register(i):
    H = pickle.load(open(f"{W}/cache/H{i:02d}.pkl", "rb"))
    Y = key_mask(i)
    res_k = CK / raster.PX                          # metres per key pixel (1.32 m)
    # key mask in key metres: pixel (r, c) -> X = c*res_k, Y = -r*res_k
    T, C = detail_tables_m(H)
    # coarse: correlate on a 1.32 m grid
    bx0, by0, bx1, by1 = T[:, 0].min(), T[:, 1].min(), T[:, 2].max(), T[:, 3].max()
    shape = (int((by1 - by0) / res_k) + 3, int((bx1 - bx0) / res_k) + 3)
    tim = rasterise(T, bx0, by1, res_k, shape)
    # table rows are 3.55 m wide with 4 m gaps: close them so the shape is the block footprint
    tim = ndimage.binary_closing(tim > 0, np.ones((7, 3))).astype(np.float32)
    K = Y.astype(np.float32)
    corr = signal.fftconvolve(K, tim[::-1, ::-1], mode="valid")
    area_t = tim.sum(); area_k = K.sum()
    iou = corr / (area_t + area_k - corr)
    r, c = np.unravel_index(np.argmax(iou), iou.shape)
    # top-left of the table raster sits at key pixel (r, c): key X of bx0 = c*res_k, key Y of by1 = -r*res_k
    dX = c * res_k - bx0
    dY = -r * res_k - by1
    # fine: same at 0.25 m with the key mask upsampled
    up = int(round(res_k / 0.25))
    Kf = np.kron(K, np.ones((up, up), np.float32))
    rf = res_k / up
    shape_f = (int((by1 - by0) / rf) + 3, int((bx1 - bx0) / rf) + 3)
    tf = rasterise(T, bx0, by1, rf, shape_f)
    tf = ndimage.binary_closing(tf > 0, np.ones((int(4.5 / rf) | 1, 3))).astype(np.float32)
    r0, c0 = r * up, c * up
    best = None
    win = up + 2
    at = tf.sum()
    for dr in range(-win, win + 1):
        for dc in range(-win, win + 1):
            rr, cc = r0 + dr, c0 + dc
            if rr < 0 or cc < 0 or rr + tf.shape[0] > Kf.shape[0] or cc + tf.shape[1] > Kf.shape[1]:
                continue
            ov = (Kf[rr:rr + tf.shape[0], cc:cc + tf.shape[1]] * tf).sum()
            v = ov / (at + Kf.sum() - ov)
            if best is None or v > best[0]:
                best = (v, rr, cc)
    v, rr, cc = best
    dXf = cc * rf - bx0
    dYf = -rr * rf - by1
    # inside fraction: tables inside the highlighted block
    inside = (Kf[rr:rr + tf.shape[0], cc:cc + tf.shape[1]] * tf).sum() / at
    out = dict(sheet=i, m_per_pt=C, dX=float(dXf), dY=float(dYf), iou=float(v), coarse_iou=float(iou.max()),
               tables_inside=float(inside), key_block_m2=float(K.sum() * res_k ** 2), tables_m2=float(at * rf * rf))
    return out


if __name__ == "__main__":
    res = {}
    for i in map(int, sys.argv[1:]):
        o = register(i)
        res[i] = o
        print(json.dumps(o))
    json.dump(res, open(f"{W}/cache/register.json", "w"), indent=1)
