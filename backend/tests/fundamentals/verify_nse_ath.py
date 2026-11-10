"""Verify the NSE Stock Ratings all-time-high fields (nse_market.ath_fields and the market computation).

No Mongo and no network: a synthetic price store is written to a temporary folder and the real computation reads it.

Run:  python backend/tests/fundamentals/verify_nse_ath.py

What this pins down:
  * The high is the higher of the full-history high (stock_highs) and the store's highest adjusted close, so a
    stored high that was never raised cannot hide a newer peak.
  * With no stored high, only a stock that listed inside the store has a known high (its whole life is in the
    store). Anything else is unknown, never "at its high".
  * A bonus inside the store is applied before the store's highest close is taken, so a pre-bonus close is not
    mistaken for a peak.
  * "New all-time high" means the latest close is above every earlier high, or stock_highs moved to the latest
    session. A stock that did not trade in the latest session is never new.
"""

import gzip
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="nse_ath_")
os.environ["NSE_RATINGS_DATA_DIR"] = TMP
_REPO = Path(__file__).resolve().parents[3]
for _p in (_REPO / "shared", _REPO / "backend"):        # the repo's own packages before any installed copy
    sys.path.insert(0, str(_p))

from app.services import nse_market as M  # noqa: E402
from app.services import nse_ratings_logic as L  # noqa: E402

failures: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  got {got!r}, want {want!r}"))
    if not ok:
        failures.append(name)


D0 = date(2026, 1, 1)
T = "2026-11-09"

# ── ath_fields by hand ────────────────────────────────────────────────────────────────
f = M.ath_fields(90.0, True, 95.0, "2026-06-01", 95.0, 120.0, "2024-03-05", None, D0, T)
check("stored high above the store: measured against it", (f["ath"], f["ath_date"], f["from_ath"], f["ath_basis"]),
      (120.0, "2024-03-05", -25.0, "history"))
f = M.ath_fields(150.0, True, 150.0, T, 140.0, 120.0, "2024-03-05", None, D0, T)
check("store above a stale stored high: today's close is the high", (f["ath"], f["ath_date"], f["from_ath"], f["ath_new"]),
      (150.0, T, 0.0, True))
f = M.ath_fields(118.0, True, 118.0, T, 110.0, 120.0, "2024-03-05", None, D0, T)
check("a store high below the stored intraday peak is not new", (f["ath"], f["ath_new"]), (120.0, False))
f = M.ath_fields(119.0, True, 119.0, T, 110.0, 120.0, T, None, D0, T)
check("stock_highs moved to today: new", f["ath_new"], True)
f = M.ath_fields(150.0, False, 150.0, "2026-11-06", 150.0, 120.0, "2024-03-05", None, D0, T)
check("no trade in the latest session: never new", f["ath_new"], False)
f = M.ath_fields(80.0, True, 100.0, "2026-05-01", 100.0, None, None, date(2026, 3, 2), D0, T)
check("no stored high, listed inside the store: known since listing", (f["ath"], f["from_ath"], f["ath_basis"]),
      (100.0, -20.0, "listing"))
f = M.ath_fields(80.0, True, 100.0, "2026-05-01", 100.0, None, None, date(2015, 3, 2), D0, T)
check("no stored high, listed before the store: unknown", (f["ath"], f["from_ath"], f["ath_basis"]), (None, None, None))
f = M.ath_fields(80.0, True, 100.0, "2026-05-01", 100.0, None, None, None, D0, T)
check("no stored high, listing date unknown: unknown", f["from_ath"], None)
f = M.ath_fields(None, False, 100.0, "2026-05-01", 100.0, 120.0, "2024-03-05", None, D0, T)
check("no current price: unknown", f["from_ath"], None)

# ── the market computation on a synthetic store ────────────────────────────────────────
days = []
d = date(2026, 6, 1)
while len(days) < 40:
    if d.weekday() < 5:
        days.append(d)
    d += timedelta(days=1)


def write(kind: str, day: date, obj: dict) -> None:
    path = Path(TMP) / kind / f"{day.isoformat()}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh)


bonus_ex = days[20]
for t, day in enumerate(days):
    prices = {
        "RISER": 100.0 + t,                                   # climbs every day: today is its all-time high
        "FALLER": 200.0 - t,                                  # high on day 0 in the store, stored high far above
        # 1:1 bonus at days[20]: raw closes 300 -> 160 (adjusted: 150 -> 160); the adjusted peak is today
        "BONUS": (300.0 if t < 20 else 160.0) + (0 if t < 20 else t - 20),
        "NEWLIST": 50.0 + (5 if t == 30 else 0) if t >= 25 else None,   # lists on days[25]; peak on days[30]
        "OLDNOHI": 70.0,                                      # listed long ago, no stored high: unknown
    }
    write("prices", day, {s: [c, c, 1000, 10.0, 10, 50.0] for s, c in prices.items() if c is not None})
    write("indices", day, {nm: 1000.0 + t for nm in M.INDEX_NAMES})

actions = {"BONUS": [{"ex": bonus_ex, "factor": 0.5, "adjusted": ["bonus 1:1"], "unadjusted": []}]}
meta_rows = {s: {"sector": "Test", "series": "EQ", "listed_on": None}
             for s in ("RISER", "FALLER", "BONUS", "OLDNOHI")}
meta_rows["NEWLIST"] = {"sector": "Test", "series": "EQ", "listed_on": days[25].isoformat()}
highs = {"RISER": {"all_time_high": 120.0, "all_time_high_date": "2025-01-10"},
         "FALLER": {"all_time_high": 400.0, "all_time_high_date": "2024-08-01"},
         "BONUS": {"all_time_high": 170.0, "all_time_high_date": "2025-12-01"}}
res, header = M.compute(days, {}, actions, meta_rows, {}, L.calibration(), highs)
last = days[-1].isoformat()

r = res["RISER"]
check("RISER: today's close beats the stored high", (r["ath"], r["from_ath"], r["ath_new"], r["ath_date"]),
      (139.0, 0.0, True, last))
r = res["FALLER"]
check("FALLER: measured against the stored 400", (r["ath"], r["from_ath"], r["ath_new"], r["ath_basis"]),
      (400.0, round((161 / 400 - 1) * 100, 2), False, "history"))
r = res["BONUS"]
check("BONUS: the raw pre-bonus 300 counts as 150, so the high is today's 179, not 300", (r["ath"], r["ath_date"]),
      (179.0, last))
check("BONUS: its close of 179 is above the stored 170, so new", (r["from_ath"], r["ath_new"]), (0.0, True))
r = res["NEWLIST"]
check("NEWLIST: listed inside the store, peak 55 on its 6th day", (r["ath"], r["from_ath"], r["ath_basis"]),
      (55.0, round((50 / 55 - 1) * 100, 2), "listing"))
r = res["OLDNOHI"]
check("OLDNOHI: no stored high and an old listing: unknown", (r["ath"], r["from_ath"], r["ath_new"]), (None, None, None))
check("from_ath is never above zero", all((v["from_ath"] or 0) <= 0 for v in res.values()), True)

print(f"\n{'ALL PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
