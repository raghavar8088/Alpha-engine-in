"""Safety-rail checks for the option-SELLING pre-live desk (Phase 5).

Answers the questions a risk desk has to be able to answer with evidence rather than
assurance, against the REAL engine driven by a fake price feed:

  1. Can a session ever end with an unbounded naked short and no stop recorded?
  2. Does closing a multi-leg structure close EVERY leg, always?
  3. Does the daily loss circuit breaker actually halt new entries?
  4. Do positions survive a process restart, including across sessions?
  5. Is the selling desk's paper capital isolated from the buying desk's?
  6. Are stops evaluated intrabar, or only on bar close?
  7. Is an expiring structure always closed?

Uses a throwaway Mongo database (`MONGO_DB_NAME` is overridden before any import that
touches it), so it never reads or writes the live desks' collections. No Dhan calls are
made anywhere in this file.

Run from the repo root:
    python prelive-service/verify_selling_desk.py
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Point every downstream import at a scratch database BEFORE db_selling binds its client.
# The live desks' data must be untouchable from a test run.
_TEST_DB = f"tradingai_selling_test_{uuid.uuid4().hex[:8]}"
os.environ["MONGO_DB_NAME"] = _TEST_DB
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ["PRELIVE_SELLING_INITIAL_CAPITAL"] = "10000000"
os.environ["PRELIVE_SELLING_DAILY_LOSS_PCT"] = "0.03"

sys.path[:0] = ["shared", "strategy-service", "options-service", "backtesting-service",
                "prelive-service"]

IST = timezone(timedelta(hours=5, minutes=30))
FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


class FakeFeed:
    """Deterministic price source. `spot` drives the wall checks; every option leg is
    priced from a simple multiple of its entry premium so a test can say 'the book is
    now worth 3x what I sold it for' without modelling Black-Scholes again."""

    def __init__(self, spot=25000.0):
        self.spot = spot
        self.multiplier = 1.0
        self.base: dict = {}
        self.unpriceable: set = set()

    def ltp(self, security_id, exchange_segment):
        if exchange_segment == "IDX_I":
            return self.spot
        sid = str(security_id)
        if sid in self.unpriceable:
            return None
        return round(self.base.get(sid, 100.0) * self.multiplier, 2)


