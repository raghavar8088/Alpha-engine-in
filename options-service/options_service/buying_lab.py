"""Buying Lab v2 — the option-buying backtest rebuilt on what the Pre-Live audit measured
(2026-10-02). It replaces run_options_backtest's sweep as the way a buying strategy is judged.

WHAT WAS WRONG WITH THE OLD SWEEP
  - premiums from Black-Scholes at trailing REALIZED vol x 1.15 — the real NIFTY premiums the
    desk paid show that a VIX-based model with a calendar clock underprices expiry-day options
    by ~52% and that intraday decay runs much faster than calendar time charges;
  - it called the strategy on every bar, holding or not, and kept one instance for years —
    the live desk builds a fresh instance each morning and does not ask a strategy for a
    signal while it holds a position, so the backtest traded a different strategy;
  - it qualified on WIN RATE, which says nothing for options (a 38% win rate can make money
    and a 70% one lose it), with no allowance for testing 215 strategies at once;
  - lot 75 (NIFTY's lot is 65), no bid-ask spread.

THIS ENGINE
  Replay, exactly as the live desk runs (prelive-service): every session a FRESH strategy
  instance warmed on the last 400 bars of its timeframe (5m / 15m / 1h, session-anchored);
  asked for a signal at each bar close unless it holds a position; at most 6 trades a day; no
  entry on a bar starting at/after 15:15; BUY -> ATM CE, SELL -> ATM PE of the nearest weekly
  expiry (Thursday until Aug 2025, Tuesday from Sep 2025; holidays move it a session earlier);
  premium stop/target of its category checked on 5-minute bars (stop first when both), else
  15:15. Validated against the desk's real trades: per-strategy trade counts correlate 0.95.

  Premiums: Black-Scholes on a variance clock of trading minutes + 0.2 session per calendar
  night, IV = India VIX x a days-to-expiry ratio — both fitted on the desk's 5,800 real
  premiums (exit re-pricing unbiased to +-1.5% for 1-80 days to expiry; expiry day still
  overstates exits ~10%, i.e. flatters buyers, and is flagged). Month to month the model is
  only good to ~+-5-8% of an option's price — more than the edges being hunted — so a model
  backtest can FILTER, never ACCEPT. Costs: today's lot (65), a bid-ask spread of
  max(Rs0.05, 0.25% of premium) a side, Angel One's rate card at the trade date.

  THE GATE (all five): a strategy passes only if
    1. DIRECTION (needs no option price): the signed NIFTY move from entry to exit has
       t >= 2.0 on EXPLORE and t >= 1.0 with the same sign on HELD-OUT;
    2. Deflated Sharpe >= 0.95 over the full period, deflated for EVERY strategy in the run;
    3. CSCV probability of backtest overfitting <= 0.5 across the run;
    4. modelled net per trade > 0 on explore AND held-out;
    5. >= 100 explore trades and >= 30 held-out trades.
  Passing makes a strategy a CANDIDATE for pre-registration (forward paper on real
  premiums, option_hypotheses); the lab never puts anything into trading itself.
"""

from __future__ import annotations

import itertools
import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from statistics import NormalDist

from options_service.options_backtest import OPTION_BUYING_CATEGORIES
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe
from tradingai_shared.option_fees import option_round_trip

IST = timezone(timedelta(hours=5, minutes=30))
R = 0.065
LOT = 65
W_NIGHT = 0.2
IV_RATIO = {"0": 0.984, "1": 0.855, "2-6": 0.903, "7-20": 0.888, "21-40": 0.898, "80+": 0.908}
HALF_SPREAD_PCT = 0.0025
EXPLORE_END = date(2025, 12, 31)
TF_MIN = {"5m": 5, "15m": 15, "1h": 60}
GATE = {"direction_t_explore": 2.0, "direction_t_holdout": 1.0, "min_dsr": 0.95, "max_pbo": 0.5,
        "min_trades_explore": 100, "min_trades_holdout": 30}


def _mins(e: int) -> int:
    return ((e + 19800) % 86400) // 60


def _dkey(e: int) -> int:
    return (e + 19800) // 86400


