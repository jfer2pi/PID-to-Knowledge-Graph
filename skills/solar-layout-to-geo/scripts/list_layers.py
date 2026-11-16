#!/usr/bin/env python3
"""Start a work directory and list the CAD layers in a layout PDF.

Reads every vector path and text span on the page together with its PDF layer
(optional-content group), and writes:

    <work>/source.json      the PDF and page this work directory is about
    <work>/layers.json      per-layer counts, geometry hints and sample text
    <work>/layers.md        the same as a table, with the role each layer gets
                            under the current layer_map.json
    <work>/layer_map.json   a starting map (only if none exists yet)

Read layers.md, then edit layer_map.json so that module, table and
inverter-label layers (and site features) are matched with the right named
groups. Re-run this script to see the new roles.

Usage:
    python list_layers.py site_layout.pdf --work work/my-site [--page 1]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import frame, load_map, load_page  # noqa: E402
from pvgeo import layermap  # noqa: E402
from pvgeo.vector import layer_summary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, nargs="?", help="layout PDF (omit to re-list an existing work dir)")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--page", type=int, default=1)
    args = ap.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    if args.pdf:
        if not args.pdf.exists():
            print(f"error: {args.pdf} not found", file=sys.stderr)
            return 2
        (args.work / "source.json").write_text(json.dumps(
            {"pdf": str(args.pdf.resolve()), "page": args.page}, indent=2), encoding="utf-8")
    if not (args.work / "layer_map.json").exists():
        layermap.write_default(args.work)
        print(f"wrote starting map {args.work / 'layer_map.json'}")

    objs, spans, info = load_page(args.work)
    lmap = load_map(args.work)
    rows = layer_summary(objs, spans)
    for r in rows:
        role, groups = layermap.classify(r["layer"], lmap["roles"])
        r["role"], r["groups"] = role, groups
    (args.work / "layers.json").write_text(json.dumps({"page_info": info, "layers": rows}, indent=2),
                                           encoding="utf-8")

    n_pdf_layers = len(info["layers"])
    fr, how = frame(lmap, spans, info)
    lines = [f"# Layers: {Path(json.loads((args.work / 'source.json').read_text())['pdf']).name}", "",
             f"- page size: {info['width_pt']:.0f} x {info['height_pt']:.0f} pt, rotation {info['rotation']}",
             f"- PDF layers (optional content groups): {n_pdf_layers}",
             f"- vector objects: {len(objs)}, text spans: {len(spans)}",
             f"- scale: {how} -> {fr.m_per_pt:.5f} m per pt", ""]
    if n_pdf_layers == 0:
        lines += ["**No PDF layers.** The CAD layers were flattened on export. Use the visual route "
                  "in references/procedure.md (colour/size grouping and Claude-read labels).", ""]
    by_role: dict = {}
    for r in rows:
        by_role.setdefault(r["role"] or "(unmapped)", []).append(r)
    for role in sorted(by_role, key=lambda k: (k == "(unmapped)", k)):
        rs = by_role[role]
        lines += [f"## {role} ({len(rs)} layers, {sum(r['objects'] for r in rs)} objects)", "",
                  "| layer | objects | text | items | top sizes (w x h pt, n) | groups |", "|---|---|---|---|---|---|"]
        show = rs if len(rs) <= 25 else rs[:12] + [None] + rs[-5:]
        for r in show:
            if r is None:
                lines.append(f"| ... {len(rs) - 17} more | | | | | |")
                continue
            sizes = "; ".join(f"{w}x{h} ({n})" for w, h, n in r["top_sizes_pt"])
            items = ", ".join(f"{k}:{v}" for k, v in r["items"].items())
            text = r["text_spans"] if not r["sample_text"] else f"{r['text_spans']}: {' / '.join(r['sample_text'][:3])}"
            lines.append(f"| `{r['layer'] or '(none)'}` | {r['objects']} | {text} | {items} | {sizes} | "
                         f"{r['groups'] or ''} |")
        lines.append("")
    (args.work / "layers.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(rows)} layers, {len(objs)} objects -> {args.work / 'layers.md'}")
    print(f"scale: {how} ({fr.m_per_pt:.5f} m/pt)")
    for role in sorted(by_role, key=lambda k: (k == "(unmapped)", k)):
        rs = by_role[role]
        print(f"  {role:<16} {len(rs):>4} layers {sum(r['objects'] for r in rs):>8} objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
