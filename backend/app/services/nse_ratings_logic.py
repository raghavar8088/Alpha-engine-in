"""NSE Stock Ratings: the rules that turn one company into one row of the table.

Pure functions, with no database and no network. That way every rule can be checked
offline against real pages (backend/tests/fundamentals/verify_nse_ratings.py), and the
table, the detail drawer and the background refresher can never compute a row three
different ways.

THE SCORES ARE THE MODULE'S OWN, UNCHANGED
Fundamentals, latest quarter and P&L record come from `fundamental_rating.rate`,
`results_strength.analyse` and `pnl_strength.analyse`. These are the calls the Rate tab
makes, on the same cached screener.in page. Nothing here re-weights a pillar or re-bands
a quarter. The quarterly revenue and profit columns are computed with the quarterly read's
own helpers (`_growth`, `_is_distorted`). So a growth rate off a loss is "not meaningful"
in this table exactly when it is on the card, and a net profit driven by other income is
flagged in both places or in neither.

THE OVERALL RATING IS A BLEND OF THE MODULE'S THREE GRADES, AND THE WEIGHTS ARE WRITTEN DOWN
    overall = 70% fundamentals + 15% latest quarter + 15% P&L record
The seven-pillar fundamentals score is the lasting judgement of the business, so it
carries most of the weight. The latest quarter and the P&L record can each move it, but
neither can lift a weak business into a strong grade on its own: a perfect quarter raises
the overall by at most 0.15 x (10 - fundamentals). A grade with no data is dropped and its
weight is shared over the others. That is the module's rule for a missing pillar too,
because a missing number is not a bad number. The overall uses the same nine-tier scale as
every other grade here.

INSUFFICIENT DATA IS ITS OWN VERDICT, NEVER A LOW SCORE
A company is marked "Insufficient Data", with the reason written out, when:
  * there is no fundamentals score at all (no screener.in page, or none of its inputs);
  * fewer than 4 of the pillars that apply to it had data, or less than 60% of their
    weight (banks and NBFCs have five applicable pillars, everyone else has seven); or
  * its latest filed quarter is two or more quarters past the SEBI deadline. The numbers
    then describe the business as it was most of a year ago.
Scoring a missing number as zero would say "this company is bad". The truth is "we cannot
tell", and the table says that instead.

FRESHNESS FOLLOWS THE FILING CALENDAR, NOT THE AGE OF THE CACHE
Under SEBI LODR Regulation 33, quarterly results are due within 45 days of the quarter's
end, and the March quarter (filed with the audited annual accounts) within 60. A row is
  current   when its latest quarter is the newest one that has ended;
  due       when it is one quarter behind, but that quarter's deadline has not passed yet;
  outdated  when it is behind a quarter whose deadline, plus a 7-day grace, has passed.
Separately, a row is PENDING when NSE lists a results board meeting dated after the
latest quarter in the rating. That means new results are out but not yet read, and it is
what triggers a refresh.

RETURNS ARE PRICE RETURNS, ADJUSTED FOR SHARE-COUNT CHANGES
They compare closes from NSE's end-of-day bhavcopy. The starting close is multiplied by
every bonus, split and consolidation factor that went ex in between. The bhavcopy itself
is NOT adjusted for these: its PREV_CLOSE on an ex-date is the raw close (verified in the
Nov 2026 NSE research), so an unadjusted 1:1 bonus would show as a 50% crash. Rights
issues, demergers, capital reductions and preference-share bonuses move the price in a way
the share count does not capture, so they are named in a note on the affected returns
rather than guessed at. Dividends are not added back: these are price returns, not total
returns.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone

from app.services.fundamental_rating import PILLARS, PILLAR_LABELS
from app.services.grades import grade
from app.services.results_strength import _at, _growth, _is_distorted, _vals

IST = timezone(timedelta(hours=5, minutes=30))

# Bump when a rule below changes what a row holds: the refresher then rebuilds every row
# from the cached screener.in pages, without fetching any of them again.
ROW_VERSION = 1

OVERALL_WEIGHTS = {"fundamentals": 0.70, "quarter": 0.15, "pnl": 0.15}
OVERALL_LABELS = {"fundamentals": "Fundamentals", "quarter": "Latest quarter",
                  "pnl": "P&L record"}
MIN_PILLARS = 4
MIN_APPLICABLE_COVERAGE = 0.60
INDICATIVE_COVERAGE = 0.75          # below this a rating is flagged as indicative
OVERDUE_INSUFFICIENT = 2            # quarters past the deadline at which a rating stops

RESULT_DAYS = 45                    # SEBI LODR Reg 33, quarters 1-3
ANNUAL_RESULT_DAYS = 60             # the March quarter, filed with the audited year
GRACE_DAYS = 7                      # screener.in lag + the odd calendar-year filer

STALE_FETCH_DAYS = 45               # say so on the row
STALE_REFETCH_DAYS = 100            # refetch even with no results event
PENDING_BACKOFF_H = (0, 12, 24, 48, 96)   # hours before attempt n+1 for one results event
OVERDUE_RECHECK_DAYS = 7
ERROR_RETRY_DAYS = 7
EVENING_HOUR_IST = 20               # a same-day results meeting is read after this hour

INSUFFICIENT_KEY = "insufficient"
INSUFFICIENT_LABEL = "Insufficient Data"

# ── index membership ─────────────────────────────────────────────────────────────
# The five non-overlapping slices of NSE's broad-market index family, most senior first.
# The composites nest exactly, as checked against niftyindices.com on 10 Nov 2026:
# Nifty 100 = 50 + Next 50, LargeMidcap 250 = 100 + Midcap 150, Nifty 500 = LargeMidcap
# 250 + Smallcap 250, and Total Market = 500 + Microcap 250. So a stock's composite
# memberships are DERIVED from its slice, never fetched separately.
INDEX_SLICES = (
    ("nifty50", "Nifty 50", "ind_nifty50list"),
    ("niftynext50", "Nifty Next 50", "ind_niftynext50list"),
    ("niftymidcap150", "Nifty Midcap 150", "ind_niftymidcap150list"),
    ("niftysmallcap250", "Nifty Smallcap 250", "ind_niftysmallcap250list"),
    ("niftymicrocap250", "Nifty Microcap 250", "ind_niftymicrocap250_list"),
)
OUTSIDE_KEY, OUTSIDE_LABEL = "nserest", "Not in a Nifty index"
COMPOSITES = {
    "nifty50": ("nifty100", "nifty250", "nifty500", "niftytotalmarket"),
    "niftynext50": ("nifty100", "nifty250", "nifty500", "niftytotalmarket"),
    "niftymidcap150": ("nifty250", "nifty500", "niftytotalmarket"),
    "niftysmallcap250": ("nifty500", "niftytotalmarket"),
    "niftymicrocap250": ("niftytotalmarket",),
}
# What the Index filter offers, in the order a person reads them. The keys match the
# Universe tab's (nifty100 / nifty250 / nifty500 / niftytotalmarket / niftymicrocap250 /
# nserest), so the same names mean the same sets across the module.
INDEX_FILTERS = (
    ("nifty50", "Nifty 50"),
    ("niftynext50", "Nifty Next 50"),
    ("nifty100", "Nifty 100"),
    ("niftymidcap150", "Nifty Midcap 150"),
    ("nifty250", "Nifty LargeMidcap 250"),
    ("niftysmallcap250", "Nifty Smallcap 250"),
    ("nifty500", "Nifty 500"),
    ("niftymicrocap250", "Nifty Microcap 250"),
    ("niftytotalmarket", "Nifty Total Market"),
    (OUTSIDE_KEY, OUTSIDE_LABEL),
)


def index_fields(slice_key: str | None) -> dict:
    """The row's index columns, from the one slice it belongs to (or none)."""
    keys = [k for k, _, _ in INDEX_SLICES]
    if slice_key not in keys:
        return {"index_tier": None, "index_label": OUTSIDE_LABEL,
                "idx_rank": len(keys) + 1, "indices": [OUTSIDE_KEY]}
    rank = keys.index(slice_key) + 1
    return {"index_tier": slice_key, "index_label": INDEX_SLICES[rank - 1][1],
            "idx_rank": rank, "indices": [slice_key, *COMPOSITES[slice_key]]}


