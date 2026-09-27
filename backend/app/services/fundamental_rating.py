"""Rates a company's fundamentals out of 10, and says why in words.

WHAT "FUNDAMENTALLY STRONG" IS TAKEN TO MEAN
A business that earns a high return on the capital it employs, grows sales and profit,
turns that profit into actual cash, does not depend on borrowing to survive, and is not
being quietly sold down by its own promoters. Valuation enters as a modifier, not as the
definition — a wonderful business at a silly price is still a wonderful business, and the
score says so while marking the price down.

That is a quality-and-growth reading. It is stated here rather than buried because a deep
value investor would weight the same seven pillars differently, and PILLARS below is where
they would change it.

HOW THE SCORE IS BUILT
Seven pillars, each scored 0-10 from thresholds that are written down rather than fitted,
then a weighted average rounded to one decimal. Every pillar returns the numbers it used
and a sentence naming them, so a 4.2 can always be traced to the inputs that produced it.

TWO HONESTY RULES, BECAUSE THEY CHANGE THE ANSWER
  * A pillar with no data is DROPPED and its weight redistributed over the pillars that
    do have data — it is never scored 0 and never scored 5. A missing number is not a bad
    number, and averaging in a neutral 5 would quietly drag every score toward mediocrity.
    What was dropped is listed in `skipped`, and `coverage` says how much of the intended
    weight actually had data behind it. A rating built on three of seven pillars is a
    weaker claim than one built on seven, and the caller is told which it is holding.
  * Banks and NBFCs skip the debt and cash-flow pillars entirely. Borrowing IS the raw
    material of a lender, so a bank's debt-to-equity of 8 is ordinary rather than alarming,
    and operating cash flow for a lender swings with the loan book instead of tracking
    profit quality. Scoring them on a manufacturer's yardstick would rate every healthy
    bank in India as distressed.

The rating is a research aid over public filings, not advice, and it cannot see what
screener.in does not publish — related-party dealings, auditor changes, governance, or
what the business will do next.
"""

import logging

from app.services.grades import grade

logger = logging.getLogger("fundamental_rating")

# Weights sum to 1.0 over the pillars that have data; see _blend for redistribution.
PILLARS = {
    "returns":      0.22,   # ROCE / ROE — the single best quality signal for Indian equities
    "growth":       0.20,   # compounded sales + profit growth
    "profitability": 0.14,  # operating margin, level and direction
    "balance_sheet": 0.16,  # borrowings vs net worth, interest cover
    "cash":         0.12,   # does reported profit arrive as cash
    "valuation":    0.08,   # price against those earnings and their growth
    "ownership":    0.08,   # promoter holding level and direction
}

LENDER_PATTERNS = (
    "bank", "financ", "nbfc", "housing finance", "capital market",
    "insurance", "asset management", "investment",
)


# ── small helpers ────────────────────────────────────────────────────────────────


def _last(series, n: int = 1):
    """Last n non-None values of a screener row, oldest first."""
    vals = [v for v in (series or []) if v is not None]
    return vals[-n:] if vals else []


def _latest(series):
    vals = _last(series, 1)
    return vals[0] if vals else None


def _band(value, bands, reverse: bool = False) -> float:
    """Map a value onto a 0-10 score via (threshold, score) pairs, best first.

    reverse=True means lower is better (debt, P/E), so the comparison flips.
    """
    for threshold, score in bands:
        if (value <= threshold) if reverse else (value >= threshold):
            return score
    return 0.0


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _x(v) -> str:
    return "n/a" if v is None else f"{v:.2f}x"


def is_lender(f: dict) -> bool:
    """Bank / NBFC / insurer, for whom debt and cash-flow pillars do not apply."""
    hay = " ".join(str(x or "").lower() for x in (f.get("sector"), f.get("industry")))
    if any(p in hay for p in LENDER_PATTERNS):
        return True
    # Fallback for a page with no taxonomy: lenders report interest as their main line.
    pl = f.get("profit_loss") or {}
    return "Financing Profit" in pl or "Financing Margin %" in pl


# ── the seven pillars ────────────────────────────────────────────────────────────
# Each returns (score 0-10, reason, inputs) or None when it has nothing to judge.


