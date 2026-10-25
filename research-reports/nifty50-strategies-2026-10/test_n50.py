"""Hand checks of n50_engine.py.

    python test_n50.py                      synthetic checks only
    N50_DATA=<dir> python test_n50.py       also the look-ahead and smoke checks on the clean panel
                                            (<dir> holds n50_clean.pkl and universe.json)
"""
import os
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n50_engine as E  # noqa: E402
from app.services import angel_fees  # noqa: E402

NB = E.NB
ONE, ZERO = np.array([1]), np.zeros(1)


def flat(level=100.0):
    O = np.full((1, NB), level)
    return {"o": O, "h": O + 0.2, "l": O - 0.2, "c": O.copy(), "vw": np.full((1, NB), level)}


def set_bar(G, b, o, h, l, c):
    G["o"][0, b], G["h"][0, b], G["l"][0, b], G["c"][0, b] = o, h, l, c


def s1_day():
    """Range 99-101 in the first three candles, a breakout in the 09:40 candle (b = 5), then drift at 101.5."""
    G = flat()
    G["h"][0, 1], G["l"][0, 2] = 101.0, 99.0
    for b in range(3, NB):
        set_bar(G, b, 100.5, 100.7, 100.3, 100.5)
    set_bar(G, 5, 100.8, 101.4, 100.7, 101.3)
    for b in range(6, NB):
        set_bar(G, b, 101.5, 101.8, 101.2, 101.5)
    return G


def s1_trade(G, slip=0.0, side=1):
    sl = np.full(1, slip)
    sd = np.full(1, side)
    Hr, Lr = np.array([101.0]), np.array([99.0])
    if side < 0:                                   # the mirror image around 100
        Hr, Lr = 200 - Lr, 200 - Hr
    j, entry, ok, sq = E.s1_entry(G, sd, Hr, Lr, 3, sl)
    stop = Lr if side > 0 else Hr
    tgt = entry + sd * 2 * np.abs(entry - stop)
    xb, px, why = E.walk(G, j, sd, entry, stop, tgt, sq, sl)
    return j[0], entry[0], ok[0], xb[0], px[0], why[0]


def mirror(G):
    return {"o": 200 - G["o"], "h": 200 - G["l"], "l": 200 - G["h"], "c": 200 - G["c"], "vw": 200 - G["vw"]}


# ---------------------------------------------------------------------------- costs
def test_fees_equal_angel_round_trip():
    rng = np.random.default_rng(0)
    for _ in range(3000):
        e, x = rng.uniform(20, 9000, 2)
        q = int(rng.integers(1, 20000))
        for side in ("BUY", "SELL"):
            want = angel_fees.round_trip(e, x, q, side=side, product="INTRADAY").total
            buy, sell = (e * q, x * q) if side == "BUY" else (x * q, e * q)
            got = float(E.fees(np.array([buy]), np.array([sell]))[0])
            assert abs(got - want) <= 0.011, (e, x, q, side, got, want)


def test_cs_equals_ii_spreads_within_one_session():
    sys.path.insert(0, str(E.ROOT / "backend" / "research" / "index_intraday_2026_10"))
    try:
        import ii_spreads
    except Exception as exc:                       # its own imports need the index-intraday data layer
        print(f"   (skipped: ii_spreads not importable here: {exc.__class__.__name__})")
        return
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 600)))
    h, l = c * (1 + rng.uniform(0, 0.002, 600)), c * (1 - rng.uniform(0, 0.002, 600))
    v = rng.integers(0, 5, 600).astype(float)
    a = E.cs_half_spread_bp(h, l, v, np.ones(599, bool))
    b = ii_spreads.cs_half_spread_bp(h, l, v)
    assert abs(a - b) < 1e-12, (a, b)


