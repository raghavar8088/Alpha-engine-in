"""The evidence engine — the reason behind the trade.

A strategy signal is a CANDIDATE, never an entry. Before this desk commits capital it
assembles seven independent pillars of research and writes down, in plain English, what
each one found. That record is stored on the position at entry time and is what the UI
shows on the row.

WHY SEVEN PILLARS AND NOT ONE SCORE
------------------------------------
A single blended number cannot be argued with. Seven separate verdicts can: when a trade
goes wrong you can see that volume and momentum agreed, structure was intact, and it was
the news pillar that had nothing to say — which is a different lesson from "the model gave
it 0.71". Each pillar therefore returns its own score, its own verdict, and ONE sentence.

WRITTEN AT ENTRY TIME, NEVER REGENERATED
-----------------------------------------
The sentences are computed from the data available at the moment of entry and stored. They
are never recomputed later against newer data, because a "reason" that updates itself is
not a reason — it is a post-hoc justification, and it would always look prescient.

THE VETO IS NOT A LOW SCORE
----------------------------
Four conditions stop a trade regardless of how the other pillars voted: the index regime
is hostile, the live quote disagrees with the stored bars, the name is too illiquid to
exit, or genuinely negative news landed in the last 24 hours. These are not weighted in
with everything else, because a stock can look perfect on six dimensions and still be a
stock you cannot get out of.

HONEST LIMITS OF THE NEWS PILLAR — read this before trusting it
----------------------------------------------------------------
`research_service` ingests three market-wide RSS feeds (ET Markets, Moneycontrol, LiveMint)
and stores HEADLINES AND SUMMARIES ONLY — that is what those publishers syndicate. It is
not per-stock coverage. Many names will legitimately have no news, and this pillar says so
rather than inventing something. Sentiment requires `ai-service` to have a provider key;
without one the pillar reports `sentiment: not-configured` and NEVER guesses a direction
from keywords. Consequently news is VETO-CAPABLE BUT NOT REQUIRED: "no news" is neutral.
A design that required positive news would simply never trade.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from strategy_service.indicators import adx, ema, rsi, sma

from app.core.db import research_signals_collection
from app.services import commodity_patterns as CP
from app.services.strategy_factory.primitives import classify_regime

logger = logging.getLogger("trending_stocks.evidence")

# How many of the seven pillars must actively SUPPORT the trade.
MIN_PILLARS = int(os.getenv("TS_MIN_PILLARS", "5"))

# Liquidity floor: median daily turnover below this and the desk will not size into it.
MIN_TURNOVER = float(os.getenv("TS_MIN_TURNOVER", "50000000"))       # ₹5 crore
NEWS_LOOKBACK_HOURS = int(os.getenv("TS_NEWS_HOURS", "72"))
NEWS_VETO_HOURS = int(os.getenv("TS_NEWS_VETO_HOURS", "24"))

SUPPORTS, NEUTRAL, OPPOSES, VETO = "supports", "neutral", "opposes", "veto"

PILLARS = ["volume", "momentum", "news", "price_action", "pattern", "regime", "liquidity"]


@dataclass
class Pillar:
    name: str
    verdict: str
    score: float
    sentence: str
    facts: dict = field(default_factory=dict)

    def as_doc(self) -> dict:
        return {"name": self.name, "verdict": self.verdict, "score": round(self.score, 3),
                "sentence": self.sentence, "facts": self.facts}


@dataclass
class Evidence:
    ok: bool
    supports: int
    required: int
    score: float
    pillars: list[Pillar]
    vetoes: list[str] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """The sentences, strongest support first — this is what goes on the position."""
        ordered = sorted(self.pillars, key=lambda p: -p.score)
        return [p.sentence for p in ordered]

    def as_doc(self) -> dict:
        return {"ok": self.ok, "supports": self.supports, "required": self.required,
                "score": round(self.score, 3), "vetoes": self.vetoes,
                "reasons": self.reasons,
                "pillars": [p.as_doc() for p in self.pillars]}

    def summary(self) -> str:
        if self.vetoes:
            return f"NO TRADE — {self.vetoes[0]}"
        if not self.ok:
            return (f"NO TRADE — only {self.supports} of {len(self.pillars)} research "
                    f"pillars support this (needs {self.required})")
        return (f"{self.supports} of {len(self.pillars)} pillars support this trade, "
                "no vetoes")


def _closes(bars) -> list[float]:
    return [b.close for b in bars]


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _obv_slope(bars, window: int = 30) -> float:
    """Sign-weighted volume accumulation over the window, normalised by total volume, so
    it is comparable between a heavily-traded large cap and a thin one."""
    seg = bars[-(window + 1):]
    if len(seg) < 5:
        return 0.0
    net = total = 0.0
    for prev, cur in zip(seg, seg[1:]):
        v = cur.volume or 0.0
        total += v
        net += v if cur.close > prev.close else (-v if cur.close < prev.close else 0.0)
    return net / total if total else 0.0


# --------------------------------------------------------------------------------
# 1. Volume
# --------------------------------------------------------------------------------


def volume_pillar(bars, window: int = 20) -> Pillar:
    if len(bars) < window + 2:
        return Pillar("volume", NEUTRAL, 0.0,
                      "Not enough bars to judge participation.", {"bars": len(bars)})
    hist = [b.volume for b in bars[-(window + 1):-1] if b.volume is not None]
    cur = bars[-1].volume or 0.0
    med = statistics.median(hist) if hist else 0.0
    if med <= 0:
        return Pillar("volume", NEUTRAL, 0.0,
                      "No volume is reported for this series, so participation cannot be "
                      "confirmed either way.", {"median": med})
    rvol = cur / med
    obv = _obv_slope(bars)
    facts = {"rvol": round(rvol, 2), "median_volume": round(med), "obv_slope": round(obv, 3)}

    if rvol >= 1.5 and obv > 0.05:
        return Pillar("volume", SUPPORTS, min(1.0, 0.4 + rvol / 5),
                      f"Traded {rvol:.1f}x its {window}-bar median volume with net "
                      f"accumulation ({obv:+.0%} of volume on up bars) — participation is "
                      "confirming the move.", facts)
    if rvol >= 1.2:
        return Pillar("volume", SUPPORTS, 0.35,
                      f"Volume {rvol:.1f}x the {window}-bar median — above normal, though "
                      "not exceptional.", facts)
    if rvol < 0.7:
        return Pillar("volume", OPPOSES, -0.4,
                      f"Only {rvol:.1f}x median volume — this move is happening on air, "
                      "which is how breakouts fail.", facts)
    return Pillar("volume", NEUTRAL, 0.05,
                  f"Volume {rvol:.1f}x the {window}-bar median — ordinary participation.",
                  facts)


# --------------------------------------------------------------------------------
# 2. Momentum
# --------------------------------------------------------------------------------


def momentum_pillar(daily, bench_daily=None) -> Pillar:
    if len(daily) < 25:
        return Pillar("momentum", NEUTRAL, 0.0,
                      "Fewer than 25 daily bars — momentum cannot be measured yet.",
                      {"daily_bars": len(daily)})
    c = _closes(daily)
    r5 = _pct(c[-1], c[-6]) if len(c) > 6 else 0.0
    r20 = _pct(c[-1], c[-21]) if len(c) > 21 else 0.0
    r60 = _pct(c[-1], c[-61]) if len(c) > 61 else r20

    try:
        rsi_now = rsi(c, 14)[-1]
    except (ValueError, IndexError):
        rsi_now = 50.0
    try:
        adx_now = adx(daily, 14)[0][-1]
    except (ValueError, IndexError):
        adx_now = 0.0

    high_252 = max(b.high for b in daily[-252:])
    from_high = _pct(c[-1], high_252)

    rs = None
    if bench_daily and len(bench_daily) > 21:
        bc = _closes(bench_daily)
        rs = r20 - _pct(bc[-1], bc[-21])

    facts = {"ret_5d": round(r5, 2), "ret_20d": round(r20, 2), "ret_60d": round(r60, 2),
             "rsi": round(rsi_now, 1), "adx": round(adx_now, 1),
             "pct_from_252d_high": round(from_high, 2),
             "rs_vs_benchmark_20d": round(rs, 2) if rs is not None else None}

    rs_txt = (f", outperforming the index by {rs:+.1f} points over 20 sessions"
              if rs is not None else "")
    positives = sum([r20 > 0, r60 > 0, rsi_now >= 55, adx_now >= 20, from_high > -15])

    if positives >= 4:
        return Pillar("momentum", SUPPORTS, min(1.0, 0.45 + positives * 0.1),
                      f"Up {r5:+.1f}% in 5 sessions and {r20:+.1f}% in a month{rs_txt}; "
                      f"RSI {rsi_now:.0f}, ADX {adx_now:.0f}, and it is {abs(from_high):.1f}% "
                      "below its 52-week high.", facts)
    if positives >= 3:
        return Pillar("momentum", SUPPORTS, 0.35,
                      f"Mildly positive: {r20:+.1f}% over a month{rs_txt}, RSI "
                      f"{rsi_now:.0f}, ADX {adx_now:.0f}.", facts)
    if r20 < -5 and rsi_now < 45:
        return Pillar("momentum", OPPOSES, -0.5,
                      f"Down {r20:.1f}% over the month with RSI {rsi_now:.0f} — this is a "
                      "falling stock, not a trending one.", facts)
    return Pillar("momentum", NEUTRAL, 0.0,
                  f"Mixed: {r20:+.1f}% over a month, RSI {rsi_now:.0f}, ADX {adx_now:.0f}.",
                  facts)


# --------------------------------------------------------------------------------
# 3. News
# --------------------------------------------------------------------------------

_SUFFIXES = {"LIMITED", "LTD", "LTD.", "THE", "COMPANY", "CO", "CORPORATION", "CORP",
             "INDIA", "INDIAN", "&", "AND", "OF", "PVT", "PRIVATE"}


def news_aliases(symbol: str, name: str | None) -> list[str]:
    """Company-name aliases for a symbol.

    `research_service.normalize.detect_symbols` matches tickers only — it finds "RELIANCE"
    but not "Reliance Industries said". This widens that to the instrument master's own
    company name, with corporate suffixes stripped, which is where most headline mentions
    actually live. Aliases shorter than four characters are dropped: a three-letter token
    matches half the newspaper."""
    out = {symbol.upper()}
    if name:
        words = [w for w in re.split(r"[^A-Za-z0-9]+", name.upper()) if w]
        core = [w for w in words if w not in _SUFFIXES]
        if core:
            out.add(" ".join(core[:2]))
            out.add(core[0])
    return sorted({a for a in out if len(a) >= 4})


async def news_pillar(symbol: str, name: str | None = None,
                      hours: int = NEWS_LOOKBACK_HOURS) -> Pillar:
    """Headlines mentioning this name in the lookback window, with AI sentiment when a
    provider is configured and an explicit `not-configured` when one is not."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    aliases = news_aliases(symbol, name)
    patterns = [re.compile(rf"\b{re.escape(a)}\b", re.I) for a in aliases]

    hits: list[dict] = []
    try:
        async for d in research_signals_collection.find(
                {"timestamp": {"$gte": cutoff}}).sort("timestamp", -1).limit(400):
            text = f"{d.get('reasoning') or ''} {d.get('symbol') or ''}"
            if d.get("symbol", "").upper() == symbol.upper() or any(p.search(text) for p in patterns):
                hits.append(d)
    except Exception as exc:  # noqa: BLE001 — the news store must never break a scan
        logger.warning("[trending_stocks] news lookup failed for %s: %s", symbol, exc)
        return Pillar("news", NEUTRAL, 0.0,
                      "The news store could not be read this cycle, so news is unknown "
                      "rather than absent.", {"error": str(exc)[:160]})

    facts = {"headlines": len(hits), "lookback_hours": hours, "aliases": aliases,
             "sources": sorted({h.get("source") for h in hits if h.get("source")}),
             "sentiment": "not-configured"}

    if not hits:
        return Pillar("news", NEUTRAL, 0.0,
                      f"No headlines found for {symbol} in the last {hours} hours across "
                      "the three syndicated market feeds — this is broad market news, not "
                      "per-stock coverage, so silence here is not a negative.", facts)

    recent = [h for h in hits
              if (h.get("timestamp") and h["timestamp"] >=
                  datetime.now(timezone.utc) - timedelta(hours=NEWS_VETO_HOURS))]
    sentiment, summary = await _news_sentiment(hits[:8])
    facts["sentiment"] = sentiment
    facts["recent_24h"] = len(recent)
    if summary:
        facts["ai_summary"] = summary[:400]

    titles = "; ".join((h.get("reasoning") or "")[:90] for h in hits[:2])
    if sentiment == "bearish" and recent:
        return Pillar("news", VETO, -1.0,
                      f"{len(recent)} headline(s) in the last {NEWS_VETO_HOURS}h read "
                      f"bearish for {symbol}: {titles}", facts)
    if sentiment == "bullish":
        return Pillar("news", SUPPORTS, 0.6,
                      f"{len(hits)} headline(s) in {hours}h, read bullish: {titles}", facts)
    if sentiment == "not-configured":
        return Pillar("news", SUPPORTS if len(hits) >= 2 else NEUTRAL,
                      0.3 if len(hits) >= 2 else 0.1,
                      f"{len(hits)} headline(s) mention {symbol} in the last {hours}h "
                      f"({', '.join(facts['sources']) or 'unknown source'}) — the desk is "
                      "counting coverage, not reading it: no AI provider is configured, so "
                      f"no sentiment is claimed. Latest: {titles}", facts)
    return Pillar("news", NEUTRAL, 0.1,
                  f"{len(hits)} headline(s) in {hours}h, read {sentiment}: {titles}", facts)


