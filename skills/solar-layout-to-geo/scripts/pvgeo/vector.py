"""Read vector objects from a CAD-exported PDF, keeping the CAD layer of each.

AutoCAD and most CAD plotters export layers as PDF optional-content groups.
PyMuPDF reports the layer of every drawing (get_drawings) and text span
(get_texttrace), which is what makes a PDF behave like a DXF here.

Sheet coordinates are PDF points with the origin at the top-left (y down),
as PyMuPDF returns them. `SheetFrame` converts them to "sheet metres":
X east, Y north, scaled by the drawing scale. A georeferencing transform
then maps sheet metres to a real CRS.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon, box

PT_MM = 25.4 / 72.0  # one PDF point in millimetres


@dataclass
class Obj:
    """One vector drawing (a path) on a layer."""

    layer: str
    kind: str                      # "f" fill, "s" stroke, "fs" both
    rect: tuple[float, float, float, float]
    items: list = field(repr=False)
    fill: tuple | None = None
    color: tuple | None = None
    width: float = 0.0
    closed: bool = False

    @property
    def w(self) -> float:
        return self.rect[2] - self.rect[0]

    @property
    def h(self) -> float:
        return self.rect[3] - self.rect[1]

    def polygons(self) -> list[Polygon]:
        """Quads and rectangles in this drawing as polygons (sheet points)."""
        out = []
        for it in self.items:
            if it[0] == "qu":
                q = it[1]
                pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
                p = Polygon(pts)
                if p.area > 0:
                    out.append(p)
            elif it[0] == "re":
                r = it[1]
                if r.width > 0 and r.height > 0:
                    out.append(box(r.x0, r.y0, r.x1, r.y1))
        if not out and (self.closed or "f" in self.kind):
            pts = self.vertices()
            if len(pts) >= 3:
                p = Polygon(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 0:
                    out.append(p)
        return out

    def vertices(self) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        for it in self.items:
            if it[0] == "l":
                for p in it[1:3]:
                    if not pts or (p.x, p.y) != pts[-1]:
                        pts.append((p.x, p.y))
            elif it[0] == "c":
                for p in (it[1], it[4]):
                    if not pts or (p.x, p.y) != pts[-1]:
                        pts.append((p.x, p.y))
        return pts

    def lines(self) -> list[LineString]:
        """Line work as polylines (sheet points); quads/rects as their rings."""
        out = []
        cur: list[tuple[float, float]] = []

        def flush():
            if len(cur) >= 2:
                out.append(LineString(cur))

        for it in self.items:
            if it[0] in ("l", "c"):
                a, b = (it[1], it[2]) if it[0] == "l" else (it[1], it[4])
                if cur and (a.x, a.y) == cur[-1]:
                    cur.append((b.x, b.y))
                else:
                    flush()
                    cur = [(a.x, a.y), (b.x, b.y)]
            else:
                flush()
                cur = []
        flush()
        for p in self.polygons():
            out.append(LineString(p.exterior.coords))
        return out


@dataclass
class Span:
    """A text span from the PDF text layer, with its layer."""

    layer: str
    text: str
    rect: tuple[float, float, float, float]
    size: float


def read_page(pdf_path: str, page_no: int = 1) -> tuple[list[Obj], list[Span], dict]:
    """Return (vector objects, text spans, page info) for one page (1-based)."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    objs = []
    for d in page.get_drawings():
        r = d["rect"]
        objs.append(Obj(layer=d.get("layer") or "", kind=d.get("type") or "",
                        rect=(r.x0, r.y0, r.x1, r.y1), items=d["items"],
                        fill=d.get("fill"), color=d.get("color"),
                        width=d.get("width") or 0.0, closed=bool(d.get("closePath"))))
    spans = []
    for t in page.get_texttrace():
        text = "".join(chr(c[0]) for c in t["chars"])
        if text.strip():
            b = t["bbox"]
            spans.append(Span(layer=t.get("layer") or "", text=text, rect=tuple(b), size=t["size"]))
    info = {"width_pt": page.rect.width, "height_pt": page.rect.height,
            "layers": [v["name"] for v in doc.get_ocgs().values()],
            "rotation": page.rotation, "viewports": viewports(doc, page)}
    return objs, spans, info


def viewports(doc, page) -> list[dict]:
    """Measured viewports (/VP with /Measure) that CAD plotters write.

    A viewport's X conversion factor is drawing units per PDF point. The paper
    viewport carries 0.35278 (mm per pt); the model-space viewport carries the
    drawing scale, e.g. 0.88189 m per pt at 1:2500. Geospatial viewports
    (/Measure /Subtype /GEO) are reported too, but not used yet.
    """
    import re as _re

    obj = doc.xref_object(page.xref)
    if "/VP" not in obj:
        return []
    out = []
    for chunk in obj.split("/Type /Viewport")[:-1]:
        c = _re.findall(r"/X \[\s*<<\s*/C ([\d.]+)", chunk)
        geo = "/GEO" in chunk
        bb = _re.findall(r"/BBox \[([^\]]+)\]", obj[obj.find(chunk) + len(chunk):][:200])
        out.append({"x_per_pt": float(c[-1]) if c else None, "geo": geo,
                    "bbox": [float(v) for v in bb[0].split()] if bb else None})
    return out


def layer_summary(objs: list[Obj], spans: list[Span]) -> list[dict]:
    """Per-layer counts and geometry hints, to decide each layer's role."""
    by: dict[str, list[Obj]] = defaultdict(list)
    for o in objs:
        by[o.layer].append(o)
    tx: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        tx[s.layer].append(s)
    rows = []
    for layer in sorted(set(by) | set(tx)):
        os_ = by.get(layer, [])
        items = Counter(it[0] for o in os_ for it in o.items)
        sizes = Counter((round(o.w, 1), round(o.h, 1)) for o in os_)
        x0 = min((o.rect[0] for o in os_), default=None)
        rows.append({
            "layer": layer,
            "objects": len(os_),
            "text_spans": len(tx.get(layer, [])),
            "sample_text": [s.text for s in tx.get(layer, [])[:5]],
            "items": dict(items),
            "kinds": dict(Counter(o.kind for o in os_)),
            "top_sizes_pt": [[w, h, n] for (w, h), n in sizes.most_common(3)],
            "bbox_pt": None if x0 is None else [
                round(x0, 1), round(min(o.rect[1] for o in os_), 1),
                round(max(o.rect[2] for o in os_), 1), round(max(o.rect[3] for o in os_), 1)],
        })
    return rows


@dataclass
class SheetFrame:
    """Sheet points (y down) <-> sheet metres (Y north-up), via the drawing scale."""

    m_per_pt: float

    @classmethod
    def from_ratio(cls, ratio: float) -> "SheetFrame":
        return cls(m_per_pt=PT_MM * ratio / 1000.0)

    def to_m(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.m_per_pt, -y * self.m_per_pt)

    def to_pt(self, X: float, Y: float) -> tuple[float, float]:
        return (X / self.m_per_pt, -Y / self.m_per_pt)

    def geom_to_m(self, g):
        from shapely.affinity import affine_transform
        k = self.m_per_pt
        return affine_transform(g, [k, 0, 0, -k, 0, 0])


def scale_ratio_from_text(spans: list[Span]) -> float | None:
    """Find a '1:2500' style scale in the title block text."""
    for s in spans:
        m = re.search(r"\b1\s*[:/]\s*(\d{1,3}(?:[.,\s]\d{3})+|\d{2,6})\b", s.text)
        if m:
            return float(re.sub(r"[.,\s]", "", m.group(1)))
    return None
