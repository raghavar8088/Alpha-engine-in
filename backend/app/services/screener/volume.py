"""Volume gainers for the day, the week and the month — and whether price is going with it.

THE QUESTION THIS TAB EXISTS TO ANSWER is not "what traded a lot", which is just a list of
large caps. It is "what traded FAR MORE THAN IT USUALLY DOES, and did price go anywhere on
it". Volume without price movement and price movement without volume are both meaningful,
and they mean opposite things, so the two are always reported together and never collapsed
into one score.

FIVE STATES, and the distinction between them is the whole point:

  ACCUMULATION   price up, volume up      buyers are paying up; the move has fuel behind it
  DISTRIBUTION   price down, volume up    sellers are hitting bids; a decline with conviction
  WEAK RALLY     price up, volume DOWN    a drift, not a move — nobody is defending it
  SELLING DRIED  price down, volume down  the sellers have finished; often where bases start
  CHURN          volume up, price flat    heavy two-way trade at one level — stock changing
                                          hands. Frequently precedes a move, direction unknown.

Calling a WEAK RALLY a "volume gainer" without that label would be the most misleading thing
this module could do, because it looks identical to accumulation in a sorted table.

DELIVERY IS THE TIEBREAKER. From the NSE bhavcopy: what share of the day's volume actually
went to a demat rather than being squared off. High volume on low delivery is traders passing
stock around; high volume on high delivery is someone taking it home. Only meaningful against
the stock's own average, which `bhavcopy.delivery_stats` supplies.

NEXT TARGET IS ALWAYS LABELLED WITH HOW IT WAS DERIVED. There is no single honest "target
price" for a stock, so this reports the method alongside the number and orders the methods by
how much they are actually worth: a chart pattern's own measured move beats a prior swing
high, which beats a base projection, which beats an ATR multiple. An ATR-projected target is
arithmetic on volatility, not a forecast, and it says so.
"""

from __future__ import annotations

import logging
import os

from app.services.screener import horizons as H

logger = logging.getLogger("screener.volume")

WINDOWS = {"1d": 1, "1w": 5, "1m": 21}
WINDOW_LABELS = {"1d": "Today", "1w": "This Week", "1m": "This Month"}
WINDOW_ORDER = ["1d", "1w", "1m"]

MIN_VOL_RATIO = float(os.getenv("SCREENER_MIN_VOL_RATIO", "1.5"))
FLAT_PCT = 1.0          # |return| under this counts as "flat" for the churn label
STRONG_VOL = 3.0
HIGH_DELIVERY_RATIO = 1.3   # delivery running 30% above its own average

STATES = {
    "accumulation": "Price up on rising volume — buyers paying up",
    "distribution": "Price down on rising volume — sellers hitting bids",
    "weak_rally": "Price up but volume FALLING — a drift with nothing behind it",
    "selling_dried": "Price down on falling volume — sellers running out",
    "churn": "Heavy volume, price going nowhere — stock changing hands",
}


def classify(ret_pct: float | None, vol_ratio: float | None) -> tuple[str, str]:
    """(state key, plain-English explanation). Unknown when either input is missing."""
    if ret_pct is None or vol_ratio is None:
        return "unknown", "Not enough history to compare volume against its own average"
    heavy = vol_ratio >= 1.2
    light = vol_ratio < 0.9
    if abs(ret_pct) < FLAT_PCT and heavy:
        return "churn", STATES["churn"]
    if ret_pct > 0:
        if heavy:
            return "accumulation", STATES["accumulation"]
        if light:
            return "weak_rally", STATES["weak_rally"]
        return "accumulation", STATES["accumulation"]
    if heavy:
        return "distribution", STATES["distribution"]
    if light:
        return "selling_dried", STATES["selling_dried"]
    return "distribution", STATES["distribution"]


