"""Trading-call generation + lifecycle engine (the "Trading Calls" module).

Produces Kotak-Neo-style research calls — Name / LTP / Target / Stoploss / call
expiry / status — across three segments:

- STOCK: technical-score scan (EMA trend, RSI, MACD, ROC, Donchian breakout, ATR
  sizing) over locally backfilled daily bars. Long-only cash calls.
- FNO: index option BUY calls driven by the *qualified* strategies of the latest
  option-buying-lab sweep (the module deliberately reuses that validation gate:
  a call is only emitted when the qualified strategies for that index/style agree
  on a direction), plus index/stock futures calls from the daily technical score.
- COMMODITY: MCX futures calls, same technical scan, with daily bars fetched from
  Dhan on demand (MCX bars are not kept in the local store).

Every call is honest about its data: `ltp_source` says whether the price is a live
Dhan quote, the last locally stored bar close, or a Black-Scholes model estimate,
and `data_as_of` carries the last bar session the signal was computed from.

Lifecycle (refresh_calls): OPEN -> PARTIAL_EXIT (>= 60% of the way to target;
stoploss trails to entry) -> TARGET_HIT / STOPLOSS / EXPIRED (past call expiry).
"""

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import instruments_collection, option_sweeps_collection, trading_calls_collection
from app.services.dhan_client import DhanAPIError, DhanClient
from backtesting_service.service import load_bars
from options_service.greeks import black_scholes_price
from options_service.options_backtest import OPTION_BUYING_CATEGORIES
from strategy_service import STRATEGY_REGISTRY
from strategy_service.indicators import atr, donchian, ema, macd, roc, rsi
from tradingai_shared.contracts import StrategyContext
from tradingai_shared.domain import Bar, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))

INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
COMMODITY_WHITELIST = {"GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC"}

# Consensus gates for option calls: at least this many qualified strategies must
# vote, and the win-rate-weighted net direction must clear the threshold.
MIN_VOTERS = 3
NET_DIRECTION_GATE = 0.30
TOP_STRATEGIES_PER_STYLE = 10

# ATR multiples for directional (stock/futures/commodity) calls.
POSITIONAL_TARGET_ATR, POSITIONAL_STOP_ATR = 1.5, 0.75
INTRADAY_TARGET_ATR, INTRADAY_STOP_ATR = 0.8, 0.4

STOCK_SCORE_GATE = 0.45  # |score| needed for a cash call
FUTURES_SCORE_GATE = 0.55  # |score| needed for a futures call (short side allowed)

# Bars older than this many days can still back a positional view, but never an
# intraday one (weekend/holiday tolerant).
INTRADAY_MAX_STALENESS_DAYS = 3

