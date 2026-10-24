"""Spot checks of strategy logic on real bars, IN-SAMPLE dates only (python xa_spotcheck.py).
Each prints a few trades next to the values that should have produced them, so a reader can
confirm by eye that the rule fired where the published rule says it should."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import xa_data
import xa_strategies as S
from xa_engine import Market, run, trades_frame

m = Market.from_bars(xa_data.load())
first, last = m.session_index("2012-01-01"), m.session_index("2014-01-01") - 1
dates = pd.to_datetime(m.d_date)


def show(title, tf, n=6):
    print(f"\n== {title}: {len(tf)} trades 2012-2013")
    for t in tf.head(n).itertuples():
        print(f"  side {t.side:+d}  in {t.entry_date} @ {t.entry_px:9.2f}  out {t.exit_date} @ {t.exit_px:9.2f}  {t.reason:<10} gross {t.gross * 100:+6.2f}%")


# 1. Faber 10-month SMA, long/cash: decided at month-end closes
p = S.faber_sma(m, 10, "long")
tf = trades_frame(m, run(m, p, first, last))
show("Faber 10-month SMA (long)", tf)
me = S.month_end_mask(m)
mc = pd.Series(m.d_c[me], index=dates[me])
sma10 = mc.rolling(10).mean()
print("  month-end close vs SMA10 around the 2012-13 turn:")
for d0 in mc["2012-08":"2013-03"].index:
    print(f"    {d0.date()}  close {mc[d0]:8.2f}  sma10 {sma10[d0]:8.2f}  -> {'long' if mc[d0] > sma10[d0] else 'cash'}")

# 2. Turtle 55/20 with 2N: entries must be at the prior 55-session high (or a gap above it)
p = S.turtle(m, 55, 20, 2.0, "long_short")
tf = trades_frame(m, run(m, p, first, last))
show("Turtle 55/20, 2N stop", tf)
hi55 = S.roll_max(m.d_h, 55)
lo55 = S.roll_min(m.d_l, 55)
for t in tf.head(4).itertuples():
    lvl = hi55[t.entry_session - 1] if t.side == 1 else lo55[t.entry_session - 1]
    print(f"    entry {t.entry_px:8.2f} vs prior 55-session {'high' if t.side == 1 else 'low'} {lvl:8.2f}  (session open {m.d_o[t.entry_session]:8.2f})")

# 3. London breakout on one day: the range hours and the order levels
tr = S.run_london_breakout(m, m.session_index("2013-03-04"), m.session_index("2013-03-08"), 2.5, True)
print(f"\n== London breakout 4-8 Mar 2013: {len(tr)} trades")
for t in tr:
    d = t.entry_session
    hs, he = m.s_start[d], m.s_end[d]
    nyh = m.h_ny_hour[hs:he]
    rng = [hs + j for j in range(he - hs) if nyh[j] in (20, 21, 22, 23, 0)]
    hi, lo = m.h_h[rng].max(), m.h_l[rng].min()
    when = pd.to_datetime(m.h_t[t.entry_hour], unit="s", utc=True).tz_convert("America/New_York")
    print(f"  {m.d_date[d]}  range {lo:.2f}-{hi:.2f} ({(hi - lo) / ((hi + lo) / 2) * 100:.2f}%)  side {t.side:+d} in {t.entry_px:.2f} at {when:%H:%M} NY  "
          f"out {t.exit_px:.2f} {t.reason}")

# 4. Bollinger squeeze default: entries only after a 125-session BandWidth low
p = S.bollinger_squeeze(m, 0.0, 20, "sar", "long_short")
tf = trades_frame(m, run(m, p, first, last))
show("Bollinger squeeze (SAR exit)", tf)

# 5. Autumn effect: trades must start at the first September / November session and end at the month's end
p = S.autumn(m, "sep_and_nov")
tf = trades_frame(m, run(m, p, first, last))
show("Autumn effect (Sep and Nov)", tf)
