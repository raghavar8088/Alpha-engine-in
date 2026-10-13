"""Replay the DAILY option-buying rules on BANKNIFTY at REAL option prices (NSE closes).

Rules: the library's 48 daily swing strategies (strategy_service options_buying, 1d) and the 16
daily rules in app/services/banknifty_strategies.py.

Each session k the rule decides at 15:20 from daily bars whose last bar is TODAY UP TO 15:20
(the 15:15-15:20 bar's close is today's "close"), so the day's real close is never seen before
deciding. What it wants to hold ("CE", "PE", "STRADDLE", nothing) is bought/sold at session k's
REAL closing premium (bhavcopy) of the exact contract, plus/minus the half spread, with Angel's
charges per leg:
  contract  nearest monthly with >= 15 sessions left; ATM strike by the 15:20 price; it must
            have traded >= 20 contracts that day to be bought (an untraded close is stale)
  exits     the rule changes its mind; premium stop / target on CLOSES (the library's swing
            category: -40% / +80%; the custom rules set their own); max holding; and a roll
            when the contract has <= 3 sessions left (re-bought in the next monthly if the rule
            still wants it)
Output: results/swing/<rule>.json, one row per closed trade.
"""

import gzip
import json
import math
import os
import sys
import time
from bisect import bisect_left
from datetime import date
from multiprocessing import Pool

import bn_common as C

sys.path.insert(0, os.path.join(C.REPO, "backend"))
from app.services import banknifty_strategies as B  # noqa: E402

OUT = os.path.join(C.DATA, "results", "swing")
MIN_SWING_LEFT = 15
ROLL_AT_LEFT = 3
MIN_TRADED = 20
G: dict = {}


def init_worker():
    import strategy_service.strategies.options_buying  # noqa: F401  (fills the registry in each worker)
    bn = C.Sessions("NIFTYBANK", start=date(2015, 1, 1))
    C.set_trading_days(bn.all_days)
    with gzip.open(os.path.join(C.DATA, "closes.json.gz"), "rt") as f:
        closes = {int(k): {int(e): v for e, v in d.items()} for k, d in json.load(f).items()}
    with gzip.open(os.path.join(C.DATA, "surface.json.gz"), "rt") as f:
        surf = {int(k): {int(e): v for e, v in s.items()} for k, s in json.load(f).items()}
    daily = []
    for k in bn.days:
        bars = bn.bars[k]
        dec = [b for b in bars if C.minute(int(b[0])) + 5 <= B.DAILY_DECISION_MIN]
        daily.append({"k": k, "o": bars[0][1], "h": max(b[2] for b in bars), "l": min(b[3] for b in bars), "c": bars[-1][4],
                      "dh": max(b[2] for b in dec), "dl": min(b[3] for b in dec), "dc": dec[-1][4]})
    events = sorted({C.dk(date.fromisoformat(x)) for x in B.RBI_POLICY + B.UNION_BUDGET})
    G.update(bn=bn, closes=closes, surf=surf, daily=daily, events=events)


def event_session(ek: int) -> int | None:
    """The session that reacts to an event dated ek (the event day if NSE trades, else the next)."""
    days = G["bn"].all_days
    i = bisect_left(days, ek)
    return days[i] if i < len(days) else None


def sessions_to_event(k: int) -> int | None:
    days = G["bn"].all_days
    i = bisect_left(days, k)
    for ev in G["events"]:
        es = event_session(ev)
        if es is None or es < k:
            continue
        j = bisect_left(days, es)
        n = j - i
        return n if n <= 10 else None
    return None