_YEARS_BY_TF = {"5m": 0.25, "15m": 0.5, "1h": 1.0, "1d": 3.0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _session_date(ts: datetime):
    """Dhan daily bars stamp midnight IST (18:30 UTC of the previous day)."""
    return ts.astimezone(IST).date()


def _round_tick(price: float, tick: float) -> float:
    if tick <= 0:
        tick = 0.05
    return round(round(price / tick) * tick, 2)


# --------------------------------------------------------------------------------
# Technical scan (stocks, futures direction, commodities)
# --------------------------------------------------------------------------------


def technical_score(bars: list[Bar]) -> tuple[float, list[str], float] | None:
    """Composite score in [-1, 1] from daily bars, with human-readable reasons and
    ATR(14) for target/stop sizing. None when there is not enough history."""
    if len(bars) < 60:
        return None
    closes = [b.close for b in bars]
    close = closes[-1]

    ema20, ema50 = ema(closes, 20), ema(closes, 50)
    rsi14 = rsi(closes, 14)
    _, macd_signal = macd(closes)
    macd_line = ema(closes, 12)[-1] - ema(closes, 26)[-1]
    macd_hist = macd_line - macd_signal[-1]
    roc20 = roc(closes, 20)
    upper, lower = donchian(bars, 20)
    atr14 = atr(bars, 14)[-1]

    score, reasons = 0.0, []
    if ema20[-1] > ema50[-1]:
        score += 0.25
        reasons.append("EMA20 above EMA50 (uptrend)")
    else:
        score -= 0.25
        reasons.append("EMA20 below EMA50 (downtrend)")
    if close > ema20[-1]:
        score += 0.15
        reasons.append("price above EMA20")
    else:
        score -= 0.15
        reasons.append("price below EMA20")

    r = rsi14[-1]
    if r >= 60:
        score += 0.20
        reasons.append(f"RSI {r:.0f} strong")
    elif r >= 55:
        score += 0.10
        reasons.append(f"RSI {r:.0f} firm")
    elif r <= 40:
        score -= 0.20
        reasons.append(f"RSI {r:.0f} weak")
    elif r <= 45:
        score -= 0.10
        reasons.append(f"RSI {r:.0f} soft")

    if macd_hist > 0:
        score += 0.20
        reasons.append("MACD histogram positive")
    else:
        score -= 0.20
        reasons.append("MACD histogram negative")

    m = roc20[-1]
    if m > 2:
        score += 0.10
        reasons.append(f"20d momentum +{m:.1f}%")
    elif m < -2:
        score -= 0.10
        reasons.append(f"20d momentum {m:.1f}%")

    # Donchian proximity: within 1% of the 20d extreme reads as breakout pressure.
    if upper[-1] and close >= upper[-1] * 0.99:
        score += 0.10
        reasons.append("at 20d Donchian high (breakout zone)")
    elif lower[-1] and close <= lower[-1] * 1.01:
        score -= 0.10
        reasons.append("at 20d Donchian low (breakdown zone)")

    return max(-1.0, min(1.0, score)), reasons, atr14


def _realized_vol(bars: list[Bar], lookback: int = 21) -> float:
    closes = [b.close for b in bars[-(lookback + 1):]]
    if len(closes) < 3:
        return 0.15
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / max(len(rets) - 1, 1)
    return max(math.sqrt(var) * math.sqrt(252), 0.05)


# --------------------------------------------------------------------------------
# Live LTP helpers (always honest about the source)
# --------------------------------------------------------------------------------


async def _ltp_batch(dhan: DhanClient | None, wanted: dict[str, list[int]]) -> dict[tuple[str, str], float]:
    """{(exchange_segment, security_id): ltp} via one Dhan marketfeed call.
    Empty dict when no client / expired token — callers fall back to bar closes."""
    if dhan is None or not wanted:
        return {}
    try:
        raw = await dhan.ltp_data(wanted)
    except (DhanAPIError, Exception):
        return {}
    out: dict[tuple[str, str], float] = {}
    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    for segment, by_id in (data.items() if isinstance(data, dict) else []):
        for sec_id, payload in (by_id.items() if isinstance(by_id, dict) else []):
            ltp = payload.get("last_price") if isinstance(payload, dict) else None
            if ltp:
                out[(segment, str(sec_id))] = float(ltp)
    return out


# --------------------------------------------------------------------------------
# Call construction
# --------------------------------------------------------------------------------


def _call_doc(
    *, segment: str, horizon: str, side: str, symbol: str, display_name: str,
    instrument: dict | None, entry: float, target: float, stoploss: float,
    call_expiry_date: str, confidence: float, source: dict, rationale: str,
    ltp_source: str, data_as_of: str | None, tags: list[str],
) -> dict:
    return {
        "call_id": uuid4().hex[:12],
        "segment": segment,
        "horizon": horizon,
        "side": side,
        "symbol": symbol,
        "display_name": display_name,
        "instrument": instrument,
        "entry_price": round(entry, 2),
        "ltp": round(entry, 2),
        "ltp_source": ltp_source,
        "target": round(target, 2),
        "stoploss": round(stoploss, 2),
        "call_expiry_date": call_expiry_date,
        "status": "OPEN",
        "confidence": round(confidence, 2),
        "source": source,
        "rationale": rationale,
        "tags": tags,
        "data_as_of": data_as_of,
        "pnl_pct": None,
        "generated_on": _today_ist().isoformat(),
        "created_at": _now(),
        "updated_at": _now(),
        "closed_at": None,
    }


def _instrument_ref(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    return {
        "symbol": doc["symbol"],
        "security_id": doc["security_id"],
        "exchange_segment": doc["exchange_segment"],
        "lot_size": doc.get("lot_size", 1),
        "expiry": doc.get("expiry"),
        "strike": doc.get("strike"),
        "option_type": doc.get("option_type"),
    }


async def _is_duplicate(call: dict) -> bool:
    """One live call per instrument+horizon+side — regenerating must not stack."""
    query = {
        "segment": call["segment"],
        "symbol": call["symbol"],
        "horizon": call["horizon"],
        "side": call["side"],
        "status": {"$in": ["OPEN", "PARTIAL_EXIT"]},
    }
    inst = call.get("instrument") or {}
    if inst.get("strike") is not None:
        query["instrument.strike"] = inst["strike"]
        query["instrument.option_type"] = inst["option_type"]
    return await trading_calls_collection.find_one(query) is not None


# --------------------------------------------------------------------------------
# STOCK segment
# --------------------------------------------------------------------------------


async def _scored_daily_symbols() -> list[tuple[str, float, list[str], float, list[Bar]]]:
    """(symbol, score, reasons, atr14, bars) for every non-index symbol that has
    local daily bars. The scan universe is exactly what has been backfilled —
    the module never invents data for symbols it cannot see."""
    from app.core.db import bars_collection

    symbols = await bars_collection.distinct("symbol", {"timeframe": "1d"})
    out = []
    for symbol in sorted(symbols):
        if symbol in INDICES:
            continue
        bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 2.0)
        scored = technical_score(bars)
        if scored is None:
            continue
        score, reasons, atr14 = scored
        out.append((symbol, score, reasons, atr14, bars))
    return out


async def _stock_calls(dhan: DhanClient | None, scored: list) -> list[dict]:
    today = _today_ist()
    equities = {
        d["symbol"]: d
        async for d in instruments_collection.find({"asset_class": "EQUITY", "symbol": {"$in": [s for s, *_ in scored]}})
    }
    wanted: dict[str, list[int]] = {}
    for symbol, score, _reasons, _atr14, _bars in scored:
        inst = equities.get(symbol)
        if inst and score >= STOCK_SCORE_GATE:
            wanted.setdefault(inst["exchange_segment"], []).append(int(inst["security_id"]))
    live = await _ltp_batch(dhan, wanted)

    calls = []
    for symbol, score, reasons, atr14, bars in scored:
        if score < STOCK_SCORE_GATE:  # cash segment is long-only, like broker desks
            continue
        inst = equities.get(symbol)
        if inst is None:
            continue
        last_session = _session_date(bars[-1].ts)
        key = (inst["exchange_segment"], str(inst["security_id"]))
        ltp = live.get(key)
        ltp_source = "dhan_quote" if ltp else "last_bar_close"
        entry = ltp or bars[-1].close
        tick = inst.get("tick_size", 0.05)
        fresh_enough = (today - last_session).days <= INTRADAY_MAX_STALENESS_DAYS

        source = {"kind": "technical_scan", "strategy_id": None, "name": "Daily technical scan"}
        rationale = "; ".join(reasons)
        common = dict(
            segment="STOCK", side="BUY", symbol=symbol, display_name=symbol,
            instrument=_instrument_ref(inst), confidence=abs(score), source=source,
            rationale=rationale, ltp_source=ltp_source, data_as_of=last_session.isoformat(),
        )
        calls.append(_call_doc(
            **common, horizon="POSITIONAL", entry=entry,
            target=_round_tick(entry + POSITIONAL_TARGET_ATR * atr14, tick),
            stoploss=_round_tick(entry - POSITIONAL_STOP_ATR * atr14, tick),
            call_expiry_date=(today + timedelta(days=10)).isoformat(),
            tags=[],
        ))
        if score >= 0.6 and fresh_enough:
            calls.append(_call_doc(
                **common, horizon="INTRADAY", entry=entry,
                target=_round_tick(entry + INTRADAY_TARGET_ATR * atr14, tick),
                stoploss=_round_tick(entry - INTRADAY_STOP_ATR * atr14, tick),
                call_expiry_date=today.isoformat(),
                tags=[],
            ))
    return calls


# --------------------------------------------------------------------------------
# FNO segment
# --------------------------------------------------------------------------------


def _replay_direction(strategy_id: str, bars: list[Bar]) -> tuple[int, str]:
    """Current direction regime (+1/-1/0) of an option-buying strategy after
    replaying recent bars, plus its last stated reasoning."""
    cls = STRATEGY_REGISTRY.get(strategy_id)
    if cls is None:
        return 0, ""
    strategy = cls()
    ctx = StrategyContext(max_bars=500)
    for bar in bars[-600:]:
        ctx.push(bar)
        try:
            strategy.on_bar(ctx)
        except Exception:
            return 0, ""
    return getattr(strategy, "_dir", 0), getattr(strategy, "why", "") or ""


async def _style_consensus(symbol: str, style: str, sweep: dict) -> dict | None:
    """Win-rate-weighted direction vote of the latest sweep's qualified strategies
    for one index + style. None when too few strategies exist or vote."""
    entries = [
        e for e in sweep.get("results", [])
        if e.get("qualified")
        and e.get("style") == style
        and (e.get("symbol") or sweep.get("symbol")) == symbol
        and e.get("metrics")
    ]
    entries.sort(key=lambda e: e["metrics"].get("win_rate") or 0, reverse=True)
    entries = entries[:TOP_STRATEGIES_PER_STYLE]
    if len(entries) < MIN_VOTERS:
        return None

    bars_cache: dict[str, list[Bar]] = {}
    votes: list[tuple[dict, int, str]] = []
    for entry in entries:
        tf = entry.get("timeframe", "1d")
        if tf not in bars_cache:
            bars_cache[tf] = await to_thread.run_sync(
                load_bars, symbol, Timeframe(tf), _YEARS_BY_TF.get(tf, 1.0)
            )
        bars = bars_cache[tf]
        if not bars:
            continue
        direction, why = await to_thread.run_sync(_replay_direction, entry["strategy_id"], bars)
        votes.append((entry, direction, why))

    voters = [(e, d, w) for e, d, w in votes if d != 0]
    if len(voters) < MIN_VOTERS:
        return None
    total_weight = sum(e["metrics"]["win_rate"] for e, _, _ in voters)
    net = sum(e["metrics"]["win_rate"] * d for e, d, _ in voters) / total_weight
    n_bull = sum(1 for _, d, _ in voters if d > 0)
    n_bear = len(voters) - n_bull
    consensus_dir = 1 if net > 0 else -1
    lead = next(((e, w) for e, d, w in voters if d == consensus_dir), None)
    last_bars = max(bars_cache.values(), key=len, default=[])
    return {
        "net": net,
        "n_bull": n_bull,
        "n_bear": n_bear,
        "n_voters": len(voters),
        "lead_entry": lead[0] if lead else None,
        "lead_why": lead[1] if lead else "",
        "data_as_of": _session_date(last_bars[-1].ts).isoformat() if last_bars else None,
    }


async def _pick_option_instrument(symbol: str, direction: int, dte_days: int, spot: float) -> dict | None:
    """Nearest ATM strike on the earliest listed expiry that still covers the
    style's DTE (falls back to the furthest listed one)."""
    today = _today_ist()
    expiries = sorted(
        e for e in await instruments_collection.distinct(
            "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": symbol}
        )
        if e and e >= today.isoformat()
    )
    if not expiries:
        return None
    expiry = next(
        (e for e in expiries if (datetime.fromisoformat(e).date() - today).days >= dte_days),
        expiries[-1],
    )
    option_type = "CE" if direction > 0 else "PE"
    cursor = instruments_collection.find({
        "asset_class": "INDEX_OPTION", "underlying_symbol": symbol,
        "expiry": expiry, "option_type": option_type,
    })
    candidates = [d async for d in cursor]
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d.get("strike") or 0) - spot))


