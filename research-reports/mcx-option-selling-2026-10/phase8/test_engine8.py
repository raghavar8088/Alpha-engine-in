"""Checks for engine8: synthetic days with known answers, plus spot checks on the real bars.

    python test_engine8.py <bars.csv.gz>
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine8 as E8  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    fails += 0 if cond else 1


def synth(day, rows, expiry="2026-11-19"):
    """rows: list of (HH:MM, o, h, l, c)."""
    g = pd.DataFrame([{"ts": pd.Timestamp(f"{day} {hm}"), "open": o, "high": h, "low": l, "close": c, "volume": 100}
                      for hm, o, h, l, c in rows])
    return E8.Day(pd.Timestamp(day), pd.Timestamp(expiry), g)


slip = 1.0
# 1. ORB: range 100-101; the 09:30 bar breaks up at 101; a later bar falls through 100 -> stopped at 100 - slip
d = synth("2026-10-01", [("09:00", 100.5, 101, 100, 100.5), ("09:05", 100.5, 100.8, 100.2, 100.6), ("09:10", 100.6, 100.9, 100.3, 100.7),
                         ("09:15", 100.7, 100.9, 100.4, 100.8), ("09:20", 100.8, 100.95, 100.5, 100.9), ("09:25", 100.9, 100.95, 100.6, 100.9),
                         ("09:30", 100.9, 101.6, 100.8, 101.5), ("09:35", 101.5, 101.7, 100.9, 101.0), ("09:40", 99.8, 99.9, 99.5, 99.6)])
t = E8.s_orb([d], slip, "09:00", "09:30", "09:30", 6)
check("ORB long at the range high + slip", len(t) == 1 and t[0]["side"] == 1 and t[0]["entry"] == 101 + slip)
check("ORB stop fills at the open when the bar gaps through", t[0]["exit"] == 99.8 - slip and t[0]["reason"] == "stop",
      f"(exit {t[0]['exit']})")
check("ORB net = side x (exit - entry)/entry - cost", abs(t[0]["net"] - ((99.8 - 1 - 102) / 102 - E8.COST)) < 1e-12)
# 2. a bar spanning both sides of the range: the worse order is assumed (entered and stopped in one bar)
d2 = synth("2026-10-02", [(f"09:{m:02d}", 100.5, 101, 100, 100.5) for m in range(0, 30, 5)] + [("09:30", 100.9, 101.5, 99.5, 100.0)])
t = E8.s_orb([d2], slip, "09:00", "09:30", "09:30", 6)
check("both-sides bar = stopped in the same bar", len(t) == 1 and t[0]["reason"] == "stop" and t[0]["net"] < 0)
# 3. stop is assumed before target when one bar could hit both
d3 = synth("2026-10-03", [("09:00", 100, 100, 100, 100), ("09:05", 100, 103, 97, 100)])
px, j, why = E8.run_exit(d3, 1, 1, 100.0, 0.0, stop=98.0, target=102.0)
check("stop before target in the same bar", why == "stop" and px == 98.0)
# 4. RSI(2) by hand (Wilder smoothing)
c = np.array([10, 11, 10.5, 12, 11.0])
r = E8.rsi2(c)
ag, al = 1.0, 0.0
ag, al = (ag + 0) / 2, (al + 0.5) / 2
want2 = 100 - 100 / (1 + ag / al)
ag, al = (ag + 1.5) / 2, (al + 0) / 2
want3 = 100 - 100 / (1 + ag / al)
check("RSI(2) by hand", abs(r[2] - want2) < 1e-12 and abs(r[3] - want3) < 1e-12, f"({r[2]:.3f} vs {want2:.3f})")
# 5. intraday momentum reads only bars before the entry bar
rows = [(f"{h:02d}:{m:02d}", 100, 100.2, 99.8, 100) for h in range(9, 24) for m in range(0, 60, 5) if (h, m) <= (23, 25)]
d5 = synth("2026-10-05", rows)
k = d5.idx("22:25")
d5.c[k - 1] = 101.0
base = E8.s_momlh([d5], slip, "09:00")
d5.c[k:] = 50.0                                      # change only the future
after = E8.s_momlh([d5], slip, "09:00")
check("momentum decision ignores the future", base[0]["side"] == after[0]["side"] == 1 and base[0]["entry"] == after[0]["entry"])
# 6. real bars: LONG-DAY by hand on a real session
b = E8.load(sys.argv[1])
days = E8.sessions(b, "CRUDEOIL", "5m")
dd = days[len(days) // 2]
t = E8.s_long([dd], 1.0, "09:00")[0]
want = (dd.c[-1] - 1 - (dd.o[0] + 1)) / (dd.o[0] + 1) - E8.COST
check("real LONG-DAY by hand", abs(t["net"] - want) < 1e-12 and dd.hm[0] == "09:00" and dd.hm[-1] == "23:25",
      f"({dd.day.date()}, {len(dd.o)} bars)")
# 7. one contract per day, every kept day >= 90% of a session
check("one contract per day", all(len(set([x.expiry])) == 1 for x in days))
check("kept days are >= 90% complete", all(len(x.o) >= 157 for x in days))
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
