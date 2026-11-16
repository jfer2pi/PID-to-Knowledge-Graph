# Changelog

## Unreleased (fork): solar-layout-to-geo

- New skill `skills/solar-layout-to-geo`: CAD-exported solar layout PDF to a georeferenced PV hierarchy (station > inverter > combiner > string) without DXF conversion.
- Layer-aware vector reading (PDF optional-content groups), drawing scale from the PDF viewport measure or title block.
- Hierarchy builder: modules to tables, strings derived from module rows, station points from stacked inverter tags, `stations.json` overrides.
- QA: layer mix-up detection with suggested `reassign` rules, numbering gaps, partial strings, modules outside tables.
- Georeferencing from control points (translation, similarity, affine) with residuals; export to GeoJSON, KMZ, Shapefile and hierarchy CSV/JSON.
- `preview.py` overlay for visual checks; end-to-end test on a synthetic layered PDF.
- Route B for labelled multi-sheet packages (PVcase): `register_sheets.py` places detail sheets on the general layout by colour-class cross-correlation; `labelled.py` reads strings and combiners from printed labels (merged text runs split by character boxes, multi-part string polylines joined); totals cross-checked against the printed data block.
- Route C for flattened sheets (`"mode": "styles"`, `pvgeo/styled.py`): trackers, stations, block outlines and combiner-box symbols found by drawing style; pages registered by a shared symbol; trackers assigned to boxes within each box type's capacity; tracker counts checked against the printed per-block totals. Worked layer maps for all three sites in `references/examples/`.
- `match_points.py`: surveyed coordinates printed in the document matched to drawn feature intersections (similarity search with scale and rotation limits) and written as GCPs.
- Route D for per-station cabling sheets with leader labels and a shared key plan (`scripts/sites/route_d_cabling_sheets/`): cables traced on a colour raster, taps paired to tables along each row, circuits named from OCR'd leaders with order-based repair and the circuit table as a check, sheets placed on the key plan by block fit and transformer symbol. Lessons in `references/lessons.md` section 5b.
- Hierarchy roll-up (`pvgeo/rollup.py`, run by `export_geo.py`; `rollup_geo.py` for delivered folders): every parent level the children name (circuit, combiner, inverter, station) gets an area polygon and a record point, built only where missing and flagged as derived.

## 0.1.0 (unreleased)

First release.

- Page classification for vector (with or without a text layer), scanned and hybrid PDFs.
- `--pages` on the probe picks the P&ID pages out of a longer document, such as a permit application; later steps use only those pages.
- OCR is optional and installs only on Python 3.10–3.12, where its package is available; the skill runs without it on newer Python.
- Rendering adapts to the drawing:
  - orientation is detected automatically;
  - resolution is chosen from the measured text size;
  - pages are cut into overlapping tiles with blank-tile detection.
- Deterministic hints from the PDF text layer or OCR (RapidOCR), used to flag possible missed tags.
- Extraction schema and procedure for Claude's visual reading of each sheet.
- Graph builder:
  - merges items across sheets by tag;
  - expands pipe runs into segments, including tees and taps;
  - pairs off-page connectors;
  - locates instruments;
  - infers ISA-5.1 control loops, including relays, cascades, interlocks and VFD drives;
  - derives equipment-level flow.
- Outputs:
  - `graph.json`, the canonical graph;
  - `graph.duckdb`, with views and the `upstream`/`downstream` macros;
  - `summary.md`, for LLM context;
  - `qa_report.md`.
- `kg_query.py` CLI, GraphML and Neo4j export, and an `eval_kg.py` scorer.
- Handling for problems found on real drawings:
  - the same tag on two items (`duplicate_tag`);
  - tags reused across sheets (`tag_reused`);
  - off-page flags naming the wrong drawing (`off_page_reference_mismatch`);
  - revision suffixes on drawing numbers;
  - two revisions of one drawing in one PDF (`possible_duplicate_revision`);
  - mounted equipment (`part_of`);
  - area instruments (`area` boundaries);
  - untagged gauges (`function`);
  - valve-type codes kept out of loops;
  - P&ID detail preferred over PFD shortcuts.
- Tested on three real plants: two vector drawing sets with outlined text and one scanned set.
