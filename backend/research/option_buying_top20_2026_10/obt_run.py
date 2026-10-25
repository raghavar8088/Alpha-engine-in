"""Top 20 NIFTY option-BUYING strategies of the last month, and whether a month's top 20 keeps winning.

    python -I backend/research/option_buying_top20_2026_10/obt_run.py [workers]

The library: every option-buying strategy of the app (strategy-service, options_buying: 167 strategy x
timeframe pairs, the Pre-Live desk's library), replayed with the live desk's rules
(../prelive_2026_10/pl_replay.py):
  * every session a fresh instance, warmed on the last 400 bars of its timeframe (5m / 15m / 1h, anchored
    at 09:15, from Angel One's NIFTY 1-minute candles);
  * a signal at each bar close unless a position is open; at most 6 trades a day; no entry on a bar
    starting at or after 15:15;
  * BUY -> the ATM CALL, SELL -> the ATM PUT of the nearest weekly expiry (expiry day included), one lot of 65;
  * the category's premium stop / target (scalp 25% / 50%, intraday 30% / 60%, breakout 35% / 100%),
    else out at 15:15.
PRICES. 5-23 Oct 2026: the REAL quotes the app recorded every minute (bought at the ask, sold at the bid,
stop and target checked on the mid each minute). Other sessions: the validated premium model of
../nifty_options_orb_2026_10 (previous session's real NSE smile, India VIX, the intraday variance clock),
stop and target checked on each minute's worst and best NIFTY level, every fill paying half the spread
and a tick. Charges: Angel One's option rate card at today's rates.
WINDOWS. The last month = 24 Sep .. 23 Oct 2026. The persistence check walks 12 earlier one-month blocks:
rank on block b, measure the top 20 on block b+1 (model prices throughout, so every block is priced alike).
"""

from __future__ import annotations

import gzip
import json
import math
import multiprocessing as mp
import statistics
import sys
import time
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NOPT = HERE.parent / "nifty_options_orb_2026_10"
REPO = HERE.parents[2]
for _p in (NOPT, REPO / "shared", REPO / "strategy-service", REPO / "options-service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nopt_common as C  # noqa: E402

RES = HERE / "results"
LAST_FROM, LAST_TO = date(2026, 9, 24), date(2026, 10, 23)
N_BLOCKS = 12
BARS_FROM = date(2025, 6, 1)          # 13 months back plus warm-up for the 1-hour strategies
TF_MIN = {"5m": 5, "15m": 15, "1h": 60}
EOD_MIN = 15 * 60 + 15

# ── per-process state ─────────────────────────────────────────────────────────────────────────────
G: dict = {}


def blocks() -> list[tuple[date, date]]:
    """The last month and the 12 one-month blocks before it, oldest first: (from, to)."""
    out = [(LAST_FROM, LAST_TO)]
    to = LAST_FROM - timedelta(days=1)
    for _ in range(N_BLOCKS):
        frm = date(to.year if to.month > 1 else to.year - 1, to.month - 1 if to.month > 1 else 12, 24)
        out.append((frm, to))
        to = frm - timedelta(days=1)
    return out[::-1]


def init_worker() -> None:
    import strategy_service.strategies.options_buying  # noqa: F401
    from options_service.options_backtest import OPTION_BUYING_CATEGORIES
    from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
    from tradingai_shared.domain import Bar, SignalAction, Timeframe
    from nopt_price import Pricer
    from nopt_run import Contracts
    C.set_calendar()
    z = np.load(C.DATA / "minutes.npz")
    days = [C.dk(date.fromisoformat(str(d))) for d in z["days"]]
    # an NpzFile decompresses an array on EVERY z[...] access: read each one once
    o, h, l, c = (np.asarray(z[k]) for k in ("o", "h", "l", "c"))
    G.update(REG=STRATEGY_REGISTRY, CTX=StrategyContext, ACT=SignalAction, CATS=OPTION_BUYING_CATEGORIES,
             days=days, row={k: i for i, k in enumerate(days)}, o=o, h=h, l=l, c=c)
    px = Pricer()
    G["px"], G["cons"] = px, Contracts(px)
    # session-anchored bars per timeframe, as Bar objects, with their start epochs
    bars, starts = {}, {}
    for tf, step in (("5m", 5), ("15m", 15), ("1h", 60)):
        bl, st = [], []
        for k, i in zip(days, range(len(days))):
            if k < C.dk(BARS_FROM):
                continue
            for s in range(0, 375, step):
                e_ = min(s + step, 375)
                e0 = C.at(k, C.OPEN_MIN + s)
                bl.append(Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=datetime.fromtimestamp(e0, C.IST),
                              open=float(o[i, s]), high=float(h[i, s:e_].max()), low=float(l[i, s:e_].min()),
                              close=float(c[i, e_ - 1]), volume=0))
                st.append(e0)
        bars[tf], starts[tf] = bl, st
    G["bars"], G["starts"] = bars, starts
    # recorded real quotes: day key -> minute-of-day -> {(expiry, strike, 'C'|'P'): (bid, ask, mid)}
    chain = {}
    for f in sorted((C.DATA / "optchain").glob("*.jsonl.gz")):
        k = C.dk(date.fromisoformat(f.name[:10]))
        per = {}
        for ln in gzip.open(f, "rt"):
            m = json.loads(ln)
            exps = m.get("exp") or []
            q = {}
            for r in m["rows"]:
                ei, K, cp, ltp, bid, _, ask = r[:7]
                if bid and ask and ask >= bid > 0 and (ask - bid) / ((ask + bid) / 2) < 0.05:
                    q[(exps[ei], float(K), cp)] = (float(bid), float(ask), (bid + ask) / 2)
            per[C.minute_of_day(m["t"])] = q
        chain[k] = per
    G["chain"] = chain


