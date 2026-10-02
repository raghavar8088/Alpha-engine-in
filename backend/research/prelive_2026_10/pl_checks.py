"""(i) the leaderboard's ANTI winners over two years; (ii) the existing signals gated by the
09:45 realized/implied model (fitted on explore only)."""
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date

sys.argv = sys.argv[:1]
import pl_vol as V  # noqa: E402  (builds the day table and the explore fit)
from pl_replay import LOT, SPREAD, fees, kdate  # noqa: E402

import numpy as np  # noqa: E402

R = json.load(open("pl_replay_trades.json"))


def period(k):
    d = kdate(k)
    return "explore" if d <= date(2025, 12, 31) else "confirm" if d < date(2026, 7, 20) else "live"


# (i) the 12 ANTI rows topping the live leaderboard = the 12 worst real strategies
worst = ["intra_macd_hist_turn@15m", "intra_rsi_divergence@15m", "intra_trix@15m", "scalp_stoch_pop@5m",
         "intra_rsi_regime@15m", "nj_premium_discount@15m", "scalp_rsi2@5m", "it_market_structure@15m",
         "mt_breakout_buying@15m", "sl_reversal_finder@15m", "prt_hero_zero@15m", "scalp_ibs@5m"]
print("ANTI = SELL the option the base strategy bought (its target is the seller's stop, its stop the target).")
print("Seller net per trade (lot 65) = -(premium change) - spread - the seller's own fees:")
for per in ("explore", "confirm", "live"):
    xs = [x for k in worst for x in R.get(k, []) if period(x["k"]) == per]
    sell = [-(x["p1"] - x["p0"] + 2 * SPREAD) * LOT - fees(x["p0"], x["p1"]) for x in xs]
    print(f"  {per:8s}: the 12 'ANTI' leaders as sellers: {len(xs)} trades, {statistics.mean(sell):+.0f}/trade")
allx = [x for v in R.values() for x in v]
for per in ("explore", "confirm", "live"):
    xs = [x for x in allx if period(x["k"]) == per]
    sell = [-(x["p1"] - x["p0"] + 2 * SPREAD) * LOT - fees(x["p0"], x["p1"]) for x in xs]
    print(f"  {per:8s}: every signal as a seller: {statistics.mean(sell):+.0f}/trade")

# (ii) gate the existing signals by the 09:45 vol model (explore fit), quintile cut from explore
ok = {d["k"]: d for d in V.days if d["rv_prev"] and d["rv5"]}
pred = {k: float(np.dot(V.feats(d), V.w)) for k, d in ok.items()}
cuts = np.quantile([pred[d["k"]] for d in V.ex], [0.2, 0.4, 0.6, 0.8])


def q(k):
    return int(np.searchsorted(cuts, pred[k])) + 1 if k in pred else None


print("\nThe EXISTING signals, by the day's predicted realized/implied quintile (entries after 09:45 only):")
for per in ("explore", "confirm", "live"):
    by = defaultdict(list)
    for x in allx:
        if period(x["k"]) != per or q(x["k"]) is None:
            continue
        if V.ist(x["e"]).hour * 60 + V.ist(x["e"]).minute < 585:
            continue
        by[q(x["k"])].append(x["net"])
    print(f"  {per:8s}: " + "  ".join(f"Q{i} {statistics.mean(by[i]):+5.0f} (n {len(by[i])})" for i in sorted(by)))
