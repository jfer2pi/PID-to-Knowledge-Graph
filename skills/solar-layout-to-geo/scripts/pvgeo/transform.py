"""Sheet metres -> projected CRS, fitted from ground control points.

Methods
- translation: scale 1 and rotation 0 (or as given); needs 1 point. Only for a
  provisional placement from a single site coordinate.
- similarity (Helmert, 4 parameters): uniform scale + rotation + shift; needs 2+
  points. The default: a CAD layout is a true-scale plan, so scale should come
  out close to 1 and rotation close to the CAD's grid-to-north angle.
- affine (6 parameters): allows shear and unequal scale; needs 3+ points. Only
  for scanned or distorted sheets.

Sheet metres are X east, Y north (see vector.SheetFrame), so a fitted scale far
from 1 means a wrong drawing scale or a bad control point.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field

import numpy as np


@dataclass
class Transform:
    crs: str
    method: str
    # E = a*X + b*Y + c ; N = d*X + e*Y + f
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float
    m_per_pt: float
    residuals: list[dict] = field(default_factory=list)
    rmse_m: float | None = None
    note: str = ""

    @property
    def scale(self) -> float:
        return math.sqrt(abs(self.a * self.e - self.b * self.d))

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.d, self.a))

    def apply(self, X, Y):
        X = np.asarray(X, dtype=float)
        Y = np.asarray(Y, dtype=float)
        return self.a * X + self.b * Y + self.c, self.d * X + self.e * Y + self.f

    def apply_pt(self, x, y):
        k = self.m_per_pt
        return self.apply(np.asarray(x) * k, -np.asarray(y) * k)

    def to_json(self) -> str:
        d = asdict(self)
        d["scale"] = self.scale
        d["rotation_deg"] = self.rotation_deg
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Transform":
        d = json.loads(text)
        d.pop("scale", None)
        d.pop("rotation_deg", None)
        return cls(**d)


def fit(src: np.ndarray, dst: np.ndarray, method: str, crs: str, m_per_pt: float,
        ids: list[str] | None = None, scale: float = 1.0, rotation_deg: float = 0.0) -> Transform:
    """src: sheet metres (n,2); dst: projected coordinates (n,2)."""
    n = len(src)
    if method == "translation":
        if n < 1:
            raise ValueError("translation needs at least 1 control point")
        th = math.radians(rotation_deg)
        a, b = scale * math.cos(th), -scale * math.sin(th)
        d, e = scale * math.sin(th), scale * math.cos(th)
        rot = np.array([[a, b], [d, e]])
        shift = (dst - src @ rot.T).mean(axis=0)
        t = Transform(crs, method, a, b, shift[0], d, e, shift[1], m_per_pt)
    elif method == "similarity":
        if n < 2:
            raise ValueError("similarity needs at least 2 control points")
        A = np.zeros((2 * n, 4))
        L = np.zeros(2 * n)
        A[0::2] = np.c_[src[:, 0], -src[:, 1], np.ones(n), np.zeros(n)]
        A[1::2] = np.c_[src[:, 1], src[:, 0], np.zeros(n), np.ones(n)]
        L[0::2], L[1::2] = dst[:, 0], dst[:, 1]
        p, q, tx, ty = np.linalg.lstsq(A, L, rcond=None)[0]
        t = Transform(crs, method, p, -q, tx, q, p, ty, m_per_pt)
    elif method == "affine":
        if n < 3:
            raise ValueError("affine needs at least 3 control points")
        A = np.c_[src, np.ones(n)]
        ex = np.linalg.lstsq(A, dst[:, 0], rcond=None)[0]
        ny = np.linalg.lstsq(A, dst[:, 1], rcond=None)[0]
        t = Transform(crs, method, ex[0], ex[1], ex[2], ny[0], ny[1], ny[2], m_per_pt)
    else:
        raise ValueError(f"unknown method {method}")
    E, N = t.apply(src[:, 0], src[:, 1])
    res = np.hypot(E - dst[:, 0], N - dst[:, 1])
    ids = ids or [str(i + 1) for i in range(n)]
    t.residuals = [{"id": i, "dE": float(e_ - d_[0]), "dN": float(n_ - d_[1]), "r": float(r)}
                   for i, e_, n_, d_, r in zip(ids, E, N, dst, res)]
    dof = {"translation": n, "similarity": 2 * n - 4, "affine": 2 * n - 6}[method]
    t.rmse_m = float(np.sqrt((res ** 2).sum() / dof)) if dof > 0 else None
    return t
