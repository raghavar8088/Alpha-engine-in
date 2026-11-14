"""Backtests of the imported freqtrade strategies (STEP 5): their own signals (ws_ft_signals.py), our fills and costs
(ws_engine.py). Development and out-of-sample windows are fixed here BEFORE any result is seen, and nothing is tuned:
the strategies run with the parameters their authors shipped. The sensitivity rows only perturb the shipped stop and
ROI by +-25% to show how fragile a result is; they are never used to pick settings.

  BTC/USDT spot  dev 2018-01-01 .. 2022-12-31   oos 2023-01-01 .. 2026-10-30   (Binance spot 1m, the original market)
  ETH/USDT spot  dev 2021-01-01 .. 2022-12-31   oos 2023-01-01 .. 2026-07-18   (a second pair: robustness)
  BTC perp       dev 2020-01-01 .. 2022-12-31   oos 2023-01-01 .. 2026-10-30   (ADAPTATION: Delta India costs + funding;
                                                                               spot prices as the perpetual's proxy)
  stress         BTC spot oos at twice the costs
  sensitivity    BTC spot dev and oos with stoploss x0.75 / x1.25 and ROI x0.75 / x1.25

    python -I ws_run.py [Class,Class,...]

Writes results/freqtrade_backtests.json (repository) and the trade lists to D:/Strategy-Web-Sources/results/trades/.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_engine as E  # noqa: E402

SIG = Path(r"D:\Strategy-Web-Sources\signals")
TRADES = Path(r"D:\Strategy-Web-Sources\results\trades")
OUT = HERE / "results" / "freqtrade_backtests.json"
BATCH = ["BinHV45", "Low_BB", "Scalp", "SmoothScalp", "CCIStrategy", "ClucMay72018", "CombinedBinHAndCluc", "BinHV27",
         "CofiBitStrategy", "EMASkipPump", "MACDStrategy", "MultiRSI", "Quickie", "SmoothOperator", "Strategy005",
         "UniversalMACD", "CMCWinner", "Bandtastic", "FAdxSmaStrategy"]
VARIATIONS = {"MACDStrategy_crossed": "MACDStrategy", "ReinforcedQuickie": "Quickie", "ReinforcedSmoothScalp": "SmoothScalp"}


def ts(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp())


WIN = {
    "BTC/USDT": {"dev": (ts("2018-01-01"), ts("2023-01-01")), "oos": (ts("2023-01-01"), ts("2026-10-31"))},
    "ETH/USDT": {"dev": (ts("2021-01-01"), ts("2023-01-01")), "oos": (ts("2023-01-01"), ts("2026-07-19"))},
    "PERP": {"dev": (ts("2020-01-01"), ts("2023-01-01")), "oos": (ts("2023-01-01"), ts("2026-10-31"))},
}


def yearly(trades: list[dict]) -> dict:
    out: dict[str, float] = {}
    for x in trades:
        y = str(pd.Timestamp(x["entry_t"], unit="s", tz="UTC").year)
        out[y] = out.get(y, 0.0) + x["pnl"]
    return {k: round(v, 2) for k, v in sorted(out.items())}


def save_trades(name: str, tag: str, trades: list[dict]) -> None:
    TRADES.mkdir(parents=True, exist_ok=True)
    with open(TRADES / f"{name}__{tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["side", "entry_utc", "exit_utc", "entry", "exit", "why", "gross", "funding", "net", "pnl"])
        for x in trades:
            w.writerow([x["side"], pd.Timestamp(x["entry_t"], unit="s", tz="UTC").isoformat(),
                        pd.Timestamp(x["exit_t"], unit="s", tz="UTC").isoformat(), round(x["entry"], 4),
                        round(x["exit"], 4), x["why"], round(x["gross"], 6), round(x["funding"], 6), round(x["net"], 6),
                        round(x["pnl"], 2)])


def run_one(name: str, mins: dict) -> dict:
    t0 = time.time()
    res: dict = {"class": name}
    sig, s = E.load_signals(SIG, name, "BTC/USDT")
    res["settings"] = {k: s.get(k) for k in ["timeframe", "minimal_roi", "stoploss", "trailing_stop", "trailing_stop_positive",
                                              "trailing_stop_positive_offset", "trailing_only_offset_is_reached",
                                              "use_exit_signal", "exit_profit_only", "exit_profit_offset",
                                              "ignore_roi_if_entry_signal", "can_short", "callbacks", "mode"]}
    a, b = WIN["BTC/USDT"]["dev"][0], WIN["BTC/USDT"]["oos"][1]
    tr = E.simulate(sig, s, mins["BTC/USDT"], E.COSTS["spot"], a, b)
    save_trades(name, "BTC_spot", tr)
    res["btc_spot"] = {"dev": E.stats(tr, *WIN["BTC/USDT"]["dev"]), "oos": E.stats(tr, *WIN["BTC/USDT"]["oos"]),
                       "full": E.stats(tr, a, b), "yearly": yearly(tr)}
    # ETH spot
    try:
        sig_e, s_e = E.load_signals(SIG, name, "ETH/USDT")
        a2, b2 = WIN["ETH/USDT"]["dev"][0], WIN["ETH/USDT"]["oos"][1]
        tre = E.simulate(sig_e, s_e, mins["ETH/USDT"], E.COSTS["spot"], a2, b2)
        save_trades(name, "ETH_spot", tre)
        res["eth_spot"] = {"dev": E.stats(tre, *WIN["ETH/USDT"]["dev"]), "oos": E.stats(tre, *WIN["ETH/USDT"]["oos"]),
                           "yearly": yearly(tre)}
    except FileNotFoundError as e:
        res["eth_spot"] = {"error": str(e)}
    # perpetual adaptation (BTC, from 2020 when funding exists)
    a3, b3 = WIN["PERP"]["dev"][0], WIN["PERP"]["oos"][1]
    trp = E.simulate(sig, s, mins["BTC/USDT"], E.COSTS["perp"], a3, b3)
    save_trades(name, "BTC_perp", trp)
    res["btc_perp_adaptation"] = {"dev": E.stats(trp, *WIN["PERP"]["dev"]), "oos": E.stats(trp, *WIN["PERP"]["oos"])}
    # stress: twice the spot costs, out of sample
    trx = E.simulate(sig, s, mins["BTC/USDT"], E.COSTS["spot_x2"], *WIN["BTC/USDT"]["oos"])
    res["btc_spot_x2_oos"] = E.stats(trx, *WIN["BTC/USDT"]["oos"])
    # sensitivity of the shipped exits (never used to choose settings)
    sens = {}
    for lab, kw in {"stop x0.75": {"stop_scale": 0.75}, "stop x1.25": {"stop_scale": 1.25},
                    "roi x0.75": {"roi_scale": 0.75}, "roi x1.25": {"roi_scale": 1.25}}.items():
        trs = E.simulate(sig, s, mins["BTC/USDT"], E.COSTS["spot"], a, b, **kw)
        d, o = E.stats(trs, *WIN["BTC/USDT"]["dev"]), E.stats(trs, *WIN["BTC/USDT"]["oos"])
        sens[lab] = {"dev_net": d.get("net"), "dev_trades": d.get("trades"), "oos_net": o.get("net"), "oos_trades": o.get("trades")}
    res["sensitivity_btc_spot"] = sens
    res["seconds"] = round(time.time() - t0, 1)
    d, o = res["btc_spot"]["dev"], res["btc_spot"]["oos"]
    print(f"{name:24} dev {d.get('trades', 0):>6} tr {d.get('net', 0):>11.0f}$  oos {o.get('trades', 0):>6} tr "
          f"{o.get('net', 0):>11.0f}$  ({res['seconds']}s)", flush=True)
    return res


def main(argv: list[str]) -> None:
    names = argv[0].split(",") if argv else BATCH + list(VARIATIONS)
    mins = {"BTC/USDT": E.Minutes("BTC/USDT"), "ETH/USDT": E.Minutes("ETH/USDT")}
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"results": {}}
    for n in names:
        if (SIG / f"{n}.settings.json").exists():
            old["results"][n] = run_one(n, mins)
            OUT.write_text(json.dumps(old, indent=1, default=str), encoding="utf-8")   # checkpoint after each
        else:
            print(f"{n:24} no signals (see signals/{n}.error.txt)")
    old["windows"] = {k: {w: [pd.Timestamp(x, unit='s', tz='UTC').date().isoformat() for x in v] for w, v in d.items()}
                      for k, d in WIN.items()}
    old["costs"] = {k: c.label for k, c in E.COSTS.items()}
    old["notional_usd"] = E.NOTIONAL
    OUT.write_text(json.dumps(old, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
