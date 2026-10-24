"""Checks on Unger's portfolio, added after the out-of-sample run (results/diagnostics.json). They are reported,
not used for any verdict, and they read only the locked trade lists:

  contributions   each member's share of the portfolio's out-of-sample result, and long vs short trades
  best months     the portfolio's monthly t-statistic without its best 1 and 3 months
  placebo         2,000 portfolios whose members' trades keep their side, entry minute and holding time but
                  move to random sessions of the out-of-sample window: the timing's share of the result
  drift           buying every session's open and selling its close on each member's market, with the same
                  members and costs: the share that is the markets' own rise
  years           the portfolio's return in each calendar year at 1x and 10x a share

    python ch_diagnostics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import math

import numpy as np
import pandas as pd

import ch_run as R

RES = R.RES


def month_stats(mr: pd.Series) -> dict:
    t = mr.mean() / (mr.std(ddof=1) / math.sqrt(len(mr))) if len(mr) > 1 and mr.std(ddof=1) > 0 else None
    return {"mean": float(mr.mean()), "t": t, "months": int(len(mr))}


def monthly_from_daily(d: pd.Series, months: pd.PeriodIndex) -> pd.Series:
    return (1 + d).groupby(d.index.to_period("M")).prod().reindex(months, fill_value=1.0) - 1


def main() -> None:
    ev = json.loads((RES / "evaluation.json").read_text())
    P = ev["portfolios"]["unger_all_markets"]
    members = [tuple(m.split(":")) for m in P["members"]]
    n = len(members)
    oos = {sym: R.windows(sym, R.market(sym)[0])["OOS"] for sym in {m for m, _ in members}}
    start = min(str(R.market(s)[0]["sess_date"][a]) for s, (a, b) in oos.items())
    end = max(str(R.market(s)[0]["sess_date"][b]) for s, (a, b) in oos.items())
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    trades = {mk: pd.read_csv(RES / "trades" / f"{mk[0]}_{mk[1]}.csv").query("window == 'OOS'") for mk in members}

    def daily(t: pd.DataFrame, col: str = "net_base") -> pd.Series:
        return pd.Series(t[col].values / n, index=pd.to_datetime(t["date"].values)).groupby(level=0).sum()

    port = pd.concat([daily(t) for t in trades.values()], axis=1, sort=True).fillna(0.0).sum(axis=1)
    mr = monthly_from_daily(port, months)
    out = {"members": P["members"], "portfolio_1x": month_stats(mr)}
    # contributions and sides
    contrib = {f"{a}:{b}": {"sum_of_returns_per_share": float(t["net_base"].sum() / n), "trades": int(len(t)),
                            "long_sum": float(t.loc[t["side"] == 1, "net_base"].sum() / n), "short_sum": float(t.loc[t["side"] == -1, "net_base"].sum() / n)}
               for (a, b), t in trades.items()}
    out["contributions"] = dict(sorted(contrib.items(), key=lambda kv: -kv[1]["sum_of_returns_per_share"]))
    out["by_market"] = {}
    for sym in sorted({m for m, _ in members}):
        part = pd.concat([daily(t) for (s, _), t in trades.items() if s == sym], axis=1, sort=True).fillna(0.0).sum(axis=1)
        out["by_market"][sym] = {"members": sum(1 for s, _ in members if s == sym), **month_stats(monthly_from_daily(part, months))}
    # best months
    srt = mr.sort_values(ascending=False)
    out["without_best_1"] = month_stats(mr.drop(srt.index[:1]))
    out["without_best_3"] = month_stats(mr.drop(srt.index[:3]))
    out["best_months"] = {str(k): float(v) for k, v in srt.head(5).items()}
    out["worst_months"] = {str(k): float(v) for k, v in srt.tail(5).items()}
    # placebo: each member's trades moved to random sessions of its out-of-sample window
    sims = 2000
    rng = np.random.default_rng(23)
    sim_daily = np.zeros((sims, len(months)))
    for (sym, fam), t in trades.items():
        D, C, m = R.market(sym)
        a, b = oos[sym]
        MM = R.minute_map(D, m.length)
        side = t["side"].values
        sm_e, sm_x = D["sm"][t["ei"].values].astype(np.int64), D["sm"][t["xi"].values].astype(np.int64)
        days = rng.integers(a, b + 1, size=(sims, len(t)))
        if fam == "unger_bias":
            dur = sm_x - sm_e
            days = np.broadcast_to(t["day"].values, (sims, len(t)))
            s0 = (rng.random((sims, len(t))) * (m.length - dur)).astype(np.int64)
            ei, xi = MM[days, s0], MM[days, np.minimum(s0 + dur, m.length - 1)]
        else:
            ei, xi = MM[days, sm_e], MM[days, sm_x]
        r = np.nan_to_num(R._costed(D, side, ei, xi, R.COSTS[sym]["base"]), nan=0.0) / n
        mon = pd.PeriodIndex(pd.to_datetime(D["sess_date"][days.ravel()]), freq="M")
        pos = months.get_indexer(mon).reshape(days.shape)
        for s in range(sims):          # log-sum per month, then compound
            np.add.at(sim_daily[s], pos[s], np.log1p(r[s]))
    sim_months = np.expm1(sim_daily)
    sim_mean = sim_months.mean(axis=1)
    out["placebo"] = {"sims": sims, "mean_month_placebo_avg": float(sim_mean.mean()), "p_value": float((sim_mean >= mr.mean()).mean()),
                      "note": "placebo months compound each member's trades on random sessions; one trade's return per placement"}
    # drift: every session long from the open to the close, per member's market, same costs
    drift = []
    for sym, fam in members:
        D, C, m = R.market(sym)
        a, b = oos[sym]
        i0 = D["s_start"][a:b + 1]
        x = D["s_end"][a:b + 1] - 1
        r = R._costed(D, np.ones(len(i0)), i0, x, R.COSTS[sym]["base"]) / n
        drift.append(pd.Series(r, index=pd.to_datetime(D["sess_date"][a:b + 1])))
    dd = pd.concat(drift, axis=1, sort=True).fillna(0.0).sum(axis=1)
    out["drift_benchmark"] = month_stats(monthly_from_daily(dd, months))
    # leverage ladder, in- and out-of-sample (each share trades its rule at L x its slice)
    out["leverage"] = {}
    for wn in ("IS", "OOS"):
        tw = {mk: pd.read_csv(RES / "trades" / f"{mk[0]}_{mk[1]}.csv").query("window == @wn") for mk in members}
        pw = pd.concat([daily(t) for t in tw.values()], axis=1, sort=True).fillna(0.0).sum(axis=1)
        mw = pd.period_range(pw.index.min(), pw.index.max(), freq="M")
        yrs = max((pw.index.max() - pw.index.min()).days / 365.25, 1e-9)
        for L in (1, 2, 3, 5, 10):
            eq = (1 + L * pw).cumprod()
            mrl = monthly_from_daily(L * pw, mw)
            out["leverage"][f"{wn}_{L}x"] = {"mean_month": float(mrl.mean()), "median_month": float(mrl.median()), "worst_month": float(mrl.min()),
                                             "max_drawdown": float((eq / eq.cummax() - 1).min()), "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1)}
    # costs: the portfolio's out-of-sample mean month with every cost scaled by k (0 = no costs)
    out["cost_multiple"] = {}
    for k in (0.0, 1.0, 2.0, 3.0, 4.0, 6.0):
        parts = []
        for (sym, fam), t in trades.items():
            D, _, _ = R.market(sym)
            b = R.COSTS[sym]["base"]
            c = R.Costs(f"{k} x base", b.spread * k, b.slippage * k, b.commission * k)
            parts.append(pd.Series(R.net_returns(D, t, c) / n, index=pd.to_datetime(t["date"].values)).groupby(level=0).sum())
        pk = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
        out["cost_multiple"][f"{k:g}x"] = month_stats(monthly_from_daily(pk, months))
    # calendar years
    eq1 = (1 + port).groupby(port.index.year).prod() - 1
    eq10 = (1 + 10 * port).groupby(port.index.year).prod() - 1
    out["years"] = {int(y): {"1x": float(eq1[y]), "10x": float(eq10[y])} for y in eq1.index}
    (RES / "diagnostics.json").write_text(json.dumps(R.jsonable(out), indent=1))
    print(json.dumps(R.jsonable({k: v for k, v in out.items() if k != "contributions"}), indent=1))
    for k, v in out["contributions"].items():
        print(f"  {k:<24} {v['sum_of_returns_per_share'] * 100:+.3f}%  trades {v['trades']:>4}  long {v['long_sum'] * 100:+.3f}%  short {v['short_sum'] * 100:+.3f}%")


if __name__ == "__main__":
    main()
