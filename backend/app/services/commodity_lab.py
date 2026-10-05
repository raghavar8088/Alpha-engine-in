"""Commodity Lab (C4) — the only door from research to the Pre-Live Commodity desk and to
real money. Replaces the pattern desk's READY verdict.

WHAT A CANDIDATE MUST SHOW (all of it, on 2004-2026 daily history in rupees, after MCX
costs, rolls and the cost of carry — see commodity_lab_data):
  1. net positive in BOTH the explore period (2004-2015) and the held-out one (2016-);
  2. Deflated Sharpe >= 0.95, deflated for EVERY trial ever registered (`commodity_lab_trials`
     — the count only grows; adding variants raises everyone's bar);
  3. PBO <= 0.5 — the probability, by combinatorially symmetric cross-validation over the
     whole trial set, that the in-sample best is below the median out of sample;
  4. it beats ALWAYS-LONG on the same commodities: higher held-out Sharpe AND a full-period
     alpha t >= 2 against the long-only portfolio. 2016-2026 was a bull market in metals;
     a rule that is mostly long rode it, it did not time it;
  5. whole-lot feasibility: at least 3 of its 5 legs tradable in whole lots of the smallest
     liquid MCX contract at the book's capital and volatility budget.
Then INCUBATING: it may trade on the Pre-Live Commodity desk (paper, real fills). After
>= 60 MCX sessions of incubation with a positive real-money P&L it is CONFIRMED — the only
verdict the real-money executor accepts. 60 sessions with a loss: REJECTED_IN_INCUBATION.

TRIALS. Four classic trend rules (TS12, TS3, MA 50/200, Donchian 50/20) on each commodity,
on spot energy, and as two equal-risk portfolios; and each of the desk's daily pattern
templates on the five commodities. Pre-registered hypotheses (commodity_hypotheses) are
reported here too, but their verdicts are set by their own pre-registered rules.

Run as a job (it is CPU-bound for a couple of minutes):
    python -m app.services.commodity_lab_job
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from itertools import combinations
from statistics import NormalDist

from app.core.db import db
from app.services import commodity_lab_data as data

logger = logging.getLogger("commodity_lab")

lab_verdicts_collection = db["commodity_lab_verdicts"]
lab_runs_collection = db["commodity_lab_runs"]
lab_trials_collection = db["commodity_lab_trials"]

BOOK_CAPITAL = float(os.getenv("COMMODITY_LAB_BOOK_CAPITAL", "5000000"))
VOL_TARGET = 0.10
DSR_MIN = 0.95
PBO_MAX = 0.5
ALPHA_T_MIN = 2.0
INCUBATION_SESSIONS = 60
MIN_FEASIBLE_LEGS = 3
PBO_BLOCKS = 10
TREND_RULES = ("TS12", "TS3", "MA", "DON")


# ── rules ────────────────────────────────────────────────────────────────────────


def rule_positions(closes: list[tuple[date, float]], rule: str) -> list[float]:
    n = len(closes)
    pos = [0.0] * n
    if rule == "LONG":
        return [1.0] * n
    if rule in ("TS12", "TS3"):
        lb = 252 if rule == "TS12" else 63
        cur = 0.0
        for i in range(n):
            if i >= lb and (i == lb or closes[i][0].month != closes[i - 1][0].month):
                cur = 1.0 if closes[i][1] > closes[i - lb][1] else -1.0
            pos[i] = cur
    elif rule == "MA":
        run = [0.0]
        for _d, c in closes:
            run.append(run[-1] + c)
        for i in range(200, n):
            m50 = (run[i + 1] - run[i - 49]) / 50
            m200 = (run[i + 1] - run[i - 199]) / 200
            pos[i] = 1.0 if m50 > m200 else -1.0
    elif rule == "DON":
        cur = 0.0
        for i in range(55, n):
            w50 = [c for _d, c in closes[i - 50:i]]
            w20 = w50[-20:]
            c = closes[i][1]
            if cur <= 0 and c > max(w50):
                cur = 1.0
            elif cur >= 0 and c < min(w50):
                cur = -1.0
            elif cur > 0 and c < min(w20):
                cur = 0.0
            elif cur < 0 and c > max(w20):
                cur = 0.0
            pos[i] = cur
    return pos


def run_rule(closes: list[tuple[date, float]], key: str, rule: str) -> dict[date, float]:
    """Daily net return of `rule` on one series: vol-targeted to 10% a year (60-day vol,
    capped 3x), decided at the previous close, charged costs, rolls and carry."""
    pos = rule_positions(closes, rule)
    rets = [0.0] + [closes[i][1] / closes[i - 1][1] - 1 for i in range(1, len(closes))]
    rolls = data.ROLLS_PER_YEAR.get(key.replace("_SPOT", ""), 12)
    out: dict[date, float] = {}
    w_prev = 0.0
    for i in range(61, len(closes)):
        d = closes[i][0]
        vol = statistics.pstdev(rets[i - 60:i]) * math.sqrt(252)
        w = min(VOL_TARGET / vol, 3.0) if vol > 0 else 0.0
        target = pos[i - 1] * w
        cost = abs(target - w_prev) * data.COST_SIDE + abs(target) * data.ROLL_COST * rolls / 252
        out[d] = target * rets[i] - cost - target * data.carry_rate(key, d) / 252
        w_prev = target
    return out


def monthly(daily: dict[date, float]) -> dict[str, float]:
    m: dict[str, float] = defaultdict(float)
    for d, v in daily.items():
        m[f"{d.year:04d}-{d.month:02d}"] += v
    return dict(m)


def portfolio(series: list[dict]) -> dict:
    keys = set.intersection(*[set(s) for s in series]) if series else set()
    return {k: sum(s[k] for s in series) / len(series) for k in sorted(keys)}


# ── pattern templates on daily bars ──────────────────────────────────────────────


class _Bar:
    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, r):
        d, self.open, self.high, self.low, self.close, self.volume = r
        self.ts = datetime(d.year, d.month, d.day)


def replay_template(spec, ohlc: list[tuple], key: str) -> list[tuple[date, float]]:
    """(exit date, net return) per trade: signal on the close, entry next open, the
    template's own target/stop (stop first when both print in a day), else 60 bars; costs,
    rolls and carry for the days held."""
    from app.services.commodity_patterns import evaluate

    bars = [_Bar(r) for r in ohlc]
    rolls = data.ROLLS_PER_YEAR[key]
    trades = []
    i = 250
    while i < len(bars) - 1:
        sig = evaluate(spec, bars[i - 250:i + 1])
        if sig is None:
            i += 1
            continue
        j = i + 1
        entry = bars[j].open
        ratio = entry / sig.entry
        tgt, stp = sig.target * ratio, sig.stoploss * ratio
        side = 1 if sig.side == "BUY" else -1
        exit_px, k = None, j
        for k in range(j, min(j + 60, len(bars))):
            b = bars[k]
            if (b.low <= stp) if side > 0 else (b.high >= stp):
                exit_px = stp if (side > 0 and b.open > stp) or (side < 0 and b.open < stp) else b.open
                break
            if (b.high >= tgt) if side > 0 else (b.low <= tgt):
                exit_px = tgt if (side > 0 and b.open < tgt) or (side < 0 and b.open > tgt) else b.open
                break
        if exit_px is None:
            exit_px = bars[k].close
        held = k - j + 1
        d_exit = bars[k].ts.date()
        net = (side * (exit_px / entry - 1) - 2 * data.COST_SIDE - data.ROLL_COST * rolls / 252 * held
               - side * data.carry_rate(key, d_exit) * held / 252)
        trades.append((d_exit, net))
        i = k + 1
    return trades


# ── statistics ───────────────────────────────────────────────────────────────────


def period_stats(m: dict[str, float], lo: str, hi: str) -> dict:
    xs = [v for k, v in sorted(m.items()) if lo <= k <= hi]
    if len(xs) < 12:
        return {"months": len(xs)}
    mean, sd = statistics.mean(xs), statistics.pstdev(xs)
    eq = peak = mdd = 0.0
    for v in xs:
        eq += v
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"months": len(xs), "ann_ret_pct": round(mean * 12 * 100, 2),
            "sharpe": round(mean / sd * math.sqrt(12), 3) if sd else None,
            "t": round(mean / (sd / math.sqrt(len(xs))), 2) if sd else None, "max_dd_pct": round(mdd * 100, 1)}


def deflated_sharpe(xs: list[float], sr_var: float, n_trials: int) -> float | None:
    """Bailey & Lopez de Prado. Per-period Sharpe against the expected max of n_trials
    zero-skill Sharpes, adjusted for skew and kurtosis."""
    if len(xs) < 24 or n_trials < 2:
        return None
    m, sd = statistics.mean(xs), statistics.pstdev(xs)
    if not sd:
        return None
    sr = m / sd
    nd, eul = NormalDist(), 0.5772156649
    sr0 = math.sqrt(max(sr_var, 0.0)) * ((1 - eul) * nd.inv_cdf(1 - 1 / n_trials)
                                         + eul * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    k = len(xs)
    g3 = sum(((x - m) / sd) ** 3 for x in xs) / k
    g4 = sum(((x - m) / sd) ** 4 for x in xs) / k
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    return nd.cdf((sr - sr0) * math.sqrt(k - 1) / math.sqrt(den)) if den > 0 else None


def pbo_cscv(matrix: dict[str, dict[str, float]], months: list[str], blocks: int = PBO_BLOCKS) -> dict:
    """Probability of backtest overfitting over the whole trial set (CSCV)."""
    names = [k for k, v in matrix.items() if v]
    if len(names) < 4 or len(months) < blocks * 6:
        return {"pbo": None, "note": "too few trials or months"}
    size = len(months) // blocks
    parts = [months[b * size:(b + 1) * size] for b in range(blocks)]
    stats = {n: [] for n in names}               # per block: (count, sum, sumsq)
    for n in names:
        s = matrix[n]
        for p in parts:
            xs = [s.get(m, 0.0) for m in p]
            stats[n].append((len(xs), sum(xs), sum(x * x for x in xs)))

    def sharpe(n, idx):
        c = sum(stats[n][i][0] for i in idx)
        sm = sum(stats[n][i][1] for i in idx)
        sq = sum(stats[n][i][2] for i in idx)
        mean = sm / c
        var = sq / c - mean * mean
        return mean / math.sqrt(var) if var > 0 else 0.0

    logits = []
    allb = set(range(blocks))
    for is_idx in combinations(range(blocks), blocks // 2):
        oos_idx = tuple(sorted(allb - set(is_idx)))
        best = max(names, key=lambda n: sharpe(n, is_idx))
        oos = sorted(names, key=lambda n: sharpe(n, oos_idx))
        rank = oos.index(best) + 1
        w = rank / (len(names) + 1)
        logits.append(math.log(w / (1 - w)))
    return {"pbo": round(sum(1 for x in logits if x <= 0) / len(logits), 3), "combinations": len(logits),
            "trials": len(names), "blocks": blocks}


def alpha_vs(y: dict[str, float], x: dict[str, float]) -> dict:
    keys = sorted(set(y) & set(x))
    if len(keys) < 36:
        return {"alpha_t": None}
    ys, xs = [y[k] for k in keys], [x[k] for k in keys]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    beta = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sxx if sxx else 0.0
    alpha = my - beta * mx
    resid = [b - alpha - beta * a for a, b in zip(xs, ys)]
    s2 = sum(r * r for r in resid) / (len(keys) - 2)
    se = math.sqrt(s2 * (1 / len(keys) + mx * mx / sxx)) if sxx else None
    return {"alpha_ann_pct": round(alpha * 12 * 100, 2), "beta": round(beta, 3),
            "alpha_t": round(alpha / se, 2) if se else None}


# ── feasibility ──────────────────────────────────────────────────────────────────


async def feasibility(hist: data.History, capital: float = BOOK_CAPITAL) -> dict:
    """Per commodity: the smallest liquid contract, its lot value at today's MCX price,
    the notional the 10% vol budget allows at `capital`, and the whole lots that makes."""
    from app.services import mcx_market
    from app.services.mcx_risk import SMALLEST, lot_value, whole_lots

    out = {}
    want = sorted({c for k in data.COMMODITIES for c in SMALLEST[data.FAMILY_OF[k]]})
    uni = await mcx_market.tradable_universe(want)
    quotes = await mcx_market.quotes(list(uni.values()))
    for k in data.COMMODITIES:
        closes = hist.closes.get(k) or []
        rets = [closes[i][1] / closes[i - 1][1] - 1 for i in range(max(1, len(closes) - 60), len(closes))]
        vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 20 else None
        notional = capital * min(VOL_TARGET / vol, 3.0) / len(data.COMMODITIES) if vol else 0.0
        pick = None
        for sym in SMALLEST[data.FAMILY_OF[k]]:
            inst = uni.get(sym)
            q = quotes.get(str((inst or {}).get("angel_token") or (inst or {}).get("security_id"))) if inst else None
            if not q or not q.ltp:
                continue
            lots = whole_lots(sym, q.ltp, notional)
            pick = {"contract": sym, "expiry": inst.get("expiry"), "price": q.ltp,
                    "lot_value": round(lot_value(sym, q.ltp), 2), "lots": lots}
            break
        out[k] = {"vol_60d": round(vol, 4) if vol else None, "target_notional": round(notional, 2),
                  "vehicle": pick, "feasible": bool(pick and pick["lots"] >= 1)}
    return out


# ── the run ──────────────────────────────────────────────────────────────────────


async def run(refresh_data: bool = True) -> dict:
    from app.services.commodity_patterns import COMMODITY_CATALOG

    started = datetime.now(timezone.utc)
    fetch = await data.refresh() if refresh_data else {}
    hist = await data.load()
    lo_e, hi_e = f"{data.START.year:04d}-01", "2015-12"
    lo_h = "2016-01"
    hi_h = f"{datetime.now().year:04d}-12"

    series: dict[str, dict[str, float]] = {}        # trial key -> monthly net returns
    meta: dict[str, dict] = {}
    daily_cache: dict[tuple, dict] = {}
    keys9 = data.COMMODITIES + list(data.FRED)
    for rule in ("LONG",) + TREND_RULES:
        for k in keys9:
            daily_cache[(rule, k)] = run_rule(hist.closes[k], k, rule)
        books = {"PORT_futures": data.COMMODITIES,
                 "PORT_spot_energy": ["GOLD", "SILVER", "COPPER", "CRUDE_SPOT", "NATGAS_SPOT"]}
        for name, ks in books.items():
            daily_cache[(rule, name)] = portfolio([daily_cache[(rule, k)] for k in ks])
        if rule == "LONG":
            continue
        for k in keys9 + list(books):
            key = f"trend|{rule}|{k}"
            series[key] = monthly(daily_cache[(rule, k)])
            meta[key] = {"kind": "trend", "rule": rule, "series": k,
                         "legs": [x.replace("_SPOT", "") for x in books.get(k, [k])]}
    long_book = monthly(daily_cache[("LONG", "PORT_futures")])
    long_by = {k: monthly(daily_cache[("LONG", k)]) for k in keys9}

    for spec in [s for s in COMMODITY_CATALOG if s.timeframe == "1d"]:
        per_month: dict[str, float] = defaultdict(float)
        for k in data.COMMODITIES:
            for d, r in replay_template(spec, hist.ohlc[k], k):
                per_month[f"{d.year:04d}-{d.month:02d}"] += r / len(data.COMMODITIES)
        key = f"pattern|{spec.template}|1d"
        series[key] = dict(per_month)
        meta[key] = {"kind": "pattern", "template": spec.template, "strategy_id": spec.strategy_id,
                     "name": spec.name, "legs": data.COMMODITIES}

    # the registry: every trial ever run counts toward deflation
    now = datetime.now(timezone.utc)
    for key, m in series.items():
        await lab_trials_collection.update_one(
            {"_id": key}, {"$set": {"monthly": m, "meta": meta[key], "last_run_at": now},
                           "$setOnInsert": {"first_run_at": now}}, upsert=True)
    registry = {d["_id"]: d.get("monthly") or {} async for d in lab_trials_collection.find({}, {"monthly": 1})}
    n_trials = len(registry)
    srs = []
    for m in registry.values():
        xs = list(m.values())
        if len(xs) > 24 and statistics.pstdev(xs):
            srs.append(statistics.mean(xs) / statistics.pstdev(xs))
    sr_var = statistics.pvariance(srs) if len(srs) > 1 else 0.0
    months = sorted({k for m in registry.values() for k in m})
    pbo = pbo_cscv(registry, months)
    feas = await feasibility(hist)
    long_h = period_stats(long_book, lo_h, hi_h)

    rows = []
    for key, m in series.items():
        e, h = period_stats(m, lo_e, hi_e), period_stats(m, lo_h, hi_h)
        xs = [v for _, v in sorted(m.items())]
        dsr = deflated_sharpe(xs, sr_var, n_trials)
        legs = meta[key]["legs"]
        bench = long_book if len(legs) > 1 else long_by.get(meta[key].get("series", ""), long_book)
        bh = period_stats(bench, lo_h, hi_h)
        al = alpha_vs(m, bench)
        n_feas = sum(1 for leg in legs if feas.get(leg, {}).get("feasible"))
        reasons = []
        if not ((e.get("ann_ret_pct") or 0) > 0 and (h.get("ann_ret_pct") or 0) > 0):
            reasons.append(f"not net positive in both periods (explore {e.get('ann_ret_pct')}%/yr, "
                           f"held-out {h.get('ann_ret_pct')}%/yr)")
        if dsr is None or dsr < DSR_MIN:
            reasons.append(f"deflated Sharpe {None if dsr is None else round(dsr, 3)} < {DSR_MIN} over {n_trials} trials")
        if pbo.get("pbo") is None or pbo["pbo"] > PBO_MAX:
            reasons.append(f"PBO {pbo.get('pbo')} > {PBO_MAX} for the trial set")
        if not ((h.get("sharpe") or -9) > (bh.get("sharpe") or 9) and (al.get("alpha_t") or -9) >= ALPHA_T_MIN):
            reasons.append(f"does not beat always-long (held-out Sharpe {h.get('sharpe')} vs {bh.get('sharpe')}, "
                           f"alpha t {al.get('alpha_t')})")
        if n_feas < min(MIN_FEASIBLE_LEGS, len(legs)):
            reasons.append(f"only {n_feas}/{len(legs)} legs tradable in whole lots at Rs{BOOK_CAPITAL:,.0f}")
        rows.append({"key": key, **meta[key], "explore": e, "heldout": h, "dsr": round(dsr, 3) if dsr is not None else None,
                     "alpha": al, "benchmark_heldout_sharpe": bh.get("sharpe"), "feasible_legs": n_feas,
                     "passes_history": not reasons, "reasons": reasons})
    rows.sort(key=lambda r: -(r["dsr"] or 0))

    verdicts = await _apply_verdicts(rows)
    run_doc = {"at": now, "started_at": started, "fetch": fetch, "data_span": hist.span(),
               "n_trials_registry": n_trials, "sr_var": sr_var, "pbo": pbo, "feasibility": feas,
               "benchmark": {"name": "always-long, 5 commodities, same vol targeting and costs", "heldout": long_h,
                             "explore": period_stats(long_book, lo_e, hi_e)},
               "candidates": rows, "passed_history": [r["key"] for r in rows if r["passes_history"]],
               "verdict_counts": verdicts, "book_capital": BOOK_CAPITAL,
               "gate": {"dsr_min": DSR_MIN, "pbo_max": PBO_MAX, "alpha_t_min": ALPHA_T_MIN,
                        "min_feasible_legs": MIN_FEASIBLE_LEGS, "incubation_sessions": INCUBATION_SESSIONS}}
    await lab_runs_collection.insert_one(dict(run_doc))
    logger.info("[commodity_lab] run: %d candidates, %d passed history, PBO %s, %d trials",
                len(rows), len(run_doc["passed_history"]), pbo.get("pbo"), n_trials)
    return run_doc


async def _apply_verdicts(rows: list[dict]) -> dict:
    """History verdicts, then the incubation verdicts read off the Pre-Live desk's record."""
    from tradingai_shared import mcx_calendar as mcal

    counts: dict[str, int] = defaultdict(int)
    now = datetime.now(timezone.utc)
    for r in rows:
        prev = await lab_verdicts_collection.find_one({"_id": r["key"]}) or {}
        verdict = prev.get("verdict")
        if not r["passes_history"]:
            if verdict not in ("CONFIRMED",):
                verdict = "REJECTED_ON_HISTORY"
        elif verdict not in ("INCUBATING", "CONFIRMED", "REJECTED_IN_INCUBATION"):
            verdict = "INCUBATING"
        upd = {"key": r["key"], "kind": r["kind"], "verdict": verdict, "reasons": r["reasons"], "updated_at": now,
               "strategy_id": r.get("strategy_id"), "dsr": r["dsr"],
               "symbols": [s for leg in r["legs"] for s in data.MCX_OF.get(leg.replace("_SPOT", ""), [])],
               "summary": ("Passed the history gate; incubating on the Pre-Live desk." if r["passes_history"]
                           else "; ".join(r["reasons"]))}
        if verdict == "INCUBATING" and not prev.get("incubating_since"):
            upd["incubating_since"] = now
        if verdict == "INCUBATING" and r["kind"] == "pattern":
            since = prev.get("incubating_since") or now
            sessions = mcal.trading_days_between(since.date(), now.date())
            pnl, trades = await _incubation_record(r.get("strategy_id"), since)
            upd.update({"incubation_sessions": sessions, "incubation_trades": trades, "incubation_real_pnl": pnl})
            if sessions >= INCUBATION_SESSIONS:
                upd["verdict"] = "CONFIRMED" if (trades and pnl > 0) else "REJECTED_IN_INCUBATION"
        await lab_verdicts_collection.update_one({"_id": r["key"]}, {"$set": upd}, upsert=True)
        counts[upd["verdict"]] += 1
    return dict(counts)


