"""End-to-end test of the solar-layout-to-geo skill on a synthetic layered PDF.

The PDF imitates a CAD plot: modules on per-combiner layers, tables on a
table layer, station tags drawn as filled glyph shapes on per-inverter layers,
a fence, and a 1:1000 scale in the title text. One combiner's modules are
deliberately drawn in two places on the wrong layer, to exercise the
layer mix-up check and the reassign rule.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("shapely")
pytest.importorskip("pyproj")
pytest.importorskip("shapefile")

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "solar-layout-to-geo" / "scripts"
M_PER_PT = 25.4 / 72 * 1000 / 1000          # 1:1000
MOD_W, MOD_H = 1.65 / M_PER_PT, 1.0 / M_PER_PT
COLS, ROWS = 4, 4                            # 4x4 tables, strings of 4 modules


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    return r


def draw_table(page, x, y, mod_oc, tab_oc):
    page.draw_rect(pymupdf.Rect(x, y, x + COLS * MOD_W, y + ROWS * MOD_H), color=(0.3, 0.3, 0.3), oc=tab_oc)
    for r in range(ROWS):
        for c in range(COLS):
            x0, y0 = x + c * MOD_W, y + r * MOD_H
            page.draw_rect(pymupdf.Rect(x0 + 0.05, y0 + 0.05, x0 + MOD_W - 0.05, y0 + MOD_H - 0.05),
                           color=(0, 0, 1), oc=mod_oc)


def draw_word(page, x, y, n, oc):
    for i in range(n):
        page.draw_rect(pymupdf.Rect(x + i * 1.0, y, x + i * 1.0 + 0.8, y + 1.2),
                       color=None, fill=(0.3, 0.3, 0.3), oc=oc)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("solar")
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    tab = doc.add_ocg("SADEF_WHITE TABLE")
    fence = doc.add_ocg("PVS_Fence")
    layers = {}
    for inv in (1, 2):
        layers[("lab", inv)] = doc.add_ocg(f"PVE_Inverter-1-{inv}")
        for cb in (1, 2):
            layers[(inv, cb)] = doc.add_ocg(f"PVE_INV1-{inv}-Combiner-Box-{cb}")
    tw = COLS * MOD_W + 3
    for inv in (1, 2):
        x = 100 if inv == 1 else 480
        for cb in (1, 2):
            y = 100 + (cb - 1) * (ROWS * MOD_H + 4)
            # INV1-2 CB2 is drawn on INV1-1 CB2's layer (a CAD mistake)
            layer = layers[(1, 2)] if (inv, cb) == (2, 2) else layers[(inv, cb)]
            for t in range(2):
                draw_table(page, x + t * tw, y, layer, tab)
    # station tags INV01-01 over INV01-02, and one combiner tag elsewhere per inverter
    draw_word(page, 300, 150, 8, layers[("lab", 1)])
    draw_word(page, 300, 156.5, 8, layers[("lab", 2)])
    draw_word(page, 60, 100, 12, layers[("lab", 1)])
    draw_word(page, 70, 140, 12, layers[("lab", 2)])
    page.draw_polyline([(80, 80), (800, 80), (800, 300), (80, 300), (80, 80)], color=(0, 0.6, 0), oc=fence)
    page.insert_text((600, 560), "Scale: 1:1000", fontsize=8)
    pdf = tmp / "site.pdf"
    doc.save(pdf)
    work = tmp / "work"
    run(SCRIPTS / "list_layers.py", pdf, "--work", work)
    return pdf, work


def test_layers_and_scale(site):
    _, work = site
    info = json.loads((work / "layers.json").read_text())
    roles = {r["layer"]: r["role"] for r in info["layers"]}
    assert roles["PVE_INV1-2-Combiner-Box-1"] == "module"
    assert roles["SADEF_WHITE TABLE"] == "table"
    assert roles["PVE_Inverter-1-2"] == "inverter_label"
    assert "1:1000" in (work / "layers.md").read_text()


def test_hierarchy_and_mixup(site):
    _, work = site
    run(SCRIPTS / "build_layout.py", work, "--modules")
    rows = list(csv.DictReader((work / "layout" / "hierarchy.csv").open()))
    levels = {lv: [r for r in rows if r["level"] == lv] for lv in ("station", "inverter", "combiner", "string")}
    assert len(levels["station"]) == 1 and levels["station"][0]["location_source"] == "station_tag"
    assert len(levels["inverter"]) == 2
    assert len(levels["combiner"]) == 3                   # INV01-02-CB02 swallowed by the mistake
    assert all(int(r["n_modules"]) % 4 == 0 for r in levels["combiner"])
    qa = (work / "layout" / "qa_report.md").read_text()
    assert "fewer_combiners" in qa and "combiner_in_separate_parts" in qa
    sug = json.loads((work / "layout" / "suggested_reassign.json").read_text())
    assert sug and sug[0]["to"] == {"station": 1, "inv": 2, "cb": 2}

    m = json.loads((work / "layer_map.json").read_text())
    m["reassign"] = sug
    (work / "layer_map.json").write_text(json.dumps(m))
    run(SCRIPTS / "build_layout.py", work, "--modules")
    rows = list(csv.DictReader((work / "layout" / "hierarchy.csv").open()))
    cbs = {r["id"]: r for r in rows if r["level"] == "combiner"}
    assert set(cbs) == {"INV01-01-CB01", "INV01-01-CB02", "INV01-02-CB01", "INV01-02-CB02"}
    assert all(r["n_modules"] == "32" and r["n_strings"] == "8" for r in cbs.values())
    strings = [r for r in rows if r["level"] == "string"]
    assert len(strings) == 32 and all(r["n_modules"] == "4" for r in strings)
    assert strings[0]["path"] == "ST01 > INV01-01 > INV01-01-CB01 > INV01-01-CB01-S01"
    mods = json.loads((work / "layout" / "modules.geojson").read_text())["features"]
    assert len(mods) == 4 * 2 * 16


def test_georef_and_export(site):
    _, work = site
    # control points from a known transform: shift + 2 deg rotation, true scale
    th = math.radians(2.0)
    gcps = work / "gcps.csv"
    with gcps.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "sheet_x_pt", "sheet_y_pt", "easting", "northing"])
        for i, (x, y) in enumerate([(80, 80), (800, 80), (800, 300), (80, 300)]):
            X, Y = x * M_PER_PT, -y * M_PER_PT
            w.writerow([f"g{i}", x, y, 500000 + X * math.cos(th) - Y * math.sin(th),
                        200000 + X * math.sin(th) + Y * math.cos(th)])
    run(SCRIPTS / "georef.py", work, "--gcps", gcps, "--crs", "EPSG:27700")
    t = json.loads((work / "georef" / "transform.json").read_text())
    assert t["method"] == "similarity"
    assert abs(t["scale"] - 1) < 1e-6 and abs(t["rotation_deg"] - 2.0) < 1e-6
    assert t["rmse_m"] < 1e-6

    run(SCRIPTS / "export_geo.py", work, "--name", "Test Site")
    out = work / "out"
    for f in ("stations.geojson", "combiners.geojson", "strings.geojson", "Test Site.kmz",
              "hierarchy.csv", "hierarchy.json", "shp/combiners.shp", "shp/combiners.prj"):
        assert (out / f).exists(), f
    rows = list(csv.DictReader((out / "hierarchy.csv").open()))
    assert all(r["lon"] and r["lat"] for r in rows)
    tree = json.loads((out / "hierarchy.json").read_text())
    assert tree[0]["id"] == "ST01" and len(tree[0]["children"]) == 2
