#!/usr/bin/env python3
"""Register a set of detail sheets onto one key sheet (multi-sheet packages).

Use when a plant is drawn over several sheets (e.g. one stringing sheet per
inverter block) at different scales. Each sheet is placed on the key sheet,
usually the general layout, by cross-correlating the colours both draw:
streams, roads, module rows. Scales come from each page's model viewport.

Writes <work>/register.json (per-sheet scale, viewport and offset) and
<work>/register/overlay_pNN.png. Open every overlay: green is the key sheet,
red the detail sheet, yellow where they agree. Any sheet whose linework does
not sit on the key's is wrong. A peak_ratio below about 1.15 also means an
ambiguous match.

Usage:
    python register_sheets.py work/my-site --key-page 55 --pages 58-71
    python register_sheets.py work/my-site --key-page 55 --pages 58-71 --res 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import source  # noqa: E402
from pvgeo.register import KeyCorrelator, colour_counts, model_viewport, rasterise  # noqa: E402


def parse_pages(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--key-page", type=int, required=True)
    ap.add_argument("--pages", required=True, help="detail pages, e.g. 58-71")
    ap.add_argument("--res", type=float, default=1.0, help="metres per raster pixel (default 1.0)")
    ap.add_argument("--max-colours", type=int, default=6)
    args = ap.parse_args()

    import pymupdf
    from PIL import Image

    src = source(args.work)
    doc = pymupdf.open(src["pdf"])
    pages = parse_pages(args.pages)
    kp = doc[args.key_page - 1]
    kv = model_viewport(doc, kp)
    if not kv:
        sys.exit(f"error: page {args.key_page} has no measured model viewport; set the scale by hand")
    k_key, clip_key = kv
    print(f"key page {args.key_page}: {k_key:.5f} m/pt", flush=True)
    # pass 1: colours each detail sheet draws (pages are read one at a time to bound memory)
    sheets, sheet_cols = {}, {}
    for pn in pages:
        p = doc[pn - 1]
        v = model_viewport(doc, p)
        if not v:
            print(f"  page {pn}: no measured viewport, skipped")
            continue
        sheets[pn] = {"m_per_pt": v[0], "clip": v[1]}
        sheet_cols[pn] = colour_counts(p.get_drawings(), v[1])
    key_draw = kp.get_drawings()
    key_cols = colour_counts(key_draw, clip_key)
    shared = Counter()
    for c in sheet_cols.values():
        for col in c:
            if col in key_cols:
                shared[col] += 1
    colours = [c for c, n in shared.most_common() if n >= max(1, len(sheets) // 2)][: args.max_colours]
    if not colours:
        sys.exit("error: the detail sheets share no drawing colour with the key sheet")
    print(f"colours used: {colours}", flush=True)

    key_r = rasterise(key_draw, clip_key, k_key, colours, args.res)
    del key_draw
    tpls = {}
    for pn, s in sheets.items():
        tpls[pn] = rasterise(doc[pn - 1].get_drawings(), s["clip"], s["m_per_pt"], colours, args.res)
    max_shape = tuple(max(t.shape[i + 1] for t in tpls.values()) for i in range(2))
    kc = KeyCorrelator(key_r, max_shape)
    outdir = args.work / "register"
    outdir.mkdir(exist_ok=True)
    kimg = np.clip(key_r.sum(axis=0), 0, 1)
    for pn, tpl in tpls.items():
        m = kc.match(tpl)
        s = sheets[pn]
        s["offset_m"] = [v * args.res for v in m["offset_px"]]
        s["score"], s["peak_ratio"] = round(m["score"], 2), round(m["peak_ratio"], 3)
        flag = "  <-- check" if m["peak_ratio"] < 1.15 else ""
        print(f"  page {pn}: {s['m_per_pt']:.4f} m/pt, offset {s['offset_m'][0]:.1f}, {s['offset_m'][1]:.1f} m, "
              f"score {s['score']}, peak ratio {s['peak_ratio']}{flag}", flush=True)
        t = np.clip(tpl.sum(axis=0), 0, 1)
        ox, oy = (int(round(v)) for v in m["offset_px"])
        h, w = t.shape
        y0, x0 = max(oy - 80, 0), max(ox - 80, 0)
        crop = kimg[y0:oy + h + 80, x0:ox + w + 80]
        rgb = np.zeros(crop.shape + (3,), np.uint8)
        rgb[..., 1] = (crop * 255).astype(np.uint8)
        sub = rgb[oy - y0:oy - y0 + h, ox - x0:ox - x0 + w, 0]
        sub[...] = (t[: sub.shape[0], : sub.shape[1]] * 255).astype(np.uint8)
        Image.fromarray(rgb).save(outdir / f"overlay_p{pn:02d}.png")

    reg = {"key_page": args.key_page, "key": {"m_per_pt": k_key, "clip": clip_key,
                                              "page_size_pt": [kp.rect.width, kp.rect.height]},
           "res_m": args.res, "colours": colours, "sheets": {str(k): v for k, v in sheets.items()}}
    (args.work / "register.json").write_text(json.dumps(reg, indent=2), encoding="utf-8")
    print(f"-> {args.work / 'register.json'}; overlays in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
