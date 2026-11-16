"""Layer map: which CAD layer plays which role, and how devices are named.

The map is a JSON file in the work directory (`layer_map.json`). Each role
rule is a regex on the layer name; named groups (station, inv, cb) carry the
device numbers that the hierarchy is built from. Every site's CAD standard is
different, so Claude writes or edits this file after reading the layer list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Roles that build the PV hierarchy.
HIERARCHY_ROLES = {
    "module": "PV module outlines (one quad per module). Groups station/inv/cb if the layer encodes the combiner.",
    "table": "Mounting table / tracker outlines (one quad per table).",
    "inverter_label": "Inverter tag text drawn on its own layer. Groups station/inv.",
    "station": "Inverter station / skid symbols, if they have their own layer.",
}
# Site features exported as-is. geometry: line | polygon | point.
FEATURE_ROLES = {
    "site_boundary": "line", "fence": "line", "access_road": "line", "trench": "line",
    "mv_cable": "line", "lv_cable": "line", "stream": "polygon", "cctv": "point", "weather_station": "point",
    "comms": "point", "substation": "polygon", "building": "polygon", "other": "line",
}

DEFAULT_MAP = {
    "page": 1,
    "scale": {"ratio": None, "m_per_pt": None,
              "_note": "m_per_pt wins; else ratio (1:N); else the title-block scale"},
    "roles": [
        {"role": "module", "pattern": r"^PVE_INV(?P<station>\d+)-(?P<inv>\d+)-Combiner-Box-(?P<cb>\d+)$"},
        {"role": "table", "pattern": r"^SADEF_(?!.*PILE).*TABLE"},
        {"role": "inverter_label", "pattern": r"^PVE_Inverter-(?P<station>\d+)(-(?P<inv>\d+))?$"},
        {"role": "site_boundary", "pattern": r"Redline-Boundary"},
        {"role": "fence", "pattern": r"(?i)fence"},
        {"role": "access_road", "pattern": r"(?i)access-roads?$"},
        {"role": "trench", "pattern": r"(?i)^PVS_Trench"},
        {"role": "mv_cable", "pattern": r"(?i)cables? MV"},
        {"role": "cctv", "pattern": r"(?i)CCTV-Camera"},
        {"role": "weather_station", "pattern": r"(?i)WeatherStation"},
        {"role": "comms", "pattern": r"(?i)COMMS_Box"},
    ],
    "strings": {
        "modules_per_string": "auto",
        "_note": "auto = modal number of modules per module-row across full tables",
        "order": "rows_top_down",
    },
    "stations": {"method": "stacked_tags", "override_file": "stations.json"},
    "naming": {
        "station": "ST{station:02d}",
        "inverter": "INV{station:02d}-{inv:02d}",
        "combiner": "INV{station:02d}-{inv:02d}-CB{cb:02d}",
        "string": "INV{station:02d}-{inv:02d}-CB{cb:02d}-S{string:02d}",
        "table": "T{table:05d}",
    },
}


def load(work: Path) -> dict:
    p = work / "layer_map.json"
    if not p.exists():
        return json.loads(json.dumps(DEFAULT_MAP))
    m = json.loads(p.read_text(encoding="utf-8"))
    for k, v in DEFAULT_MAP.items():
        if k not in m:
            m[k] = v
        elif isinstance(v, dict):
            m[k] = {**v, **m[k]}
    return m


def write_default(work: Path) -> Path:
    p = work / "layer_map.json"
    p.write_text(json.dumps(DEFAULT_MAP, indent=2), encoding="utf-8")
    return p


def classify(layer: str, rules: list[dict]) -> tuple[str | None, dict]:
    """First matching rule wins. Returns (role, numeric groups)."""
    for r in rules:
        m = re.search(r["pattern"], layer)
        if m:
            groups = {k: int(v) for k, v in m.groupdict().items() if v is not None and v.isdigit()}
            groups.update({k: v for k, v in m.groupdict().items() if v is not None and not v.isdigit()})
            return r["role"], groups
    return None, {}


def name(template: str, **kw) -> str:
    try:
        return template.format(**kw)
    except (KeyError, ValueError):
        return "-".join(str(v) for v in kw.values())
