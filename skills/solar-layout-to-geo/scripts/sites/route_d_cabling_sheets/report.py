"""the route D site: QA report, georeference report, summary, previews."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, json, pickle, collections
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CRS = os.environ.get("SITE_CRS", "EPSG:32630")
ANCHOR = tuple(float(v) for v in os.environ.get("SITE_ANCHOR_LONLAT", "0,0").split(","))
W = Path(WORK)
OUT = Path(OUT)
PLANT_W = float(os.environ.get("PLANT_W", "nan"))   # published plant size in W, set per site
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
COLS = [(220, 20, 60), (30, 144, 255), (34, 139, 34), (255, 140, 0), (148, 0, 211), (0, 128, 128), (205, 92, 92),
        (70, 130, 180), (120, 160, 30), (255, 20, 147)]


def preview(A, path, S=1.6):
    F = A["feats"]
    allb = np.array([g.bounds for g, _ in F["tables"]] + [g.bounds for g, _ in F["site"]])
    x0, y0, x1, y1 = allb[:, 0].min() - 20, allb[:, 1].min() - 20, allb[:, 2].max() + 20, allb[:, 3].max() + 60
    Wd, Hd = int((x1 - x0) * S), int((y1 - y0) * S)
    im = Image.new("RGB", (Wd, Hd), "white"); d = ImageDraw.Draw(im)
    f = lambda x, y: ((x - x0) * S, (y1 - y) * S)
    fb = ImageFont.truetype(FONTB, 15); fs = ImageFont.truetype(FONT, 9); ft = ImageFont.truetype(FONTB, 20)
    for g, p in F["site"]:
        d.polygon([f(*c) for c in g.exterior.coords], outline=(150, 150, 150))
    for g, p in F["tables"]:
        k = int(p["station"][-2:]) - 1
        c = COLS[k]
        fill = tuple(int(v + (255 - v) * 0.55) for v in c)
        b = g.bounds
        d.rectangle([f(b[0], b[3]), f(b[2], b[1])], fill=fill, outline=c)
    for g, p in F["circuits"]:
        pass
    for g, p in F["combiners"]:
        u, v = f(g.x, g.y); d.rectangle([u - 2.5, v - 2.5, u + 2.5, v + 2.5], fill=(255, 200, 0), outline=(0, 0, 0))
    for g, p in F["stations"]:
        u, v = f(g.x, g.y); d.ellipse([u - 6, v - 6, u + 6, v + 6], fill=(0, 0, 0))
        d.text((u + 8, v - 20), p["id"], fill=(0, 0, 0), font=fb)
    d.text((15, 10), f"the route D site, {len(F['tables']):,} fused taps (tables of 40 modules) under 10 CTIN, colour = station; yellow = level-1 boards (TA..-1-..)",
           fill=(0, 0, 0), font=ImageFont.truetype(FONT, 13))
    # scale bar 100 m
    u, v = 20, Hd - 25
    d.line([u, v, u + 100 * S, v], fill=(0, 0, 0), width=3); d.text((u, v - 16), "100 m", fill=(0, 0, 0), font=fs)
    # north arrow
    d.polygon([(Wd - 30, 40), (Wd - 38, 62), (Wd - 22, 62)], fill=(0, 0, 0)); d.text((Wd - 35, 18), "N", fill=(0, 0, 0), font=fb)
    im.save(path, quality=88)


def main():
    A = pickle.load(open(W / "cache/assembled.pkl", "rb"))
    T = json.loads((OUT / "config/transform.json").read_text())
    rows = A["rows"]
    lv = collections.Counter(r["level"] for r in rows)
    st = [r for r in rows if r["level"] == "station"]
    n_tab = sum(r["n_tables"] for r in st)
    preview(A, OUT / "qa/preview.jpg")
    # per-sheet previews
    import debug2
    for i in range(1, 11):
        debug2.debug(i, out=str(OUT / f"qa/sheets/SHEET-{i}.png"))
        im = Image.open(OUT / f"qa/sheets/SHEET-{i}.png").convert("RGB")
        im.save(OUT / f"qa/sheets/SHEET-{i}.jpg", quality=85); (OUT / f"qa/sheets/SHEET-{i}.png").unlink()
    # QA report
    Q = []
    Q.append("# QA report: the route D site\n")
    Q.append("Source: `route_d_site_layout_with_modules.zip`, ten sheets, "
             "*Cableado corriente continua (BT) CTIN-01 … CTIN-10*, as built, January 2015, 1:1,200 with a 1:15,000 key plan.\n")
    Q.append("## What was read and what was derived\n")
    Q.append("| Level | Source | Read or derived |\n|---|---|---|")
    Q.append("| Station `CTIN-nn` | sheet title; transformer symbol on the sheet, matched to the same symbol in the key plan | read |")
    Q.append("| Inverter `INVnn` | one per CTIN (level-2 board `TAnn-2` at the station) | read (one per station; the drawings show no inverter split) |")
    Q.append("| Combiner `TAnn-1-mm` (level-1 board) | yellow board symbols; names from the circuit leaders and circuit tables | read |")
    Q.append("| Circuit `N1-xx` (level-1 cable, 95 mm²) | green cable traced on a colour raster, cut at the boards; names from the leader label whose ellipse sits on that cable | read; OCR on every sheet (see below) |")
    Q.append("| Table / fused tap | one *conector a perforación con fusible (x2)* per table, paired to tables in order along each row | read |")
    Q.append("| Strings `-S1`, `-S2` | two per tap (the ×2 fuses), 20 modules each; geometry = upper and lower module row of the table | **derived** |")
    Q.append("| Modules | 2 × 20 per table (1.0 m wide; 1.77 m in plan = 1.96 m module at 25°) | read from the table drawing; count derived |")
    Q.append("")
    Q.append("Leader text is OCR'd on all sheets: on the layered sheets the PDF font maps characters with an offset and drops the digits, "
             "and the other four sheets have their text converted to outlines. Readings were checked against the order of the circuits "
             "(N1 numbers run top to bottom, west to east) and against each sheet's circuit table.\n")
    Q.append("## Totals\n")
    Q.append(f"- Stations (CTIN) and inverters: {lv['station']}")
    Q.append(f"- Level-1 boards (combiners): {lv['combiner']}")
    Q.append(f"- Level-1 circuits: {lv['circuit']}")
    Q.append(f"- Tables (fused taps): {n_tab:,}")
    Q.append(f"- Strings (derived, 2 per tap): {lv['string']:,}")
    Q.append(f"- Modules: {n_tab * 40:,}. The published plant size implies about {PLANT_W / (n_tab * 40):.0f} W per module, "
             "consistent with 72-cell modules of that period.\n")
    Q.append("## Per sheet\n")
    Q.append("| Sheet | Station | Mode | Tables | Boards | Circuits (named / in table) | Leaders read | Taps named by leader / same row / table | Rows labelled | Placement |")
    Q.append("|---|---|---|---|---|---|---|---|---|---|")
    stmap = {r["id"]: r for r in st}
    for i in range(1, 11):
        H = pickle.load(open(W / f"cache/H{i:02d}.pkl", "rb"))
        q = H["qa"]; r = stmap[f"CTIN-{i:02d}"]
        mode = "layered (AutoCAD)" if H["E"]["layered"] else "flattened (Distiller)"
        Q.append(f"| SHEET-{i} | CTIN-{i:02d} | {mode} | {r['n_tables']} | {r['n_combiners']} | {r['n_circuits']} / {q['table_entries']} ({H['table_src']}) | "
                 f"{q['leaders_read']} / {q['leaders']} | {q['dots_named_by_leader']} / {q['dots_named_inferred']} / {q['dots_named_from_table']} | "
                 f"{q['rows_labelled']} / {q['rows']} | IoU {A['qa'][i]['reg_iou']:.2f} |")
    Q.append("")
    Q.append("Where the circuit-table count is lower than the circuits found, the table was OCR'd and lost lines; the drawing was checked by eye "
             "(the printed tables on SHEET-3, 4.5, 4.9 and 4.10 list as many circuits as were found).\n")
    Q.append("## Warnings left open\n")
    for dd in A["disc"]:
        Q.append(f"- {dd}")
    Q.append("- Strings: the drawings show one fused tap per table and the legend says the connector carries two fuses. "
             "Two strings of 20 per table is consistent with that, but string wiring inside the table is not drawn.")
    Q.append("- Placement is provisional (one published plant point). Relative placement of the ten sheets comes from the key plan (see `georef_report.md`).\n")
    Q.append("## Files\n")
    Q.append("- `preview.jpg`: the whole plant in the drawing frame.")
    Q.append("- `sheets/SHEET-n.jpg`: each sheet with the extraction drawn over it: tables boxed by circuit, `N1-xx>TAyy` labels, board names, "
             "black rings on leader tips that were read and red rings on those that were not.")
    (OUT / "qa/qa_report.md").write_text("\n".join(Q))
    # georef report
    G = []
    G.append("# Georeference report: the route D site\n")
    G.append("**Status: provisional.** Expect tens of metres of offset and possibly a small rotation. Correct it with the DXF Georeferencer "
             "KMZ mode (`gis/route_d_site.kmz`, auto-align or a few control points).\n")
    G.append("## CRS\n")
    G.append(f"{CRS}, the projected CRS set for the site.\n")
    G.append("## Building the plant frame\n")
    G.append("The ten sheets share no coordinates: each 1:1,200 view is a separate AutoCAD viewport, and four sheets were re-printed through "
             "Acrobat Distiller with no viewport data. Every sheet carries the same 1:15,000 key plan in the same place, with its own block "
             "highlighted in yellow. Each sheet was placed in the key-plan frame in two steps:\n")
    G.append("1. **Block fit.** The sheet's tables were rasterised and slid over its yellow block until the overlap (IoU) was best: 0.83 to 0.94, "
             "with 98 to 100% of the tables inside the block.")
    G.append("2. **Transformer correction.** The key plan draws each station's transformer at true size (2.5 m). The same symbol on the detail "
             "sheet was matched to it, moving each sheet by 0.3 to 7 m. After this, east-west neighbours sit 1.5 m apart with their rows within about 1 m, "
             "and every station lands on its key-plan transformer.\n")
    G.append("Scales: detail 0.4216 m per point (AutoCAD viewport measure, 1:1,195) and key plan 5.29362 m per point; the Distiller sheets "
             "were taken at the same scale as the AutoCAD ones, which the table size (47.4 pt = 20.0 m) confirms.\n")
    G.append("## Placement on the ground\n")
    gc = (OUT / "config/gcps.csv").read_text().splitlines()[1].split(",")
    G.append(f"No surveyed coordinates are printed on these sheets. The plant centroid (centroid of all tables) was placed on the published "
             f"plant point ({ANCHOR[1]}, {ANCHOR[0]}; GEM Global Solar Power Tracker or similar), "
             f"E {float(gc[3]):.1f}, N {float(gc[4]):.1f}. Scale 1 and drawing north = grid north are assumed.\n")
    G.append("Files: `config/transform.json` (frame → UTM), `config/gcps.csv`, `config/sheet_placement_blockfit.json` and "
             "`config/sheet_placement_transformer.json` (per-sheet shifts).")
    (OUT / "qa/georef_report.md").write_text("\n".join(G))
    # summary
    S = []
    S.append("# the route D site: summary\n")
    S.append("Fixed-tilt (25°) PV plant.\n")
    S.append("| | Count | Source |\n|---|---|---|")
    S.append(f"| Stations (CTIN) / inverters | {lv['station']} | read |")
    S.append(f"| Level-1 boards (TAnn-1-mm) | {lv['combiner']} | read |")
    S.append(f"| Level-1 circuits (N1-xx) | {lv['circuit']} | read (OCR, checked) |")
    S.append(f"| Tables / fused taps | {n_tab:,} | read |")
    S.append(f"| Strings | {lv['string']:,} | derived (2 × 20 per table) |")
    S.append(f"| Modules | {n_tab * 40:,} | 40 per table |\n")
    S.append("Hierarchy: `CTIN-01 > INV01 > INV01-TA01-1-05 > INV01-TA01-1-05-N1-09 > …-T03 > …-T03-S1`. "
             "Tables are numbered from the board outward along each circuit.\n")
    S.append("Georeference: **provisional** (published plant point). See `georef_report.md`.")
    (OUT / "qa/summary.md").write_text("\n".join(S))
    print("reports written")


if __name__ == "__main__":
    main()