async def _fno_calls(dhan: DhanClient | None, scored_stocks: list) -> tuple[list[dict], str | None]:
    sweep = await option_sweeps_collection.find_one({}, sort=[("created_at", -1)])
    note = None
    calls: list[dict] = []
    today = _today_ist()

    if sweep is None:
        note = "No option-lab sweep found — run the Buying Lab sweep (Options → Buying Lab) to enable qualified-strategy option calls."
    else:
        for symbol in INDICES:
            daily = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 2.0)
            if not daily:
                continue
            spot = daily[-1].close
            sigma = _realized_vol(daily)
            scored = technical_score(daily)
            daily_score = scored[0] if scored else 0.0
            atr14 = scored[2] if scored else spot * 0.01
            last_session = _session_date(daily[-1].ts)
            fresh_enough = (today - last_session).days <= INTRADAY_MAX_STALENESS_DAYS

            for style in ("intraday", "swing"):
                if style == "intraday" and not fresh_enough:
                    continue
                consensus = await _style_consensus(symbol, style, sweep)
                if consensus is None or abs(consensus["net"]) < NET_DIRECTION_GATE:
                    continue
                direction = 1 if consensus["net"] > 0 else -1
                style_cfg = OPTION_BUYING_CATEGORIES[f"options_{style}"]
                inst = await _pick_option_instrument(symbol, direction, style_cfg["dte_days"], spot)
                if inst is None:
                    continue

                dte = (datetime.fromisoformat(inst["expiry"]).date() - today).days
                live = await _ltp_batch(dhan, {inst["exchange_segment"]: [int(inst["security_id"])]})
                premium = live.get((inst["exchange_segment"], str(inst["security_id"])))
                if premium:
                    ltp_source = "dhan_quote"
                else:
                    premium = black_scholes_price(
                        spot, inst["strike"], max(dte, 1) / 365, inst["option_type"], sigma=sigma
                    )
                    ltp_source = "model"
                if premium < 1:
                    continue  # deep-OTM dust — not a tradable call

                lead = consensus["lead_entry"] or {}
                lead_wr = (lead.get("metrics") or {}).get("win_rate")
                rationale = (
                    f"{consensus['n_bull']} of {consensus['n_voters']} qualified {style} strategies "
                    f"{'bullish' if direction > 0 else 'bearish'} on {symbol} "
                    f"(win-rate-weighted net {consensus['net']:+.2f}). "
                    f"Lead: {lead.get('name', lead.get('strategy_id', '?'))}"
                    + (f" ({lead_wr * 100:.1f}% win rate)" if lead_wr else "")
                    + (f" — {consensus['lead_why']}" if consensus["lead_why"] else "")
                )
                option_word = "CALL" if inst["option_type"] == "CE" else "PUT"
                expiry_dt = datetime.fromisoformat(inst["expiry"]).date()
                validity = today if style == "intraday" else min(expiry_dt, today + timedelta(days=7))
                calls.append(_call_doc(
                    segment="FNO", horizon="INTRADAY" if style == "intraday" else "POSITIONAL",
                    side="BUY", symbol=symbol,
                    display_name=f"{symbol} {inst['strike']:g} {option_word}",
                    instrument=_instrument_ref(inst), entry=premium,
                    target=_round_tick(premium * (1 + style_cfg["premium_target_pct"]), inst.get("tick_size", 0.05)),
                    stoploss=_round_tick(premium * (1 - style_cfg["premium_stop_pct"]), inst.get("tick_size", 0.05)),
                    call_expiry_date=validity.isoformat(),
                    confidence=abs(consensus["net"]),
                    source={
                        "kind": "qualified_sweep", "sweep_id": sweep.get("sweep_id"),
                        "strategy_id": lead.get("strategy_id"), "name": lead.get("name"),
                    },
                    rationale=rationale, ltp_source=ltp_source,
                    data_as_of=consensus["data_as_of"], tags=[f"{inst['strike']:g} {option_word}", inst["expiry"]],
                ))

            # Index futures call when the daily technical score is decisive.
            if abs(daily_score) >= FUTURES_SCORE_GATE and scored:
                fut = await _nearest_future(symbol, "INDEX_FUTURE")
                if fut is not None:
                    calls.append(await _futures_call(dhan, fut, symbol, daily_score, scored[1], atr14, spot, last_session))
    # Stock futures: short side of the cash scan gets expressed here.
    for symbol, score, reasons, atr14, bars in scored_stocks:
        if abs(score) < FUTURES_SCORE_GATE:
            continue
        fut = await _nearest_future(symbol, "EQUITY_FUTURE")
        if fut is None:
            continue
        calls.append(await _futures_call(
            dhan, fut, symbol, score, reasons, atr14, bars[-1].close, _session_date(bars[-1].ts)
        ))
    return calls, note


