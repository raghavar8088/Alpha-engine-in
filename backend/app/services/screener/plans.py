"""Trade plans: Intraday, Swing and Breakout — each priced NET OF REAL ANGEL ONE COSTS.

WHY THE COSTS ARE NOT A FOOTNOTE. This app has already learned this the expensive way: when
real Angel One charges were backfilled onto the intraday desk, a book showing +Rs23,500
became -Rs33,600 and 1,415 strategies that had ranked as tournament winners turned out to
be losers. Not one of those numbers was wrong before the cutover — they were just gross. A
screener that ranks setups on gross reward-to-risk would reproduce that error one screen
earlier, so every plan here runs both legs through `angel_fees.round_trip` and reports the
R:R a real contract note would produce.

The cost model differs per mode, and the difference is large. An intraday trade pays 0.025%
sell-side STT; a swing trade that sleeps overnight pays 0.1% on BOTH legs plus a Rs20 DP
charge on exit — roughly four times the drag. Charging intraday rates on a swing plan would
understate the cost of every swing trade the screen suggests.

THE THREE MODES ARE DIFFERENT QUESTIONS, NOT THREE RISK SETTINGS.

  Intraday  today's move, closed today. Stop from ATR, target at 2R, square off 15:10.
  Swing     a multi-session trend. Stop under the last CONFIRMED swing low, target 2.5R.
  Breakout  a level being taken out. Entry at the level itself, stop under the base, target
            the measured move — the height of the base projected up from the break.

BREAKOUT REFUSES A GAPPED FILL. Reusing the drift band the Swing Trading desk already
documents: a break is only tradable within ~2% above the level. A stock that opened far
past it is not the trade the level described, and filling "because the level was crossed"
would be the plan overruling the reason it existed. When that happens the plan is returned
with `tradable: false` and the distance, rather than silently disappearing or silently
filling.
"""

from __future__ import annotations

import logging
import math
import os

from app.services.angel_fees import round_trip

logger = logging.getLogger("screener.plans")

PER_TRADE_CAPITAL = float(os.getenv("SCREENER_TRADE_CAPITAL", "50000"))

# Intraday
INTRADAY_STOP_ATR = 1.0
INTRADAY_TARGET_R = 2.0
INTRADAY_SQUAREOFF = os.getenv("SCREENER_SQUAREOFF", "15:10")

# Swing
SWING_STOP_ATR = 2.0        # floor, when the swing low is unusably far or missing
SWING_TARGET_R = 2.5

# Breakout
BREAKOUT_DRIFT_PCT = 0.02   # how far above the level a fill is still the same trade
BREAKOUT_MIN_VOL_X = 1.5

MIN_RR = 1.0                # below this the plan is reported but flagged as not worth it


def _qty(entry: float, capital: float) -> int:
    """Whole shares only. A share priced above the per-trade capital simply cannot be
    taken at this size, and reporting a fractional quantity would describe a trade the
    exchange will not accept."""
    return int(math.floor(capital / entry)) if entry > 0 else 0


def _priced(entry: float, stop: float, target: float, qty: int, product: str) -> dict:
    """Gross and net reward/risk for one plan.

    The win case and the loss case are costed SEPARATELY, because they are different
    round trips: exiting at the target and exiting at the stop have different turnovers
    and therefore different charges. Costing only one of them and applying it to both
    would flatter whichever leg it was taken from.
    """
    gross_reward = (target - entry) * qty
    gross_risk = (entry - stop) * qty
    if qty <= 0 or gross_risk <= 0:
        return {
            "qty": qty, "capital_used": round(entry * qty, 2),
            "gross_reward": None, "gross_risk": None,
            "net_reward": None, "net_risk": None,
            "gross_rr": None, "net_rr": None,
            "cost_win": None, "cost_loss": None, "product": product,
        }

    fees_win = round_trip(entry, target, qty, "BUY", product)
    fees_loss = round_trip(entry, stop, qty, "BUY", product)
    net_reward = gross_reward - fees_win.total
    net_risk = gross_risk + fees_loss.total

    return {
        "qty": qty,
        "capital_used": round(entry * qty, 2),
        "gross_reward": round(gross_reward, 2),
        "gross_risk": round(gross_risk, 2),
        "net_reward": round(net_reward, 2),
        "net_risk": round(net_risk, 2),
        "gross_rr": round(gross_reward / gross_risk, 2),
        "net_rr": round(net_reward / net_risk, 2) if net_risk > 0 else None,
        "cost_win": fees_win.as_dict(),
        "cost_loss": fees_loss.as_dict(),
        "product": product,
    }


