"""Acceptance checks for the option-SELLING engine (options_selling_backtest.py).

Every check below is a claim that has to hold for the desk's numbers to mean anything.
They run on CONTROLLED inputs wherever possible, because on live market data a pricing
bug and a bad strategy produce the same thing — a losing equity curve — and only
constructed tapes can tell them apart.

Three of these checks exist because they already caught real bugs during the build:
  * wing anchoring (section 3) — wings were anchored to spot, so a delta-selected short
    gave every trade a different, unpredictable spread width and max loss.
  * ATM strike pressure (section 5/6) — the strike-proximity exit fired on the entry bar
    of every ATM structure, closing all 13 of the expiry straddle's trades after one bar.
  * the P&L identity (section 6) — the only check that would catch a sign error in
    credit-vs-buyback accounting, which is the single easiest thing to get backwards in
    a selling engine.

Run it from the repo root:
    python options-service/verify_selling_engine.py

Bars come from Mongo via the normal loader. For an offline run, point NIFTY_BAR_DUMP at
a jsonl(.gz) export of the bars collection and no database is needed.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path[:0] = ["shared", "strategy-service", "options-service", "backtesting-service"]

from options_service.greeks import black_scholes_price  # noqa: E402
from options_service.margin import estimate_margin  # noqa: E402
from options_service.options_backtest import Leg, _structure_value  # noqa: E402
from options_service.options_selling_backtest import (  # noqa: E402
    materialize_legs,
    run_options_selling_backtest,
    strike_for_delta,
)
from strategy_service.strategies.options_selling._base import LegSpec  # noqa: E402
from tradingai_shared.domain import Bar, Timeframe, TransactionType  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


def make_bars(closes, start=datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc), minutes=15):
    """Intraday bars with a small high/low envelope, one session per 25 bars."""
    bars = []
    ts = start
    for i, c in enumerate(closes):
        bars.append(Bar(
            symbol="NIFTY", timeframe=Timeframe.M15, ts=ts,
            open=c, high=c * 1.0008, low=c * 0.9992, close=c, volume=0,
        ))
        ts += timedelta(minutes=minutes)
        if (i + 1) % 25 == 0:
            ts = ts.replace(hour=9, minute=15) + timedelta(days=1)
    return bars


print("\n1. Black-Scholes leg pricing and structure value signs")
spot, t, sig = 25000.0, 7 / 365, 0.12
short_ce = Leg("CE", 25300, TransactionType.SELL)
long_ce = Leg("CE", 25600, TransactionType.BUY)
c_short = black_scholes_price(spot, 25300, t, "CE", sigma=sig)
c_long = black_scholes_price(spot, 25600, t, "CE", sigma=sig)
check("nearer short call is worth more than the further long call", c_short > c_long,
      f"{c_short:.2f} vs {c_long:.2f}")
credit = _structure_value([short_ce, long_ce], spot, t, sig)
check("bear call spread produces a net CREDIT", credit > 0, f"credit {credit:.2f}/unit")
check("credit is less than the spread width", credit < 300, f"{credit:.2f} < 300")

print("\n2. Delta-based strike selection")
k15 = strike_for_delta(spot, t, sig, "CE", 0.15, 50.0)
k30 = strike_for_delta(spot, t, sig, "CE", 0.30, 50.0)
check("15-delta call strikes further OTM than the 30-delta", k15 > k30, f"{k15} vs {k30}")
k_hi = strike_for_delta(spot, t, 0.25, "CE", 0.15, 50.0)
check("higher volatility pushes the same delta further out", k_hi > k15, f"{k_hi} @25% vs {k15} @12%")
kp = strike_for_delta(spot, t, sig, "PE", 0.15, 50.0)
check("15-delta put strikes below spot", kp < spot, f"{kp} < {spot}")

print("\n3. Wing anchoring (wings hang off the short leg, not off spot)")
specs = [
    LegSpec("CE", sell=True, target_delta=0.15), LegSpec("CE", sell=False, wing_pct=0.01),
    LegSpec("PE", sell=True, target_delta=0.15), LegSpec("PE", sell=False, wing_pct=0.01),
]
legs = materialize_legs(specs, spot, t, sig, 50.0)
sce = next(l.strike for l in legs if l.option_type == "CE" and l.direction == TransactionType.SELL)
lce = next(l.strike for l in legs if l.option_type == "CE" and l.direction == TransactionType.BUY)
spe = next(l.strike for l in legs if l.option_type == "PE" and l.direction == TransactionType.SELL)
lpe = next(l.strike for l in legs if l.option_type == "PE" and l.direction == TransactionType.BUY)
check("call wing sits above its short call", lce > sce, f"{sce} -> {lce}")
check("put wing sits below its short put", lpe < spe, f"{spe} -> {lpe}")
width_hi = materialize_legs(specs, spot, t, 0.30, 50.0)
w_lo, w_hi = lce - sce, (
    next(l.strike for l in width_hi if l.option_type == "CE" and l.direction == TransactionType.BUY)
    - next(l.strike for l in width_hi if l.option_type == "CE" and l.direction == TransactionType.SELL)
)
check("wing width stays stable when volatility changes", abs(w_lo - w_hi) <= 50,
      f"{w_lo} pts @12% vs {w_hi} pts @30%")

print("\n4. Margin model")
naked = estimate_margin([Leg("PE", 24500, TransactionType.SELL)], spot, 75, 1,
                        [black_scholes_price(spot, 24500, t, "PE", sigma=sig)])
notional = spot * 75
check("naked short put margined on the SPAN basis", naked["basis"] == "naked_span")
check("naked margin lands in the 4-12% of notional band",
      0.04 <= naked["margin"] / notional <= 0.12,
      f"Rs {naked['margin']:,.0f} = {naked['margin'] / notional * 100:.1f}% of Rs {notional:,.0f}")
check("naked max loss reported as unbounded", naked["max_loss"] is None)

spread_legs = [Leg("PE", 24500, TransactionType.SELL), Leg("PE", 24000, TransactionType.BUY)]
prem = [black_scholes_price(spot, k, t, "PE", sigma=sig) for k in (24500, 24000)]
spread = estimate_margin(spread_legs, spot, 75, 1, prem)
theoretical = (500 - (prem[0] - prem[1])) * 75
check("hedged spread margined on the defined-risk basis", spread["basis"] == "defined_risk")
check("defined-risk margin equals width minus credit, times lot",
      abs(spread["margin"] - theoretical) < 1.0,
      f"Rs {spread['margin']:,.0f} vs theoretical Rs {theoretical:,.0f}")
check("spread margin is far below naked margin",
      spread["margin"] < naked["margin"] / 3,
      f"Rs {spread['margin']:,.0f} vs Rs {naked['margin']:,.0f}")

print("\n5. P&L direction on controlled tapes (the acceptance criterion)")
# Fixed 7-day DTE here rather than the real expiry calendar: on synthetic dates the
# weekly cycle makes DTE swing between 0.4 and 6 days, which moves a 15-delta strike
# between ~80 and ~300 points out. A tape that is "quiet" against a 300-point strike is
# a violently trending one against an 80-point strike, so the calendar would be testing
# the tape rather than the accounting. Pinning DTE isolates what this check is about.
#
# Flat tape: +/-20 points (0.08%) of chop -- genuinely inside any short strike.
flat = [25000 + 5 * ((i % 8) - 4) for i in range(400)]
# Same opening 200 bars, then a hard one-way trend of +2400 points that must run
# through the short call of anything opened along the way.
trend = flat[:200] + [25000 + 12 * (i - 200) for i in range(200, 400)]


def run(sid, bars, **kw):
    kw.setdefault("dte_days", 7)
    return run_options_selling_backtest(
        sid, "NIFTY", Timeframe.M15, bars, include_trades=True, **kw
    )


r_flat = run("sell_dead_tape_strangle", make_bars(flat))
r_trend = run("sell_dead_tape_strangle", make_bars(trend))
nf, nt = r_flat["metrics"]["net_profit"], r_trend["metrics"]["net_profit"]
check("short strangle PROFITS in a range-bound tape", nf > 0, f"Rs {nf:,.0f} over {r_flat['metrics']['total_trades']} trades")
check("short strangle LOSES when price trends through a short strike", nt < 0, f"Rs {nt:,.0f}")
check("range-bound outcome beats the trending one", nf > nt, f"Rs {nf:,.0f} vs Rs {nt:,.0f}")

print("\n6. Trade-level accounting invariants (real NIFTY run)")


def load_real_bars(timeframe=Timeframe.M15):
    """Mongo by default; a jsonl(.gz) dump when NIFTY_BAR_DUMP is set (offline runs)."""
    dump = os.environ.get("NIFTY_BAR_DUMP")
    if dump:
        import gzip
        import json

        opener = gzip.open if dump.endswith(".gz") else open
        bars = []
        for line in opener(dump, "rt"):
            d = json.loads(line)
            if d["timeframe"] != timeframe.value or d["symbol"] != "NIFTY":
                continue
            d["ts"] = datetime.fromisoformat(d["ts"])
            bars.append(Bar(**d))
        bars.sort(key=lambda b: b.ts)
        return bars
    from backtesting_service.service import load_bars

    return load_bars("NIFTY", timeframe, None)


real = load_real_bars()
if not real:
    print("  SKIPPED — no NIFTY 15m bars available (set NIFTY_BAR_DUMP or backfill Mongo)")
    real = make_bars([25000 + 5 * ((i % 8) - 4) for i in range(400)])

r = run_options_selling_backtest(
    "sell_dead_tape_condor", "NIFTY", Timeframe.M15, real, expiry_weekday=1, include_trades=True
)
trades = [t for t in r["trades"] if t["exit_ts"] is not None]
check("every trade opened for a net credit", all(t["credit"] > 0 for t in trades),
      f"{len(trades)} trades, min credit {min(t['credit'] for t in trades):.2f}")
qty = 75
# Tolerance, not equality: credit and buy-back are reported rounded to paise, and the
# identity multiplies both by 75 units, so up to 0.005 x 2 x 75 = 0.75 of rounding is
# expected and is not an accounting error.
drift = max(abs(t["pnl"] - ((t["credit"] - t["exit_price"]) * qty - t["charges"])) for t in trades)
check("P&L == (credit - buyback) x qty - charges, on every trade", drift < 0.8,
      f"max rounding drift Rs {drift:.3f} across {len(trades)} trades")
check("all four condor legs recorded on every trade", all(len(t["legs"]) == 4 for t in trades))
check("every trade carries a margin figure", all(t["margin"] > 0 for t in trades))
check("no trade exceeds the 2%-of-capital hard stop",
      r["metrics"]["selling"]["worst_trade_pct_capital"] <= 2.05,
      f"worst {r['metrics']['selling']['worst_trade_pct_capital']:.2f}% of capital")
check("every trade has an explicit exit reason",
      all(t["exit_reason"] in
          {"target", "stop", "strike_pressure", "capital_stop", "expiry", "signal", "eod"}
          for t in trades),
      str(r["metrics"]["selling"]["exit_reasons"]))

print("\n7. Layered risk control: strike wall first, capital backstop last")
# The naked put's actual disaster scenario, and the one no stop can fully protect
# against: a steady grind up that qualifies the entry (rising EMA50), then a crash that
# runs straight through the short strike inside a single session. The crash has to be
# violent enough to breach within one session because this style squares off at the
# bell -- a slower decline would simply be closed flat at EOD each day and would test
# nothing.
# The crash must begin on a SESSION BOUNDARY (make_bars starts a new day every 25 bars).
# Starting it mid-session leaves too few bars before the bell: the position squares off
# at EOD having fallen only a few hundred points, and the next session no longer
# qualifies for entry because price is now under the EMA. Bar 225 is a session open and
# is also the peak, so a position opens there and then eats the whole -1440-point day.
crash = [25000 + 3 * i for i in range(226)] + [25675 - 60 * (i - 225) for i in range(226, 266)]

# With everything live the PREMIUM stop fires, not the wall -- and that is correct. A
# 12-delta short put sits ~375 points away while its premium doubles after ~100 points
# of adverse move, so the tighter control is the premium one. The wall is not a
# first-responder; it is the control that still works when premium has not yet repriced.
r_all = run("sell_uptrend_naked_pe", make_bars(crash))
check("tightest control wins: premium stop fires ahead of the more distant wall",
      r_all["metrics"]["selling"]["exit_reasons"].get("stop", 0) > 0,
      str(r_all["metrics"]["selling"]["exit_reasons"]))

# Disable only the premium stop: the wall must now be what closes the position, well
# before the capital backstop is reached.
r_walled = run("sell_uptrend_naked_pe", make_bars(crash), loss_cap_mult=999.0)
reasons = r_walled["metrics"]["selling"]["exit_reasons"]
check("with the premium stop disabled, the strike wall closes the position",
      reasons.get("strike_pressure", 0) > 0, str(reasons))
check("the wall exits cheaper than the capital backstop would have",
      (r_walled["metrics"]["selling"]["worst_trade_pct_capital"] or 0) < 2.0,
      f"worst {r_walled['metrics']['selling']['worst_trade_pct_capital']}% of capital")

# Now disable BOTH the premium stop and the strike wall. A negative buffer puts the wall
# at twice the strike, i.e. permanently out of reach, so nothing but the capital
# backstop is left. This is the check that the backstop is genuinely non-negotiable
# rather than merely never-reached.
r_naked = run("sell_uptrend_naked_pe", make_bars(crash),
              loss_cap_mult=999.0, strike_buffer_pct=-1.0)
naked_reasons = r_naked["metrics"]["selling"]["exit_reasons"]
worst = r_naked["metrics"]["selling"]["worst_trade_pct_capital"]
check("with stop and wall both disabled, the capital backstop is what closes trades",
      naked_reasons.get("capital_stop", 0) > 0, str(naked_reasons))
check("worst trade still bounded by the 2%-of-capital ceiling",
      worst is not None and worst <= 2.05, f"worst {worst}% of capital")

print("\n" + ("ALL CHECKS PASSED" if not FAILURES else f"{len(FAILURES)} FAILED: {FAILURES}"))
sys.exit(1 if FAILURES else 0)