# ---------------------------------------------------------------------------- S1
def test_s1_target_fills_only_when_traded_through():
    G = s1_day()
    G["h"][0, 10] = 105.0                          # touches the 2R target exactly: no fill
    G["h"][0, 12] = 105.01                         # trades through it
    j, entry, ok, xb, px, why = s1_trade(G)
    assert (j, ok, xb, why) == (5, True, 12, 2) and abs(entry - 101) < 1e-12 and abs(px - 105) < 1e-12


def test_s1_fills_at_the_open_when_the_candle_gaps_above_the_level():
    G = s1_day()
    set_bar(G, 5, 101.6, 101.9, 101.5, 101.7)
    j, entry, *_ = s1_trade(G, slip=0.001)
    assert j == 5 and abs(entry - 101.6 * 1.001) < 1e-9


def test_stop_counts_first_on_a_shared_candle():
    G = s1_day()
    set_bar(G, 12, 101.5, 105.5, 98.9, 100.0)
    j, entry, ok, xb, px, why = s1_trade(G)
    assert (xb, why) == (12, 1) and abs(px - 99.0) < 1e-12


def test_a_gap_through_the_stop_fills_at_the_open_less_slippage():
    G = s1_day()
    set_bar(G, 12, 98.0, 98.5, 97.5, 98.2)
    j, entry, ok, xb, px, why = s1_trade(G, slip=0.001)
    assert (xb, why) == (12, 1) and abs(px - 98.0 * 0.999) < 1e-9 and abs(entry - 101 * 1.001) < 1e-9


def test_the_entry_candle_is_checked_for_the_stop():
    G = s1_day()
    set_bar(G, 5, 100.8, 101.4, 98.9, 100.0)
    j, entry, ok, xb, px, why = s1_trade(G)
    assert (j, xb, why) == (5, 5, 1) and abs(px - 99.0) < 1e-12


def test_square_off_at_1510_and_the_next_candle_when_1510_is_missing():
    G = s1_day()
    G["o"][0, 71] = 101.55
    j, entry, ok, xb, px, why = s1_trade(G, slip=0.001)
    assert (xb, why) == (71, 0) and abs(px - 101.55 * 0.999) < 1e-9
    for k in G:
        G[k][0, 71] = np.nan
    G["o"][0, 72] = 101.6
    j, entry, ok, xb, px, why = s1_trade(G)
    assert (xb, why) == (72, 0) and abs(px - 101.6) < 1e-12


def test_s1_order_is_cancelled_at_1130():
    G = flat(100.5)
    G["h"][0, 1], G["l"][0, 2] = 101.0, 99.0
    set_bar(G, 27, 100.8, 101.4, 100.7, 101.3)     # 11:30 breakout: too late
    assert not s1_trade(G)[2]
    set_bar(G, 26, 100.8, 101.4, 100.7, 101.3)     # 11:25: still live
    assert s1_trade(G)[0] == 26


def test_short_is_the_mirror_image():
    for build in (s1_day,):
        G = build()
        G["h"][0, 12] = 105.01
        a = s1_trade(G)
        b = s1_trade(mirror(G), side=-1)
        assert (a[0], a[2], a[3], a[5]) == (b[0], b[2], b[3], b[5]), (a, b)
        assert abs((200 - a[1]) - b[1]) < 1e-9 and abs((200 - a[4]) - b[4]) < 1e-9


# ---------------------------------------------------------------------------- S2 and S3
def test_s2_vwap_trail_exits_at_the_next_open():
    G = flat(100.5)
    G["h"][0, 1], G["l"][0, 2] = 101.0, 99.0
    G["vw"][:] = 100.0
    G["c"][0, 9] = 99.9                            # first close below the session VWAP
    G["o"][0, 10] = 99.8
    sl = np.full(1, 0.001)
    i, entry, ok, sq = E.s2_entry(G, ONE, 3, sl)
    assert i[0] == 3 and ok[0] and abs(entry[0] - 100.5 * 1.001) < 1e-9
    xb, px, why = E.walk(G, i, ONE, entry, np.array([99.0]), np.full(1, np.nan), sq, sl, trail=True)
    assert (xb[0], why[0]) == (10, 3) and abs(px[0] - 99.8 * 0.999) < 1e-9


