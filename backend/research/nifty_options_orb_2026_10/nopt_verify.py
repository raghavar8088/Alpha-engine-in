"""Checks of the option pricing and contract rules, then invariants on the real trades.

    python -I backend/research/nifty_options_orb_2026_10/nopt_verify.py
"""

from __future__ import annotations

import csv
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C.set_calendar()
    # Black-76 and implied vol
    F, K, T, s, disc = 22500.0, 22500.0, 3 / C.SESS_PER_YEAR, 0.12, 0.999
    c, p = C.b76(F, K, T, s, True, disc), C.b76(F, K, T, s, False, disc)
    check("put-call parity: C - P = disc (F - K)", abs((c - p) - disc * (F - K)) < 1e-9, f"{c} {p}")
    K2 = 22600.0
    c2, p2 = C.b76(F, K2, T, s, True, disc), C.b76(F, K2, T, s, False, disc)
    check("put-call parity off the money", abs((c2 - p2) - disc * (F - K2)) < 1e-9)
    iv = C.implied_vol(c, F, K, T, True, disc)
    check("implied vol round trip", iv is not None and abs(iv - s) < 1e-6, str(iv))
    check("expiry value is intrinsic", C.b76(22600, 22500, 0, 0.2, True) == 100 and C.b76(22600, 22500, 0, 0.2, False) == 0)
    # clock
    k, ek = C.dk(date(2026, 10, 23)), C.dk(date(2026, 10, 27))
    saved = C.CLOCK
    C.CLOCK = "flat"
    check("flat clock: Friday 10:00 to Tuesday expiry = 0.88 + 2 + 4 nights x 0.2 = 3.68",
          abs(C.sessions_left(C.at(k, 600), ek) - 3.68) < 1e-9, str(C.sessions_left(C.at(k, 600), ek)))
    check("flat clock: expiry day 15:15 = 15/375 of a session", abs(C.sessions_left(C.at(ek, 915), ek) - 15 / 375) < 1e-9)
    C.CLOCK = "u"
    prof = C._profile()
    check("u clock: Friday 10:00 = the profile's share left at 10:00 + 2 + 0.8",
          abs(C.sessions_left(C.at(k, 600), ek) - (prof["other"][45] + 2.8)) < 1e-9, str(C.sessions_left(C.at(k, 600), ek)))
    check("u clock: expiry day 15:15 = the expiry profile's share left at 15:15",
          abs(C.sessions_left(C.at(ek, 915), ek) - prof["expiry"][360]) < 1e-9)
    check("u clock: 09:15 is a whole session, 15:30 nothing", abs(C.day_left(C.at(ek, 555), True) - 1) < 1e-9 and C.day_left(C.at(ek, 930), True) == 0)
    check("u clock: more variance is left at 14:30 than the flat clock says (afternoon), less at 10:00",
          prof["expiry"][315] > 60 / 375 and prof["other"][45] < 330 / 375)
    C.CLOCK = saved
    k19 = C.dk(date(2026, 10, 19))
    check("calendar: 20 Oct 2026 (Dussehra) is not a session", C.dk(date(2026, 10, 20)) not in C._TRADING_SET)
    check("calendar: 1 Feb 2026 (Budget Sunday) is a session", C.dk(date(2026, 2, 1)) in C._TRADING_SET)
    check("calendar: 2 Mar 2024 (DR drill) is not a full session", C.dk(date(2024, 3, 2)) not in C._TRADING_SET)
    check("sessions between Fri 16 Oct and Mon 19 Oct 2026 = 2", C.trading_sessions_between(C.dk(date(2026, 10, 16)), k19) == 2)
    # fills and charges
    check("buy fill: mid 120 -> 120 x 1.0015 + 0.05 = 120.23 -> 120.25", abs(C.buy_fill(120.0) - 120.25) < 1e-9, str(C.buy_fill(120.0)))
    check("sell fill: mid 140 -> 140 x 0.9985 - 0.05 = 139.74 -> 139.70", abs(C.sell_fill(140.0) - 139.70) < 1e-9, str(C.sell_fill(140.0)))
    check("sell fill never below one tick", C.sell_fill(0.01) == C.TICK)
    from app.services.angel_fees import option_round_trip
    fb = option_round_trip(120.0, 140.0, 1, 65, on=date(2026, 10, 23), side="BUY")
    check("charges = the app's option_round_trip", abs(C.charges(120.0, 140.0) - fb.total) < 1e-9)
    check("STT is 0.15% of the premium sold, rounded to the rupee as on a contract note",
          abs(fb.stt - round(140.0 * 65 * 0.0015)) < 0.01, str(fb.as_dict()))
    fs = option_round_trip(140.0, 120.0, 1, 65, on=date(2026, 10, 23), side="SELL")
    check("a seller pays STT on the premium it sells to open", abs(fs.stt - round(140.0 * 65 * 0.0015)) < 0.01, str(fs.as_dict()))
    # contract rule on the real listing
    from nopt_price import Pricer
    from nopt_run import Contracts
    px = Pricer()
    cons = Contracts(px)
    pk = cons.pick(C.dk(date(2026, 10, 16)), 25000.0)
    check("Fri 16 Oct 2026 -> the Mon 19 Oct expiry (Tue 20 Oct was a holiday)", pk is not None and C.kdate(pk[0]) == date(2026, 10, 19), str(pk))
    pk = cons.pick(k19, 25000.0)
    check("expiry day 19 Oct 2026 -> that day's contract (0DTE)", pk is not None and C.kdate(pk[0]) == date(2026, 10, 19), str(pk))
    pk = cons.pick(C.dk(date(2023, 6, 23)), 18700.0)
    check("Fri 23 Jun 2023 -> Wed 28 Jun 2023 (Thu 29 Jun was Bakri Id)", pk is not None and C.kdate(pk[0]) == date(2023, 6, 28), str(pk))
    pk = cons.pick(C.dk(date(2022, 1, 10)), 18000.0)
    check("Mon 10 Jan 2022 -> Thu 13 Jan 2022 (Thursday weeklies)", pk is not None and C.kdate(pk[0]) == date(2022, 1, 13), str(pk))
    # invariants on the real trades, both sides
    for side in ("buy", "sell"):
        for rr in (2, 3, 4, 5, 6):
            path = C.RES / f"trades_{side}_rr_1_{rr}.csv"
            if not path.exists():
                continue
            tr = list(csv.DictReader(open(path, encoding="utf-8")))
            lab = f"{side} 1:{rr}"
            days = {}
            for t in tr:
                days[t["date"]] = days.get(t["date"], 0) + 1
            check(f"{lab}: at most one trade a day", max(days.values()) == 1)
            check(f"{lab}: calls on upside breaks, puts on downside",
                  all((t["option"] == "CALL") == (float(t["or_stop"]) < float(t["nifty_in"])) for t in tr))
            check(f"{lab}: strike within 25 points of NIFTY at entry", all(abs(float(t["strike"]) - float(t["nifty_in"])) <= 25.01 for t in tr))
            check(f"{lab}: expiry on or after the trade day, within 7 days",
                  all(0 <= (date.fromisoformat(t["expiry"]) - date.fromisoformat(t["date"])).days <= 7 for t in tr))
            check(f"{lab}: the anchor smile is from an earlier session", all(t["anchor"] < t["date"] for t in tr))
            check(f"{lab}: entries 09:30-14:59, exits by 15:15", all("09:30" <= t["entry_time"] <= "14:59" and t["exit_time"] <= "15:15" for t in tr))
            check(f"{lab}: net = gross - charges", all(abs(float(t["net"]) - (float(t["gross"]) - float(t["charges"]))) < 0.02 for t in tr))
            if side == "buy":
                ok = all((float(t["fill_in"]) > float(t["mid_in"])) and (float(t["fill_out"]) < float(t["mid_out"]) or float(t["fill_out"]) == C.TICK) for t in tr)
                check(f"{lab}: bought above the mid, sold below it", ok)
            else:
                ok = all((float(t["fill_in"]) < float(t["mid_in"]) or float(t["fill_in"]) == C.TICK) and float(t["fill_out"]) > float(t["mid_out"]) for t in tr)
                check(f"{lab}: sold below the mid, bought back above it", ok)
                check(f"{lab}: margin blocked on every short (Rs50k-4L a lot)", all(50_000 < float(t["capital"]) < 400_000 for t in tr))
    bpath, spath = C.RES / "trades_buy_rr_1_2.csv", C.RES / "trades_sell_rr_1_2.csv"
    if bpath.exists() and spath.exists():
        b = {t["date"]: t for t in csv.DictReader(open(bpath, encoding="utf-8"))}
        s_ = {t["date"]: t for t in csv.DictReader(open(spath, encoding="utf-8"))}
        same = all(b[d]["strike"] == s_[d]["strike"] and b[d]["expiry"] == s_[d]["expiry"] and b[d]["entry_time"] == s_[d]["entry_time"]
                   and b[d]["exit_time"] == s_[d]["exit_time"] for d in b)
        check("mirror: the seller trades the buyer's exact contract at the buyer's exact minutes", same and set(b) == set(s_))
        check("mirror: before costs the seller earns exactly what the buyer loses",
              all(abs(float(b[d]["before_costs"]) + float(s_[d]["before_costs"])) < 0.02 for d in b))
    print()
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
