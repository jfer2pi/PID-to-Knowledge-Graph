# Lessons from real documents

Read this before starting on a new site. It holds what the first five sites taught, as rules to apply and as checks for what went wrong.

## Contents
1. Triage: which route a document needs
2. General rules
3. Route A lessons (one layered sheet)
4. Route B lessons (labelled multi-sheet packages)
5. Route C notes (flattened sheets)
5b. Route D lessons (per-station cabling sheets with leaders and a key plan)
6. Georeferencing lessons
7. Performance and environment
8. Site log

---

## 1. Triage: which route a document needs

Spend the first ten minutes here. The wrong route wastes hours.

1. **Find the drawing pages.** Project PDFs bury drawings inside 100 to 340 pages of memoria. Ask the user for the page range, or probe with `pid-to-kg/scripts/probe_pdf.py --pages`.
2. **Count the PDF layers.** `len(doc.get_ocgs())`. Plotters and even Word exports keep CAD layers. A PDF assembled with PDFsam or a print driver usually has none.
3. **Find the measured viewports.** Look for `/VP` with `/Measure` in the page object. The model-space viewport's `/X /C` is metres per point. The paper viewport is 0.3528 (mm per point): ignore it.
4. **Find where the hierarchy lives.**

| Where the hierarchy lives | Route |
|---|---|
| In layer names (`PVE_INV10-1-Combiner-Box-5`) | **A** |
| In printed text labels (`14-2-3`, `DCB 14-2`) on layered sheets | **B** |
| Nowhere in layers or labels: only colours, outlines and schematics | **C** (by drawing style) |
| In leader labels and a circuit table, one sheet per station, a shared key plan | **D** (leaders + key plan) |

5. **Look for printed coordinates before asking the user for GCPs.** Grep the whole document for 6- and 7-digit numbers with decimals ("COORDENADAS", "UTM", "ETRS89", "X/Y"). Coordinate sheets often sit 10 to 30 pages after the layouts.
6. **Render one sheet and zoom in on one tracker or table.** Ten seconds of looking saves a wrong assumption about how strings are drawn.
7. **A zip of sheets can mix producers.** Check `creator` and the OCG count per file: on the route D site six sheets were AutoCAD plots with 41 layers and four were Acrobat Distiller re-prints with no layers, no viewports and text turned into outlines.

## 2. General rules

- **Read the printed totals first** ("Total No of Modules", "Nº seguidores", "SUBCAMPO FORMADO POR 180 TRACKERS", data blocks). They are the acceptance test. An extraction that does not reproduce them is not finished.
- **Confirm every automatic fix on the drawing's own labels before applying it.** Reassign rules, station overrides and GCP matches all count.
- **Say what is read and what is derived.** Labels and layer names are read. Geometric string chunking, station points from tags, and a one-point georeference are derived. Every output row should say which.
- **Render overlays** (`preview.py`, `register/overlay_*.png`) **and look at them.** Every bug in the first three sites was visible in an overlay before it was visible in the numbers.
- **Generalise only from evidence.** A pattern seen on one site goes into the layer map for that site. It goes into code defaults only after a second site confirms it.

## 3. Route A lessons (one layered sheet)

- **CAD teams colour arrays by combiner**, so the combiner layers *are* the module geometry. Each quad on such a layer is one module. Table quads are a whole number of modules long.
- **Tags are often drawn as glyph outlines, not text.** The text layer then holds only the title block. Station tags can still be found from glyph positions. INVxx-01 over INVxx-02 share a left edge, so pair the tags *across the two inverter layers*. Pairing within one layer picks up stacked combiner tags. This happened on the route A site ST21 and ST22 until fixed.
- **Layer mix-ups happen.** On the route A site, one inverter's CB02 and CB06 modules were on the next inverter's layers. Look for a combiner drawn in two separate areas together with another inverter missing that combiner number. Decide which inverter a stray part belongs to by **centroid distance**. Edge distance ties when rows touch.
- **Trailing missing combiners count too.** The gap check must look up to the usual combiner count, not just inside each inverter's own range.
- **Irregular rows near stations and roads** give partial strings and modules outside table outlines. Leave them flagged; do not force them into a string.
- **Scale.** Prefer the model viewport measure, then check it against the scale bar. Title-block text can say "1:3.000" with a thousands dot, so parse it with separators.

## 4. Route B lessons (labelled multi-sheet packages)