def next_target(bars: list[H.Bar], price: float, pattern_hits: list[dict] | None,
                atr: float | None) -> dict:
    """The next level up, with the method that produced it stated.

    Ordered by how much each method is actually worth. Every branch names itself so a
    reader can weigh it; a bare number here would imply a confidence none of these have.
    """
    hits = [h for h in (pattern_hits or []) if h.get("direction") == "bullish"]
    # 1. A chart pattern's own measured move — the only target derived from the shape
    #    the market actually drew.
    triggered = [h for h in hits if h.get("state") == "TRIGGERED"]
    for pool, note in ((triggered, "triggered"), (hits, "forming")):
        if pool:
            best = max(pool, key=lambda h: h.get("confidence") or 0)
            if best.get("target") and best["target"] > price:
                return {
                    "target": round(best["target"], 2),
                    "upside_pct": round((best["target"] / price - 1) * 100, 2),
                    "method": f"{best['pattern']} measured move ({note})",
                    "strength": "strong" if note == "triggered" else "moderate",
                    "note": best.get("rationale"),
                }

    # 2. The nearest level price previously turned back from.
    resistance = H.nearest_resistance_above(bars, price)
    if resistance:
        return {
            "target": round(resistance, 2),
            "upside_pct": round((resistance / price - 1) * 100, 2),
            "method": "nearest prior swing high",
            "strength": "moderate",
            "note": "The last level this stock turned back from — the first thing that has to give way",
        }

    # 3. At new highs there is no overhead level, so project the recent base's height.
    high20 = H.donchian_high(bars, 20)
    low20 = H.donchian_low(bars, 20)
    if high20 and low20 and high20 > low20 and price >= high20 * 0.995:
        projected = price + (high20 - low20)
        return {
            "target": round(projected, 2),
            "upside_pct": round((projected / price - 1) * 100, 2),
            "method": "measured move — 20-session base height projected up",
            "strength": "moderate",
            "note": "No overhead resistance: the stock is at or above its 20-session high",
        }

    # 4. Volatility arithmetic. Weakest, and labelled as such.
    if atr and atr > 0:
        projected = price + 3 * atr
        return {
            "target": round(projected, 2),
            "upside_pct": round((projected / price - 1) * 100, 2),
            "method": "3x ATR projection",
            "strength": "weak",
            "note": "Arithmetic on volatility, not a forecast — no level or pattern supports this",
        }

    return {"target": None, "upside_pct": None, "method": "none available",
            "strength": "none",
            "note": "No pattern, no overhead level and no usable ATR — no honest target"}


def volume_reason(row: dict, state: str, vol_ratio: float | None,
                  delivery: dict | None, sector_ctx: dict | None,
                  pattern_hits: list[dict] | None) -> list[str]:
    """Why the volume is there. Evidence only — an empty list is a valid answer."""
    out: list[str] = []

    if vol_ratio is not None and vol_ratio >= STRONG_VOL:
        out.append(f"Volume is {vol_ratio:.1f}x its own recent average — far outside this "
                   f"stock's normal participation")
    elif vol_ratio is not None and vol_ratio >= MIN_VOL_RATIO:
        out.append(f"Volume is {vol_ratio:.1f}x its own recent average")

    if delivery:
        dp, ratio = delivery.get("delivery_pct"), delivery.get("delivery_ratio")
        if dp is not None and ratio is not None and ratio >= HIGH_DELIVERY_RATIO:
            out.append(f"{dp:.0f}% of it went to delivery against a {delivery['delivery_avg']:.0f}% "
                       f"average — this is being taken home, not traded around")
        elif dp is not None and ratio is not None and ratio < 0.8:
            out.append(f"Only {dp:.0f}% delivery against a {delivery['delivery_avg']:.0f}% "
                       f"average — heavy volume but it is intraday churn, not accumulation")
        elif dp is not None:
            out.append(f"{dp:.0f}% delivery")
        trades = delivery.get("trades")
        if trades and delivery.get("delivery_qty"):
            avg_ticket = delivery["delivery_qty"] / trades
            if avg_ticket > 500:
                out.append(f"Average delivered quantity per trade is {avg_ticket:,.0f} shares — "
                           f"large tickets, which is institutional rather than retail")

    brk = row.get("breakout")
    if brk:
        out.append(f"It broke its {brk['window']}-session high on {brk['date']} — volume "
                   f"arriving on a breakout is the confirmation the breakout needs")

    if pattern_hits:
        trig = [h for h in pattern_hits if h.get("state") == "TRIGGERED"]
        if trig:
            # .get throughout: this builds a display string, and a hit that is missing an
            # optional label must cost the label, never the whole reason list.
            tf = (trig[0].get("timeframe_label") or trig[0].get("timeframe") or "").lower()
            where = f" on the {tf} chart" if tf else ""
            out.append(f"A {trig[0].get('pattern', 'chart pattern')} completed{where} "
                       f"at the same time")

    if sector_ctx and sector_ctx.get("return_pct") is not None:
        sr = sector_ctx["return_pct"]
        if abs(sr) >= 1.5:
            out.append(f"{sector_ctx['sector']} is {sr:+.1f}% over the same window — the volume "
                       f"is sector-wide, not specific to this name")

    if state == "churn":
        out.append("Price has not moved despite the volume — someone is absorbing supply at "
                   "this level, and the direction it resolves is not yet decided")
    elif state == "weak_rally":
        out.append("Note the volume is BELOW average — this rise is not being paid for")

    return out


