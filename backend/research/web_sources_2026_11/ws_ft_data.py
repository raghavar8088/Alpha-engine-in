"""Freqtrade-format candle files from the repository's own Binance data (no download).

Source: antigravity engine/data/historical/deep/BTCUSDT_1m.csv (Binance Vision spot 1m klines 2017-08-17 -> 2026-10-30,
SHA-256 verified by the BTC deep-backtest study; time = candle OPEN in unix seconds) and ETHUSDT_1m.json (2021-01 ->
2026-07). Writes <datadir>/binance/<PAIR>-<tf>.feather with freqtrade's columns (date UTC = candle open, open, high,
low, close, volume). Higher timeframes are resampled from 1m with label=left / closed=left, as exchanges build them;
a candle is written only if at least one minute exists in it (freqtrade fills the rest on load).

    <venv python> -I ws_ft_data.py <datadir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HIST = Path(r"D:\INDIAN MARKET\antigravity-main\antigravity-main\engine\data\historical")
TFS = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h",
       "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1D"}


def load_btc() -> pd.DataFrame:
    df = pd.read_csv(HIST / "deep" / "BTCUSDT_1m.csv", usecols=["time", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.drop(columns="time")


def load_eth() -> pd.DataFrame:
    rows = json.loads((HIST / "ETHUSDT_1m.json").read_text())
    df = pd.DataFrame(rows).rename(columns={"time": "t"})
    df["date"] = pd.to_datetime(df["t"], unit="s", utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


def write(df: pd.DataFrame, pair: str, out: Path) -> None:
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    s = df.set_index("date")
    for tf, rule in TFS.items():
        if tf == "1m":
            r = s
        else:
            r = s.resample(rule, label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
        r = r.reset_index()[["date", "open", "high", "low", "close", "volume"]]
        p = out / f"{pair.replace('/', '_')}-{tf}.feather"
        r.to_feather(p)
        print(f"{pair} {tf:4} {len(r):>9} candles {r['date'].iloc[0]} -> {r['date'].iloc[-1]}")


def main(datadir: Path) -> None:
    out = datadir / "binance"
    out.mkdir(parents=True, exist_ok=True)
    write(load_btc(), "BTC/USDT", out)
    write(load_eth(), "ETH/USDT", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