# ── small helpers ────────────────────────────────────────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "nan", "NaN", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _r(v, d: int = 1):
    return None if v is None else round(v, d)


def as_date(v) -> date | None:
    """A date from a date, a datetime (read in IST) or an ISO string."""
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(IST).date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def aware(v) -> datetime | None:
    """Mongo hands datetimes back naive (they are UTC); make them comparable."""
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def iso(d) -> str | None:
    d = as_date(d)
    return d.isoformat() if d else None


def fmt_day(d) -> str:
    d = as_date(d)
    return f"{d.day} {calendar.month_abbr[d.month]} {d.year}" if d else "—"


def parse_nse_date(s) -> date | None:
    """'06-OCT-2008', '10-Nov-2026', '10-Nov-2026 15:30:00' or '10-11-2026' -> date."""
    s = (s or "").strip()
    if not s:
        return None
    head = s.split(" ")[0]
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


# ── the filing calendar ──────────────────────────────────────────────────────────


def _qe(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def quarter_end(label) -> date | None:
    """screener.in's 'Sep 2026' -> 2026-09-30. None for anything that is not a month."""
    m = re.match(r"^\s*([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{4})\s*$", str(label or ""))
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    return _qe(int(m.group(2)), mon) if mon else None


def qlabel(d) -> str | None:
    d = as_date(d)
    return f"{calendar.month_abbr[d.month]} {d.year}" if d else None


def prev_quarter_end(d: date) -> date:
    """The latest calendar quarter end strictly before `d`."""
    for y in (d.year, d.year - 1):
        for m in (12, 9, 6, 3):
            qe = _qe(y, m)
            if qe < d:
                return qe
    return _qe(d.year - 2, 12)


def _qindex(d: date) -> int:
    return d.year * 4 + (d.month - 1) // 3


def shift_quarter(qe: date, k: int) -> date:
    y, r = divmod(_qindex(qe) + k, 4)
    return _qe(y, r * 3 + 3)


def quarters_between(a: date, b: date) -> int:
    return _qindex(b) - _qindex(a)


def filing_deadline(qe: date) -> date:
    return qe + timedelta(days=ANNUAL_RESULT_DAYS if qe.month == 3 else RESULT_DAYS)


def required_quarter(today: date) -> date:
    """The newest quarter whose filing deadline (plus grace) has already passed."""
    qe = prev_quarter_end(today)
    while filing_deadline(qe) + timedelta(days=GRACE_DAYS) >= today:
        qe = shift_quarter(qe, -1)
    return qe


def freshness(qend: date | None, today: date) -> dict:
    if qend is None:
        return {"state": "unknown", "behind": None, "next_q": None, "next_due": None,
                "required": required_quarter(today)}
    current = prev_quarter_end(today)
    required = required_quarter(today)
    nxt = shift_quarter(qend, 1)
    if qend >= current:
        state, behind = "current", 0
    elif qend >= required:
        state, behind = "due", 0
    else:
        state, behind = "outdated", quarters_between(qend, required)
    return {"state": state, "behind": behind, "next_q": nxt,
            "next_due": filing_deadline(nxt), "required": required}


def pending_refresh(qend: date | None, meetings: list[date], today: date) -> dict:
    """Has NSE listed a results meeting whose quarter the rating does not contain yet?

    A results board meeting on date D approves the quarter that ended before D, and the
    results are disclosed within 30 minutes of it (LODR Reg 30). So a meeting after the
    latest quarter in the rating means newer figures exist.
    """
    past = [m for m in meetings if m <= today]
    upcoming = [m for m in meetings if m > today]
    last = max(past) if past else None
    nxt = min(upcoming) if upcoming else None
    pend = None
    if last is not None:
        expected = prev_quarter_end(last)
        if qend is None or qend < expected:
            pend = {"key": f"{expected.isoformat()}:{last.isoformat()}",
                    "expected": expected, "meeting": last}
    return {"last_meeting": last, "next_meeting": nxt, "pending": pend}


# ── the latest quarter's numbers ─────────────────────────────────────────────────


def _base_note(now, base, when) -> str | None:
    """Words for a comparison whose base is zero or a loss, where % change means nothing."""
    if now is None or base is None or base > 0:
        return None
    if now > 0:
        return f"turned profitable (₹{base:,.0f} Cr in {when})"
    if now > base:
        return f"loss narrowed from ₹{base:,.0f} Cr in {when}"
    return f"loss widened from ₹{base:,.0f} Cr in {when}"


def quarter_numbers(f: dict) -> dict:
    """Latest quarter's revenue and profit with YoY and QoQ, validated as the card is."""
    q = f.get("quarters") or {}
    periods = list(f.get("quarters_periods") or [])
    sales = _vals(q, "Sales", "Revenue")
    op = _vals(q, "Operating Profit", "Financing Profit")
    net = _vals(q, "Net Profit")
    other = _vals(q, "Other Income")
    pbt = _vals(q, "Profit before tax")
    opm = _vals(q, "OPM %", "Financing Margin %")

    label = periods[-1] if periods else None
    yoy_label = periods[-5] if len(periods) >= 5 else None
    prev_label = periods[-2] if len(periods) >= 2 else None
    rev, np_, opq = _at(sales, -1), _at(net, -1), _at(op, -1)

    out = {
        "qlabel": label, "qend": iso(quarter_end(label)), "qyoy_label": yoy_label,
        "qprev_label": prev_label, "quarters_n": len(periods),
        "rev": rev, "rev_yoy": _r(_growth(rev, _at(sales, -5))),
        "rev_qoq": _r(_growth(rev, _at(sales, -2))),
        "np": np_, "np_yoy": _r(_growth(np_, _at(net, -5))),
        "np_qoq": _r(_growth(np_, _at(net, -2))),
        "op": opq, "op_yoy": _r(_growth(opq, _at(op, -5))),
        "op_qoq": _r(_growth(opq, _at(op, -2))),
        "opm_q": _at(opm, -1),
        "np_flag": None, "np_note": None,
    }

    # The quarterly read's own rule: other income large enough to drive net profit makes
    # the net-profit comparison unsafe, at either end of it.
    distorted = [lbl for lbl, idx in ((label, -1), (yoy_label, -5), (prev_label, -2))
                 if lbl and _is_distorted(_at(other, idx), _at(pbt, idx), _at(op, idx))]
    notes = []
    for base_idx, when in ((-5, yoy_label), (-2, prev_label)):
        n = _base_note(np_, _at(net, base_idx), when)
        if n:
            notes.append(("YoY: " if base_idx == -5 else "QoQ: ") + n)
    if distorted:
        out["np_flag"] = "distorted"
        notes.insert(0, "other income drives net profit in " + ", ".join(dict.fromkeys(distorted))
                     + "; read operating profit instead")
    elif notes:
        out["np_flag"] = "base"
    if notes:
        out["np_note"] = "; ".join(notes)
    return out


# ── the fundamental metrics the pillars already read ─────────────────────────────


def metrics(f: dict, r: dict) -> dict:
    pil = {p["pillar"]: (p.get("inputs") or {}) for p in (r.get("pillars") or [])}
    ratios = f.get("ratios") or {}
    ranges = f.get("ranges") or {}
    lender = bool(r.get("is_lender"))
    growth, bs = pil.get("growth", {}), pil.get("balance_sheet", {})
    prof, own = pil.get("profitability", {}), pil.get("ownership", {})
    cash, val = pil.get("cash", {}), pil.get("valuation", {})
    sh = f.get("shareholding") or {}
    fii = [v for v in (sh.get("FIIs") or []) if v is not None]
    dii = [v for v in (sh.get("DIIs") or []) if v is not None]
    pe = num(ratios.get("Stock P/E"))
    return {
        # A lender's ROCE is meaningless (see fundamental_rating), so it is not shown.
        "roce": None if lender else num(ratios.get("ROCE")),
        "roe": num(ratios.get("ROE")),
        "de": None if lender else bs.get("debt_to_equity"),
        "int_cover": None if lender else bs.get("interest_cover"),
        "opm": prof.get("opm_now"),
        "net_margin": prof.get("net_margin_now"),
        "opm_drift": prof.get("drift"),
        "sales_cagr": growth.get("sales_cagr"),
        "profit_cagr": growth.get("profit_cagr"),
        "profit_ttm": growth.get("profit_ttm"),
        "pe": pe if (pe is not None and pe > 0) else None,
        "peg": val.get("peg"),
        "promoter": own.get("promoter_now"),
        "promoter_drift": own.get("drift") if own.get("promoter_now") is not None else None,
        "no_promoter": bool(own.get("no_promoter")),
        "institutional": own.get("institutional") if own.get("institutional") is not None
        else (round(fii[-1] + dii[-1], 2) if fii and dii else None),
        "cash_conv": cash.get("conversion"),
        "mcap": num(ratios.get("Market Cap")),
        "price": num(ratios.get("Current Price")),
        "div_yield": num(ratios.get("Dividend Yield")),
        "screener_1y": num((ranges.get("Stock Price CAGR") or {}).get("1 Year")),
    }


# ── strengths, weaknesses and risks, in words with numbers ───────────────────────

STRENGTH_MIN = 7.5
WEAKNESS_MAX = 5.0


def _fact(p: dict) -> str:
    i = p.get("inputs") or {}
    k = p.get("pillar")
    try:
        if k == "returns":
            if i.get("roce") is not None:
                return f"ROCE {i['roce']:.1f}%"
            if i.get("roe") is not None:
                return f"ROE {i['roe']:.1f}%"
        elif k == "growth":
            bits = []
            if i.get("sales_cagr") is not None:
                bits.append(f"sales {i['sales_cagr']:+.0f}%/yr")
            if i.get("profit_cagr") is not None:
                bits.append(f"profit {i['profit_cagr']:+.0f}%/yr")
            if bits:
                return ", ".join(bits)
        elif k == "profitability":
            if i.get("opm_now") is not None:
                return f"operating margin {i['opm_now']:.0f}%"
            if i.get("net_margin_now") is not None:
                return f"net margin {i['net_margin_now']:.0f}%"
        elif k == "balance_sheet" and i.get("debt_to_equity") is not None:
            return f"debt {i['debt_to_equity']:.2f}× net worth"
        elif k == "cash" and i.get("conversion") is not None:
            return f"{i['conversion']:.2f}× of profit arrives as cash"
        elif k == "valuation" and i.get("pe") is not None:
            return f"P/E {i['pe']:.0f}" + (f", PEG {i['peg']:.1f}" if i.get("peg") else "")
        elif k == "ownership":
            if i.get("promoter_now") is not None:
                drift = i.get("drift") or 0
                return f"promoters {i['promoter_now']:.0f}%" + (
                    f" ({drift:+.1f} pts)" if abs(drift) >= 0.5 else "")
            if i.get("institutional") is not None:
                return f"institutions {i['institutional']:.0f}%, no promoter group"
    except (TypeError, ValueError):
        pass
    return f"{p.get('score', 0):.1f}/10"


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:+.0f}%"


