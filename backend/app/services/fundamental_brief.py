"""A few sentences about the company's fundamentals, written to be read and pasted.

WHY THE SERVER WRITES THIS AND NOT THE PAGE
The brief has to say the same thing as the score, and the score is computed here. A
sentence assembled in the browser from a handful of fields would drift from the pillars
the moment a threshold moved, and nobody would notice — the number and the words would
just quietly stop agreeing. Composing it next to the rating means the brief is built from
the same pillar objects the score was, including which pillar came out best and worst.

WHAT IT SAYS, AND IN WHAT ORDER
The order is the order a person asks the questions in: what is it and how good is it,
what is the best thing about it, what is the worst, how is it doing right now, and is
there anything about the rating itself I should distrust. Every clause carries a real
number, because "strong balance sheet" is worth nothing next to "debt-to-equity of 0.05".

NO ADJECTIVES THE SCORE DOES NOT SUPPORT
The wording is chosen from the pillar's own score, so a 9-out-of-10 balance sheet is
"effectively debt-free" and a 5 is "carries real leverage". Nothing here reaches for a
verdict the rating did not reach, and nothing recommends an action — the module rates
filings, it does not know what the reader should do.
"""

import logging

logger = logging.getLogger("fundamental_brief")

# The clause each pillar contributes. Written to follow its own LABEL without repeating it
# — "its strongest ground is return on capital, at 26.6%" rather than "... is return on
# capital: a return on capital of 26.6%".
_FACTS = {
    "returns": lambda i: (f"at {i['roce']:.1f}%" if i.get("roce") is not None
                          else f"at a return on equity of {i['roe']:.1f}%"
                          if i.get("roe") is not None else None),
    "growth": lambda i: (
        f"with sales compounding at {i['sales_cagr']:.0f}% and profit at {i['profit_cagr']:.0f}%"
        if i.get("sales_cagr") is not None and i.get("profit_cagr") is not None
        else f"with sales compounding at {i['sales_cagr']:.0f}%" if i.get("sales_cagr") is not None
        else f"with profit compounding at {i['profit_cagr']:.0f}%" if i.get("profit_cagr") is not None
        else None),
    "profitability": lambda i: (f"at an operating margin of {i['opm_now']:.0f}%"
                                if i.get("opm_now") is not None
                                else f"at a net margin of {i['net_margin_now']:.0f}%"
                                if i.get("net_margin_now") is not None else None),
    "balance_sheet": lambda i: (f"with borrowings at {i['debt_to_equity']:.2f} times net worth"
                                if i.get("debt_to_equity") is not None else None),
    "cash": lambda i: (f"at {i['conversion']:.2f} rupees of operating cash for every rupee of "
                       "reported profit" if i.get("conversion") is not None else None),
    "valuation": lambda i: (f"at {i['pe']:.0f} times earnings" if i.get("pe") is not None
                            else None),
    "ownership": lambda i: (f"with promoters holding {i['promoter_now']:.0f}%"
                            if i.get("promoter_now") is not None
                            else f"with institutions holding {i['institutional']:.0f}% and no "
                                 "promoter group" if i.get("institutional") is not None else None),
}


def _fact(pillar: dict) -> str | None:
    fn = _FACTS.get(pillar.get("pillar"))
    if not fn:
        return None
    try:
        return fn(pillar.get("inputs") or {})
    except Exception:                                    # a fact is never worth an exception
        return None


def _quality(score: float) -> str:
    if score >= 9:
        return "exceptional"
    if score >= 7.8:
        return "strong"
    if score >= 6.2:
        return "solid"
    if score >= 4.6:
        return "unremarkable"
    if score >= 3.4:
        return "poor"
    return "very poor"


