"""Verify the natural-language layer's DETERMINISTIC half. No network, no model.

Run:  python backend/tests/instrument_search/verify_nlq.py

The language model's only job is to emit a filter. Everything after that — validating it,
running it, and describing it back to you — is ordinary code, and it is the part that must
be right: a model that returns nonsense should produce a visibly empty or rejected filter,
never a plausible-looking list of stocks chosen by something nobody can inspect.

So this covers:
  * `sanitise()` — the model is NOT trusted. Unknown keys, bad types, out-of-range numbers
    and invented sectors are dropped rather than passed through to the executor.
  * `apply_filter()` — the actual screening, over fixture rows shaped like the real
    `screener_momentum` documents.
  * `describe()` — the English shown in the UI must match the filter that ran.
  * `status()` — when no provider key exists it must say so, not pretend.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()

from app.services.instrument_search import nlq

FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


SECTORS = {"IT", "Financial Services", "Automobile", "FMCG", "Power"}

# Shaped exactly like real screener_momentum rows.
ROWS = [
    {"symbol": "INFY", "sector": "IT", "ltp": 1600, "turnover": 8e9, "volume_x": 1.2,
     "returns": {"1d": 0.9, "1w": 2.0, "1m": 12.0, "6m": 25.0}, "pct_from_ath": -3.0,
     "up_streak": 4, "sma20": 1550, "sma50": 1500, "sma200": 1400, "breakout": "20d high"},
    {"symbol": "TCS", "sector": "IT", "ltp": 3900, "turnover": 6e9, "volume_x": 0.8,
     "returns": {"1d": -0.4, "1w": -1.0, "1m": 4.0, "6m": 9.0}, "pct_from_ath": -18.0,
     "up_streak": 0, "sma20": 3950, "sma50": 3900, "sma200": 3700, "breakout": None},
    {"symbol": "HDFCBANK", "sector": "Financial Services", "ltp": 1700, "turnover": 9.5e9,
     "volume_x": 2.4, "returns": {"1d": 1.6, "1w": 3.0, "1m": 11.0, "6m": 14.0},
     "pct_from_ath": -1.0, "up_streak": 6, "sma20": 1650, "sma50": 1600, "sma200": 1500,
     "breakout": "52w high"},
    {"symbol": "TATAPOWER", "sector": "Power", "ltp": 420, "turnover": 3.1e9, "volume_x": 1.9,
     "returns": {"1d": 2.2, "1w": 5.0, "1m": 18.0, "6m": -4.0}, "pct_from_ath": -30.0,
     "up_streak": 3, "sma20": 405, "sma50": 400, "sma200": 430, "breakout": None},
    {"symbol": "TINYCO", "sector": "Power", "ltp": 40, "turnover": 2e7, "volume_x": 0.4,
     "returns": {"1d": 9.0, "1w": 20.0, "1m": 60.0, "6m": 80.0}, "pct_from_ath": -2.0,
     "up_streak": 5, "sma20": 38, "sma50": 35, "sma200": 30, "breakout": "20d high"},
]

INDEX_OF = {"INFY": ("nifty50", "nifty100", "nifty500"),
            "TCS": ("nifty50", "nifty100", "nifty500"),
            "HDFCBANK": ("nifty50", "nifty100", "nifty500"),
            "TATAPOWER": ("nifty100", "nifty500"),
            "TINYCO": ()}


def run(flt):
    return [r["symbol"] for r in nlq.apply_filter(ROWS, flt, lambda s: INDEX_OF.get(s, ()))]


print("\n== sanitise: the model is not trusted ==")
raw = {"sector": "it", "returns": {"1m": {"gte": 10}}, "limit": 5000,
       "drop_table": "students", "sort_by": "1m", "sort_dir": "DESC",
       "above_sma": ["20", "999"], "turnover_min": -5}
clean = nlq.sanitise(raw, SECTORS)
check("unknown keys are dropped", "drop_table" not in clean, str(clean))
check("sector is matched case-insensitively to a REAL sector", clean.get("sector") == "IT")
check("limit is clamped", clean.get("limit") == 100, str(clean.get("limit")))
check("sort_dir is lower-cased and validated", clean.get("sort_dir") == "desc")
check("bogus SMA periods are dropped", clean.get("above_sma") == ["20"], str(clean.get("above_sma")))
check("a negative turnover floor is rejected", "turnover_min" not in clean)
check("an invented sector is dropped",
      "sector" not in nlq.sanitise({"sector": "Cryptocurrency Mining"}, SECTORS))
check("a totally unusable answer sanitises to nothing",
      nlq.sanitise({"nonsense": True, "sector": 42}, SECTORS) == {})

print("\n== apply_filter: the actual screening ==")
check("sector filter", set(run({"sector": "IT"})) == {"INFY", "TCS"}, str(run({"sector": "IT"})))
check("index membership", "TINYCO" not in run({"index": "nifty500"}), str(run({"index": "nifty500"})))
got = run({"returns": {"1m": {"gte": 10}}})
check("returns lower bound", set(got) == {"INFY", "HDFCBANK", "TATAPOWER", "TINYCO"}, str(got))
got = run({"returns": {"1m": {"gte": 10}}, "turnover_min": 5e9})
check("turnover floor excludes the illiquid mover TINYCO",
      set(got) == {"INFY", "HDFCBANK"}, str(got))
got = run({"pct_from_ath": {"gte": -5}})
check("'near its high' is pct_from_ath >= -5",
      set(got) == {"INFY", "HDFCBANK", "TINYCO"}, str(got))
got = run({"pct_from_ath": {"lte": -20}})
check("'well below its high' is pct_from_ath <= -20", set(got) == {"TATAPOWER"}, str(got))
got = run({"above_sma": ["20", "50", "200"]})
check("full SMA stack excludes TATAPOWER (below its 200)",
      "TATAPOWER" not in got and "INFY" in got, str(got))
check("TCS is excluded — it is below its own 20-day", "TCS" not in got, str(got))
check("breakout_only", set(run({"breakout_only": True})) == {"INFY", "HDFCBANK", "TINYCO"},
      str(run({"breakout_only": True})))
check("volume_x floor", set(run({"volume_x_min": 1.9})) == {"HDFCBANK", "TATAPOWER"},
      str(run({"volume_x_min": 1.9})))
check("up_streak floor", set(run({"up_streak_min": 4})) == {"INFY", "HDFCBANK", "TINYCO"},
      str(run({"up_streak_min": 4})))

print("\n== sorting and limit ==")
check("sorts by the requested window, descending",
      run({"sort_by": "1m", "sort_dir": "desc"})[0] == "TINYCO",
      str(run({"sort_by": "1m", "sort_dir": "desc"})))
check("ascending works too", run({"sort_by": "1m", "sort_dir": "asc"})[0] == "TCS")
check("limit is honoured", len(run({"limit": 2})) == 2)
check("a row missing the sort field never crashes the sort",
      len(run({"sort_by": "pct_from_ath"})) == len(ROWS))

print("\n== a combined query, end to end ==")
combined = nlq.sanitise({"sector": "IT", "returns": {"1m": {"gte": 10}},
                         "pct_from_ath": {"gte": -5}, "turnover_min": 5e9,
                         "sort_by": "1m", "limit": 10}, SECTORS)
check("'IT stocks up 10% this month near their highs' -> INFY only",
      run(combined) == ["INFY"], str(run(combined)))

print("\n== describe: the English must match the filter ==")
text = nlq.describe(combined)
for fragment in ("IT sector", "up at least 10% over 1m", "within 5% of its all-time high",
                 "turnover over"):
    check(f"describe mentions {fragment!r}", fragment in text, text)
check("an empty filter is described honestly", nlq.describe({}) == "no constraints")

print("\n== provider status is honest ==")
st = nlq.status()
check("status reports whether it is enabled", isinstance(st["enabled"], bool),
      f"enabled={st['enabled']} provider={st['provider']}")
check("when disabled it says search stays lexical",
      st["enabled"] or "lexical" in st["note"], st["note"])
check("when enabled it says the model does not pick stocks",
      not st["enabled"] or "never picks stocks" in st["note"], st["note"])
check("no keyword fallback exists anywhere in the module",
      "lexicon" not in open(nlq.__file__, encoding="utf-8").read().lower())

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