def contract(k: int, S: float, kind: str) -> tuple | None:
    cl = G["closes"].get(k)
    if not cl:
        return None
    for ek in sorted(cl):
        if C.trading_sessions_left(k, ek) < MIN_SWING_LEFT:
            continue
        K = round(S / C.STEP) * C.STEP
        row = cl[ek].get(str(float(K)))
        if not row:
            return None
        legs = [("CE", 0, 2), ("PE", 1, 3)] if kind == "STRADDLE" else [(kind, 0 if kind == "CE" else 1, 2 if kind == "CE" else 3)]
        px = []
        for typ, i, n in legs:
            if row[i] <= 0 or row[n] < MIN_TRADED:
                return None
            px.append((typ, row[i]))
        return ek, K, px
    return None


def mark(k: int, ek: int, K: float, typ: str) -> float | None:
    row = G["closes"].get(k, {}).get(ek, {}).get(str(float(K)))
    if not row:
        return None
    v = row[0] if typ == "CE" else row[1]
    return v if v > 0 else None


def close_trade(pos, k, why, dec_price):
    pnl, legs_out = 0.0, []
    for typ, p_in in pos["legs"]:
        p_out = mark(k, pos["ek"], pos["K"], typ)
        if p_out is None:   # strike now > 10% from the money (not kept) or no close: worth its intrinsic value
            p_out = max(0.05, (dec_price - pos["K"]) if typ == "CE" else (pos["K"] - dec_price))
        pnl += C.net_pnl(p_in, p_out)
        legs_out.append([typ, round(p_in, 2), round(p_out, 2)])
    move = (dec_price / pos["S0"] - 1) * 1e4
    fav = move if pos["kind"] == "CE" else -move if pos["kind"] == "PE" else abs(move)
    return [pos["k0"], k, pos["kind"], C.trading_sessions_left(pos["k0"], pos["ek"]), round(pos["S0"], 2), pos["K"],
            legs_out, why, C.trading_sessions_left(pos["k0"], k) - 1, round(pnl, 2), round(fav, 2)]


def run_rule(name, decide, stop_pct, target_pct, max_hold):
    """decide(i, holding, age) -> wanted kind or None, called once a session at 15:20."""
    daily = G["daily"]
    k0 = C.dk(C.RESEARCH_START)
    pos, out = None, []
    for i, d in enumerate(daily):
        k = d["k"]
        want = decide(i, pos["kind"] if pos else None, (C.trading_sessions_left(pos["k0"], k) - 1) if pos else 0)
        if k < k0:
            continue
        if pos:
            why = None
            vals = [(mark(k, pos["ek"], pos["K"], typ), p_in) for typ, p_in in pos["legs"]]
            if all(v is not None for v, _ in vals):
                ret = sum(v for v, _ in vals) / sum(p for _, p in vals) - 1
                if stop_pct is not None and ret <= -stop_pct:
                    why = "stop"
                elif target_pct is not None and ret >= target_pct:
                    why = "target"
            age = C.trading_sessions_left(pos["k0"], k) - 1
            if why is None and want != pos["kind"]:
                why = "signal"
            if why is None and age >= max_hold:
                why = "max_hold"
            if why is None and C.trading_sessions_left(k, pos["ek"]) <= ROLL_AT_LEFT:
                why = "roll"
            if why:
                out.append(close_trade(pos, k, why, d["dc"]))
                pos = None
                if why in ("stop", "target", "max_hold"):
                    continue                     # not re-entered on the session it was closed
        if pos is None and want:
            c = contract(k, d["dc"], want)
            if c:
                ek, K, legs = c
                pos = {"k0": k, "ek": ek, "K": K, "kind": want, "legs": legs, "S0": d["dc"]}
    return out


