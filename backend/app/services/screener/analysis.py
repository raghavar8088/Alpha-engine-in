"""Stock Analysis — ask about specific stocks rather than waiting for a screen to find them.

WHY THIS EXISTS ALONGSIDE THE OTHER TABS. Everything else in this module is screen-driven:
it computes over a fixed index universe and shows you what it found. That is useless when
you already have a name in hand and the name is outside the Nifty 500 — which is most of
what a Chartink scan returns. This is symbol-driven and works on anything with stored bars.

TWO VERDICTS, NOT ONE. "Bullish?" and "good to buy?" are different questions and merging
them is the single most misleading thing this page could do. A stock can be in a textbook
uptrend and still be a bad purchase — 14% extended past its breakout, or in a 2% circuit
band where a stop cannot fill, or under ASM where the margin rules change under you. So:

  bias   — where the chart is pointing:      Bullish / Neutral / Bearish
  action — whether to put money in TODAY:    Buy / Watch / Avoid

`action` is never better than what tradability allows, no matter how good the chart is.

EVIDENCE, NOT A BLACK BOX. Every verdict carries the pillar scores that produced it and a
written reason per pillar. A number with no argument behind it is worth nothing here, and
the reader has to be able to disagree with a specific step rather than the whole thing.

SOURCES. Own stored daily bars (trend, momentum, structure, patterns), NSE bhavcopy
(delivery vs the stock's own habit), NSE sec_list + ASM/GSM (bands, surveillance),
Chartink's public screens (an independent second opinion on the same name), and Angel for
the live price. Anything unreachable degrades to "unknown" and is reported as such — never
silently treated as a pass.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from app.services.screener import bhavcopy as BHAV
from app.services.screener import chartink as CK
from app.services.screener import horizons as H
from app.services.screener import patterns as PAT
from app.services.screener import plans as PLANS
from app.services.screener import reasons as REASONS
from app.services.screener import volume as VOL

logger = logging.getLogger("screener.analysis")

MAX_SYMBOLS = 40
LOOKBACK = 400
BENCH = "NIFTY"

# ── on-demand history ───────────────────────────────────────────────────────────
# The screener backfills the Nifty 500 and nothing else, but the names a user pastes come
# from whole-market Chartink scans, so most of them have no stored bars at all. Without
# this the tab answers "no history" for the majority of any realistic list — which is not
# an analysis, it is an apology.
#
# So: fetch what is missing from Angel, persist it, and analyse it. Subsequent runs on the
# same names are instant because the bars are now stored like any other.
FETCH_LOOKBACK_DAYS = 500   # ~1.4y — enough for SMA200 and a 52-week range
FETCH_PACE = 0.4            # Angel's historical endpoint is the rate-limited one
MAX_FETCH = 25              # per request, so a long paste cannot hang the page

# Chartink screens used as a cross-check. Membership in one of these is a genuinely
# independent read on the same stock — a different engine, different data vintage, and a
# rule someone else wrote. Cheap because chartink caches for 15 minutes.
CROSSCHECK = ["all-time-high-8", "short-term-breakouts", "breakouts", "volume-shockers",
              "rsi-crossing-60", "nr7-narrow-range-7"]

TOKEN_RE = re.compile(r"[A-Za-z0-9&_.-]+")
SERIES_RE = re.compile(r"-(EQ|BE|BZ|SM|ST|IV|RR|SZ)$", re.I)

# ── pillar weights ──────────────────────────────────────────────────────────────
# Trend and tradability carry the most because they answer the two questions that can
# each independently sink a trade: is the stock going up, and can you actually get in and
# out of it. Momentum and volume refine; structure is about timing.
WEIGHTS = {"trend": 26, "momentum": 22, "volume": 18, "structure": 14, "tradability": 20}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_symbols(raw: str | list[str]) -> list[str]:
    """Accept anything: commas, spaces, newlines, NSE: prefixes, -EQ suffixes, quotes."""
    text = raw if isinstance(raw, str) else " ".join(str(x) for x in (raw or []))
    out, seen = [], set()
    for m in TOKEN_RE.findall(text or ""):
        t = m.upper()
        if t in ("NSE", "BSE"):
            continue
        t = re.sub(r"^(NSE|BSE):", "", t)
        t = SERIES_RE.sub("", t)
        if not t or len(t) > 25 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:MAX_SYMBOLS]


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI. None rather than 50 when there is not enough history — a neutral
    reading and an absent one must not look the same."""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 1)


