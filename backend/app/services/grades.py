"""The nine-tier grade every score in this module is reported as.

One scale, used in three places — the company overall, its latest quarter, and its
multi-year profit & loss record — so "excellent" means the same distance above average
wherever it appears, and the three grades can be read against each other at a glance.

WHERE THE BOUNDARIES COME FROM
The scale is centred, not stretched to flatter. "Average" straddles 5.0 on a 1-10 score,
which is what an unremarkable listed company actually earns here: a mid-teens ROCE, growth
around nominal GDP, a clean but unexciting balance sheet. The tiers then widen as they go
out, because the difference between 8.4 and 9.0 is a far rarer thing than the difference
between 4.6 and 5.4.

For calibration, on the large caps this was built against: Reliance lands in "good",
Vedanta and NRB Bearings in "very good", ITC/Infosys/Nestle/HDFC Bank in "excellent",
TCS at the bottom of "extraordinary". "Explosive" is deliberately almost empty — a company
has to be near the top of every pillar at once to reach it, and if a quarter of the market
were scoring it the word would mean nothing.

THE NOUN CHANGES, THE TIER DOES NOT
`grade(score, "company" | "quarter" | "pnl")` returns the same nine tier names with the
subject attached, so a card can say "Excellent fundamentals", "Excellent quarterly
results" and "Excellent profit & loss record" without three separate vocabularies.
"""

# (minimum score, tier name, stable key for styling). Ordered best first.
TIERS: list[tuple[float, str, str]] = [
    (9.0, "Explosive", "explosive"),
    (8.4, "Extraordinary", "extraordinary"),
    (7.8, "Excellent", "excellent"),
    (7.0, "Very good", "very-good"),
    (6.2, "Good", "good"),
    (5.4, "Above average", "above-average"),
    (4.6, "Average", "average"),
    (3.4, "Below average", "below-average"),
    (0.0, "Worst", "worst"),
]

SUBJECTS = {
    "company": "fundamentals",
    "quarter": "quarterly results",
    "pnl": "profit & loss record",
}

# Ordered worst -> best, for filter dropdowns and legends that read bottom-up.
ORDER = [key for _, _, key in reversed(TIERS)]


def tier(score: float | None) -> tuple[str, str]:
    """(tier name, key) for a 1-10 score."""
    if score is None:
        return "Not rated", "unrated"
    for minimum, name, key in TIERS:
        if score >= minimum:
            return name, key
    return "Worst", "worst"


def grade(score: float | None, subject: str = "company") -> dict:
    """The full grade for a score: tier, key, and the phrase to print."""
    name, key = tier(score)
    noun = SUBJECTS.get(subject, SUBJECTS["company"])
    return {
        "grade": f"{name} {noun}" if key != "unrated" else f"Not rated — {noun}",
        "tier": name,
        "grade_key": key,
        "subject": subject,
    }


def scale(subject: str = "company") -> list[dict]:
    """The whole ladder, for a legend or a filter list. Worst first."""
    noun = SUBJECTS.get(subject, SUBJECTS["company"])
    out = []
    for i, (minimum, name, key) in enumerate(reversed(TIERS)):
        # The top of a tier is the bottom of the next one up, and 10 for the highest.
        upper = list(reversed(TIERS))[i + 1][0] if i + 1 < len(TIERS) else 10.0
        out.append({"tier": name, "grade_key": key, "grade": f"{name} {noun}",
                    "from": minimum, "to": round(upper - 0.1, 1) if upper < 10 else 10.0})
    return out
