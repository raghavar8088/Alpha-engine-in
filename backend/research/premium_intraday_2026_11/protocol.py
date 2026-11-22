"""The test protocol, fixed before any result was seen (22 Nov 2026).

PERIODS
  development  4 Nov 2024 - 30 Apr 2026, walk-forward: train 6 months, test the next 3 months, four folds
  final        1 May 2026 - 3 Nov 2026, UNTOUCHED: opened once, after prereg.json is frozen and committed
  post-final   4 - 20 Nov 2026 if the box's bars can be read (a genuinely later slice; reported separately)

WALK-FORWARD CHOICE
  The only parameter chosen on data is each strategy's target multiple, from {1.5R, 2R, 3R}: in each fold the
  multiple with the best mean net R on the TRAINING window (>= 20 trades, else 2R) is used on the TEST window.
  For the final period the choice is made on the last six development months (Nov 2025 - Apr 2026) and frozen.

TRIALS COUNTED
  6 strategies x 2 sides x 4 ladder levels x 3 targets = 144 configurations replayed. Only the PRIMARY level of
  each strategy can qualify (36 candidate configurations); the other levels are the ablations the brief asks for.
  The 62 imported strategies (54 tournament + 8 Stock Momentum) are judged on the same criteria. The multiple-
  testing bar uses K = 100 (36 + 62, rounded up): one-sided Bonferroni 5% -> t >= 3.29.
"""
from datetime import date

DEV_START, DEV_END = date(2024, 11, 4), date(2026, 4, 30)
FINAL_START, FINAL_END = date(2026, 5, 1), date(2026, 11, 3)
POST_START, POST_END = date(2026, 11, 4), date(2026, 11, 20)

FOLDS = [  # (train_from, train_to, test_from, test_to)
    (date(2024, 11, 4), date(2025, 4, 30), date(2025, 5, 1), date(2025, 7, 31)),
    (date(2025, 2, 1), date(2025, 7, 31), date(2025, 8, 1), date(2025, 10, 31)),
    (date(2025, 5, 1), date(2025, 10, 31), date(2025, 11, 1), date(2026, 1, 31)),
    (date(2025, 8, 1), date(2026, 1, 31), date(2026, 2, 1), date(2026, 4, 30)),
]
FINAL_TRAIN = (date(2025, 11, 1), date(2026, 4, 30))
TARGETS = (1.5, 2.0, 3.0)
LEVELS = ("L0", "L1", "L2", "L3")
MIN_TRAIN_TRADES = 20
DEFAULT_TARGET = 2.0
K_TRIALS = 100

# Promotion criteria (pis lifecycle). Every one must hold; long and short are judged separately.
CRITERIA = {
    "backtest_qualified": {
        "wf_oos_min_trades": 60, "wf_oos_mean_R_gt": 0.0,
        "final_min_trades": 30, "final_mean_R_gt": 0.0, "final_profit_factor_ge": 1.10,
        "final_mean_R_at_2x_slippage_ge": 0.0,
        "pooled_t_day_ge": 2.0,
        "wf_folds_positive_min": 3,
        "pooled_net_ex_best5pct_days_gt": 0.0, "pooled_top_symbol_share_le": 0.35,
        "final_book_max_dd_pct_le": 5.0,
    },
    "portfolio_eligible": {
        "forward_min_trades": 30, "forward_min_sessions": 15, "forward_mean_R_gt": 0.0,
        "pooled_with_forward_t_day_ge": 3.29,
        "forward_not_worse_than_backtest_p_gt": 0.05,
        "forward_missed_rate_le": 0.50, "forward_unresolved_exits": 0,
    },
    "paused": {"forward_cum_R_le": -8.0, "forward_dd_vs_backtest_ge": 2.0},
}


def in_period(d, a, b):
    return a <= d <= b