async def _nearest_future(symbol: str, asset_class: str) -> dict | None:
    today_iso = _today_ist().isoformat()
    cursor = instruments_collection.find(
        {"asset_class": asset_class, "underlying_symbol": symbol, "expiry": {"$gte": today_iso}}
    ).sort("expiry", 1).limit(1)
    docs = [d async for d in cursor]
    return docs[0] if docs else None


async def _futures_call(
    dhan: DhanClient | None, fut: dict, symbol: str, score: float,
    reasons: list[str], atr14: float, spot: float, last_session,
) -> dict:
    live = await _ltp_batch(dhan, {fut["exchange_segment"]: [int(fut["security_id"])]})
    ltp = live.get((fut["exchange_segment"], str(fut["security_id"])))
    entry = ltp or spot
    ltp_source = "dhan_quote" if ltp else "last_bar_close"
    side = "BUY" if score > 0 else "SELL"
    sign = 1 if score > 0 else -1
    tick = fut.get("tick_size", 0.05)
    expiry_dt = datetime.fromisoformat(fut["expiry"]).date()
    validity = min(expiry_dt, _today_ist() + timedelta(days=7))
    return _call_doc(
        segment="FNO", horizon="POSITIONAL", side=side, symbol=symbol,
        display_name=f"{symbol} FUT",
        instrument=_instrument_ref(fut), entry=entry,
        target=_round_tick(entry + sign * POSITIONAL_TARGET_ATR * atr14, tick),
        stoploss=_round_tick(entry - sign * POSITIONAL_STOP_ATR * atr14, tick),
        call_expiry_date=validity.isoformat(),
        confidence=abs(score),
        source={"kind": "technical_scan", "strategy_id": None, "name": "Daily technical scan"},
        rationale="; ".join(reasons),
        ltp_source=ltp_source, data_as_of=last_session.isoformat(),
        tags=["FUT", fut["expiry"]],
    )


