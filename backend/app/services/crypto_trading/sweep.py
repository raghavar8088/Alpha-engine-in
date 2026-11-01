"""The sweep: every strategy-cryptocurrency pair backtested on the venue's own history.

    python -m app.services.crypto_trading.sweep --universe U.json --cache DIR --out R.jsonl [--workers N]
           [--coins BTC,ETH] [--strategies SF0001,ema_cross@15m] [--redo]
    python -m app.services.crypto_trading.sweep --dump-library L.json     (the library, for the importer)

Data are fetched once per coin into --cache (one JSON file per symbol and timeframe, plus the
funding series) and reused by every pair; results are appended to --out as one JSON line per pair,
so an interrupted sweep resumes where it stopped (pairs already in the file are skipped unless
--redo). Pairs are grouped by coin so each worker process loads a coin's history once.

The same function (`run_pair`) serves the live desk's revalidation; this module only adds the
batch: fetching, scheduling and writing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import os
import sys
import time

from .config import BACKTEST_DAYS, BENCHMARK_SYMBOL, DERIVED_FROM, TF_SECONDS, TIMEFRAMES

DATA_TFS = [tf for tf in TIMEFRAMES if tf not in DERIVED_FROM]


def _path(cache: str, symbol: str, name: str) -> str:
    return os.path.join(cache, f"{symbol}_{name}.json.gz")


def _launch_ts(coin: dict) -> int:
    from datetime import datetime
    lt = coin.get("launch_time")
    try:
        return int(datetime.fromisoformat(lt.replace("Z", "+00:00")).timestamp()) if lt else 0
    except ValueError:
        return 0


def prepare(coin: dict, cache: str, now: int | None = None, refresh: bool = False) -> dict:
    """Fetch (or reuse) every timeframe's window and the funding series for one coin."""
    from . import delta
    os.makedirs(cache, exist_ok=True)
    now = now or int(time.time())
    sym, listed = coin["venue_symbol"], _launch_ts(coin)
    got = {}
    for tf in DATA_TFS:
        p = _path(cache, sym, tf)
        if os.path.exists(p) and not refresh:
            got[tf] = len(json.load(gzip.open(p, "rt")))
            continue
        days = BACKTEST_DAYS[tf]
        if tf == "15m":                     # 15m also feeds 45m, whose window is longer
            days = max(days or 0, BACKTEST_DAYS["45m"] or 0) or None
        start = max(listed, now - days * 86400) if days else listed
        rows = delta.candles(sym, tf, start, now - TF_SECONDS[tf])   # closed bars only
        json.dump(rows, gzip.open(p, "wt"))
        got[tf] = len(rows)
    p = _path(cache, sym, "funding")
    if not os.path.exists(p) or refresh:
        json.dump(delta.funding(sym, listed or now - 900 * 86400, now), gzip.open(p, "wt"))
    return got


def load(cache: str, symbol: str) -> tuple[dict[str, list[list]], list]:
    from .delta import resample
    data = {tf: json.load(gzip.open(_path(cache, symbol, tf), "rt")) for tf in DATA_TFS}
    for tf, parent in DERIVED_FROM.items():
        data[tf] = resample(data[parent], TF_SECONDS[tf])
    now = data["1m"][-1][0] if data.get("1m") else int(time.time())
    for tf, days in BACKTEST_DAYS.items():          # trim each timeframe to its own window
        if days:
            data[tf] = [r for r in data[tf] if r[0] >= now - days * 86400]
    funding = [tuple(x) for x in json.load(gzip.open(_path(cache, symbol, "funding"), "rt"))]
    return data, funding


def provenance() -> dict:
    """Where the strategy code being graded was imported from, and how much of it there is."""
    import strategy_service
    import tradingai_shared
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    from app.services.strategy_factory import catalog
    return {"strategy_service": os.path.dirname(strategy_service.__file__),
            "tradingai_shared": os.path.dirname(tradingai_shared.__file__),
            "strategy_factory": os.path.dirname(catalog.__file__),
            "strategies_registry": len(STRATEGY_REGISTRY), "factory_catalog": len(catalog.FACTORY_CATALOG)}


_W: dict = {}


