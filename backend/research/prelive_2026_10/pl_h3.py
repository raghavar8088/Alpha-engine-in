"""H3: buying volatility around scheduled events, on history (2024-10..2026-10).

Events (official schedules: RBI press releases, federalreserve.gov, bls.gov):
  RBI policy decisions, announced ~10:00 IST on the session itself
  FOMC decisions, ~23:30/00:30 IST -> the next Indian session reacts
  US CPI releases, 18:00/19:00 IST -> the next Indian session reacts
Trades (pre-specified, ATM straddle of next week's expiry, priced with the calibrated model:
clock = trading minutes + 0.2 session a night, IV = VIX x 0.888, spread 0.5 pt a leg a side,
Angel rate card), each compared with the SAME trade on all other days:
  US events  bought 15:15 on the US release date's Indian session, sold 09:30 next session
  RBI        bought 09:20, sold 11:00 (around the announcement) and, separately, sold 15:15
Also the realized move itself: |09:15->15:15| and the overnight gap on event days vs others.
"""
import math
import statistics
import sys
from bisect import bisect_right
from datetime import date, datetime, timedelta

sys.argv = sys.argv[:1]
import pl_h1 as H  # noqa: E402
from pl_replay import IST, LOT, N5, TD, bs, expiry_key, fees, kdate, n5t  # noqa: E402

RBI = ["2024-10-09", "2024-12-06", "2025-02-07", "2025-04-09", "2025-06-06", "2025-08-06", "2025-10-01", "2025-12-05",
       "2026-02-06", "2026-04-08", "2026-06-05", "2026-08-05"]
FOMC = ["2024-11-07", "2024-12-18", "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
        "2025-10-29", "2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"]
CPI = ["2024-10-10", "2024-11-13", "2024-12-11", "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
       "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-12-18", "2026-01-13", "2026-02-13",
       "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11"]
TDK = sorted(TD)
TDKS = set(TDK)


def k_of(iso):
    return (date.fromisoformat(iso) - date(1970, 1, 1)).days


def session_on_or_before(k):
    while k not in TDKS and k > TDK[0]:
        k -= 1
    return k if k in TDKS else None


def next_session(k):
    i = bisect_right(TDK, k)
    return TDK[i] if i < len(TDK) else None


def spot(e):
    i = bisect_right(n5t, e - 300) - 1
    return N5[i][4] if i >= 0 else None


def straddle(k_buy, hm_buy, k_sell, hm_sell):
    t0 = datetime.combine(kdate(k_buy), datetime.min.time()).replace(hour=hm_buy[0], minute=hm_buy[1], tzinfo=IST)
    t1 = datetime.combine(kdate(k_sell), datetime.min.time()).replace(hour=hm_sell[0], minute=hm_sell[1], tzinfo=IST)
    S0, S1 = spot(int(t0.timestamp())), spot(int(t1.timestamp()))
    v0, v1 = H.V.vix_at(int(t0.timestamp())), H.V.vix_at(int(t1.timestamp()))
    if not (S0 and S1 and v0 and v1):
        return None
    xk = expiry_key(k_buy, plus_week=True)
    exp = datetime.combine(kdate(xk), datetime.min.time()).replace(hour=15, minute=30, tzinfo=IST)
    K = round(S0 / 50) * 50
    T0, T1 = H.T_clock(t0, exp), H.T_clock(t1, exp)
    c0, p0 = bs(S0, K, T0, v0 * H.RATIO, True), bs(S0, K, T0, v0 * H.RATIO, False)
    c1, p1 = bs(S1, K, T1, v1 * H.RATIO, True), bs(S1, K, T1, v1 * H.RATIO, False)
    net = (c1 + p1 - c0 - p0 - 4 * H.SPREAD_PTS) * LOT - fees(c0, c1) - fees(p0, p1)
    return net, abs(S1 / S0 - 1) * 1e4


def summarize(lab, ev, base):
    ev = [x for x in ev if x is not None]
    base = [x for x in base if x is not None]
    me, mb = statistics.mean(x[0] for x in ev), statistics.mean(x[0] for x in base)
    se = math.sqrt(statistics.variance([x[0] for x in ev]) / len(ev) + statistics.variance([x[0] for x in base]) / len(base))
    print(f"  {lab}: events n {len(ev)} net {me:+6.0f} (|move| {statistics.median(x[1] for x in ev):.0f} bp) | "
          f"other days n {len(base)} net {mb:+6.0f} (|move| {statistics.median(x[1] for x in base):.0f} bp) | "
          f"difference {me - mb:+6.0f}, t {(me - mb) / se:+.2f}; events positive {sum(1 for x in ev if x[0] > 0)}/{len(ev)}")


# US events: overnight straddle from the US date's Indian session
us_k = {}
for lab, dates in (("FOMC", FOMC), ("CPI", CPI)):
    ks = set()
    for d in dates:
        k = session_on_or_before(k_of(d))
        if k is not None and next_session(k) is not None:
            ks.add(k)
    us_k[lab] = ks
print("US EVENTS (overnight straddle 15:15 -> 09:30 next session):")
all_on = {k: straddle(k, (15, 15), next_session(k), (9, 30)) for k in TDK[:-1] if next_session(k)}
for lab in ("FOMC", "CPI"):
    ev = [all_on.get(k) for k in us_k[lab]]
    base = [v for k, v in all_on.items() if k not in us_k["FOMC"] | us_k["CPI"]]
    summarize(lab, ev, base)
both = us_k["FOMC"] | us_k["CPI"]
summarize("FOMC+CPI", [all_on.get(k) for k in both], [v for k, v in all_on.items() if k not in both])

print("RBI DECISION DAYS:")
rbi_k = {k_of(d) for d in RBI if k_of(d) in TDKS}
for lab, sell in (("09:20 -> 11:00", (11, 0)), ("09:20 -> 15:15", (15, 15))):
    allx = {k: straddle(k, (9, 20), k, sell) for k in TDK}
    summarize(lab, [allx.get(k) for k in rbi_k], [v for k, v in allx.items() if k not in rbi_k])
print("event counts in the bar history:", {"RBI": len(rbi_k), "FOMC": len(us_k["FOMC"]), "CPI": len(us_k["CPI"])})
