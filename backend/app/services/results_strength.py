"""Are the latest RESULTS strong? — a separate question from whether the business is good.

WHY THIS IS NOT PART OF THE 1-10 FUNDAMENTAL SCORE
`fundamental_rating` judges the business over five and ten years: does it earn its cost of
capital, compound, convert profit to cash, stay unlevered. This asks something narrower and
more perishable — did the quarter just reported come in ahead of the same quarter last year,
and is the trend of the last four quarters up or down. A great business can post a poor
quarter and a poor business a great one, so blending the two would blur both. They are
reported side by side instead.

OPERATING PROFIT LEADS, NOT NET PROFIT — THIS IS THE WHOLE POINT
"Other Income" on an Indian P&L absorbs asset sales, forex swings, treasury gains and
write-backs, and it can dwarf the operating business for a quarter. NRB Bearings reported
Dec 2023 net profit of Rs166 Cr on operating profit of Rs36 Cr, because other income was
Rs192 Cr; the very next Dec, net profit was Rs22 Cr. Comparing those two prints gives
-87% and reads as a collapse, while operating profit over the same two quarters went
36 -> 45, which is +25% and the truth about the business.

So: operating profit carries the most weight, sales next, and net profit is reported but
never allowed to drive the verdict on its own. Where other income is large enough to
distort a comparison, the quarter is FLAGGED and said so in words rather than quietly
averaged in.

GROWTH OFF A NEGATIVE OR NEAR-ZERO BASE IS NOT A NUMBER
The same company printed net profit of -1 in Mar 2025. "+4,300% YoY" against that is
arithmetic, not information, so any comparison whose base is <= 0 returns None and is
described instead of being scored.

YEAR-ON-YEAR, NOT SEQUENTIAL, FOR THE VERDICT
Quarter-on-quarter moves in most Indian businesses are seasonal — a Q3 festive quarter
against a Q2 tells you about the calendar, not the company. The verdict is built on the
same quarter a year earlier. QoQ is computed and shown, because it is the first thing a
reader looks for, but it is deliberately not scored.
"""

import logging

from app.services.grades import grade

logger = logging.getLogger("results_strength")

# Weights over the signals that have data; redistributed like the fundamental pillars.
WEIGHTS = {
    "operating_profit_yoy": 0.40,   # the honest profit line
    "sales_yoy": 0.30,
    "margin_direction": 0.15,
    "consistency": 0.15,
}

# Other income at or above this share of profit before tax makes a net-profit
# comparison for that quarter unsafe to read at face value.
ONE_OFF_SHARE = 0.35


def _vals(table: dict, *names) -> list:
    for n in names:
        if n in table:
            return table[n] or []
    return []


def _at(series: list, idx: int):
    """Value at a signed index, or None if the series is too short."""
    if not series:
        return None
    if idx < -len(series) or idx >= len(series):
        return None
    return series[idx]


def _growth(now, base):
    """Percent change, or None where the base makes it meaningless."""
    if now is None or base is None or base <= 0:
        return None
    return (now / base - 1) * 100


def _band(value, bands) -> float:
    for threshold, score in bands:
        if value >= threshold:
            return score
    return 0.0


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def _rs(v) -> str:
    return "n/a" if v is None else f"Rs{v:,.0f} Cr"


def _is_distorted(other_income, pbt, operating_profit) -> bool:
    """Is this quarter's NET profit driven by something other than operations?"""
    if other_income is None:
        return False
    if pbt not in (None, 0) and abs(other_income) >= ONE_OFF_SHARE * abs(pbt):
        return True
    if operating_profit not in (None, 0) and abs(other_income) >= 0.5 * abs(operating_profit):
        return True
    return False


def _verdict(score: float) -> tuple[str, str]:
    if score >= 8.0:
        return "Results are strong", "strong"
    if score >= 6.5:
        return "Results are improving", "good"
    if score >= 5.0:
        return "Results are mixed", "mixed"
    if score >= 3.5:
        return "Results are weak", "weak"
    return "Results are poor", "poor"


