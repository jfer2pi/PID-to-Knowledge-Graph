---
name: solar-layout-to-geo
description: Converts a solar PV site layout PDF exported from CAD (AutoCAD, Civil 3D, BricsCAD) into a georeferenced map and an electrical hierarchy of the plant - inverter stations, inverters, combiner boxes and strings with the array areas each one feeds - as GeoJSON, KMZ, Shapefile and a hierarchy CSV/JSON. Reads the CAD layers that survive in the PDF, so no DXF conversion is needed. Use when the user wants to digitize, map or georeference a PV plant layout, build a device hierarchy (e.g. Inverter 10 > Combiner 10.05 > String 10.05.01), or get combiner/string/inverter areas as GIS layers.
---

# Solar layout PDF to georeferenced PV hierarchy

Work is split between deterministic scripts and you:

- **Scripts** read every vector path in the PDF together with its CAD layer, build the hierarchy, fit the georeference and write the GIS files.
- **You** decide which layers mean what (`layer_map.json`), check the result against the drawing, resolve what QA flags, and gather control points with the user.

Scripts live in `scripts/` next to this file; call them by full path. Keep the work directory in the user's folder, e.g. `work/<site>`. The rendering helpers of the sibling `pid-to-kg` skill (`render_pages.py`, `crop.py`) also work on these PDFs.

**Setup.** `pip install -r <skill dir>/scripts/requirements.txt` (Python 3.10+). PyMuPDF is AGPL-licensed: fine for internal use; check the licence before shipping it inside a commercial product.

## Ground rules