def explain(r: dict, q: dict, p: dict, qn: dict, m: dict, series: str | None) -> dict:
    pillars = [x for x in (r.get("pillars") or []) if x.get("score") is not None]
    strengths = [f"{x['label']} ({_fact(x)})"
                 for x in sorted(pillars, key=lambda x: -x["score"]) if x["score"] >= STRENGTH_MIN][:3]
    weaknesses = [f"{x['label']} ({_fact(x)})"
                  for x in sorted(pillars, key=lambda x: x["score"]) if x["score"] <= WEAKNESS_MAX][:3]

    risks: list[str] = []
    if m.get("de") is not None and m["de"] > 1.0:
        risks.append(f"leverage: borrowings {m['de']:.2f}× net worth")
    if m.get("int_cover") is not None and m["int_cover"] < 2.5:
        risks.append(f"interest covered only {m['int_cover']:.1f}× by operating profit")
    if m.get("cash_conv") is not None and m["cash_conv"] < 0.6:
        risks.append(f"only {m['cash_conv']:.2f}× of reported profit arrived as operating cash")
    if m.get("promoter_drift") is not None and m["promoter_drift"] <= -2:
        risks.append(f"promoters cut their stake by {abs(m['promoter_drift']):.1f} pts")
    elif m.get("promoter") is not None and m["promoter"] < 25:
        risks.append(f"low promoter stake ({m['promoter']:.0f}%)")
    if m.get("pe") is not None and m["pe"] > 60:
        risks.append(f"rich valuation: {m['pe']:.0f}× earnings")
    if m.get("opm_drift") is not None and m["opm_drift"] <= -3:
        risks.append(f"operating margin down {abs(m['opm_drift']):.0f} pts in three years")
    if m.get("profit_ttm") is not None and m["profit_ttm"] < -10:
        risks.append(f"trailing-year profit down {abs(m['profit_ttm']):.0f}%")
    if q.get("score") is not None and q["score"] < 4.6:
        risks.append(f"weak latest quarter ({qn.get('qlabel')}: sales {_pct(qn.get('rev_yoy'))}, "
                     f"operating profit {_pct(qn.get('op_yoy'))} YoY)")
    if qn.get("np") is not None and qn["np"] < 0:
        risks.append(f"loss-making in {qn.get('qlabel')} (net ₹{qn['np']:,.0f} Cr)")
    if q.get("one_off_flag") and qn.get("np_flag") == "distorted":
        risks.append("other income distorts net profit; operating profit is the honest line")
    if m.get("mcap") is not None and m["mcap"] < 500:
        risks.append(f"micro-cap (₹{m['mcap']:,.0f} Cr): thin trading")
    if series == "BE":
        risks.append("BE series: trade-for-trade, delivery only")
    elif series == "BZ":
        risks.append("BZ series: NSE flags it for non-compliance with listing rules")
    risks = risks[:5]

    parts = []
    if strengths:
        parts.append("Strengths: " + "; ".join(strengths))
    if weaknesses:
        parts.append("Weaknesses: " + "; ".join(weaknesses))
    if risks:
        parts.append("Risks: " + "; ".join(risks))
    if not parts and pillars:
        parts.append("No pillar stands out either way; every pillar scores between "
                     f"{WEAKNESS_MAX:g} and {STRENGTH_MIN:g}.")
    return {"strengths": strengths, "weaknesses": weaknesses, "risks": risks,
            "text": ". ".join(parts) + ("." if parts else "")}