def _p_returns(f: dict):
    r = f.get("ratios") or {}
    ranges = f.get("ranges") or {}
    roce = r.get("ROCE")
    roe_now = r.get("ROE")
    roe_3y = (ranges.get("Return on Equity") or {}).get("3 Years")

    if is_lender(f):
        # A lender's capital employed includes its deposits and borrowings, which is what
        # it lends out — so ROCE reads at 6-8% for even an excellent bank and means
        # nothing here. ROE is the measure the whole sector is actually judged on.
        primary = roe_now if roe_now is not None else roe_3y
        if primary is None:
            return None
        score = _band(primary, [(20, 10), (17, 9), (15, 8), (12.5, 6.5), (10, 5), (7, 3.5), (4, 2)])
        if roe_3y is not None and roe_3y < 10 and score > 5:
            score -= 1.0
        reason = (f"ROE of {_pct(primary)}"
                  + (f" against a 3-year average of {_pct(roe_3y)}" if roe_3y is not None else "")
                  + ". " + ("Excellent returns on shareholder capital for a lender." if primary >= 17 else
                            "Healthy returns on equity." if primary >= 14 else
                            "Modest returns for a lender." if primary >= 10 else
                            "Weak returns on equity.")
                  + " ROCE is ignored for banks and NBFCs — their capital employed is the deposits "
                    "and borrowings they lend out, so it reads low for even an excellent lender.")
        return (max(0.0, min(10.0, score)), reason,
                {"roe": roe_now, "roe_3y": roe_3y, "roce_ignored": roce})

    # ROCE is the primary read; ROE 3y guards against a good single year.
    primary = roce if roce is not None else roe_now
    if primary is None:
        return None

    score = _band(primary, [(25, 10), (20, 9), (17, 8), (14, 6.5), (11, 5), (8, 3.5), (5, 2)])
    if roe_3y is not None and roe_3y < 10 and score > 5:
        score -= 1.0          # a flattering current year over a weak 3-year record
    label = "ROCE" if roce is not None else "ROE"
    reason = (f"{label} of {_pct(primary)}"
              + (f", with a 3-year ROE of {_pct(roe_3y)}" if roe_3y is not None else "")
              + ". " + ("Earns well above its cost of capital." if primary >= 17 else
                        "Comfortably above cost of capital." if primary >= 14 else
                        "Around the cost of capital — capital is not compounding fast." if primary >= 10 else
                        "Below any sensible cost of capital; the business destroys value as it grows."))
    return max(0.0, min(10.0, score)), reason, {"roce": roce, "roe": roe_now, "roe_3y": roe_3y}


def _series_cagr(values, periods, years: int = 3) -> float | None:
    """CAGR in percent over the last `years` ANNUAL columns of a screener statement.

    The trailing 'TTM' column is dropped first: it overlaps the final year, so leaving it
    in would compress the period and overstate the rate. Returns None where the base is
    zero or negative, because a growth rate off a loss is not a meaningful number.
    """
    if not values or not periods:
        return None
    pairs = [(p, v) for p, v in zip(periods, values)
             if v is not None and "TTM" not in str(p).upper()]
    if len(pairs) < years + 1:
        return None
    base, latest = pairs[-(years + 1)][1], pairs[-1][1]
    if base is None or base <= 0 or latest is None or latest <= 0:
        return None
    return ((latest / base) ** (1 / years) - 1) * 100