async def _news_sentiment(articles: list[dict]) -> tuple[str, str | None]:
    """Sentiment via `ai-service`, or an honest 'not-configured'.

    Deliberately NO keyword lexicon fallback. A bag of positive and negative words applied
    to financial headlines produces a number that looks like sentiment and is not one, and
    this desk would then veto real trades on it."""
    try:
        from ai_service.modules import summarize_news
        from ai_service.provider import get_provider
        provider = get_provider()
        if not provider.configured:
            return "not-configured", None
        payload = [{"title": (a.get("reasoning") or "")[:200], "source": a.get("source"),
                    "published_at": str(a.get("timestamp"))} for a in articles]
        res = await summarize_news(payload, provider)
        if not isinstance(res, dict) or res.get("status") == "not_configured":
            return "not-configured", None
        return str(res.get("sentiment") or "neutral"), res.get("summary")
    except Exception as exc:  # noqa: BLE001
        logger.info("[trending_stocks] news sentiment unavailable: %s", exc)
        return "not-configured", None


# --------------------------------------------------------------------------------
# 4. Price action
# --------------------------------------------------------------------------------


def price_action_pillar(bars, daily, pivot: int = 4) -> Pillar:
    if len(bars) < 30:
        return Pillar("price_action", NEUTRAL, 0.0,
                      "Too few bars to read structure.", {"bars": len(bars)})
    highs, lows = CP.pivots(bars, pivot, pivot)
    hh = hl = 0
    for a, b in zip(highs, highs[1:]):
        hh += 1 if bars[b].high > bars[a].high else -1
    for a, b in zip(lows, lows[1:]):
        hl += 1 if bars[b].low > bars[a].low else -1
    intact = hh > 0 and hl > 0

    last = bars[-1]
    rng = last.high - last.low
    close_pos = ((last.close - last.low) / rng) if rng > 0 else 0.5

    above: list[str] = []
    below: list[str] = []
    dc = _closes(daily) if daily else []
    for period in (20, 50, 200):
        if len(dc) > period:
            m = sma(dc, period)
            if m:
                (above if dc[-1] > m[-1] else below).append(f"{period}-DMA")

    facts = {"structure_intact": intact, "swing_highs": len(highs), "swing_lows": len(lows),
             "close_position_in_bar": round(close_pos, 3),
             "above": above, "below": below}

    bits = []
    if intact:
        bits.append(f"higher highs and higher lows intact across {min(len(highs), len(lows))} swings")
    elif hh <= 0 and hl <= 0:
        bits.append("the swing sequence is making lower highs and lower lows")
    else:
        bits.append("the swing sequence is mixed")
    if above:
        bits.append(f"trading above its {', '.join(above)}")
    if below:
        bits.append(f"below its {', '.join(below)}")
    bits.append(f"closed in the top {(1-close_pos)*100:.0f}% of the signal bar"
                if close_pos >= 0.5 else
                f"closed in the bottom {close_pos*100:.0f}% of the signal bar")
    sentence = (bits[0][0].upper() + bits[0][1:]) + "; " + "; ".join(bits[1:]) + "."

    score = 0.0
    score += 0.4 if intact else (-0.4 if (hh <= 0 and hl <= 0) else 0.0)
    score += 0.15 * len(above) - 0.15 * len(below)
    score += 0.2 if close_pos >= 0.6 else (-0.2 if close_pos < 0.35 else 0.0)
    verdict = SUPPORTS if score >= 0.3 else OPPOSES if score <= -0.3 else NEUTRAL
    return Pillar("price_action", verdict, max(-1.0, min(1.0, score)), sentence, facts)


