"""Verify the NSE Stock Ratings rules (app/services/nse_ratings_logic.py).

No Mongo and no network: every rule is a pure function, and the fixtures below are taken
from NSE's feeds and from screener.in pages as they read on 10 Nov 2026.

Run:  python backend/tests/fundamentals/verify_nse_ratings.py

What this pins down, because each one was easy to get wrong:
  * The filing calendar: a quarter is "due" until its SEBI deadline plus grace, not from
    the day it ends; the March quarter gets 60 days, the others 45.
  * Corporate actions: "Bonus a:b" means a new shares for every b held, so 1:1 halves
    the price; a split from Rs 10 to Re 1 is a factor of 0.1; rights and demergers are
    named, never guessed.
  * The overall: a missing grade is dropped and its weight shared, never scored as zero;
    and Insufficient Data replaces the number rather than sitting next to it.
"""

import math
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import nse_ratings_logic as L  # noqa: E402

failures: list[str] = []


def check(name: str, got, want) -> None:
    ok = (abs(got - want) < 1e-6) if isinstance(want, float) and isinstance(got, float) else got == want
    if not ok:
        failures.append(f"{name}: got {got!r}, want {want!r}")


d = date

# ── the filing calendar ──────────────────────────────────────────────────────────
check("prev qe", L.prev_quarter_end(d(2026, 11, 10)), d(2026, 9, 30))
check("prev qe on a quarter end", L.prev_quarter_end(d(2026, 9, 30)), d(2026, 6, 30))
check("prev qe in January", L.prev_quarter_end(d(2026, 1, 5)), d(2025, 12, 31))
check("deadline Q2", L.filing_deadline(d(2026, 9, 30)), d(2026, 11, 14))
check("deadline March", L.filing_deadline(d(2026, 3, 31)), d(2026, 5, 30))
check("required 10 Nov", L.required_quarter(d(2026, 11, 10)), d(2026, 6, 30))
check("required on deadline+grace", L.required_quarter(d(2026, 11, 21)), d(2026, 6, 30))
check("required after grace", L.required_quarter(d(2026, 11, 22)), d(2026, 9, 30))
check("required 1 Jun", L.required_quarter(d(2026, 6, 1)), d(2025, 12, 31))
check("shift back across a year", L.shift_quarter(d(2026, 3, 31), -1), d(2025, 12, 31))
check("quarters between", L.quarters_between(d(2025, 12, 31), d(2026, 6, 30)), 2)
check("quarter label", L.quarter_end("Sep 2026"), d(2026, 9, 30))
check("TTM is not a quarter", L.quarter_end("TTM"), None)

t = d(2026, 11, 10)
check("fresh current", L.freshness(d(2026, 9, 30), t)["state"], "current")
fr = L.freshness(d(2026, 6, 30), t)
check("fresh due", (fr["state"], fr["next_due"]), ("due", d(2026, 11, 14)))
check("fresh outdated 1", (L.freshness(d(2026, 3, 31), t)["state"], L.freshness(d(2026, 3, 31), t)["behind"]),
      ("outdated", 1))
check("fresh outdated 2", L.freshness(d(2025, 12, 31), t)["behind"], 2)
check("fresh unknown", L.freshness(None, t)["state"], "unknown")

# ── results meetings ─────────────────────────────────────────────────────────────
pr = L.pending_refresh(d(2026, 6, 30), [d(2026, 8, 10), d(2026, 11, 5)], t)
check("pending after a Q2 meeting", (bool(pr["pending"]), pr["pending"]["expected"]), (True, d(2026, 9, 30)))
check("pending key", pr["pending"]["key"], "2026-09-30:2026-11-05")
check("no pending once the quarter is in", L.pending_refresh(d(2026, 9, 30), [d(2026, 11, 5)], t)["pending"], None)
pr = L.pending_refresh(d(2026, 6, 30), [d(2026, 8, 10), d(2026, 11, 13)], t)
check("future meeting is next, not pending", (pr["pending"], pr["next_meeting"]), (None, d(2026, 11, 13)))