def _p_growth(f: dict):
    ranges = f.get("ranges") or {}
    pl = f.get("profit_loss") or {}
    periods = f.get("profit_loss_periods") or []
    sales = ranges.get("Compounded Sales Growth") or {}
    profit = ranges.get("Compounded Profit Growth") or {}
    s3, s5 = sales.get("3 Years"), sales.get("5 Years")
    p3, p5 = profit.get("3 Years"), profit.get("5 Years")
    ttm = profit.get("TTM")

    s = s3 if s3 is not None else s5
    p = p3 if p3 is not None else p5

    # A company that changed its financial year leaves screener's CAGR cells blank even
    # though the yearly statement is right there. Computing from the statement keeps the
    # heaviest pillar alive instead of dropping it over a formatting gap.
    computed = False
    if s is None:
        s = _series_cagr(pl.get("Sales") or pl.get("Revenue"), periods)
        computed = computed or s is not None
    if p is None:
        p = _series_cagr(pl.get("Net Profit"), periods)
        computed = computed or p is not None

    if s is None and p is None:
        return None

    parts, scores = [], []
    if s is not None:
        scores.append(_band(s, [(20, 10), (15, 8.5), (10, 7), (7, 5.5), (4, 4), (0, 2.5)]))
        parts.append(f"sales compounding at {_pct(s)}")
    if p is not None:
        scores.append(_band(p, [(22, 10), (16, 8.5), (11, 7), (7, 5.5), (3, 4), (0, 2.5)]))
        parts.append(f"profit at {_pct(p)}")

    score = sum(scores) / len(scores)
    if ttm is not None and ttm < -10:
        score -= 1.5
        parts.append(f"but the trailing year is down {_pct(abs(ttm))}")
    elif ttm is not None and ttm > 20:
        score += 0.5
        parts.append(f"and the trailing year is up {_pct(ttm)}")

    verdict = ("Growing strongly." if score >= 8 else "Growing steadily." if score >= 6.5
               else "Slow growth." if score >= 4.5 else "Stagnant or shrinking.")
    note = (" Computed from the yearly statement — screener.in leaves the compounded cells "
            "blank for this company, usually a changed financial year." if computed else "")
    return (max(0.0, min(10.0, score)),
            f"Over 3-5 years, {', '.join(parts)}. {verdict}{note}",
            {"sales_cagr": round(s, 1) if s is not None else None,
             "profit_cagr": round(p, 1) if p is not None else None,
             "profit_ttm": ttm, "computed_from_statement": computed})


def _p_profitability(f: dict):
    pl = f.get("profit_loss") or {}

    if is_lender(f):
        # "Financing Margin %" nets interest paid against interest earned, so it runs at a
        # few percent for a perfectly healthy bank and is not comparable to a
        # manufacturer's OPM. Net profit against revenue is the honest read for a lender.
        profits = [v for v in (pl.get("Net Profit") or []) if v is not None]
        revenue = [v for v in (pl.get("Revenue") or pl.get("Sales") or []) if v is not None]
        if not profits or not revenue:
            return None
        n = min(len(profits), len(revenue))
        now = profits[-1] / revenue[-1] * 100 if revenue[-1] else None
        if now is None:
            return None
        then = (profits[-4] / revenue[-4] * 100) if n >= 4 and revenue[-4] else None
        score = _band(now, [(28, 10), (22, 8.5), (17, 7), (12, 5.5), (7, 4), (0, 2.5)])
        drift = (now - then) if then is not None else None
        if drift is not None and drift >= 3:
            score += 0.75
        elif drift is not None and drift <= -3:
            score -= 1.0
        return (max(0.0, min(10.0, score)),
                f"Net profit margin {_pct(now)} of revenue"
                + (f", against {_pct(then)} three years ago" if then is not None else "")
                + ". " + ("Highly profitable lender." if now >= 22 else
                          "Solidly profitable." if now >= 15 else
                          "Thin profitability for a lender." if now >= 8 else
                          "Barely profitable.")
                + " Operating margin is not used for banks and NBFCs.",
                {"net_margin_now": round(now, 2),
                 "net_margin_3y_ago": round(then, 2) if then is not None else None})

    opm = [v for v in (pl.get("OPM %") or []) if v is not None]
    if not opm:
        return None
    now = opm[-1]
    then = opm[-4] if len(opm) >= 4 else opm[0]
    drift = now - then

    score = _band(now, [(25, 10), (18, 8.5), (13, 7), (9, 5.5), (5, 4), (0, 2.5)])
    if drift >= 3:
        score += 0.75
    elif drift <= -3:
        score -= 1.0

    direction = ("widening" if drift >= 1.5 else "narrowing" if drift <= -1.5 else "flat")
    return (max(0.0, min(10.0, score)),
            f"Operating margin {_pct(now)}, {direction} from {_pct(then)} three years ago. "
            + ("Strong pricing power." if now >= 20 else
               "Healthy margin." if now >= 13 else
               "Thin margin — little room for error." if now >= 6 else
               "Barely profitable at the operating line."),
            {"opm_now": now, "opm_3y_ago": then, "drift": round(drift, 2)})


