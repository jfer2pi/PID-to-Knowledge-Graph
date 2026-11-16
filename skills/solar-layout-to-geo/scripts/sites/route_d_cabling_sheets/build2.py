"""the route D site per-sheet hierarchy, v2.

CTIN (sheet) > TA level-1 board > circuit N1 > connection point (fused tap, one per table).
Rows come from the connectors; tables are paired to connectors in order along each row;
circuits are connected components of the green N1 cable raster, cut at the boards;
names come from the drawing's circuit table (text or OCR) and the row label boxes.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, re, pickle, collections, json
import numpy as np
from scipy import ndimage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster
from build import circuit_table, row_label_names

W = WORK
PITCH, GAP, TW, TH = 48.08, 0.66, 47.42, 8.45


def rows_from_dots(D, tol=6.0):
    order = np.argsort(D[:, 1])
    rid = np.zeros(len(D), int); r = -1; last = None
    for k in order:
        if last is None or D[k, 1] - last > tol:
            r += 1
        rid[k] = r; last = D[k, 1]
    ry = np.array([D[rid == k, 1].mean() for k in range(r + 1)])
    return rid, ry


def align(dx, slots, synth):
    """order-preserving one-to-one map of sorted dot x's onto sorted slots [(x0,x1)].
    Cost: distance from the dot to the slot interval, plus a small penalty for synthetic slots."""
    n, m = len(dx), len(slots)
    INF = 1e9
    def cost(a, b):
        x0, x1 = slots[b]
        out = 0 if x0 - 1.0 <= dx[a] <= x1 + 1.0 else min(abs(dx[a] - x0), abs(dx[a] - x1)) + 5
        return out + (3 if synth[b] else 0) + 0.001 * abs(dx[a] - (x0 + x1) / 2)
    dp = np.full((n + 1, m + 1), INF); dp[0, :] = 0
    for a in range(1, n + 1):
        for b in range(a, m + 1):
            dp[a, b] = min(dp[a, b - 1], dp[a - 1, b - 1] + cost(a - 1, b - 1))
    # backtrack
    pairs = []; a, b = n, m
    while a > 0:
        if b > a and dp[a, b] == dp[a, b - 1]:
            b -= 1
        else:
            pairs.append((a - 1, b - 1)); a -= 1; b -= 1
    return pairs[::-1], dp[n, m]


def tables_for_rows(T, D, rid, ry, flattened):
    """returns per dot: table box (x0,y0,x1,y1) and whether it was read or synthesised"""
    out = {}
    stats = collections.Counter()
    Tc = (T[:, 1] + T[:, 3]) / 2 if len(T) else np.zeros(0)
    for r, y in enumerate(ry):
        idx = np.where(rid == r)[0]
        idx = idx[np.argsort(D[idx, 0])]
        tt = T[abs(Tc - y) < 6] if len(T) else np.zeros((0, 4))
        tt = tt[np.argsort(tt[:, 0])]
        slots = [(t[0], t[2]) for t in tt]
        synth = [False] * len(slots)
        ty0 = tt[:, 1].mean() if len(tt) else y - TH / 2 - 1
        if flattened and len(slots) < len(idx) + 2:
            # extend the row's table grid to cover the connectors
            phase = slots[0][0] if slots else D[idx[0], 0]
            lo = min(D[idx, 0].min(), slots[0][0] if slots else 1e9) - 2 * PITCH
            hi = max(D[idx, 0].max(), slots[-1][1] if slots else -1e9) + 2 * PITCH
            k0 = int(np.floor((lo - phase) / PITCH)); k1 = int(np.ceil((hi - phase) / PITCH))
            for k in range(k0, k1 + 1):
                x0 = phase + k * PITCH
                if not any(abs(x0 - s[0]) < PITCH / 2 for s in slots):
                    slots.append((x0, x0 + TW)); synth.append(True)
            o = np.argsort([s[0] for s in slots])
            slots = [slots[j] for j in o]; synth = [synth[j] for j in o]
        pairs, c = align(D[idx, 0], slots, synth)
        for a, b in pairs:
            x0, x1 = slots[b]
            out[idx[a]] = ((x0, ty0, x1, ty0 + TH), "synthesised" if synth[b] else "read")
            stats["synth" if synth[b] else "read"] += 1
    return out, stats


def components(i, clip, tas, D, rid):
    lab, sizes, rgb = raster.circuits(i, clip, tas)
    dot_comp = {}
    for a, d in enumerate(D):
        j = raster.label_at(lab, clip, d[0], d[1], r=2.5)
        if j:
            dot_comp[a] = j
    ta_touch = [raster.touching(lab, clip, t) for t in tas]
    comp_ta = {}
    for j in set(dot_comp.values()):
        hits = [q for q, s in enumerate(ta_touch) if j in s]
        comp_ta[j] = hits
    # merge board-less fragments into a component on the same row when they are adjacent
    # and no board lies between them; otherwise give them the nearest board
    tx = [((t[0] + t[2]) / 2, (t[1] + t[3]) / 2) for t in tas]
    changed = True
    while changed:
        changed = False
        for j, hits in list(comp_ta.items()):
            if hits:
                continue
            mine = [a for a, c in dot_comp.items() if c == j]
            rows = set(rid[mine])
            best = None
            for a, c in dot_comp.items():
                if c == j or rid[a] not in rows:
                    continue
                b = min(mine, key=lambda b: abs(D[a, 0] - D[b, 0]))
                lo, hi = sorted((D[a, 0], D[b, 0]))
                between = any(lo < x < hi and abs(y - D[a, 1]) < 12 for x, y in tx)
                dd = hi - lo
                if not between and dd < 1.3 * PITCH and (best is None or dd < best[0]):
                    best = (dd, c)
            if best is not None:
                for a in mine:
                    dot_comp[a] = best[1]
                del comp_ta[j]
                changed = True
                break
    for j, hits in comp_ta.items():
        if hits:
            continue
        mine = [a for a, c in dot_comp.items() if c == j]
        dd = [(min(np.hypot(D[a, 0] - x, D[a, 1] - y) for a in mine), q) for q, (x, y) in enumerate(tx)]
        d0, q = min(dd)
        if d0 < 40:
            comp_ta[j] = [q]
    return dot_comp, comp_ta


def rownum(name):
    m = re.match(r"F\.(\d\d)\.(\d\d)", name or "")
    return int(m[2]) if m else None


def fix_table(table):
    """dedupe by N1, and repair rows that break the monotone order of the printed table"""
    by = {}
    for e in table:
        by.setdefault(e["n1"], e)
    es = [dict(e) for _, e in sorted(by.items())]
    fixes = []
    for k, e in enumerate(es):
        r = rownum(e["row"])
        prv = rownum(es[k - 1]["row"]) if k else None
        nxt = rownum(es[k + 1]["row"]) if k + 1 < len(es) else None
        if prv is not None and nxt is not None and not (prv <= r <= nxt) and prv <= nxt:
            # pick the neighbour sharing this entry's board, else the next row
            cand = es[k + 1] if es[k + 1]["ta"] == e["ta"] else (es[k - 1] if es[k - 1]["ta"] == e["ta"] else es[k + 1])
            fixes.append((e["n1"], e["row"], cand["row"]))
            e["row"] = cand["row"]; e["row_fixed"] = True
    return es, fixes


def name_sheet(i, E, D, rid, ry, dot_comp, comp_ta, table, lab_row_names):
    from scipy.optimize import linear_sum_assignment
    # row numbers for every row index (interpolate missing labels)
    nums = np.array([rownum(lab_row_names.get(r)) if lab_row_names.get(r) else np.nan for r in range(len(ry))], float)
    if np.isnan(nums).any() and (~np.isnan(nums)).sum() >= 2:
        ok = ~np.isnan(nums)
        nums[~ok] = np.round(np.interp(np.where(~ok)[0], np.where(ok)[0], nums[ok]))
    comps = sorted(set(dot_comp.values()))
    info = {}
    for j in comps:
        mine = [a for a, c in dot_comp.items() if c == j]
        rows = sorted(set(rid[mine]))
        prim = collections.Counter(rid[mine]).most_common(1)[0][0]
        info[j] = dict(dots=mine, rows=rows, prim=prim, rownums=[nums[r] for r in rows],
                       x=float(D[mine, 0].mean()), boards=comp_ta.get(j, []))
    # west-to-east rank among components sharing the primary row
    for j, v in info.items():
        peers = sorted([k for k, w in info.items() if w["prim"] == v["prim"]], key=lambda k: info[k]["x"])
        v["rank"] = peers.index(j); v["npeers"] = len(peers)
    def erank(e):
        peers = sorted([f["n1"] for f in table if f["row"] == e["row"]])
        return peers.index(e["n1"]), len(peers)
    board_name = {}
    for it in range(3):
        C = np.full((len(comps), len(table)), 50.0)
        for a, j in enumerate(comps):
            v = info[j]
            for b, e in enumerate(table):
                rn = rownum(e["row"])
                dr = min((abs(rn - x) for x in v["rownums"] if not np.isnan(x)), default=5)
                c = 2.0 * dr
                bn = board_name.get(v["boards"][0]) if v["boards"] else None
                if bn is not None and bn != e["ta"]:
                    c += 6
                rk, npr = erank(e)
                if npr > 1 and v["npeers"] > 1 and rk != v["rank"]:
                    c += 1.5
                C[a, b] = c
        ra, cb = linear_sum_assignment(C)
        assign = {comps[a]: table[b] for a, b in zip(ra, cb) if C[a, b] < 12}
        # unassigned components (fragments): attach to the circuit of the same board on the nearest row
        for j in comps:
            if j in assign:
                continue
            v = info[j]
            best = None
            for k, e in assign.items():
                w = info[k]
                same_board = v["boards"][:1] == w["boards"][:1] and v["boards"]
                d = abs(v["prim"] - w["prim"]) + (0 if same_board else 3)
                if best is None or d < best[0]:
                    best = (d, e)
            if best:
                assign[j] = best[1]; v["merged"] = True
        votes = collections.defaultdict(collections.Counter)
        for j, e in assign.items():
            if info[j]["boards"] and not info[j].get("merged"):
                votes[info[j]["boards"][0]][e["ta"]] += 1
        board_name = {q: c.most_common(1)[0][0] for q, c in votes.items()}
    for j, e in assign.items():
        v = info[j]
        v["cost"] = float(min((abs(rownum(e["row"]) - x) for x in v["rownums"] if not np.isnan(x)), default=9))
    return info, assign, board_name


def name_by_leaders(i, E, D, rid, ry, dot_comp, comp_ta, table, Ls, clip):
    """dot -> (n1, ta) from the leader whose tip lands on the dot's circuit component"""
    lab, sizes, rgb = raster.circuits(i, clip, E["ta_raw"])
    tas = E["ta_raw"]
    tx = [((t[0] + t[2]) / 2, (t[1] + t[3]) / 2) for t in tas]
    lead = collections.defaultdict(list)
    used_leaders = []
    # raw raster label -> merged component id (fragments were merged in components())
    raw2m = {}
    for a in range(len(D)):
        rj = raster.label_at(lab, clip, D[a, 0], D[a, 1], r=2.5)
        if rj and a in dot_comp:
            raw2m.setdefault(rj, collections.Counter())[dot_comp[a]] += 1
    raw2m = {k: v.most_common(1)[0][0] for k, v in raw2m.items()}
    # circuit leaders: tip on a green component, text read as a circuit or unreadable
    cl = []
    for L in Ls:
        p = L.get("parsed")
        if p and p["kind"] == "board":
            continue
        if not p and not re.search(r"(?i)c\s*i\s*r\s*c|n\s*1", L.get("text", "")):
            continue
        tx_, ty_ = L["tip"]
        c_ = int((tx_ - clip[0]) * raster.PX); r_ = int((ty_ - clip[1]) * raster.PX); R_ = int(3 * raster.PX)
        win = rgb[max(r_ - R_, 0):r_ + R_ + 1, max(c_ - R_, 0):c_ + R_ + 1]
        def mind(mask):
            ys, xs = np.nonzero(mask)
            return np.min(np.hypot(ys - R_, xs - R_)) if len(ys) else 1e9
        if mind(raster.is_purple(win)) < mind(raster.is_green(win)):
            continue
        j = raster.label_at(lab, clip, L["tip"][0], L["tip"][1], r=3.0) or raster.label_at(lab, clip, L["tip"][0], L["tip"][1], r=7.0)
        j = raw2m.get(j)
        if not j:
            continue
        r = int(np.argmin(abs(ry - L["tip"][1])))
        cl.append(dict(L=L, j=j, row=r, x=L["tip"][0], n1=p["n1"] if p else None, ta=p["ta"] if p else None))
    cl.sort(key=lambda c: (c["row"], c["x"]))
    # repair OCR slips: distrust numbers not in the table, duplicates, and readings out of order
    n1_tab = {e["n1"]: e["ta"] for e in table}
    table_ok = bool(n1_tab) and set(range(1, max(n1_tab) + 1)) <= set(n1_tab)
    for c in cl:
        c["ocr_n1"] = c["n1"]
        if c["n1"] is not None and table_ok and c["n1"] not in n1_tab:
            c["n1"] = None
    def lis_keep():
        idx = [k for k, c in enumerate(cl) if c["n1"] is not None]
        L_ = [1] * len(idx); P = [-1] * len(idx)
        for a in range(len(idx)):
            for b in range(a):
                if cl[idx[b]]["n1"] < cl[idx[a]]["n1"] and L_[b] + 1 > L_[a]:
                    L_[a] = L_[b] + 1; P[a] = b
        keep = set()
        if idx:
            a = int(np.argmax(L_))
            while a >= 0:
                keep.add(idx[a]); a = P[a]
        return keep
    keep = lis_keep()
    counts = collections.Counter(c["n1"] for c in cl if c["n1"] is not None)
    for k, c in enumerate(cl):
        if c["n1"] is None:
            continue
        dup = counts[c["n1"]] > 1
        bad_ta = table_ok and c["ta"] is not None and n1_tab.get(c["n1"]) not in (None, c["ta"])
        if (k not in keep and (dup or bad_ta)) or (dup and bad_ta):
            c["n1"] = None
    # refill: unassigned numbers between the neighbouring kept readings
    have = {c["n1"] for c in cl if c["n1"] is not None}
    pool = sorted(set(n1_tab) - have) if n1_tab else []
    k = 0
    while k < len(cl):
        if cl[k]["n1"] is not None:
            k += 1; continue
        k1 = k
        while k1 < len(cl) and cl[k1]["n1"] is None:
            k1 += 1
        v0 = max([c["n1"] for c in cl[:k] if c["n1"] is not None], default=0)
        v1 = min([c["n1"] for c in cl[k1:] if c["n1"] is not None], default=10 ** 6)
        cand = [n for n in pool if v0 < n < v1]
        if len(cand) == k1 - k:
            for kk, n in zip(range(k, k1), cand):
                cl[kk]["n1"] = n; cl[kk]["repaired"] = True
        k = k1
    n1_ta = {e["n1"]: e["ta"] for e in table}
    for c in cl:
        if c["n1"] is None:
            continue
        ta = n1_ta.get(c["n1"], c["ta"]) if (c["ta"] is None or c.get("repaired") or c["ocr_n1"] != c["n1"]) else c["ta"]
        if ta is None:
            continue
        lead[c["j"]].append(dict(n1=c["n1"], ta=ta, x=c["x"], y=c["L"]["tip"][1], row=c["row"]))
        used_leaders.append(c["n1"])
    dot_name = {}
    for a, j in dot_comp.items():
        ls = lead.get(j, [])
        if not ls:
            continue
        if len({l["n1"] for l in ls}) == 1:
            dot_name[a] = ls[0]; continue
        same = [l for l in ls if l["row"] == rid[a]]
        if not same:
            dr = min(abs(l["row"] - rid[a]) for l in ls)
            same = [l for l in ls if abs(l["row"] - rid[a]) == dr]
        def blocked(l):
            lo, hi = sorted((D[a, 0], l["x"]))
            return any(lo < x < hi and abs(y - D[a, 1]) < 10 for x, y in tx)
        free = [l for l in same if not blocked(l)] or same
        dot_name[a] = min(free, key=lambda l: abs(l["x"] - D[a, 0]))
    # dots still unnamed: same-row neighbour in the same component, else nearest named dot of same board
    for a, j in dot_comp.items():
        if a in dot_name:
            continue
        cands = [b for b in dot_name if rid[b] == rid[a]]
        if cands:
            b = min(cands, key=lambda b: abs(D[b, 0] - D[a, 0]))
            dot_name[a] = dict(dot_name[b], inferred=True)
    return dot_name, lead, used_leaders


