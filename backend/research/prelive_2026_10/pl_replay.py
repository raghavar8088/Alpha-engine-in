"""Replay every NIFTY option-BUYING strategy of the Pre-Live desk over two years of real NIFTY
bars, exactly as the live desk runs them, and price the options with a model calibrated on the
desk's own 5,800 real-premium trades.

Live rules reproduced (prelive-service/main.py + prelive_engine.py):
  - every session the strategy is a FRESH instance (direction state 0) warmed on the last 400
    bars of its timeframe; bars are 5m / 15m / 1h (session-anchored at 09:15)
  - it is asked for a signal at each bar close unless it holds a position (then the bar is only
    pushed); at most 6 trades a day; no entry on a bar starting at/after 15:15
  - BUY -> ATM CE, SELL -> ATM PE of the nearest weekly expiry (Thursday until Aug 2025,
    Tuesday from Sep 2025; a holiday moves it to the previous session); 1 lot
  - exits: premium stop / target of the strategy's category (checked on 5m highs/lows, stop
    first when both), else 15:15
Premium model: Black-Scholes, calendar time, IV = India VIX x a factor fitted on the real trades
(expiry day: by hour, 1.85-4.0; 1 day: 1.33; 2-6 days: 1.05); exit re-priced along the path.
Costs at today's rates and lot (65): Rs20/order + GST, exchange 0.03503%, STT 0.15% of the
premium sold, stamp 0.003% on the buy, SEBI; plus a bid-ask spread of 0.25 pt per side.
Structures scored on the SAME signals: the desk's ATM weekly (baseline); next week's expiry;
NIFTY futures held to 15:15 (no stop); the weekly option held only 60 minutes.
Periods: EXPLORE to 2025-12-31, CONFIRM 2026-01-01..2026-07-19, LIVE 2026-07-20..2026-10-01
(the desk's own forward window, for validating the replay against the real trades).
"""
import json
import math
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path[:0] = [r"D:\INDIAN MARKET\shared", r"D:\INDIAN MARKET\strategy-service", r"D:\INDIAN MARKET\options-service"]
import strategy_service.strategies.options_buying  # noqa: F401,E402
from options_service.options_backtest import OPTION_BUYING_CATEGORIES  # noqa: E402
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext  # noqa: E402
from tradingai_shared.domain import Bar, SignalAction, Timeframe  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
R = 0.065
LOT = 65
SPREAD = 0.25
D = json.load(open("nifty_bars.json"))
N5 = D["NIFTY_5m"]
N15 = D["NIFTY_15m"]
V15 = D["INDIAVIX_15m"]
vt = [r[0] for r in V15]


def ist(e):
    return datetime.fromtimestamp(e, IST)


def mins(e):
    return ((e + 19800) % 86400) // 60


def dkey(e):
    return (e + 19800) // 86400


TD = sorted({dkey(r[0]) for r in N5})
TDS = set(TD)


