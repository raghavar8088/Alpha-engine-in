"""An independent recomputation of sampled n50_engine trades: plain loops over the raw clean candles (not the
engine's cubes), daily figures rebuilt from the raw rows, and the app's own angel_fees.round_trip.

    python reference_n50.py <data dir: n50_clean.pkl, universe.json> [samples per setup and side]

Only sessions up to 2024-12-31 are read.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n50_engine as E  # noqa: E402
from app.services import angel_fees  # noqa: E402


def session_rows(g):
    """{candle index: (o, h, l, c, v)} for one stock-session."""
    out = {}
    for ts, o, h, l, c, v in zip(g.ts, g.o, g.h, g.l, g.c, g.v):
        out[((ts.hour * 60 + ts.minute) - (9 * 60 + 15)) // 5] = (o, h, l, c, float(v))
    return out


def cs_ref(days_rows):
    """Corwin-Schultz over every same-session pair of adjacent candles that both traded."""
    vals = []
    k = 3 - 2 * math.sqrt(2)
    for cs in days_rows:
        for b in sorted(cs):
            if b + 1 not in cs:
                continue
            o1, h1, l1, c1, v1 = cs[b]
            o2, h2, l2, c2, v2 = cs[b + 1]
            if v1 <= 0 or v2 <= 0 or l1 <= 0 or l2 <= 0:
                continue
            beta = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
            gam = math.log(max(h1, h2) / min(l1, l2)) ** 2
            a = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gam / k)
            vals.append(max(2 * (math.exp(a) - 1) / (1 + math.exp(a)), 0.0))
    return max(sum(vals) / len(vals) / 2 * 1e4, 1.0)


def ref_trade(setup, side, cs, H15, L15, slip, target_r=2.0):
    bars = sorted(cs)
    after = [b for b in bars if b >= 71]
    sq = after[0] if after else max(b for b in bars if b < 71)
    vw, num, den = {}, 0.0, 0.0
    for b in bars:
        o, h, l, c, v = cs[b]
        num += (h + l + c) / 3 * v
        den += v
        vw[b] = num / den if den > 0 else float("nan")
    trail, target = False, None
    if setup == "S1":
        level, stop = (H15, L15) if side > 0 else (L15, H15)
        entry_bar = None
        for b in bars:
            if 3 <= b <= 26 and b < sq:
                o, h, l, c, v = cs[b]
                if (side > 0 and h >= level) or (side < 0 and l <= level):
                    entry_bar = b
                    entry = (max(level, o) if side > 0 else min(level, o)) * (1 + side * slip)
                    break
        if entry_bar is None:
            return None
    elif setup == "S2":
        if 3 not in cs or 3 >= sq:
            return None
        entry_bar, entry, stop, trail = 3, cs[3][0] * (1 + side * slip), (L15 if side > 0 else H15), True
    else:
        touch = None
        for b in bars:
            if 3 <= b < sq:
                o, h, l, c, v = cs[b]
                if (side > 0 and l <= vw[b]) or (side < 0 and h >= vw[b]):
                    touch = b
                    break
        if touch is None:
            return None
        ref = cs[touch][1] if side > 0 else cs[touch][2]
        ext = cs[touch][2] if side > 0 else cs[touch][1]
        sig = None
        for b in bars:
            if touch < b <= 50 and b < sq:
                o, h, l, c, v = cs[b]
                ext = min(ext, l) if side > 0 else max(ext, h)
                if (side > 0 and c > ref) or (side < 0 and c < ref):
                    sig = b
                    break
        if sig is None:
            return None
        nxt = [b for b in bars if b > sig]
        if not nxt or nxt[0] >= sq:
            return None
        entry_bar, entry, stop = nxt[0], cs[nxt[0]][0] * (1 + side * slip), ext
    if setup != "S2":
        target = entry + side * target_r * abs(entry - stop)
    if (entry - stop) * side <= 0:
        return None
    for b in bars:
        if b < entry_bar or b >= sq:
            continue
        o, h, l, c, v = cs[b]
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            px = stop if b == entry_bar else (min(o, stop) if side > 0 else max(o, stop))
            return entry_bar, entry, stop, b, px * (1 - side * slip), 1
        if target is not None and ((side > 0 and h > target) or (side < 0 and l < target)):
            return entry_bar, entry, stop, b, target, 2
        if trail and ((side > 0 and c < vw[b]) or (side < 0 and c > vw[b])):
            k = next(x for x in bars if x > b)
            return entry_bar, entry, stop, k, cs[k][0] * (1 - side * slip), 3
    return entry_bar, entry, stop, sq, cs[sq][0] * (1 - side * slip), 0


def main(data, per=150):
    data = Path(data)
    raw = pd.read_pickle(data / "n50_clean.pkl")
    raw = raw[raw.day <= pd.Timestamp("2024-12-31")].reset_index(drop=True)
    P = E.Panel(raw, HERE / "phase0" / "membership.json", data / "universe.json")
    f = P.screen(3)
    stocks_raw = {s: g for s, g in raw.groupby("symbol")}
    rng = np.random.default_rng(42)
    cs_cache, daily_cache = {}, {}
    worst = {"price": 0.0, "net": 0.0, "screen": 0.0}
    n_cmp = n_trade = mism = 0
    for setup in E.SETUPS:
        for side in (1, -1):
            pool = E.pool(P, f, setup, side)
            pick = pool.iloc[rng.choice(len(pool), size=min(per, len(pool)), replace=False)]
            for r in pick.itertuples():
                sym, day = r.stock, r.day
                g = stocks_raw[sym]
                if sym not in daily_cache:
                    dd = {d: session_rows(x) for d, x in g.groupby("day")}
                    daily_cache[sym] = dd
                dd = daily_cache[sym]
                days = sorted(dd)
                k = days.index(day)
                cs = dd[day]
                # the screen from raw rows
                O, H15 = cs[0][0], max(cs[b][1] for b in (0, 1, 2))
                L15, Pc = min(cs[b][2] for b in (0, 1, 2)), cs[2][3]
                trs = []
                for j in range(k - 14, k):
                    hj = max(x[1] for x in dd[days[j]].values())
                    lj = min(x[2] for x in dd[days[j]].values())
                    cp = dd[days[j - 1]][max(dd[days[j - 1]])][3] if j >= 1 else None
                    trs.append(max(hj - lj, abs(hj - cp), abs(lj - cp)) if cp is not None else hj - lj)
                or_move = (Pc - O) / (sum(trs) / 14)
                worst["screen"] = max(worst["screen"], abs(or_move - r.mv * side))
                turn5 = np.mean([sum(x[3] * x[4] for x in dd[days[j]].values()) / len(dd[days[j]])
                                 for j in range(k - 20, k)])
                key = (sym, day.year)
                if key not in cs_cache:
                    cs_cache[key] = cs_ref([dd[d] for d in days if d.year == day.year])
                slip = (cs_cache[key] + E.EXTRA_SLIP_BP) / 1e4
                ref = ref_trade(setup, side, cs, H15, L15, slip)
                q = None
                if ref is not None:
                    eb, entry, stop, xb, px, why = ref
                    q = math.floor(min(E.RISK / abs(entry - stop), E.CAP_TRADE / entry, 0.01 * turn5 / entry))
                    if q < 1:
                        ref = None
                n_cmp += 1
                if (ref is not None) != bool(r.ok):
                    mism += 1
                    print(f"MISMATCH trade/no-trade {setup} {side} {sym} {day.date()}: ref {ref} engine ok={r.ok}")
                    continue
                if ref is None:
                    continue
                n_trade += 1
                fee = angel_fees.round_trip(entry, px, q, side="BUY" if side > 0 else "SELL", product="INTRADAY").total
                net = side * (px - entry) * q - fee
                same = (eb == r.entry_bar and xb == r.exit_bar and why == r.reason and q == r.qty)
                dp = max(abs(entry - r.entry), abs(px - r.exit), abs(stop - r.stop))
                worst["price"] = max(worst["price"], dp)
                worst["net"] = max(worst["net"], abs(net - r.net))
                if not same or dp > 1e-6 or abs(net - r.net) > 0.02:
                    mism += 1
                    print(f"MISMATCH {setup} {side} {sym} {day.date()}: ref bars {eb}->{xb} why {why} q {q} entry {entry:.4f}"
                          f" exit {px:.4f} net {net:.2f} | engine {r.entry_bar}->{r.exit_bar} why {r.reason} q {r.qty}"
                          f" entry {r.entry:.4f} exit {r.exit:.4f} net {r.net:.2f}")
    print(f"compared {n_cmp} sampled candidates ({n_trade} trades): {mism} mismatches; worst price diff "
          f"{worst['price']:.2e}, worst net diff {worst['net']:.4f}, worst or_move diff {worst['screen']:.2e}")
    sys.exit(1 if mism else 0)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 150)