def _pillar(score: float, label: str, note: str, verdict: str) -> dict:
    return {"key": label, "score": round(max(0.0, min(100.0, score))),
            "verdict": verdict, "note": note}


# ── the five pillars ────────────────────────────────────────────────────────────

def _trend(closes: list[float], price: float) -> dict:
    s20, s50, s200 = H.sma(closes, 20), H.sma(closes, 50), H.sma(closes, 200)
    have = [x for x in (s20, s50, s200) if x]
    if not have:
        return _pillar(50, "trend", "Not enough history to judge the trend.", "unknown")

    above = sum(1 for m in (s20, s50, s200) if m and price > m)
    of = sum(1 for m in (s20, s50, s200) if m)
    stacked = bool(s20 and s50 and s200 and s20 > s50 > s200)
    inverted = bool(s20 and s50 and s200 and s20 < s50 < s200)

    score = above / of * 70 + (30 if stacked else 0)
    if inverted:
        score = min(score, 20)

    parts = [f"Price is above {above} of its {of} moving averages"]
    if stacked:
        parts.append("and the 20 > 50 > 200 stack is intact — a textbook uptrend")
    elif inverted:
        parts.append("and the averages are stacked downward (20 < 50 < 200) — a downtrend")
    elif s200 and price < s200:
        parts.append("but it is below the 200-day, so the long trend is still down")

    v = "strong" if score >= 75 else "ok" if score >= 50 else "weak" if score >= 25 else "bad"
    # Joined with a comma, not a full stop: every continuation starts with "and" or "but",
    # so a period produced "moving averages. and the stack is intact".
    return _pillar(score, "trend", ", ".join(parts) + ".", v)


def _momentum(rets: dict, rs_val: float | None, r: float | None) -> dict:
    m1, m6 = rets.get("1m"), rets.get("6m")
    score = 50.0
    bits = []

    if m1 is not None:
        score += max(-25, min(25, m1 * 1.6))
        bits.append(f"{m1:+.1f}% over a month")
    if m6 is not None:
        score += max(-15, min(15, m6 * 0.4))
        bits.append(f"{m6:+.1f}% over six")
    if rs_val is not None:
        score += max(-15, min(15, rs_val * 1.2))
        bits.append(f"{'beating' if rs_val > 0 else 'lagging'} the Nifty by "
                    f"{abs(rs_val):.1f}pp")
    if r is not None:
        # RSI is used as a CAUTION, not a signal. Above 75 the move is stretched and the
        # next buyer is paying for someone else's gain; below 30 it is falling, and
        # "oversold" is not a reason to buy something in a downtrend.
        if r >= 75:
            score -= 8
            bits.append(f"RSI {r:.0f} — stretched")
        elif r <= 30:
            score -= 10
            bits.append(f"RSI {r:.0f} — falling hard")
        else:
            bits.append(f"RSI {r:.0f}")

    if not bits:
        return _pillar(50, "momentum", "No usable return history.", "unknown")
    v = "strong" if score >= 70 else "ok" if score >= 50 else "weak" if score >= 32 else "bad"
    return _pillar(score, "momentum", ", ".join(bits).capitalize() + ".", v)