# --------------------------------------------------------------------------------
# COMMODITY segment (MCX futures, bars fetched from Dhan on demand)
# --------------------------------------------------------------------------------


async def _commodity_calls(dhan: DhanClient | None) -> tuple[list[dict], str | None]:
    underlyings = [
        u for u in await instruments_collection.distinct(
            "underlying_symbol", {"asset_class": "COMMODITY_FUTURE"}
        )
        if u in COMMODITY_WHITELIST
    ]
    if not underlyings:
        return [], (
            "MCX instruments are not loaded yet — run market-data-service/universe.py "
            "(it now includes MCX commodity futures), then generate again."
        )
    if dhan is None:
        return [], "Commodity calls need a connected Dhan account — MCX daily bars are fetched live, not stored locally."

    today = _today_ist()
    calls: list[dict] = []
    errors = 0
    for underlying in sorted(underlyings):
        fut = await _nearest_future(underlying, "COMMODITY_FUTURE")
        if fut is None:
            continue
        try:
            raw = await dhan.historical_daily(
                fut["security_id"], fut["exchange_segment"], "FUTCOM",
                (today - timedelta(days=400)).isoformat(), today.isoformat(),
            )
        except (DhanAPIError, Exception):
            errors += 1
            continue
        stamps = raw.get("timestamp") or []
        bars = [
            Bar(
                symbol=underlying, timeframe=Timeframe.D1,
                ts=datetime.fromtimestamp(stamps[i], tz=timezone.utc),
                open=raw["open"][i], high=raw["high"][i], low=raw["low"][i],
                close=raw["close"][i], volume=int(raw.get("volume", [0] * len(stamps))[i] or 0),
            )
            for i in range(len(stamps))
        ]
        scored = technical_score(bars)
        if scored is None:
            continue
        score, reasons, atr14 = scored
        if abs(score) < FUTURES_SCORE_GATE:
            continue
        calls.append(await _futures_call(
            dhan, fut, underlying, score, reasons, atr14, bars[-1].close, _session_date(bars[-1].ts)
        ))
    note = None
    if errors and not calls:
        note = "Dhan rejected the MCX history requests (token expired?) — reconnect the broker and generate again."
    return calls, note


