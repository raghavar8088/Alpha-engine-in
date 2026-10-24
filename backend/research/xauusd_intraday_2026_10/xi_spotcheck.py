"""Spot checks of the intraday rules on real minutes, IN-SAMPLE dates only (python xi_spotcheck.py):
each prints a few trades with their New York entry/exit times and the levels that produced them."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import xi_data
import xi_strategies as S
from xi_engine import trades_frame

D = xi_data.load()
C = S.Context(D)
sd = D["sess_date"]
a = int(np.searchsorted(sd, np.datetime64("2019-03-04")))
b = int(np.searchsorted(sd, np.datetime64("2019-03-09"))) - 1


def ny(i):
    return pd.Timestamp(int(D["t"][i]), unit="s", tz="UTC").tz_convert("America/New_York").strftime("%a %H:%M")


def show(title, rows):
    tf = trades_frame(D, rows)
    print(f"\n== {title}: {len(tf)} trades 4-8 Mar 2019")
    for t in tf.itertuples():
        print(f"  {t.date} side {t.side:+d} in {ny(t.ei)} @ {t.ep:8.3f}  out {ny(t.xi)} @ {t.xp:8.3f}  {t.reason:<6} gross {t.gross * 100:+.3f}%")


days = range(a, b + 1)
show("ORB first 5-minute bar, COMEX open, 10R, flat 16:59", S.orb_first_bar(D, C, days, "comex", 5, "10R", "end"))
d0 = a + 1
i0 = S.at(D, d0, S.T["comex"])
print(f"   check {sd[d0]}: 08:20 open {D['o'][i0]:.3f}, 08:24 close {D['c'][i0 + 4]:.3f}, range {D['l'][i0:i0 + 5].min():.3f}-{D['h'][i0:i0 + 5].max():.3f}, "
      f"minute {ny(i0)}")
show("Crabel, COMEX open, k=1, opposite stop", S.crabel(D, C, days, "comex", 1.0, "opposite"))
o, st = C.comex_anchor()
print(f"   stretch {sd[d0]}: {st[d0]:.3f} (10 earlier sessions' mean of min(H-O, O-L) from 08:20)")
show("London breakout (published)", S.london_breakout(D, C, days, 2.5, True, True))
show("Intraday momentum, COMEX day", S.intraday_momentum(D, C, days, "comex", "first"))
show("London PM fix, 2 minutes", S.london_fix(D, C, days, "pm", 2))
show("Pivots fade, London+NY", S.pivots(D, C, days, "fade", "london_ny"))
print(f"   pivots {sd[d0]}: P {C.pivot['P'][d0]:.2f} R1 {C.pivot['R1'][d0]:.2f} S1 {C.pivot['S1'][d0]:.2f} "
      f"(prev session H {D['d_h'][d0 - 1]:.2f} L {D['d_l'][d0 - 1]:.2f} C {D['d_c'][d0 - 1]:.2f})")
show("Bollinger 15m reversion", S.bb_intraday(D, C, days, 15, 2.0, "long_short"))
nf = sorted(str(x) for x in S.NFP if str(x).startswith("2019"))
print("\nNFP 2019 by the BLS rule:", nf)
a2, b2 = int(np.searchsorted(sd, np.datetime64("2019-01-01"))), int(np.searchsorted(sd, np.datetime64("2019-04-30")))
show("NFP straddle Jan-Apr 2019", S.nfp(D, C, range(a2, b2), "straddle", "end", "none"))