def analyse(f: dict) -> dict:
    """Read the quarterly table and say whether the latest results are strong."""
    q = f.get("quarters") or {}
    periods = f.get("quarters_periods") or []
    if not q or len(periods) < 5:
        return {"rated": False, "score": None, "verdict": "Not enough quarters to judge",
                "band": "unknown", "signals": [], **grade(None, "quarter"), "headline":
                "screener.in did not return enough quarterly history to compare this "
                "quarter with the same quarter last year."}

    sales = _vals(q, "Sales", "Revenue")
    op = _vals(q, "Operating Profit", "Financing Profit")
    opm = _vals(q, "OPM %", "Financing Margin %")
    net = _vals(q, "Net Profit")
    other = _vals(q, "Other Income")
    pbt = _vals(q, "Profit before tax")

    latest_label = periods[-1] if periods else "latest"
    yoy_label = periods[-5] if len(periods) >= 5 else "a year earlier"
    prev_label = periods[-2] if len(periods) >= 2 else "previous"

    sales_yoy = _growth(_at(sales, -1), _at(sales, -5))
    sales_qoq = _growth(_at(sales, -1), _at(sales, -2))
    op_yoy = _growth(_at(op, -1), _at(op, -5))
    net_yoy = _growth(_at(net, -1), _at(net, -5))
    opm_now, opm_then = _at(opm, -1), _at(opm, -5)
    opm_delta = (opm_now - opm_then) if (opm_now is not None and opm_then is not None) else None

    # Is either end of the net-profit comparison distorted by one-off other income?
    distorted_now = _is_distorted(_at(other, -1), _at(pbt, -1), _at(op, -1))
    distorted_then = _is_distorted(_at(other, -5), _at(pbt, -5), _at(op, -5))
    net_base = _at(net, -5)
    net_unusable = net_base is not None and net_base <= 0

    signals, scores = [], {}

    if op_yoy is not None:
        s = _band(op_yoy, [(25, 10), (15, 9), (8, 7.5), (3, 6), (0, 5), (-10, 3), (-25, 1.5)])
        scores["operating_profit_yoy"] = s
        signals.append({
            "label": "Operating profit YoY", "value": _pct(op_yoy),
            "tone": "good" if op_yoy >= 5 else "bad" if op_yoy < 0 else "neutral",
            "detail": f"{_rs(_at(op, -1))} this quarter against {_rs(_at(op, -5))} in {yoy_label}. "
                      "This is the line the verdict leans on — it excludes other income.",
        })

    if sales_yoy is not None:
        s = _band(sales_yoy, [(20, 10), (14, 9), (9, 7.5), (5, 6), (0, 5), (-8, 3), (-20, 1.5)])
        scores["sales_yoy"] = s
        signals.append({
            "label": "Sales YoY", "value": _pct(sales_yoy),
            "tone": "good" if sales_yoy >= 5 else "bad" if sales_yoy < 0 else "neutral",
            "detail": f"{_rs(_at(sales, -1))} against {_rs(_at(sales, -5))} in {yoy_label}.",
        })

    if opm_delta is not None:
        s = _band(opm_delta, [(2.5, 10), (1, 8.5), (0, 7), (-1, 5.5), (-2.5, 4), (-5, 2.5)])
        scores["margin_direction"] = s
        signals.append({
            "label": "Operating margin", "value": f"{opm_now:.0f}% ({opm_delta:+.0f} pts YoY)",
            "tone": "good" if opm_delta >= 1 else "bad" if opm_delta <= -1 else "neutral",
            "detail": f"{opm_now:.0f}% this quarter against {opm_then:.0f}% in {yoy_label}.",
        })

    # Consistency: how many of the last four quarters grew on their own year-ago quarter.
    if len(sales) >= 8:
        wins, checked = 0, 0
        for i in range(1, 5):
            g = _growth(_at(sales, -i), _at(sales, -i - 4))
            if g is not None:
                checked += 1
                wins += 1 if g > 0 else 0
        if checked:
            s = {4: 10.0, 3: 8.0, 2: 5.5, 1: 3.5, 0: 1.5}.get(wins, 5.0) if checked == 4 else \
                (wins / checked) * 10
            scores["consistency"] = s
            signals.append({
                "label": "Consistency", "value": f"{wins} of {checked} quarters up YoY",
                "tone": "good" if wins >= 3 else "bad" if wins <= 1 else "neutral",
                "detail": "Sales against the same quarter a year earlier, over the last "
                          f"{checked} quarters — growth that repeats, or a single good print.",
            })

    # Net profit is REPORTED, never scored, and carries its own caveat where needed.
    if net_unusable:
        net_note = (f"Net profit in {yoy_label} was {_rs(net_base)}, so a percentage change "
                    "from it would not be a real number.")
    elif distorted_now or distorted_then:
        which = yoy_label if distorted_then and not distorted_now else \
                latest_label if distorted_now and not distorted_then else "both quarters"
        net_note = (f"Other income is large enough in {which} to drive net profit "
                    "independently of the business, so this comparison is not a clean read "
                    "of operations.")
    else:
        net_note = None

    signals.append({
        "label": "Net profit YoY",
        "value": "not comparable" if (net_unusable or net_yoy is None) else _pct(net_yoy),
        "tone": "neutral" if (net_note or net_yoy is None) else
                ("good" if net_yoy >= 5 else "bad" if net_yoy < 0 else "neutral"),
        "detail": (f"{_rs(_at(net, -1))} against {_rs(net_base)} in {yoy_label}. "
                   + (net_note or "Not scored — operating profit above is the cleaner signal.")),
    })

    if not scores:
        return {"rated": False, "score": None, "verdict": "Not enough data to judge results",
                "band": "unknown", "signals": signals, **grade(None, "quarter"),
                "headline": "The quarterly table was read, but none of the comparisons it "
                            "needs could be computed."}

    live = sum(WEIGHTS[k] for k in scores)
    score = round(sum(v * WEIGHTS[k] for k, v in scores.items()) / live, 1)
    verdict, band = _verdict(score)

    bits = []
    if sales_yoy is not None:
        bits.append(f"sales {_pct(sales_yoy)}")
    if op_yoy is not None:
        bits.append(f"operating profit {_pct(op_yoy)}")
    if opm_delta is not None:
        bits.append(f"margin {opm_delta:+.0f} pts")
    headline = (f"{latest_label} against {yoy_label}: " + ", ".join(bits) + ". "
                + {"strong": "A clearly good quarter.",
                   "good": "Moving in the right direction.",
                   "mixed": "Some progress, some slippage.",
                   "weak": "The quarter went backwards.",
                   "poor": "A bad quarter on every line that matters."}[band])
    if net_note:
        headline += " " + net_note

    return {
        "rated": True, "score": score, "verdict": verdict, "band": band,
        **grade(score, "quarter"),
        "headline": headline, "signals": signals,
        "latest_quarter": latest_label, "comparison_quarter": yoy_label,
        "previous_quarter": prev_label,
        "sales_qoq": round(sales_qoq, 1) if sales_qoq is not None else None,
        "one_off_flag": bool(distorted_now or distorted_then or net_unusable),
        "one_off_note": net_note,
        "coverage": round(live, 3),
    }