# ── corporate actions (subjects exactly as NSE prints them) ──────────────────────
check("bonus 1:1", L.parse_action("Bonus 1:1")["factor"], 0.5)
check("bonus 17:25", L.parse_action("Bonus 17:25")["factor"], 25 / 42)
check("bonus 2:1", L.parse_action("Bonus 2:1")["factor"], 1 / 3)
check("split 10 to 1", L.parse_action(
    "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share")["factor"], 0.1)
check("split 5 to 2", L.parse_action(
    "Face Value Split (Sub-Division) - From Rs 5/- Per Share To Rs 2/- Per Share")["factor"], 0.4)
check("consolidation", L.parse_action(
    "Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")["factor"], 10.0)
a = L.parse_action("Rights 1:4 @ Premium Rs 65/-")
check("rights is named, not adjusted", (a["factor"], a["unadjusted"]), (None, ["rights issue"]))
a = L.parse_action("Scheme Of Arrangement - Bonus Ncrps 4:1")
check("preference bonus", (a["factor"], a["unadjusted"]), (None, ["bonus preference shares"]))
check("demerger", L.parse_action("Demerger")["unadjusted"], ["demerger"])
for s in ("Dividend - Rs 5 Per Share", "Interim Dividend - Re 0.10 Per Share",
          "Annual General Meeting/Dividend - Rs  0.50 Per Share", "Buy Back", "Interest Payment"):
    check(f"no price effect: {s}", L.parse_action(s), None)

# ── returns ──────────────────────────────────────────────────────────────────────
check("3M back", L.months_back(d(2026, 11, 9), 3), d(2026, 8, 9))
check("3M back from 31 May", L.months_back(d(2026, 5, 31), 3), d(2026, 2, 28))
check("2Y back", L.months_back(d(2026, 11, 9), 24), d(2024, 11, 9))
bonus = [{"ex": d(2026, 3, 2), **L.parse_action("Bonus 1:1")}]
r = L.compute_returns((d(2026, 11, 9), 110.0),
                      {"r3m": (d(2026, 8, 7), 100.0), "r1y": (d(2025, 11, 7), 200.0),
                       "r6m": (d(2026, 5, 8), None), "r2y": (None, None)},
                      bonus, listed_on=d(2025, 6, 1))
check("bonus outside 3M window", r["r3m"], 10.0)
check("bonus inside 1Y window halves the base", r["r1y"], 10.0)
check("no anchor price", r["r6m"], None)
check("no anchor reason", r["ret_detail"]["r6m"]["reason"], "no traded price on or just after 8 May 2026")
r = L.compute_returns((d(2026, 11, 9), 50.0), {"r2y": (d(2024, 11, 8), None)}, [], listed_on=d(2025, 2, 1))
check("listed after the anchor", r["ret_detail"]["r2y"]["reason"], "listed 1 Feb 2025, after 8 Nov 2024")
rights = [{"ex": d(2026, 9, 1), **L.parse_action("Rights 1:4 @ Premium Rs 65/-")}]
r = L.compute_returns((d(2026, 11, 9), 90.0), {"r3m": (d(2026, 8, 7), 100.0), "r1y": (d(2025, 11, 7), 80.0)},
                      rights)
check("rights noted on the windows it sits in", r["ret_notes"], ["3M/1Y not adjusted for the rights issue (ex 1 Sep 2026)"])