- **PVcase packages** print one "DETALLE BLOQUE INVERSOR n" sheet per inverter. Each is a separate zoomed viewport (1:1500 or 1:1750 at Arcos 2), so sheets share no frame.
- **Register sheets onto the general layout**, even a flattened one. Rasterise the colour classes both draw (streams, roads, module strokes, fence) at 1 m per pixel and cross-correlate per channel. With scale from the viewports and north-up sheets, only a translation is unknown. Peak ratios of 1.2 to 2.1 were all correct; check the overlays anyway.
- **Labels can be merged in one PDF text run** ("DCB 14-12DCB 14-6"). Split them with regex matches on character boxes (`get_texttrace` chars), never on whitespace.
- **One string can be several polylines.** At Arcos 2 a string was the full-length wiring zigzag plus a shorter return line in the same module column. Join unlabelled polylines to the labelled one when *either* line lies mostly along the other. A one-sided test failed at 49.5% overlap.
- **Three module columns per tracker means one string per column** ("3H"). Assign modules to the nearest string polyline within 0.6 module widths. The result was 3,616 strings × 26 modules = 94,016, equal to the printed total.
- **Station location**: the inverter-symbol blob with the most home-run cable vertices.
- **Memory**: do not hold all sheets' drawings at once. Stream page by page. A 1.45M-path key sheet plus 14 sheets went over 7 GB.

## 5. Route C lessons (flattened sheets)

Learned at Huévar I (PAL project, pp. 197–207, PDFsam-assembled, no layers, no viewports):

- **Run a style census before anything else.** One `(type, colour, size)` class held exactly the printed tracker total (2,448 black quads at 4.3 × 25.2 pt). That is how you know you have the trackers.
- **Block outlines are thick strokes converted to fills**, one object per block in a colour of its own. Polygonise each object's own segments separately; mixing objects joins neighbouring blocks. Choose the face that holds exactly one block label and the **most trackers**, then the smallest area. Do not exclude by colour: red and light-blue block outlines were lost to an exclusion list meant for the fence and streams.
- **Combiner boxes are on the grounding plan**, not the layout: small symbols on the earth conductor. Two symbol styles meant two box types, black for 20-input and red for 18-input. The string schematics give their capacity (10 or 9 trackers), and the count per style checks the design: 180 = 10 blocks × 18, and 71 against an expected 72.
- **A box symbol can be hidden under a block label.** In block 11 the box grid broke exactly where the "11*" label box sits. Flag it, keep every tracker assigned, and do not invent the box.
- **Sheets of one set plotted at one scale differ by a translation.** Match a symbol both draw (station skids) by translation vote: 14 of 14 agreed on +82.9, −10.3 pt.
- **INV tags were merged into one long text run**, and some sit about 30 m from their skid. Use regex matches on character boxes, and pair tags to symbols one to one with a 60 m limit. A fixed 30 m nearest-neighbour test missed 3 of 14.
- **Look for plant coordinates in the memoria**, the text chapters, not only the drawings. "Coordenadas de la planta … ETRS89 Huso 29" gave a provisional anchor, and the PVsyst report's latitude and longitude confirmed it to about 0.01°.
- **PyMuPDF**: create all pages first, then take `doc[i]`. A page object made before `new_page` goes stale.

## 5b. Route D lessons (per-station cabling sheets with leaders and a key plan)

Learned on the route D site (ten *Cableado corriente continua (BT) CTIN-nn* sheets, 1:1,200, each with the same 1:15,000 key plan):