def _volume(vol_x: float | None, d: dict | None) -> dict:
    ratio = (d or {}).get("delivery_ratio")
    pct, avg = (d or {}).get("delivery_pct"), (d or {}).get("delivery_avg")
    if vol_x is None and ratio is None:
        return _pillar(50, "volume", "No volume or delivery data stored.", "unknown")

    score = 50.0
    bits = []
    if vol_x is not None:
        score += max(-15, min(25, (vol_x - 1) * 20))
        bits.append(f"{vol_x:.1f}x its 20-day average volume")
    if ratio is not None:
        # Delivery against the stock's OWN habit, never an absolute — a utility routinely
        # delivers 70% and a small cap 15%, so a flat threshold just ranks sectors.
        score += max(-25, min(25, (ratio - 1) * 45))
        word = ("well above" if ratio >= 1.3 else "above" if ratio >= 1.05
                else "in line with" if ratio >= 0.85 else "below" if ratio >= 0.6
                else "far below")
        bits.append(f"{pct:.0f}% delivered, {word} its own {avg:.0f}% average ({ratio:.2f}x)")
        if vol_x and vol_x >= 2 and ratio < 0.7:
            bits.append("— heavy volume with light delivery is churn, not accumulation")

    v = "strong" if score >= 70 else "ok" if score >= 50 else "weak" if score >= 32 else "bad"
    return _pillar(score, "volume", ", ".join(bits).capitalize() + ".", v)


def _close_strength(bar) -> float | None:
    """Where in the session's range the close landed, 0 (at the low) to 1 (at the high).

    A stock that prints an all-time high and closes near the bottom of its range was SOLD
    into that high — the buyers who mattered were sellers by the close. The sweep found
    names touching a record intraday and closing 6% under it, and without this they scored
    as clean breakouts.
    """
    rng = (bar.high or 0) - (bar.low or 0)
    if rng <= 0:
        return None
    return max(0.0, min(1.0, (bar.close - bar.low) / rng))


def _structure(hl: dict, price: float, ath: float | None, brk: bool,
               close_strength: float | None = None) -> dict:
    from_high = hl.get("pct_from_high")
    from_low = hl.get("pct_from_low")
    if from_high is None:
        return _pillar(50, "structure", "No 52-week range stored.", "unknown")

    # Closest to a high is best, but AT the high with nothing above is also where the
    # chase risk lives — so the peak of this pillar sits just under the high, not on it.
    score = 100 + from_high * 4 if from_high > -25 else 0
    bits = [f"{abs(from_high):.1f}% below its 52-week high"
            if from_high < -0.05 else "at its 52-week high"]
    if from_low is not None:
        bits.append(f"{from_low:+.0f}% off the low")
    if ath and price >= ath * 0.999:
        score = max(score, 88)
        bits.append("and printing an all-time high")
    if brk:
        score = min(100.0, score + 8)
        bits.append("with a 20-day breakout today")

    # A weak close inside the session's range is a rejection, and it matters most exactly
    # where this pillar scores highest — at a high. Penalised in proportion, and named.
    if close_strength is not None:
        if close_strength < 0.3:
            score -= 28
            bits.append(f"but it closed in the bottom {close_strength * 100:.0f}% of the "
                        f"day's range — the high was sold into")
        elif close_strength < 0.5:
            score -= 12
            bits.append(f"though it closed only {close_strength * 100:.0f}% up the day's range")
        elif close_strength >= 0.8:
            bits.append("closing near the top of the day's range")

    v = "strong" if score >= 75 else "ok" if score >= 50 else "weak" if score >= 25 else "bad"
    return _pillar(max(0.0, score), "structure", ", ".join(bits).capitalize() + ".", v)