def intraday_plan(row: dict, capital: float = PER_TRADE_CAPITAL) -> dict | None:
    """Same-session momentum trade. Stop sized in ATR, target at 2R, squared off at 15:10."""
    entry = row.get("ltp")
    atr = row.get("atr14")
    if not entry or not atr or atr <= 0:
        return None

    stop = entry - INTRADAY_STOP_ATR * atr
    if stop <= 0:
        return None
    target = entry + INTRADAY_TARGET_R * (entry - stop)
    qty = _qty(entry, capital)
    pricing = _priced(entry, stop, target, qty, "INTRADAY")

    return {
        "kind": "intraday",
        "label": "Intraday",
        "tradable": True,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "stop_pct": round((stop / entry - 1) * 100, 2),
        "target_pct": round((target / entry - 1) * 100, 2),
        "horizon": "same session",
        "exit_rule": f"Square off at {INTRADAY_SQUAREOFF} IST regardless",
        "basis": (f"Stop is {INTRADAY_STOP_ATR:g}x the 14-day ATR ({atr:.2f}), so it is sized "
                  f"to this stock's own volatility rather than a fixed percentage. "
                  f"Target is {INTRADAY_TARGET_R:g}R."),
        **pricing,
    }


def swing_plan(row: dict, capital: float = PER_TRADE_CAPITAL) -> dict | None:
    """Multi-session trend trade. Stop under the last confirmed swing low."""
    entry = row.get("ltp")
    atr = row.get("atr14")
    if not entry or not atr or atr <= 0:
        return None

    swing_low = row.get("swing_low")
    atr_stop = entry - SWING_STOP_ATR * atr
    # Prefer the structural level, but never a stop so far away it makes the trade
    # meaningless — fall back to the ATR stop when the swing low is below it.
    if swing_low and swing_low < entry and swing_low >= atr_stop:
        stop, stop_basis = swing_low, "the last confirmed swing low"
    else:
        stop, stop_basis = atr_stop, f"{SWING_STOP_ATR:g}x ATR (no usable swing low nearby)"
    if stop <= 0:
        return None

    target = entry + SWING_TARGET_R * (entry - stop)
    qty = _qty(entry, capital)
    pricing = _priced(entry, stop, target, qty, "DELIVERY")

    return {
        "kind": "swing",
        "label": "Swing",
        "tradable": True,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "stop_pct": round((stop / entry - 1) * 100, 2),
        "target_pct": round((target / entry - 1) * 100, 2),
        "horizon": "3-15 sessions",
        "exit_rule": "Trail the stop up under each new swing low once 1R is banked",
        "basis": (f"Stop is {stop_basis}. Target is {SWING_TARGET_R:g}R. Costed on the "
                  f"DELIVERY schedule — this position sleeps overnight, so it pays 0.1% STT "
                  f"on both legs plus a DP charge on exit, roughly 4x the intraday drag."),
        **pricing,
    }