def static_flags(f: dict, r: dict, q: dict, qn: dict, coverage: float | None) -> list[dict]:
    """Data-quality notes that depend only on the page, not on today's date."""
    flags = []
    if r.get("is_lender"):
        flags.append({"k": "lender", "lvl": "info",
                      "t": "Scored as a lender: the debt and cash-conversion pillars do not apply"})
    if f.get("basis") == "standalone":
        flags.append({"k": "standalone", "lvl": "info",
                      "t": "Standalone figures: screener.in has no consolidated accounts for it"})
    if coverage is not None and MIN_APPLICABLE_COVERAGE <= coverage < INDICATIVE_COVERAGE:
        flags.append({"k": "coverage", "lvl": "warn",
                      "t": f"Only {coverage * 100:.0f}% of the applicable pillar weight had data, "
                           "so treat the rating as indicative"})
    if not q.get("rated"):
        flags.append({"k": "quarters", "lvl": "warn",
                      "t": q.get("headline") or "Quarterly results could not be read"})
    if qn.get("np_flag") == "distorted":
        flags.append({"k": "oneoff", "lvl": "warn", "t": "Net profit: " + (qn.get("np_note") or "")})
    elif r.get("is_lender") and qn.get("np_note"):
        flags.append({"k": "oneoff", "lvl": "info", "t": "Net profit: " + qn["np_note"]})
    growth = next((p for p in (r.get("pillars") or []) if p.get("pillar") == "growth"), None)
    if growth and (growth.get("inputs") or {}).get("computed_from_statement"):
        flags.append({"k": "growth_computed", "lvl": "info",
                      "t": "Growth computed from the yearly statement; screener.in left its "
                           "compounded-growth cells blank"})
    missing = [m for m in (f.get("missing") or []) if m]
    if missing:
        flags.append({"k": "missing", "lvl": "info",
                      "t": "screener.in did not publish: " + ", ".join(missing)})
    return flags


