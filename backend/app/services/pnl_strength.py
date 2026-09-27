"""Is the multi-year PROFIT & LOSS record strong? — the third of the three grades.

WHAT THIS ANSWERS THAT THE OTHER TWO DO NOT
`results_strength` reads one quarter against the same quarter a year earlier: perishable,
and easily flattered or ruined by a single event. `fundamental_rating` reads the whole
business including its balance sheet, cash conversion, valuation and ownership. This sits
between them and reads only the P&L, down the years: has this company actually grown its
sales and its operating profit over a decade, has it held its margin while doing so, and
did it do that every year or in one lucky burst?

A company can score well on the business and badly here — a cash-rich, debt-free, highly
rated franchise whose sales have gone sideways for eight years. The reverse happens too.
Keeping the P&L record as its own grade is what makes that visible instead of averaged.

SAME TWO RULES AS THE QUARTERLY READ, FOR THE SAME REASONS
  * OPERATING profit, not net profit, carries the weight. Other income on an Indian P&L
    absorbs asset sales, forex and write-backs, and a single year of it distorts any
    comparison that ends or begins there. Net profit is reported and flagged, never scored.
  * A growth rate off a base of zero or less is not a number, so it is described rather
    than computed.

CONSISTENCY IS SCORED SEPARATELY FROM RATE
Two companies can both compound sales at 12%: one did 12% nine years running, the other
did nothing for eight years and then doubled. The first is a business, the second is an
event. So "how many of the last N years grew" is its own signal, weighted as heavily as
the margin trend, rather than being folded into the CAGR.

THE TTM COLUMN IS EXCLUDED FROM EVERY CAGR
screener.in's last P&L column is trailing-twelve-months, which overlaps the final full
year. Treating it as another annual period shortens the span and overstates the rate. It
is still shown in the table and used for the "latest direction" read, but never as a CAGR
endpoint.
"""

import logging

from app.services.grades import grade

logger = logging.getLogger("pnl_strength")

WEIGHTS = {
    "sales_growth": 0.24,
    "profit_growth": 0.26,      # operating profit, the honest line
    "margin_trend": 0.16,
    "consistency": 0.20,
    "interest_burden": 0.14,
}

ONE_OFF_SHARE = 0.35


def _vals(table: dict, *names) -> list:
    for n in names:
        if n in table:
            return table[n] or []
    return []


def _annual(values: list, periods: list) -> list[tuple[str, float]]:
    """(period, value) pairs for real financial years only — TTM dropped."""
    out = []
    for p, v in zip(periods, values or []):
        if v is None or "TTM" in str(p).upper():
            continue
        out.append((p, v))
    return out


def _cagr(pairs: list[tuple[str, float]], years: int) -> float | None:
    if len(pairs) < years + 1:
        return None
    base, latest = pairs[-(years + 1)][1], pairs[-1][1]
    if base is None or base <= 0 or latest is None or latest <= 0:
        return None
    return ((latest / base) ** (1 / years) - 1) * 100


def _band(value, bands) -> float:
    for threshold, score in bands:
        if value >= threshold:
            return score
    return 0.0


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def _rs(v) -> str:
    return "n/a" if v is None else f"Rs{v:,.0f} Cr"