def compose(r: dict, q: dict | None = None, p: dict | None = None) -> dict:
    """Return {'brief': prose, 'copy_text': the same plus the identifying facts}."""
    name = r.get("name") or r.get("symbol") or "This company"
    symbol = r.get("symbol") or ""
    score = r.get("score")
    grade = (r.get("grade") or "").lower()
    pillars = [x for x in (r.get("pillars") or []) if x.get("score") is not None]

    if score is None or not pillars:
        brief = (f"{name} could not be rated — screener.in did not return enough of its "
                 "filings to judge the business on.")
        head = f"{name}" + (f" ({symbol})" if symbol else "") + " — not rated"
        return {"brief": brief, "copy_text": brief, "headline_text": head}

    what = r.get("industry") or r.get("sector")
    ranked = sorted(pillars, key=lambda x: x["score"])
    best, worst = ranked[-1], ranked[0]

    # 1. what it is and how good it is
    sentences = [
        f"{name}" + (f" ({what.lower()})" if what else "")
        + f" scores {score}/10 — {grade or 'rated'}."
    ]

    # 2. the best thing about it, with the number behind it
    best_fact = _fact(best)
    if best_fact:
        sentences.append(
            f"Its strongest ground is {best['label'].lower()}, {best_fact} — "
            f"{_quality(best['score'])}."
        )

    # 3. the worst thing, only where it is actually a weakness
    worst_fact = _fact(worst)
    if worst_fact and worst["score"] < 6.5 and worst["pillar"] != best["pillar"]:
        lead = "The weak point is" if worst["score"] >= 4 else "The clear problem is"
        sentences.append(f"{lead} {worst['label'].lower()}, {worst_fact}.")
    elif worst["score"] >= 6.5:
        sentences.append("Nothing in the seven pillars comes out badly — the weakest, "
                         f"{worst['label'].lower()}, still scores {worst['score']}/10.")

    # 4. how it is doing right now, and over the years
    now_bits = []
    if q and q.get("score") is not None:
        tier = (q.get("tier") or "").lower()
        now_bits.append(f"the latest quarter is {tier}"
                        + (f" ({q['latest_quarter']})" if q.get("latest_quarter") else ""))
    if p and p.get("score") is not None:
        now_bits.append(f"the multi-year P&L record is {(p.get('tier') or '').lower()}")
    if now_bits:
        sentences.append("On the statements, " + " and ".join(now_bits) + ".")

    # 5. anything that should make the reader trust the rating less
    caveats = []
    if r.get("is_lender"):
        caveats.append("scored as a lender, so the debt and cash-conversion pillars do not apply")
    if (r.get("coverage") or 1) < 0.75:
        caveats.append(f"only {round((r.get('coverage') or 0) * 100)}% of the intended weight "
                       "had data behind it")
    if (q or {}).get("one_off_flag") or (p or {}).get("one_off_flag"):
        caveats.append("one-off other income distorts the net-profit line in at least one "
                       "period, so the operating lines are the honest read")
    if caveats:
        sentences.append("Worth knowing: " + "; ".join(caveats) + ".")

    brief = " ".join(sentences)

    # The headline is composed once and reused, so the small Copy button beside the grades
    # and the big one under the brief can never disagree about what the grades are.
    head = f"{name}" + (f" ({symbol})" if symbol else "")
    headline_lines = [f"{head} — {score}/10, {r.get('grade') or ''}".rstrip(" ,-")]
    grades = []
    if q and q.get("score") is not None:
        grades.append(f"Quarter {q['score']}/10 ({q.get('tier')})")
    if p and p.get("score") is not None:
        grades.append(f"P&L record {p['score']}/10 ({p.get('tier')})")
    if grades:
        headline_lines.append(" · ".join(grades))
    headline_text = "\n".join(headline_lines)

    lines = list(headline_lines) + ["", brief, ""]

    facts = []
    if r.get("price") is not None:
        facts.append(f"Price Rs{r['price']:,.0f}")
    if r.get("market_cap_cr") is not None:
        facts.append(f"M-cap Rs{r['market_cap_cr']:,.0f} Cr")
    if r.get("pe") is not None:
        facts.append(f"P/E {r['pe']:.1f}")
    if r.get("roce") is not None:
        facts.append(f"ROCE {r['roce']:.1f}%")
    if facts:
        lines.append(" · ".join(facts))
    lines.append("Pillars: " + ", ".join(f"{x['label']} {x['score']}" for x in
                                         sorted(pillars, key=lambda z: -z["score"])))
    if r.get("source_url"):
        lines.append(f"Source: {r['source_url']}")
    lines.append("Rated from public filings — research aid, not investment advice.")

    return {"brief": brief, "copy_text": "\n".join(lines), "headline_text": headline_text}
