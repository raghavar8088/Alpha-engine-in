"""The "why is this stock trending" engine.

THE ONE RULE: never emit a reason we cannot point at a number for.

That rule is the whole design. It is easy to write something that produces a confident
sentence for every row — and a screener that always has an explanation is a screener whose
explanations mean nothing, because it has no way of saying "this moved and I do not know
why". That answer is common, it is honest, and it is genuinely useful: an uncorroborated
9% move is a different trade from a 9% move the whole sector is making.

Bullish Stocks set the precedent by refusing to approximate order-book strength rather than
inventing a proxy for it. Same discipline here.

THREE TIERS
  1  mechanical   always available, computed from our own bars and quotes
  2  corroborating  may legitimately be absent (fundamentals, F&O buildup, sector context)
  3  narrative    news and filings; labelled, and reported as unavailable when it is

Each reason carries the measurement that produced it, so the UI can show the number beside
the sentence and a trade can be argued with rather than merely asserted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Weights are for ORDERING the stack, not for scoring the stock — the momentum score is
# computed separately from the raw measurements. A reason's weight says "how much does
# this explain the move", which is a different question from "how good is this stock".
@dataclass
class Reason:
    code: str
    tier: int
    text: str
    weight: float
    value: float | None = None
    unit: str | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        if self.value is not None:
            d["value"] = round(self.value, 2)
        return d


# ── thresholds ──────────────────────────────────────────────────────────────────
VOL_NOTABLE = 1.5          # x its own 20-day average before volume is worth mentioning
VOL_STRONG = 3.0
DELIVERY_NOTABLE = 55.0    # % of traded quantity taken to demat
SECTOR_MOVE_PCT = 1.5      # sector move that counts as "the whole sector is doing this"
RS_STRONG = 3.0            # percentage points of outperformance vs the index
CONSISTENCY_STRONG = 65.0  # % of sessions in the window that closed up
EMA_HOLD_STRONG = 80.0     # % of the last month held above the 9 EMA
NEAR_HIGH_PCT = -2.0       # within 2% of the rolling high


def build(metrics: dict, sector_ctx: dict | None = None,
          fundamentals: dict | None = None, fno: dict | None = None,
          narrative: dict | None = None) -> list[dict]:
    """Assemble the ranked reason stack for one stock.

    `metrics` is the row the momentum board already computed. Everything else is optional
    and simply contributes nothing when absent — which is the point.
    """
    out: list[Reason] = []

    # ── tier 1: mechanical ──────────────────────────────────────────────────────
    vol_x = metrics.get("volume_x")
    if vol_x is not None and vol_x >= VOL_NOTABLE:
        strength = "far above" if vol_x >= VOL_STRONG else "above"
        out.append(Reason(
            "volume", 1,
            f"Trading {vol_x:.1f}x its 20-day average volume — participation is {strength} normal",
            weight=min(1.0, vol_x / 5) * 0.9, value=vol_x, unit="x",
        ))

    delivery = metrics.get("delivery_pct")
    if delivery is not None and delivery >= DELIVERY_NOTABLE:
        out.append(Reason(
            "delivery", 1,
            f"{delivery:.0f}% of today's volume went to delivery — buying, not intraday churn",
            weight=0.75, value=delivery, unit="%",
        ))

    brk = metrics.get("breakout")
    if brk and brk.get("window"):
        out.append(Reason(
            "breakout", 1,
            f"Closed through its {brk['window']}-session high on {brk.get('date')}",
            weight=0.85 if brk["window"] >= 50 else 0.65, value=float(brk["window"]),
            unit="sessions",
        ))

    pct_high = metrics.get("pct_from_52w_high")
    if pct_high is not None and pct_high >= NEAR_HIGH_PCT:
        out.append(Reason(
            "at_highs", 1,
            f"Within {abs(pct_high):.1f}% of its 52-week high",
            weight=0.7, value=pct_high, unit="%",
        ))

    ema_hold = metrics.get("ema9_hold_pct")
    if ema_hold is not None and ema_hold >= EMA_HOLD_STRONG:
        out.append(Reason(
            "ema_hold", 1,
            f"Held above its 9 EMA for {ema_hold:.0f}% of the last month",
            weight=0.6, value=ema_hold, unit="%",
        ))

    cons = metrics.get("consistency")
    if cons is not None and cons >= CONSISTENCY_STRONG:
        out.append(Reason(
            "consistency", 1,
            f"{cons:.0f}% of sessions in this window closed up — a grind, not one gap",
            weight=0.65, value=cons, unit="%",
        ))

    streak = metrics.get("up_streak")
    if streak and streak >= 3:
        out.append(Reason(
            "streak", 1,
            f"{streak} consecutive up sessions",
            weight=0.5, value=float(streak), unit="sessions",
        ))

    rs_idx = metrics.get("rs_index")
    if rs_idx is not None and rs_idx >= RS_STRONG:
        out.append(Reason(
            "rs_index", 1,
            f"Outperforming NIFTY by {rs_idx:.1f} points over this horizon",
            weight=0.8, value=rs_idx, unit="pp",
        ))

    # ── tier 2: corroborating ───────────────────────────────────────────────────
    if sector_ctx:
        sec_ret = sector_ctx.get("return_pct")
        sec_name = sector_ctx.get("sector")
        sec_rank = sector_ctx.get("rank")
        sec_total = sector_ctx.get("of")
        if sec_ret is not None and abs(sec_ret) >= SECTOR_MOVE_PCT:
            rank_txt = f", rank {sec_rank} of {sec_total}" if sec_rank else ""
            out.append(Reason(
                "sector_rotation", 2,
                f"{sec_name} is {sec_ret:+.1f}% over this horizon{rank_txt} — "
                f"this is sector rotation, not a lone move",
                weight=0.9, value=sec_ret, unit="%",
            ))
        elif sec_ret is not None:
            out.append(Reason(
                "sector_flat", 2,
                f"{sec_name} is only {sec_ret:+.1f}% — the move is stock-specific",
                weight=0.55, value=sec_ret, unit="%",
            ))

    if fundamentals and fundamentals.get("known"):
        bits = []
        rev = fundamentals.get("revenue_growth")
        pat = fundamentals.get("earnings_growth")
        roe = fundamentals.get("roe")
        if rev is not None and rev >= 10:
            bits.append(f"revenue +{rev:.0f}% YoY")
        if pat is not None and pat >= 10:
            bits.append(f"earnings +{pat:.0f}% YoY")
        if roe is not None and roe >= 15:
            bits.append(f"ROE {roe:.0f}%")
        if bits:
            out.append(Reason(
                "fundamentals", 2,
                "Fundamentals support it: " + ", ".join(bits),
                weight=0.7, value=rev if rev is not None else None, unit="%",
            ))

    if fno and fno.get("known"):
        kind = fno.get("buildup")
        if kind == "long":
            out.append(Reason(
                "fno_long", 2,
                "Price up with open interest up — fresh long buildup, not a squeeze",
                weight=0.85, value=fno.get("oi_change_pct"), unit="%",
            ))
        elif kind == "short_covering":
            out.append(Reason(
                "fno_covering", 2,
                "Price up with open interest FALLING — short covering, which tends to "
                "exhaust rather than trend",
                weight=0.8, value=fno.get("oi_change_pct"), unit="%",
            ))

    # ── tier 3: narrative ───────────────────────────────────────────────────────
    if narrative and narrative.get("available") and narrative.get("headline"):
        out.append(Reason(
            "news", 3, narrative["headline"], weight=0.6,
        ))

    out.sort(key=lambda r: (-r.weight, r.tier))
    return [r.as_dict() for r in out]


def summarise(symbol: str, horizon_return: float | None, reasons: list[dict],
              narrative_available: bool) -> str:
    """One honest sentence for the row tooltip and the drawer header.

    When nothing corroborates the move, say exactly that. This is the branch that makes
    the rest of the engine trustworthy.
    """
    move = f"{horizon_return:+.1f}%" if horizon_return is not None else "moving"
    tier1 = [r for r in reasons if r["tier"] == 1]
    tier2 = [r for r in reasons if r["tier"] == 2]

    if not tier1 and not tier2:
        return (f"{symbol} {move} with nothing in the data explaining it — no unusual "
                f"volume, no breakout, no sector move. Unexplained.")

    # `lead` is empty whenever a stock has corroboration but no mechanical signal — a
    # sector-wide move on ordinary volume, say. Building the sentence by joining only the
    # parts that exist keeps that case from rendering as "SYMBOL +9.1%. . IT is up".
    parts = [f"{symbol} {move}"]
    if tier1:
        parts.append("; ".join(r["text"] for r in tier1[:2]))

    if tier2:
        parts.append(tier2[0]["text"])
        return ". ".join(parts) + "."

    missing = "no sector move, no fundamental change, no F&O buildup"
    missing += ", no news found" if narrative_available else ", news not checked"
    parts.append(f"Otherwise uncorroborated — {missing}")
    return ". ".join(parts) + "."


def classify(reasons: list[dict]) -> str:
    """A one-word character for the move, used for the UI chip colour."""
    codes = {r["code"] for r in reasons}
    if "sector_rotation" in codes:
        return "rotation"
    if "fno_covering" in codes:
        return "short-covering"
    if "breakout" in codes and "volume" in codes:
        return "breakout"
    if "fundamentals" in codes:
        return "fundamental"
    if codes & {"volume", "streak", "consistency"}:
        return "momentum"
    return "unexplained"


def chips(reasons: list[dict], limit: int = 3) -> list[dict]:
    """Compact labels for the board's Why column — the drawer carries the full stack."""
    out = []
    for r in reasons[:limit]:
        code = r["code"]
        if code == "volume":
            label = f"Vol {r['value']:.1f}x"
        elif code == "sector_rotation":
            label = f"Sector {r['value']:+.1f}%"
        elif code == "breakout":
            label = f"{int(r['value'])}d breakout"
        elif code == "delivery":
            label = f"Delivery {r['value']:.0f}%"
        elif code == "rs_index":
            label = f"RS {r['value']:+.1f}"
        elif code == "fno_long":
            label = "Long buildup"
        elif code == "fno_covering":
            label = "Short covering"
        elif code == "at_highs":
            label = "At 52w high"
        elif code == "streak":
            label = f"{int(r['value'])}d streak"
        elif code == "fundamentals":
            label = "Fundamentals"
        elif code == "consistency":
            label = "Consistent"
        elif code == "ema_hold":
            label = "Above 9EMA"
        elif code == "sector_flat":
            label = "Stock-specific"
        else:
            label = code.replace("_", " ").title()
        out.append({"label": label, "tier": r["tier"], "code": code})
    return out
