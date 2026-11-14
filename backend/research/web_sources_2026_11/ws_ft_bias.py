"""freqtrade's own bias checks on the imported strategies (STEP 4): lookahead-analysis and recursive-analysis.

Runs the freqtrade CLI of the isolated venv on the local candle files (ws_ft_data.py); freqtrade reads Binance's
PUBLIC market list (no account, no key). Each strategy gets a window sized to its timeframe so that enough signals
are checked. lookahead-analysis re-runs the backtest cut at each checked signal and reports signals and indicators
that change when the future is removed; recursive-analysis compares indicator values computed with different
startup-candle counts (a dependence means results depend on where the data starts).

    python -I ws_ft_bias.py [Class,Class,...]       (system python; it calls the venv's freqtrade)

Writes results/freqtrade_bias.json; raw CLI logs go to D:/Strategy-Web-Sources/bias/.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FT = Path(r"D:\Strategy-Web-Sources\venv-ft\Scripts\freqtrade.exe")
ROOT = Path(r"D:\Strategy-Web-Sources\freqtrade\freqtrade-strategies")
UD = Path(r"D:\Strategy-Web-Sources\ft_user_data")
LOGS = Path(r"D:\Strategy-Web-Sources\bias")
OUT = HERE / "results" / "freqtrade_bias.json"
INV = json.loads((HERE / "registry" / "freqtrade_inventory.json").read_text(encoding="utf-8"))
RANGE = {"1m": "20240101-20240201", "5m": "20240101-20240401", "15m": "20240101-20240701", "30m": "20230101-20240101",
         "1h": "20230101-20240701", "4h": "20200101-20240101", "12h": "20190101-20240101", "1d": "20190101-20240101"}
# rare-signal strategies caught too few trades (0/10) in the default window: their busiest calendar year (from our trades)
RANGE_OVERRIDE = {"BinHV45": "20200101-20210101", "Low_BB": "20200101-20210101", "ClucMay72018": "20210101-20220101",
                  "CombinedBinHAndCluc": "20180101-20190101", "UniversalMACD": "20180101-20190101"}


def config(fut: bool, startup: int | None = None) -> Path:
    cfg = {
        "max_open_trades": 1, "stake_currency": "USDT", "stake_amount": "unlimited", "tradable_balance_ratio": 0.99,
        "dry_run": True, "dry_run_wallet": 10000, "trading_mode": "futures" if fut else "spot",
        "margin_mode": "isolated" if fut else "",
        # Bybit's public market list: Binance's exchangeInfo times out from this machine (its small endpoints answer).
        # The exchange only supplies market metadata; the candles are still the local Binance files (datadir).
        "exchange": {"name": "bybit", "key": "", "secret": "",
                     "pair_whitelist": ["BTC/USDT:USDT" if fut else "BTC/USDT"], "pair_blacklist": []},
        "pairlists": [{"method": "StaticPairList"}],
        "entry_pricing": {"price_side": "same", "use_order_book": False, "order_book_top": 1, "price_last_balance": 0.0,
                          "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1}},
        "exit_pricing": {"price_side": "same", "use_order_book": False, "order_book_top": 1},
        "dataformat_ohlcv": "feather", "user_data_dir": str(UD), "datadir": str(UD / "data" / "binance"),
        "internals": {"process_throttle_secs": 5},
    }
    if startup:
        # ANALYSIS-ONLY override: freqtrade's recursive-analysis refuses a strategy whose startup_candle_count is 0
        cfg["startup_candle_count"] = startup
    p = UD / f"config_{'futures' if fut else 'spot'}{'_s' + str(startup) if startup else ''}.json"
    p.write_text(json.dumps(cfg, indent=1))
    return p


def run(cmd: list[str], log: Path) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    txt = r.stdout + "\n" + r.stderr
    log.write_text(txt, encoding="utf-8")
    return txt


def main(argv: list[str]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    names = argv[0].split(",") if argv else []
    by = {r["class"]: r for r in INV["strategies"] if "class" in r}
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"lookahead": {}, "recursive": {}}
    for n in names:
        r = by[n]
        fut = bool(r.get("shorts"))
        tf = r["settings"].get("timeframe", {}).get("value", "5m")
        spath = str((ROOT / r["file"]).parent)
        cfg = str(config(fut))
        pair = "BTC/USDT:USDT" if fut else "BTC/USDT"
        rng = RANGE_OVERRIDE.get(n) or RANGE.get(tf, "20240101-20240401")
        csvp = LOGS / f"{n}_lookahead.csv"
        txt = run([str(FT), "lookahead-analysis", "-c", cfg, "--strategy", n, "--strategy-path", spath, "--timerange", rng,
                   "-p", pair, "--minimum-trade-amount", "10", "--targeted-trade-amount", "20",
                   "--lookahead-analysis-exportfilename", str(csvp)], LOGS / f"{n}_lookahead.log")
        row = None
        if csvp.exists():
            with open(csvp, newline="", encoding="utf-8") as f:
                rows = [x for x in csv.DictReader(f) if x.get("strategy") == n]
            row = rows[-1] if rows else None
        err = None if row else (re.findall(r"(?m)^.*(?:ERROR|Error|error).*$", txt)[-3:] or [txt[-600:]])
        res["lookahead"][n] = {"timerange": rng, "pair": pair, "result": row, "error": err}
        own = r["settings"].get("startup_candle_count", {}).get("value") or 0
        cfg2 = str(config(fut, None if own else 200))
        txt2 = run([str(FT), "recursive-analysis", "-c", cfg2, "--strategy", n, "--strategy-path", spath, "--timerange", rng,
                    "-p", pair, "--startup-candle", "199", "399", "499", "999", "1999"], LOGS / f"{n}_recursive.log")
        # freqtrade prints a table of indicators with the % difference per startup count; keep the table lines
        tbl = [ln for ln in txt2.splitlines() if ln.strip().startswith(("|", "┃", "│", "┏", "┡", "└"))]
        no_var = "No variance on indicator" in txt2 or "no variance" in txt2.lower()
        res["recursive"][n] = {"timerange": rng, "table": tbl[:60], "no_variance_reported": no_var,
                               "strategy_startup_candle_count": own,
                               "analysis_override": None if own else "startup_candle_count 200 set in the analysis config only",
                               "error": None if (tbl or no_var) else txt2[-800:]}
        la = row.get("has_bias") if row else "error"
        print(f"{n:24} lookahead has_bias={la}  recursive rows={len(tbl)} no_variance={no_var}", flush=True)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