# --------------------------------------------------------------------------------
# 5. Chart pattern
# --------------------------------------------------------------------------------


def pattern_pillar(signal) -> Pillar:
    """The firing setup itself, plus how clean its geometry was.

    Uses the signal's own confidence and the feasibility report's overhead count: a
    pattern that fired with a structural stop and a clear path is a better version of the
    same pattern than one that scraped through."""
    feas = (signal.meta or {}).get("feasibility") or {}
    tests = feas.get("tests") or {}
    overhead = tests.get("overhead_count", 0)
    facts = {"pattern": signal.pattern, "detail": signal.detail,
             "confirmations": signal.confirmations, "confidence": signal.confidence,
             "stop_basis": feas.get("stop_basis"), "overhead_levels": overhead,
             "r_multiple": feas.get("r_multiple")}
    confirms = "; ".join(signal.confirmations[:3]) if signal.confirmations else "no extra confirmations"
    clear = ("no known supply between here and target" if not overhead
             else f"{overhead} known level(s) overhead, all beyond the halfway mark")
    score = 0.3 + 0.4 * (signal.confidence - 0.5)
    if feas.get("stop_basis") == "structural":
        score += 0.15
    verdict = SUPPORTS if score >= 0.3 else NEUTRAL
    return Pillar("pattern", verdict, max(-1.0, min(1.0, score)),
                  f"{signal.pattern}: {signal.detail}. Confirmed by {confirms}; {clear}.",
                  facts)