def breakout_plan(row: dict, capital: float = PER_TRADE_CAPITAL) -> dict | None:
    """Level-break trade with a measured-move target and a drift band on the fill."""
    ltp = row.get("ltp")
    level = row.get("donchian_high_20")
    base_low = row.get("base_low_20")
    atr = row.get("atr14")
    if not ltp or not level or not base_low or not atr or atr <= 0:
        return None
    if base_low >= level:
        return None

    # Entry is the LEVEL, not the last price: that is what the setup describes.
    entry = level
    drift = (ltp / level - 1)
    tradable = drift <= BREAKOUT_DRIFT_PCT

    height = level - base_low
    stop = max(base_low, entry - SWING_STOP_ATR * atr)
    if stop <= 0 or stop >= entry:
        return None
    target = entry + height                      # measured move: the base projected up

    qty = _qty(entry, capital)
    pricing = _priced(entry, stop, target, qty, "DELIVERY")

    vol_x = row.get("volume_x")
    confirmations = []
    if vol_x is not None:
        if vol_x >= BREAKOUT_MIN_VOL_X:
            confirmations.append(f"volume {vol_x:.1f}x its average — confirmed")
        else:
            confirmations.append(f"volume only {vol_x:.1f}x its average — unconfirmed break")

    plan = {
        "kind": "breakout",
        "label": "Breakout",
        "tradable": tradable,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "stop_pct": round((stop / entry - 1) * 100, 2),
        "target_pct": round((target / entry - 1) * 100, 2),
        "horizon": "1-10 sessions",
        "drift_pct": round(drift * 100, 2),
        "drift_band_pct": BREAKOUT_DRIFT_PCT * 100,
        "exit_rule": "Exit on a close back inside the base, or at the measured move",
        "basis": (f"Entry is the 20-session high ({level:.2f}). Stop is under the base "
                  f"({base_low:.2f}). Target is the measured move — the {height:.2f} base "
                  f"height projected up from the break. "
                  + ("; ".join(confirmations) if confirmations else "")),
        **pricing,
    }
    if not tradable:
        plan["blocked_reason"] = (
            f"Price is {drift * 100:.1f}% above the {level:.2f} level, outside the "
            f"{BREAKOUT_DRIFT_PCT * 100:.0f}% drift band. A stock that has already run this "
            f"far past its trigger is not the trade the level described — taking it here "
            f"would be paying up for a breakout that already happened.")
    return plan


async def plans_for(row: dict, pattern_hits: list[dict] | None = None,
                    capital: float = PER_TRADE_CAPITAL) -> list[dict]:
    """All three plans for one stock, each annotated with any pattern that confirms it."""
    out = []
    for fn in (intraday_plan, swing_plan, breakout_plan):
        plan = fn(row, capital)
        if plan is None:
            continue
        plan["confirming_patterns"] = confirming(plan, pattern_hits or [])
        plan["worth_taking"] = bool(
            plan.get("net_rr") is not None and plan["net_rr"] >= MIN_RR and plan["tradable"])
        out.append(plan)
    return out


def confirming(plan: dict, hits: list[dict]) -> list[dict]:
    """Bullish pattern hits on the timeframe that matches the plan's horizon.

    An intraday plan is confirmed by a daily pattern; a swing plan by a weekly one. Letting
    a weekly cup & handle "confirm" a trade that closes at 15:10 would be borrowing
    authority from a horizon the trade never reaches.
    """
    tf = "1w" if plan["kind"] == "swing" else "1d"
    return [
        {"pattern": h["pattern"], "state": h["state"], "timeframe": h["timeframe"],
         "confidence": h["confidence"], "rationale": h["rationale"]}
        for h in hits
        if h["direction"] == "bullish" and h["timeframe"] == tf
    ][:3]


def gate(row: dict, kind: str) -> tuple[bool, str]:
    """Does this stock qualify for this mode at all? Returns (passes, why-not).

    The gates are deliberately about the SETUP, not about the stock being good. A stock can
    be an excellent long-term hold and a terrible intraday trade, and vice versa.
    """
    vol_x = row.get("volume_x")
    ret_1d = (row.get("returns") or {}).get("1d")
    ret_1w = (row.get("returns") or {}).get("1w")
    ret_1m = (row.get("returns") or {}).get("1m")

    if kind == "intraday":
        if ret_1d is None or ret_1d <= 0:
            return False, "not up today"
        if vol_x is None or vol_x < 1.2:
            return False, "no unusual volume today"
        if row.get("sma20") and row["ltp"] < row["sma20"]:
            return False, "trading below its own 20-day average"
        return True, ""

    if kind == "swing":
        if ret_1w is None or ret_1m is None:
            return False, "not enough history for a weekly and monthly read"
        if ret_1w <= 0 or ret_1m <= 0:
            return False, "week and month must both be positive"
        if row.get("sma50") and row["ltp"] < row["sma50"]:
            return False, "below its 50-day average"
        if (row.get("ema9_hold_pct") or 0) < 50:
            return False, "has not been holding above its 9 EMA"
        return True, ""

    if kind == "breakout":
        if not row.get("donchian_high_20"):
            return False, "no 20-session level stored"
        if vol_x is None or vol_x < BREAKOUT_MIN_VOL_X:
            return False, f"volume below {BREAKOUT_MIN_VOL_X}x its average — unconfirmed"
        if not row.get("breakout"):
            return False, "has not broken a multi-session high"
        return True, ""

    return False, f"unknown mode {kind!r}"
