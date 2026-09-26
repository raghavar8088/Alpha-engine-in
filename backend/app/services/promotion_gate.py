"""The promotion gate: does a strategy's record show an EDGE, or just a good run?

Every desk in this app runs many strategies at once and ranks them by net P&L. That
ranking is the most dangerous number on the page, because **the top of a large leaderboard
is where luck collects.** Run 150 coin-flipping strategies and roughly 75 finish positive;
the best of them will look excellent, and it will have proved nothing.

So a verdict here is not "did it make money". It is "would this record be surprising if the
strategy had no edge at all".

WHY THE t-STAT THRESHOLD MOVES WITH THE NUMBER OF STRATEGIES
------------------------------------------------------------
A t-statistic of 2 means "about a 1-in-20 chance of a run this good from nothing". Test ONE
strategy and that is decent evidence. Test 150 and you should EXPECT seven or eight to clear
it on noise alone — clearing it tells you almost nothing.

The fix is to hold the error rate for the WHOLE FAMILY of strategies rather than for each
one. Bonferroni: to keep a 5% chance of even one false positive across N strategies, each
must clear 5%/N. The threshold therefore rises with N:

      1 strategy    t >= 1.96
     50 strategies  t >= 3.29
    150 strategies  t >= 3.59
    548 strategies  t >= 3.89

That is deliberately demanding, and it is the honest bar. A desk that promotes on t >= 1.5
out of 548 candidates is not selecting an edge, it is selecting the luckiest ticket.

Bonferroni is the conservative choice among the corrections. It assumes the strategies are
independent, which they are not — many here are the same idea at different parameters, so
the true number of independent bets is lower than N and this bar is stricter than it needs
to be. That is the right direction to err when the output is "put real money on this".

WHAT THE GATE CANNOT DO
-----------------------
It cannot tell you a strategy will keep working. It only rules out the records that are
indistinguishable from chance. Everything it passes is a candidate for out-of-sample
testing, not a conclusion.
"""

import math
from statistics import NormalDist

# Family-wise error rate: the chance of promoting even ONE strategy that has no edge.
FAMILY_ALPHA = 0.05

# A record shorter than this cannot be judged at all, whatever it returned.
MIN_TRADES = 30

# Economic floors, applied on top of the statistical one. A strategy can be significant and
# still not worth trading — significantly grinding out less than its costs, for instance.
MIN_PROFIT_FACTOR = 1.2
MAX_DRAWDOWN_PCT = 25.0


def t_threshold(n_strategies: int) -> float:
    """The t-statistic a strategy must clear, given how many were tried alongside it.

    Two-sided Bonferroni. Returns the plain 1.96 for a single strategy and rises from
    there; never returns less than 1.96, because no amount of arithmetic makes a weaker
    result more convincing."""
    n = max(int(n_strategies or 1), 1)
    alpha = FAMILY_ALPHA / n
    return max(NormalDist().inv_cdf(1.0 - alpha / 2.0), 1.96)


def trade_stats(pnls: list[float], capital: float) -> dict:
    """Summary of one strategy's closed-trade record."""
    n = len(pnls)
    if n == 0:
        return {"trades": 0, "wins": 0, "win_rate": 0.0, "net_pnl": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": None,
                "expectancy": 0.0, "max_drawdown_pct": 0.0, "t_stat": None,
                "return_pct": 0.0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net, gp, gl = sum(pnls), sum(wins), abs(sum(losses))

    equity = peak = capital
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    t_stat = None
    if n >= 2:
        mean = net / n
        sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (n - 1))
        if sd > 0:
            t_stat = round(mean / (sd / math.sqrt(n)), 3)

    return {
        "trades": n, "wins": len(wins),
        "win_rate": round(len(wins) / n, 4),
        "net_pnl": round(net, 2),
        "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "expectancy": round(net / n, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "t_stat": t_stat,
        "return_pct": round(net / capital * 100, 3) if capital else 0.0,
    }


def verdict(stats: dict, n_strategies: int) -> tuple[str, list[str]]:
    """READY / REJECTED / PENDING, with the reasoning spelled out.

    PENDING is not a soft pass. It means the record is too short to judge, and a short
    record is exactly where a lucky streak looks like an edge."""
    need_t = t_threshold(n_strategies)

    if stats["trades"] < MIN_TRADES:
        return "PENDING", [
            f"{stats['trades']}/{MIN_TRADES} closed trades — too short to judge. "
            f"No verdict is not approval."]

    fails: list[str] = []
    if stats["net_pnl"] <= 0:
        fails.append(f"Net P&L ₹{stats['net_pnl']:,.0f} is not positive after costs.")

    pf = stats["profit_factor"]
    if pf is None and stats["gross_loss"] == 0 and stats["gross_profit"] > 0:
        pass                       # every trade a winner; no losses to divide by
    elif pf is None or pf <= MIN_PROFIT_FACTOR:
        fails.append(
            f"Profit factor {'undefined' if pf is None else round(pf, 2)} "
            f"is not above {MIN_PROFIT_FACTOR}.")

    if stats["expectancy"] <= 0:
        fails.append(f"Expectancy ₹{stats['expectancy']:,.0f} per trade is not positive.")

    if stats["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        fails.append(
            f"Peak-to-trough drawdown {stats['max_drawdown_pct']:.1f}% exceeds "
            f"{MAX_DRAWDOWN_PCT:.0f}%.")

    t = stats["t_stat"]
    if t is None or t < need_t:
        fails.append(
            f"t-statistic {'undefined' if t is None else round(t, 2)} is below the "
            f"{need_t:.2f} this desk requires. That bar is raised because {n_strategies} "
            f"strategies were tried: at the usual 1.96 you would expect about "
            f"{max(1, round(n_strategies * 0.05))} of them to clear it on luck alone, so "
            f"clearing 1.96 here would mean nothing.")

    if fails:
        return "REJECTED", fails

    return "READY", [
        f"{stats['trades']} trades, profit factor "
        f"{'no losing trades' if pf is None else format(pf, '.2f')}, expectancy "
        f"₹{stats['expectancy']:,.0f}/trade, max drawdown {stats['max_drawdown_pct']:.1f}%, "
        f"t-stat {format(t, '.2f')} against a {need_t:.2f} bar corrected for "
        f"{n_strategies} strategies tried. This record would be surprising from a strategy "
        f"with no edge — which is not the same as proof that it will keep working."]


def grade(pnls: list[float], capital: float, n_strategies: int) -> dict:
    """stats + verdict in one call — what a leaderboard row needs."""
    stats = trade_stats(pnls, capital)
    v, reasons = verdict(stats, n_strategies)
    return {**stats, "verdict": v, "verdict_reasons": reasons,
            "t_threshold": round(t_threshold(n_strategies), 3),
            "strategies_tested": int(n_strategies)}
