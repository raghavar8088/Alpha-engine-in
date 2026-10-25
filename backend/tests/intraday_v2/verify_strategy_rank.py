"""The leaderboard's multi-factor rank: does it order strategies the way it says it does?

Run:  python backend/tests/intraday_v2/verify_strategy_rank.py

Pure - no Mongo, no network. What is tested:
- the weights add to 100 and every factor is reported per row;
- percentiles are relative to the board, ties share one, and "lower is better" inverts;
- a missing factor counts as neutral, not as worst;
- a profit factor with no losing trade is the best, not missing;
- a short record is pulled toward 50, so five lucky trades cannot outrank a long good record;
- rows with no trades are unranked and sort last; ranks run 1..n in score order;
- day factors: positive-day share over the strategy's sessions, recent P&L over the DESK's last 5.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.strategy_rank import FACTORS, _percentiles, day_factors, rank_rows  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    failures += 0 if ok else 1


def row(sid, trades, **kw):
    base = {"strategy_id": sid, "trades": trades, "net_pnl": 0.0, "win_rate": 0.5, "t_stat": 0.0,
            "net_bp_per_trade": 0.0, "profit_factor": 1.0, "gross_profit": 1.0, "gross_loss": 1.0,
            "max_drawdown_pct": 2.0, "positive_days_pct": 50.0, "recent_pnl": 0.0}
    base.update(kw)
    return base


check("weights sum to 100", abs(sum(w for _k, _l, w, _h in FACTORS) - 100.0) < 1e-9)

p = _percentiles([1.0, 2.0, 2.0, 3.0], True)
check("percentile ties share a rank", p == [0.0, 50.0, 50.0, 100.0], str(p))
p = _percentiles([1.0, 5.0, None], False)
check("lower is better inverts; missing stays None", p == [100.0, 0.0, None], str(p))

good = row("good", 100, t_stat=2.0, net_bp_per_trade=20.0, profit_factor=1.8, max_drawdown_pct=1.0,
           positive_days_pct=70.0, recent_pnl=50_000.0, win_rate=0.55, net_pnl=150_000.0)
bad = row("bad", 100, t_stat=-2.0, net_bp_per_trade=-20.0, profit_factor=0.6, max_drawdown_pct=5.0,
          positive_days_pct=20.0, recent_pnl=-50_000.0, win_rate=0.35, net_pnl=-150_000.0)
mid = row("mid", 100)
lucky = row("lucky", 5, t_stat=9.0, net_bp_per_trade=90.0, profit_factor=None, gross_loss=0.0,
            gross_profit=10_000.0, max_drawdown_pct=0.0, positive_days_pct=100.0,
            recent_pnl=60_000.0, win_rate=1.0, net_pnl=10_000.0)
idle = row("idle", 0)
out = rank_rows([idle, bad, lucky, mid, good], min_trades=30)
order = [r["strategy_id"] for r in out]
check("good record ranks first", order[0] == "good", str(order))
check("five perfect trades do not outrank a long good record",
      order.index("lucky") > order.index("good"), str(order))
check("a short record is pulled toward 50",
      abs(lucky["rank_score"] - 50) < abs(good["rank_score"] - 50) and lucky["rank_shrunk"],
      f"lucky {lucky['rank_score']} good {good['rank_score']}")
check("bad record ranks last of the traded", order[-2] == "bad", str(order))
check("no trades: unranked and last", order[-1] == "idle" and idle["rank"] is None and idle["rank_score"] is None)
check("ranks run 1..n in score order",
      [r["rank"] for r in out[:-1]] == [1, 2, 3, 4]
      and all(out[i]["rank_score"] >= out[i + 1]["rank_score"] for i in range(3)))
pf = next(f for f in lucky["rank_factors"] if f["key"] == "profit_factor")
check("profit factor with no losses is the best", pf["percentile"] == 100.0, str(pf))
check("every factor reported per row", all(len(r["rank_factors"]) == len(FACTORS) for r in out[:-1]))

a = row("a", 50, t_stat=None)
b = row("b", 50, t_stat=1.0)
c = row("c", 50, t_stat=-1.0)
rank_rows([a, b, c])
ta = next(f for f in a["rank_factors"] if f["key"] == "t_stat")
check("missing factor is neutral, not worst", ta["percentile"] is None and b["rank_score"] > a["rank_score"] > c["rank_score"],
      f"a {a['rank_score']} b {b['rank_score']} c {c['rank_score']}")

desk = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"]
f = day_factors({"2026-10-14": 100.0, "2026-10-15": -50.0, "2026-10-23": 25.0, "2026-10-22": 0.0}, desk)
check("positive-day share over the strategy's own sessions", f["positive_days_pct"] == 50.0, str(f))
check("recent P&L sums only the desk's last 5 sessions", f["recent_pnl"] == 25.0, str(f))
check("never traded: day factors missing", day_factors({}, desk)["recent_pnl"] is None)

print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
