"""Entry / exit signals of freqtrade strategies, computed by each strategy's OWN code (fidelity to the source).

Runs in the isolated freqtrade venv only (D:/Strategy-Web-Sources/venv-ft), after the static review in
registry/freqtrade_inventory.json found no network, process or file access in the strategy files. The strategy is
loaded by freqtrade's StrategyResolver (which maps interface-2 buy/sell columns to enter/exit), the candles come from
freqtrade's own loader (missing candles filled as in backtesting), and indicators and signals are produced exactly as
freqtrade's backtester produces them (advise_all_indicators + ft_advise_signals). Informative pairs are served by a
backtest-mode DataProvider from the same local files. No exchange object, no network.

Writes, per strategy and pair, <out>/<Class>__<PAIR>.npz (candle open times in unix seconds, tf minutes, enter/exit
long and short as int8) and <out>/<Class>.settings.json (the exit settings freqtrade would apply). Fills, exits and
costs are NOT simulated here: ws_engine.py does that on 1-minute bars.

    <venv python> -I ws_ft_signals.py <clone root> <datadir> <out dir> <pair[,pair]> <Class> [<Class> ...]
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from freqtrade.configuration import TimeRange  # noqa: F401  (kept for parity with freqtrade's loaders)
from freqtrade.data.dataprovider import DataProvider
from freqtrade.data.history import load_pair_history
from freqtrade.enums import CandleType, RunMode
from freqtrade.resolvers import StrategyResolver
from freqtrade.strategy.interface import IStrategy

HERE = Path(__file__).resolve().parent
INV = json.loads((HERE / "registry" / "freqtrade_inventory.json").read_text(encoding="utf-8"))
TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
          "12h": 720, "1d": 1440}


def overridden(strategy: IStrategy, name: str) -> bool:
    return getattr(type(strategy), name, None) is not getattr(IStrategy, name, None)


def run(root: Path, datadir: Path, out: Path, pairs: list[str], name: str) -> None:
    rec = next(r for r in INV["strategies"] if r.get("class") == name)
    # a strategy that can short must run in futures mode (freqtrade refuses it on spot); its candles are the SPOT
    # candles under the perpetual's name (BTC/USDT:USDT): spot price as the perpetual's price, basis ignored (labelled)
    fut = bool(rec.get("shorts"))
    ctype = CandleType.FUTURES if fut else CandleType.SPOT
    pairs = [p + ":USDT" if fut and ":" not in p else p for p in pairs]
    config = {
        "strategy": name, "strategy_path": str((root / rec["file"]).parent), "datadir": datadir / "binance",
        "user_data_dir": datadir.parent, "exchange": {"name": "binance", "pair_whitelist": pairs},
        "stake_currency": "USDT", "stake_amount": "unlimited", "max_open_trades": 1, "dry_run": True,
        "runmode": RunMode.BACKTEST, "trading_mode": "futures" if fut else "spot", "margin_mode": "isolated" if fut else "",
        "candle_type_def": ctype,
        "dataformat_ohlcv": "feather", "pairlists": [{"method": "StaticPairList"}], "entry_pricing": {}, "exit_pricing": {},
    }
    strategy = StrategyResolver.load_strategy(config)
    config["timeframe"] = strategy.timeframe
    strategy.dp = DataProvider(config, None)
    strategy.ft_bot_start()
    tf = TF_MIN[strategy.timeframe]
    settings = {k: getattr(strategy, k, None) for k in
                ["timeframe", "minimal_roi", "stoploss", "trailing_stop", "trailing_stop_positive",
                 "trailing_stop_positive_offset", "trailing_only_offset_is_reached", "use_exit_signal", "exit_profit_only",
                 "exit_profit_offset", "ignore_roi_if_entry_signal", "can_short", "startup_candle_count",
                 "process_only_new_candles", "position_adjustment_enable", "use_custom_stoploss"]}
    settings["minimal_roi"] = {str(k): float(v) for k, v in (settings["minimal_roi"] or {}).items()}
    settings["callbacks"] = [m for m in ("custom_stoploss", "custom_exit", "custom_entry_price", "custom_exit_price",
                                         "adjust_trade_position", "confirm_trade_entry", "confirm_trade_exit", "leverage")
                             if overridden(strategy, m)]
    settings["interface_version"] = getattr(strategy, "INTERFACE_VERSION", None)
    settings["file"] = rec["file"]
    settings["mode"] = "futures (spot candles as the perpetual's price proxy)" if fut else "spot"
    settings["pairs"] = {}
    for pair in pairs:
        t0 = time.time()
        df = load_pair_history(datadir=datadir / "binance", timeframe=strategy.timeframe, pair=pair,
                               data_format="feather", candle_type=ctype, fill_up_missing=True)
        if df.empty:
            settings["pairs"][pair] = {"error": "no data"}
            continue
        ind = strategy.advise_all_indicators({pair: df})[pair]
        sig = strategy.ft_advise_signals(ind, {"pair": pair})
        cols = {}
        for c in ("enter_long", "exit_long", "enter_short", "exit_short"):
            v = sig[c].fillna(0).to_numpy() if c in sig else np.zeros(len(sig))
            cols[c] = (v == 1).astype(np.int8)
        # unit-independent (freqtrade's frames are datetime64[ms, UTC] under pandas 3, [ns] under older pandas)
        tsec = ((sig["date"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
        # a filled candle (no trades in it) cannot be traded on: mark it so the engine skips those signals
        filled = (sig["volume"].to_numpy() == 0).astype(np.int8)
        # ':' must not reach a Windows file name (it would write an NTFS alternate data stream)
        np.savez_compressed(out / f"{name}__{pair.replace('/', '_').replace(':', '_')}.npz", t=tsec.astype(np.int64), tf=np.int64(tf),
                            filled=filled, **cols)
        settings["pairs"][pair] = {"candles": int(len(sig)), "first": str(sig['date'].iloc[0]), "last": str(sig['date'].iloc[-1]),
                                   "enter_long": int(cols["enter_long"].sum()), "exit_long": int(cols["exit_long"].sum()),
                                   "enter_short": int(cols["enter_short"].sum()), "exit_short": int(cols["exit_short"].sum()),
                                   "seconds": round(time.time() - t0, 1)}
        print(f"{name:26} {pair:9} tf={strategy.timeframe:4} candles={len(sig):>8} enterL={cols['enter_long'].sum():>7} "
              f"exitL={cols['exit_long'].sum():>8} enterS={cols['enter_short'].sum():>6} ({time.time() - t0:.0f}s)", flush=True)
    (out / f"{name}.settings.json").write_text(json.dumps(settings, indent=1, default=str), encoding="utf-8")


def main(argv: list[str]) -> None:
    root, datadir, out = Path(argv[0]), Path(argv[1]), Path(argv[2])
    pairs = argv[3].split(",")
    out.mkdir(parents=True, exist_ok=True)
    for name in argv[4:]:
        try:
            run(root, datadir, out, pairs, name)
        except Exception as e:  # noqa: BLE001
            (out / f"{name}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            print(f"{name:26} ERROR {type(e).__name__}: {str(e)[:160]}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
