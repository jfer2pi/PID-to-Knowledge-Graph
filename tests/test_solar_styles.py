"""Route C (flattened sheets): style matching, page registration, capacity assignment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("scipy")
pytest.importorskip("shapely")

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "solar-layout-to-geo" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pvgeo.styled import _translation_vote, match_style  # noqa: E402


def test_match_style_rotation_and_colour():
    r = pymupdf.Rect(0, 0, 25.2, 4.3)
    x = {"type": "s", "color": (0.0, 0.0, 0.0), "rect": r, "items": [("qu", None)]}
    s = {"type": "s", "color": [0, 0, 0], "size_pt": [4.3, 25.2], "items": "qu"}
    assert match_style(x, s)
    assert not match_style(x, {**s, "rotatable": False})
    assert not match_style({**x, "color": (1.0, 0, 0)}, s)


def test_translation_vote():
    from shapely.geometry import Point
    a = [Point(10, 10), Point(50, 20), Point(80, 90)]
    b = [Point(p.x - 83, p.y + 10) for p in a] + [Point(500, 500)]
    t, n = _translation_vote(a, b)
    assert t == pytest.approx((83, -10)) and n == 3


def _site(tmp: Path) -> Path:
    """Layout page: two blocks of 4 trackers in coloured outlines, labels, station
    symbols. Grounding page: the same station symbols shifted, plus 2 boxes per
    block (capacity 2 each)."""
    doc = pymupdf.open()
    doc.new_page(width=600, height=400)
    doc.new_page(width=600, height=400)
    lay, gnd = doc[0], doc[1]
    blocks = {1: (100, (0, 0.5, 1)), 2: (300, (1, 0.5, 0))}
    for b, (x0, col) in blocks.items():
        lay.draw_polyline([(x0, 100), (x0 + 120, 100), (x0 + 120, 200), (x0, 200), (x0, 100)],
                          color=col, fill=None, width=2)
        for k in range(4):
            q = pymupdf.Rect(x0 + 10 + k * 25, 120, x0 + 14.3 + k * 25, 145.2)
            lay.draw_rect(q, color=(0, 0, 0), width=0.2)
        lay.insert_text((x0 + 55, 190), f"0{b}", fontsize=10)
        lay.draw_rect(pymupdf.Rect(x0 - 10, 205, x0 - 4.6, 217.9), color=(0, 0, 0), fill=(0, 0, 0))
        lay.insert_text((x0 - 12, 228), f"INV.0{b}", fontsize=6)
        gnd.draw_rect(pymupdf.Rect(x0 - 10 - 20, 205 + 5, x0 - 4.6 - 20, 217.9 + 5), color=(0, 0, 0), fill=(0, 0, 0))
        for k in (0, 2):
            bx = x0 + 10 + k * 25 + 12 - 20
            gnd.draw_rect(pymupdf.Rect(bx, 160 + 5, bx + 9, 164.75 + 5), color=(1, 0, 0), fill=(1, 0, 0))
    lay.insert_text((500, 380), "ESCALA 1:1.000", fontsize=8)
    p = tmp / "flat.pdf"
    doc.save(p)
    return p


def test_route_c_end_to_end(tmp_path):
    pdf = _site(tmp_path)
    work = tmp_path / "work"
    subprocess.run([sys.executable, SCRIPTS / "list_layers.py", pdf, "--work", work, "--page", "1"],
                   check=True, capture_output=True)
    lmap = {
        "mode": "styles", "key_page": 1, "register_by": "station_symbol",
        "styles": [
            {"role": "tracker", "page": 1, "type": "s", "color": [0, 0, 0], "size_pt": [4.3, 25.2], "tol": 0.2},
            {"role": "station_symbol", "page": [1, 2], "type": "fs", "fill": [0, 0, 0], "size_pt": [5.4, 12.9], "tol": 0.3},
            {"role": "combiner", "page": 2, "type": "fs", "fill": [1, 0, 0], "size_pt": [9, 4.75], "tol": 0.3,
             "capacity": 2, "name": "box"},
            {"role": "block_outline", "page": 1, "type": "s", "min_size_pt": 100, "saturated_or_black": True},
            {"role": "block_label", "page": 1, "text": r"^\s*(?P<station>\d{2})(?P<suffix>\*?)\s*$"},
            {"role": "station_label", "page": 1, "text": r"INV\.(?P<station>\d{2})"},
        ],
        "expect_trackers": {"": 4}, "min_trackers_per_block": 2,
        "strings": {"per_tracker": 2, "modules_per_string": 26},
        "naming": {"station": "CT{station:02d}", "inverter": "INV{station:02d}",
                   "combiner": "INV{station:02d}-C{cb:02d}", "string": "INV{station:02d}-C{cb:02d}-S{string:02d}",
                   "table": "INV{station:02d}-T{table:03d}"},
    }
    (work / "layer_map.json").write_text(json.dumps(lmap))
    r = subprocess.run([sys.executable, SCRIPTS / "build_layout.py", work], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    qa = (work / "layout" / "qa_report.md").read_text()
    assert "shift +20.0, -5.0" in qa                       # grounding page registered onto the layout
    assert qa.count("matches_printed_total") == 1 and "4 trackers = 4 printed" in qa
    import csv
    rows = list(csv.DictReader((work / "layout" / "hierarchy.csv").open()))
    cbs = [x for x in rows if x["level"] == "combiner"]
    assert len(cbs) == 4 and all(x["n_strings"] == "4" for x in cbs)
    sts = [x for x in rows if x["level"] == "station"]
    assert {x["location_source"] for x in sts} == {"station_symbol"}
    assert sum(int(x["n_modules"]) for x in rows if x["level"] == "string") == 8 * 2 * 26