def _p_balance_sheet(f: dict):
    if is_lender(f):
        return None                      # see the module docstring
    bs = f.get("balance_sheet") or {}
    pl = f.get("profit_loss") or {}
    borrow = _latest(bs.get("Borrowings"))
    equity = _latest(bs.get("Equity Capital"))
    reserves = _latest(bs.get("Reserves"))
    if borrow is None or reserves is None:
        return None
    net_worth = (equity or 0) + reserves
    if net_worth <= 0:
        return 0.5, "Net worth is negative or zero — the balance sheet is impaired.", \
               {"borrowings": borrow, "net_worth": net_worth}

    de = borrow / net_worth
    score = _band(de, [(0.1, 10), (0.3, 9), (0.6, 7.5), (1.0, 6), (1.75, 4.5), (2.5, 3), (4, 1.5)],
                  reverse=True)

    # Interest cover is the second read: leverage only bites when it cannot be serviced.
    op = _latest(pl.get("Operating Profit"))
    interest = _latest(pl.get("Interest"))
    cover = (op / interest) if (op is not None and interest) else None
    if cover is not None:
        if cover >= 8:
            score = min(10.0, score + 0.75)
        elif cover < 2.5:
            score -= 2.0

    return (max(0.0, min(10.0, score)),
            f"Borrowings of Rs{borrow:,.0f} Cr against a net worth of Rs{net_worth:,.0f} Cr "
            f"({_x(de)} debt-to-equity)"
            + (f", interest covered {_x(cover)} by operating profit" if cover is not None else "")
            + ". " + ("Effectively debt-free." if de <= 0.15 else
                      "Comfortably financed." if de <= 0.6 else
                      "Carries real leverage." if de <= 1.75 else
                      "Heavily indebted — the lenders have first claim on this business."),
            {"debt_to_equity": round(de, 2), "borrowings": borrow,
             "net_worth": net_worth, "interest_cover": round(cover, 2) if cover else None})


def _p_cash(f: dict):
    if is_lender(f):
        return None                      # see the module docstring
    cf = f.get("cash_flow") or {}
    pl = f.get("profit_loss") or {}
    cfo = [v for v in (cf.get("Cash from Operating Activity") or []) if v is not None]
    profits = [v for v in (pl.get("Net Profit") or []) if v is not None]
    if len(cfo) < 2 or len(profits) < 2:
        return None

    n = min(3, len(cfo), len(profits))
    cfo_sum, profit_sum = sum(cfo[-n:]), sum(profits[-n:])
    if profit_sum <= 0:
        return (2.0, f"No positive profit over the last {n} years to convert into cash.",
                {"cfo_sum": cfo_sum, "profit_sum": profit_sum, "years": n})

    ratio = cfo_sum / profit_sum
    score = _band(ratio, [(1.1, 10), (0.9, 9), (0.75, 7.5), (0.6, 6), (0.4, 4), (0.2, 2.5)])
    return (max(0.0, min(10.0, score)),
            f"Over {n} years the business generated Rs{cfo_sum:,.0f} Cr of operating cash "
            f"against Rs{profit_sum:,.0f} Cr of reported profit ({_x(ratio)} conversion). "
            + ("Profits are real cash." if ratio >= 0.9 else
               "Most profit converts to cash." if ratio >= 0.7 else
               "A large share of profit is not arriving as cash." if ratio >= 0.4 else
               "Reported profit is largely not turning into cash — treat the earnings with suspicion."),
            {"cfo_sum": cfo_sum, "profit_sum": profit_sum,
             "conversion": round(ratio, 2), "years": n})


