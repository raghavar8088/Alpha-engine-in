"""Phase 8, pre-registered test P8_event_proxy: do the six rules' signals do worse right after
the stock files a company announcement? Window, keyword list and decision from
prereg/P8_event_proxy.json; announcements from fetch_announcements.py.

    D:/intraday_ai_data/venv/Scripts/python.exe event_proxy.py
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from prereg import load  # noqa: E402
from stubpkg import DATA  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
RULE = load("P8_event_proxy")
KEYWORDS = [k.strip() for k in RULE["affected"]["H8_material"].split("one of:")[1].split(",")]
DEV_FROM, HOLDOUT_FROM, END = "2025-11-04", "2026-05-04", "2026-11-03"


def load_announcements() -> dict[str, tuple[list[int], list[bool]]]:
    by: dict[str, list[tuple[int, bool]]] = defaultdict(list)
    for p in sorted((DATA / "intraday" / "nse_events" / "ann").glob("*.json.gz")):
        for r in json.load(gzip.open(p, "rt", encoding="utf-8"))["rows"]:
            if not r.get("symbol") or not r.get("t"):
                continue
            t = int(datetime.fromisoformat(r["t"]).timestamp())
            desc = (r.get("desc") or "").lower()
            by[r["symbol"]].append((t, any(k in desc for k in KEYWORDS)))
    out = {}
    for s, lst in by.items():
        lst.sort()
        out[s] = ([t for t, _m in lst], [m for _t, m in lst])
    return out


def daily_diff(rows: list[dict], key: str) -> tuple[float, float, int]:
    by = defaultdict(lambda: ([], []))
    for r in rows:
        by[r["day"]][0 if r[key] else 1].append(r["net_bp"])
    diffs = [sum(a) / len(a) - sum(b) / len(b) for a, b in by.values() if a and b]
    if len(diffs) < 3:
        return float("nan"), 0.0, len(diffs)
    m = sum(diffs) / len(diffs)
    sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / (len(diffs) - 1))
    return m, (m / (sd / math.sqrt(len(diffs))) if sd else 0.0), len(diffs)


def main() -> None:
    ann = load_announcements()
    days_with = len(list((DATA / "intraday" / "nse_events" / "ann").glob("*.json.gz")))
    rows = []
    for line in gzip.open(DATA / "runs" / "y2" / "features.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if not r.get("filled") or not (DEV_FROM <= r["day"] <= END):
            continue
        prev = date.fromisoformat(r["day"]) - timedelta(days=1)
        lo = int(datetime(prev.year, prev.month, prev.day, 15, 30, tzinfo=IST).timestamp())
        ts, mat = ann.get(r["sym"], ([], []))
        i, j = bisect_right(ts, lo), bisect_right(ts, r["t"])
        r["any"] = j > i
        r["material"] = any(mat[i:j])
        rows.append(r)
    print(f"announcement days loaded: {days_with}; signals {len(rows)}; keywords {len(KEYWORDS)}")
    res = {}
    for h, key in (("H8_any", "any"), ("H8_material", "material")):
        for name, lo_d, hi_d in (("development", DEV_FROM, HOLDOUT_FROM), ("holdout", HOLDOUT_FROM, "9999")):
            per = [r for r in rows if lo_d <= r["day"] < hi_d]
            m, t, n = daily_diff(per, key)
            aff = [r["net_bp"] for r in per if r[key]]
            una = [r["net_bp"] for r in per if not r[key]]
            res[f"{h}:{name}"] = {"diff_bp": round(m, 3), "t": round(t, 2), "days": n,
                                  "affected_share": round(len(aff) / len(per), 4) if per else None,
                                  "affected_mean_bp": round(sum(aff) / len(aff), 3) if aff else None,
                                  "unaffected_mean_bp": round(sum(una) / len(una), 3) if una else None}
        hd, dv = res[f"{h}:holdout"], res[f"{h}:development"]
        adopt = hd["diff_bp"] <= -2 and hd["t"] <= -2 and dv["diff_bp"] < 0
        res[f"{h}:holdout"]["decision"] = "ADOPT" if adopt else "NO-GO"
    for k, v in res.items():
        print(f"{k:<24} {json.dumps(v)}")
    out = DATA / "runs" / "event_proxy"
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "result.json", "w"), indent=1)


if __name__ == "__main__":
    main()