def _kdate(k: int) -> date:
    return date(1970, 1, 1) + timedelta(days=k)


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S: float, K: float, T: float, sig: float, call: bool) -> float:
    if T <= 0 or sig <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (R + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * _ncdf(d1) - K * math.exp(-R * T) * _ncdf(d2) if call else K * math.exp(-R * T) * _ncdf(-d2) - S * _ncdf(-d1)


def _bucket(dte: int) -> str:
    return "0" if dte == 0 else "1" if dte == 1 else "2-6" if dte <= 6 else "7-20" if dte <= 20 else "21-40" if dte <= 40 else "80+"


class Market:
    """NIFTY 5m/15m bars and India VIX 15m, as [[epoch, o, h, l, c], ...] (bar start times)."""

    def __init__(self, n5: list, n15: list, vix15: list):
        self.n5, self.n15, self.vix = n5, n15, vix15
        self.t5 = [r[0] for r in n5]
        self.tv = [r[0] for r in vix15]
        self.days = sorted({_dkey(r[0]) for r in n5})
        self.dayset = set(self.days)
        self.rows = {"5m": n5, "15m": n15, "1h": self._agg_1h(n15)}
        self.starts = {tf: [r[0] for r in rows] for tf, rows in self.rows.items()}
        self.bars = {tf: [Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=datetime.fromtimestamp(r[0], IST),
                              open=r[1], high=r[2], low=r[3], close=r[4], volume=0) for r in rows]
                     for tf, rows in self.rows.items()}

    @staticmethod
    def _agg_1h(rows15: list) -> list:
        out, cur = [], None
        for r in rows15:
            k, m = _dkey(r[0]), _mins(r[0])
            key = (k, (m - 555) // 60)
            if cur is None or cur[0] != key:
                if cur:
                    out.append(cur[1])
                cur = (key, [k * 86400 - 19800 + (555 + key[1] * 60) * 60, r[1], r[2], r[3], r[4]])
            else:
                c = cur[1]
                c[2], c[3], c[4] = max(c[2], r[2]), min(c[3], r[3]), r[4]
        if cur:
            out.append(cur[1])
        return out

    def is_td(self, k: int) -> bool:
        return k in self.dayset if k <= self.days[-1] else _kdate(k).weekday() < 5

    def expiry(self, k: int) -> int:
        """Nearest weekly NIFTY expiry on/after day k (holiday -> the session before)."""
        d = _kdate(k)
        wd = 1 if d >= date(2025, 9, 1) else 3
        x = d
        while x.weekday() != wd:
            x += timedelta(days=1)
        xk = (x - date(1970, 1, 1)).days
        while not self.is_td(xk):
            xk -= 1
        return xk if xk >= k else self.expiry(k + 1)

    def T(self, e: int, xk: int) -> float:
        """Years on the fitted variance clock from epoch e to 15:30 of expiry day xk."""
        k, m = _dkey(e), _mins(e)
        if k > xk:
            return 1e-6
        today = max(0, 930 - max(m, 555))
        if k == xk:
            return max(today, 1) / ((252 + 365 * W_NIGHT) * 375)
        lo = bisect_right(self.days, k)
        hi = bisect_right(self.days, min(xk, self.days[-1]))
        full = (hi - lo) + sum(1 for j in range(max(k + 1, self.days[-1] + 1), xk + 1) if _kdate(j).weekday() < 5)
        mins = today + 375 * full + W_NIGHT * 375 * (xk - k)
        return mins / ((252 + 365 * W_NIGHT) * 375)

    def vix_at(self, e: int) -> float | None:
        i = bisect_right(self.tv, e - 900) - 1
        return self.vix[i][4] / 100 if i >= 0 and e - self.tv[i] < 86400 * 5 else None

    def spot_before(self, e: int) -> float | None:
        i = bisect_right(self.t5, e - 300) - 1
        return self.n5[i][4] if i >= 0 else None

    def price(self, e: int, S: float, K: float, call: bool, xk: int) -> float | None:
        v = self.vix_at(e)
        if not v:
            return None
        return bs(S, K, self.T(e, xk), v * IV_RATIO[_bucket(xk - _dkey(e))], call)


def _half(px: float) -> float:
    return max(0.05, px * HALF_SPREAD_PCT)


def simulate_option(mk: Market, e0: int, s0: float, side: int, stop_pct: float, tgt_pct: float) -> dict | None:
    """One ATM option bought at e0 (paper at the model mid; real at mid + half spread) and
    managed on 5-minute bars to its premium stop/target or 15:15."""
    k = _dkey(e0)
    xk = mk.expiry(k)
    call = side > 0
    K = round(s0 / 50) * 50
    p0 = mk.price(e0, s0, K, call, xk)
    if not p0 or p0 < 1:
        return None
    stop, tgt = p0 * (1 - stop_pct), p0 * (1 + tgt_pct)
    eod = k * 86400 - 19800 + 915 * 60
    a = bisect_left(mk.t5, e0)
    b = bisect_left(mk.t5, (k + 1) * 86400 - 19800)
    exit_e, p1, why = None, None, "eod"
    for r in mk.n5[a:b]:
        if r[0] >= eod:
            break
        te = r[0] + 300
        worst = mk.price(te, r[3] if call else r[2], K, call, xk)
        best = mk.price(te, r[2] if call else r[3], K, call, xk)
        if worst is not None and worst <= stop:
            exit_e, p1, why = te, stop, "stop"
            break
        if best is not None and best >= tgt:
            exit_e, p1, why = te, tgt, "target"
            break
    if exit_e is None:
        exit_e = eod
        s1 = mk.spot_before(eod)
        p1 = mk.price(eod, s1, K, call, xk) or 0.0
    s1 = mk.spot_before(exit_e) or s0
    on = _kdate(k)
    real_in, real_out = p0 + _half(p0), max(0.05, p1 - _half(p1))
    net = (real_out - real_in) * LOT - option_round_trip(real_in, real_out, LOT, on=on)["total"]
    return {"k": k, "e": e0, "x": exit_e, "side": side, "dte": xk - k, "p0": p0, "p1": p1, "why": why,
            "net": round(net, 2), "move_bp": side * (s1 / s0 - 1) * 1e4}


def replay(mk: Market, strategy_id: str, tf: str) -> list[dict]:
    """The live desk's rules, bar by bar, for one strategy on one timeframe."""
    cls = STRATEGY_REGISTRY[strategy_id]
    probe = cls(params={})
    style = OPTION_BUYING_CATEGORIES.get(probe.metadata.category, OPTION_BUYING_CATEGORIES["options_intraday"])
    bars, starts = mk.bars[tf], mk.starts[tf]
    out = []
    for k in mk.days:
        a = bisect_left(starts, k * 86400 - 19800)
        b = bisect_left(starts, (k + 1) * 86400 - 19800)
        if b - a < 3 or a < 50:
            continue
        strat = cls(params={})
        ctx = StrategyContext(max_bars=max(500, probe.warmup + 5))
        for bb in bars[max(0, a - 400):a]:
            ctx.push(bb)
        busy_until, n_today = 0, 0
        for j in range(a, b):
            ctx.push(bars[j])
            s = starts[j]
            end = min(s + TF_MIN[tf] * 60, k * 86400 - 19800 + 930 * 60)
            if end < busy_until or n_today >= 6 or len(ctx.bars) < probe.warmup:
                continue
            try:
                sg = strat.on_bar(ctx)
            except Exception:  # noqa: BLE001 - a rule error is a non-signal
                sg = None
            if sg is None or sg.signal not in (SignalAction.BUY, SignalAction.SELL) or _mins(s) >= 915:
                continue
            tr = simulate_option(mk, end, bars[j].close, 1 if sg.signal == SignalAction.BUY else -1,
                                 style["premium_stop_pct"], style["premium_target_pct"])
            if tr is None:
                continue
            busy_until = tr["x"]
            n_today += 1
            out.append(tr)
    return out


# ── statistics ───────────────────────────────────────────────────────────────────


def _t(xs: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


def deflated_sharpe(daily: list[float], sr_var: float, n_trials: int) -> float | None:
    if len(daily) < 30 or n_trials < 2:
        return None
    n = len(daily)
    m = statistics.mean(daily)
    sd = statistics.pstdev(daily)
    if not sd:
        return None
    sr = m / sd
    g3 = sum(((x - m) / sd) ** 3 for x in daily) / n
    g4 = sum(((x - m) / sd) ** 4 for x in daily) / n
    nd, eul = NormalDist(), 0.5772156649
    sr0 = math.sqrt(max(sr_var, 0.0)) * ((1 - eul) * nd.inv_cdf(1 - 1 / n_trials) + eul * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    return nd.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(den)) if den > 0 else None


def pbo_cscv(matrix: list[list[float]], blocks: int = 16) -> float | None:
    """matrix[strategy][day] -> probability the in-sample best is below median out of sample."""
    import numpy as np
    M = np.array(matrix, dtype=float).T
    T, N = M.shape
    if T < blocks * 5 or N < 2:
        return None
    size = T // blocks
    bs_ = np.array([M[b * size:(b + 1) * size].sum(0) for b in range(blocks)])
    bq = np.array([(M[b * size:(b + 1) * size] ** 2).sum(0) for b in range(blocks)])
    below = total = 0
    for combo in itertools.combinations(range(blocks), blocks // 2):
        sel = np.zeros(blocks, bool)
        sel[list(combo)] = True

        def sr(mask):
            cnt = size * mask.sum()
            mu = bs_[mask].sum(0) / cnt
            var = np.maximum((bq[mask].sum(0) - cnt * mu * mu) / (cnt - 1), 1e-18)
            return mu / np.sqrt(var)
        a, o = sr(sel), sr(~sel)
        best = int(np.argmax(a))
        rank = (o <= o[best]).sum() / (N + 1)
        below += 1 if rank <= 0.5 else 0
        total += 1
    return below / total


def evaluate(results: dict[str, list[dict]], days: list[int]) -> dict:
    """The gate over one run: per-strategy records, then DSR/PBO across the run."""
    rows, daily = {}, {}
    for key, trades in results.items():
        ex = [t for t in trades if _kdate(t["k"]) <= EXPLORE_END]
        ho = [t for t in trades if _kdate(t["k"]) > EXPLORE_END]
        d = dict.fromkeys(days, 0.0)
        for t in trades:
            d[t["k"]] = d.get(t["k"], 0.0) + t["net"]
        daily[key] = [d[k] for k in days]

        def stats(xs):
            if not xs:
                return {"trades": 0}
            mv = [t["move_bp"] for t in xs]
            return {"trades": len(xs), "net_per_trade": round(statistics.mean(t["net"] for t in xs), 2),
                    "net": round(sum(t["net"] for t in xs), 2),
                    "direction_hit": round(sum(1 for x in mv if x > 0) / len(mv), 4),
                    "direction_mean_bp": round(statistics.mean(mv), 3),
                    "direction_t": round(_t(mv), 3) if _t(mv) is not None else None,
                    "expiry_day_share": round(sum(1 for t in xs if t["dte"] == 0) / len(xs), 3)}
        rows[key] = {"key": key, "explore": stats(ex), "holdout": stats(ho), "all": stats(trades)}
    keys = list(rows)
    srs = []
    for kk in keys:
        ser = daily[kk]
        sd = statistics.pstdev(ser)
        srs.append(statistics.mean(ser) / sd if sd else 0.0)
    sr_var = statistics.pvariance(srs) if len(srs) > 1 else 0.0
    pbo = pbo_cscv([daily[kk] for kk in keys]) if len(keys) > 1 else None
    passed = []
    for kk in keys:
        r = rows[kk]
        r["dsr"] = deflated_sharpe(daily[kk], sr_var, len(keys))
        e, h = r["explore"], r["holdout"]
        et, ht = e.get("direction_t"), h.get("direction_t")
        checks = {
            "direction": bool(et is not None and ht is not None and et >= GATE["direction_t_explore"]
                              and ht >= GATE["direction_t_holdout"]),
            "deflated_sharpe": bool(r["dsr"] is not None and r["dsr"] >= GATE["min_dsr"]),
            "pbo": bool(pbo is not None and pbo <= GATE["max_pbo"]),
            "net_both_periods": bool((e.get("net_per_trade") or -1) > 0 and (h.get("net_per_trade") or -1) > 0),
            "trades": bool(e.get("trades", 0) >= GATE["min_trades_explore"] and h.get("trades", 0) >= GATE["min_trades_holdout"]),
        }
        r["gate"] = checks
        r["passed"] = all(checks.values())
        if r["passed"]:
            passed.append(kk)
        if r["dsr"] is not None:
            r["dsr"] = round(r["dsr"], 4)
    n20 = [rows[kk] for kk in keys if rows[kk]["all"].get("trades", 0) >= 20]
    return {"rows": rows, "passed": passed, "pbo": pbo, "trials": len(keys), "gate": GATE,
            "luck": {"strategies": len(n20), "direction_t_above_2_expected_by_chance": round(len(n20) * 0.02275, 1),
                     "direction_t_above_2_observed": sum(1 for r in n20 if (r["all"].get("direction_t") or 0) > 2)},
            "model": {"clock": f"trading minutes + {W_NIGHT} session per calendar night", "iv_over_vix": IV_RATIO,
                      "half_spread_pct": HALF_SPREAD_PCT, "lot": LOT, "explore_end": EXPLORE_END.isoformat()}}


def buying_pairs() -> list[tuple[str, str]]:
    import strategy_service.strategies.options_buying  # noqa: F401 - registers the library
    out = []
    for sid, cls in STRATEGY_REGISTRY.items():
        if "options_buying" not in (getattr(cls, "__module__", "") or ""):
            continue
        for tfv in [getattr(t, "value", str(t)) for t in (cls.metadata.timeframes or [])]:
            if tfv in TF_MIN:
                out.append((sid, tfv))
    return sorted(out)