# ── the latest quarter, validated like the card ──────────────────────────────────
page = {
    "quarters_periods": ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
    "quarters": {
        "Sales": [100.0, 110.0, 120.0, 115.0, 130.0],
        "Operating Profit": [10.0, 12.0, 14.0, 13.0, 16.0],
        "OPM %": [10.0, 11.0, 12.0, 11.0, 12.0],
        "Other Income": [1.0, 1.0, 1.0, 1.0, 30.0],
        "Profit before tax": [8.0, 10.0, 12.0, 11.0, 42.0],
        "Net Profit": [-2.0, 7.0, 9.0, 8.0, 31.0],
    },
}
qn = L.quarter_numbers(page)
check("latest label", (qn["qlabel"], qn["qend"]), ("Sep 2026", "2026-09-30"))
check("revenue yoy/qoq", (qn["rev_yoy"], qn["rev_qoq"]), (30.0, 13.0))
check("profit off a loss is not a percentage", qn["np_yoy"], None)
check("other income flagged", qn["np_flag"], "distorted")
check("note says why", "other income drives net profit in Sep 2026" in qn["np_note"]
      and "turned profitable" in qn["np_note"], True)

# ── the stock rating: six components ────────────────────────────────────────────
ps = {"returns": 6.0, "profitability": 8.0, "cash": 9.0, "ownership": 7.0, "growth": 8.0,
      "balance_sheet": 10.0, "valuation": 4.0}
base = {"fund": 7.8, "quarter": 10.0, "pnl": 7.0, "pillars_n": 7, "pillars_applicable": 7,
        "coverage": 1.0, "fetched_at": datetime(2026, 11, 10), "qlabel": "Sep 2026",
        "pillar_scores": ps, "val_rel_score": 2.0, "mom_score": 9.0, "mom_pct": 91.0, "r1y": 41.0,
        "rev_yoy": 28.3, "op_yoy": 88.4, "pe": 43.0, "pe_rel": 1.4}
cur = L.freshness(d(2026, 9, 30), t)
quality = round((6 * .22 + 8 * .14 + 9 * .12 + 7 * .08) / .56, 1)          # 7.3
parts = {"quality": quality, "growth": 7.5, "quarter": 10.0, "valuation": 3.0, "strength": 10.0, "momentum": 9.0}
check("components", L.rating_components(base), parts)
want = round(sum(parts[k] * w for k, w in L.RATING_WEIGHTS.items()), 1)
o = L.overall_rating(base, cur)
check("rating is the weighted six", (o["overall"], o["ovr_status"]), (want, "rated"))
check("weights sum to 1", round(sum(L.RATING_WEIGHTS.values()), 6), 1.0)
check("explanation names best (either of the two at 10.0) and worst",
      (o["ovr_explain"].startswith("Strongest: quarterly results 10.0 (Sep 2026: sales +28%, op. profit +88% YoY)")
       or o["ovr_explain"].startswith("Strongest: financial strength 10.0"))
      and "Weakest: valuation 3.0 (P/E 43, 1.4x the sector median)" in o["ovr_explain"], True)
o = L.overall_rating({**base, "mom_score": None, "val_rel_score": None}, cur)
check("missing momentum is dropped, valuation falls back to the pillar",
      (o["rating_parts"]["momentum"], o["rating_parts"]["valuation"], "price momentum" in o["ovr_explain"]),
      (None, 4.0, True))
lender = {**base, "pillar_scores": {**ps, "balance_sheet": None, "cash": None}}
check("lender: strength not scored, still rated", (L.overall_rating(lender, cur)["rating_parts"]["strength"],
                                                    L.overall_rating(lender, cur)["ovr_status"]), (None, "rated"))
check("insufficient: no quality pillar",
      L.overall_rating({**base, "pillar_scores": {"growth": 8.0, "valuation": 4.0, "balance_sheet": 9.0}}, cur)["ovr_reasons"][0]
      .startswith("none of the quality pillars"), True)
thin = {**base, "pillar_scores": {"returns": 6.0}, "quarter": None, "pnl": None, "val_rel_score": None, "mom_score": None}
check("insufficient: too few components", L.overall_rating(thin, cur)["ovr_reasons"], ["only 1 of the 6 rating components had data"])
check("insufficient: no fundamentals",
      L.overall_rating({**base, "fund": None}, cur)["ovr_key"], L.INSUFFICIENT_KEY)
check("insufficient: three pillars",
      L.overall_rating({**base, "pillars_n": 3}, cur)["ovr_reasons"], ["only 3 of 7 pillars had data"])
