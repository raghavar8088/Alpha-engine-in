"""Index intraday research: publish the results to the module (the Strategy Dashboard reads them).

    python backend/research/index_intraday_2026_10/ii_catalog.py

Writes backend/app/services/index_intraday/catalog.json: every registered trial with its
selection / validation / combined metrics, its STATUS and, when it is not Validated, the FIRST
gate it failed (with the number), plus the stage-3 measurements for the ones that got there,
and monthly net returns for the strongest ~100 (equity curves in the Backtesting Lab).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import sys
_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "shared", _ROOT / "backend"):
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ii_final import load_returns  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = _ROOT / "backend" / "app" / "services" / "index_intraday" / "catalog.json"
FAMILY_LABELS = {
    "orb": "Opening-range breakout", "pdhl": "Previous-day high/low breakout", "volbreak": "Volatility breakout",
    "imom": "Intraday momentum (first to last half hour)", "ema": "EMA crossover", "supertrend": "Supertrend (+ADX filter)",
    "rsi": "RSI momentum / mean reversion", "bollinger": "Bollinger Bands", "vwap": "VWAP (index: TWAP)",
    "pullback": "Trend pullback", "mtf": "Multi-timeframe confirmation", "regime": "VIX regime switch",
    "gap": "Gap fade / follow", "trendday": "Trend-day continuation",
}
EXIT_LABELS = {"eod": "held to the 15:12 square-off", "r2": "0.5 ATR stop, 2R target", "trail": "0.5 ATR stop, 0.5 ATR trail",
               "atr_eod": "0.5 ATR stop, else square-off", "sig": "0.75 ATR stop, signal exit",
               "sig_nostop": "signal exit only", "time60": "0.5 ATR stop, signal exit, 60-minute limit",
               "trail_wide": "0.75 ATR stop, 1 ATR trail"}
CORE = ["trades", "trades_per_day", "win_rate", "mean_net_bp", "mean_gross_bp", "t_trade", "profit_factor",
        "expectancy_bp", "rr", "ann_bp", "sharpe", "sortino", "max_dd_bp", "months_positive", "avg_month_bp",
        "years_positive", "years"]
BRIEF = ["trades", "win_rate", "mean_net_bp", "mean_gross_bp", "profit_factor", "sharpe", "max_dd_bp", "years_positive"]
VAL_BRIEF = ["trades", "mean_net_bp", "sharpe"]


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 4)


def history_starts() -> dict[str, str]:
    """Each index's first stored session (Angel's 1-minute history is shorter for some)."""
    from app.services.index_intraday.data import load
    out = {}
    for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYNXT50", "NIFTY100", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        try:
            out[idx] = str(load(idx).dates[0])
        except FileNotFoundError:
            pass
    return out


def first_failure(r: pd.Series, starts: dict[str, str] | None = None) -> str:
    begins = (starts or {}).get(r["index"])
    if begins and begins > "2021-12-31":
        return (f"no data: {r['index']}'s 1-minute history begins {begins}, after the 2016-21 selection period — "
                f"it could not be put through the protocol")
    if not r.get("sel_trades") or r["sel_trades"] < 150:
        return f"selection: {int(r.get('sel_trades') or 0)} trades (needs 150)"
    if r["sel_mean_net_bp"] < 1.0:
        return f"selection: {r['sel_mean_net_bp']:+.2f} bp a trade after costs (needs +1.00)"
    if r["sel_sharpe"] < 0.5:
        return f"selection: Sharpe {r['sel_sharpe']:.2f} (needs 0.50)"
    if r["sel_profit_factor"] < 1.10:
        return f"selection: profit factor {r['sel_profit_factor']:.2f} (needs 1.10)"
    if r["sel_years_positive"] < 4:
        return f"selection: positive in {int(r['sel_years_positive'])} of 6 years (needs 4)"
    if not r["sel15_mean_net_bp"] > 0:
        return f"selection: {r['sel15_mean_net_bp']:+.2f} bp at 1.5x costs (needs > 0)"
    if not (r["val_mean_net_bp"] > 0 and r["val_sharpe"] > 0 and r["val_profit_factor"] > 1.0):
        return f"validation 2022-23: {r['val_mean_net_bp']:+.2f} bp a trade, Sharpe {r['val_sharpe']:.2f}"
    if r.get("dsr_eff", 0) < 0.95:
        return f"luck: deflated Sharpe {r['dsr_eff']:.3f} (needs 0.950)"
    if r.get("etf_2023_net_bp") is None or not r.get("etf_2023_net_bp", -1) > 0:
        return f"tradability: {r.get('etf_2023_net_bp', float('nan')):+.2f} bp a trade run on the ETF itself, 2020-23"
    if r.get("breadth_pos", 0) < 2:
        return f"breadth: positive on {int(r.get('breadth_pos') or 0)} related indexes (needs 2)"
    if not r.get("wf_bp", 0) > 0:
        return "walk-forward: re-optimising every 6 months lost money"
    return "neighbours: nearby parameters do not hold up"


def assign_ids(reg: pd.DataFrame) -> dict[str, str]:
    """Ids never move. The 1,208 trials first published (run 1, rounds 1-3) keep the ids they were
    given then — ii0001.. in (index, family, key) order of that run's record — and every trial
    registered since takes the next number, in (round, index, family, key) order. A deployment or a
    journal entry that names an id keeps meaning the same strategy."""
    first = pd.read_csv(HERE / "data" / "run1_uncorrected_data" / "stage3.csv", usecols=["key", "index", "family"])
    ids = {f"{r['key']}@{r['index']}": f"ii{n:04d}"
           for n, (_, r) in enumerate(first.sort_values(["index", "family", "key"]).iterrows(), 1)}
    nxt = len(ids) + 1
    for _, r in reg.sort_values(["round", "index", "family", "key"]).iterrows():
        tag = f"{r['key']}@{r['index']}"
        if tag not in ids:
            ids[tag] = f"ii{nxt:04d}"
            nxt += 1
    return ids


def main() -> None:
    reg = pd.read_csv(HERE / "data" / "stage3.csv")
    rets = load_returns()
    real = reg[reg["sv_trades"].fillna(0) >= 100].copy()
    top = set(real.sort_values("sv_sharpe", ascending=False).head(100)["key"] + "@" + real.sort_values(
        "sv_sharpe", ascending=False).head(100)["index"])
    top |= set(reg[reg["stage2"]]["key"] + "@" + reg[reg["stage2"]]["index"])
    for (fam, idx), g in real[real["index"].isin(["NIFTY", "BANKNIFTY", "SENSEX"])].groupby(["family", "index"]):
        b = g.sort_values("sv_sharpe", ascending=False).iloc[0]
        top.add(f"{b['key']}@{idx}")
    starts = history_starts()
    ids = assign_ids(reg)
    out = []
    for _, r in reg.sort_values(["index", "family", "key"]).iterrows():
        p = json.loads(r["params"])
        rec = {
            "id": ids[f"{r['key']}@{r['index']}"], "key": r["key"], "family": r["family"], "family_label": FAMILY_LABELS.get(r["family"], r["family"]),
            "params": p, "exit": r["exit"], "exit_label": EXIT_LABELS.get(r["exit"], r["exit"]), "index": r["index"],
            "round": int(r["round"]), "status": "Validated" if bool(r.get("validated")) else "Backtested",
            "stage1": bool(r["stage1"]), "stage2": bool(r["stage2"]),
            "failed": None if bool(r.get("validated")) else first_failure(r, starts),
            "sel": {k: _num(r.get(f"sel_{k}")) for k in (CORE if r["stage1"] else BRIEF)},
            "val": {k: _num(r.get(f"val_{k}")) for k in (CORE if r["stage1"] else VAL_BRIEF)},
            "sv": {k: _num(r.get(f"sv_{k}")) for k in (CORE if r["stage1"] else BRIEF)},
            "dsr": _num(r.get("dsr_eff")), "dsr_raw": _num(r.get("dsr_raw")),
        }
        if bool(r["stage2"]):
            rec["stage3"] = {k: _num(r.get(k)) for k in ("nb_median_sharpe", "breadth_pos", "breadth_tested", "wf_bp",
                                                         "idx_2023_net_bp", "idx_2023_trades", "etf_2023_net_bp",
                                                         "etf_2023_gross_bp", "etf_2023_trades", "mc_p_losing_year",
                                                         "mc_median_year_bp", "mc_p5_year_bp", "mc_dd95_bp")}
        tag = f"{r['key']}@{r['index']}"
        if tag in top and r["index"] in rets and r["key"] in rets[r["index"]].columns:
            s = rets[r["index"]][r["key"]]
            m = s.groupby(s.index.to_period("M")).sum()
            rec["monthly"] = [[str(k), round(float(v), 2)] for k, v in m.items()]
        out.append(rec)
    summ = json.loads((HERE / "data" / "stage3_summary.json").read_text(encoding="utf-8"))
    doc = {
        "generated": date.today().isoformat(), "trials": len(reg), "trials_100_trades": int(len(real)),
        "effective_trials": int(round(summ["effective_trials"])), "luck_sharpe": summ["luck_sharpe"],
        "validated": int(reg["validated"].sum()),
        "periods": {"selection": "2016-01-01..2021-12-31", "validation": "2022-01-01..2023-12-31",
                    "holdout": "2024-01-01..2026-10-09 (never opened: no strategy reached it)"},
        "costs": "Angel intraday charges at Rs10 lakh + the research slippage table (bp a side)",
        "history_starts": starts,
        "strategies": out,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} — {len(out)} strategies, {sum('monthly' in s for s in out)} with monthly curves, "
          f"{OUT.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