def analyse(f: dict) -> dict:
    """Grade the yearly P&L record."""
    pl = f.get("profit_loss") or {}
    periods = f.get("profit_loss_periods") or []
    ranges = f.get("ranges") or {}
    if not pl or len(periods) < 4:
        return {"rated": False, "score": None, "verdict": "Not enough years to judge",
                "signals": [], **grade(None, "pnl"), "headline": "screener.in did not return enough yearly "
                                           "history to read a record from."}

    sales = _annual(_vals(pl, "Sales", "Revenue"), periods)
    op = _annual(_vals(pl, "Operating Profit", "Financing Profit"), periods)
    opm = _annual(_vals(pl, "OPM %", "Financing Margin %"), periods)
    net = _annual(_vals(pl, "Net Profit"), periods)
    interest = _annual(_vals(pl, "Interest"), periods)
    other = _annual(_vals(pl, "Other Income"), periods)
    pbt = _annual(_vals(pl, "Profit before tax"), periods)

    span = len(sales)
    signals, scores = [], {}

    # ── growth: screener's own CAGR boxes first, computed from the table as fallback ──
    s_box = ranges.get("Compounded Sales Growth") or {}
    sales_cagr = s_box.get("5 Years") or s_box.get("3 Years")
    sales_years = 5 if s_box.get("5 Years") is not None else 3
    if sales_cagr is None:
        for y in (5, 3):
            sales_cagr = _cagr(sales, y)
            if sales_cagr is not None:
                sales_years = y
                break

    if sales_cagr is not None:
        scores["sales_growth"] = _band(sales_cagr,
                                       [(20, 10), (15, 9), (11, 7.5), (7, 6), (4, 4.5), (0, 3), (-5, 1.5)])
        first, last = sales[0], sales[-1]
        signals.append({
            "label": f"Sales growth ({sales_years}y)", "value": _pct(sales_cagr),
            "tone": "good" if sales_cagr >= 10 else "bad" if sales_cagr < 4 else "neutral",
            "detail": f"{_rs(first[1])} in {first[0]} to {_rs(last[1])} in {last[0]}, "
                      f"compounding at {_pct(sales_cagr)} over {sales_years} years.",
        })

    op_cagr = None
    for y in (5, 3):
        op_cagr = _cagr(op, y)
        if op_cagr is not None:
            op_years = y
            break
    if op_cagr is not None:
        scores["profit_growth"] = _band(op_cagr,
                                        [(22, 10), (16, 9), (11, 7.5), (7, 6), (3, 4.5), (0, 3), (-5, 1.5)])
        signals.append({
            "label": f"Operating profit growth ({op_years}y)", "value": _pct(op_cagr),
            "tone": "good" if op_cagr >= 10 else "bad" if op_cagr < 3 else "neutral",
            "detail": f"{_rs(op[-(op_years + 1)][1])} in {op[-(op_years + 1)][0]} to "
                      f"{_rs(op[-1][1])} in {op[-1][0]}. Operating profit, so no other income in it.",
        })

    # ── margin over the decade ───────────────────────────────────────────────────────
    if len(opm) >= 4:
        now, then = opm[-1][1], opm[-min(6, len(opm))][1]
        delta = now - then
        scores["margin_trend"] = _band(delta, [(3, 10), (1, 8.5), (-0.5, 7), (-2, 5.5), (-4, 4), (-7, 2.5)])
        signals.append({
            "label": "Margin trend", "value": f"{now:.0f}% ({delta:+.0f} pts)",
            "tone": "good" if delta >= 1 else "bad" if delta <= -2 else "neutral",
            "detail": f"Operating margin {then:.0f}% in {opm[-min(6, len(opm))][0]} against "
                      f"{now:.0f}% in {opm[-1][0]}. "
                      + ("Holding or widening while growing is the hard part."
                         if delta >= -0.5 else
                         "Growing sales while the margin slips means the growth is being bought."),
        })

    # ── consistency: growth that repeats, and years without a loss ───────────────────
    if span >= 4:
        up = sum(1 for i in range(1, span)
                 if sales[i][1] is not None and sales[i - 1][1] not in (None, 0)
                 and sales[i][1] > sales[i - 1][1])
        checked = span - 1
        losses = sum(1 for _, v in net if v is not None and v < 0)
        ratio = up / checked if checked else 0
        s = ratio * 10
        if losses:
            s -= min(3.0, losses * 1.5)
        scores["consistency"] = max(0.0, min(10.0, s))
        signals.append({
            "label": "Consistency", "value": f"{up} of {checked} years up",
            "tone": "good" if ratio >= 0.75 and not losses else "bad" if (ratio < 0.5 or losses >= 2) else "neutral",
            "detail": f"Sales rose in {up} of the last {checked} years"
                      + (f", and net profit was negative in {losses} of {len(net)}."
                         if losses else ", with no loss-making year in the record.")
                      + " Growth that repeats is a business; one good year is an event.",
        })

    # ── what interest eats ───────────────────────────────────────────────────────────
    if interest and op and op[-1][1] and op[-1][1] > 0:
        share = (interest[-1][1] / op[-1][1]) * 100 if interest[-1][1] is not None else None
        if share is not None:
            scores["interest_burden"] = _band(-share,
                                              [(-3, 10), (-8, 9), (-15, 7.5), (-25, 6), (-40, 4), (-60, 2.5)])
            signals.append({
                "label": "Interest burden", "value": f"{share:.0f}% of op. profit",
                "tone": "good" if share <= 10 else "bad" if share >= 30 else "neutral",
                "detail": f"Interest of {_rs(interest[-1][1])} against operating profit of "
                          f"{_rs(op[-1][1])} in {op[-1][0]}. "
                          + ("Lenders take almost nothing." if share <= 5 else
                             "A manageable share." if share <= 20 else
                             "Lenders take a large slice of what the business earns."),
            })

    # ── net profit: reported, never scored ───────────────────────────────────────────
    distorted_years = [p for (p, oi), (_, pb), (_, o) in zip(other, pbt, op)
                       if oi is not None and pb not in (None, 0)
                       and abs(oi) >= ONE_OFF_SHARE * abs(pb)]
    net_note = None
    if distorted_years:
        shown = ", ".join(distorted_years[-3:])
        net_note = (f"Other income was large enough to drive net profit in {shown}"
                    + (" among others" if len(distorted_years) > 3 else "")
                    + ", so the net-profit line in those years is not a read on operations.")
    if net:
        signals.append({
            "label": "Net profit (latest year)", "value": _rs(net[-1][1]),
            "tone": "neutral",
            "detail": f"{_rs(net[-1][1])} in {net[-1][0]}. "
                      + (net_note or "Reported for context — operating profit above is what the "
                                     "record is scored on."),
        })

    if not scores:
        return {"rated": False, "score": None, "verdict": "Not enough data to judge the record",
                "signals": signals, **grade(None, "pnl"),
                "headline": "The yearly table was read, but none of its comparisons could be computed."}

    live = sum(WEIGHTS[k] for k in scores)
    score = round(sum(v * WEIGHTS[k] for k, v in scores.items()) / live, 1)

    bits = []
    if sales_cagr is not None:
        bits.append(f"sales {_pct(sales_cagr)}")
    if op_cagr is not None:
        bits.append(f"operating profit {_pct(op_cagr)}")
    headline = (f"Over {span} years of accounts" + (": " + ", ".join(bits) if bits else "") + ". "
                + ("A record of steady, profitable growth." if score >= 7.8 else
                   "A solid record with some soft patches." if score >= 6.2 else
                   "A mixed record — growth without much to show for it, or the reverse."
                   if score >= 4.6 else
                   "A weak record: the P&L has not compounded."))
    if net_note:
        headline += " " + net_note

    return {
        "rated": True, "score": score, **grade(score, "pnl"),
        "verdict": grade(score, "pnl")["grade"],
        "headline": headline, "signals": signals,
        "years": span,
        "first_year": sales[0][0] if sales else None,
        "last_year": sales[-1][0] if sales else None,
        "one_off_flag": bool(distorted_years),
        "one_off_note": net_note,
        "coverage": round(live, 3),
    }
