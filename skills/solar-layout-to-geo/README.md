# Solar layout to georeferenced PV hierarchy

By Fernando Rodríguez ([jfer2pi](https://github.com/jfer2pi)), built with Claude's help on top of Scott Duncan's [P&ID to Knowledge Graph](https://github.com/ScottDuncanAI) skill, which this repository forks.

**Turn a solar plant's as-built layout PDF into GIS layers and a device hierarchy, without converting it to DXF first.**

Most solar layouts are plotted from AutoCAD or Civil 3D, and the plot keeps the CAD layers as PDF layers. When the CAD team colours the array by combiner box, which is common practice, every module in the PDF already says which inverter and combiner it belongs to. This skill reads that structure directly. It returns:

- **The hierarchy**: station > inverter > combiner box > string, with module and table counts at every level, e.g. `ST10 > INV10-01 > INV10-01-CB05 > INV10-01-CB05-S01`.
- **Georeferenced layers**: inverter stations as points; inverter, combiner and string areas as polygons; tables; fence, boundary, roads, trenches and CCTV. Formats are GeoJSON, KMZ for Google Earth, and Shapefile.
- **QA** that catches CAD mistakes, such as modules drawn on the wrong combiner layer, and suggests the fix.

## How it works

1. `list_layers.py` reads every path in the PDF with its layer and suggests a role for each layer.
2. Claude reviews the layer list and writes `layer_map.json`, which says which layers are modules, tables, inverter tags and site features.
3. `build_layout.py` assigns modules to tables and derives strings from the module rows. It groups everything by combiner and inverter, and finds each station from its tags.
4. Claude checks `preview.py` overlays against the drawing's own labels and resolves what QA flags.
5. `georef.py` fits the sheet to real coordinates from control points: as-built station coordinates, fence corners from imagery, or a national-grid base map. It reports scale, rotation and residuals.
6. `export_geo.py` writes the GIS files and the hierarchy with coordinates.

See [SKILL.md](SKILL.md) for the workflow and [references/procedure.md](references/procedure.md) for the details.

## Route A example: a layered as-built layout

The as-built layout has about 500 PDF layers: combiner module layers, inverter-tag layers, table types and site features. The skill extracted:

| Item | Count |
|---|---|
| Inverter stations | about 20 |
| Inverters | about 40 |
| Combiner boxes | about 400 |
| Strings | about 9,000 |
| Tables | about 2,400 |
| Modules | about 200,000 |

QA found two layer mix-ups in the CAD. two combiners of one station had been drawn on the next station's combiner layers. The drawing's own labels confirmed both, and both are corrected with `reassign` rules.

## Second site: Arcos 2 (47 MWdc, Puerto Real, Cádiz)

A PVcase design package inside a 105-page project PDF. Pages 58 to 71 hold one stringing sheet per inverter block, each a zoomed viewport at 1:1500 or 1:1750. The general layout (page 55) is flattened. The skill:

- registered the 14 sheets onto the general layout by correlating streams, roads and module rows;
- read the hierarchy from the printed labels;
- matched three of the four surveyed trench-stream crossings printed on pages 82 to 85 automatically, which gives a fit to ETRS89 UTM 29N with 0.48 m RMSE. The fourth crossing's predicted position falls on the stream, an independent check.

| Item | Count |
|---|---|
| Power stations / central inverters | 14 |
| DC combiner boxes | 224 |
| Strings (26 modules) | 3,616 |
| Modules | 94,016 (equal to the total printed on the drawing) |

## Third site: Huévar I (50 MWp, Huévar del Aljarafe, Sevilla)

An execution project assembled with PDFsam: no layers, no viewport scales, no hierarchy labels. The skill found everything by drawing style.

**From the layout (p. 199)**
- Blocks from their coloured outlines.
- Trackers: one rectangle style, 2,448 in all, matching the printed 180 or 162 per block for all 14 blocks.
- Stations from the skid symbols tagged INV.01–INV.14.

**From the grounding plan (p. 200)**, registered by the station symbols:
- 251 combiner boxes in two symbol styles, for 20-input and 18-input boxes.
- Trackers are assigned to boxes within each type's capacity, and each tracker carries 2 strings of 26 modules. These levels are flagged as derived.
- One box in block 11 is hidden under a label. QA reports it.

**Placement** comes from the plant coordinate printed in the memoria, so it is provisional.

## Route D example: per-station cabling sheets

Ten as-built DC cabling sheets, one per station (CTIN), at 1:1,200. Six are AutoCAD plots with layers; four were re-printed through Distiller with no layers and the text turned into outlines. The hierarchy is printed as leader labels (`CIRC. N1-09 a TA01-1-05`) and a circuit table on each sheet. This became route D (`scripts/sites/route_d_cabling_sheets/`).

**On each sheet**
- Tables from their outlines, or from the module cells on the re-prints. One fused tap per table, paired in order along each row: about 200 per station, about 2,000 in all.
- Level-1 cables traced on a colour raster, since part of the cable is drawn as image strips. Each cable is named by the leader whose ellipse sits on it, read by OCR and checked against the circuit order and the table: about 300 circuits on about 160 level-1 boards.
- Four places where the drawing's leader and its own table name different boards are listed in the QA report, with the board the cable actually reaches.

**Placement**: every sheet carries the same key plan with its block highlighted. Sheets were fitted to their block, then to the transformer symbol both drawings share. The plant sits on its published coordinate, so it is provisional.

## Parent levels from children

Whenever the strings or tables carry their parents' ids, the export adds any parent level the drawing did not give: an area polygon (the children's union, closed across the row gap, never overlapping) and a record point, flagged as derived. Existing levels are never redrawn. `scripts/rollup_geo.py` applies the same rule to an already delivered site folder.

## Limits

- **Scanned (raster) drawings** are not handled. Vector PDFs work with or without layers.
- **Strings are derived from module rows or taps**, not read from a string schedule. Their numbering is geometric.
- **OCR** (Tesseract) is needed for route D, where labels are outlines or use fonts without a usable text layer.
- **Station points from tags** are within a few metres of the skid.
- **One control point gives a provisional position only.** Use three or more.
- **PyMuPDF**, used to read layers, is AGPL-3.0.

## Setup

```bash
pip install -r skills/solar-layout-to-geo/scripts/requirements.txt
pytest tests/test_solar_layout.py
```