- **Check the scale from the tables, not only the viewport.** A 20-module table was 47.4 pt = 20.0 m at 0.4216 m/pt on every sheet, which confirmed that the Distiller re-prints kept the AutoCAD scale.
- **Module size in plan is foreshortened.** Cells were 1.0 × 1.77 m: a 1.96 m module tilted 25°. 40 modules per table over about 2,000 tables against the published plant size gave 306 W, which confirms the reading.
- **PyMuPDF on a rotated page**: `get_drawings()` returns unrotated coordinates, `get_pixmap(clip=)` takes displayed ones. Apply `page.rotation_matrix` to drawings and words once, and do everything else in displayed coordinates.
- **Part of the cable can be raster.** On the AutoCAD sheets many green cable runs were 34 × 564 px image strips, not vectors. Trace cables on a colour raster (4 px/pt, anti-aliasing off) for all sheets alike, dilate 1 px (strips meet a pixel out of line), bridge gaps up to 16 px along rows and columns (dots, leader ellipses and purple cables are drawn on top), then cut at the board symbols.
- **Rows come from the taps, and every table in a row is wired.** Taps sit on table boundaries and bunch in pairs near the boards, so "the table under the cable" undercounts. Pair taps to tables in order along each row with a monotone alignment. Cluster tap rows at a third of the row pitch: one row had taps along the top and the bottom edge of its tables.
- **Flattened tables**: draw the thin grey module strokes, fill holes (each cell is a closed box), open, label, and split runs at the table pitch (48.08 pt). Where a label covers cells, extend the row's grid to cover its taps.
- **Merge cable fragments only on the same row, only when adjacent, and never across a board.** A cross-row fallback glued circuits whose link to the board was drawn in black.
- **Name circuits from the leaders.** Each label `CIRC. N1-xx a TAnn-1-mm` has a leader whose ellipse sits on that circuit's cable: a direct, local mapping. Leaders are two-segment strokes (underline, then the segment to the tip, in either order) or two separate paths: join a loose diagonal to an underline end. Skip tips nearer purple than green (board leaders).
- **OCR every leader.** On the AutoCAD sheets the leader font maps characters with an offset and drops the digits (`&,5& 1 D 7$` = `CIRC. N1 a TA`), and the re-prints have no text. Single-line OCR of the crop above the underline (500 dpi, psm 7), then a whitelisted pass on the left 55–70% of the line. Normalise `TAO`, `TAQ`, `Nt`, `Ni`.
- **Repair OCR with order.** N1 numbers run top to bottom and west to east. Distrust a reading only if it is missing from a gap-free table, duplicated, or out of order; refill a gap only when exactly one missing number fits. An aggressive longest-run filter threw away good readings where two leaders tip in swapped order.
- **The circuit table is a check, not the truth.** Trust it only from PDF text or a gap-free OCR. The drawings themselves disagreed four times between leader and table (e.g. `N1-19 a TA09-1-10` on the drawing, TA09-1-09 in the table): use the board the cable physically reaches, as named by the other circuits on it, and list each case.
- **Boards side by side** (two or three at one row) are touched by several cables: name board symbols by one-to-one assignment over all touches, not first-touch votes.
- **Never run two OCR jobs that share temp file names.** A foreground run and a background batch both wrote `/tmp/lead.png`; sheet 1 read sheet 9's labels (`TA09`). Name temp files per process and per sheet.
- **Area polygons per combiner (and circuit, inverter)** are worth adding when strings are rectangles: union of the group's tables, closed at a radius just over half the row gap (2.1 m for a 4.03 m gap), clipped so they never cover another group's table. Keep a group split by an aisle or by another board's table as a multipart polygon rather than painting over the gap.
- **A sheet's view shows its neighbours' tables.** After assembly, drop a table whose centre lies outside its own key-plan block and inside another (one on the route D site; every station then had the same number of).

## 5b2. Route A with tracker outlines per station layer (Casilla)

- **One layer per CT, trackers as outline boxes with module cross-lines** (`0_CT Nº1` … `Nº14`). Count trackers from the boxes (the loose verticals are torque tubes, not sides), and modules from the cross-lines: 41 lines = 42 rows × 2 = 84 (2P). Equal object counts per layer (5,160) were the first hint of 120 trackers each.
- **Strings from the printed module total**: 140,812 / 28 = 5,029 exactly; 84-module trackers carry 3 strings and 56-module ones 2. Geometry is derived (thirds of the tracker).
- **Placing a printed coordinate that does not say which point it is**: the location sheet drew a circle around the plant. Register that sheet to the layout through symbols both draw (the 14 CT symbols: 0.1–0.7 m residuals) and take the circle centre. Check the bin size when locating symbols on a histogram: 0.25 pt bins read as 1 pt put the plant 7 km away.
- **A dashed plant contour does not close into a boundary**: closing the dashes merged it with the floodplain. Export the contour as drawn lines.
- **Unzip on the Mac cannot overwrite** (deletion is off): write over an existing file with `unzip -p zip member > file` instead.

## 5c. Rolling the hierarchy up from its children

- **Rule:** if the finest drawn level names its parents, every parent level must exist in the output (area + record point), but only build what is missing. Nothing existing is redrawn.
- `pvgeo/rollup.py`: area = union of the children closed at just over half the typical row gap, clipped off other groups' children, never overlapping. The row gap is measured between blocks of children merged at 0.35 m (strings inside a table can sit 5–10 cm apart; a "nearest non-touching sibling" test picks the string two rows over instead of the next row). Measured: the route A site 1.10 m, Arcos 2 1.9 m, the route D site 2.2 m, Huévar I 2.8 m.
- **Match parents on the ids the children carry.** the route D site strings carry inverter and combiner but not station; matching on the full chain would have duplicated every combiner.
- **Use the 90th-percentile row gap, not the median**, and cap at 5 m: Casilla's 3.85 m and 4.13 m trackers on a 9.1 m pitch leave gaps of 4.97 and 5.25 m, and the median left every station area in pieces (8 to 22 parts; 1–2 after).
- **Keep combiner areas even when a combiner has one circuit**; only a station that is a single inverter is skipped as a duplicate.
- Applied to the four sites: the route A site gained about 20 station areas (two inverter fields each, mostly two parts); Arcos 2 and Huévar I had nothing missing (one inverter per station); the route D site already had circuit, combiner and inverter areas.

## 6. Georeferencing lessons