# --------------------------------------------------------------------------------
# Public API: generate + refresh
# --------------------------------------------------------------------------------


async def generate_calls(dhan: DhanClient | None, segments: list[str] | None = None) -> dict:
    segments = segments or ["STOCK", "FNO", "COMMODITY"]
    notes: dict[str, str] = {}
    created: list[dict] = []

    scored_stocks = await _scored_daily_symbols() if {"STOCK", "FNO"} & set(segments) else []

    candidates: list[dict] = []
    if "STOCK" in segments:
        candidates += await _stock_calls(dhan, scored_stocks)
        if not scored_stocks:
            notes["STOCK"] = "No non-index symbols have local daily bars — backfill stocks in the market-data service to widen the scan."
    if "FNO" in segments:
        fno, note = await _fno_calls(dhan, scored_stocks)
        candidates += fno
        if note:
            notes["FNO"] = note
    if "COMMODITY" in segments:
        commodity, note = await _commodity_calls(dhan)
        candidates += commodity
        if note:
            notes["COMMODITY"] = note

    for call in candidates:
        if await _is_duplicate(call):
            continue
        await trading_calls_collection.insert_one(call)
        call.pop("_id", None)
        created.append(call)

    return {"created": len(created), "calls": created, "notes": notes, "scanned": len(candidates)}


