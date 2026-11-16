"""Shared helpers for the solar-layout-to-geo scripts."""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pvgeo import layermap  # noqa: E402
from pvgeo.vector import SheetFrame, read_page, scale_ratio_from_text  # noqa: E402


def source(work: Path) -> dict:
    p = work / "source.json"
    if not p.exists():
        sys.exit(f"error: {p} not found; run list_layers.py first")
    return json.loads(p.read_text(encoding="utf-8"))


def load_page(work: Path, page: int | None = None):
    """Vector objects, text spans and page info, cached after the first read."""
    src = source(work)
    page = page or src["page"]
    cache = work / "cache" / f"page_{page:02d}.pkl"
    if cache.exists() and cache.stat().st_mtime >= Path(src["pdf"]).stat().st_mtime:
        with cache.open("rb") as f:
            return pickle.load(f)
    print(f"reading vectors from {Path(src['pdf']).name} page {page} (cached afterwards)...", flush=True)
    data = read_page(src["pdf"], page)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    return data


def frame(lmap: dict, spans, info: dict | None = None) -> tuple[SheetFrame, str]:
    """Drawing scale, in order: layer_map m_per_pt, layer_map ratio, the PDF's
    model-space viewport measure, the title-block '1:N' text."""
    sc = lmap.get("scale", {})
    if sc.get("m_per_pt"):
        return SheetFrame(float(sc["m_per_pt"])), f"layer_map m_per_pt={sc['m_per_pt']}"
    if sc.get("ratio"):
        return SheetFrame.from_ratio(float(sc["ratio"])), f"layer_map ratio 1:{sc['ratio']:g}"
    vps = [v for v in (info or {}).get("viewports", []) if v.get("x_per_pt")
           and abs(v["x_per_pt"] - 0.35278) > 1e-3 and not v.get("geo")]
    if vps:
        # model-space viewport measures are usually in metres per point; a value
        # above 50 would mean millimetres per point
        v = vps[0]["x_per_pt"]
        m = v / 1000.0 if v > 50 else v
        return SheetFrame(m), f"PDF viewport measure {vps[0]['x_per_pt']} per pt"
    r = scale_ratio_from_text(spans)
    if r:
        return SheetFrame.from_ratio(r), f"title block 1:{r:g}"
    sys.exit("error: no drawing scale; set scale.ratio or scale.m_per_pt in layer_map.json")


def load_map(work: Path) -> dict:
    m = layermap.load(work)
    m["_work"] = str(work)
    return m