def model_trade(k: int, e0: int, S0: float, call: bool, stop_pct: float, tgt_pct: float):
    pick = G["cons"].pick(k, S0)
    if pick is None:
        return None
    ek, K, kp = pick
    px = G["px"]
    m0 = px.premium(e0, S0, K, call, ek, kp)
    if m0 < 1:
        return None
    stop, tgt = m0 * (1 - stop_pct), m0 * (1 + tgt_pct)
    i = G["row"][k]
    first = (e0 - C.at(k, C.OPEN_MIN)) // 60                    # the minute that starts at e0
    exit_mid, why, te = None, "eod", C.at(k, EOD_MIN)
    for m in range(first, 360):
        t_end = C.at(k, C.OPEN_MIN + m + 1)
        worst = G["l"][i, m] if call else G["h"][i, m]
        best = G["h"][i, m] if call else G["l"][i, m]
        if px.premium(t_end, worst, K, call, ek, kp) <= stop:
            exit_mid, why, te = stop, "stop", t_end
            break
        if px.premium(t_end, best, K, call, ek, kp) >= tgt:
            exit_mid, why, te = tgt, "target", t_end
            break
    if exit_mid is None:
        exit_mid = px.premium(te, float(G["c"][i, 359]), K, call, ek, kp)
    buy, sell = C.buy_fill(m0), C.sell_fill(exit_mid)
    return {"ek": ek, "K": K, "in": buy, "out": sell, "why": why, "te": te, "priced": "model"}


def real_trade(k: int, e0: int, S0: float, call: bool, stop_pct: float, tgt_pct: float):
    pick = G["cons"].pick(k, S0)
    if pick is None:
        return None
    ek, K, _ = pick
    key = (C.kdate(ek).isoformat(), float(K), "C" if call else "P")
    ch = G["chain"][k]
    m_start = C.minute_of_day(e0)
    mins = sorted(m for m in ch if m >= m_start and m <= EOD_MIN)
    q0 = next(((m, ch[m][key]) for m in mins if key in ch[m]), None)
    if q0 is None or q0[0] > m_start + 2:
        return None
    m0, (b0, a0, mid0) = q0
    stop, tgt = mid0 * (1 - stop_pct), mid0 * (1 + tgt_pct)
    out, why, te = None, "eod", C.at(k, EOD_MIN)
    last_bid = b0
    for m in mins:
        if m <= m0 or key not in ch[m]:
            continue
        b, a, mid = ch[m][key]
        last_bid = b
        if mid <= stop:
            out, why, te = b, "stop", C.at(k, 0) + m * 60
            break
        if mid >= tgt:
            out, why, te = b, "target", C.at(k, 0) + m * 60
            break
    if out is None:
        out = last_bid
    return {"ek": ek, "K": K, "in": a0, "out": max(out, C.TICK), "why": why, "te": te, "priced": "real"}


