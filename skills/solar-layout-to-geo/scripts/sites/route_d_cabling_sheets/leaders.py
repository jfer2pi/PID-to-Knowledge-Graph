"""Leader labels: 'CIRC. N1-xx a TAnn-1-mm ...' and 'TAnn-1-mm a TAnn-2 ...' with their tips."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, re, subprocess, pickle
import numpy as np
import pymupdf as fitz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load, disp, pdf
from build import words_disp

RC = re.compile(r"N\s*1\s*[-–]\s*([0-9O]{2})\s*a\s*T\s*A\s*([0-9O]{2})\s*[-–]\s*1\s*[-–]\s*([0-9O]{2})")
RB = re.compile(r"T\s*A\s*([0-9O]{2})\s*[-–]\s*1\s*[-–]\s*([0-9O]{2})\s*a\s*T\s*A\s*([0-9O]{2})\s*[-–]\s*2")


def find_leaders(i, clip):
    s = disp(load(i))
    out = []
    for g in s["dr"]:
        c = g.get("color")
        if g["type"] != "s" or not c or max(c) > 0.1 or len(g["Di"]) != 2 or g["Di"][0][0] != "l" or g["Di"][1][0] != "l":
            continue
        R = g["D"]
        if not fitz.Rect(clip).intersects(R) or R.x1 > 952 or R.width < 60:
            continue
        (a0, a1), (b0, b1) = [(it[1], it[2]) for it in g["Di"]]
        if not (abs(a0.y - a1.y) < 1.5 and abs(a0.x - a1.x) > 40):
            if abs(b0.y - b1.y) < 1.5 and abs(b0.x - b1.x) > 40:
                (a0, a1), (b0, b1) = (b1, b0), (a1, a0)
            else:
                continue
        h = (a0, a1); tip = b1
        hy = (a0.y + a1.y) / 2
        out.append(dict(hx0=min(h[0].x, h[1].x), hx1=max(h[0].x, h[1].x), hy=hy, tip=(tip.x, tip.y)))
    # leaders drawn as two separate paths: an underline and a loose diagonal touching its end
    hz, dg = [], []
    for g in s["dr"]:
        c = g.get("color")
        if g["type"] != "s" or not c or max(c) > 0.1 or len(g["Di"]) != 1 or g["Di"][0][0] != "l":
            continue
        if not fitz.Rect(clip).intersects(g["D"]) or g["D"].x1 > 952:
            continue
        p0, p1 = g["Di"][0][1], g["Di"][0][2]
        if abs(p0.y - p1.y) < 1.5 and abs(p0.x - p1.x) > 40:
            hz.append((p0, p1))
        elif abs(p0.y - p1.y) > 2 and 4 < abs(p0 - p1) < 90:
            dg.append((p0, p1))
    have = {(round(L["tip"][0], 1), round(L["tip"][1], 1)) for L in out}
    for p0, p1 in dg:
        for h in hz:
            for e in (h[0], h[1]):
                for a, b in ((p0, p1), (p1, p0)):
                    if abs(a - e) < 0.8:
                        key = (round(b.x, 1), round(b.y, 1))
                        if key not in have:
                            have.add(key)
                            out.append(dict(hx0=min(h[0].x, h[1].x), hx1=max(h[0].x, h[1].x), hy=(h[0].y + h[1].y) / 2,
                                            tip=(b.x, b.y), split=True))
    return out


def _ocr(page, box, dpi, extra=()):
    import os
    png = f"/tmp/lead_{os.getpid()}.png"
    page.get_pixmap(dpi=dpi, clip=fitz.Rect(box), colorspace=fitz.csGRAY).save(png)
    return subprocess.run(["tesseract", png, "-", "--psm", "7", *extra], capture_output=True, text=True).stdout.strip()


def read_text(i, L, page):
    x0, x1, y = L["hx0"], L["hx1"], L["hy"]
    box = (x0 - 1, y - 11, x1 + 1, y - 0.2)
    t = _ocr(page, box, 500)
    if parse(t):
        return t
    # second pass: the designation only (left part of the line), whitelisted
    for frac, dpi in ((0.62, 600), (0.55, 700), (0.7, 500)):
        b2 = (x0 - 1, y - 11, x0 + frac * (x1 - x0), y - 0.2)
        t2 = _ocr(page, b2, dpi, ("-c", "tessedit_char_whitelist=CIRNTAa0123456789-. "))
        if parse(t2):
            return t2
    return t


def parse(t):
    t2 = t.replace("—", "-").replace("–", "-").replace("~", "-")
    t2 = re.sub(r"N[tTlIi|]", "N1", t2)
    t2 = re.sub(r"TA[0OQD]+(?=\d)", "TA0", t2)
    t2 = re.sub(r"N1-(\d)\s(\d)\s*a", r"N1-\1\2 a", t2)
    t2 = re.sub(r"(?<=TA)[OQD]", "0", t2)
    t2 = re.sub(r"(?<=TA0)[OQD]", "0", t2)
    t2 = t2.replace("TAO", "TA0").replace("TAQ", "TA0")
    m = RB.search(t2)
    if m and "CIRC" not in t2.upper() and "N1" not in t2:
        g = [int(x.replace("O", "0")) for x in m.groups()]
        return dict(kind="board", ctin=g[0], ta=g[1])
    m = RC.search(t2)
    if m:
        g = [int(x.replace("O", "0")) for x in m.groups()]
        return dict(kind="circuit", n1=g[0], ctin=g[1], ta=g[2])
    return None


def leaders(i, clip, layered):
    Ls = find_leaders(i, clip)
    page = fitz.open(pdf(i))[0]
    for L in Ls:
        L["text"] = read_text(i, L, page)
        L["parsed"] = parse(L["text"])
    return Ls


if __name__ == "__main__":
    for i in map(int, sys.argv[1:]):
        E = pickle.load(open(f"{WORK}/cache/E{i:02d}.pkl", "rb"))
        Ls = leaders(i, E.get("clip") or (20, 20, 950, 830), E["layered"])
        ok = [L for L in Ls if L["parsed"]]
        kinds = [L["parsed"]["kind"] for L in ok]
        print(i, "leaders", len(Ls), "parsed", len(ok), "circuit", kinds.count("circuit"), "board", kinds.count("board"))
        for L in Ls:
            if not L["parsed"]:
                print("   unparsed:", repr(L["text"][:70]))
        pickle.dump(Ls, open(f"{WORK}/cache/L{i:02d}.pkl", "wb"))