def kdate(k):
    return date(1970, 1, 1) + timedelta(days=k)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, sig, call):
    if T <= 0 or sig <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (R + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * ncdf(d1) - K * math.exp(-R * T) * ncdf(d2) if call else K * math.exp(-R * T) * ncdf(-d2) - S * ncdf(-d1)


H0 = {9: 1.85, 10: 1.72, 11: 2.07, 12: 2.14, 13: 2.04, 14: 3.0, 15: 4.0}


def ivx(dte, hour):
    if dte == 0:
        return H0.get(hour, 2.1)
    return 1.33 if dte == 1 else 1.05


def expiry_key(k, plus_week=False):
    d = kdate(k)
    wd = 1 if d >= date(2025, 9, 1) else 3
    x = d
    while x.weekday() != wd:
        x += timedelta(days=1)
    if plus_week:
        x += timedelta(days=7)
    xk = (x - date(1970, 1, 1)).days
    if xk <= TD[-1]:
        while xk not in TDS:
            xk -= 1
    return xk


def T_years(e, xk):
    exp = xk * 86400 - 19800 + (15 * 60 + 30) * 60
    return max(exp - e, 60) / (365 * 86400)


def vix_at(e):
    i = bisect_right(vt, e - 900) - 1
    return V15[i][4] / 100 if i >= 0 and e - vt[i] < 86400 * 5 else None


def fees(p0, p1):
    t0, t1 = p0 * LOT, p1 * LOT
    brok = 40.0
    exch = (t0 + t1) * 0.0003503
    sebi = (t0 + t1) * 0.000001
    gst = 0.18 * (brok + exch + sebi)
    return brok + exch + sebi + gst + t1 * 0.0015 + t0 * 0.00003


def fut_cost(s0, s1):
    n0, n1 = s0 * LOT, s1 * LOT
    brok = 40.0
    exch = (n0 + n1) * 0.0000173
    sebi = (n0 + n1) * 0.000001
    gst = 0.18 * (brok + exch + sebi)
    return brok + exch + sebi + gst + max(n0, n1) * 0.0005 + min(n0, n1) * 0.00002 + 0.5 * LOT * 2  # 0.5 pt slip a side


# ── bars per timeframe, grouped by day ──
def mkbars(rows, tf):
    out = []
    for r in rows:
        out.append(Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=ist(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=0))
    return out


def agg_1h(rows15):
    out, cur = [], None
    for r in rows15:
        k, m = dkey(r[0]), mins(r[0])
        b = (m - 555) // 60
        key = (k, b)
        if cur is None or cur[0] != key:
            if cur:
                out.append(cur[1])
            start = k * 86400 - 19800 + (555 + b * 60) * 60
            cur = (key, [start, r[1], r[2], r[3], r[4]])
        else:
            c = cur[1]
            c[2] = max(c[2], r[2]); c[3] = min(c[3], r[3]); c[4] = r[4]
    if cur:
        out.append(cur[1])
    return out


ROWS = {"5m": N5, "15m": N15, "1h": agg_1h(N15)}
TFMIN = {"5m": 5, "15m": 15, "1h": 60}
BARS = {tf: mkbars(r, tf) for tf, r in ROWS.items()}
STARTS = {tf: [r[0] for r in rows] for tf, rows in ROWS.items()}
n5t = [r[0] for r in N5]


def day_slice(tf, k):
    st = STARTS[tf]
    a = bisect_left(st, k * 86400 - 19800)
    b = bisect_left(st, (k + 1) * 86400 - 19800)
    return a, b


def path5(e_from, k):
    """5m bars of day k that START at/after e_from (the position is open through them)."""
    a = bisect_left(n5t, e_from)
    b = bisect_left(n5t, (k + 1) * 86400 - 19800)
    return N5[a:b]


def sim_option(e0, s0, side, k, stop_pct, tgt_pct, xk, hold_limit_min=None):
    """Premium path along 5m bars; returns (exit_e, p0, p1, reason)."""
    call = side > 0
    K = round(s0 / 50) * 50
    v = vix_at(e0)
    if not v:
        return None
    dte = (xk - k)
    sig = v * ivx(dte, ist(e0).hour)
    p0 = bs(s0, K, T_years(e0, xk), sig, call)
    if p0 < 1:
        return None
    stop, tgt = p0 * (1 - stop_pct), p0 * (1 + tgt_pct)
    eod = k * 86400 - 19800 + (15 * 60 + 15) * 60
    for r in path5(e0, k):
        t = r[0]
        if t >= eod or (hold_limit_min and t >= e0 + hold_limit_min * 60):
            break
        te = t + 300
        sig_t = v * ivx(dte, ist(te).hour)
        worst = r[3] if call else r[2]
        best = r[2] if call else r[3]
        pw = bs(worst, K, T_years(te, xk), sig_t, call)
        pb = bs(best, K, T_years(te, xk), sig_t, call)
        if pw <= stop:
            return te, p0, stop, "stop"
        if pb >= tgt:
            return te, p0, tgt, "target"
    i = bisect_right(n5t, min(eod, e0 + (hold_limit_min or 10**6) * 60) - 300) - 1
    s1 = N5[i][4]
    te = min(eod, e0 + (hold_limit_min or 10**6) * 60)
    sig_t = v * ivx(dte, ist(te).hour)
    return te, p0, bs(s1, K, T_years(te, xk), sig_t, call), "eod" if not hold_limit_min else "time"


def spot_close_before(e):
    i = bisect_right(n5t, e - 300) - 1
    return N5[i][4] if i >= 0 else None


def replay(sid, tf):
    cls = STRATEGY_REGISTRY[sid]
    probe = cls(params={})
    cat = probe.metadata.category
    style = OPTION_BUYING_CATEGORIES.get(cat, OPTION_BUYING_CATEGORIES["options_intraday"])
    warm = probe.warmup
    bars = BARS[tf]
    out = []
    for k in TD:
        a, b = day_slice(tf, k)
        if b - a < 3 or a < 50:
            continue
        strat = cls(params={})
        ctx = StrategyContext(max_bars=max(500, warm + 5))
        for bb in bars[max(0, a - 400):a]:
            ctx.push(bb)
        busy_until = 0
        n_today = 0
        for j in range(a, b):
            bar = bars[j]
            ctx.push(bar)
            s = STARTS[tf][j]
            end = min(s + TFMIN[tf] * 60, k * 86400 - 19800 + 930 * 60)
            if end < busy_until or n_today >= 6 or len(ctx.bars) < warm:
                continue
            try:
                sg = strat.on_bar(ctx)
            except Exception:
                sg = None
            if sg is None or sg.signal not in (SignalAction.BUY, SignalAction.SELL):
                continue
            if mins(s) >= 915:
                continue
            side = 1 if sg.signal == SignalAction.BUY else -1
            s0 = bar.close
            xk = expiry_key(k)
            r = sim_option(end, s0, side, k, style["premium_stop_pct"], style["premium_target_pct"], xk)
            if r is None:
                continue
            te, p0, p1, why = r
            busy_until = te
            n_today += 1
            # the same signal, other structures
            xk2 = expiry_key(k, plus_week=True)
            r2 = sim_option(end, s0, side, k, style["premium_stop_pct"], style["premium_target_pct"], xk2)
            r60 = sim_option(end, s0, side, k, style["premium_stop_pct"], style["premium_target_pct"], xk, hold_limit_min=60)
            eod = k * 86400 - 19800 + (15 * 60 + 15) * 60
            s_eod = spot_close_before(eod)
            out.append({
                "k": k, "e": end, "side": side, "dte": xk - k, "s0": s0, "p0": p0, "p1": p1, "why": why, "hold": (te - end) / 60,
                "net": (p1 - p0 - 2 * SPREAD) * LOT - fees(p0, p1),
                "fav_eod_bp": side * (s_eod / s0 - 1) * 1e4 if s_eod else None,
                "net_nextwk": ((r2[2] - r2[1] - 2 * SPREAD) * LOT - fees(r2[1], r2[2])) if r2 else None,
                "net_60m": ((r60[2] - r60[1] - 2 * SPREAD) * LOT - fees(r60[1], r60[2])) if r60 else None,
                "net_fut": (side * (s_eod - s0) * LOT - fut_cost(s0, s_eod)) if s_eod else None,
            })
    return out


def period(k):
    d = kdate(k)
    return "explore" if d <= date(2025, 12, 31) else "confirm" if d < date(2026, 7, 20) else "live"


def main():
    pairs = []
    for sid, cls in STRATEGY_REGISTRY.items():
        if "options_buying" not in (getattr(cls, "__module__", "") or ""):
            continue
        for tfv in [getattr(t, "value", str(t)) for t in (cls.metadata.timeframes or [])]:
            if tfv in TFMIN:
                pairs.append((sid, tfv))
    pairs.sort()
    if len(sys.argv) > 1:
        pairs = pairs[:int(sys.argv[1])]
    print(f"{len(pairs)} strategy/timeframe pairs; days {kdate(TD[0])}..{kdate(TD[-1])}", flush=True)
    res = {}
    t0 = time.time()
    for n, (sid, tf) in enumerate(pairs):
        t1 = time.time()
        tr = replay(sid, tf)
        res[f"{sid}@{tf}"] = tr
        if n % 10 == 0 or time.time() - t1 > 60:
            print(f"  {n + 1}/{len(pairs)} {sid}@{tf}: {len(tr)} trades, {time.time() - t1:.0f}s (total {time.time() - t0:.0f}s)", flush=True)
    json.dump(res, open("pl_replay_trades.json", "w"))
    print("saved", flush=True)


if __name__ == "__main__":
    main()
