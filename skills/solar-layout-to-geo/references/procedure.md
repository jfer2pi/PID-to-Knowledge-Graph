# Procedure details

## Contents
1. Writing the layer map
2. How the hierarchy is built
3. Control points
4. Outputs and fields
5. Pitfalls seen on real layouts
6. Route B: labelled multi-sheet packages
7. Route C: flattened sheets by drawing style

---

## 1. Writing the layer map

`layer_map.json` in the work directory:

```json
{
  "page": 1,
  "scale": {"ratio": null, "m_per_pt": null},
  "roles": [
    {"role": "module", "pattern": "^PVE_INV(?P<station>\\d+)-(?P<inv>\\d+)-Combiner-Box-(?P<cb>\\d+)$"},
    {"role": "table", "pattern": "^SADEF_(?!.*PILE).*TABLE"},
    {"role": "inverter_label", "pattern": "^PVE_Inverter-(?P<station>\\d+)(-(?P<inv>\\d+))?$"},
    {"role": "fence", "pattern": "(?i)fence"}
  ],
  "strings": {"modules_per_string": "auto"},
  "stations": {"method": "stacked_tags", "override_file": "stations.json"},
  "naming": {"station": "ST{station:02d}", "inverter": "INV{station:02d}-{inv:02d}",
             "combiner": "INV{station:02d}-{inv:02d}-CB{cb:02d}",
             "string": "INV{station:02d}-{inv:02d}-CB{cb:02d}-S{string:02d}", "table": "T{table:05d}"},
  "reassign": []
}
```

- Rules are regexes, tried in order; the first match wins. Named groups `station`, `inv`, `cb` carry device numbers. Digits become integers.
- **Roles**:
  - The hierarchy roles are `module`, `table` and `inverter_label`.
  - The site roles are `site_boundary`, `fence`, `access_road`, `trench`, `mv_cable` and `lv_cable` (lines), `cctv`, `weather_station` and `comms` (points), and `substation` and `building` (polygons).
  - `other` exports a layer as lines.
- **How to recognise layers in `layers.md`**:

| Layer type | What it looks like |
|---|---|
| Modules | Thousands of small quads (`qu`) of one size. Width x height x scale ≈ 1.7 x 1.0 m, or the transpose. |
| Tables | Quads a whole number of modules long, e.g. 22 modules x 1.65 m ≈ 36 m. |
| Inverter tags | Filled shapes (`f`) the size of text glyphs. Tags are often drawn as outlines, not text. |
| Fence and boundaries | Long line work (`l`). |

- **If module layers are not per combiner** (one `PV_MODULES` layer, say), map that layer as `module` without groups. The hierarchy then stops at tables, and combiners come out as `UNASSIGNED-n`. Tell the user, because combiner areas then need another source, such as the string schedule or colours.
- **Scale**: `m_per_pt` overrides everything. Otherwise the PDF viewport measure is used, and then the title-block `1:N`. Always check against the scale bar.

## 2. How the hierarchy is built

1. **Modules**: each quad on a module layer is a module. Outlines drawn twice are dropped (`duplicate_modules`). `reassign` rules move modules of a given layer inside a normalized page box to another station, inverter and combiner.
2. **Tables**: quads on table layers. Very small quads (under 25% of the median area) are ignored. Each module goes to the table containing its centre. Modules outside every table are grouped into reconstructed tables (`modules_outside_tables`).
3. **Module rows**: within a table, modules are split into rows across the table's short axis, then ordered along its long axis.
4. **Strings**: each table's modules are read row by row, top to bottom and left to right along the table, then cut into runs of `modules_per_string`. `auto` takes the most common row length. Strings never span tables. A short run is a `partial_string`. Strings are numbered per combiner: tables top to bottom, then left to right. **This is geometric. It matches the as-built schedule only if the installer followed the same order.** That is why every string row carries `derived: true`.
5. **Combiners**: all strings with the same station, inverter and combiner, as one area (MultiPolygon).
6. **Inverters**: the union of their combiners. **Stations**: a point.
   - `stacked_tags` finds the station's two inverter tags (e.g. INV10-01 over INV10-02) on two different inverter layers, sharing a left edge.
   - Stations with a single inverter, or other tag styles, fall back to the array centroid and are flagged.
   - `stations.json` overrides any station.

### QA codes

| Code | Severity | Meaning / action |
|---|---|---|
| `no_modules` | error | No module layer matched. Fix the layer map. |
| `combiner_in_separate_parts` | warning | One combiner layer covers areas far apart. If another inverter lacks that combiner number, a fix is suggested in `suggested_reassign.json`. Confirm it on the drawing labels first. |
| `combiner_numbering_gap` | warning | Combiner numbers missing inside an inverter's range. |
| `station_location_fallback` | warning | Station placed at the array centroid. Find it visually and add it to `stations.json`. |
| `partial_string` | warning | A string with fewer modules than the string length. |
| `modules_outside_tables` | warning | Modules with no table outline around them. |
| `table_shared_by_combiners`, `tables_without_modules` | warning | Check on the drawing. |
| `fewer_combiners`, `combiner_size_differs` | note | Usually real design variation. |
| `modules_per_string_inferred`, `reassigned_modules`, `no_table_layer` | note | For the report. |