def main() -> int:
    from db_selling import (_db, daily_pnl_collection, instruments_collection,
                            positions_collection, trades_collection)
    import prelive_selling_engine as E
    from prelive_selling_engine import OpenLeg, OpenStructure, PreLiveSellingEngine
    from options_service.options_selling_backtest import OPTION_SELLING_CATEGORIES

    print(f"scratch database: {_TEST_DB}\n")

    # Seed the instruments a structure needs, so contract lookup resolves.
    expiry = (datetime.now(IST).date() + timedelta(days=5)).isoformat()
    docs = []
    for strike in range(23000, 27001, 50):
        for ot in ("CE", "PE"):
            docs.append({
                "asset_class": "INDEX_OPTION", "expiry": expiry, "strike": float(strike),
                "option_type": ot, "symbol": f"NIFTY-{strike}-{ot}",
                "security_id": f"{strike}{1 if ot == 'CE' else 2}",
                "exchange_segment": "NSE_FNO",
            })
    instruments_collection.insert_many(docs)

    engine = PreLiveSellingEngine()
    feed = FakeFeed()
    engine.new_session()
    style = OPTION_SELLING_CATEGORIES["options_sell_swing"]

    def make_structure(key, legs_spec, credit_per_unit, lots=1, entry_spot=25000.0,
                       exp=None, margin=200000.0):
        legs = []
        for ot, strike, sold, prem in legs_spec:
            sid = f"{int(strike)}{1 if ot == 'CE' else 2}"
            feed.base[sid] = prem
            legs.append(OpenLeg(ot, strike, sold, sid, "NSE_FNO", f"NIFTY-{strike}-{ot}", prem))
        pos = OpenStructure(key=key, strategy_id=key.split("@")[0], tf="15m", legs=legs,
                            credit=credit_per_unit, lots=lots, margin=margin,
                            margin_basis="naked_span", entry_ts=datetime.now(IST),
                            entry_spot=entry_spot, expiry=exp or expiry, style=style)
        engine.positions[key] = pos
        positions_collection.replace_one({"key": key}, engine._pos_doc(pos, credit_per_unit),
                                         upsert=True)
        return pos

    print("1. Multi-leg close closes EVERY leg")
    make_structure("t_condor@15m",
                   [("CE", 25300, True, 60.0), ("CE", 25600, False, 20.0),
                    ("PE", 24700, True, 55.0), ("PE", 24400, False, 18.0)],
                   credit_per_unit=77.0)
    feed.multiplier = 0.4  # decayed -> take profit
    events = engine.manage_open(feed.ltp)
    trade = trades_collection.find_one({"key": "t_condor@15m"})
    check("closing a 4-leg condor books all 4 legs", trade is not None and len(trade["legs"]) == 4,
          f"{len(trade['legs']) if trade else 0} legs recorded")
    check("no position doc left behind after close",
          positions_collection.find_one({"key": "t_condor@15m"}) is None)
    check("engine holds no in-memory remnant", "t_condor@15m" not in engine.positions)
    check("exit reason recorded", bool(trade and trade["exit_reason"]),
          trade["exit_reason"] if trade else "-")
    check("P&L == (credit - buyback) x qty",
          trade is not None
          and abs(trade["pnl"] - (trade["credit"] - trade["exit_cost"]) * trade["qty"]) < 0.01,
          f"pnl Rs{trade['pnl']:,.2f}" if trade else "-")

    print("\n2. Every open structure carries a stop it cannot escape")
    pos = make_structure("t_naked@15m", [("PE", 24500, True, 80.0)], credit_per_unit=80.0)
    check("naked short has a capital backstop configured", pos.max_loss_pct_capital > 0,
          f"{pos.max_loss_pct_capital:.1%} of pool")
    check("naked short has a premium stop configured", pos.loss_cap_mult > 0,
          f"{pos.loss_cap_mult}x credit")
    check("naked short registered a strike wall", pos.wall_pe is not None,
          f"PE wall {pos.wall_pe}")

    print("\n3. Stops fire on price movement, not only on bar close")
    feed.multiplier = 3.0  # premium tripled -> deep loss on the short
    events = engine.manage_open(feed.ltp)   # NOTE: no bar was finalized here
    check("manage_open (per-tick) closed the losing short without any bar close",
          len(events) == 1 and "t_naked@15m" not in engine.positions,
          events[0]["exit_reason"] if events else "no event")

    print("\n4. Daily loss circuit breaker halts NEW entries")
    engine.day_start_equity = 10_000_000.0
    engine.breaker_tripped = False
    # Book a loss larger than 3% of the pool.
    trades_collection.insert_one({
        "key": "loss@15m", "strategy_id": "loss", "pnl": -400_000.0,
        "exit_ts": datetime.now(IST).isoformat(), "legs": [], "qty": 75,
    })
    tripped = engine.check_breaker(feed.ltp)
    check("breaker trips once the day's loss crosses the limit", tripped,
          engine.breaker_reason or "")

    class _Strat:
        def __init__(self): self._open = False
        def position_closed(self): self._open = False
    engine.strategies["blocked@15m"] = _Strat()
    engine.contexts["blocked@15m"] = None
    before = len(engine.positions)
    from tradingai_shared.domain import Bar, Timeframe
    bar = Bar(symbol="NIFTY", timeframe=Timeframe.M15, ts=datetime.now(IST),
              open=25000, high=25010, low=24990, close=25000, volume=0)
    # on_bar must refuse to open while the breaker is up, whatever the strategy says.
    result = engine.on_bar("blocked", "15m", bar, feed.ltp)
    check("no new structure opens while the breaker is tripped",
          result is None and len(engine.positions) == before)

    print("\n5. Open structures survive a process restart")
    make_structure("t_carry@15m", [("PE", 24300, True, 45.0), ("PE", 24000, False, 15.0)],
                   credit_per_unit=30.0, lots=2)
    engine2 = PreLiveSellingEngine()  # fresh process would do exactly this
    restored = engine2.positions.get("t_carry@15m")
    check("structure restored from Mongo on startup", restored is not None)
    check("restored structure keeps all its legs", restored is not None and len(restored.legs) == 2)
    check("restored structure keeps its lot count", restored is not None and restored.lots == 2,
          f"lots={restored.lots if restored else '-'}")
    check("restored structure keeps its margin", restored is not None and restored.margin > 0)
    check("restored structure rebuilt its strike wall", restored is not None and restored.wall_pe is not None,
          f"PE wall {restored.wall_pe if restored else '-'}")

    print("\n6. Expiring structures are always closed")
    yesterday = (datetime.now(IST).date() - timedelta(days=1)).isoformat()
    make_structure("t_expired@15m", [("CE", 25500, True, 20.0)], credit_per_unit=20.0,
                   exp=yesterday)
    feed.multiplier = 1.0
    events = engine.manage_open(feed.ltp)
    check("a structure past its expiry is closed, not carried",
          "t_expired@15m" not in engine.positions,
          next((e["exit_reason"] for e in events if e["key"] == "t_expired@15m"), "not closed"))

    print("\n7. A partially-priced book produces NO decision")
    p = make_structure("t_partial@15m",
                       [("CE", 25400, True, 50.0), ("CE", 25700, False, 15.0)],
                       credit_per_unit=35.0)
    feed.unpriceable.add(p.legs[1].security_id)   # one leg goes dark
    feed.multiplier = 5.0                          # the other says "catastrophic loss"
    events = engine.manage_open(feed.ltp)
    check("no action taken when a leg is unpriceable (never act on a partial mark)",
          "t_partial@15m" in engine.positions
          and not any(e["key"] == "t_partial@15m" for e in events))
    feed.unpriceable.clear()

    print("\n8. Selling desk capital is isolated from the buying desk")
    names = set(_db.list_collection_names())
    check("all desk collections are prelive_selling_*",
          all(n.startswith("prelive_selling_") for n in names if n.startswith("prelive")),
          ", ".join(sorted(n for n in names if n.startswith("prelive"))) or "none yet")
    check("selling desk never writes the buying desk's collections",
          not any(n.startswith("prelive_") and not n.startswith("prelive_selling_") for n in names))
    bal = engine.balance()
    check("capital pool is the selling desk's own env var",
          bal["initial_capital"] == 10_000_000.0, f"Rs{bal['initial_capital']:,.0f}")

    print("\n9. EOD square-off is style-dependent (swing must NOT be flattened nightly)")
    check("swing style is not squared off at EOD",
          OPTION_SELLING_CATEGORIES["options_sell_swing"]["square_off_eod"] is False)
    check("positional style is not squared off at EOD",
          OPTION_SELLING_CATEGORIES["options_sell_positional"]["square_off_eod"] is False)
    check("intraday style IS squared off at EOD",
          OPTION_SELLING_CATEGORIES["options_sell_intraday"]["square_off_eod"] is True)
    # A FRESH, healthy structure. The one from section 5 was legitimately stopped out by
    # section 7's 5x price spike (which moves every open leg, not just the partial one) —
    # correct engine behaviour, so this section makes its own subject rather than
    # asserting against a position earlier sections have already acted on.
    feed.multiplier = 1.0
    make_structure("t_overnight@15m", [("PE", 24200, True, 40.0), ("PE", 23900, False, 12.0)],
                   credit_per_unit=28.0)
    engine.close_session(feed.ltp)
    check("carried swing structures survive close_session",
          "t_overnight@15m" in engine.positions
          and positions_collection.find_one({"key": "t_overnight@15m"}) is not None,
          "still open in memory and in Mongo")
    day = daily_pnl_collection.find_one({"session": engine.session_date})
    check("session P&L doc records what was carried overnight",
          day is not None and "open_carried" in day,
          f"carried={day.get('open_carried') if day else '-'}")

    _db.client.drop_database(_TEST_DB)
    print(f"\ndropped scratch database {_TEST_DB}")
    print("\n" + ("ALL SAFETY CHECKS PASSED" if not FAILURES
                  else f"{len(FAILURES)} FAILED: {FAILURES}"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
