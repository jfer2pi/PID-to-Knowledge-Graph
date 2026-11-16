import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, re, subprocess, os, pickle
import pymupdf as fitz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import pdf

FIX = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})

def ocr_lines(i, clip, dpi=500, psm=6):
    d = fitz.open(pdf(i)); p = d[0]
    import os
    png = f"/tmp/ocr_{i}_{os.getpid()}.png"
    p.get_pixmap(dpi=dpi, clip=fitz.Rect(clip), colorspace=fitz.csGRAY).save(png)
    import cv2, numpy as np
    im = cv2.imread(png, 0)
    bw = (im < 160).astype(np.uint8) * 255
    for k in ((60, 1), (1, 60)):
        lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        bw[lines > 0] = 0
    cv2.imwrite(png, 255 - bw)
    r = subprocess.run(["tesseract", png, "-", "--psm", str(psm)], capture_output=True, text=True)
    return r.stdout.splitlines()

RX = re.compile(r"F\s*[.,]?\s*([0-9O]{2})\s*[.,]\s*([0-9O]{2})[^A-Z]{0,14}C\s*I\s*R\s*C\W*N\s*1\W*([0-9O]{2})\W*a\W*T\s*A\s*([0-9O]{2})\W*1\W*([0-9O]{2})")

def parse_circuits(lines):
    out = []
    for ln in lines:
        # normalise digits inside the obvious tokens
        t = ln.replace("—", "-").replace("–", "-")
        for m in RX.finditer(t):
            g = [x.replace("O", "0") for x in m.groups()]
            out.append(dict(row=f"F.{g[0]}.{g[1]}", n1=int(g[2]), ctin=int(g[3]), ta=int(g[4])))
    return out

if __name__ == "__main__":
    i = int(sys.argv[1]); clip = [float(v) for v in sys.argv[2:6]]
    L = ocr_lines(i, clip)
    c = parse_circuits(L)
    print(len(L), "lines", len(c), "circuits")
    for x in c: print(x)