# ── the row ──────────────────────────────────────────────────────────────────────


def static_row(f: dict, r: dict, q: dict, p: dict, series: str | None = None) -> dict:
    """Everything a row holds that comes from the screener.in page."""
    qn = quarter_numbers(f)
    m = metrics(f, r)
    lender = bool(r.get("is_lender"))
    if lender and qn.get("np_flag") == "distorted":
        # A lender's "other income" is fees, commissions and treasury gains: the business,
        # not a one-off. The module's rule fires on nearly every bank (HDFC Bank: all three
        # quarters), so the table words it as a note instead of a warning.
        qn["np_flag"] = None
        qn["np_note"] = ("other income (fees, treasury) is over a third of pre-tax profit, as at "
                         "most lenders; financing profit is the cleaner line")
    applicable = [k for k in PILLARS if not (lender and k in ("balance_sheet", "cash"))]
    applicable_w = sum(PILLARS[k] for k in applicable)
    pillars = r.get("pillars") or []
    live_w = sum(x.get("weight") or 0 for x in pillars)
    coverage = (live_w / applicable_w) if (applicable_w and pillars) else None
    return {
        "screener_name": r.get("name") or f.get("name"),
        "screener_sector": r.get("sector") or f.get("sector"),
        "industry": r.get("industry") or f.get("industry"),
        "fund": r.get("score"), "fund_key": r.get("grade_key"), "fund_tier": r.get("tier"),
        "fund_verdict": r.get("verdict"),
        "coverage": _r(coverage, 3), "pillars_n": len(pillars),
        "pillars_applicable": len(applicable), "is_lender": lender,
        "pillar_scores": {x["pillar"]: x.get("score") for x in pillars},
        "quarter": q.get("score"), "q_key": q.get("grade_key"), "q_tier": q.get("tier"),
        "q_headline": q.get("headline"),
        "pnl": p.get("score"), "pnl_key": p.get("grade_key"), "pnl_tier": p.get("tier"),
        **qn, **m,
        "explain": explain(r, q, p, qn, m, series),
        "sflags": static_flags(f, r, q, qn, coverage),
        "basis": f.get("basis"), "source_url": f.get("source_url"),
        "fetched_at": f.get("fetched_at"),
        "fetch_error": None,
        "v": ROW_VERSION,
    }


