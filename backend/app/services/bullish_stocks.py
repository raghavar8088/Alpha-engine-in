"""Bullish Stocks — a screener over the Nifty 50/100/250/500 universe for stocks in a
sustained, confirmed uptrend: making higher highs and higher lows, pressing against their
52-week high, riding above the 9 EMA for a month or more, with the moving-average stack,
momentum and volume all agreeing.

Trade plan attached to every qualifying row (the reason this screen exists): enter at the
live price, 10% stop, 10% first target, and trail the stop 10% below the running high as
the stock advances.

Data sources are the same Angel/local ones the Stocks Range table already uses — the
niftyindices constituent lists (via stock_universe), Angel FULL quotes for the live price,
and the stored daily bars for every indicator. No new vendor, no new credentials.

Highs are measured against the genuine ALL-TIME high, kept per symbol in stock_highs
(seeded by a deep Angel history walk, then nudged forward from daily bars) rather than
against the shallow window bars_collection holds. The 52-week high is still computed and
shown alongside it.

Fundamentals come from stock_fundamentals (Yahoo, refreshed daily): revenue and earnings
growth, margins, debt, ROE and institutional holding are graded out of 6 and can gate
qualification. One item from the original brief has no programmatic source anywhere and is
deliberately NOT approximated: order-book strength, which is disclosed in prose in filings
and is sector-specific. Everything else is real data or absent, never invented.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from app.core.db import (
    bars_collection,
    instruments_collection,
    stock_universe_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.stock_fundamentals import grade as grade_fundamentals
from app.services.stock_fundamentals import load_fundamentals
from app.services.stock_highs import load_highs
from app.services.stocks_range import INDEX_LABELS, QUOTE_PACE_SECONDS
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("bullish_stocks")

# ── screen thresholds ────────────────────────────────────────────────────────────
EMA_FAST = 9
EMA9_MIN_SESSIONS = 21        # "above the 9 EMA for more than a month" ≈ 21 sessions
SMA_MID, SMA_SLOW = 50, 200
NEAR_HIGH_PCT = 0.98          # within 2% of the 52-week high counts as "at highs"
VOL_BREAKOUT_MULT = 1.2       # last session's volume vs its 20-day average
RSI_PERIOD, RSI_MIN = 14, 50.0
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RS_LOOKBACK = 63              # ~3 months, for outperformance vs index and sector
STRUCTURE_BLOCK = 21          # sessions per block (~1 month) for the HH/HL structure test
STRUCTURE_BLOCKS = 3          # compare 3 consecutive monthly blocks
WINDOW_52W = 252              # sessions in a rolling year
TRAIL_HIGH_WINDOW = 20        # running high the trailing stop hangs off

STOP_PCT = 0.10               # 10% stop
TARGET_PCT = 0.10             # 10% first target
TRAIL_PCT = 0.10              # trail 10% below the running high

SCREEN_TTL_SECONDS = 300      # these are daily-bar signals; recompute at most every 5 min
BENCHMARK_SYMBOL = "NIFTY"
MIN_FUNDAMENTAL_SCORE = 3     # of 6 — a confirmation bar, not a value screen

IST = timezone(timedelta(hours=5, minutes=30))


class BullishError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── indicators (plain lists in, no numpy dependency) ─────────────────────────────


def _ema_series(vals: list[float], period: int) -> list[float]:
    """EMA seeded with the first `period` SMA. Result aligns to vals[period-1:]."""
    if len(vals) < period:
        return []
    k = 2 / (period + 1)
    ema = sum(vals[:period]) / period
    out = [ema]
    for v in vals[period:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _sma(vals: list[float], period: int) -> float | None:
    return sum(vals[-period:]) / period if len(vals) >= period else None


def _rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(closes: list[float]) -> tuple[float | None, float | None]:
    """Returns (macd line, signal line) at the latest bar."""
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return None, None
    fast = _ema_series(closes, MACD_FAST)
    slow = _ema_series(closes, MACD_SLOW)
    # fast aligns to closes[MACD_FAST-1:], slow to closes[MACD_SLOW-1:] — trim the fast
    # head so both series sit on the same bars before subtracting.
    fast = fast[MACD_SLOW - MACD_FAST:]
    line = [f - s for f, s in zip(fast, slow)]
    if len(line) < MACD_SIGNAL:
        return None, None
    sig = _ema_series(line, MACD_SIGNAL)
    return line[-1], (sig[-1] if sig else None)


def _ema9_streak(closes: list[float]) -> int:
    """How many consecutive most-recent sessions closed above the 9 EMA."""
    ema = _ema_series(closes, EMA_FAST)
    if not ema:
        return 0
    aligned = closes[EMA_FAST - 1:]
    streak = 0
    for c, e in zip(reversed(aligned), reversed(ema)):
        if c > e:
            streak += 1
        else:
            break
    return streak


def _ascending(seq: list[float], n: int = 3) -> bool:
    s = seq[-n:]
    return len(s) >= 2 and all(s[i] > s[i - 1] for i in range(1, len(s)))


def _higher_structure(highs: list[float], lows: list[float]) -> bool:
    """Higher highs AND higher lows across consecutive ~monthly blocks.

    Deliberately NOT fractal +/-k swing pivots. On a stock trending hard with shallow
    pullbacks — precisely what this screen looks for — a pivot test finds no swing points
    at all, because every forward bar takes out the prior peak, so the structure check
    silently rejected the entire watchlist. Block extremes encode "higher highs and
    higher lows" directly and degrade gracefully on noisy data.
    """
    need = STRUCTURE_BLOCK * STRUCTURE_BLOCKS
    if len(highs) < need or len(lows) < need:
        return False
    hs, ls = highs[-need:], lows[-need:]
    block_highs, block_lows = [], []
    for i in range(STRUCTURE_BLOCKS):
        block_highs.append(max(hs[i * STRUCTURE_BLOCK:(i + 1) * STRUCTURE_BLOCK]))
        block_lows.append(min(ls[i * STRUCTURE_BLOCK:(i + 1) * STRUCTURE_BLOCK]))
    return _ascending(block_highs, STRUCTURE_BLOCKS) and _ascending(block_lows, STRUCTURE_BLOCKS)


def _pctize(f: dict | None, key: str) -> float | None:
    """Yahoo reports growth/margin/holding ratios as fractions — show them as percentages."""
    if not f or f.get(key) is None:
        return None
    return round(f[key] * 100, 2)


def _pct_return(closes: list[float], lookback: int) -> float | None:
    if len(closes) < lookback + 1 or closes[-lookback - 1] <= 0:
        return None
    return (closes[-1] / closes[-lookback - 1] - 1) * 100


# ── screen ───────────────────────────────────────────────────────────────────────


def _evaluate(closes, highs, lows, volumes, ltp, all_time_high: float | None = None) -> dict | None:
    """Compute every signal for one stock. None when there is not enough history.

    `all_time_high` comes from stock_highs (the full-history walk). When it is missing the
    stock is simply not credited with the all-time-high signal — it is never silently
    downgraded to the 52-week high, which would quietly change what the column means.
    """
    if len(closes) < SMA_SLOW + 1 or ltp is None:
        return None

    ema9_days = _ema9_streak(closes)
    sma50 = _sma(closes, SMA_MID)
    sma200 = _sma(closes, SMA_SLOW)
    high_52w = max(highs[-WINDOW_52W:]) if highs else None
    rsi = _rsi(closes)
    macd_line, macd_sig = _macd(closes)
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else None
    last_vol = volumes[-1] if volumes else None
    trail_high = max(highs[-TRAIL_HIGH_WINDOW:]) if highs else None

    if sma50 is None or sma200 is None or high_52w is None or not high_52w:
        return None

    pct_from_high = (ltp / high_52w - 1) * 100
    pct_from_ath = ((ltp / all_time_high - 1) * 100) if all_time_high else None

    return {
        # raw values (shown in the table)
        "all_time_high": round(all_time_high, 2) if all_time_high else None,
        "pct_from_ath": round(pct_from_ath, 2) if pct_from_ath is not None else None,
        "ema9_days": ema9_days,
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "high_52w": round(high_52w, 2),
        "pct_from_52w_high": round(pct_from_high, 2),
        "rsi": round(rsi, 1) if rsi is not None else None,
        "macd": round(macd_line, 2) if macd_line is not None else None,
        "macd_signal": round(macd_sig, 2) if macd_sig is not None else None,
        "vol_x_avg": round(last_vol / avg_vol, 2) if (avg_vol and last_vol) else None,
        "ret_3m": _pct_return(closes, RS_LOOKBACK),
        "trail_high": round(trail_high, 2) if trail_high else None,
        # boolean signals
        "sig_ema9": ema9_days >= EMA9_MIN_SESSIONS,
        "sig_ma_stack": ltp > sma50 and ltp > sma200 and sma50 > sma200,
        "sig_near_high": ltp >= high_52w * NEAR_HIGH_PCT,
        "sig_all_time_high": bool(all_time_high and ltp >= all_time_high * NEAR_HIGH_PCT),
        "sig_structure": _higher_structure(highs, lows),
        "sig_rsi": rsi is not None and rsi > RSI_MIN,
        "sig_macd": (macd_line is not None and macd_sig is not None
                     and macd_line > macd_sig and macd_line > 0),
        "sig_volume": bool(avg_vol and last_vol and last_vol >= avg_vol * VOL_BREAKOUT_MULT),
    }


# module-level cache: {(index): (expires_at, payload)}
_cache: dict[str, tuple[float, dict]] = {}


async def _fno_symbols(symbols: list[str]) -> set[str]:
    """Stocks that have listed derivatives — i.e. an equity future/option whose underlying
    is this symbol. Read from the same instrument master the order path uses, so the flag
    is real rather than a hand-maintained list."""
    out: set[str] = set()
    async for d in instruments_collection.find(
        {"asset_class": {"$in": ["EQUITY_FUTURE", "EQUITY_OPTION"]},
         "underlying_symbol": {"$in": symbols}},
        {"underlying_symbol": 1},
    ):
        if d.get("underlying_symbol"):
            out.add(d["underlying_symbol"])
    return out


async def _benchmark_return() -> tuple[float | None, str]:
    """3-month return of the NIFTY index from stored daily bars. Falls back to the
    universe median (computed by the caller) when the index series isn't loaded."""
    closes = [
        b["close"]
        async for b in bars_collection.find(
            {"timeframe": "1d", "symbol": BENCHMARK_SYMBOL}, {"close": 1, "ts": 1}
        ).sort("ts", 1)
    ]
    r = _pct_return(closes, RS_LOOKBACK)
    return (r, BENCHMARK_SYMBOL) if r is not None else (None, "universe median")