def test_s2_close_below_vwap_on_the_entry_candle_exits_next_candle():
    G = flat(100.5)
    G["vw"][:] = 100.0
    G["c"][0, 3] = 99.95
    i, entry, ok, sq = E.s2_entry(G, ONE, 3, ZERO)
    xb, px, why = E.walk(G, i, ONE, entry, np.array([99.0]), np.full(1, np.nan), sq, ZERO, trail=True)
    assert (xb[0], why[0]) == (4, 3)


def s3_day():
    G = flat(100.5)
    G["vw"][:] = 100.0
    G["l"][0, 3] = 100.3                           # no touch at 09:30
    set_bar(G, 4, 100.3, 100.4, 99.95, 100.1)      # touches the VWAP
    set_bar(G, 5, 100.1, 100.38, 99.8, 100.35)     # no close above 100.4 yet
    set_bar(G, 6, 100.3, 100.5, 100.1, 100.45)     # signal
    set_bar(G, 7, 100.46, 100.6, 100.4, 100.5)     # entry at this open
    return G


def test_s3_pullback_entry_and_stop():
    k, entry, stop, ok, sq = E.s3_entry(s3_day(), ONE, 3, ZERO)
    assert ok[0] and k[0] == 7 and abs(entry[0] - 100.46) < 1e-12 and abs(stop[0] - 99.8) < 1e-12


def test_s3_signal_after_1325_is_too_late():
    G = flat(100.5)
    G["vw"][:] = 100.0
    G["l"][0, 3:] = 100.3
    set_bar(G, 40, 100.3, 100.4, 99.95, 100.1)
    G["c"][0, 41:51] = 100.3
    G["c"][0, 51] = 100.45                         # 13:30 candle closes above: too late
    assert not E.s3_entry(G, ONE, 3, ZERO)[3][0]
    G["c"][0, 50] = 100.45                         # 13:25 candle: in time
    k, entry, stop, ok, sq = E.s3_entry(G, ONE, 3, ZERO)
    assert ok[0] and k[0] == 51


def test_entries_do_not_read_candles_after_the_entry():
    rng = np.random.default_rng(3)
    for build, fn in ((s1_day, lambda G: E.s1_entry(G, ONE, np.array([101.0]), np.array([99.0]), 3, ZERO)[:2]),
                      (s3_day, lambda G: E.s3_entry(G, ONE, 3, ZERO)[:2])):
        G = build()
        i0, e0 = fn(G)
        H = {k: v.copy() for k, v in G.items()}
        for k in ("o", "h", "l", "c", "vw"):
            H[k][0, i0[0] + 1:] *= rng.uniform(0.95, 1.05, NB - i0[0] - 1)
        i1, e1 = fn(H)
        assert i0[0] == i1[0] and abs(e0[0] - e1[0]) < 1e-12


# ---------------------------------------------------------------------------- sizing and the book
def test_sizing_caps():
    p = types.SimpleNamespace(turn5=np.array([[1e9, 1e9, 2e7]]))
    s, d = np.zeros(3, int), np.array([0, 1, 2])
    entry, stop = np.array([100.0, 1000.0, 1000.0]), np.array([99.0, 999.5, 990.0])
    r = E.settle(p, s, d, np.ones(3), np.full(3, 3), entry, stop, np.full(3, 71), entry, np.zeros(3, int),
                 np.ones(3, bool))
    assert list(r["qty"]) == [5000, 1000, 200]     # risk / notional / turnover cap binds
    assert abs(r["net"][0] + E.fees(np.array([5e5]), np.array([5e5]))[0]) < 1e-9


def test_book_takes_the_first_five_entries_in_time_then_rank_order():
    C = pd.DataFrame({"d": [0] * 7, "entry_bar": [3, 3, 5, 4, 6, 7, 8], "exit_bar": [71] * 7,
                      "mv": [0.3, 0.9, 0.5, 0.4, 0.8, 0.7, 0.6], "notional": [9e5] * 7})
    kept = E.book(C)
    assert list(kept.index) == [1, 0, 3, 2, 4]


