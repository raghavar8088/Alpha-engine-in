"""The Gold Lab: its live rules are the research's rules, and its book does honest arithmetic.

Run:  python backend/tests/gold_desk/verify_gold_lab.py

PARITY   gold_lab_rules.targets() against backend/research/gold_lab_2026_10/gl_families.py on
         the research's own GLD / UUP / TIP / S&P 500 history, 2004-2026, every strategy, every
         day. Needs the research data (gl_fetch.py); skipped, and said so, without it.
BOOK     sizing, rebalancing (average price, realised P&L on a cut and on a flip), fees, funding
         signs, when a decision may be taken and when it may be executed (the next New York open
         of an NYSE session — never on a holiday, never before the open), and the fail-closed
         paths. No Mongo, no network.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Coll, check, finish, section  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.services import gold_lab_rules as R  # noqa: E402

asyncio.set_event_loop(asyncio.new_event_loop())


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════════════════
section("PARITY — the live rules are the research's rules (2004-2026, every day)")

LAB = ROOT / "backend" / "research" / "gold_lab_2026_10"
if not (LAB / "data" / "GLD_1d.csv.gz").exists():
    print("  SKIP  research data not present (run gl_fetch.py) — parity not checked here")
else:
    sys.path.insert(0, str(LAB))
    import gl_families as GF  # noqa: E402
    from gl_engine import market  # noqa: E402

    m = market("GLD")
    ctx = GF.Ctx(m)
    closes = pd.DataFrame({"gld": m.close,
                           "uup": market("UUP", on=m.dates).close,
                           "tip": market("TIP", on=m.dates).close,
                           "spx": market("SPX", on=m.dates).close}, index=m.dates)
    port = R.targets(closes)
    research = {
        "gl1": GF.multi_signal({"scale": 1.5, "tom": True}, ctx),
        "gl2": GF.macro_residual({"H": 10, "z0": 2.0}, ctx),
        "gl3": GF.trend_plus_shock({"w_shock": 1.0, "w_trend": 1.0}, ctx),
        "gl4": GF.trend_plus_shock({"w_shock": 0.5, "w_trend": 1.0}, ctx),
        "gl5": GF.tsmom({"L": 126, "mode": "long_flat", "tv": 0.15}, ctx),
        "gl6": GF.shock_stop({"k": 2.0}, ctx),
        "gl7": GF.reversal({"k": 3.0, "H": 5, "dir": "cont"}, ctx),
    }
    for sid, ref in research.items():
        diff = float(np.max(np.abs(np.asarray(ref, float) - port[sid].to_numpy())))
        active = int((np.abs(np.asarray(ref, float)) > 0).sum())
        check(f"{sid} matches the research rule on all {len(ref):,} days", diff < 1e-12,
              f"max |diff| {diff:.1e}; in the market on {active:,} days")
    # the live window: computed on the last 5 years only, the recent targets are unchanged
    tail = closes.iloc[-1260:]
    port_tail = R.targets(tail)
    worst = 0.0
    for sid in R.LAB_IDS:
        worst = max(worst, float(np.max(np.abs(port_tail[sid].iloc[-250:].to_numpy() - port[sid].iloc[-250:].to_numpy()))))
    check("a 5-year window gives the same targets for the last year as the full history", worst < 1e-9, f"{worst:.1e}")

# ═════════════════════════════════════════════════════════════════════════════════
section("CALENDAR — NYSE sessions, the month-turn's future, failing closed")

check("NYSE holidays are not sessions; weekends are not either",
      not R.is_nyse_day(date(2026, 11, 26)) and not R.is_nyse_day(date(2026, 12, 25))
      and not R.is_nyse_day(date(2026, 10, 10)) and R.is_nyse_day(date(2026, 10, 12)))
check("the next session skips a weekend and a holiday",
      R.next_nyse_day(date(2026, 11, 25)) == date(2026, 11, 27) and R.next_nyse_day(date(2026, 10, 9)) == date(2026, 10, 12))
check("observed holidays: July 4th 2026 (Saturday) closes Friday the 3rd; 2027's Christmas closes the 24th",
      not R.is_nyse_day(date(2026, 7, 3)) and not R.is_nyse_day(date(2027, 12, 24)))
check("past the calendar's end the lab knows it does not know", not R.calendar_known(date(2029, 1, 2)))
dts = pd.DatetimeIndex(pd.to_datetime([d.isoformat() for d in R.nyse_days(date(2026, 10, 1), date(2026, 10, 28))]))
fut = R.nyse_days(date(2026, 10, 29), date(2026, 11, 10))
tom = R.turn_of_month(dts, fut)
# Oct 2026 sessions end Fri 30th: the last two are 29 and 30; a target set at the close of the
# 28th is for the 29th — inside the turn — and only the future calendar can say so
check("the month-turn target at the last known day uses the NYSE calendar ahead of it",
      tom[-1] == 1.0 and tom[-2] == 0.0, list(tom[-3:]))

# ═════════════════════════════════════════════════════════════════════════════════
section("BOOK — sizing, rebalancing, fees, funding, timing")

from app.services import gold_delta_feed as F  # noqa: E402
from app.services import gold_lab as L  # noqa: E402

state_c, hold_c, fill_c, eq_c = Coll("state"), Coll("holdings"), Coll("fills"), Coll("equity")
L.state_coll, L.holdings_coll, L.fills_coll, L.equity_coll = state_c, hold_c, fill_c, eq_c
SPEC = {"contract_value": 0.001, "taker_fee_rate": 0.0001, "funding_interval_s": 14400}


async def prod(sym):
    return dict(SPEC)
F.product = prod

PX = {"bid": 3999.5, "ask": 4000.5}


async def fp(sym, side, n):
    return {"price": PX["ask"] if side == "BUY" else PX["bid"], "basis": "touch", "spread_bp": 2.5,
            "bid": PX["bid"], "ask": PX["ask"], "mid": (PX["bid"] + PX["ask"]) / 2}
F.fill_price = fp


async def tick(sym):
    return {"bid": PX["bid"], "ask": PX["ask"], "mid": (PX["bid"] + PX["ask"]) / 2, "mark": (PX["bid"] + PX["ask"]) / 2}
F.ticker = tick


async def mark(sym):
    return (PX["bid"] + PX["ask"]) / 2
F.mark_price = mark
F.funding_series = lambda s: asyncio.sleep(0, result=[])

sleeve = L.CAPITAL / len(R.LAB_IDS)
n = L.contracts_for(0.75, sleeve, 4000.0, 0.001)
check("a target of 0.75 of a sleeve buys round(0.75 x sleeve / contract) whole contracts",
      n == round(0.75 * sleeve / 4.0), n)
check("a short target is a negative contract count", L.contracts_for(-1.0, sleeve, 4000.0, 0.001) < 0)

h = {"sid": "gl5", "contracts": 0, "avg_price": 0.0, "realized": 0.0, "fees": 0.0, "funding": 0.0}
h = L.apply_fill(h, 100, 4000.0, 0.001, 0.0001)
check("opening: average price is the fill, fee = notional x rate x 1.18",
      h["contracts"] == 100 and h["avg_price"] == 4000.0 and abs(h["fees"] - 100 * 0.001 * 4000 * 0.0001 * 1.18) < 1e-12)
h = L.apply_fill(h, 100, 4100.0, 0.001, 0.0001)
check("adding at a higher price averages up", abs(h["avg_price"] - 4050.0) < 1e-9 and h["contracts"] == 200)
h = L.apply_fill(h, -50, 4150.0, 0.001, 0.0001)
check("cutting realises (exit - average) on the part sold, the average unchanged",
      abs(h["realized"] - 50 * 0.001 * 100.0) < 1e-9 and abs(h["avg_price"] - 4050.0) < 1e-9 and h["contracts"] == 150)
h = L.apply_fill(h, -250, 4000.0, 0.001, 0.0001)
check("a flip closes the whole long at the fill and opens the remainder short at it",
      h["contracts"] == -100 and abs(h["avg_price"] - 4000.0) < 1e-9
      and abs(h["realized"] - (50 * 0.001 * 100.0 + 150 * 0.001 * (4000.0 - 4050.0))) < 1e-9)
h2 = L.apply_fill(dict(h), 100, 3900.0, 0.001, 0.0001)
check("covering a short below its average is a gain", h2["contracts"] == 0 and h2["realized"] > h["realized"])

paid = L.funding_due(150, 0.001, 4000.0, 0.005)
check("funding: a long pays rate% of notional at an exchange, a short receives it",
      abs(paid - 150 * 0.001 * 4000.0 * 0.005 / 100) < 1e-12 and L.funding_due(-150, 0.001, 4000.0, 0.005) < 0)

NY = L.NY
fri_close = datetime(2026, 10, 9, 16, 50, tzinfo=NY)            # Friday after the close
sat = datetime(2026, 10, 10, 12, 0, tzinfo=NY)
mon_pre = datetime(2026, 10, 12, 9, 15, tzinfo=NY)
mon_open = datetime(2026, 10, 12, 9, 36, tzinfo=NY)
check("a decision is due after 16:30 New York on a session day, not before",
      L.decision_due(fri_close, date(2026, 10, 9)) and not L.decision_due(datetime(2026, 10, 9, 15, 0, tzinfo=NY), date(2026, 10, 9)))
check("…and only on the bar of THAT session (a stale bar decides nothing)",
      not L.decision_due(fri_close, date(2026, 10, 8)))
check("execution waits for the next session's open: not on Saturday, not before 09:35 Monday",
      L.execution_due(sat, date(2026, 10, 9)) is False and L.execution_due(mon_pre, date(2026, 10, 9)) is False
      and L.execution_due(mon_open, date(2026, 10, 9)) is True)
thanks = datetime(2026, 11, 26, 9, 40, tzinfo=NY)
check("Thanksgiving is not the next open — the Friday after it is",
      L.execution_due(thanks, date(2026, 11, 25)) is False
      and L.execution_due(datetime(2026, 11, 27, 9, 40, tzinfo=NY), date(2026, 11, 25)) is True)
check("an execution missed by more than a session is skipped, not done late",
      L.execution_due(datetime(2026, 10, 13, 9, 40, tzinfo=NY), date(2026, 10, 9)) == "stale")

# a whole decision -> execution round on the in-memory book
closes = pd.DataFrame({"gld": 100 * np.exp(np.cumsum(np.r_[0, np.full(299, 0.002)])),
                       "uup": 25.0, "tip": 110.0, "spx": 5000.0},
                      index=pd.DatetimeIndex(pd.to_datetime([d.isoformat() for d in
                                                             R.nyse_days(date(2025, 8, 1), date(2026, 10, 9))][-300:])))
state_c.docs.append({"_id": "lab", "enabled": True})
dec = run(L.decide(closes, now=fri_close))
check("a decision stores every strategy's target for the bar it was computed on",
      dec["bar_date"] == "2026-10-09" and set(dec["targets"]) == set(R.LAB_IDS) and dec["targets"]["gl5"] > 0, dec.get("targets"))
again = run(L.decide(closes, now=fri_close + timedelta(minutes=5)))
check("…once per bar: deciding again changes nothing", again.get("unchanged") is True)
ex0 = run(L.execute(now=mon_pre))
check("before the open nothing is executed", ex0.get("executed") is False)
ex = run(L.execute(now=mon_open))
hl = {d["sid"]: d for d in hold_c.docs}
check("at the open each strategy is rebalanced to its target at the touch",
      ex.get("executed") is True and hl["gl5"]["contracts"] == L.contracts_for(dec["targets"]["gl5"], sleeve, 4000.0, 0.001)
      and all(f["price"] == PX["ask"] for f in fill_c.docs if f["contracts"] > 0))
n_fills = len(fill_c.docs)
ex2 = run(L.execute(now=mon_open + timedelta(minutes=10)))
check("…once: a second pass trades nothing", ex2.get("executed") is False and len(fill_c.docs) == n_fills)
check("the long fills paid the ask, and every fill carries its fee", all(f["fee"] > 0 for f in fill_c.docs))

async def nofee(sym):
    return {**SPEC, "taker_fee_rate": None}
F.product = nofee
state_c.docs = [d for d in state_c.docs if d["_id"] != "lab:decision"]
run(L.decide(closes.iloc[:-1], now=datetime(2026, 10, 8, 16, 50, tzinfo=NY)))
before = len(fill_c.docs)
exn = run(L.execute(now=datetime(2026, 10, 9, 9, 40, tzinfo=NY)))
check("no published fee: nothing is traded (fail closed)", exn.get("executed") is False and len(fill_c.docs) == before, exn)
F.product = prod

finish()
