#!/usr/bin/env python3
"""Build the PV hierarchy and sheet-space layers from a layout PDF.

Uses layer_map.json to find module, table and inverter-label layers, then
writes to <work>/layout/:

    stations|inverters|combiners|strings|tables|site.geojson
                         features in sheet metres (X east, Y north, local origin)
    modules.geojson      every module with its string and position (--modules)
    hierarchy.csv        one row per station, inverter, combiner and string
    hierarchy.json       the same as a nested tree
    qa_report.md         errors, warnings and notes to check on the drawing
    summary.md           headline counts and the scale used

Usage:
    python build_layout.py work/my-site [--modules]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import frame, load_map, load_page, source  # noqa: E402
from pvgeo import hierarchy  # noqa: E402
from pvgeo.writers import write_geojson  # noqa: E402

CSV_COLS = ["id", "level", "parent", "path", "station", "inverter", "combiner", "string",
            "n_inverters", "n_combiners", "n_strings", "n_tables", "n_modules", "table",
            "location_source", "derived", "partial", "x_pt", "y_pt"]


def tree(rows: list[dict]) -> list[dict]:
    nodes = {r["id"]: {**{k: v for k, v in r.items() if k not in ("path",)}, "children": []} for r in rows}
    roots = []
    for r in rows:
        p = r.get("parent")
        (nodes[p]["children"] if p in nodes else roots).append(nodes[r["id"]])
    for n in nodes.values():
        if not n["children"]:
            n.pop("children")
    return roots


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work", type=Path)
    ap.add_argument("--modules", action="store_true", help="also write every module (large)")
    args = ap.parse_args()

    lmap = load_map(args.work)
    reg_path = args.work / "register.json"
    if lmap.get("mode") == "styles":
        # route C: flattened sheets, objects found by drawing style
        import pymupdf
        from pvgeo import styled
        from pvgeo.vector import SheetFrame, scale_ratio_from_text, Span
        doc = pymupdf.open(source(args.work)["pdf"])
        kp = doc[int(lmap["key_page"]) - 1]
        sc = lmap.get("scale", {})
        if sc.get("m_per_pt"):
            fr, how = SheetFrame(float(sc["m_per_pt"])), f"layer_map m_per_pt={sc['m_per_pt']}"
        else:
            r = sc.get("ratio") or scale_ratio_from_text(
                [Span("", t[4], tuple(t[:4]), 0) for t in kp.get_text("blocks")])
            if not r:
                sys.exit("error: no scale; set scale.ratio in layer_map.json")
            fr, how = SheetFrame.from_ratio(float(r)), f"1:{float(r):g} (key page {lmap['key_page']})"
        lmap["_m_per_pt"] = fr.m_per_pt
        res = styled.build_styles(doc, lmap, with_modules=args.modules)
        W, H = kp.rect.width, kp.rect.height
        page_no = int(lmap["key_page"])
    elif lmap.get("mode") == "labels":
        # multi-sheet package: every sheet moved into the key sheet's frame
        import pymupdf
        from pvgeo import labelled
        from pvgeo.vector import SheetFrame
        if not reg_path.exists():
            sys.exit("error: mode 'labels' needs register.json; run register_sheets.py first")
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        doc = pymupdf.open(source(args.work)["pdf"])
        res = labelled.build_multi(doc, reg, lmap, with_modules=args.modules)
        fr = SheetFrame(reg["key"]["m_per_pt"])
        how = f"key page {reg['key_page']} viewport ({len(reg['sheets'])} sheets registered onto it)"
        W, H = reg["key"]["page_size_pt"]
        page_no = reg["key_page"]
    else:
        objs, spans, info = load_page(args.work)
        fr, how = frame(lmap, spans, info)
        W, H = info["width_pt"], info["height_pt"]
        res = hierarchy.build(objs, spans, lmap, (W, H), with_modules=args.modules)
        page_no = source(args.work)["page"]
    out = args.work / "layout"
    out.mkdir(exist_ok=True)

    meta = {"m_per_pt": fr.m_per_pt, "scale_source": how, "page": page_no, "page_size_pt": [W, H]}
    (out / "sheet.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    for lay, feats in res.features.items():
        rows = []
        for f in feats:
            props = dict(f.props)
            c = f.geom.centroid if f.geom.geom_type != "Point" else f.geom
            props.setdefault("x_pt", round(c.x, 2))
            props.setdefault("y_pt", round(c.y, 2))
            rows.append((fr.geom_to_m(f.geom), props))
        write_geojson(out / f"{lay}.geojson", rows, crs_name="sheet-metres")

    with (out / "hierarchy.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in res.rows:
            w.writerow(r)
    (out / "hierarchy.json").write_text(json.dumps(tree(res.rows), indent=1), encoding="utf-8")

    sev = Counter(i.severity for i in res.issues)
    qa = ["# QA report", "",
          f"{sev.get('error', 0)} errors, {sev.get('warning', 0)} warnings, {sev.get('note', 0)} notes. "
          "Check each warning on the drawing (preview.py or crop.py with the normalized bbox shown).", ""]
    for s in ("error", "warning", "note"):
        items = [i for i in res.issues if i.severity == s]
        if not items:
            continue
        qa += [f"## {s.title()}s", ""]
        by_code: dict = {}
        for i in items:
            by_code.setdefault(i.code, []).append(i)
        for code, its in by_code.items():
            qa.append(f"### `{code}` ({len(its)})")
            for i in its[:40]:
                where = ""
                if i.bbox_pt:
                    b = i.bbox_pt
                    where = f" — bbox {b[0]/W:.3f} {b[1]/H:.3f} {b[2]/W:.3f} {b[3]/H:.3f}"
                qa.append(f"- {i.message}{where}")
            if len(its) > 40:
                qa.append(f"- ... and {len(its) - 40} more")
            qa.append("")
    (out / "qa_report.md").write_text("\n".join(qa), encoding="utf-8")
    sug = out / "suggested_reassign.json"
    if res.suggested_reassign:
        sug.write_text(json.dumps(res.suggested_reassign, indent=2), encoding="utf-8")
    elif sug.exists():
        sug.unlink()

    s = res.stats
    summ = ["# Layout summary", "",
            f"- scale: {how}, {fr.m_per_pt:.5f} m per pt",
            *([f"- module outline: {s['module_size_pt'][0] * fr.m_per_pt:.2f} x "
               f"{s['module_size_pt'][1] * fr.m_per_pt:.2f} m as drawn"] if "module_size_pt" in s else []),
            f"- stations {s.get('stations', 0)}, inverters {s.get('inverters', 0)}, "
            f"combiners {s.get('combiners', 0)}, strings {s.get('strings', 0)} "
            f"({s.get('modules_per_string', '?')} modules each), tables {s.get('tables', 0)}, "
            f"modules {s.get('modules', 0)}",
            *([f"- sheets: {s['pages']}"] if "pages" in s else []),
            f"- layers by role: {s.get('layers_by_role')}", "",
            "| station | inverters | combiners | strings | modules | location |", "|---|---|---|---|---|---|"]
    for f in res.features["stations"]:
        p = f.props
        summ.append(f"| {p['id']} | {p['n_inverters']} | {p['n_combiners']} | {p['n_strings']} | "
                    f"{p['n_modules']} | {p['location_source']} |")
    (out / "summary.md").write_text("\n".join(summ) + "\n", encoding="utf-8")

    print("\n".join(summ[2:5]))
    print(f"QA: {sev.get('error', 0)} errors, {sev.get('warning', 0)} warnings, {sev.get('note', 0)} notes "
          f"-> {out / 'qa_report.md'}")
    return 1 if sev.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