# --------------------------------------------------------------------------------
# 6. Market regime
# --------------------------------------------------------------------------------


def regime_pillar(bars, bench_daily) -> Pillar:
    """The stock's own regime AND the index's.

    Momentum's catastrophic losses are not randomly distributed — Daniel & Moskowitz
    showed they cluster in panic states, after market declines and during the rebound. So
    the index is a VETO here, not a weighted input: when the market is below its long
    average, this desk stops opening new longs regardless of how good one chart looks."""
    state = classify_regime(bars)
    facts = {"symbol_regime": state.primary, "tags": sorted(state.tags),
             "adx": state.adx, "atr_pct": state.atr_pct}

    if not bench_daily or len(bench_daily) < 210:
        facts["index"] = "insufficient index history"
        return Pillar("regime", NEUTRAL if state.primary in ("strong_bull", "weak_bull") else OPPOSES,
                      0.2 if state.primary in ("strong_bull", "weak_bull") else -0.2,
                      f"Stock is in {state.primary.replace('_', ' ')} (ADX {state.adx}); the "
                      "index regime could not be checked — not enough benchmark history.",
                      facts)

    bc = _closes(bench_daily)
    ma200 = sma(bc, 200)
    index_ok = bool(ma200) and bc[-1] > ma200[-1]
    idx_state = classify_regime(bench_daily)
    facts.update({"index_above_200dma": index_ok, "index_regime": idx_state.primary,
                  "index_atr_pct": idx_state.atr_pct})

    if not index_ok:
        return Pillar("regime", VETO, -1.0,
                      f"The index is below its 200-day average ({bc[-1]:,.0f} vs "
                      f"{ma200[-1]:,.0f}) — this desk does not open new longs into a market "
                      "in that state, whatever one chart says.", facts)
    if "high_volatility" in idx_state.tags:
        return Pillar("regime", VETO, -1.0,
                      f"Index volatility is in the top quartile of its own recent range "
                      f"(ATR {idx_state.atr_pct}% of price) — the state where momentum "
                      "reversals cluster.", facts)

    bull = state.primary in ("strong_bull", "weak_bull") or "breakout" in state.tags
    if bull:
        return Pillar("regime", SUPPORTS, 0.6,
                      f"Stock is in {state.primary.replace('_', ' ')} (ADX {state.adx}) and "
                      f"the index is above its 200-day average in a {idx_state.primary.replace('_', ' ')} "
                      "state.", facts)
    return Pillar("regime", NEUTRAL, 0.0,
                  f"Index conditions are fine, but the stock itself reads "
                  f"{state.primary.replace('_', ' ')} (ADX {state.adx}).", facts)