def overall_rating(row: dict, fr: dict) -> dict:
    """The blended rating, or Insufficient Data with the reasons written out."""
    reasons: list[str] = []
    if row.get("fund") is None:
        if row.get("fetch_error"):
            reasons.append(f"screener.in: {row['fetch_error']}")
        elif not row.get("fetched_at"):
            reasons.append("not read from screener.in yet; queued")
        else:
            reasons.append("screener.in published none of the inputs the seven pillars need")
    else:
        n, applicable = row.get("pillars_n") or 0, row.get("pillars_applicable") or len(PILLARS)
        cov = row.get("coverage")
        if n < MIN_PILLARS:
            reasons.append(f"only {n} of {applicable} pillars had data")
        elif cov is not None and cov < MIN_APPLICABLE_COVERAGE:
            reasons.append(f"only {cov * 100:.0f}% of the applicable pillar weight had data")
    if fr.get("state") == "outdated" and (fr.get("behind") or 0) >= OVERDUE_INSUFFICIENT:
        reasons.append(f"its latest filed quarter, {row.get('qlabel')}, is {fr['behind']} "
                       "quarters past the filing deadline")
    if reasons:
        return {"overall": None, "ovr_key": INSUFFICIENT_KEY, "ovr_tier": INSUFFICIENT_LABEL,
                "ovr_status": "insufficient", "ovr_reasons": reasons, "ovr_components": [],
                "ovr_formula": None}

    comps = []
    for key, field in (("fundamentals", "fund"), ("quarter", "quarter"), ("pnl", "pnl")):
        s = row.get(field)
        if s is not None:
            comps.append({"key": key, "label": OVERALL_LABELS[key], "score": s,
                          "weight": OVERALL_WEIGHTS[key]})
    live = sum(c["weight"] for c in comps)
    raw = sum(c["score"] * c["weight"] for c in comps) / live
    for c in comps:
        c["eff"] = round(c["weight"] / live, 3)
    score = round(max(1.0, min(10.0, raw)), 1)
    g = grade(score, "company")
    formula = " + ".join(f"{c['eff'] * 100:.0f}% × {c['score']:.1f}" for c in comps) + f" = {score:.1f}"
    return {"overall": score, "ovr_key": g["grade_key"], "ovr_tier": g["tier"],
            "ovr_status": "rated", "ovr_reasons": [], "ovr_components": comps,
            "ovr_formula": formula}


def time_fields(row: dict, today: date) -> dict:
    """What depends on today's date: freshness, pending refresh, flags and the overall."""
    qend = as_date(row.get("qend"))
    fr = freshness(qend, today)
    meetings = sorted({d for d in (as_date(x) for x in (row.get("meetings") or [])) if d})
    pr = pending_refresh(qend, meetings, today)

    tflags: list[dict] = []
    if row.get("fetch_error"):
        tflags.append({"k": "error", "lvl": "bad", "t": f"screener.in: {row['fetch_error']}"})
    if pr["pending"]:
        pend = pr["pending"]
        when = "today" if pend["meeting"] == today else f"on {fmt_day(pend['meeting'])}"
        tflags.append({"k": "pending", "lvl": "warn",
                       "t": f"Results board meeting {when}: the {qlabel(pend['expected'])} "
                            "figures are not in this rating yet, so a refresh is queued"})
    if fr["state"] == "outdated":
        req = fr["required"]
        tflags.append({"k": "outdated",
                       "lvl": "bad" if fr["behind"] >= OVERDUE_INSUFFICIENT else "warn",
                       "t": f"Latest filed quarter is {row.get('qlabel')}; {qlabel(req)} results "
                            f"were due by {fmt_day(filing_deadline(req))}"})
    elif fr["state"] == "due" and not pr["pending"]:
        t = f"{qlabel(fr['next_q'])} results due by {fmt_day(fr['next_due'])}"
        if pr["next_meeting"]:
            t += f"; board meeting on {fmt_day(pr['next_meeting'])}"
        tflags.append({"k": "due", "lvl": "info", "t": t})
    elif fr["state"] == "unknown" and row.get("fund") is not None:
        tflags.append({"k": "noquarters", "lvl": "warn",
                       "t": "No quarterly results on screener.in; the latest quarter cannot be judged"})
    fetched = as_date(row.get("fetched_at"))
    if fetched and (today - fetched).days > STALE_FETCH_DAYS:
        tflags.append({"k": "stale", "lvl": "info",
                       "t": f"Fundamentals last read from screener.in {(today - fetched).days} days ago"})

    return {
        "freshness": fr["state"], "behind": fr["behind"],
        "next_q": qlabel(fr["next_q"]), "next_due": iso(fr["next_due"]),
        "last_meeting": iso(pr["last_meeting"]), "next_meeting": iso(pr["next_meeting"]),
        "pending": bool(pr["pending"]),
        "pending_key": pr["pending"]["key"] if pr["pending"] else None,
        "tflags": tflags,
        **overall_rating(row, fr),
        "t_day": today.isoformat(),
    }