def test_book_notional_cap():
    C = pd.DataFrame({"d": [0] * 3, "entry_bar": [3, 4, 5], "exit_bar": [71] * 3, "mv": [1, 1, 1],
                      "notional": [3e6, 2.5e6, 2e6]})
    assert list(E.book(C).index) == [0, 2]


# ---------------------------------------------------------------------------- on the clean panel
def _subset(data):
    p = pd.read_pickle(Path(data) / "n50_clean.pkl")
    keep = {"RELIANCE", "INFY", "HDFCBANK", "TATASTEEL", "SBIN"}
    import json
    idx = set(json.load(open(Path(data) / "universe.json"))["indices"])
    return p[(p.symbol.isin(keep | idx)) & (p.day <= pd.Timestamp("2022-09-30"))].reset_index(drop=True)


def test_screen_reads_nothing_after_0925(data):
    p = _subset(data)
    mem, uni = HERE / "phase0" / "membership.json", Path(data) / "universe.json"
    a = E.Panel(p, mem, uni)
    fa = a.screen(3)
    d0 = 150
    day0 = a.days[d0]
    q = p.copy()
    late = ((q.day == day0) & ((q.ts.dt.hour * 60 + q.ts.dt.minute) >= 9 * 60 + 30)) | (q.day > day0)
    rng = np.random.default_rng(5)
    k = rng.uniform(0.9, 1.1, late.sum())
    for col in ("o", "h", "l", "c"):
        q.loc[late, col] = q.loc[late, col] * k
    q.loc[late, "v"] = (q.loc[late, "v"] * rng.uniform(0.5, 2.0, late.sum())).round()
    b = E.Panel(q, mem, uni)
    fb = b.screen(3)
    checked = 0
    for key in ("or_move", "gap", "or_pos", "rvol", "rs_nifty", "rs_sector", "VWAP", "H", "L", "P", "prevH",
                "prevL", "nifty_ret", "eligible"):
        x, y = np.asarray(fa[key])[:, :d0 + 1], np.asarray(fb[key])[:, :d0 + 1]
        assert np.array_equal(x, y, equal_nan=True) if x.dtype != bool else np.array_equal(x, y), key
        checked += 1
    for key in ("atr", "turn5"):
        assert np.array_equal(getattr(a, key)[:, :d0 + 1], getattr(b, key)[:, :d0 + 1], equal_nan=True), key
    assert fa["eligible"][:, d0].sum() >= 3 and checked == 14


def test_smoke_on_real_candles(data):
    p = _subset(data)
    P = E.Panel(p, HERE / "phase0" / "membership.json", Path(data) / "universe.json")
    f = P.screen(3)
    for setup in E.SETUPS:
        for side in (1, -1):
            df = E.pool(P, f, setup, side)
            t = df[df.ok]
            assert len(t) > 20, (setup, side, len(t))
            assert (t.entry_bar >= 3).all() and (t.exit_bar >= t.entry_bar).all() and (t.exit_bar <= 74).all()
            assert np.isfinite(t.R).all() and (t.qty >= 1).all() and (t.notional <= E.CAP_TRADE + 1e-6).all()
            assert ((t.entry - t.stop) * side > 0).all()
            if setup == "S1":
                H, L = f["H"][t.s, t.d], f["L"][t.s, t.d]
                assert (((t.entry >= H) if side > 0 else (t.entry <= L))).all()
                assert (t.entry_bar <= 26).all()
            if setup == "S3":
                assert (t.entry_bar <= 51).all()


if __name__ == "__main__":
    data = os.environ.get("N50_DATA")
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in tests:
        needs = fn.__code__.co_argcount > 0
        if needs and not data:
            print(f"skip {name} (N50_DATA not set)")
            continue
        try:
            fn(data) if needs else fn()
            print(f"ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print("all run tests passed" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