def _tradability(gate: dict | None) -> dict:
    """Straight from the All Time High desk's pre-entry gate — same checks, same source."""
    if not gate:
        return _pillar(50, "tradability", "Could not check band, surveillance or liquidity.",
                       "unknown")
    checks = {c["key"]: c for c in gate.get("checks", [])
              if c["key"] in ("band", "surveillance", "liquidity")}
    if not checks:
        return _pillar(50, "tradability", "No tradability data.", "unknown")

    pts = {"pass": 1.0, "warn": 0.45, "unknown": 0.6, "fail": 0.0}
    score = sum(pts[c["verdict"]] for c in checks.values()) / len(checks) * 100
    fails = [c for c in checks.values() if c["verdict"] == "fail"]
    warns = [c for c in checks.values() if c["verdict"] == "warn"]
    note = (fails[0]["detail"] if fails else warns[0]["detail"] if warns
            else "Normal circuit band, no surveillance flag, and liquid enough to exit.")
    v = "bad" if fails else "weak" if warns else "strong"
    return _pillar(score, "tradability", note, v)


# ── verdict ─────────────────────────────────────────────────────────────────────

def _verdict(pillars: dict, extension_pct: float | None) -> dict:
    total = sum(WEIGHTS.values())
    score = round(sum(WEIGHTS[k] * p["score"] for k, p in pillars.items()) / total)

    chart = round((WEIGHTS["trend"] * pillars["trend"]["score"]
                   + WEIGHTS["momentum"] * pillars["momentum"]["score"]
                   + WEIGHTS["structure"] * pillars["structure"]["score"])
                  / (WEIGHTS["trend"] + WEIGHTS["momentum"] + WEIGHTS["structure"]))

    bias = ("Bullish" if chart >= 62 else "Bearish" if chart <= 38 else "Neutral")

    trad = pillars["tradability"]
    # The action can never be better than tradability allows. A perfect chart on a stock
    # whose stop cannot fill is not a buy; it is a stock to admire from a distance.
    if trad["verdict"] == "bad":
        action, why = "Avoid", trad["note"]
    elif bias == "Bearish":
        action, why = "Avoid", "The chart is pointing down; there is nothing to buy here yet."
    elif bias == "Neutral":
        action, why = "Watch", "No trend worth paying for yet — wait for it to pick a side."
    elif extension_pct is not None and extension_pct > 12:
        action, why = ("Watch",
                       f"Bullish, but already {extension_pct:.0f}% above its 20-day "
                       f"breakout level — buying here means paying for a move that has "
                       f"happened and putting the stop a long way down.")
    elif trad["verdict"] == "weak":
        action, why = "Watch", "Bullish, but " + trad["note"][0].lower() + trad["note"][1:]
    elif score >= 72:
        action, why = "Buy", "Trend, participation and tradability all line up."
    else:
        action, why = ("Watch",
                       "Bullish, but not every pillar agrees — see which ones are weak.")

    return {"score": score, "chart_score": chart, "bias": bias,
            "action": action, "action_why": why}


# ── the analyser ────────────────────────────────────────────────────────────────

async def _crosscheck() -> dict[str, list[str]]:
    """{symbol: [screen labels it currently appears in]}. Never raises."""
    out: dict[str, list[str]] = {}
    try:
        results = await asyncio.gather(
            *(CK.named(s) for s in CROSSCHECK), return_exceptions=True)
    except Exception:  # noqa: BLE001
        return out
    for slug, res in zip(CROSSCHECK, results):
        if isinstance(res, Exception) or not isinstance(res, dict) or not res.get("ok"):
            continue
        label = (CK.NAMED.get(slug) or {}).get("label", slug)
        for row in res.get("rows") or []:
            out.setdefault(row["symbol"], []).append(label)
    return out