- **Look for surveyed points printed in the document** and find them on the drawing as feature intersections (`match_points.py`). At Arcos 2, "cruce zanja-DPH" meant the DC home-run trench or MV trench crossing a stream. That gave three automatic GCPs at 0.48 m RMSE.
- **A point that does not match can still be a check.** Its predicted position should land on the right feature type on the general layout, as Arcos 2 crossing 4 did on the stream.
- **Constrain the search.** Allow scale within 3% of 1 and rotation within 3°, because CAD layouts are true scale and grid-north. Without limits, the four points match noise.
- **CRS from context.** UK on OS MasterMap: British National Grid, EPSG:27700. Andalusia west of 6°W: ETRS89 UTM 29N, EPSG:25829; sheets often say "UTM H29 ETRS89". Spain otherwise: UTM 30N, EPSG:25830.
- **With no coordinates at all**, a published site centre (planning documents, archaeology reports, GEM) gives a *provisional* one-point placement. Label it provisional everywhere.
- **The cloud workspace cannot reach OSM, Overpass or tile servers.** Do not plan on automatic matching against basemaps from here.
- **A shared key plan is a common frame.** When every sheet carries the same key plan with its own block highlighted, place each sheet by the IoU of its tables against the highlight (0.83–0.94 on the route D site), then correct with a symbol drawn at true size in both, such as the station transformer: shifts of 0.3–7 m, after which east-west neighbours sat a uniform 1.5 m apart. The block outline alone is biased by its margin around the tables.
- **Elsewhere**: pick the WGS 84 UTM zone for the longitude (a national SIRGAS or ETRS frame is usually within a metre). GEM and WRI give a plant point; place the plant centroid on it and say it is provisional.

- **Auto-aligning tracker rows to imagery**:
  - Rows repeat every 5–6 m, so a local search wider than half the pitch locks onto the neighbouring row. Do the coarse match over the whole site, where block outlines break the repetition, then the local matches within ±3 m.
  - Do not trust rotation from one global correlation at 1 m: pixel aliasing of narrow rows outweighs fractions of a degree. Solve rotation and scale from several regional shifts instead. On a synthetic test this gave 0.05° and under 1 m at 300 m from the centre.

## 7. Performance and environment

- `get_drawings()` on a 460k-path sheet takes about 20 s. Cache it (`cache/page_NN.pkl`).
- **Intersecting against 19k small stream polygons**: query an STRtree per geometry. Unioning everything first took 12 minutes, against under 2 with the tree.
- **Commands that run several minutes** should run in the background with a long timeout. Poll the output; do not start a second copy.
- **OCR is the slow step**: about 50 leaders × up to 4 Tesseract calls per sheet, 1–2 minutes a sheet. Run sheets one after another in the background.
- **Quote paths with spaces** ("the route A site.kmz"). Use absolute paths for zip targets: a relative `../../..` that resolves to `/` trips the safety check.

## 8. Site log

| Site | Document | Route | Result |
|---|---|---|---|
| Route A example | As-built layout, 1 sheet, about 500 layers | A | about 20 stations, 40 inverters, 400 combiners, 9,000 strings, 200,000 modules. Two CAD layer mix-ups fixed. Provisional placement from a published site centre. |
| Arcos 2, Puerto Real, 47 MWdc | Project PDF pp. 58–71 (PVcase stringing) + p. 55 layout + pp. 82–85 crossings | B | 14 CT, 224 DCB, 3,616 strings, 94,016 modules (= printed). 0.48 m RMSE in EPSG:25829 from three printed crossings. |
| Huévar I, Sevilla, 50 MWp | PAL project PDF pp. 197–207, flattened (layout p. 199 + grounding plan p. 200) | C | 14 CT, 251 combiner boxes (one hidden under a label), 2,448 trackers (= printed per block), 4,896 derived strings, 127,296 modules. Provisional placement from the memoria's plant coordinate (EPSG:25829). |
| Casilla Solar PV, Valencina de la Concepción (Sevilla), 49.3 MWp | Anexo urbanístico rev1 (37 pp.), layout on p. 37, 1:6,500, 147 layers | A | 14 CT, 1,678 trackers (= printed), 140,784 modules (printed 140,812: one string short), 5,028 derived strings of 28, 14 derived station areas. No inverters or combiner boxes drawn. Provisional placement: printed coordinate at the location-circle centre (EPSG:25829). |
| Route D example | Ten as-built DC cabling sheets, one per CTIN, 1:1,200 + key plan; six AutoCAD, four Distiller re-prints | D | 10 CTIN, about 160 level-1 boards, about 300 circuits (= circuit tables, checked by eye where OCR'd), about 2,000 tables / fused taps (about 200 per CTIN), about 86,000 modules, about 4,300 derived strings. Four leader-versus-table conflicts in the drawings logged. Provisional placement on the GEM plant point. |
