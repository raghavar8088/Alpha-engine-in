"""Backtest vs the live tournament, trade by trade, over the days both cover (Phase 2 check).

    python fidelity.py <run name> [strategy ids, comma-separated; default: all]

A live trade is "reproduced" when the backtest took the same strategy, stock and side at the
same signal close (opening-range families: the same day). Reports, overall and per strategy:
live trades, backtest trades, shared, the share of live trades reproduced, how often shared
trades closed for the same reason, and both sides' net on the shared trades.
Targets (INTRADAY_STOCKS_AI_UPGRADE_PLAN.md Phase 2): >= 60% reproduced, >= 95% same exit.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def day(t: int) -> str:
    return datetime.fromtimestamp(t, IST).date().isoformat()


def reason(r: str | None) -> str:
    r = (r or "").lower()
    return "eod" if r.startswith("eod") else r


def main() -> None:
    name = sys.argv[1]
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    bt = [json.loads(x) for x in gzip.open(DATA / "runs" / name / "trades.jsonl.gz", "rt", encoding="utf-8")]
    live = [json.loads(x) for x in open(DATA / "exports" / "live_v2.jsonl", encoding="utf-8")]
    live = [r for r in live if r.get("status") == "CLOSED" and (only is None or r["strategy_id"] in only)]
    days = {day(r["opened_at"]) for r in live}
    bt = [t for t in bt if day(t[2]) in days and (only is None or t[0] in only)]

    def k_bt(t):
        return (t[0], t[1], t[4], day(t[2])) if "orb" in t[0] else (t[0], t[1], t[4], t[2])

    def k_live(r):
        sid = r["strategy_id"]
        return (sid, r["symbol"], r["side"], day(r["opened_at"])) if "orb" in sid else (sid, r["symbol"], r["side"], r["signal_bar_close"])

    bmap, lmap = defaultdict(list), defaultdict(list)
    for t in bt:
        bmap[k_bt(t)].append(t)
    for r in live:
        lmap[k_live(r)].append(r)
    per = defaultdict(lambda: defaultdict(float))
    for k in set(bmap) | set(lmap):
        sid = k[0]
        b, lv = bmap.get(k, []), lmap.get(k, [])
        per[sid]["bt"] += len(b)
        per[sid]["live"] += len(lv)
        for t, r in zip(b, lv):
            per[sid]["shared"] += 1
            per[sid]["same_exit"] += reason(t[11]) == reason(r.get("exit_reason"))
            per[sid]["bt_net_shared"] += t[10]
            per[sid]["live_net_shared"] += r.get("realized_pnl") or 0.0
    tot = defaultdict(float)
    print(f"days compared: {len(days)} ({min(days)} -> {max(days)})")
    print(f"{'strategy':<26} {'live':>5} {'bt':>5} {'shared':>6} {'repro%':>7} {'same exit%':>10} {'bt net (shared)':>16} {'live net (shared)':>18}")
    for sid in sorted(per, key=lambda s: -per[s]["live"]):
        p = per[sid]
        for kk, v in p.items():
            tot[kk] += v
        print(f"{sid:<26} {int(p['live']):>5} {int(p['bt']):>5} {int(p['shared']):>6} "
              f"{p['shared'] / p['live'] * 100 if p['live'] else 0:>6.1f}% "
              f"{p['same_exit'] / p['shared'] * 100 if p['shared'] else 0:>9.1f}% "
              f"{p['bt_net_shared']:>16,.0f} {p['live_net_shared']:>18,.0f}")
    repro = tot["shared"] / tot["live"] * 100 if tot["live"] else 0.0
    same = tot["same_exit"] / tot["shared"] * 100 if tot["shared"] else 0.0
    print(f"{'ALL':<26} {int(tot['live']):>5} {int(tot['bt']):>5} {int(tot['shared']):>6} {repro:>6.1f}% {same:>9.1f}% "
          f"{tot['bt_net_shared']:>16,.0f} {tot['live_net_shared']:>18,.0f}")
    print(f"targets: reproduced >= 60% -> {'MET' if repro >= 60 else 'NOT MET'}; same exit >= 95% -> {'MET' if same >= 95 else 'NOT MET'}")


if __name__ == "__main__":
    main()
