"""Replay every INTRADAY option-buying strategy of the library (5m / 15m) on BANKNIFTY,
with the live NIFTY desk's rules, buying BANKNIFTY's MONTHLY ATM options.

Live rules reproduced (prelive-service/main.py + prelive_engine.py, as pl_replay.py did for NIFTY):
  - every session the strategy is a FRESH instance warmed on the last 400 bars of its timeframe
    (bars are session-anchored at 09:15); it is asked for a signal at each bar close unless it
    holds a position; at most 6 trades a day; no entry on a bar ending after 15:00 (the NIFTY
    tournament allows them until 15:15, where they are squared off the moment they open)
  - BUY -> ATM CE, SELL -> ATM PE (strike = spot rounded to 100), 1 lot of 30, of the nearest
    monthly with >= 7 sessions left (else the next monthly)
  - exits: the category's premium stop / target, checked on 5m highs/lows (stop first when a
    bar touches both, filled at the level), else 15:15
Premium model: Black-76 on the forward; vol = the PREVIOUS session's real smile for that very
contract (bhavcopy closes, bn_surface.py) at the strike's moneyness, scaled by India VIX now /
VIX at the previous close; variance clock. Costs: Angel's rate card today + 0.25% half spread.
The two strategies that read a second index (SMT divergence) get NIFTY where they asked for
BANKNIFTY - the same pair, seen from the other side.

Output: results/lib/<strategy>@<tf>.json - one row per trade. Resumable; runs in parallel.
"""

import gzip
import json
import math
import os
import sys
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime
from multiprocessing import Pool

import bn_common as C
from bn_price import Pricer

OUT = os.path.join(C.DATA, "results", "lib")
G: dict = {}


