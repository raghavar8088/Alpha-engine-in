"""Offline checks of the NSE Stock Ratings Rank column (nse_ratings_logic.fundamental_score / rank_scores).

    python backend/tests/fundamentals/verify_fundamental_rank.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import nse_ratings_logic as L  # noqa: E402

FAILS = []


def check(ok: bool, msg: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


full = {"quality": 8.0, "growth": 6.0, "quarter": 7.0, "valuation": 5.0, "strength": 9.0, "momentum": 1.0}
want = (8 * .25 + 6 * .20 + 7 * .15 + 5 * .15 + 9 * .15) / .90
check(abs(L.fundamental_score(full) - want) < 1e-9, f"five parts at the rating's weights ({want:.3f}); momentum ignored")
check(L.fundamental_score({**full, "momentum": 10.0}) == L.fundamental_score(full), "momentum never moves the score")
no_q = {**full, "quarter": None}
want4 = (8 * .25 + 6 * .20 + 5 * .15 + 9 * .15) / .75
check(abs(L.fundamental_score(no_q) - want4) < 1e-9, "a missing part's weight is shared over the rest")
check(L.fundamental_score({**full, "quality": None}) is None, "no quality: not ranked")
check(L.fundamental_score({"quality": 8.0, "growth": 6.0, "valuation": 5.0}) is None, "3 of 5 parts: not ranked")
check(L.fundamental_score(None) is None and L.fundamental_score({}) is None, "no parts: not ranked")

r = L.rank_scores({"A": 8.0, "B": 9.0, "C": 8.0, "D": 7.0})
check([r[k]["frank"] for k in "BACD"] == [1, 2, 2, 4], "equal scores share a rank (1, 2, 2, 4)")
check(all(v["frank_of"] == 4 for v in r.values()), "every rank carries the ranked count")
check(r["A"]["fscore"] == 8.0 and isinstance(r["A"]["fscore"], float), "the score rides along, rounded")
check(L.rank_scores({}) == {}, "nothing to rank: empty")
check(L.METHODOLOGY.get("fund_rank", {}).get("record") and len(L.METHODOLOGY["fund_rank"]["record"]) == 5,
      "the method panel carries the definition and the five-year record")

print(f"\n{len(FAILS)} FAILED" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