def _work(task: tuple) -> dict:
    """Worker: one pair. The coin's history (and the benchmark's) is loaded once per process."""
    sid, coin, cache = task
    from . import library as lib
    from .adapters import Contract
    from .backtest import _base, run_pair
    row = lib.by_id()[sid]
    contract = Contract.from_coin(coin)
    try:
        if _W.get("symbol") != contract.symbol:
            _W["symbol"] = contract.symbol
            _W["data"], _W["funding"] = load(cache, contract.symbol)
        bench = None
        if row["base_id"] in ("relative_strength", "sector_rotation"):
            if "bench" not in _W:
                _W["bench"] = load(cache, BENCHMARK_SYMBOL)[0]
            bench = _W["bench"]
        if "prov" not in _W:
            _W["prov"] = provenance()
        res = run_pair(row, contract, _W["data"], _W["funding"], bench)
        res["libraries"] = {"strategies_registry": _W["prov"]["strategies_registry"],
                            "factory_catalog": _W["prov"]["factory_catalog"]}
        return res
    except Exception as exc:  # noqa: BLE001 - one pair's failure is recorded, never fatal to the sweep
        return _base(row, contract, "error", f"{type(exc).__name__}: {str(exc)[:300]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump-library", default="")
    ap.add_argument("--universe")
    ap.add_argument("--cache")
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--coins", default="")
    ap.add_argument("--strategies", default="")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--refresh-data", action="store_true")
    a = ap.parse_args(argv)

    from . import library as lib
    prov = provenance()
    print(f"libraries: {prov}", flush=True)
    if prov["strategies_registry"] < 600:
        # A stale copy of strategy_service on the path (a developer venv) registers a fraction of the
        # module's strategies and carries old indicators the Factory also uses: refuse to grade on it.
        print("refusing to run: the Strategies-module registry is incomplete - wrong strategy_service on the path",
              flush=True)
        return 2
    if a.dump_library:
        rows = list(lib.library())
        json.dump(rows, open(a.dump_library, "w", encoding="utf-8"), default=str)
        print(f"library: {len(rows)} strategies -> {a.dump_library} {lib.summary()}", flush=True)
        return 0
    if not (a.universe and a.cache and a.out):
        ap.error("--universe, --cache and --out are required to sweep")
    uni = json.load(open(a.universe))
    coins = [c for c in uni["selected"] if not a.coins or c["symbol"] in a.coins.split(",")]
    rows = [r for r in lib.library() if not a.strategies or r["strategy_id"] in a.strategies.split(",")]
    done = set()
    if os.path.exists(a.out) and not a.redo:
        for line in open(a.out, encoding="utf-8"):
            try:
                d = json.loads(line)
                if d.get("status") != "error":
                    done.add(d["pair_id"])
            except ValueError:
                continue

    t0 = time.time()
    for c in coins:
        print(f"data {c['venue_symbol']}: {prepare(c, a.cache, refresh=a.refresh_data)}", flush=True)
    if any(r["base_id"] in ("relative_strength", "sector_rotation") for r in rows):
        btc = next((c for c in uni["selected"] if c["venue_symbol"] == BENCHMARK_SYMBOL), None)
        if btc:
            prepare(btc, a.cache)
    print(f"data ready in {time.time() - t0:.0f}s", flush=True)

    from .backtest import pair_id
    tasks = [(r["strategy_id"], c, a.cache) for c in coins for r in rows
             if pair_id(r["strategy_id"], c["venue_symbol"]) not in done]
    print(f"{len(tasks)} pairs to run ({len(done)} already done) on {a.workers} workers", flush=True)
    counts: dict[str, int] = {}
    t1 = time.time()
    with open(a.out, "a", encoding="utf-8") as out, mp.get_context("spawn").Pool(a.workers) as pool:
        for i, res in enumerate(pool.imap_unordered(_work, tasks, chunksize=2), 1):
            out.write(json.dumps(res, default=str) + "\n")
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            if i % 200 == 0 or i == len(tasks):
                out.flush()
                el = time.time() - t1
                print(f"  {i}/{len(tasks)} in {el:.0f}s ({el / i:.2f}s each) {counts}", flush=True)
    print(f"sweep done in {time.time() - t0:.0f}s: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
