"""Backtests of the QuantConnect re-implementations (STEP 5). Windows fixed before results were seen; nothing tuned.

  crypto (QC-11340, QC-13690, QC-15987, QC-18379, QC-13509)
    BTC/USDT spot  dev 2018-01-01 .. 2022-12-31   oos 2023-01-01 .. 2026-10-30
    ETH/USDT spot  dev 2021-01-01 .. 2022-12-31   oos 2023-01-01 .. 2026-07-18
    BTC perp       oos 2023-01-01 .. 2026-10-30   (ADAPTATION for the long/short ones: Delta costs + funding)
  QC-20960 gold sweep (XAUUSD; the author backtested 2021-01-01 .. 2026-06-01)
    pre    2010-01-01 .. 2020-12-31   data the author's post does not show (out of sample for the author's design)
    author 2021-01-01 .. 2026-05-31   the author's own window (reproduces the author-reported claim; in sample)
    post   2026-06-01 .. 2026-10-30   after the post (forward, small)
  QC-5079 gold timing (GLD in the source; XAUUSD spot here = ADAPTATION)
    dev 2010-01-01 .. 2017-12-31   oos 2018-01-01 .. 2026-10-30

    python -I ws_run_qc.py        writes results/qc_backtests.json; trades to D:/Strategy-Web-Sources/results/trades/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_engine as E  # noqa: E402
import ws_run as R  # noqa: E402
import ws_strategies as S  # noqa: E402

SIG = Path(r"D:\Strategy-Web-Sources\signals_qc")
OUT = HERE / "results" / "qc_backtests.json"
ts = R.ts
CW = {"BTC_USDT": {"dev": (ts("2018-01-01"), ts("2023-01-01")), "oos": (ts("2023-01-01"), ts("2026-10-31"))},
      "ETH_USDT": {"dev": (ts("2021-01-01"), ts("2023-01-01")), "oos": (ts("2023-01-01"), ts("2026-07-19"))}}
GW_SWEEP = {"pre": (ts("2010-01-01"), ts("2021-01-01")), "author": (ts("2021-01-01"), ts("2026-06-01")),
            "post": (ts("2026-06-01"), ts("2026-10-31"))}
GW_TIMING = {"dev": (ts("2010-01-01"), ts("2018-01-01")), "oos": (ts("2018-01-01"), ts("2026-10-31"))}


def load(sid: str, market: str) -> tuple[dict, dict]:
    z = np.load(SIG / f"{sid}__{market}.npz")
    s = json.loads((SIG / f"{sid}.settings.json").read_text(encoding="utf-8"))
    return {k: z[k] for k in z.files}, s


def windows(tr: list[dict], W: dict) -> dict:
    return {k: E.stats(tr, a, b) for k, (a, b) in W.items()}


def qc_13509(m: E.Minutes, market: str) -> list[dict]:
    """RSI(14, simple averages) < 25 and close < SMA50 (daily) -> buy at the next open; stop market at 0.96 x fill,
    then 0.96 x the highest daily CLOSE since entry (the source starts that high at 0, so the first close after entry
    resets the stop even below the first one); the stop fills at its level, or at the open if the day opens below."""
    b = S.bars(m, "1D")
    r, sma = S.rsi_simple(b["c"], 14).to_numpy(), b["c"].rolling(50).mean().to_numpy()
    o, h, l, c, t0 = (b[k].to_numpy() for k in ("o", "h", "l", "c", "t0"))
    cost = E.COSTS["spot"]
    out, i, n = [], 50, len(b)
    while i < n - 1:
        if r[i] < 25 and sma[i] > c[i]:
            j = i + 1
            P0, stop, hi = o[j], o[j] * 0.96, 0.0
            k = j
            exit_px = None
            while k < n:
                if k > j and o[k] <= stop:
                    exit_px = o[k]
                    break
                if l[k] <= stop:
                    exit_px = stop
                    break
                if c[k] > hi:                                 # updated at the day's close, used from the next day
                    hi = c[k]
                    stop = c[k] * 0.96
                k += 1
            if exit_px is None:
                k, exit_px = n - 1, c[n - 1]
            gross = (exit_px - P0) / P0
            net = gross - 2 * (cost.fee + cost.slip)
            out.append({"side": 1, "entry_t": int(t0[j]), "exit_t": int(t0[k]) + 86400, "entry": float(P0),
                        "exit": float(exit_px), "why": "TRAIL", "gross": gross, "funding": 0.0, "net": net,
                        "pnl": net * E.NOTIONAL, "hold_min": (int(t0[k]) + 86400 - int(t0[j])) / 60})
            i = k + 1
        else:
            i += 1
    return out


def main() -> None:
    res = {}
    mins = {"BTC_USDT": E.Minutes("BTC/USDT"), "ETH_USDT": E.Minutes("ETH/USDT")}
    for sid in ["QC-11340", "QC-13690", "QC-15987", "QC-18379"]:
        res[sid] = {}
        for mk, m in mins.items():
            sig, s = load(sid, mk)
            a, b = CW[mk]["dev"][0], CW[mk]["oos"][1]
            tr = E.simulate(sig, s, m, E.COSTS["spot"], a, b)
            R.save_trades(sid, f"{mk}_spot", tr)
            res[sid][f"{mk}_spot"] = {**windows(tr, CW[mk]), "yearly": R.yearly(tr)}
            if mk == "BTC_USDT":
                trx = E.simulate(sig, s, m, E.COSTS["spot_x2"], *CW[mk]["oos"])
                res[sid]["BTC_USDT_spot_x2_oos"] = E.stats(trx, *CW[mk]["oos"])
                if s.get("can_short"):
                    trp = E.simulate(sig, s, m, E.COSTS["perp"], *CW[mk]["oos"])
                    res[sid]["BTC_perp_adaptation_oos"] = E.stats(trp, *CW[mk]["oos"])
        d, o = res[sid]["BTC_USDT_spot"]["dev"], res[sid]["BTC_USDT_spot"]["oos"]
        print(f"{sid:10} BTC dev {d.get('trades', 0):>5} tr {d.get('net', 0):>10.0f}$  oos {o.get('trades', 0):>5} tr {o.get('net', 0):>10.0f}$")
    res["QC-13509"] = {}
    for mk, m in mins.items():
        tr = qc_13509(m, mk)
        R.save_trades("QC-13509", f"{mk}_spot", tr)
        res["QC-13509"][f"{mk}_spot"] = {**windows(tr, CW[mk]), "yearly": R.yearly(tr)}
    d, o = res["QC-13509"]["BTC_USDT_spot"]["dev"], res["QC-13509"]["BTC_USDT_spot"]["oos"]
    print(f"QC-13509   BTC dev {d.get('trades', 0):>5} tr {d.get('net', 0):>10.0f}$  oos {o.get('trades', 0):>5} tr {o.get('net', 0):>10.0f}$")
    g = E.GoldMinutes()
    for sid, W in [("QC-20960", GW_SWEEP), ("QC-5079", GW_TIMING)]:
        sig, s = load(sid, "XAUUSD")
        a, b = min(x[0] for x in W.values()), max(x[1] for x in W.values())
        tr = E.simulate(sig, s, g, E.COSTS_GOLD["gold"], a, b)
        R.save_trades(sid, "XAUUSD", tr)
        trx = E.simulate(sig, s, g, E.COSTS_GOLD["gold_x2"], a, b)
        res[sid] = {"XAUUSD": {**windows(tr, W), "yearly": R.yearly(tr)}, "XAUUSD_x2": windows(trx, W)}
        print(sid, {k: (v.get("trades"), round(v.get("net", 0) or 0)) for k, v in res[sid]["XAUUSD"].items() if k != "yearly"})
    res["_meta"] = {"costs": {**{k: c.label for k, c in E.COSTS.items()}, **{k: c.label for k, c in E.COSTS_GOLD.items()}},
                    "notional_usd": E.NOTIONAL,
                    "windows": {"crypto": {k: {w: [pd.Timestamp(x, unit='s', tz='UTC').date().isoformat() for x in v] for w, v in d.items()} for k, d in CW.items()},
                                "QC-20960": {w: [pd.Timestamp(x, unit='s', tz='UTC').date().isoformat() for x in v] for w, v in GW_SWEEP.items()},
                                "QC-5079": {w: [pd.Timestamp(x, unit='s', tz='UTC').date().isoformat() for x in v] for w, v in GW_TIMING.items()}}}
    OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
