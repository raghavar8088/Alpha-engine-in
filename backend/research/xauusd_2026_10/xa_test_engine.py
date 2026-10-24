"""Engine checks on hand-built price paths (python xa_test_engine.py). Every fill rule the study
relies on is exercised: next-open entries, signal exits, stop entries (touch and gap), stops
(touch and gap), stop-before-target in one hour, the stop in the entry hour, trailing stops,
time exits, the window end, and the cost and financing arithmetic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path

import numpy as np
import pandas as pd

from xa_engine import COSTS, Costs, Market, Plan, curve_stats, equity_curve, net_returns, run, stats, trades_frame

HOURS = 4                                   # hours per session in these tests


def market(hours: list[tuple[float, float, float, float]], rate: float = 0.05) -> Market:
    """hours: (open, high, low, close) for consecutive hours; HOURS per session."""
    n = len(hours) // HOURS
    t0 = pd.Timestamp("2024-01-08 23:00", tz="UTC")              # a Monday session, 18:00 New York
    idx = []
    for s in range(n):
        base = t0 + pd.Timedelta(days=s)
        idx += [base + pd.Timedelta(hours=k) for k in range(HOURS)]
    a = np.array(hours, float)
    d_date = np.array([np.datetime64("2024-01-09") + np.timedelta64(s, "D") for s in range(n)], dtype="datetime64[D]")
    d_o = a[::HOURS, 0]
    d_h = a[:, 1].reshape(n, HOURS).max(axis=1)
    d_l = a[:, 2].reshape(n, HOURS).min(axis=1)
    d_c = a[HOURS - 1::HOURS, 3]
    days = pd.date_range("2024-01-01", periods=200, freq="D")
    return Market(d_date=d_date, d_o=d_o, d_h=d_h, d_l=d_l, d_c=d_c,
                  h_t=np.array([x.value // 10**9 for x in idx], dtype=np.int64), h_o=a[:, 0], h_h=a[:, 1], h_l=a[:, 2], h_c=a[:, 3],
                  h_ny_hour=np.array([(18 + k) % 24 for _ in range(n) for k in range(HOURS)]),
                  s_start=np.arange(n) * HOURS, s_end=np.arange(1, n + 1) * HOURS, rate=pd.Series(rate, index=days))


def flat(n_sessions: int, px: float = 100.0):
    return [(px, px + 0.5, px - 0.5, px)] * (n_sessions * HOURS)


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    assert cond, name


def b(n, *on):
    a = np.zeros(n, bool)
    for i in on:
        a[i] = True
    return a


def test_next_open_and_signal_exit():
    h = flat(8)
    for k in range(3 * HOURS, 8 * HOURS):           # price steps up from session 3
        h[k] = (110.0, 110.5, 109.5, 110.0)
    m = market(h)
    p = Plan(long_entry=b(8, 1), long_exit=b(8, 4))
    t = run(m, p, 1, 7)
    check("one trade", len(t) == 1)
    check("entry at the open of the session after the signal", t[0].entry_session == 2 and t[0].entry_px == 100.0)
    check("exit at the next open after the exit signal", t[0].exit_session == 5 and t[0].exit_px == 110.0 and t[0].reason == "signal")


def test_stop_entry_touch_and_gap():
    h = flat(5)
    h[2 * HOURS + 1] = (100.0, 106.0, 99.8, 105.5)      # session 2, hour 1 trades through 105
    m = market(h)
    buy = np.full(5, np.nan)
    buy[1] = 105.0
    t = run(m, Plan(buy_stop=buy, max_hold=1), 1, 4)
    check("stop entry fills at the level when touched", t[0].entry_px == 105.0 and t[0].entry_session == 2)
    h2 = flat(5)
    h2[2 * HOURS + 1] = (107.0, 108.0, 106.5, 107.5)    # gaps over the level
    t2 = run(market(h2), Plan(buy_stop=buy, max_hold=1), 1, 4)
    check("stop entry fills at the open when the hour gaps past the level", t2[0].entry_px == 107.0)


def test_stop_touch_gap_and_priority():
    h = flat(6)
    h[3 * HOURS + 2] = (99.0, 99.2, 94.0, 94.5)         # long from 100 with stop 95: touched
    m = market(h)
    t = run(m, Plan(long_entry=b(6, 1), stop_dist=np.full(6, 5.0)), 1, 5)
    check("stop fills at the stop level", t[0].exit_px == 95.0 and t[0].reason == "stop")
    h2 = flat(6)
    h2[3 * HOURS + 2] = (93.0, 93.5, 92.0, 92.5)        # opens below the stop
    t2 = run(market(h2), Plan(long_entry=b(6, 1), stop_dist=np.full(6, 5.0)), 1, 5)
    check("a gap through the stop fills at the open", t2[0].exit_px == 93.0)
    h3 = flat(6)
    h3[3 * HOURS + 2] = (100.0, 111.0, 94.0, 100.0)     # stop 95 and target 110 in one hour
    t3 = run(market(h3), Plan(long_entry=b(6, 1), stop_dist=np.full(6, 5.0), tp_dist=np.full(6, 10.0)), 1, 5)
    check("stop and target in one hour -> the stop", t3[0].reason == "stop" and t3[0].exit_px == 95.0)
    h4 = flat(6)
    h4[3 * HOURS + 2] = (100.0, 111.0, 99.0, 110.5)
    t4 = run(market(h4), Plan(long_entry=b(6, 1), stop_dist=np.full(6, 5.0), tp_dist=np.full(6, 10.0)), 1, 5)
    check("target alone fills at the target", t4[0].reason == "target" and t4[0].exit_px == 110.0)


def test_stop_in_entry_hour():
    h = flat(5)
    h[2 * HOURS + 1] = (100.0, 106.0, 99.0, 100.0)      # buy-stop 105 fills, stop 103 also inside the hour
    m = market(h)
    buy = np.full(5, np.nan)
    buy[1] = 105.0
    t = run(m, Plan(buy_stop=buy, stop_dist=np.full(5, 2.0)), 1, 4)
    check("a stop touched in the entry hour counts against the trade", t[0].reason == "stop" and t[0].exit_px == 103.0 and t[0].exit_hour == t[0].entry_hour)


def test_trailing_time_and_window():
    h = []
    for s in range(8):
        px = 100.0 + 2 * s
        h += [(px, px + 0.5, px - 0.5, px)] * HOURS
    h[6 * HOURS + 1] = (112.0, 112.2, 105.0, 106.0)     # falls through a chandelier stop
    m = market(h)
    atr = np.full(8, 1.0)
    t = run(m, Plan(long_entry=b(8, 0), trail=("chandelier", 3.0, atr)), 1, 7)
    # highest high before session 6 = 110.5 (session 5) -> stop 107.5 at the close of session 5
    check("chandelier stop ratchets up and fills", t[0].reason == "stop" and abs(t[0].exit_px - 107.5) < 1e-9)
    t2 = run(market(flat(8)), Plan(long_entry=b(8, 1), max_hold=3), 1, 7)
    check("time exit after max_hold sessions", t2[0].exit_session == 5 and t2[0].reason == "time")
    t3 = run(market(flat(8)), Plan(long_entry=b(8, 1)), 1, 6)
    check("open trade closed at the window end", t3[0].reason == "window end" and t3[0].exit_session == 6)


def test_state_reversal():
    m = market(flat(8))
    s = np.array([0, 1, 1, -1, -1, 0, 0, 0], float)
    p = Plan(long_entry=s > 0, short_entry=s < 0, long_exit=s <= 0, short_exit=s >= 0, reverse=True, state=True)
    t = run(m, p, 1, 7)
    check("long, then reversed to short at one open, then flat", [(x.side, x.entry_session, x.exit_session) for x in t] == [(1, 2, 4), (-1, 4, 6)])


def test_costs():
    m = market(flat(40), rate=0.05)
    tf = trades_frame(m, run(m, Plan(long_entry=b(40, 1), max_hold=7), 1, 39))
    c = Costs("t", spread=0.40, slippage=0.10, commission=0.035, fin_long_add=0.005, fin_short_add=0.015)
    r = net_returns(m, tf, c)
    nights = int(tf["nights"].iloc[0])
    expect = ((100 - 0.3) - (100 + 0.3) - 0.07) / 100.3 - (0.05 + 0.005) * nights / 365
    check(f"long net = price move - spread - slippage - commission - financing ({nights} nights)", abs(r[0] - expect) < 1e-12)
    tf2 = tf.copy()
    tf2["side"] = -1
    r2 = net_returns(m, tf2, c)
    expect2 = ((100 - 0.3) - (100 + 0.3) - 0.07) / 99.7 - (0.015 - 0.05) * nights / 365
    check("short net receives the T-bill less the add-on", abs(r2[0] - expect2) < 1e-12)
    st = stats(np.array([0.05, -0.02, -0.01, 0.03, -0.01, -0.02, -0.03]))
    check("longest losing streak", st["longest_losing_streak"] == 3)
    check("profit factor", abs(st["profit_factor"] - 0.08 / 0.09) < 1e-12)
    eq = equity_curve(m, tf, r, 1, 39, COSTS["C1"])
    check("equity ends at 1 + the trade's net return", abs(eq.iloc[-1] - (1 + r[0])) < 1e-12)
    check("curve stats run", "max_drawdown" in curve_stats(eq))


if __name__ == "__main__":
    for f in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        f()
    print("all engine checks passed")