def build(i, verbose=True):
    E = pickle.load(open(f"{W}/cache/E{i:02d}.pkl", "rb"))
    T = np.array(E["tables_raw"]) if E["tables_raw"] else np.zeros((0, 4))
    D = np.array(E["dots"])
    clip = E.get("clip") or (20, 20, 950, 830)
    rid, ry = rows_from_dots(D)
    tab, tstats = tables_for_rows(T, D, rid, ry, not E["layered"])
    dot_comp, comp_ta = components(i, clip, E["ta_raw"], D, rid)
    # row label names
    labels = E["label_raw"]
    names = row_label_names(i, E, labels)
    lab_row = {}
    for b, nm in zip(labels, names):
        cy = (b[1] + b[3]) / 2
        r = int(np.argmin(abs(ry - cy)))
        if abs(ry[r] - cy) < 5:
            lab_row[r] = nm
    rows_bottom = max(t[0][3] for t in tab.values())
    table, src = circuit_table(i, E, rows_bottom)
    table, fixes = fix_table(table)
    import leaders as LD
    Ls = LD.leaders(i, clip, E["layered"])
    dot_name, lead, used_leaders = name_by_leaders(i, E, D, rid, ry, dot_comp, comp_ta, table, Ls, clip)
    info, assign, board_name = name_sheet(i, E, D, rid, ry, dot_comp, comp_ta, table, lab_row)
    # table fallback for dots no leader reached
    for a, j in dot_comp.items():
        if a not in dot_name and j in assign:
            e = assign[j]
            dot_name[a] = dict(n1=e["n1"], ta=e["ta"], from_table=True)
    # board names from leader-named circuits
    votes = collections.defaultdict(collections.Counter)
    for a, nm in dot_name.items():
        j = dot_comp[a]
        for q in comp_ta.get(j, [])[:1]:
            votes[q][nm["ta"]] += 1
    board_name = {q: c.most_common(1)[0][0] for q, c in votes.items()}
    # QA
    q = collections.Counter()
    q["leaders_read"] = sum(1 for L in Ls if L.get("parsed")); q["leaders"] = len(Ls)
    q["dots_named_by_leader"] = sum(1 for v in dot_name.values() if not v.get("from_table") and not v.get("inferred"))
    q["dots_named_inferred"] = sum(1 for v in dot_name.values() if v.get("inferred"))
    q["dots_named_from_table"] = sum(1 for v in dot_name.values() if v.get("from_table"))
    q["dots_unnamed"] = len(D) - len(dot_name)
    n1_t = {e["n1"]: e["ta"] for e in table}
    q["leader_vs_table_ta_mismatch"] = sum(1 for v in dot_name.values() if v["n1"] in n1_t and n1_t[v["n1"]] != v["ta"])
    q["circuits_found"] = len({v["n1"] for v in dot_name.values()})
    q["dots"] = len(D); q["tables_read"] = tstats["read"]; q["tables_synth"] = tstats["synth"]
    q["dots_without_table"] = len(D) - len(tab)
    q["dots_without_circuit"] = sum(1 for a in range(len(D)) if a not in dot_comp)
    q["circuits"] = len(info); q["circuits_named"] = len(assign)
    q["fragments_merged"] = sum(1 for v in info.values() if v.get("merged"))
    q["table_rows_fixed"] = len(fixes)
    q["circuits_off_row"] = sum(1 for v in info.values() if v.get("cost", 0) > 1)
    q["table_entries"] = len(table)
    n1s = [e["n1"] for e in assign.values()]
    q["n1_unused"] = len({e["n1"] for e in table} - set(n1s))
    q["boards"] = len(E["ta_raw"]); q["boards_named"] = len(board_name)
    q["rows"] = len(ry); q["rows_labelled"] = len(lab_row)
    res = dict(sheet=i, E=E, D=D, dot_name=dot_name, leaders=Ls, rid=rid, ry=ry, tab=tab, dot_comp=dot_comp, comp_ta=comp_ta, info=info,
               assign=assign, board_name=board_name, lab_row=lab_row, table=table, table_src=src, table_fixes=fixes, qa=dict(q))
    pickle.dump(res, open(f"{W}/cache/H{i:02d}.pkl", "wb"))
    if verbose:
        print(i, dict(q))
    return res


if __name__ == "__main__":
    for i in map(int, sys.argv[1:]):
        build(i)