# --------------------------------------------------------------------------------
# 7. Liquidity
# --------------------------------------------------------------------------------


def liquidity_pillar(daily, ltp: float | None, quote_ok: bool, quote_note: str,
                     quote_source: str | None = None) -> Pillar:
    facts = {"ltp": ltp, "quote_ok": quote_ok, "quote_note": quote_note,
             "ltp_source": quote_source}
    if not quote_ok:
        return Pillar("liquidity", VETO, -1.0,
                      f"Quote check failed — {quote_note}. The strategies read bars and "
                      "the desk fills at the live price; those two must describe the same "
                      "instrument.", facts)
    if not daily or len(daily) < 20:
        return Pillar("liquidity", NEUTRAL, 0.0,
                      "Not enough daily history to measure turnover.", facts)

    turnovers = [b.close * (b.volume or 0) for b in daily[-20:]]
    med = statistics.median(turnovers)
    facts["median_turnover_20d"] = round(med)
    if med < MIN_TURNOVER:
        return Pillar("liquidity", VETO, -1.0,
                      f"Median daily turnover is only ₹{med/1e7:.2f} crore, below the "
                      f"₹{MIN_TURNOVER/1e7:.1f} crore floor — a position here is easy to "
                      "enter and hard to leave.", facts)
    return Pillar("liquidity", SUPPORTS, 0.5,
                  f"₹{med/1e7:.1f} crore median daily turnover; {quote_note}"
                  + (f" via {quote_source}." if quote_source else "."), facts)


