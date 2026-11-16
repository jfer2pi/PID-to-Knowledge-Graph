#!/usr/bin/env python3
"""Draw the extracted hierarchy over the rendered sheet, for a visual check.

Combiner areas are filled in one colour per inverter, strings are outlined,
station points are red dots, and ids are written on top. Open the image and
compare it with the drawing: wrong groupings, missing areas and misplaced
stations show at a glance.

Usage:
    python preview.py work/my-site                         # whole sheet
    python preview.py work/my-site --bbox 0.36 0.33 0.45 0.40 --labels strings
    python preview.py work/my-site --gcps                  # also mark control points

--bbox is normalized page coordinates (x0 y0 x1 y1, origin top-left), the same
as qa_report.md prints. --labels picks which ids to write: stations,
inverters, combiners or strings (default: stations and combiners when zoomed,
stations only for the whole sheet).
"""

from __future__ import annotations

import argparse
import colorsys
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import source  # noqa: E402


def colour(i: int, alpha: int) -> tuple:
    r, g, b = colorsys.hsv_to_rgb((i * 0.618034) % 1.0, 0.75, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255), alpha)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--long-edge", type=int, default=3000, help="output image long edge in px")
    ap.add_argument("--labels", nargs="*", choices=["stations", "inverters", "combiners", "strings"])
    ap.add_argument("--gcps", action="store_true", help="mark control points from georef/gcps_used.csv")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFont

    src = source(args.work)
    lay = args.work / "layout"
    meta = json.loads((lay / "sheet.json").read_text(encoding="utf-8"))
    k = meta["m_per_pt"]
    W, H = meta["page_size_pt"]
    x0, y0, x1, y1 = args.bbox or (0, 0, 1, 1)
    bw, bh = (x1 - x0) * W, (y1 - y0) * H
    scale = args.long_edge / max(bw, bh)
    pdf = pdfium.PdfDocument(src["pdf"])
    page = pdf[meta.get("page", src["page"]) - 1]
    crop = (x0 * W, (1 - y1) * H, (1 - x1) * W, y0 * H)  # left, bottom, right, top
    img = page.render(scale=scale, crop=crop).to_pil().convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(10, int(args.long_edge / 160)))
    except OSError:
        font = ImageFont.load_default()

    def px(X, Y):  # sheet metres -> image px
        return ((X / k - x0 * W) * scale, (-Y / k - y0 * H) * scale)

    def polys(geom):
        t = geom["type"]
        if t == "Polygon":
            return [geom["coordinates"]]
        if t == "MultiPolygon":
            return geom["coordinates"]
        return []

    def load(name):
        p = lay / f"{name}.geojson"
        return json.loads(p.read_text(encoding="utf-8"))["features"] if p.exists() else []

    zoomed = args.bbox is not None
    labels = set(args.labels if args.labels is not None else (["stations", "combiners"] if zoomed else ["stations"]))
    inv_index = {}
    for f in load("combiners"):
        p = f["properties"]
        key = (p.get("station"), p.get("inverter"))
        ci = inv_index.setdefault(key, len(inv_index))
        for poly in polys(f["geometry"]):
            d.polygon([px(*c) for c in poly[0]], fill=colour(ci, 90), outline=colour(ci, 255))
    if zoomed:
        for f in load("strings"):
            for poly in polys(f["geometry"]):
                d.polygon([px(*c) for c in poly[0]], outline=(20, 20, 20, 160))
    for name in ("strings", "combiners", "inverters"):
        if name not in labels:
            continue
        for f in load(name):
            p = f["properties"]
            X, Y = p["x_pt"] * k, -p["y_pt"] * k
            u, v = px(X, Y)
            if 0 <= u < img.width and 0 <= v < img.height:
                d.text((u, v), p["id"], fill=(0, 0, 0, 255), font=font, anchor="mm",
                       stroke_width=2, stroke_fill=(255, 255, 255, 255))
    r = max(4, args.long_edge // 300)
    for f in load("combiner_boxes"):
        X, Y = f["geometry"]["coordinates"]
        u, v = px(X, Y)
        q = max(2, r // 2)
        d.rectangle([u - q, v - q, u + q, v + q], fill=(0, 0, 0, 255), outline=(255, 255, 255, 255))
    for f in load("stations"):
        X, Y = f["geometry"]["coordinates"]
        u, v = px(X, Y)
        fallback = f["properties"].get("location_source") == "array_centroid"
        d.ellipse([u - r, v - r, u + r, v + r], fill=(255, 140, 0, 255) if fallback else (220, 0, 0, 255),
                  outline=(255, 255, 255, 255))
        if "stations" in labels:
            d.text((u + r + 2, v), f["properties"]["id"] + (" (fallback)" if fallback else ""),
                   fill=(200, 0, 0, 255), font=font, anchor="lm", stroke_width=2, stroke_fill=(255, 255, 255, 255))
    gp = args.work / "georef" / "gcps_used.csv"
    if args.gcps and gp.exists():
        for row in csv.DictReader(gp.open(encoding="utf-8")):
            u = (float(row["sheet_x_pt"]) - x0 * W) * scale
            v = (float(row["sheet_y_pt"]) - y0 * H) * scale
            d.line([u - 2 * r, v, u + 2 * r, v], fill=(0, 120, 255, 255), width=3)
            d.line([u, v - 2 * r, u, v + 2 * r], fill=(0, 120, 255, 255), width=3)
            d.text((u + 2 * r, v - 2 * r), f"{row['id']} r={float(row['r']):.1f}m", fill=(0, 80, 220, 255),
                   font=font, stroke_width=2, stroke_fill=(255, 255, 255, 255))
    out = args.out or lay / ("preview.png" if not zoomed else f"preview_{x0:.3f}_{y0:.3f}_{x1:.3f}_{y1:.3f}.png")
    Image.alpha_composite(img, over).convert("RGB").save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
