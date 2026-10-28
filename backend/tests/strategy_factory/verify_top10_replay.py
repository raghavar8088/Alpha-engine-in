"""Does the Strategy Factory Top-10 replay trade exactly as the backtest that picked its ten?

Run inside the backend container (it reads the bar stores):
    docker exec -i -w /app/backend alpha-engine-backend-1 python tests/strategy_factory/verify_top10_replay.py

For each of the ten, on its most-traded stock and MCX series, the same closed bars are replayed two
ways: backtest() over the whole series, and top10_replay.step() one bar at a time, the way the live
loop feeds it (no precomputed regime series - each step classifies the regime from its own slice).
Every trade must agree: entry bar, exit bar, side, entry and exit price, exit reason. Nothing is
written anywhere.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.db import sf_backtests_collection  # noqa: E402
from app.services.strategy_factory import top10_replay as R  # noqa: E402
from app.services.strategy_factory.backtest import backtest  # noqa: E402
from app.services.strategy_factory.catalog import FACTORY_BY_ID  # noqa: E402

PER_MARKET = 1          # series per strategy and market (its most traded)
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    failures += 0 if ok else 1


def via_step(strat, bars, symbol, exchange, htf):
    out, pos = [], None
    for k in range(max(strat.min_bars, 2) + 1, len(bars)):
        pos, closed = R.step(strat, bars, k, pos, symbol=symbol, exchange=exchange, htf_bars=htf)
        if closed is not None:
            out.append((bars[closed["entry_k"]].ts, bars[closed["exit_k"]].ts, closed["side"],
                        round(closed["entry"], 4), round(closed["exit"], 4), closed["exit_reason"]))
    return out


async def main() -> None:
    compared = 0
    for sid in R.ROSTER:
        strat = FACTORY_BY_ID[sid]
        for source in R.SOURCES:
            rows = [r async for r in sf_backtests_collection.find(
                {"strategy_id": sid, "source": source}, {"symbol": 1, "overall.trades": 1})]
            rows.sort(key=lambda r: -((r.get("overall") or {}).get("trades") or 0))
            for r in rows[:PER_MARKET]:
                sym = r["symbol"]
                bars = await R.closed_bars(source, sym, strat.timeframe)
                htf = await R.closed_bars(source, sym, strat.htf) if strat.htf else None
                if len(bars) <= strat.min_bars + 2:
                    print(f"SKIP {sid} {source}:{sym} - {len(bars)} bars")
                    continue
                exchange = "MCX" if source == "commodity" else "NSE"
                ref = backtest(strat, bars, sym, exchange, htf_bars=htf, slippage_bps=R.SLIPPAGE_BPS,
                               cost_model="commodity" if source == "commodity" else "equity_delivery")
                want = [(t.entry_ts, t.exit_ts, t.side, round(t.entry, 4), round(t.exit, 4), t.reason)
                        for t in ref.trades]
                got = via_step(strat, bars, sym, exchange, htf)
                first = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b), None)
                check(f"{sid} {strat.timeframe} {source}:{sym} - {len(want)} backtest trades over "
                      f"{len(bars)} bars", want == got,
                      f"step gave {len(got)}; first difference at #{first}: "
                      f"{want[first] if first is not None else want[len(got):][:1]} vs "
                      f"{got[first] if first is not None else got[len(want):][:1]}")
                compared += 1
    check("compared at least ten series", compared >= 10, str(compared))
    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)


asyncio.run(main())