def library_rule(sid):
    from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
    from tradingai_shared.domain import Bar, SignalAction, Timeframe
    cls = STRATEGY_REGISTRY[sid]
    strat = cls(params={})
    ctx = StrategyContext(max_bars=max(600, strat.warmup + 5))
    daily = G["daily"]
    state = {"want": None}

    def bar(d, partial):
        return Bar.model_construct(symbol="BANKNIFTY", timeframe=Timeframe("1d"), ts=C.ist(C.at(d["k"], C.OPEN_MIN)),
                                   open=d["o"], high=d["dh"] if partial else d["h"], low=d["dl"] if partial else d["l"],
                                   close=d["dc"] if partial else d["c"], volume=0, oi=None)

    def decide(i, holding, age):
        ctx.push(bar(daily[i], True))
        sg = None
        if len(ctx.bars) >= strat.warmup:
            try:
                sg = strat.on_bar(ctx)
            except Exception:
                sg = None
        ctx.bars[-1] = bar(daily[i], False)          # tomorrow sees the full day
        if sg is not None:
            if sg.signal == SignalAction.BUY:
                state["want"] = "CE"
            elif sg.signal == SignalAction.SELL:
                state["want"] = "PE"
            elif sg.signal in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT):
                state["want"] = None
        return state["want"]

    return decide


def custom_rule(rule):
    daily = G["daily"]

    def decide(i, holding, age):
        k = daily[i]["k"]
        days = [B.DailyBar(d["k"], d["o"], d["h"], d["l"], d["c"]) for d in daily[max(0, i - 260):i]]
        t = daily[i]
        days.append(B.DailyBar(k, t["o"], t["dh"], t["dl"], t["dc"]))
        ctx = {"holding": holding, "age": age, "sessions_to_event": sessions_to_event(k)}
        s = G["surf"].get(k)
        if s:
            fronts = [ek for ek in sorted(s) if C.trading_sessions_left(k, ek) >= MIN_SWING_LEFT]
            if fronts:
                # variance-clock vol -> annualised trading-day vol (what 20-day realised vol is in):
                # sigma_vc^2 * T_vc = sigma_td^2 * T_td
                ek0 = fronts[0]
                t_vc = s[ek0][1] / C.SESS_PER_YEAR
                t_td = C.trading_sessions_left(k, ek0) / 252
                ctx["atm_iv"] = s[ek0][2] * math.sqrt(t_vc / t_td) if t_td > 0 else None
        return rule.target(days, ctx)

    return decide


def replay(name):
    path = os.path.join(OUT, f"{name}.json")
    if os.path.exists(path):
        return name, -1, 0.0
    t0 = time.time()
    customs = {r.id: r for r in B.daily_rules()}
    if name in customs:
        r = customs[name]
        trades = run_rule(name, custom_rule(r), r.stop_pct, r.target_pct, r.max_hold)
        meta = {"family": r.family, "label": r.label, "params": r.params}
    else:
        trades = run_rule(name, library_rule(name), 0.40, 0.80, 60)
        meta = {"family": "Library swing", "label": name, "params": {}}
    with open(path + ".tmp", "w") as f:
        json.dump({"sid": name, "tf": "1d", **meta,
                   "cols": ["k", "k_exit", "kind", "sessions_left", "S0", "K", "legs", "why", "held", "net", "fav_bp"],
                   "trades": trades}, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    return name, len(trades), time.time() - t0


def names():
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    lib = sorted(sid for sid, cls in STRATEGY_REGISTRY.items()
                 if "options_buying" in (getattr(cls, "__module__", "") or "")
                 and any(getattr(t, "value", str(t)) == "1d" for t in (cls.metadata.timeframes or [])))
    return lib + [r.id for r in B.daily_rules()]


def main():
    os.makedirs(OUT, exist_ok=True)
    ns = names()
    if len(sys.argv) > 1:
        ns = [n for n in ns if any(a in n for a in sys.argv[1:])]
    nproc = int(os.environ.get("BN_PROCS", "10"))
    print(f"{len(ns)} daily rules on {nproc} processes", flush=True)
    t0 = time.time()
    with Pool(nproc, initializer=init_worker) as pool:
        for n, (name, ntr, secs) in enumerate(pool.imap_unordered(replay, ns), 1):
            print(f"{n}/{len(ns)} {name}: {ntr} trades {secs:.0f}s (wall {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    import strategy_service.strategies.options_buying  # noqa: F401
    main()