# --------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------


def assemble(pillars: list[Pillar], required: int | None = None) -> Evidence:
    """Apply the entry gate to a set of pillars.

    THE RULE LIVES HERE AND ONLY HERE. The engine builds its pillars in pieces so it can
    cache the symbol-level ones across 678 strategies, and it would have been easy to let
    it re-implement "no veto AND at least N supports" inline — at which point the page,
    the engine and this module could disagree about what a passing trade is. One
    function, one definition.

    A VETO is not a low score. Four conditions stop a trade regardless of how the rest
    voted: a hostile index regime, a live quote that disagrees with the stored bars, a
    name too illiquid to exit, and genuinely negative news in the last 24 hours. A stock
    can look perfect on six dimensions and still be one you cannot get out of."""
    req = int(required if required is not None else MIN_PILLARS)
    vetoes = [p.sentence for p in pillars if p.verdict == VETO]
    supports = sum(1 for p in pillars if p.verdict == SUPPORTS)
    score = sum(p.score for p in pillars) / len(pillars) if pillars else 0.0
    return Evidence(ok=(not vetoes and supports >= req), supports=supports,
                    required=req, score=score, pillars=pillars, vetoes=vetoes)


async def gather(*, symbol: str, name: str | None, signal, entry_bars, daily_bars,
                 bench_daily, ltp: float | None, quote_ok: bool, quote_note: str,
                 quote_source: str | None = None, pivot: int = 4,
                 min_pillars: int | None = None) -> Evidence:
    """All seven pillars for one candidate signal, assembled in one call.

    The engine does NOT use this — it builds the same pillars in two cached groups because
    the symbol-level ones (momentum, news, liquidity) are identical for all 678 strategies
    looking at that symbol this cycle, and recomputing them per strategy would mean 678
    news lookups per symbol per tick. This is the straightforward path for a single
    signal, and it ends in the same `assemble()` the engine calls."""
    return assemble([
        volume_pillar(entry_bars),
        momentum_pillar(daily_bars, bench_daily),
        await news_pillar(symbol, name),
        price_action_pillar(entry_bars, daily_bars, pivot),
        pattern_pillar(signal),
        regime_pillar(entry_bars, bench_daily),
        liquidity_pillar(daily_bars, ltp, quote_ok, quote_note, quote_source),
    ], min_pillars)


__all__ = ["Evidence", "Pillar", "assemble", "gather", "PILLARS", "MIN_PILLARS", "news_aliases",
           "volume_pillar", "momentum_pillar", "news_pillar", "price_action_pillar",
           "pattern_pillar", "regime_pillar", "liquidity_pillar",
           "SUPPORTS", "NEUTRAL", "OPPOSES", "VETO"]
