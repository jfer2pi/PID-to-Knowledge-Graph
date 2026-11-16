"""Area polygons per circuit, combiner and inverter: union of their tables, closed across the inter-row gap."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import pickle, collections, json
from pathlib import Path
from shapely.ops import unary_union
from shapely.geometry import MultiPolygon, Polygon
from shapely.strtree import STRtree

W = Path(WORK)
R = 2.1            # closing radius: bridges the 4.03 m gap between rows and 0.28 m between tables, nothing wider
MIT = dict(join_style=2, mitre_limit=10)


def close(geoms):
    return unary_union(geoms).buffer(R, **MIT).buffer(-R, **MIT)


def build(A):
    T = A["feats"]["tables"]
    tables = [g for g, _ in T]
    tree = STRtree(tables)
    out = {}
    stats = {}
    for level, key in (("circuit", lambda p: f"{p['inverter']}-{p['combiner']}-{p['circuit']}"),
                       ("combiner", lambda p: f"{p['inverter']}-{p['combiner']}"),
                       ("inverter", lambda p: p["inverter"])):
        grp = collections.defaultdict(list)
        meta = {}
        for k, (g, p) in enumerate(T):
            grp[key(p)].append(k); meta[key(p)] = p
        feats = []
        for gid, ks in grp.items():
            poly = close([tables[k] for k in ks])
            # never cover another group's table
            own = set(ks)
            others = [tables[j] for j in tree.query(poly) if j not in own and tables[j].intersection(poly).area > 1e-6]
            if others:
                poly = poly.difference(unary_union(others).buffer(0.05, **MIT))
            poly = poly.buffer(0)
            parts = len(getattr(poly, "geoms", [poly]))
            p = meta[gid]; n = len(ks)
            props = dict(id=gid, level=f"{level}_area", inverter=p["inverter"], station=p["station"], n_tables=n,
                         n_strings=2 * n, n_modules=40 * n, area_m2=round(poly.area, 1), parts=parts,
                         method=f"union of its tables closed at {R} m")
            if level in ("circuit", "combiner"):
                props["combiner"] = p["combiner"]
            if level == "circuit":
                props["circuit"] = p["circuit"]
            feats.append((poly, props))
        # overlap check
        g = [f[0] for f in feats]; t2 = STRtree(g); ov = 0.0
        for a, ga in enumerate(g):
            for b in t2.query(ga):
                if b > a:
                    ov += ga.intersection(g[b]).area
        stats[level] = dict(n=len(feats), multipart=sum(1 for f in feats if f[1]["parts"] > 1),
                            max_parts=max(f[1]["parts"] for f in feats), overlap_m2=round(ov, 1),
                            mean_area_m2=round(sum(f[0].area for f in feats) / len(feats)))
        out[f"{level}_areas"] = feats
    return out, stats


if __name__ == "__main__":
    A = pickle.load(open(W / "cache/assembled.pkl", "rb"))
    new, stats = build(A)
    A["feats"].update(new)
    pickle.dump(A, open(W / "cache/assembled.pkl", "wb"))
    print(json.dumps(stats, indent=1))
    mp = [p for _, p in new["combiner_areas"] if p["parts"] > 1]
    print("multipart combiners:", [(p["id"], p["parts"]) for p in mp][:20])
