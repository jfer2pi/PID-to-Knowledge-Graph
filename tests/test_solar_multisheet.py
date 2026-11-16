"""Unit tests for the multi-sheet pieces of solar-layout-to-geo."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("shapely")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "solar-layout-to-geo" / "scripts"))

from pvgeo.labelled import _greedy, labels, sheet_to_key  # noqa: E402
from pvgeo.register import KeyCorrelator  # noqa: E402


def test_correlator_recovers_offset():
    rng = np.random.default_rng(0)
    key = np.zeros((2, 300, 400), np.float32)
    for _ in range(40):                                   # random "streams" and "roads"
        c = rng.integers(0, 2)
        y, x = rng.integers(0, 290), rng.integers(0, 380)
        key[c, y:y + rng.integers(2, 10), x:x + rng.integers(5, 20)] = 1
    tpl = key[:, 120:220, 150:280].copy()
    m = KeyCorrelator(key, tpl.shape[1:]).match(tpl)
    assert abs(m["offset_px"][0] - 150) < 0.5 and abs(m["offset_px"][1] - 120) < 0.5
    assert m["peak_ratio"] > 1.2


def test_labels_split_merged_runs(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    oc = doc.add_ocg("PVcase Device Numbering")
    page.insert_text((50, 100), "DCB 14-12DCB 14-6", fontsize=8, oc=oc)
    page.insert_text((50, 150), "DCB 3-1", fontsize=8)          # not on the layer
    p = tmp_path / "l.pdf"
    doc.save(p)
    pg = pymupdf.open(p)[0]
    out = labels(pg, re.compile("^PVcase Device Numbering$"), re.compile(r"DCB\s*(?P<station>\d+)-(?P<cb>\d+)"))
    assert [g for g, _ in out] == [{"station": 14, "cb": 12}, {"station": 14, "cb": 6}]
    assert out[0][1][2] <= out[1][1][0] + 1e-6                 # first label ends before the second


def test_greedy_is_one_to_one():
    from shapely.geometry import LineString, Point
    lines = [LineString([(x, 0), (x, 10)]) for x in (0, 1, 2)]
    pts = [Point(0.1, 5), Point(0.2, 5), Point(2.1, 5)]
    m = _greedy(pts, lines, 0.6)
    assert m[0] == 0 and m[2] == 2 and 1 not in m              # second label too far from line 1


def test_sheet_to_key():
    reg = {"key": {"m_per_pt": 2.0, "clip": [10, 20, 0, 0]},
           "sheets": {"5": {"m_per_pt": 0.5, "clip": [100, 200, 0, 0], "offset_m": [40, 60]}}}
    a, b, d, e, xo, yo = sheet_to_key(reg, 5)
    x, y = a * 100 + xo, e * 200 + yo                           # sheet clip corner -> key
    assert (x, y) == pytest.approx((10 + 40 / 2, 20 + 60 / 2))
    assert a == pytest.approx(0.25)