def _p_valuation(f: dict):
    r = f.get("ratios") or {}
    pe = r.get("Stock P/E")
    if pe is None or pe <= 0:
        return None
    growth = (f.get("ranges", {}).get("Compounded Profit Growth") or {}).get("3 Years")

    score = _band(pe, [(12, 10), (18, 8.5), (25, 7), (35, 5.5), (50, 4), (75, 2.5)], reverse=True)
    peg = None
    if growth and growth > 0:
        peg = pe / growth
        if peg <= 1.0:
            score = min(10.0, score + 1.5)
        elif peg <= 1.5:
            score = min(10.0, score + 0.75)
        elif peg > 3:
            score -= 1.25

    return (max(0.0, min(10.0, score)),
            f"Trades at {pe:.1f}x earnings"
            + (f", a PEG of {peg:.2f} against {_pct(growth)} profit growth" if peg else "")
            + ". " + ("Cheap against its own earnings." if score >= 8 else
                      "Fairly priced." if score >= 6 else
                      "Richly priced — the growth has to show up." if score >= 4 else
                      "Expensive; the price already assumes a lot."),
            {"pe": pe, "profit_cagr_3y": growth, "peg": round(peg, 2) if peg else None})


def _p_ownership(f: dict):
    sh = f.get("shareholding") or {}
    prom = [v for v in (sh.get("Promoters") or []) if v is not None]
    fii_all = [v for v in (sh.get("FIIs") or []) if v is not None]
    dii_all = [v for v in (sh.get("DIIs") or []) if v is not None]

    # HDFC Bank, ITC, L&T and most large private banks have no promoter group at all —
    # screener omits the row entirely. That is a fact about the company, not a gap in the
    # data, so it is judged on institutional conviction instead of being dropped with a
    # misleading "not published".
    if not prom or max(prom) <= 0.0:
        if not fii_all or not dii_all:
            return None
        held = fii_all[-1] + dii_all[-1]
        prev = (fii_all[0] + dii_all[0]) if len(fii_all) > 1 and len(dii_all) > 1 else None
        score = _band(held, [(60, 9), (45, 8), (30, 7), (20, 6), (0, 5)])
        drift = (held - prev) if prev is not None else None
        if drift is not None and drift >= 2:
            score = min(10.0, score + 0.5)
        elif drift is not None and drift <= -2:
            score -= 1.0
        return (max(0.0, min(10.0, score)),
                f"No promoter group — the company is professionally managed and widely held. "
                f"Institutions own {held:.1f}%"
                + (f", {'up' if drift and drift > 0 else 'down'} from {prev:.1f}%"
                   if drift is not None and abs(drift) >= 0.5 else "")
                + ". Judged on institutional conviction, since there is no promoter stake to read.",
                {"promoter_now": None, "no_promoter": True, "institutional": round(held, 2),
                 "fii": fii_all[-1], "dii": dii_all[-1]})

    now = prom[-1]
    then = prom[0]
    drift = now - then

    score = _band(now, [(60, 9.5), (50, 8.5), (40, 7), (30, 5.5), (20, 4.5), (0, 3.5)])
    # Direction matters more than level: promoters selling down is the louder signal.
    if drift <= -2:
        score -= 2.0
    elif drift <= -0.5:
        score -= 0.75
    elif drift >= 2:
        score += 1.0

    fii = [v for v in (sh.get("FIIs") or []) if v is not None]
    dii = [v for v in (sh.get("DIIs") or []) if v is not None]
    inst = ""
    if fii and dii:
        inst = f" Institutions hold {fii[-1] + dii[-1]:.1f}%."

    direction = ("rising" if drift >= 0.5 else "falling" if drift <= -0.5 else "steady")
    return (max(0.0, min(10.0, score)),
            f"Promoters hold {_pct(now)}, {direction} from {_pct(then)} over the quarters shown.{inst} "
            + ("Promoters selling into the market is the single loudest warning here."
               if drift <= -2 else
               "Skin in the game." if now >= 50 else
               "Modest promoter stake." if now >= 30 else
               "Low promoter ownership — no one holder is anchored to the outcome."),
            {"promoter_now": now, "promoter_then": then, "drift": round(drift, 2),
             "fii": fii[-1] if fii else None, "dii": dii[-1] if dii else None})


PILLAR_FUNCS = {
    "returns": _p_returns,
    "growth": _p_growth,
    "profitability": _p_profitability,
    "balance_sheet": _p_balance_sheet,
    "cash": _p_cash,
    "valuation": _p_valuation,
    "ownership": _p_ownership,
}

