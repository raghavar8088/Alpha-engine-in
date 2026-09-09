"""Turning a passed research verdict into a tradeable call.

Shape follows the desk convention the module was asked to match: a BUY RANGE rather than a
single price, two targets, one stop, and a stated holding window in working days.

Levels are sized in ATR, not in percentages, because a fixed percentage stop is either too
tight on a volatile name or too loose on a quiet one and the same number cannot be both:

  STOP    the lower of (entry - 2.2 x ATR) and (the pullback swing low - 0.3 x ATR), so a
          structural level is used when the chart offers one and volatility when it does
          not. Never wider than 12% — past that the position gets too small to matter.
  T1      2.0R. The literature's minimum acceptable reward-to-risk for this style.
  T2      3.5R, and additionally required to sit under the nearest overhead resistance
          where one exists, because a target above a supply shelf is a target the stock
          has to fight through rather than reach.
  RANGE   entry +/- 0.35 x ATR, which is where the call can still be taken without the
          arithmetic changing materially.

HORIZON is derived, not chosen: the distance to T1 divided by the daily ATR gives the
sessions the move needs at its recent pace, and that is bucketed into 1 week / 10 days /
1 month. A signal whose T1 needs more sessions than the longest bucket is rejected rather
than relabelled, because a target that cannot be reached in the stated window is not a
swing trade with a long horizon, it is a wrong target.

A call is REJECTED, never softened, when reward-to-risk comes out under 1:2. Widening the
target or tightening the stop to force the ratio is how a desk manufactures the appearance
of an edge.

Research basis for the calibration:
  https://bottomstreet.com/learn/swing-trading-strategies-india/     (pullback band, RS)
  https://swingfolio.com/blog/ema-pullback-trading-strategy          (20 EMA pullback, volume)
  https://theforexgeek.com/adx-swing-trading-strategy/               (ADX > 20-25, +DI/-DI)
  https://quantstock.org/blog/atr-stop-loss-strategy-guide           (ATR multiples, sizing)
  https://tradethatswing.com/trend-trading-strategy-for-high-momentum-stocks-atr-based/
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.screener.horizons import Bar, nearest_resistance_above
from app.services.swing_signals.research import Research

STOP_ATR = 2.2
STRUCT_PAD_ATR = 0.3
MAX_STOP_PCT = 12.0
MIN_STOP_PCT = 2.0
T1_R = 2.0
T2_R = 3.5
RANGE_ATR = 0.35
MIN_RR = 2.0

# (label, working days) — the buckets the desk publishes in.
HORIZONS = (("1 week", 5), ("10 days", 10), ("1 month", 21))
MAX_SESSIONS = HORIZONS[-1][1]


@dataclass
class Signal:
    symbol: str
    name: str | None
    sector: str | None
    generated_on: str
    price: float
    buy_low: float
    buy_high: float
    stop: float
    target1: float
    target2: float
    risk_pct: float
    reward1_pct: float
    reward2_pct: float
    rr1: float
    rr2: float
    horizon: str
    horizon_days: int
    est_sessions: float
    score: float
    pillars_passed: int
    conviction: str
    atr: float
    atr_pct: float
    reasons: list[str]
    against: list[str]
    facts: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _conviction(score: float, pillars: int) -> str:
    if score >= 82 and pillars >= 7:
        return "HIGH"
    if score >= 72 and pillars >= 6:
        return "MEDIUM"
    return "MODEST"


def build(res: Research, bars: list[Bar], name: str | None = None,
          sector: str | None = None, on: str = "") -> tuple[Signal | None, str | None]:
    """(signal, rejection). Exactly one is ever non-None."""
    if not res.ok:
        return None, res.reject

    price = float(res.facts["price"])
    a = float(res.facts["atr"])

    # --- stop: volatility, or structure when the chart offers one -------------------
    vol_stop = price - STOP_ATR * a
    swing_low = res.facts.get("swing_low")
    struct_stop = (float(swing_low) - STRUCT_PAD_ATR * a) if swing_low else None
    stop = min(vol_stop, struct_stop) if struct_stop else vol_stop
    basis = ("the pullback swing low" if struct_stop and struct_stop <= vol_stop
             else f"{STOP_ATR:g}x ATR")

    risk = price - stop
    if risk <= 0:
        return None, "stop resolves at or above the entry — no risk unit to size from"
    risk_pct = risk / price * 100
    if risk_pct > MAX_STOP_PCT:
        return None, (f"a stop that respects the structure sits {risk_pct:.1f}% away, past "
                      f"the {MAX_STOP_PCT:.0f}% ceiling — ₹1 lakh here buys too little to matter")
    if risk_pct < MIN_STOP_PCT:
        # Snap out to the floor rather than reject: an unusually quiet name is not a broken
        # setup, but a 0.8% stop is noise and will be taken out by the spread.
        stop = price * (1 - MIN_STOP_PCT / 100)
        risk = price - stop
        risk_pct = MIN_STOP_PCT
        basis = f"{MIN_STOP_PCT:g}% floor (ATR stop was inside the noise)"

    t1 = price + T1_R * risk
    t2 = price + T2_R * risk

    # --- respect overhead supply on the far target ----------------------------------
    res_above = nearest_resistance_above(bars, price)
    capped = None
    if res_above and res_above < t2:
        if res_above <= t1:
            return None, (f"the nearest resistance at ₹{res_above:,.0f} sits below a 1:2 "
                          "target — there is no room between the entry and the supply above it")
        t2 = res_above
        capped = res_above

    rr1 = (t1 - price) / risk
    rr2 = (t2 - price) / risk
    if rr1 < MIN_RR:
        return None, (f"reward-to-risk is 1:{rr1:.1f}, under the 1:{MIN_RR:g} bar — "
                      "not worth the capital at this stop")

    # --- horizon, derived from how far T1 is in daily ATRs ---------------------------
    est = (t1 - price) / a
    horizon, hdays = HORIZONS[-1]
    for label, days in HORIZONS:
        if est <= days * 0.9:
            horizon, hdays = label, days
            break
    if est > MAX_SESSIONS:
        return None, (f"T1 is {est:.0f} sessions away at this stock's own pace — beyond the "
                      f"{MAX_SESSIONS}-session window, so it is not a swing target")

    sig = Signal(
        symbol=res.symbol, name=name, sector=sector, generated_on=on,
        price=round(price, 2),
        buy_low=round(price - RANGE_ATR * a, 2),
        buy_high=round(price + RANGE_ATR * a, 2),
        stop=round(stop, 2), target1=round(t1, 2), target2=round(t2, 2),
        risk_pct=round(risk_pct, 2),
        reward1_pct=round((t1 - price) / price * 100, 2),
        reward2_pct=round((t2 - price) / price * 100, 2),
        rr1=round(rr1, 2), rr2=round(rr2, 2),
        horizon=horizon, horizon_days=hdays, est_sessions=round(est, 1),
        score=res.score, pillars_passed=res.pillars_passed,
        conviction=_conviction(res.score, res.pillars_passed),
        atr=round(a, 2), atr_pct=float(res.facts["atr_pct"]),
        reasons=res.reasons, against=res.against,
        facts={**res.facts, "stop_basis": basis,
               **({"t2_capped_at_resistance": round(capped, 2)} if capped else {})},
    )
    return sig, None
