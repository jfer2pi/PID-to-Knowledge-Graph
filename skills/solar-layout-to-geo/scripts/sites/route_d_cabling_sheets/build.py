"""the route D site: per-sheet hierarchy CTIN > TA (level-1 board) > circuit N1 > connection (table)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, re, pickle, collections, json
import numpy as np
import pymupdf as fitz
from scipy.optimize import linear_sum_assignment
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load, pdf
import ocr

W = WORK


def words_disp(i):
    s = load(i)
    M = fitz.Matrix(*s["derot"])
    out = []
    for w in s["words"]:
        r = fitz.Rect(w[:4]) * M
        out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    return out


def text_lines(words, tol=2.0):
    """group words into lines by y centre"""
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines, cur, cy = [], [], None
    for w in ws:
        y = (w[1] + w[3]) / 2
        if cy is not None and abs(y - cy) > tol:
            lines.append(cur); cur = []
        cur.append(w); cy = y if not cur[:-1] else cy
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        ln.sort(key=lambda w: w[0])
        out.append((" ".join(w[4] for w in ln), ln))
    return out


def circuit_table(i, E, rows_bottom):
    if E["layered"]:
        lines = [t for t, _ in text_lines(words_disp(i))]
        src = "text"
        got = ocr.parse_circuits(lines)
        if len(got) >= 5:
            return got, src
        lines = ocr.ocr_lines(i, (20, rows_bottom + 4, 950, 835))
        src = "ocr"
    else:
        lines = ocr.ocr_lines(i, (20, rows_bottom + 4, 950, 835))
        src = "ocr"
    return ocr.parse_circuits(lines), src


def row_label_names(i, E, labels):
    """name each label box: text inside (layered) or OCR of the box (flattened)"""
    names = []
    if E["layered"]:
        ws = words_disp(i)
        for b in labels:
            t = [w[4] for w in ws if b[0] - 1 <= (w[0] + w[2]) / 2 <= b[2] + 1 and b[1] - 1 <= (w[1] + w[3]) / 2 <= b[3] + 1]
            m = re.search(r"F\.(\d\d)\.(\d\d)", " ".join(t))
            names.append(f"F.{m[1]}.{m[2]}" if m else None)
    else:
        d = fitz.open(pdf(i)); p = d[0]
        import subprocess
        for k, b in enumerate(labels):
            png = f"/tmp/lab_{i}_{k}_{__import__('os').getpid()}.png"
            p.get_pixmap(dpi=600, clip=fitz.Rect(b[0] + 1, b[1] + 1, b[2] - 1, b[3] - 1), colorspace=fitz.csGRAY).save(png)
            r = subprocess.run(["tesseract", png, "-", "--psm", "7", "-c", "tessedit_char_whitelist=F.0123456789"],
                               capture_output=True, text=True).stdout
            m = re.search(r"F\.?(\d\d)\.?(\d\d)", r.replace(" ", ""))
            names.append(f"F.{m[1]}.{m[2]}" if m else None)
    return names


def green_components(green, tas, snap=0.8):
    """circuits: connected green segments, cut at TA boxes"""
    tab = [box(*t).buffer(0.6) for t in tas]
    segs = []
    for s in green:
        L = LineString([(s[0], s[1]), (s[2], s[3])])
        if L.length < 1e-6:
            continue
        for T in tab:
            if L.intersects(T):
                L = L.difference(T)
        if L.is_empty:
            continue
        for g in getattr(L, "geoms", [L]):
            if g.length > 0.05:
                segs.append(g)
    n = len(segs)
    par = list(range(n))
    def f(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a
    tree = STRtree(segs)
    for a, g in enumerate(segs):
        for b in tree.query(g.buffer(snap)):
            if b > a and segs[b].distance(g) < snap:
                # touching: join only at endpoints or crossings within snap (cables don't cross other circuits much)
                par[f(a)] = f(b)
    comps = collections.defaultdict(list)
    for a in range(n):
        comps[f(a)].append(segs[a])
    return list(comps.values())


def build(i, verbose=True):
    E = pickle.load(open(f"{W}/cache/E{i:02d}.pkl", "rb"))
    T = np.array(E["tables_raw"]); D = np.array(E["dots"])
    tas = E["ta_raw"]
    # rows by table y-centre
    yc = (T[:, 1] + T[:, 3]) / 2
    order = np.argsort(yc)
    row_id = np.zeros(len(T), int); r = -1; last = None
    for k in order:
        if last is None or yc[k] - last > 4:
            r += 1
        row_id[k] = r; last = yc[k]
    row_y = np.array([yc[row_id == k].mean() for k in range(r + 1)])
    import raster
    clip = E.get("clip") or (20, 20, 950, 830)
    lab, sizes, rgb = raster.circuits(i, clip, tas)
    Gm = raster.green_mask(rgb)
    PX = raster.PX
    cov = np.zeros(len(T))
    for k, t in enumerate(T):
        r0 = int((t[1] - 1.5 - clip[1]) * PX); r1 = int((t[3] + 1.5 - clip[1]) * PX)
        c0 = int((t[0] - clip[0]) * PX); c1 = int((t[2] - clip[0]) * PX)
        if r1 <= 0 or c1 <= 0:
            continue
        cov[k] = Gm[max(r0, 0):r1, max(c0, 0):c1].any(axis=0).mean()
    wired = cov > 0.25
    # dots -> wired tables, one to one
    cand = np.where(wired)[0]
    C = np.full((len(D), len(cand)), 1e6)
    for a, d in enumerate(D):
        for b, k in enumerate(cand):
            t = T[k]
            if t[1] - 2 <= d[1] <= t[3] + 2:
                dx = 0 if t[0] - 0.8 <= d[0] <= t[2] + 0.8 else min(abs(d[0] - t[0]), abs(d[0] - t[2]))
                C[a, b] = abs(d[0] - (t[0] + t[2]) / 2) + 50 * dx
    ra, cb = linear_sum_assignment(C)
    dot_tab = {a: cand[b] for a, b in zip(ra, cb) if C[a, b] < 1e5}
    bad = len(D) - len(dot_tab)
    # circuits: raster components
    dot_circ = {}
    for a, d in enumerate(D):
        j = raster.label_at(lab, clip, d[0], d[1], r=2.5)
        if j:
            dot_circ[a] = j
    used = set(dot_circ.values())
    circ_ta = {}
    ta_touch = [raster.touching(lab, clip, t) for t in tas]
    for j in used:
        hits = [q for q, s in enumerate(ta_touch) if j in s]
        circ_ta[j] = hits[0] if len(hits) == 1 else (None if not hits else tuple(hits))
    CL = sorted(used)
    # names
    labels = E["label_raw"]
    lab_names = row_label_names(i, E, labels)
    lab_row = {}
    for b, nm in zip(labels, lab_names):
        cy = (b[1] + b[3]) / 2
        k = int(np.argmin(abs(row_y - cy)))
        if abs(row_y[k] - cy) < 4:
            lab_row[k] = nm
    rows_bottom = T[wired][:, 3].max() if wired.any() else T[:, 3].max()
    table, src = circuit_table(i, E, rows_bottom)
    res = dict(sheet=i, E=E, T=T, D=D, row_id=row_id, row_y=row_y, wired=wired, dot_tab=dot_tab, unassigned_dots=bad,
               circ_ids=CL, dot_circ=dot_circ, circ_ta=circ_ta, lab_row=lab_row, table=table, table_src=src)
    if verbose:
        print(f"sheet {i}: tables {len(T)} wired {wired.sum()} dots {len(D)} matched {len(dot_tab)} unmatched {bad} | "
              f"circuits {len(circ_ta)} (no TA {sum(v is None for v in circ_ta.values())}, multi {sum(isinstance(v, tuple) for v in circ_ta.values())}) TA boxes {len(tas)} | "
              f"rows {len(row_y)} labelled {len(lab_row)} ({sum(v is None for v in lab_row.values())} unread) | table {len(table)} via {src}")
    pickle.dump(res, open(f"{W}/cache/B{i:02d}.pkl", "wb"))
    return res


if __name__ == "__main__":
    for i in map(int, sys.argv[1:]):
        build(i)