async def _fetch_missing(symbols: list[str]) -> dict:
    """Pull daily candles from Angel for symbols with no stored history, and persist them.

    Resolves through the instrument master first and falls back to Angel's own scrip
    search, because the master is Dhan-derived: its not knowing a symbol says nothing
    about whether NSE lists it. CALSOFT taught that lesson to the ATH mapper.
    """
    from datetime import timedelta

    from pymongo import UpdateOne

    from app.core.db import bars_collection, instruments_collection
    from app.services import ath_trading as ATH
    from app.services.angel_client import AngelAPIError, angel_client

    inst = {d["symbol"]: d async for d in instruments_collection.find(
        {"symbol": {"$in": symbols}, "asset_class": "EQUITY",
         "angel_token": {"$ne": None}},
        {"_id": 0, "symbol": 1, "angel_token": 1, "angel_exchange": 1})}

    for sym in symbols:
        if sym in inst:
            continue
        try:
            found = await ATH._angel_lookup(sym)
            if found:
                inst[sym] = await ATH._adopt_instrument(found)
        except Exception as exc:  # noqa: BLE001
            logger.info("analysis: scrip search failed for %s (%s)", sym, str(exc)[:100])

    if not inst:
        return {"fetched": 0, "failed": len(symbols), "resolved": 0}

    now = datetime.now(H.IST)
    to_dt = now.strftime("%Y-%m-%d 15:30")
    from_dt = (now - timedelta(days=FETCH_LOOKBACK_DAYS)).strftime("%Y-%m-%d 09:15")
    try:
        await angel_client._session()
    except AngelAPIError:
        pass

    ok = fail = 0
    for sym, i in list(inst.items())[:MAX_FETCH]:
        try:
            candles = await angel_client.candles(
                i.get("angel_exchange") or "NSE", str(i["angel_token"]), "D",
                from_dt, to_dt)
        except Exception as exc:  # noqa: BLE001
            logger.info("analysis: candles failed for %s (%s)", sym, str(exc)[:100])
            fail += 1
            # Pace even on failure. Skipping the sleep here is what turned one throttle
            # into a cascade the last time this pattern was written.
            await asyncio.sleep(FETCH_PACE)
            continue
        ops = []
        for row in candles or []:
            try:
                # Store the DATETIME, never its isoformat string — `ts` is queried with
                # range filters and a string silently matches none of them.
                ts = datetime.fromisoformat(row[0]).astimezone(timezone.utc)
                ops.append(UpdateOne(
                    {"symbol": sym, "timeframe": "1d", "ts": ts},
                    {"$set": {"symbol": sym, "timeframe": "1d", "ts": ts,
                              "open": float(row[1]), "high": float(row[2]),
                              "low": float(row[3]), "close": float(row[4]),
                              "volume": float(row[5]), "oi": None}},
                    upsert=True))
            except (ValueError, TypeError, IndexError):
                continue
        if ops:
            await bars_collection.bulk_write(ops, ordered=False)
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(FETCH_PACE)

    logger.info("analysis: fetched history for %s symbol(s), %s failed", ok, fail)
    return {"fetched": ok, "failed": fail, "resolved": len(inst)}