def replay(args) -> tuple[str, list]:
    sid, tf, k_from, k_to, use_real = args
    cls = G["REG"][sid]
    probe = cls(params={})
    style = G["CATS"].get(probe.metadata.category, G["CATS"]["options_intraday"])
    warm = probe.warmup
    bars, starts = G["bars"][tf], G["starts"][tf]
    out = []
    for k in G["days"]:
        if k < k_from or k > k_to:
            continue
        a = bisect_left(starts, C.at(k, 0))
        b = bisect_left(starts, C.at(k + 1, 0))
        if b - a < 3 or a < 50:
            continue
        strat = cls(params={})
        ctx = G["CTX"](max_bars=max(500, warm + 5))
        for bb in bars[max(0, a - 400):a]:
            ctx.push(bb)
        busy_until, n_today = 0, 0
        for j in range(a, b):
            ctx.push(bars[j])
            s = starts[j]
            end = min(s + TF_MIN[tf] * 60, C.at(k, 15 * 60 + 30))
            if end < busy_until or n_today >= 6 or len(ctx.bars) < warm:
                continue
            try:
                sg = strat.on_bar(ctx)
            except Exception:  # noqa: BLE001 - a strategy that throws simply gives no signal, as on the live desk
                sg = None
            if sg is None or sg.signal not in (G["ACT"].BUY, G["ACT"].SELL):
                continue
            if C.minute_of_day(s) >= EOD_MIN:
                continue
            call = sg.signal == G["ACT"].BUY
            S0 = bars[j].close
            r = None
            if use_real and k in G["chain"]:
                r = real_trade(k, end, S0, call, style["premium_stop_pct"], style["premium_target_pct"])
            if r is None:
                r = model_trade(k, end, S0, call, style["premium_stop_pct"], style["premium_target_pct"])
            if r is None:
                continue
            busy_until = r["te"]
            n_today += 1
            ch = C.charges(r["in"], r["out"], side="BUY")
            out.append([k, end, 1 if call else -1, round(S0, 2), r["K"], r["ek"], r["in"], r["out"], r["why"], r["te"],
                        round((r["out"] - r["in"]) * C.LOT - ch, 2), r["priced"]])
    return f"{sid}@{tf}", out