async def screen(index: str, qualified_only: bool = True, force: bool = False) -> dict:
    if index not in INDEX_LABELS:
        raise BullishError(f"Unknown index '{index}' — pick one of {list(INDEX_LABELS)}")

    key = f"{index}:{qualified_only}"
    hit = _cache.get(key)
    if hit and not force and hit[0] > time.monotonic():
        return hit[1]

    docs = [d async for d in stock_universe_collection.find({"indices": index})]
    if not docs:
        raise BullishError("Stock universe not seeded yet — try again in a moment.")
    symbols = [d["symbol"] for d in docs]

    # ── live quotes (same path as Stocks Range: pre-warm, chunk, tolerate failures) ──
    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": symbols}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    by_ex: dict[str, list[str]] = {}
    tok_sym: dict[str, str] = {}
    for sym, i in inst.items():
        if i.get("angel_token"):
            tok = str(i["angel_token"])
            by_ex.setdefault(i.get("angel_exchange") or "NSE", []).append(tok)
            tok_sym[tok] = sym
    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)
    q_by_sym: dict[str, dict] = {}
    for grouped in batches(by_ex):
        try:
            for tok, q in (await angel_client.full_quote(grouped)).items():
                if tok in tok_sym:
                    q_by_sym[tok_sym[tok]] = q
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)

    # ── daily bars (oldest→newest per symbol) ──
    ohlcv: dict[str, dict[str, list[float]]] = {}
    async for b in bars_collection.find(
        {"timeframe": "1d", "symbol": {"$in": symbols}},
        {"symbol": 1, "close": 1, "high": 1, "low": 1, "volume": 1, "ts": 1},
    ).sort("ts", 1):
        s = ohlcv.setdefault(b["symbol"], {"c": [], "h": [], "l": [], "v": []})
        s["c"].append(b.get("close") or 0.0)
        s["h"].append(b.get("high") or b.get("close") or 0.0)
        s["l"].append(b.get("low") or b.get("close") or 0.0)
        s["v"].append(b.get("volume") or 0.0)

    fno = await _fno_symbols(symbols)
    bench_ret, bench_name = await _benchmark_return()
    highs = await load_highs(symbols)
    funds = await load_fundamentals(symbols)

    scored: list[dict] = []
    for d in docs:
        sym = d["symbol"]
        s = ohlcv.get(sym)
        if not s:
            continue
        q = q_by_sym.get(sym)
        ltp = (q.get("ltp") if q else None) or (s["c"][-1] if s["c"] else None)
        prev = (q.get("close") if q else None) or (s["c"][-2] if len(s["c"]) >= 2 else None)
        ath = (highs.get(sym) or {}).get("all_time_high")
        ev = _evaluate(s["c"], s["h"], s["l"], s["v"], ltp, ath)
        if not ev:
            continue
        chg1d = (ltp - prev) if (ltp is not None and prev) else None
        f = funds.get(sym)
        scored.append({
            "symbol": sym,
            "name": d.get("name"),
            "sector": d.get("sector") or "Unclassified",
            "belongs_to": INDEX_LABELS.get(d.get("tightest_index")),
            "fno_enabled": sym in fno,
            "ltp": round(ltp, 2),
            "change_1d_pct": round(chg1d / prev * 100, 2) if (chg1d is not None and prev) else None,
            "all_time_high_date": (highs.get(sym) or {}).get("all_time_high_date"),
            **ev,
            **grade_fundamentals(f),
            "revenue_growth": _pctize(f, "revenue_growth"),
            "earnings_growth": _pctize(f, "earnings_growth"),
            "profit_margin": _pctize(f, "profit_margin"),
            "roe": _pctize(f, "roe"),
            "debt_to_equity": round(f["debt_to_equity"], 1) if f and f.get("debt_to_equity") is not None else None,
            "held_institutions": _pctize(f, "held_institutions"),
            "held_insiders": _pctize(f, "held_insiders"),
            "analyst_rec": (f or {}).get("analyst_rec"),
        })

    # ── relative strength: vs the index (or universe median) and vs own sector ──
    rets = [r["ret_3m"] for r in scored if r["ret_3m"] is not None]
    median = sorted(rets)[len(rets) // 2] if rets else None
    bench = bench_ret if bench_ret is not None else median
    sec_rets: dict[str, list[float]] = {}
    for r in scored:
        if r["ret_3m"] is not None:
            sec_rets.setdefault(r["sector"], []).append(r["ret_3m"])
    sec_avg = {k: sum(v) / len(v) for k, v in sec_rets.items()}

    for r in scored:
        rr = r["ret_3m"]
        r["sector_ret_3m"] = round(sec_avg.get(r["sector"], 0.0), 2) if rr is not None else None
        r["sig_outperform"] = bool(
            rr is not None and bench is not None
            and rr > bench and rr > sec_avg.get(r["sector"], 0.0)
        )
        r["ret_3m"] = round(rr, 2) if rr is not None else None

        signals = [
            r["sig_ema9"], r["sig_ma_stack"], r["sig_near_high"], r["sig_all_time_high"],
            r["sig_structure"], r["sig_rsi"], r["sig_macd"], r["sig_volume"],
            r["sig_outperform"],
        ]
        r["score"] = sum(1 for s in signals if s)
        r["max_score"] = len(signals)
        # The four technical non-negotiables define "bullish" for this desk: a month above
        # the 9 EMA, the full MA stack, pressed against the 52-week high, and an intact
        # higher-high/higher-low structure. The all-time-high signal, volume, RSI, MACD and
        # relative strength add conviction (they lift the score) but never on their own
        # qualify a stock — an all-time high is the ambition, not a hard gate, because a
        # stock can be a valid breakout while still working through an old overhead level.
        r["qualified"] = bool(
            r["sig_ema9"] and r["sig_ma_stack"] and r["sig_near_high"] and r["sig_structure"]
        )
        # Fundamentals gate separately from the technical read, so a stock is never dropped
        # merely because Yahoo has no data for it. Unknown = not blocked, and flagged.
        fs = r.get("fundamental_score")
        r["fundamentally_ok"] = fs is None or fs >= MIN_FUNDAMENTAL_SCORE

        # trade plan — enter now, 10% stop, 10% first target, stop trails the running high
        ltp = r["ltp"]
        r["entry"] = ltp
        r["stop_loss"] = round(ltp * (1 - STOP_PCT), 2)
        r["target"] = round(ltp * (1 + TARGET_PCT), 2)
        r["trail_stop"] = round((r["trail_high"] or ltp) * (1 - TRAIL_PCT), 2)

    rows = ([r for r in scored if r["qualified"] and r["fundamentally_ok"]]
            if qualified_only else scored)
    rows.sort(key=lambda r: (-r["score"], r["pct_from_52w_high"] is None, -(r["pct_from_52w_high"] or -999)))

    graded = sum(1 for r in scored if r.get("fundamentals_known"))
    payload = {
        "index": index,
        "label": INDEX_LABELS[index],
        "count": len(rows),
        "screened": len(scored),
        "qualified_only": qualified_only,
        "benchmark": bench_name,
        "benchmark_ret_3m": round(bench, 2) if bench is not None else None,
        # coverage, so the UI can be honest about what actually backed this run
        "fundamentals_available": graded > 0,
        "fundamentals_graded": graded,
        "ath_available": sum(1 for r in scored if r.get("all_time_high")),
        "high_window": "all-time",
        "unscreened_note": "Order-book strength is not screened — no programmatic source.",
        "plan": {"stop_pct": STOP_PCT * 100, "target_pct": TARGET_PCT * 100, "trail_pct": TRAIL_PCT * 100},
        "computed_at": _now().isoformat(),
        "rows": rows,
    }
    _cache[key] = (time.monotonic() + SCREEN_TTL_SECONDS, payload)
    return payload
