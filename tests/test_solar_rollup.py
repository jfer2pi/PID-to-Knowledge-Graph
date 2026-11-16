"""Roll-up of parent levels from string polygons: only what is missing is built."""
import sys
from pathlib import Path

from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "solar-layout-to-geo" / "scripts"))
from pvgeo.rollup import rollup  # noqa: E402


def plant(stations=2, inv_per_station=2, cb_per_inv=3, rows_per_cb=2, tables=5):
    """rows of 20 x 3.5 m tables, 7.5 m pitch; each combiner owns consecutive rows"""
    strings, row = [], 0
    for s in range(1, stations + 1):
        for i in range(1, inv_per_station + 1):
            for c in range(1, cb_per_inv + 1):
                for _ in range(rows_per_cb):
                    y = -row * 7.5
                    for t in range(tables):
                        x = t * 20.3
                        p = dict(station=f"ST{s}", inverter=f"INV{s}{i}", combiner=f"CB{c:02d}", n_modules=20)
                        strings.append((box(x, y, x + 20, y + 1.75), dict(p, id=f"S{row}-{t}a")))
                        strings.append((box(x, y + 1.75, x + 20, y + 3.5), dict(p, id=f"S{row}-{t}b")))
                    row += 1
    return strings


def test_builds_missing_levels_without_overlap():
    new, notes = rollup({"strings": plant()})
    cb = new["combiner_areas"]
    assert len(cb) == 2 * 2 * 3
    assert all(p["parts"] == 1 for _, p in cb)                         # two rows bridged into one area
    for a, (ga, _) in enumerate(cb):
        for gb, _ in cb[a + 1:]:
            assert ga.intersection(gb).area < 1e-6
    assert len(new["inverter_areas"]) == 4 and len(new["station_areas"]) == 2
    assert len(new["combiners"]) == 12 and len(new["stations"]) == 2   # record points, none existed
    assert all(p["derived"] for _, p in new["combiners"])


def test_existing_parents_are_left_alone():
    s = plant()
    have_cb = [(box(0, 0, 1, 1), dict(id="X", station="ST1", inverter="INV11", combiner="CB01", level="combiner"))]
    have_inv = [(box(0, 0, 1, 1), dict(id=f"INV{a}{b}", station=f"ST{a}", inverter=f"INV{a}{b}")) for a in (1, 2) for b in (1, 2)]
    new, notes = rollup({"strings": s, "combiners": have_cb, "inverters": have_inv})
    assert "inverter_areas" not in new                                  # all four exist as areas
    assert len(new["combiner_areas"]) == 11                             # only the missing ones
    assert len(new["combiners_derived"]) == 11


def test_one_inverter_per_station_gets_no_duplicate_station_area():
    new, notes = rollup({"strings": plant(inv_per_station=1)})
    assert "inverter_areas" in new and "station_areas" not in new
    assert any("identical" in n for n in notes)


def test_point_parents_get_areas():
    s = plant(stations=1, inv_per_station=1)
    pts = [(Point(0, 0), dict(id=f"CB{c:02d}", station="ST1", inverter="INV11", combiner=f"CB{c:02d}")) for c in (1, 2, 3)]
    new, _ = rollup({"strings": s, "combiners": pts})
    assert len(new["combiner_areas"]) == 3 and "combiners_derived" not in new