def refresh_reason(row: dict, now: datetime) -> tuple[int, str] | None:
    """Why this row should be read from screener.in again now, as (priority, reason).

    Lower priority numbers go first. Returns None when the row is current enough.
    """
    if not row.get("listed", True):
        return None
    now = now.astimezone(IST)
    today = now.date()
    ref = row.get("refresh") or {}
    last_try = aware(ref.get("last_try"))
    hours = (now - last_try).total_seconds() / 3600 if last_try else None
    fetched = aware(row.get("fetched_at"))

    if row.get("pending") and row.get("pending_key"):
        meeting = as_date(row.get("last_meeting"))
        if not (meeting == today and now.hour < EVENING_HOUR_IST):
            attempts = ref.get("attempts", 0) if ref.get("key") == row["pending_key"] else 0
            if attempts < len(PENDING_BACKOFF_H) and (hours is None or hours >= PENDING_BACKOFF_H[attempts]):
                return 1, "results"
    if fetched is None:
        if row.get("fetch_error"):
            return (5, "retry") if (hours is None or hours >= 24 * ERROR_RETRY_DAYS) else None
        return (2, "new") if (hours is None or hours >= 6) else None
    if row.get("fetch_error") and (hours is None or hours >= 24 * ERROR_RETRY_DAYS):
        return 5, "retry"
    age_days = (now - fetched).total_seconds() / 86400
    if (row.get("freshness") == "outdated" and age_days >= OVERDUE_RECHECK_DAYS
            and (hours is None or hours >= 24 * OVERDUE_RECHECK_DAYS)):
        return 3, "overdue"
    if age_days >= STALE_REFETCH_DAYS:
        return 4, "stale"
    return None


# ── price returns ────────────────────────────────────────────────────────────────

HORIZONS = (("r3m", 3, "3M"), ("r6m", 6, "6M"), ("r1y", 12, "1Y"), ("r2y", 24, "2Y"))

_BONUS = re.compile(r"\bbonus\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_SPLIT = re.compile(r"(?:split|sub[\s-]*division)\b.*?from\s*(?:rs|re)\.?\s*([\d.]+)"
                    r".*?to\s*(?:rs|re)\.?\s*([\d.]+)", re.I)
_CONSOL = re.compile(r"consolidat\w*\b.*?from\s*(?:rs|re)\.?\s*([\d.]+)"
                     r".*?to\s*(?:rs|re)\.?\s*([\d.]+)", re.I)


def months_back(d: date, months: int) -> date:
    y, m0 = divmod(d.year * 12 + (d.month - 1) - months, 12)
    m = m0 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def parse_action(subject: str) -> dict | None:
    """A corporate action's effect on the price series, or None when it has none.

    factor: multiply closes BEFORE the ex-date by this to put them on today's share
    count. A 1:1 bonus is 0.5, a split from Rs 10 to Re 1 is 0.1, and a consolidation
    from Re 1 to Rs 10 is 10.
    unadjusted: actions that move the price in a way no share-count factor describes.
    """
    s = " ".join(str(subject or "").split())
    low = s.lower()
    factor, adjusted, unadjusted = 1.0, [], []
    for a, b in _BONUS.findall(s):
        a, b = float(a), float(b)
        if a > 0 and b > 0:
            factor *= b / (a + b)
            adjusted.append(f"bonus {a:g}:{b:g}")
    for old, new in _SPLIT.findall(s):
        old, new = num(old.rstrip(".")), num(new.rstrip("."))
        if old and new:
            factor *= new / old
            adjusted.append(f"split ₹{old:g}→₹{new:g}")
    for old, new in _CONSOL.findall(s):
        old, new = num(old.rstrip(".")), num(new.rstrip("."))
        if old and new:
            factor *= new / old
            adjusted.append(f"consolidation ₹{old:g}→₹{new:g}")
    if re.search(r"\brights?\b", low):
        unadjusted.append("rights issue")
    if "demerger" in low or "spin off" in low or "spin-off" in low:
        unadjusted.append("demerger")
    if "capital reduction" in low or "reduction of capital" in low:
        unadjusted.append("capital reduction")
    if re.search(r"ncrps|preference share", low):
        unadjusted.append("bonus preference shares")
    if not adjusted and not unadjusted:
        return None
    return {"factor": factor if adjusted else None, "adjusted": adjusted, "unadjusted": unadjusted}