def init_worker():
    import strategy_service.strategies.options_buying  # noqa: F401
    from strategy_service.strategies.options_buying import _cross_symbol
    from tradingai_shared.domain import Bar, Timeframe

    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    vix = C.Sessions("INDIAVIX", start=date(2015, 12, 1))
    nf = C.Sessions("NIFTY", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    G.update(bn=bn, px=Pricer(vix, spot=bn))

    def mk(sess, tf, minutes):
        rows = []
        for k in sess.days:
            bars = sess.bars[k]
            if minutes == 5:
                rows += [list(r) for r in bars]
                continue
            cur = None
            for r in bars:
                b = (C.minute(int(r[0])) - C.OPEN_MIN) // minutes
                if cur is None or cur[0] != b:
                    if cur:
                        rows.append(cur[1])
                    cur = (b, [C.at(k, C.OPEN_MIN + b * minutes), r[1], r[2], r[3], r[4]])
                else:
                    c = cur[1]
                    c[2] = max(c[2], r[2]); c[3] = min(c[3], r[3]); c[4] = r[4]
            if cur:
                rows.append(cur[1])
        return rows

    def objects(rows, tf):
        return [Bar.model_construct(symbol="BANKNIFTY", timeframe=Timeframe(tf), ts=C.ist(int(r[0])), open=r[1],
                                    high=r[2], low=r[3], close=r[4], volume=0, oi=None) for r in rows]

    G["rows"], G["objs"], G["starts"] = {}, {}, {}
    nf_close: dict = {}
    for tf, m in (("5m", 5), ("15m", 15)):
        rows = mk(bn, tf, m)
        G["rows"][tf], G["objs"][tf], G["starts"][tf] = rows, objects(rows, tf), [int(r[0]) for r in rows]
        for r in mk(nf, tf, m):
            nf_close[(tf, int(r[0]))] = r[4]

    def close_at(symbol, timeframe, ts):           # the other index of the pair
        return nf_close.get((timeframe, int(ts.timestamp())))
    _cross_symbol.close_at = close_at
    G["n5t"] = [int(r[0]) for r in G["rows"]["5m"]]


def premium(e: int, S: float, K: float, call: bool, ek: int, kp: int) -> float:
    return G["px"].premium(e, S, K, call, ek, kp)


def sim(e0: int, S0: float, side: int, k: int, stop_pct: float, tgt_pct: float, ek: int, kp: int):
    call = side > 0
    K = round(S0 / C.STEP) * C.STEP
    p0 = premium(e0, S0, K, call, ek, kp)
    if not p0 or p0 < 5:
        return None
    stop, tgt = p0 * (1 - stop_pct), p0 * (1 + tgt_pct)
    eod = C.at(k, C.SQUARE_OFF_MIN)
    n5t, rows = G["n5t"], G["rows"]["5m"]
    i = bisect_left(n5t, e0)
    while i < len(rows) and n5t[i] < eod and C.dkey(n5t[i]) == k:
        r = rows[i]
        te = n5t[i] + 300
        worst, best = (r[3], r[2]) if call else (r[2], r[3])
        if premium(te, worst, K, call, ek, kp) <= stop:
            return te, K, p0, stop, "stop"
        if premium(te, best, K, call, ek, kp) >= tgt:
            return te, K, p0, tgt, "target"
        i += 1
    j = bisect_right(n5t, eod - 300) - 1
    S1 = rows[j][4]
    return eod, K, p0, premium(eod, S1, K, call, ek, kp), "eod"


def spot_before(e: int) -> float:
    n5t = G["n5t"]
    return G["rows"]["5m"][bisect_right(n5t, e - 300) - 1][4]


def replay(job):
    sid, tf = job
    path = os.path.join(OUT, f"{sid}@{tf}.json")
    if os.path.exists(path):
        return sid, tf, -1, 0.0
    from options_service.options_backtest import OPTION_BUYING_CATEGORIES
    from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
    from tradingai_shared.domain import SignalAction

    t0 = time.time()
    cls = STRATEGY_REGISTRY[sid]
    probe = cls(params={})
    style = OPTION_BUYING_CATEGORIES.get(probe.metadata.category, OPTION_BUYING_CATEGORIES["options_intraday"])
    warm = probe.warmup
    tfmin = 5 if tf == "5m" else 15
    rows, objs, starts = G["rows"][tf], G["objs"][tf], G["starts"][tf]
    out = []
    k0 = C.dk(C.RESEARCH_START)
    day_idx: dict[int, tuple[int, int]] = {}
    for i, s in enumerate(starts):
        k = C.dkey(s)
        a, _ = day_idx.get(k, (i, i))
        day_idx[k] = (a, i + 1)
    for k in sorted(day_idx):
        if k < k0:
            continue
        a, b = day_idx[k]
        if b - a < 3 or a < 50:
            continue
        cp = G["px"].contract_for(k)
        if cp is None:
            continue
        ek, kp = cp
        strat = cls(params={})
        ctx = StrategyContext(max_bars=max(500, warm + 5))
        for bb in objs[max(0, a - 400):a]:
            ctx.push(bb)
        busy_until, n_today = 0, 0
        for j in range(a, b):
            ctx.push(objs[j])
            s = starts[j]
            end = min(s + tfmin * 60, C.at(k, C.CLOSE_MIN))
            if end < busy_until or n_today >= 6 or len(ctx.bars) < warm:
                continue
            try:
                sg = strat.on_bar(ctx)
            except Exception:
                sg = None
            if sg is None or sg.signal not in (SignalAction.BUY, SignalAction.SELL):
                continue
            if C.minute(end) > C.NO_ENTRY_AFTER_MIN or C.dkey(end) != k:
                continue
            side = 1 if sg.signal == SignalAction.BUY else -1
            S0 = rows[j][4]
            r = sim(end, S0, side, k, style["premium_stop_pct"], style["premium_target_pct"], ek, kp)
            if r is None:
                continue
            te, K, p0, p1, why = r
            busy_until = te
            n_today += 1
            S1 = spot_before(te)
            out.append([k, end, side, C.trading_sessions_left(k, ek), round(S0, 2), K, round(p0, 2), round(p1, 2), why,
                        round((te - end) / 60), round(C.net_pnl(p0, p1), 2), round(side * (S1 / S0 - 1) * 1e4, 2)])
    with open(path + ".tmp", "w") as f:
        json.dump({"sid": sid, "tf": tf, "category": probe.metadata.category, "stop": style["premium_stop_pct"],
                   "target": style["premium_target_pct"],
                   "cols": ["k", "entry_e", "side", "sessions_left", "S0", "K", "p0", "p1", "why", "hold_min", "net", "fav_bp"],
                   "trades": out}, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    return sid, tf, len(out), time.time() - t0


def jobs():
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    out = []
    for sid, cls in STRATEGY_REGISTRY.items():
        if "options_buying" not in (getattr(cls, "__module__", "") or ""):
            continue
        for t in cls.metadata.timeframes or []:
            tfv = getattr(t, "value", str(t))
            if tfv in ("5m", "15m"):
                out.append((sid, tfv))
    return sorted(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    js = jobs()
    if len(sys.argv) > 1:   # a number = the first N pairs; otherwise strategy-id substrings
        js = js[:int(sys.argv[1])] if sys.argv[1].isdigit() else [j for j in js if any(a in j[0] for a in sys.argv[1:])]
    nproc = int(os.environ.get("BN_PROCS", "10"))
    print(f"{len(js)} strategy/timeframe pairs on {nproc} processes", flush=True)
    t0 = time.time()
    with Pool(nproc, initializer=init_worker) as pool:
        for n, (sid, tf, ntr, secs) in enumerate(pool.imap_unordered(replay, js), 1):
            print(f"{n}/{len(js)} {sid}@{tf}: {ntr} trades {secs:.0f}s (wall {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