check("insufficient: low coverage",
      L.overall_rating({**base, "coverage": 0.55}, cur)["ovr_status"], "insufficient")
o = L.overall_rating({**base, "qlabel": "Dec 2025"}, L.freshness(d(2025, 12, 31), t))
check("insufficient: two quarters overdue", (o["overall"], o["ovr_reasons"]),
      (None, ["its latest filed quarter, Dec 2025, is 2 quarters past the filing deadline"]))
check("one quarter overdue keeps the rating",
      L.overall_rating(base, L.freshness(d(2026, 3, 31), t))["ovr_status"], "rated")
tf = L.time_fields({"meetings": []}, t)
check("never read", (tf["ovr_tier"], tf["ovr_reasons"]),
      ("Insufficient Data", ["not read from screener.in yet; queued"]))

# ── momentum score ───────────────────────────────────────────────────────────────
check("momentum blends percentiles", L.momentum_score(0.9, 0.8, 0.7), (8.3, 83.0))
check("young listing: scored on what it has", L.momentum_score(None, 0.5, None), (5.0, 50.0))
check("no 6M or 12M figure: not scored", L.momentum_score(None, None, 0.9), (None, None))

# ── forward estimates ────────────────────────────────────────────────────────────
cal = {"version": "test", "drift_log_per_session": 0.0004, "vol_floor": 0.004, "vol_cap": 0.10,
       "horizons": {"1m": {"sessions": 21, "ewma_weight": 0.5,
                           "z": {"0.05": -1.8, "0.1": -1.3, "0.5": 0.0, "0.9": 1.3, "0.95": 1.8}}},
       "validation": {"1m": {"by_liquidity": {"liquid": 0.80, "thin": 0.70}, "by_vol": {"1": 0.81},
                             "passed": True, "period": "Nov 2024 - Nov 2026"}}}
e = L.estimate(100.0, 0.0004, 0.0004, 250, 0.0, 0, None, "EQ", 1, 20.0, cal)
s1m = 0.02 * math.sqrt(21)
check("1m bear is the 10th percentile", e["1m"]["bear"], round(math.expm1(0.0084 - 1.3 * s1m) * 100, 2))
check("1m base is the drift", e["1m"]["base"], round(math.expm1(0.0084) * 100, 2))
check("target price follows the return", e["1m"]["bull_px"], round(100 * math.exp(0.0084 + 1.3 * s1m), 2))
check("downside is the 5th percentile", e["1m"]["down"], round(math.expm1(0.0084 - 1.8 * s1m) * 100, 2))
check("liquid, well-calibrated bucket -> high confidence", e["1m"]["conf"], "high")
check("horizon without calibration -> insufficient", e["1d"]["status"], "insufficient")
e = L.estimate(100.0, 0.0004, 0.0004, 250, 0.15, 0, None, "EQ", 1, 0.2, cal)
check("thin and patchy -> low confidence", e["1m"]["conf"], "low")
check("too little history", L.estimate(100.0, 0.0004, 0.0004, 50, 0.0, 0, None, "EQ", 1, 20.0, cal)["1m"]["reason"],
      "only 50 daily returns in the last year; 120 are needed")
check("BZ series", L.estimate(100.0, 0.0004, 0.0004, 250, 0.0, 0, None, "BZ", 1, 20.0, cal)["1m"]["status"], "insufficient")
check("stale price", L.estimate(100.0, 0.0004, 0.0004, 250, 0.0, 6, None, "EQ", 1, 20.0, cal)["1m"]["reason"],
      "no trade in the last 6 sessions")
check("a recent unadjustable action",
      L.estimate(100.0, 0.0004, 0.0004, 250, 0.0, 0, "a demerger (ex 1 Oct 2026)", "EQ", 1, 20.0, cal)["1m"]["status"],
      "insufficient")