## 3. Control points

`gcps.csv` columns:

- **`id`**: any label.
- **The sheet side**, one of:
  - `feature`: a hierarchy id such as `ST10` (the station point), `INV10-01` or `INV10-01-CB05` (the area centroid), or `site:<role>` (the centre of that feature's bounding box, e.g. `site:site_boundary`).
  - `sheet_x_pt` and `sheet_y_pt` in PDF points, origin top-left, y down.
- **The map side**, one of:
  - `easting` and `northing` in `--crs`;
  - `lon` and `lat`.

**Getting sheet points from a preview image.** For a preview made with `--bbox x0 y0 x1 y1` on a page W x H pt, an image pixel (u, v) in an image of size (w, h) is:

```
x_pt = (x0 + u / w * (x1 - x0)) * W
y_pt = (y0 + v / h * (y1 - y0)) * H
```

Rendered images may be shown downscaled. Use the original image size.

**Choosing points.**
- Use 3–6 points near the corners of the site, not in a line.
- Use station skids, the substation, fence corners and gates.
- Avoid the module areas' centroids: imagery shows the panels, but a centroid on the drawing and a centroid on imagery are rarely the same point.
- Re-run `preview.py --gcps` to see each point and its residual.

**Interpreting the fit.**

| Result | Meaning |
|---|---|
| Similarity scale within 1% of 1, residuals under ~2 m | Good. |
| Scale off by more than 2% | Wrong drawing scale or a wrong point. |
| One big residual | That point is wrong, or it was matched to a different feature. |

**Affine** fits suit scans and distorted plots only. On a CAD plot they can hide a bad point by shearing the drawing.

## 4. Outputs and fields

`out/hierarchy.csv` has one row per station, inverter, combiner and string, in depth-first order:

| Field | Meaning |
|---|---|
| `id`, `level`, `parent`, `path` | Identity and place in the tree, e.g. `ST10 > INV10-01 > INV10-01-CB05 > INV10-01-CB05-S01` |
| `station`, `inverter`, `combiner`, `string` | Device numbers |
| `n_inverters`, `n_combiners`, `n_strings`, `n_tables`, `n_modules` | Counts below this item |
| `table` | For strings: the table they sit on |
| `location_source` | For stations: `station_tag`, `array_centroid` or what `stations.json` says |
| `derived` | Strings: `True` (derived, not read from a schedule) |
| `partial` | Strings shorter than the string length |
| `x_pt`, `y_pt` | Sheet position (PDF points) |
| `easting`, `northing` | Projected coordinates |
| `lon`, `lat` | WGS84 coordinates |

Layers in `out/` carry the same ids, so a SCADA tag table can be joined to them.

## 5. Pitfalls seen on real layouts
6. Route B: labelled multi-sheet packages

- **Tags drawn as shapes.** CAD "text to geometry" plotting is common, so the PDF text layer holds only the title block. Tags are read from glyph-shape positions on their own layers, not as text.
- **Modules of one inverter on another inverter's combiner layer.** the route A site had two combiners of one station drawn on the next station's layers. Look for `combiner_in_separate_parts` together with a gap or a missing combiner on a neighbour.
- **A whole block of linework on one inverter layer.** the route A site's `PVE_Inverter-1-1` holds tens of thousands of strokes. Only filled glyph-sized shapes are used as tags, so this is harmless.
- **Irregular rows beside stations and roads.** Tables are shortened and a few modules sit outside the table outline. Strings there come out partial.
- **Base map in the national grid.** UK layouts on OS MasterMap are drawn in British National Grid at true scale, so a similarity fit should give a scale of 1 and a rotation of 0.

## 6. Route B: labelled multi-sheet packages

Example `layer_map.json` for a PVcase package (Arcos 2):

```json
{
  "mode": "labels",
  "roles": [
    {"role": "string_label", "pattern": "^PVcase Stringing Numbers$", "text": "(?P<station>\\d+)-(?P<cb>\\d+)-(?P<string>\\d+)"},
    {"role": "combiner_label", "pattern": "^PVcase Device Numbering$", "text": "DCB\\s*(?P<station>\\d+)-(?P<cb>\\d+)"},
    {"role": "string", "pattern": "^PVcase Strings$"},
    {"role": "module", "pattern": "^PVcase Modules$"},
    {"role": "combiner", "pattern": "^PVcase DC Combiners$"},
    {"role": "inverter", "pattern": "^PVcase Central Inverters$"},
    {"role": "homerun_cable", "pattern": "^PVcase DC Cables \\(Combiner - Central inverter\\)$"},
    {"role": "fence", "pattern": "^PVcase Fence$"},
    {"role": "access_road", "pattern": "^PVcase Road$"},
    {"role": "mv_cable", "pattern": "^Zanja MT$"},
    {"role": "stream", "pattern": "^HS1_L_NAT$"}
  ],
  "naming": {"station": "CT{station:02d}", "inverter": "INV{station:02d}",
             "combiner": "DCB {station}-{cb}", "string": "{station}-{cb}-{string}"}
}
```

**How it is built**

1. Every string label goes to the nearest string polyline within 3 m, one to one, closest pairs first.
2. Unlabelled polylines that run along a labelled one (more than half of either line within a third of a module width) join that string.
3. Every module goes to the string whose polyline is nearest, within 0.6 module widths.
4. String polygon = minimum rotated rectangle of its modules.
5. Combiner area = union of its strings.
6. Combiner box = the nearest combiner symbol to its label.
7. Station = the inverter-symbol blob with the most home-run cable vertices.

**QA codes**

| Code | Meaning |
|---|---|
| `string_without_polyline`, `string_polyline_without_label` | A label and its wiring did not pair up |
| `string_module_count` | A string with a different module count from most strings |
| `combiner_box_not_found` | No box found for a combiner |
| `combiner_numbering_gap`, `string_numbering_gap` | Missing numbers in a sequence |
| `string_label_conflict` | The same id appears on two sheets more than 5 m apart: a registration problem or a duplicate label |
| `matches_printed_total`, `differs_from_printed_total` | Comparison with the totals printed on the key sheet |

**Matching printed coordinates**

- `known.csv` has `id, easting, northing, note`.
- Choose `--pair` from what the coordinate sheet shows. For "cruce zanja-DPH", the trench is the DC home-run or MV trench and DPH is the stream, so use `homerun_cable:stream` and `mv_cable:stream`.
- The search keeps the placement with the most matched points within `--inlier-m` (default 4 m), with scale within 3% of 1 and rotation within 3 degrees.

## 7. Route C: flattened sheets by drawing style

The worked example is `references/examples/huevar1_routeC.layer_map.json`. Each style rule matches drawings by:

| Field | Meaning |
|---|---|
| `type` | `s`, `f` or `fs` |
| `color` / `fill` | RGB 0–1, within 0.02 |
| `size_pt` | Width and height, within `tol`; either orientation unless `"rotatable": false` |
| `n_items` | Path segment count, to tell symbols apart |
| `items` | All items of one kind, e.g. `"qu"` |
| `min_size_pt` | Minimum size |
| `saturated_or_black` | Only saturated colours or black |
| `exclude_fills` | Colours to skip |
| `page` | One page or a list of pages |

Text roles take `text` (a regex with named groups) and an optional `layer`.

**Roles**

| Role | What it is |
|---|---|
| `tracker` | Trackers |
| `station_symbol` | Station symbols. Also the default `register_by` role, so put it on every page you use. |
| `combiner` | Combiner boxes, one rule per box type, each with `capacity` (trackers per box) and `name` |
| `block_outline` | Coloured outlines |
| `block_label` | Groups `station` and an optional `suffix` |
| `station_label` | Group `station` |
| Site roles | `fence`, `access_road`, `stream`, ...; exported as lines |

**Settings**

| Setting | Meaning |
|---|---|
| `expect_trackers` | Printed trackers per block, by label suffix, e.g. `{"*": 162, "": 180}` |
| `strings` | `{"per_tracker": 2, "modules_per_string": 26}`, from the string schematics |
| `scale` | `ratio`, or left unset to read the title block ("1:3.000" is handled) |
| `min_trackers_per_block` | Default 10 |

**Finding the styles.** Run a census of `(type, colour, fill, rounded size)` over `get_drawings()` on the layout page.

| Feature | What gives it away |
|---|---|
| Trackers | A count that equals the printed total (2,448 at Huévar I) |
| Station symbols | Small filled shapes, about as many as there are inverters |
| Combiner symbols | Repeated filled symbols of one size, usually two colours for two box types |
| Block outlines | Single large filled objects of a colour of their own (thick strokes converted to fills) |

**QA codes**

| Code | Meaning |
|---|---|
| `page_registered`, `weak_registration`, `page_not_registered` | Result of moving other pages onto the key page |
| `block_outline_not_found`, `trackers_outside_blocks`, `combiners_outside_blocks` | Something lies outside every block |
| `matches_printed_total`, `differs_from_printed_total` | Trackers per block against the printed counts |
| `combiner_capacity_mismatch` | Box capacity does not add up to the trackers. Every tracker is still assigned, by giving existing boxes spare capacity; affected boxes carry `over_capacity`. |
| `station_location_fallback` | A station placed without its symbol |
| `derived_levels` | Lists what is read and what is derived |