PILLAR_LABELS = {
    "returns": "Return on capital",
    "growth": "Growth",
    "profitability": "Profitability",
    "balance_sheet": "Balance sheet",
    "cash": "Cash conversion",
    "valuation": "Valuation",
    "ownership": "Promoter ownership",
}


def _verdict(score: float) -> tuple[str, str]:
    if score >= 8.5:
        return "Fundamentally strong", "strong"
    if score >= 7.0:
        return "Good, with minor blemishes", "good"
    if score >= 5.5:
        return "Mixed — strengths and real weaknesses", "mixed"
    if score >= 4.0:
        return "Fundamentally weak", "weak"
    return "Fundamentally poor", "poor"


def rate(f: dict) -> dict:
    """Score one company's parsed screener.in fundamentals out of 10."""
    pillars, skipped = [], []
    lender = is_lender(f)

    for key, weight in PILLARS.items():
        try:
            result = PILLAR_FUNCS[key](f)
        except Exception:                                # one bad row must not sink the rating
            logger.exception("pillar %s failed for %s", key, f.get("symbol"))
            result = None
        if result is None:
            why = ("not meaningful for a bank/NBFC — borrowing is its raw material"
                   if lender and key in ("balance_sheet", "cash")
                   else "screener.in did not publish the inputs")
            skipped.append({"pillar": key, "label": PILLAR_LABELS[key],
                            "weight": weight, "why": why})
            continue
        score, reason, inputs = result
        pillars.append({"pillar": key, "label": PILLAR_LABELS[key],
                        "score": round(score, 1), "weight": weight,
                        "reason": reason, "inputs": inputs})

    if not pillars:
        return {"symbol": f.get("symbol"), "name": f.get("name"), "rated": False,
                "score": None, "verdict": "Not enough data to rate", "band": "unknown",
                **grade(None, "company"),
                "pillars": [], "skipped": skipped, "coverage": 0.0,
                "summary": "screener.in returned a page, but none of the seven pillars had "
                           "the numbers behind them — nothing here is worth a score."}

    # Redistribute the weight of dropped pillars over the ones that survived, so a
    # missing input never reads as a bad input.
    live_weight = sum(p["weight"] for p in pillars)
    score = sum(p["score"] * p["weight"] for p in pillars) / live_weight
    for p in pillars:
        p["effective_weight"] = round(p["weight"] / live_weight, 3)

    score = round(max(1.0, min(10.0, score)), 1)
    verdict, band = _verdict(score)
    ranked = sorted(pillars, key=lambda p: p["score"])
    strongest, weakest = ranked[-1], ranked[0]

    summary = (f"{f.get('name') or f.get('symbol')} rates {score}/10 — {verdict.lower()}. "
               f"Strongest: {strongest['label'].lower()} ({strongest['score']}/10). "
               f"Weakest: {weakest['label'].lower()} ({weakest['score']}/10).")
    if lender:
        summary += " Scored as a lender: debt and cash-conversion pillars do not apply."
    if live_weight < 0.75:
        summary += (f" Only {live_weight * 100:.0f}% of the intended weight had data, so treat "
                    "this as indicative rather than settled.")

    return {
        "symbol": f.get("symbol"), "name": f.get("name"),
        "sector": f.get("sector"), "industry": f.get("industry"),
        "rated": True, "score": score, "verdict": verdict, "band": band,
        **grade(score, "company"),
        "is_lender": lender,
        "coverage": round(live_weight, 3),
        "pillars": sorted(pillars, key=lambda p: -p["weight"]),
        "skipped": skipped,
        "summary": summary,
        "price": (f.get("ratios") or {}).get("Current Price"),
        "market_cap_cr": (f.get("ratios") or {}).get("Market Cap"),
        "pe": (f.get("ratios") or {}).get("Stock P/E"),
        "roce": (f.get("ratios") or {}).get("ROCE"),
        "screener_pros": f.get("pros") or [],
        "screener_cons": f.get("cons") or [],
        "basis": f.get("basis"),
        "source_url": f.get("source_url"),
        "data_missing": f.get("missing") or [],
    }
