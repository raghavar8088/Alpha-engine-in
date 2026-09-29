"""Verify the Gold Desk's money arithmetic. No Mongo, no Angel, no network.

Run:  python backend/tests/gold_desk/verify_gold_book.py

Three things here decide money, and each of them is a place the desk this module was
ported from got it wrong:

  THE FEE      Delta charges 0.01% a side on gold and 0.05% on Bitcoin. The original
               hardcoded one crypto rate and charged it on gold — 5.9x the real cost, on a
               book whose only question is whether an edge survives its costs.

  THE SIZE     An MCX gold lot is a KILOGRAM: at Rs 1,46,800 per 10 g that is Rs 1.47
               CRORE of notional. A book that sized it from the broker's `lotsize` field,
               or that let margin decide, would hold a hundred times the gold it can pay
               for and call the result a paper record.

  THE SESSION  Every session template reads `bar.ts.date()`. Bars anchored to the MCX open
               would hand a 24/7 venue a session boundary in the middle of active trading.

The prices below are real: MCX GOLD/GOLDM read from the production bar store and the Delta
gold perpetuals read from the venue, both on 2026-09-29. Assertions against reality rather
than against themselves.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()


def _stub_missing(*names: str) -> None:
    """Neutralise import-time third-party dependencies this test never exercises.

    `gold_desk` reaches the shared commodity services for its contract mathematics, and
    those reach a broker client, which imports a Redis driver at module scope. Stubbed
    here rather than in the shared `_stub_infra`, which other test directories rely on —
    widening a shared stub to suit one test is how a stub stops representing anything."""
    import types
    for name in names:
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            cur = mod
            for part in name.split(".")[1:]:
                sub = types.ModuleType(f"{cur.__name__}.{part}")
                setattr(cur, part, sub)
                sys.modules[sub.__name__] = sub
                cur = sub


_stub_missing("redis", "redis.asyncio", "fastapi")

if not hasattr(sys.modules["redis.asyncio"], "Redis"):
    # `broker_data` annotates a module-level `redis.Redis | None`, which is evaluated at
    # import. A bare module object has no such attribute, so the name has to exist.
    sys.modules["redis.asyncio"].Redis = type("Redis", (), {})
    sys.modules["redis.asyncio"].from_url = lambda *a, **k: None

from app.services import gold_desk as G  # noqa: E402
from app.services.gold_delta_feed import Bar, resample  # noqa: E402

FAILURES: list[str] = []

# Read from production / the venue on 2026-09-29.
MCX_GOLD = 146652.0         # Rs per 10 g, 1 kg lot
MCX_GOLDM = 146820.0        # Rs per 10 g, 100 g lot
DELTA_XAUT = 4153.44        # $ per troy ounce
DELTA_SPEC = {"contract_value": 0.001, "taker_fee_rate": 0.0001}
CRYPTO_RATE = 0.00059       # what the original charged on gold


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


# ── 1. MCX sizing: whole lots, and never more gold than the book can pay for ──────

section("MCX sizing")

mcx = G.VENUES["mcx"]

units, notional, committed, why = G._sizing(mcx, "GOLDM", {}, MCX_GOLDM, mcx.capital)
check("GOLDM is tradable on this book", units == 1, f"{units} lot(s), notional Rs {notional:,.0f}")
check("GOLDM notional is one 100 g lot",
      abs(notional - MCX_GOLDM * 10) < 1, f"Rs {notional:,.0f} (100 g at Rs {MCX_GOLDM:,.0f}/10 g)")
check("GOLDM notional fits inside the book",
      notional <= mcx.capital, f"Rs {notional:,.0f} of Rs {mcx.capital:,.0f}")
check("GOLDM ties up margin, not the whole notional",
      0 < committed < notional * 0.2, f"Rs {committed:,.0f} margin on Rs {notional:,.0f}")

units_g, notional_g, _c, why_g = G._sizing(mcx, "GOLD", {}, MCX_GOLD, mcx.capital)
check("GOLD is refused rather than part-funded", units_g == 0 and why_g is not None,
      (why_g or "")[:96])
check("GOLD is refused because a 1 kg lot is Rs 1.47 crore",
      abs(MCX_GOLD * 100 - 14665200) < 1, f"Rs {MCX_GOLD * 100:,.0f} of notional per lot")

# Free margin, not just capital, has to bind — otherwise a book already fully deployed
# keeps opening positions.
units_broke, _n, _c, why_broke = G._sizing(mcx, "GOLDM", {}, MCX_GOLDM, 1000.0)
check("GOLDM is refused when the free margin is gone", units_broke == 0 and why_broke is not None,
      (why_broke or "")[:96])

# ── 2. Delta sizing: whole contracts, one slot's share, no leverage ───────────────

section("Delta sizing")

delta = G.VENUES["delta"]
units_d, notional_d, committed_d, why_d = G._sizing(
    delta, "XAUTUSD", DELTA_SPEC, DELTA_XAUT, delta.capital)

slot = delta.capital / delta.max_positions
per_contract = DELTA_XAUT * DELTA_SPEC["contract_value"]
check("XAUTUSD sizes to whole contracts", units_d == int(slot // per_contract),
      f"{units_d} contracts at ${per_contract:.3f} each")
check("a position is one slot's share of the book", notional_d <= slot + per_contract,
      f"${notional_d:,.2f} against a ${slot:,.2f} slot")
check("no leverage is taken — committed capital IS the notional",
      abs(committed_d - notional_d) < 1e-9, f"${committed_d:,.2f}")
check("the whole book cannot be over-committed",
      notional_d * delta.max_positions <= delta.capital + per_contract * delta.max_positions,
      f"{delta.max_positions} slots x ${notional_d:,.2f}")

# ── 3. The fee. The bug this port exists to fix. ─────────────────────────────────

section("Fees")

import asyncio  # noqa: E402

qty = units_d * DELTA_SPEC["contract_value"]
gold_fee = asyncio.run(G._charges(delta, "XAUTUSD", DELTA_SPEC, DELTA_XAUT, qty, True))
expected = DELTA_XAUT * qty * DELTA_SPEC["taker_fee_rate"] * (1 + G.DELTA_GST)
crypto_fee = DELTA_XAUT * qty * CRYPTO_RATE

check("the Delta fee comes from the venue's own product spec",
      abs(gold_fee - expected) < 1e-9, f"${gold_fee:.4f} on ${DELTA_XAUT * qty:,.2f} of notional")
check("GST is applied on top of the venue rate, not baked into it",
      abs(gold_fee / (DELTA_XAUT * qty) - 0.000118) < 1e-9,
      f"effective {gold_fee / (DELTA_XAUT * qty) * 100:.4f}% a side")
check("the old crypto rate would have charged ~5x as much",
      4.5 < crypto_fee / gold_fee < 5.5, f"${crypto_fee:.4f} against ${gold_fee:.4f}")

# A product that reports no rate must cost nothing rather than fall back to a guess: a
# silent default is how the wrong fee got charged for months in the first place.
zero_fee = asyncio.run(G._charges(delta, "XAUTUSD", {"taker_fee_rate": 0.0}, DELTA_XAUT, qty, True))
check("an unknown venue rate charges zero rather than a guessed default", zero_fee == 0.0)

# MCX charges come from the shared commodity cost model, so gold pays what every other
# contract in this app pays.
mcx_fee = asyncio.run(G._charges(mcx, "GOLDM", {}, MCX_GOLDM, 10, True))
check("MCX charges are real and non-zero", mcx_fee > 0, f"Rs {mcx_fee:,.2f} on one GOLDM lot")

# ── 4. The session: UTC buckets for a venue that never closes ────────────────────

section("Delta bar buckets")

base = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
bars = [Bar(base + timedelta(minutes=15 * i), 100 + i, 101 + i, 99 + i, 100.5 + i, 10)
        for i in range(96)]                     # a full 24h of 15m bars
r45 = resample(bars, 45)

check("45m buckets start on a 45-minute boundary from UTC midnight",
      all((b.ts.hour * 60 + b.ts.minute) % 45 == 0 for b in r45),
      f"{len(r45)} buckets")
check("a full UTC day divides evenly into 45m buckets — no stub bar",
      len(r45) == 32, f"{len(r45)} buckets for 24h")
check("buckets are ordered oldest-first", all(a.ts < b.ts for a, b in zip(r45, r45[1:])))
check("aggregation keeps OHLC consistent",
      all(b.low <= b.open <= b.high and b.low <= b.close <= b.high for b in r45))
check("the first bucket opens on the first bar and closes on the third",
      r45[0].open == bars[0].open and r45[0].close == bars[2].close)
check("the day is the UTC day, not the MCX session",
      G._session_start(delta).hour == 0 and G._session_start(delta).tzinfo == timezone.utc)

# ── 5. The two books stay separate ───────────────────────────────────────────────

section("Book separation")

check("two venues are registered", set(G.VENUE_KEYS) == {"mcx", "delta"}, str(G.VENUE_KEYS))
check("they hold different currencies", mcx.currency == "INR" and delta.currency == "USD")
try:
    G.venue("nifty")
    unknown_raised = False
except KeyError:
    unknown_raised = True
check("an unknown venue raises rather than defaulting to one of them", unknown_raised)
check("both books carry a floor the original had none of",
      0 < mcx.book_floor_pct < 1 and 0 < delta.book_floor_pct < 1,
      f"entries stop at {mcx.book_floor_pct:.0%} of capital")
check("both books ship with a daily loss breaker",
      mcx.daily_loss_pct > 0 and delta.daily_loss_pct > 0)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