async def board(index: str | None = None, window: str = "1d", limit: int = 60,
                state_filter: str | None = None, fresh: bool = False) -> dict:
    """Volume gainers over one window, with price-volume state, reasons and a target."""
    from app.services.screener import bhavcopy, patterns, sectors
    from app.services.screener.momentum import DEFAULT_INDEX, universe_snapshot

    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r}; expected one of {WINDOW_ORDER}")

    index = index or DEFAULT_INDEX
    sessions = WINDOWS[window]
    snap = await universe_snapshot(index, fresh=fresh)
    symbols = [r["symbol"] for r in snap["rows"]]
    bars_by_sym = await H.load_daily_bars(symbols, fresh=fresh)

    delivery = await bhavcopy.delivery_stats()
    scan = await patterns.scan(index, fresh=False)
    hits_by_sym: dict[str, list[dict]] = {}
    for h in scan["rows"]:
        hits_by_sym.setdefault(h["symbol"], []).append(h)

    horizon = {"1d": "1d", "1w": "1w", "1m": "1m"}[window]
    sector_board = sectors.roll_up(snap, horizon)
    sector_index = {s["sector"]: s for s in sector_board["sectors"]}

    rows = []
    for r in snap["rows"]:
        bars = bars_by_sym.get(r["symbol"]) or []
        cur, base = H.window_volume(bars, sessions)
        if not cur or not base or base <= 0:
            continue
        vol_ratio = cur / base
        ret = r["returns"].get(horizon)
        state, state_text = classify(ret, vol_ratio)
        if state_filter and state != state_filter:
            continue
        if vol_ratio < MIN_VOL_RATIO:
            continue

        d = delivery.get(r["symbol"])
        sec = sector_index.get(r["sector"]) or {}
        hits = hits_by_sym.get(r["symbol"], [])
        tgt = next_target(bars, r["ltp"], hits, r.get("atr14"))

        # DELIVERY CAN CONTRADICT THE STATE, and when it does that is the more important
        # fact. Price up on heavy volume reads as "accumulation" by definition — but the
        # top of this board is routinely full of names whose delivery collapsed to 7%
        # against a 41% average, which is the same stock being passed between traders all
        # day and squared off by the close. That is very nearly the opposite of
        # accumulation. The state stays a pure price-volume fact, because that is what it
        # measures; the conflict gets its own flag so the table can show the disagreement
        # instead of leaving the label to be read as a verdict it cannot support.
        dratio = (d or {}).get("delivery_ratio")
        conflict = None
        if dratio is not None:
            if state == "accumulation" and dratio <= 0.6:
                conflict = ("Delivery collapsed to "
                            f"{dratio:.2f}x its average — the volume is being squared off "
                            f"intraday, so this is not the accumulation the price-volume "
                            f"reading implies")
            elif state == "distribution" and dratio >= 1.4:
                conflict = (f"Delivery ran at {dratio:.2f}x its average even as price fell — "
                            f"someone is taking stock on the way down, which is not ordinary "
                            f"distribution")

        rows.append({
            "symbol": r["symbol"],
            "name": r.get("name"),
            "sector": r["sector"],
            "ltp": r["ltp"],
            "return_pct": ret,
            "volume_ratio": round(vol_ratio, 2),
            "volume": cur,
            "volume_baseline": base,
            "turnover": r.get("turnover"),
            "delivery_pct": (d or {}).get("delivery_pct"),
            "delivery_avg": (d or {}).get("delivery_avg"),
            "delivery_ratio": (d or {}).get("delivery_ratio"),
            "trades": (d or {}).get("trades"),
            "state": state,
            "state_label": state.replace("_", " ").title(),
            "state_text": state_text,
            "price_confirms": state in ("accumulation", "distribution"),
            "delivery_conflict": conflict,
            "sector_return_pct": sec.get("return_pct"),
            "reasons": volume_reason(r, state, vol_ratio, d,
                                     {"sector": r["sector"], "return_pct": sec.get("return_pct")},
                                     hits),
            "target": tgt,
            "patterns": [{"pattern": h["pattern"], "state": h["state"],
                          "timeframe": h["timeframe"]} for h in hits[:3]],
        })

    rows.sort(key=lambda x: -x["volume_ratio"])

    by_state: dict[str, int] = {}
    for x in rows:
        by_state[x["state"]] = by_state.get(x["state"], 0) + 1

    return {
        "index": snap["index"],
        "label": snap["label"],
        "window": window,
        "window_label": WINDOW_LABELS[window],
        "sessions": sessions,
        "count": len(rows),
        "min_volume_ratio": MIN_VOL_RATIO,
        "by_state": by_state,
        "states": [{"key": k, "label": k.replace("_", " ").title(), "text": v}
                   for k, v in STATES.items()],
        "delivery_available": bool(delivery),
        "delivery_note": (
            f"Delivery data for {len(delivery)} symbols from the NSE end-of-day bhavcopy."
            if delivery else
            "No delivery data stored yet — the NSE bhavcopy archive has not been captured "
            "from this host. Delivery columns read n/a rather than 0."),
        "rows": rows[:limit],
    }