async def _incubation_record(strategy_id: str | None, since: datetime) -> tuple[float, int]:
    from app.core.db import commodity_prelive_positions_collection

    if not strategy_id:
        return 0.0, 0
    pnl, n = 0.0, 0
    async for p in commodity_prelive_positions_collection.find(
            {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}, "opened_at": {"$gte": since}},
            {"realized_pnl": 1, "real": 1}):
        pnl += ((p.get("real") or {}).get("pnl") if p.get("real") else p.get("realized_pnl")) or 0.0
        n += 1
    return round(pnl, 2), n


# ── read side ────────────────────────────────────────────────────────────────────


async def admitted(universe: list[str]) -> dict[str, dict[str, dict]]:
    """{symbol: {strategy_id: evidence}} — pattern strategies the Lab lets the Pre-Live
    desk trade: INCUBATING (that desk IS the incubator) or CONFIRMED. Empty until one passes."""
    out: dict[str, dict[str, dict]] = {s: {} for s in universe}
    async for v in lab_verdicts_collection.find({"kind": "pattern", "verdict": {"$in": ["INCUBATING", "CONFIRMED"]}}):
        sid = v.get("strategy_id")
        for sym in v.get("symbols") or []:
            if sym in out and sid:
                out[sym][sid] = {"basis": f"commodity_lab_{v['verdict'].lower()}", "source_symbol": sym,
                                 "trades": v.get("incubation_trades", 0), "dsr": v.get("dsr"),
                                 "why": v.get("summary") or "Admitted by the Commodity Lab."}
    return out


async def latest_run(full: bool = False) -> dict | None:
    doc = await lab_runs_collection.find_one({}, sort=[("at", -1)])
    if not doc:
        return None
    doc.pop("_id", None)
    for k in ("at", "started_at"):
        if isinstance(doc.get(k), datetime):
            doc[k] = doc[k].isoformat()
    if not full:
        doc["candidates"] = doc.get("candidates", [])[:120]
    return doc


async def verdicts() -> list[dict]:
    out = []
    async for v in lab_verdicts_collection.find({}).sort("_id", 1):
        v.pop("_id", None)
        for k in ("updated_at", "incubating_since"):
            if isinstance(v.get(k), datetime):
                v[k] = v[k].isoformat()
        out.append(v)
    return out