# ── what the refresher picks up ──────────────────────────────────────────────────
noon = datetime(2026, 11, 10, 12, 0, tzinfo=L.IST)
evening = datetime(2026, 11, 10, 21, 0, tzinfo=L.IST)
row = {"listed": True, "fetched_at": datetime(2026, 9, 27), "pending": True,
       "pending_key": "2026-09-30:2026-11-10", "last_meeting": "2026-11-10", "freshness": "due"}
check("same-day meeting waits for the evening", L.refresh_reason(row, noon), None)
check("same-day meeting read in the evening", L.refresh_reason(row, evening), (1, "results"))
row2 = {**row, "last_meeting": "2026-11-05", "pending_key": "2026-09-30:2026-11-05"}
check("earlier meeting read now", L.refresh_reason(row2, noon), (1, "results"))
spent = {**row2, "refresh": {"key": row2["pending_key"], "attempts": 5,
                             "last_try": datetime(2026, 11, 9)}}
check("retries for one event are capped", L.refresh_reason(spent, noon), None)
backoff = {**row2, "refresh": {"key": row2["pending_key"], "attempts": 1,
                               "last_try": datetime(2026, 11, 10, 5, 0)}}
check("second try waits 12h", L.refresh_reason(backoff, noon), None)
check("never read", L.refresh_reason({"listed": True}, noon), (2, "new"))
check("stale", L.refresh_reason({"listed": True, "fetched_at": datetime(2026, 7, 1)}, noon), (4, "stale"))
check("overdue recheck", L.refresh_reason({"listed": True, "fetched_at": datetime(2026, 10, 20),
                                           "freshness": "outdated"}, noon), (3, "overdue"))
check("delisted is left alone", L.refresh_reason({"listed": False}, noon), None)

# ── a stale consolidated page swapped for standalone says so ─────────────────────
note = ("screener.in's consolidated quarterly results stop at Jun 2024, so the standalone "
        "figures, which run to Sep 2026, are used")
fl = L.static_flags({"basis": "standalone", "basis_note": note}, {"pillars": []},
                    {"rated": True}, {}, 1.0)
check("basis note becomes the standalone flag",
      [x["t"] for x in fl if x["k"] == "standalone"], ["S" + note[1:]])
fl = L.static_flags({"basis": "standalone"}, {"pillars": []}, {"rated": True}, {}, 1.0)
check("plain standalone keeps its own wording",
      [x["t"] for x in fl if x["k"] == "standalone"],
      ["Standalone figures: screener.in has no consolidated accounts for it"])

# ── an unpublished half-year balance-sheet column is skipped, not read as zero ───
from app.services.fundamental_rating import _p_balance_sheet  # noqa: E402

bs_page = {"sector": "Diversified", "profit_loss": {"Operating Profit": [300.0, 320.0], "Interest": [5.0, 6.0]},
           "balance_sheet": {"Equity Capital": [11.0, 11.0, 0.0], "Reserves": [1835.0, 1757.0, 0.0],
                             "Borrowings": [100.0, 170.0, 0.0]}}
got = _p_balance_sheet(bs_page)
check("zero half-year column skipped", (got[2]["net_worth"], got[2]["debt_to_equity"]), (1768.0, 0.1))
check("...and scored on the real column", got[0] >= 9, True)
populated = {**bs_page, "balance_sheet": {"Equity Capital": [11.0, 11.0], "Reserves": [1835.0, 1757.0],
                                          "Borrowings": [100.0, 170.0]}}
check("a populated page is unchanged", _p_balance_sheet(populated)[2], got[2])

# ── index slices ─────────────────────────────────────────────────────────────────
f = L.index_fields("niftymidcap150")
check("midcap composites", f["indices"], ["niftymidcap150", "nifty250", "nifty500", "niftytotalmarket"])
check("outside every index", (L.index_fields(None)["indices"], L.index_fields(None)["idx_rank"]),
      (["nserest"], 6))

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    for f_ in failures:
        print("  -", f_)
    sys.exit(1)
print("OK: NSE Stock Ratings rules verified")