async def analyse(raw: str | list[str], fresh: bool = False) -> dict:
    """Analyse one stock or a list. Never raises for a single bad symbol."""
    symbols = parse_symbols(raw)
    if not symbols:
        return {"count": 0, "rows": [], "error": "No usable symbols in that input."}

    from app.core.db import stock_fundamentals_collection, stock_highs_collection

    bars_by, delivery, cross, gate_ctx = await asyncio.gather(
        H.load_daily_bars(symbols, LOOKBACK, fresh=fresh),
        BHAV.delivery_stats(),
        _crosscheck(),
        _gate_context(),
        return_exceptions=True,
    )
    if isinstance(bars_by, Exception):
        logger.warning("analysis: bars unavailable (%s)", bars_by)
        bars_by = {}
    for name, val in (("delivery", delivery), ("cross", cross)):
        if isinstance(val, Exception):
            logger.info("analysis: %s unavailable (%s)", name, val)
    delivery = {} if isinstance(delivery, Exception) else delivery
    cross = {} if isinstance(cross, Exception) else cross
    gate_ctx = None if isinstance(gate_ctx, Exception) else gate_ctx

    highs = {d["symbol"]: d async for d in stock_highs_collection.find(
        {"symbol": {"$in": symbols}}, {"_id": 0, "symbol": 1, "all_time_high": 1,
                                       "all_time_high_date": 1})}
    caps = {d["symbol"]: d async for d in stock_fundamentals_collection.find(
        {"symbol": {"$in": symbols}}, {"_id": 0, "symbol": 1, "market_cap": 1})}
    # Company names, so a row reads as a company rather than a ticker and a search box can
    # match either. The field was being emitted as a hardcoded None.
    from app.core.db import instruments_collection
    names = {d["symbol"]: d.get("name") async for d in instruments_collection.find(
        {"symbol": {"$in": symbols}, "asset_class": "EQUITY"},
        {"_id": 0, "symbol": 1, "name": 1})}

    # Anything without enough stored history gets pulled from Angel now, then re-read.
    # Done once for the whole request rather than per symbol.
    missing = [s for s in symbols if len(bars_by.get(s) or []) < 30]
    fetch_note = None
    if missing:
        try:
            got = await _fetch_missing(missing)
            if got["fetched"]:
                bars_by = await H.load_daily_bars(symbols, LOOKBACK, fresh=True)
            if len(missing) > MAX_FETCH:
                fetch_note = (f"{len(missing)} symbols had no stored history; the first "
                              f"{MAX_FETCH} were fetched. Run again to do the rest.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("analysis: on-demand fetch failed (%s)", exc)
            fetch_note = "Could not reach Angel to backfill the missing histories."

    bench = bars_by.get(BENCH) or []
    bench_rets = H.all_horizon_returns([b.close for b in bench]) if bench else {}

    rows = [_analyse_one(s, bars_by.get(s) or [], bench_rets, delivery.get(s),
                         cross.get(s) or [], highs.get(s), caps.get(s), gate_ctx,
                         names.get(s))
            for s in symbols]

    ok = [r for r in rows if r.get("analysed")]
    rows.sort(key=lambda r: (-(r.get("verdict", {}).get("score") or -1)))
    return {
        "count": len(rows),
        "analysed": len(ok),
        "rows": rows,
        "fetch_note": fetch_note,
        "generated_at": _now().isoformat(),
        "sources": {
            "bars": "own stored daily bars (Angel One)",
            "delivery": "NSE bhavcopy",
            "surveillance": "NSE sec_list + ASM/GSM registers",
            "crosscheck": "Chartink public screens (delayed)",
        },
        "note": ("`bias` is where the chart points; `action` is whether to buy TODAY. They "
                 "are separate on purpose — a stock can be in a clean uptrend and still be "
                 "a poor purchase because it is extended or cannot be exited."),
    }


async def _gate_context():
    from app.services import ath_gate as GATE
    return await GATE.build_context("observe", 100000.0)


def _analyse_one(symbol: str, bars: list, bench_rets: dict, deliv: dict | None,
                 screens: list[str], high: dict | None, cap: dict | None, ctx,
                 name: str | None = None) -> dict:
    base = {"symbol": symbol, "name": name, "screens": screens, "analysed": False}
    mcap = (cap or {}).get("market_cap")
    base["market_cap_cr"] = round(mcap / 1e7) if mcap else None

    if len(bars) < 30:
        # Say which kind of nothing this is. "Never heard of it" and "listed last month"
        # call for completely different responses from the reader.
        base["note"] = (
            f"Only {len(bars)} stored sessions — not enough to analyse. Either the symbol "
            f"is wrong, or the desk has not backfilled its history yet."
            if bars else
            "No stored price history for this symbol. Check the spelling, or it may be "
            "outside the universe this app backfills.")
        if screens:
            base["note"] += f" Chartink currently lists it in: {', '.join(screens)}."
        return base

    closes = [b.close for b in bars]
    price = closes[-1]
    rets = H.all_horizon_returns(closes)
    hl = H.high_low_context(bars, 252)
    atr14 = H.atr(bars, 14)
    vol_x = H.volume_ratio(bars, 20)
    r = rsi(closes)
    ath = (high or {}).get("all_time_high")
    brk_date = H.donchian_break(bars, 20)
    broke_today = bool(brk_date and brk_date == H.ist_date(bars[-1].ts))
    d20 = H.donchian_high(bars[:-1], 20)
    extension = ((price / d20 - 1) * 100) if d20 and d20 > 0 else None

    gate = None
    if ctx is not None:
        try:
            gate = ctx.evaluate(symbol, price, float(ath or 0)).to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.info("analysis: gate failed for %s (%s)", symbol, exc)

    pillars = {
        "trend": _trend(closes, price),
        "momentum": _momentum(rets, H.relative_strength(rets.get("1m"),
                                                        bench_rets.get("1m")), r),
        "volume": _volume(vol_x, deliv),
        "structure": _structure(hl, price, ath, broke_today, _close_strength(bars[-1])),
        "tradability": _tradability(gate),
    }
    verdict = _verdict(pillars, extension)

    weekly = H.to_weekly(bars)
    hits = PAT._scan_symbol(symbol, None, bars, "1d")
    hits += PAT._scan_symbol(symbol, None, weekly, "1w") if len(weekly) >= 45 else []

    metrics = {
        "ltp": price, "atr14": atr14, "volume_x": vol_x,
        "swing_low": H.last_swing_low(bars),
        "pct_from_52w_high": hl.get("pct_from_high"),
        "consistency": H.consistency(closes, 21),
        "up_streak": H.up_streak(closes),
        "ema9_hold_pct": H.days_above_ema(closes, 9, 21),
        "rs_index": H.relative_strength(rets.get("1m"), bench_rets.get("1m")),
        "breakout": {"window": 20, "date": brk_date.isoformat()} if broke_today else None,
        **{k: (deliv or {}).get(k) for k in
           ("delivery_pct", "delivery_avg", "delivery_ratio")},
    }

    return {
        **base,
        "analysed": True,
        "ltp": round(price, 2),
        "sessions": len(bars),
        "as_of": H.ist_date(bars[-1].ts).isoformat(),
        "verdict": verdict,
        "pillars": pillars,
        "returns": {k: (round(v, 2) if v is not None else None) for k, v in rets.items()},
        "levels": {
            "sma20": _r(H.sma(closes, 20)), "sma50": _r(H.sma(closes, 50)),
            "sma200": _r(H.sma(closes, 200)),
            "rsi14": r, "atr14": _r(atr14),
            "atr_pct": _r(atr14 / price * 100) if atr14 else None,
            # The session's own high and low. Needed because "printed a new all-time
            # high" is a claim about the HIGH, not the close — a stock can take out its
            # record intraday and close a percent under it, and judging that on the close
            # reports it as "1% away" from a record it actually set.
            "day_high": _r(bars[-1].high), "day_low": _r(bars[-1].low),
            "close_strength": _r(_close_strength(bars[-1]), 3),
            "week52_high": _r(hl.get("high")), "week52_low": _r(hl.get("low")),
            "pct_from_52w_high": _r(hl.get("pct_from_high")),
            "all_time_high": _r(ath),
            "swing_low": _r(H.last_swing_low(bars)),
            "resistance": _r(H.nearest_resistance_above(bars, price)),
            "breakout_level_20d": _r(d20),
            "extension_pct": _r(extension),
        },
        "delivery": deliv,
        "gate": gate,
        "patterns": [{"key": h.get("pattern"),
                      "label": (h.get("pattern") or "").replace("_", " ").title(),
                      "family": h.get("family_label"),
                      "timeframe": h.get("timeframe_label"), "state": h.get("state"),
                      "direction": h.get("direction"),
                      "target": h.get("target"), "stoploss": h.get("stoploss"),
                      "reward_risk": h.get("reward_risk")} for h in hits[:8]],
        "next_target": VOL.next_target(bars, price, hits, atr14),
        "plan": PLANS.swing_plan(metrics),
        "reasons": REASONS.build(metrics)[:6],
    }


def _r(v, nd: int = 2):
    return None if v is None else round(v, nd)