def compute_returns(latest: tuple[date, float] | None,
                    anchors: dict[str, tuple[date | None, float | None]],
                    actions: list[dict], listed_on: date | None = None) -> dict:
    """3M / 6M / 1Y / 2Y price returns for one stock, with what was adjusted and what was not.

    `anchors` maps a horizon key to (anchor trading date, close on it or None).
    `actions` holds {"ex": date, "factor", "adjusted", "unadjusted"} dicts.
    """
    out = {k: None for k, _, _ in HORIZONS}
    detail: dict[str, dict] = {}
    notes: list[str] = []
    if not latest or not latest[1] or latest[1] <= 0:
        return {**out, "ret_close": None, "ret_detail": {},
                "ret_notes": ["no close in the last two sessions"]}
    ld, lc = latest
    unadj_by: dict[str, list[str]] = {}
    for key, _, label in HORIZONS:
        ad, ac = anchors.get(key, (None, None))
        if ad is None:
            detail[key] = {"date": None, "reason": "no bhavcopy found for that date"}
            continue
        if ac is None or ac <= 0:
            if listed_on and listed_on > ad:
                reason = f"listed {fmt_day(listed_on)}, after {fmt_day(ad)}"
            else:
                reason = f"no traded price on or just after {fmt_day(ad)}"
            detail[key] = {"date": ad.isoformat(), "reason": reason}
            continue
        factor, adj, unadj = 1.0, [], []
        for a in actions:
            ex = a.get("ex")
            if ex is None or not (ad < ex <= ld):
                continue
            if a.get("factor"):
                factor *= a["factor"]
                adj += [f"{x} (ex {fmt_day(ex)})" for x in a.get("adjusted") or []]
            unadj += [f"{x} (ex {fmt_day(ex)})" for x in a.get("unadjusted") or []]
        ret = (lc / (ac * factor) - 1) * 100
        out[key] = round(ret, 1)
        detail[key] = {"date": ad.isoformat(), "close": ac,
                       "factor": round(factor, 6) if factor != 1.0 else None,
                       "adjusted": adj, "unadjusted": unadj}
        # No "too big to be true" warning here: INDOTHAI (-92% in a year) and GSLSU (-82%)
        # looked like missed splits in testing and were checked session by session. Both
        # were real collapses. The screener.in comparison below is the check that holds up.
        for u in unadj:
            unadj_by.setdefault(u, []).append(label)
    for action, labels in unadj_by.items():
        notes.append(f"{'/'.join(labels)} not adjusted for the {action}")
    return {**out, "ret_close": lc, "ret_detail": detail, "ret_notes": notes}


def screener_check(row: dict, as_of: date | None) -> str | None:
    """Our 1Y return against screener.in's own 1-year price CAGR, when both are recent.

    screener's figure is as of the day the page was read, so the two are only compared
    when that read is within four days of the close the return is measured to.
    """
    ours, theirs = row.get("r1y"), row.get("screener_1y")
    fetched = as_date(row.get("fetched_at"))
    if ours is None or theirs is None or not fetched or not as_of:
        return None
    if abs((as_of - fetched).days) > 4:
        return None
    if abs(ours - theirs) > max(15.0, 0.25 * abs(theirs)):
        return (f"1Y return {ours:+.1f}% differs from screener.in's 1-year figure "
                f"({theirs:+.0f}%); a corporate action may be missing from NSE's feed")
    return None


def quarter_band(score: float | None) -> str:
    """The Quarter filter's bands: the nine tiers, grouped in pairs a person can pick."""
    if score is None:
        return "unrated"
    if score >= 7.8:
        return "strong"
    if score >= 6.2:
        return "good"
    if score >= 4.6:
        return "average"
    return "weak"


METHODOLOGY = {
    "overall_weights": OVERALL_WEIGHTS,
    "min_pillars": MIN_PILLARS,
    "min_applicable_coverage": MIN_APPLICABLE_COVERAGE,
    "overdue_insufficient": OVERDUE_INSUFFICIENT,
    "rules": [
        "Fundamentals, latest quarter and P&L record are the Rate tab's own three scores, "
        "computed by the same code from the same screener.in page.",
        "Overall = 70% fundamentals + 15% latest quarter + 15% P&L record. A grade with no "
        "data is dropped and its weight shared over the others, the module's rule for a "
        "missing pillar.",
        f"Insufficient Data: no fundamentals score, fewer than {MIN_PILLARS} applicable "
        f"pillars or under {MIN_APPLICABLE_COVERAGE:.0%} of their weight, or a latest "
        f"quarter {OVERDUE_INSUFFICIENT}+ quarters past its filing deadline. Banks and "
        "NBFCs have five applicable pillars, everyone else seven.",
        f"Freshness follows SEBI LODR Reg 33: results within {RESULT_DAYS} days of a "
        f"quarter's end ({ANNUAL_RESULT_DAYS} for the March quarter), plus a {GRACE_DAYS}-day "
        "grace before a quarter counts as overdue.",
        "A results board meeting on NSE dated after the rating's latest quarter queues the "
        "stock for a fresh screener.in read. Same-day meetings are read after 20:00 IST, "
        "and each event is retried for about a week if screener.in has not caught up.",
        "Returns are price returns from NSE's end-of-day bhavcopy. Bonus issues, splits and "
        "consolidations from NSE's corporate-actions feed are adjusted for. Rights issues "
        "and demergers are named on the return, not adjusted. Dividends are excluded.",
        "QoQ growth is shown but never scored, because most Indian businesses are seasonal. "
        "Growth off a loss or a zero base is reported as not meaningful.",
    ],
}
