# Route D scripts: per-station cabling sheets with leaders and a key plan

Fernando's pipeline for a route D site, built with Claude's help. It covers packages where:

- each sheet shows one station (CTIN) at 1:1,200, with its level-1 boards, cables and fused taps;
- the hierarchy is printed as **leader labels** (`CIRC. N1-09 a TA01-1-05`) and a **circuit table**, not as layers;
- every sheet carries the **same key plan** in the same place, with its own block highlighted;
- some sheets are AutoCAD plots with layers and others are re-prints with text turned into outlines.

These scripts are site-specific (colours, key-plan box, CRS and anchor are constants at the top of each file). Copy them next to a new site and adjust the constants. They are the reference implementation of route D in `SKILL.md`.

## Order

```
export ROUTE_D_SRC=src ROUTE_D_WORK=work ROUTE_D_RENDER=render ROUTE_D_OUT=out/<site>
python extract.py 1 2 ... 10      # styles -> cache/E##.pkl: tables, taps, boards, row labels, cables
python build2.py 1 ... 10         # per sheet: rows, tap-to-table pairing, circuits, leader OCR, names -> cache/H##.pkl
                                  # run sheets one after another: OCR temp files are per process, never run two copies on one sheet
python qa_names.py 1 ... 10       # circuits found vs circuit table, board mismatches
python debug2.py N                # render/hNN.png: tables boxed by circuit, N1-xx>TAyy labels, leader tips
python register_ac.py 1 ... 10    # block fit on the key plan -> cache/register.json
python ctin_match.py 2 1 2 ... 10 # transformer correction against the key plan -> cache/ctin_match.json
python assemble.py                # plant frame, name resolution, foreign tables dropped -> cache/assembled.pkl
python areas.py                   # circuit, combiner and inverter area polygons (union of tables closed at 2.1 m)
python export.py                  # provisional georeference, GeoJSON, Shapefile, KMZ, hierarchy
python report.py                  # qa_report.md, georef_report.md, summary.md, preview.jpg, sheets/*.jpg
```

## Modules

| File | Does |
|---|---|
| `load.py` | page cache, displayed (rotated) coordinates, measured viewports |
| `extract.py` | style census per role; tables from vector outlines or, on flattened sheets, from module cells (fill holes, split runs at the table pitch) |
| `raster.py` | colour raster at 4 px/pt; green cable mask with 1 px dilation and gap bridging; components cut at the boards |
| `ocr.py` | circuit-table OCR with grid lines removed |
| `leaders.py` | two-segment and split leaders, tip, single-line OCR of the label with a whitelisted second pass |
| `build.py`, `build2.py` | rows from taps, order-preserving tap-to-table alignment, fragment merging, leader naming with sequence repair, table fallback |
| `register_ac.py` | sheet → key-plan translation by IoU of the tables against the highlighted block |
| `ctin_match.py` | transformer symbol on the sheet → same symbol in the key plan, a 0.1 m correction |
| `assemble.py` | board naming by one-to-one assignment, label-versus-table resolution, hierarchy and features |
| `areas.py` | area polygons per circuit, combiner and inverter: union of their tables closed across the row gap, clipped off other groups' tables, no overlaps |
| `export.py`, `report.py` | outputs in the `converted_layouts` structure |