def stats(tr: list) -> dict:
    if not tr:
        return {"trades": 0, "net": 0.0}
    net = [t[10] for t in tr]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"trades": len(tr), "net": round(sum(net), 2), "win_rate": round(len(wins) / len(net) * 100, 1),
            "profit_factor": round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None,
            "avg": round(sum(net) / len(net), 2), "best": max(net), "worst": min(net), "max_dd": round(mdd, 2),
            "avg_premium": round(statistics.mean(t[6] for t in tr), 2),
            "net_real": round(sum(t[10] for t in tr if t[11] == "real"), 2),
            "trades_real": sum(1 for t in tr if t[11] == "real"),
            "exits": {w: sum(1 for t in tr if t[8] == w) for w in ("target", "stop", "eod")},
            "calls": sum(1 for t in tr if t[2] > 0)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    RES.mkdir(exist_ok=True)
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    pairs = sorted((sid, getattr(t, "value", str(t))) for sid, cls in STRATEGY_REGISTRY.items()
                   if "options_buying" in (getattr(cls, "__module__", "") or "")
                   for t in (cls.metadata.timeframes or []) if getattr(t, "value", str(t)) in TF_MIN)
    if limit:
        pairs = pairs[:limit]
    bl = blocks()
    C.set_calendar()
    kf, kt = C.dk(bl[0][0]), C.dk(bl[-1][1])
    t0 = time.time()
    with mp.Pool(workers, initializer=init_worker) as pool:
        # 1. the last month, real quotes where recorded
        last = dict(pool.map(replay, [(s, tf, C.dk(LAST_FROM), C.dk(LAST_TO), True) for s, tf in pairs]))
        print(f"last month replayed: {len(last)} pairs, {sum(len(v) for v in last.values())} trades, {time.time() - t0:.0f}s", flush=True)
        # 2. thirteen months, model prices throughout
        hist = dict(pool.map(replay, [(s, tf, kf, kt, False) for s, tf in pairs]))
        print(f"13 months replayed: {sum(len(v) for v in hist.values())} trades, {time.time() - t0:.0f}s", flush=True)
    rank = sorted(((name, stats(tr)) for name, tr in last.items()), key=lambda x: -x[1]["net"])
    # persistence: rank on block b, measure block b+1
    bk = [(C.dk(a), C.dk(b)) for a, b in bl]
    per_block = {name: [sum(t[10] for t in tr if a <= t[0] <= b) for a, b in bk] for name, tr in hist.items()}
    names = sorted(per_block)
    pers = []
    for i in range(len(bk) - 1):
        ranked = sorted(names, key=lambda n: -per_block[n][i])
        top, bottom = ranked[:20], ranked[-20:]
        nxt = [per_block[n][i + 1] for n in names]
        pers.append({"rank_on": [str(bl[i][0]), str(bl[i][1])], "test_on": [str(bl[i + 1][0]), str(bl[i + 1][1])],
                     "top20_in_rank_month": round(sum(per_block[n][i] for n in top), 2),
                     "top20_next_month": round(sum(per_block[n][i + 1] for n in top), 2),
                     "bottom20_next_month": round(sum(per_block[n][i + 1] for n in bottom), 2),
                     "all_avg_x20_next_month": round(statistics.mean(nxt) * 20, 2),
                     "top20_positive_next_month": sum(1 for n in top if per_block[n][i + 1] > 0)})
    model_last_rank = sorted(names, key=lambda n: -per_block[n][-1])
    out = {"window": [str(LAST_FROM), str(LAST_TO)], "pairs": len(pairs), "blocks": [[str(a), str(b)] for a, b in bl],
           "last_month": [{"name": n, **s} for n, s in rank],
           "last_month_model_only_top20": model_last_rank[:20],
           "persistence": pers,
           "positive_last_month": sum(1 for _, s in rank if s["net"] > 0),
           "runtime_s": round(time.time() - t0)}
    with open(RES / "summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    with gzip.open(HERE / "data" / "trades_last_month.json.gz", "wt") as g:
        json.dump(last, g)
    with gzip.open(HERE / "data" / "trades_13_months.json.gz", "wt") as g:
        json.dump(hist, g)
    print(f"positive last month: {out['positive_last_month']} of {len(rank)}")
    for i, (n, s) in enumerate(rank[:20], 1):
        print(f"{i:2}. {n:42} trades {s['trades']:3}  win {s['win_rate']:5.1f}%  net {s['net']:>10.0f}  PF {s['profit_factor']}  "
              f"maxDD {s['max_dd']:.0f}  real {s['trades_real']}/{s['trades']} {s['net_real']:.0f}")
    for p in pers:
        print(f"rank {p['rank_on']} -> test {p['test_on']}: top20 then {p['top20_in_rank_month']:>10.0f}  next {p['top20_next_month']:>10.0f}  "
              f"bottom20 next {p['bottom20_next_month']:>10.0f}  avg x20 next {p['all_avg_x20_next_month']:>10.0f}  "
              f"top20 up next: {p['top20_positive_next_month']}/20")


if __name__ == "__main__":
    main()