- **Record only what is drawn.** Strings are derived from drawn modules, never invented; say so in the report. Station points from tags are approximate (within a few metres of the skid).
- **Never hide a CAD mistake.** When a layer holds the wrong modules, fix it with a `reassign` rule only after you have seen the drawing's own labels confirm it, and list every rule in your report.
- **A one-point georeference is provisional.** Say so plainly. Real use needs 3+ control points spread around the site.
- **Build every parent level the children determine, but only where it is missing.** When strings (or tables) carry their combiner, inverter, station or circuit ids, each of those parents must exist in the output as an area polygon and as a record point. If a parent already exists, leave it alone. A station that is a single inverter gets no separate area (it would repeat the inverter's). `export_geo.py` does this automatically; for a delivered folder run `python scripts/rollup_geo.py <converted_layouts/site>`. Derived areas and points are flagged `derived`.

**Start by reading [references/lessons.md](references/lessons.md)**: triage, rules learned on real sites, and failure modes to check for.

## Routes

- **Route A, one layered sheet** (e.g. an as-built site layout from AutoCAD): the hierarchy is encoded in layer names, such as one layer per combiner. Follow the workflow below.
- **Route B, a set of labelled sheets** (e.g. a PVcase design package with one stringing sheet per inverter block): the hierarchy is printed as text labels (`14-2-3`, `DCB 14-2`) and the sheets are separate zoomed viewports. See "Route B" further down.
- **Route C, flattened sheets** (no layers, no hierarchy labels, e.g. a PDFsam-merged execution project): objects are found by drawing style. See "Route C" further down.
- **Route D, one cabling sheet per station with leaders and a key plan** (e.g. as-built DC cabling sheets, one per CTIN): the hierarchy is in leader labels (`CIRC. N1-09 a TA01-1-05`) and a circuit table; sheets may mix AutoCAD plots and outline-text re-prints. See "Route D" further down.

Probe first. `python ../pid-to-kg/scripts/probe_pdf.py <pdf> --work <work>/probe --pages <range>` classifies the pages, and `list_layers.py` on one sheet shows whether layers survived and whether the hierarchy lives in layer names or in labels.

## Workflow (route A)

```
- [ ] 1. Layers:     python scripts/list_layers.py <pdf> --work <work> [--page N]
- [ ] 2. Layer map:  read <work>/layers.md; edit <work>/layer_map.json; re-run step 1 until roles are right
- [ ] 3. Build:      python scripts/build_layout.py <work>
- [ ] 4. Check:      python scripts/preview.py <work> [--bbox ...]; work through layout/qa_report.md; rebuild
- [ ] 5. GCPs:       agree control points with the user -> <work>/gcps.csv
- [ ] 6. Georef:     python scripts/georef.py <work> --gcps <work>/gcps.csv --crs <EPSG>
- [ ] 7. Export:     python scripts/export_geo.py <work> --name "<site>"
- [ ] 8. Report
```

### 1. Layers
`list_layers.py` writes `layers.md`: every layer with its object count, geometry types, typical sizes and sample text, grouped by the role the current `layer_map.json` gives it. It also reports the drawing scale it found (the PDF's model-space viewport measure, else the title-block `1:N`).

If the PDF has **no layers** (flattened on export) the layer route does not apply. Tell the user and ask for a PDF exported with layers, or the DWG/DXF.

### 2. Layer map
Read [references/procedure.md](references/procedure.md) section 1. In short, set regex rules so that:

- `module` matches the per-combiner module layers, with named groups `station`, `inv`, `cb` (e.g. `PVE_INV10-1-Combiner-Box-5`). Typical module size is about 1.0 x 1.7 m at drawing scale; check `top_sizes_pt` x the scale.
- `table` matches table or tracker outlines (exclude pile layers).
- `inverter_label` matches the layers that hold inverter tags, with `station` and `inv` groups.
- Site features (fence, site boundary, roads, trenches, cables, CCTV, weather station) map to their roles.

Check the scale against the scale bar with `crop.py`. If they disagree, set `scale.m_per_pt` in the map.

### 3–4. Build and check
`build_layout.py` writes `layout/`: sheet-space layers, `hierarchy.csv/json`, `summary.md` and `qa_report.md`. Then:

1. Run `preview.py <work>` and look at the whole sheet. Each inverter's combiners are filled in one colour, and station points are red; an orange point is a fallback.
2. For each warning, zoom with `preview.py --bbox x0 y0 x1 y1` (the normalized bbox QA prints) and compare with the drawing's own labels.
3. Resolve:
   - `combiner_in_separate_parts` with a suggested fix: confirm on the drawing that the stray area is labelled for the other inverter, then copy the rule from `layout/suggested_reassign.json` into `layer_map.json` `"reassign"`.
   - `station_location_fallback`: find the station skid or tag in a preview, convert its image position to sheet points (`x_pt = (x0 + u/img_w*(x1-x0)) * page_w`, same for y), and write `<work>/stations.json` as `{"1": {"x_pt": ..., "y_pt": ..., "source": "visual"}}`.
   - `partial_string`, `modules_outside_tables`: irregular rows are common near stations and roads. Leave them flagged unless the user has a string schedule.
   - `modules_per_string_inferred`: confirm the string length with the user if they know it, and set `strings.modules_per_string`.
4. Rebuild until no error remains and every warning has been checked.

### 5–6. Control points and georeference
Read [references/procedure.md](references/procedure.md) section 3. Ask the user for the best source they have, in this order:

1. As-built coordinates of inverter stations or the substation (O&M manual, asset register, SCADA). Reference them by id: `feature=ST10`.
2. Points they read from satellite imagery or Google Earth: fence corners, gates, station skids, substation. Get the sheet position from a preview.
3. In the UK, OS MasterMap features drawn on the base map (building corners, road junctions) with British National Grid coordinates.

The projected CRS is the CAD's grid if known (British National Grid EPSG:27700, a UTM zone, a state plane). With lon/lat GCPs and no `--crs`, UTM is picked automatically.

`georef.py` fits a similarity transform by default. A scale far from 1 or a large residual means a wrong control point or a wrong drawing scale. With one point it only translates, and the result is provisional.

### 7–8. Export and report
`export_geo.py` writes `out/`: WGS84 GeoJSON per layer, a KMZ for Google Earth, Shapefiles in the projected CRS, `hierarchy.csv` and `hierarchy.json` with coordinates, and `georef_report.md`.

Tell the user:

- where the files are;
- counts: stations, inverters, combiners, strings, modules;
- the CAD issues found and any reassign rules applied;
- how good the georeference is (method, RMSE, provisional or not);
- what is derived rather than drawn (strings, station points).

## Route B: multi-sheet labelled packages

```
- [ ] 1. Layers:    python scripts/list_layers.py <pdf> --work <work> --page <one stringing sheet>
- [ ] 2. Register:  python scripts/register_sheets.py <work> --key-page <general layout> --pages <stringing sheets>
                    open every register/overlay_pNN.png: the red linework must sit on the green
- [ ] 3. Layer map: "mode": "labels" plus label and geometry roles (references/procedure.md section 6)
- [ ] 4. Build:     python scripts/build_layout.py <work>; preview.py; QA until clean
- [ ] 5. GCPs:      printed survey coordinates -> python scripts/match_points.py <work> --known known.csv
                      --crs <EPSG> --pair <roleA>:<roleB> [...]; or GCPs from the user as in route A
- [ ] 6. Georef + export as in route A
```

- **Key sheet**: the general layout, which shows the whole plant. It can be flattened (no layers). It only gives the frame, and every detail sheet is registered onto it.
- **Registration** needs each sheet's measured model viewport (scale) and north-up sheets. It correlates the colours the sheets share (streams, roads, module rows). A peak ratio under about 1.15, or an overlay that does not sit on the key, means the sheet is wrong. Do not build on it.
- **Labels**: `string_label` and `combiner_label` rules carry a `text` regex with named groups. Labels merged into one PDF text run are split by regex match on character boxes.
- **Strings drawn in several polylines** (zigzag wiring plus return conductor) are joined automatically. `string_polyline_without_label` warns about the rest.
- **QA** compares extracted totals with the totals printed on the key sheet ("Total No of Modules"). Report any difference.
- **Printed coordinates**: design packages often survey a few points: trench-stream crossings, substation corners, access points. `match_points.py` finds them as intersections of two feature roles. It keeps only placements with true scale and north-up, writes `gcps.csv`, and reports where unmatched points should be. Check unmatched points visually. If one lands on the right feature, report it as an independent check.

## Route C: flattened sheets, by drawing style

```
- [ ] 1. Census:    count colour/type/size combinations on the layout and on the grounding plan; zoom on
                    one tracker, one station and one combiner box symbol
- [ ] 2. Layer map: "mode": "styles" with style rules per role (references/procedure.md section 7)
- [ ] 3. Build:     python scripts/build_layout.py <work>; preview.py; QA until clean
- [ ] 4. GCPs, georef, export as in route A (look for plant coordinates in the memoria first)
```

What each level comes from:

| Level | Source | Read or derived |
|---|---|---|
| Blocks | The face of a coloured outline that holds one block label and the most trackers | Read |
| Trackers | One style (e.g. black quads 4.3 x 25.2 pt) | Read |
| Stations | Symbol style nearest the "INV.xx" tag, one to one | Read |
| Combiner boxes | Symbol styles on the grounding plan (*red de tierras*), one style per box type, with that type's tracker capacity from the string schematics | Positions and types read |
| Tracker-to-box assignment | Minimum total distance within capacity | **Derived** |
| Strings | `per_tracker` per tracker, split along it | **Derived** |
| Box numbers | Top-down, left-right | **Derived** |

Other pages are moved onto the key page by matching a symbol both draw (`register_by`, usually the station symbol). QA compares trackers per block with the counts printed on the drawing (`expect_trackers`, keyed by label suffix) and checks box capacity against tracker counts.

## Route D: per-station cabling sheets with leaders and a key plan

Reference implementation: `scripts/sites/route_d_cabling_sheets/` (README there gives the order). Lessons: `references/lessons.md` section 5b.

```
- [ ] 1. Census:     styles per role on one layered and one flattened sheet; zoom on a row end, a board and a leader
- [ ] 2. Extract:    tables (vector outlines, or module cells filled and split at the table pitch), taps, boards,
                     row labels, transformer hatch
- [ ] 3. Build:      rows from taps; taps paired to tables in order along each row; circuits from a colour raster
                     of the cable, cut at the boards; names from leader OCR (sequence-repaired), table as check
- [ ] 4. Check:      debug image per sheet; circuits found vs circuit table; one tap per table; per-station counts
- [ ] 5. Place:      block fit on the key-plan highlight, then transformer symbol to key-plan transformer
- [ ] 6. Georef + export (provisional unless the package prints coordinates); correct with KMZ mode
```

| Level | Source | Read or derived |
|---|---|---|
| Station | sheet title; transformer symbol | Read |
| Level-1 board (combiner) | board symbols, named by one-to-one assignment from the circuits that reach them | Read |
| Circuit | cable component plus the leader whose ellipse sits on it | Read (OCR, checked) |
| Table / tap | one fused tap per table, paired in order along the row | Read |
| Strings | per tap, from the legend (fuses ×2) and module counts | **Derived** |

When the leader and the circuit table name different boards, use the board the cable physically reaches (named by the other circuits on it) and list the conflict in the QA report.

## Correcting a provisional placement

When the georeference rests on one published point (sites without survey data), open the exported KMZ in Fernando's DXF Georeferencer, KMZ mode (`R/kmz_align.R` in the georef project, an add-on that leaves the DXF app unchanged). The file loads what it needs, so from the project folder (RStudio or Positron):

```r
source("R/kmz_align.R")
launch_georef_kmz("output/converted_layouts/<site>/gis/<site>.kmz", mode = "auto")   # or launch_georef_kmz() for the start screen
```

`app.R` / Run App on the project opens the DXF app only; KMZ mode is Run App on `R/kmz_align.R` or the console call above.

- **Auto-align** downloads Esri imagery around the site. A coarse whole-site match (2 m grid, rotation ±2°) finds the arrays. Then each of up to 3 × 3 regions is matched within ±3 m, under half the row pitch. Each matched region becomes a control point in the app, which fits rotation and scale and shows the error per point.
- **Manual**: click a point on the layout, then the true spot on the satellite. One pair shifts, two or more pairs rotate and scale.
- **A weak match** (peak ratio under 1.15, or RMSE over 3 m) usually means the plant is not built in the imagery yet. Fall back to manual points.

## Naming

Ids follow `naming` templates in `layer_map.json`. The default mirrors common drawing labels: `ST10`, `INV10-01`, `INV10-01-CB05`, `INV10-01-CB05-S01`. For a scheme like `Inverter 10 > Combiner 10.05 > String 10.05.01`, set e.g. `"combiner": "{station}.{cb:02d}"` and `"string": "{station}.{cb:02d}.{string:02d}"`. Fields available: `station`, `inv`, `cb`, `string`.
