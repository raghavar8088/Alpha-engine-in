"""The intraday shape of the variance clock, from NIFTY's own 1-minute moves (2021-10-25 .. 2023-12-31).

    python -I backend/research/nifty_options_orb_2026_10/nopt_clock.py

The first model ran the clock FLAT through the session (every minute 1/375 of a day). The recorded
quotes then showed it overpricing expiry-day options at 09:30 by ~7% and decaying them too fast in the
afternoon. NIFTY's variance is not flat: the 09:15 minute alone carries ~6% of a day's, the morning more
than its share, the middle of the day less, and the last 90 minutes more. So a minute now counts for its
share of the day's variance: the mean squared 1-minute return at that minute of the day, on 2021-23
sessions only (no option prices and none of the later data used), separately for weekly-expiry days and
other days. A whole session is still 1 and a night still 0.2, so prices at the close do not change.

Output: data/clock_profile.json  {"expiry": [376 cumulative remaining shares], "other": [...], ...}
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402

FROM, TO = "2021-10-25", "2023-12-31"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    z = np.load(C.DATA / "minutes.npz")
    days = [str(d) for d in z["days"]]
    with gzip.open(C.DATA / "listing.json.gz", "rt") as f:
        lst = json.load(f)
    expiries = {int(e) for s in lst.values() for e in s}
    o, c, pres = z["o"], z["c"], z["present"]
    sel = [i for i, d in enumerate(days) if FROM <= d <= TO and pres[i].all()]
    r = np.zeros((len(sel), 375))
    for j, i in enumerate(sel):
        r[j, 0] = np.log(c[i, 0] / o[i, 0])
        r[j, 1:] = np.diff(np.log(c[i]))
    is_exp = np.array([C.dk(date.fromisoformat(days[i])) in expiries for i in sel])
    out = {"from": FROM, "to": TO}
    for lab, m in (("expiry", is_exp), ("other", ~is_exp)):
        v = (r[m] ** 2).mean(axis=0)
        w = v / v.sum()
        rem = np.r_[np.cumsum(w[::-1])[::-1], 0.0]          # rem[m] = share of the day's variance from minute m on
        out[lab] = [round(float(x), 6) for x in rem]
        out[lab + "_sessions"] = int(m.sum())
        print(f"{lab}: {int(m.sum())} sessions; remaining at 09:30 {rem[15]:.3f} (flat 0.960), 12:00 {rem[165]:.3f} (0.560), "
              f"14:30 {rem[315]:.3f} (0.160), 15:00 {rem[345]:.3f} (0.080)")
    with open(C.DATA / "clock_profile.json", "w", encoding="utf-8") as f:
        json.dump(out, f)
    with open(C.RES / "clock_profile.json", "w", encoding="utf-8") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