async def refresh_calls(dhan: DhanClient | None) -> int:
    """Refresh LTPs and roll statuses for every live call. Returns updated count."""
    cursor = trading_calls_collection.find({"status": {"$in": ["OPEN", "PARTIAL_EXIT"]}})
    live_calls = [d async for d in cursor]
    if not live_calls:
        return 0

    wanted: dict[str, list[int]] = {}
    for call in live_calls:
        inst = call.get("instrument") or {}
        if inst.get("security_id") and inst.get("exchange_segment"):
            wanted.setdefault(inst["exchange_segment"], []).append(int(inst["security_id"]))
    quotes = await _ltp_batch(dhan, wanted)

    today = _today_ist()
    updated = 0
    for call in live_calls:
        inst = call.get("instrument") or {}
        key = (inst.get("exchange_segment"), str(inst.get("security_id")))
        ltp = quotes.get(key)
        changes: dict = {}
        if ltp:
            changes["ltp"] = round(ltp, 2)
            changes["ltp_source"] = "dhan_quote"
        elif inst.get("option_type") is None and call["segment"] != "COMMODITY":
            # cash/index/futures fall back to the last stored daily close
            bars = await to_thread.run_sync(load_bars, call["symbol"], Timeframe.D1, 0.1)
            if bars:
                changes["ltp"] = round(bars[-1].close, 2)
                changes["ltp_source"] = "last_bar_close"

        price = changes.get("ltp", call["ltp"])
        entry, target, stop = call["entry_price"], call["target"], call["stoploss"]
        sign = 1 if call["side"] == "BUY" else -1
        pnl_pct = sign * (price - entry) / entry * 100 if entry else None
        changes["pnl_pct"] = round(pnl_pct, 2) if pnl_pct is not None else None

        status = call["status"]
        hit_target = price >= target if sign > 0 else price <= target
        hit_stop = price <= stop if sign > 0 else price >= stop
        progress = sign * (price - entry) / abs(target - entry) if target != entry else 0

        if hit_target:
            status = "TARGET_HIT"
        elif hit_stop:
            status = "STOPLOSS"
        elif call["call_expiry_date"] < today.isoformat():
            status = "EXPIRED"
        elif progress >= 0.6 and status == "OPEN":
            # book part, trail the stop to entry — the call can no longer lose
            status = "PARTIAL_EXIT"
            changes["stoploss"] = entry
        if status != call["status"]:
            changes["status"] = status
            if status in ("TARGET_HIT", "STOPLOSS", "EXPIRED"):
                changes["closed_at"] = _now()
        if changes:
            changes["updated_at"] = _now()
            await trading_calls_collection.update_one({"_id": call["_id"]}, {"$set": changes})
            updated += 1
    return updated
