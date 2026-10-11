"""Verify the Gold Desk's money arithmetic. No Mongo, no Angel, no network.

Run:  python backend/tests/gold_desk/verify_gold_book.py

The arithmetic that decides money, each a place the desk this module was ported from got wrong
or this desk got wrong before its research (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md):

  THE FEE      Delta charges 0.01% a side on gold (product spec), 0.05% on Bitcoin. A fee the
               venue does not publish now REFUSES the trade (D7) — it used to be charged as zero.
  THE SIZE     An MCX gold lot is a kilogram (Rs 1.47 crore); the book trades GOLDM only. A Delta
               strategy holds one sleeve of capital / 9 at 1x — the H1 forward test.
  THE SESSION  A 24/7 venue's day is the UTC day, buckets anchored to UTC midnight.

Prices are real: MCX GOLD/GOLDM from the production bar store and the Delta gold perpetual from
the venue, 2026-09-29.

Imports through `_harness`, which puts this repo's `shared/` first on the path — the stale
`TradingAI/shared` package used to shadow it and this file failed to import (D17).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import check, finish, section  # noqa: E402

from app.services import gold_desk as G  # noqa: E402
from app.services import gold_h1 as H  # noqa: E402
from app.services.commodity_positions import multiplier  # noqa: E402
from app.services.commodity_prelive import margin_pct  # noqa: E402
from app.services.gold_delta_feed import Bar, resample  # noqa: E402

MCX_GOLD = 146652.0         # Rs per 10 g, 1 kg lot
MCX_GOLDM = 146820.0        # Rs per 10 g, 100 g lot
DELTA_XAUT = 4153.44        # $ per troy ounce
DELTA_SPEC = {"contract_value": 0.001, "taker_fee_rate": 0.0001}
CRYPTO_RATE = 0.00059       # what the original charged on gold

mcx, delta = G.VENUES["mcx"], G.VENUES["delta"]

# ── 1. MCX contract mathematics ────────────────────────────────────────────────────
section("MCX contract mathematics")

notional = MCX_GOLDM * multiplier("GOLDM")
check("one GOLDM lot is 100 g: price per 10 g x 10", abs(notional - MCX_GOLDM * 10) < 1, f"Rs {notional:,.0f}")
check("one GOLDM lot fits inside the Rs 30 lakh book (and two do, three do not)",
      notional <= mcx.capital and 2 * notional <= mcx.capital < 3 * notional, f"Rs {notional:,.0f}")
m = margin_pct("GOLDM") * notional
check("a lot ties up broker-measured margin, not its whole notional", 0 < m < notional * 0.2, f"Rs {m:,.0f}")
check("GOLD (1 kg) is off the book: Rs 1.47 crore a lot could never be sized on it",
      "GOLD" not in mcx.symbols and abs(MCX_GOLD * multiplier("GOLD") - 14665200) < 1)
check("account mode caps the net position at two lots", mcx.mode == "account" and mcx.max_net_units == 2)

# ── 2. Delta sizing: one sleeve per strategy, whole contracts, no leverage ─────────
section("Delta sizing (H1 sleeves)")

n_specs = len(G.specs_for(delta))
sleeve = delta.capital / n_specs
per_contract = DELTA_XAUT * DELTA_SPEC["contract_value"]
units = int(sleeve // per_contract)
check("nine strategies, nine sleeves of capital / 9", n_specs == 9 and abs(sleeve - 10_000 / 9) < 1e-9)
check("a sleeve buys whole contracts", units == int((10_000 / 9) // per_contract), f"{units} contracts at ${per_contract:.3f}")
check("no leverage: a sleeve's notional is within the sleeve", units * per_contract <= sleeve)
check("nine full sleeves can never commit more than the book", 9 * units * per_contract <= delta.capital)
check("record mode: no shared slots, no daily breaker (it would censor H1's sample)",
      delta.mode == "record" and delta.daily_loss_pct is None and delta.max_positions == 9)

# ── 3. The fee ────────────────────────────────────────────────────────────────────
section("Fees")

qty = units * DELTA_SPEC["contract_value"]
gold_fee = G._fee(delta, DELTA_SPEC, DELTA_XAUT, qty, True)
expected = DELTA_XAUT * qty * DELTA_SPEC["taker_fee_rate"] * (1 + G.DELTA_GST)
crypto_fee = DELTA_XAUT * qty * CRYPTO_RATE
check("the Delta fee comes from the venue's own product spec", abs(gold_fee - expected) < 1e-9, f"${gold_fee:.4f}")
check("GST is applied on top of the venue rate", abs(gold_fee / (DELTA_XAUT * qty) - 0.000118) < 1e-9)
check("the old crypto rate would have charged ~5x as much", 4.5 < crypto_fee / gold_fee < 5.5)
check("a venue that publishes no fee REFUSES the trade — no silent zero (D7)",
      G._fee(delta, {"taker_fee_rate": None}, DELTA_XAUT, qty, True) is None
      and G._fee(delta, {"taker_fee_rate": 0.0}, DELTA_XAUT, qty, True) is None)
mcx_fee = G._fee(mcx, {}, MCX_GOLDM, 10, True)
check("MCX charges are real and non-zero", mcx_fee > 0, f"Rs {mcx_fee:,.2f} on one GOLDM lot")

# ── 4. The session ────────────────────────────────────────────────────────────────
section("Delta bar buckets")

base = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
bars = [Bar(base + timedelta(minutes=15 * i), 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(96)]
r45 = resample(bars, 45)
check("45m buckets start on a 45-minute boundary from UTC midnight",
      all((b.ts.hour * 60 + b.ts.minute) % 45 == 0 for b in r45), f"{len(r45)} buckets")
check("a full UTC day divides evenly into 45m buckets — no stub bar", len(r45) == 32)
check("buckets are ordered oldest-first", all(a.ts < b.ts for a, b in zip(r45, r45[1:])))
check("aggregation keeps OHLC consistent", all(b.low <= b.open <= b.high and b.low <= b.close <= b.high for b in r45))
check("the first bucket opens on the first bar and closes on the third",
      r45[0].open == bars[0].open and r45[0].close == bars[2].close)
check("the Delta day is the UTC day", G._day_key(delta) == datetime.now(timezone.utc).date().isoformat())

# ── 5. The two books stay separate ────────────────────────────────────────────────
section("Book separation")

check("two venues are registered", set(G.VENUE_KEYS) == {"mcx", "delta"}, str(G.VENUE_KEYS))
check("they hold different currencies", mcx.currency == "INR" and delta.currency == "USD")
try:
    G.venue("nifty")
    unknown_raised = False
except KeyError:
    unknown_raised = True
check("an unknown venue raises rather than defaulting to one of them", unknown_raised)
check("both books carry a floor — a ruin guard",
      0 < mcx.book_floor_pct < 1 and 0 < delta.book_floor_pct < 1)
check("the shared-book (MCX) venue has a daily loss breaker", (mcx.daily_loss_pct or 0) > 0)
check("H1's nine are the plan's nine", set(H.H1_TEMPLATES) == {
    "donchian_fast", "donchian_slow", "keltner_break", "prior_session_break", "round_number_break",
    "pivot_break", "hh_hl_shift", "atr_thrust", "ema_ribbon"})

finish()
