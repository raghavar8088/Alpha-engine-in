"""Phase 2, step 1: what the option data itself says - on the DISCOVERY period only.

    python analytics.py <work_dir>

Builds an enriched panel (implied vol, delta, the option's value at expiry, the futures path)
for every traded front-month option in the discovery windows, then answers:
  A1 premium map    - selling which delta x days-to-expiry cell made money after costs?
  A2 skew           - does put/call skew at entry predict which side is safer to sell?
  A3 VRP dose       - does a bigger implied/realised gap mean more profit?
  A4 OI walls       - do the max-open-interest strikes hold better than their delta implies?
  A5 weekday        - which days of the week does a short straddle lose on?
  A7 delta-hedged   - a short ATM straddle hedged daily with futures (pure volatility premium)
Statistics are per CYCLE (each monthly expiry is one observation), never per row: the rows of
one cycle share one path and are not independent.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "shared"))
import b76  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

DISCOVERY = {"crude": ("CRUDEOIL", "2020-01-01", "2024-05-31"),
             "natgas": ("NATURALGAS", "2022-03-01", "2024-04-30")}
MINI_MULT = {"crude": 10, "natgas": 250}
RATE = {"crude": 0.311, "natgas": 0.167}
SLIP, TICK = 0.01, 0.05
MAX_TDTE = 22


def ufut_map(fut, sym):
    fexp = np.array(sorted(fut.loc[fut.sym == sym, "expiry"].unique()))
    return lambda e: pd.Timestamp(fexp[fexp >= np.datetime64(e)][0]) if (fexp >= np.datetime64(e)).any() else None


def panel(opt, fut, key):
    """One row per traded front-month option-day (TDTE <= 22) with everything needed downstream."""
    sym, a, b = DISCOVERY[key]
    o = opt[(opt.sym == sym) & (opt.expiry >= a) & (opt.expiry <= b)].copy()
    m = ufut_map(fut, sym)
    o["fexp"] = o.expiry.map({e: m(e) for e in o.expiry.unique()})
    f = fut[(fut.sym == sym)][["expiry", "date", "close", "traded"]].rename(
        columns={"expiry": "fexp", "close": "F", "traded": "ftraded"})
    o = o.merge(f, on=["fexp", "date"], how="inner")
    o = o[o.ftraded]
    # trading days to expiry, per expiry
    tdte = {}
    for e, g in o.groupby("expiry"):
        ds = sorted(d for d in g.date.unique() if d <= e)
        for i, d in enumerate(ds):
            tdte[(e, d)] = len(ds) - 1 - i
    o["tdte"] = [tdte.get(x, -1) for x in zip(o.expiry, o.date)]
    o = o[(o.tdte >= 0) & (o.tdte <= MAX_TDTE)]
    # expiry value: the expiry-day close if that strike traded then, else intrinsic vs the
    # future's expiry-day close
    ex = o[o.date == o.expiry]
    exc = ex[ex.traded].set_index(["expiry", "strike", "cp"]).close
    fexpclose = ex.groupby("expiry").F.first()
    o["F_exp"] = o.expiry.map(fexpclose)
    key3 = list(zip(o.expiry, o.strike, o.cp))
    exp_close = pd.Series([exc.get(k, np.nan) for k in key3], index=o.index)
    intrinsic = np.where(o.cp == "CE", np.maximum(o.F_exp - o.strike, 0), np.maximum(o.strike - o.F_exp, 0))
    o["exit_val"] = exp_close.fillna(pd.Series(intrinsic, index=o.index))
    o = o[o.traded & o.F_exp.notna()].copy()
    T = (o.expiry - o.date).dt.days.clip(lower=0.5) / 365
    o["T"] = T
    o["iv"] = b76.implied_vol(o.close.values, o.F.values, o.strike.values, T.values, (o.cp == "CE").values)
    o["delta"] = b76.delta(o.F.values, o.strike.values, T.values, np.nan_to_num(o.iv.values, nan=0.5), (o.cp == "CE").values)
    o.loc[o.iv.isna(), "delta"] = np.nan
    o["adelta"] = o.delta.abs()
    mult = MINI_MULT[key]
    entry = o.close - np.maximum(TICK, SLIP * o.close)
    exitp = o.exit_val + np.where(o.exit_val > 0, np.maximum(TICK, SLIP * o.exit_val), 0.0)
    fees = [mcx_option_leg(e, mult, sell=True)["total"] + (mcx_option_leg(x, mult, sell=False)["total"] if x > 0 else 0)
            for e, x in zip(entry.values, exitp.values)]
    o["pnl_lot"] = (entry - exitp) * mult - np.array(fees)
    o["margin"] = 1.2 * RATE[key] * o.F * mult
    o["roc"] = o.pnl_lot / o.margin
    o["prem_pct"] = o.close / o.F
    return o


def cycle_stats(df, val="roc"):
    """Average within each cycle first, then across cycles."""
    per = df.groupby("expiry")[val].mean()
    n = len(per)
    if n < 3:
        return pd.Series({"cycles": n, "mean_roc_%": np.nan, "t": np.nan, "pos_cycles_%": np.nan, "worst_cycle_%": np.nan})
    t = per.mean() / (per.std(ddof=1) / math.sqrt(n)) if per.std(ddof=1) > 0 else np.nan
    return pd.Series({"cycles": n, "mean_roc_%": per.mean() * 100, "t": t, "pos_cycles_%": (per > 0).mean() * 100,
                      "worst_cycle_%": per.min() * 100})


def a1_premium_map(o, key):
    tb = pd.cut(o.tdte, [0, 3, 7, 12, 17, 22], labels=["1-3", "4-7", "8-12", "13-17", "18-22"], include_lowest=False)
    db = pd.cut(o.adelta, [0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60],
                labels=["02-05", "05-10", "10-15", "15-20", "20-30", "30-40", "40-60"])
    o = o.assign(tb=tb, db=db).dropna(subset=["tb", "db"])
    out = o.groupby(["cp", "tb", "db"], observed=True).apply(cycle_stats, include_groups=False)
    if isinstance(out, pd.Series):
        out = out.unstack()
    out = out[out.cycles >= 10]
    print(f"\n== A1 PREMIUM MAP ({key}): short and hold to expiry, per-trade return on margin, cycle-averaged")
    for cp in ("PE", "CE"):
        tbl = out.loc[cp].reset_index().pivot(index="db", columns="tb", values="mean_roc_%").round(2)
        tt = out.loc[cp].reset_index().pivot(index="db", columns="tb", values="t").round(1)
        print(f"  {cp}: mean return on margin % (rows |delta|, cols trading days to expiry)")
        print(tbl.to_string())
        print(f"  {cp}: t-stat across cycles")
        print(tt.to_string())
    # stability: two halves of the discovery window
    exps = sorted(o.expiry.unique())
    half = exps[len(exps) // 2]
    o2 = o.assign(half=np.where(o.expiry < half, "H1", "H2"))
    st = o2.groupby(["cp", "tb", "db", "half"], observed=True).apply(
        lambda g: g.groupby("expiry").roc.mean().mean() * 100, include_groups=False).unstack()
    both = st[(st.H1 > 0) & (st.H2 > 0)]
    print(f"  cells positive in BOTH halves ({pd.Timestamp(half).date()} split): {len(both)} of {len(st)}")
    return out


def entries(o, n):
    """Front-month chain on the day with TDTE == n, per cycle."""
    return o[o.tdte == n]


def nearest(g, target, cp):
    x = g[(g.cp == cp) & g.adelta.notna()]
    if not len(x):
        return None
    return x.iloc[(x.adelta - target).abs().argsort().iloc[0]]


def feature_table(o, key, n):
    rows = []
    for e, g in entries(o, n).groupby("expiry"):
        p25, c25 = nearest(g, 0.25, "PE"), nearest(g, 0.25, "CE")
        atm = g.iloc[(g.strike - g.F).abs().argsort().iloc[0]]
        if p25 is None or c25 is None:
            continue
        atm_iv = g[(g.strike == atm.strike)].iv.mean()
        calls = g[(g.cp == "CE") & (g.strike > g.F)]
        puts = g[(g.cp == "PE") & (g.strike < g.F)]
        rows.append({"expiry": e, "F": atm.F, "F_exp": atm.F_exp, "atm_iv": atm_iv,
                     "skew": (p25.iv - c25.iv) / atm_iv if atm_iv else np.nan,
                     "put25_roc": p25.roc, "call25_roc": c25.roc, "put25_delta": p25.adelta, "call25_delta": c25.adelta,
                     "oi_call_wall": calls.loc[calls.oi.idxmax(), "strike"] if len(calls) else np.nan,
                     "oi_put_wall": puts.loc[puts.oi.idxmax(), "strike"] if len(puts) else np.nan,
                     "call_wall_delta": calls.loc[calls.oi.idxmax(), "adelta"] if len(calls) else np.nan,
                     "put_wall_delta": puts.loc[puts.oi.idxmax(), "adelta"] if len(puts) else np.nan,
                     "call_wall_roc": calls.loc[calls.oi.idxmax(), "roc"] if len(calls) else np.nan,
                     "put_wall_roc": puts.loc[puts.oi.idxmax(), "roc"] if len(puts) else np.nan,
                     "pcr_oi": puts.oi.sum() / max(calls.oi.sum(), 1)})
    return pd.DataFrame(rows)


def realised_vol(fut, sym):
    out = {}
    for fe, g in fut[(fut.sym == sym) & fut.traded].groupby("expiry"):
        s = g.set_index("date").close.sort_index()
        rv = np.log(s).diff().rolling(20, min_periods=15).std() * math.sqrt(252)
        for d, v in rv.items():
            out[(fe, d)] = v
    return out


def split_report(ft, feat, y, label):
    x = ft[[feat, y]].dropna()
    if len(x) < 8:
        return
    med = x[feat].median()
    hi, lo = x[x[feat] > med][y], x[x[feat] <= med][y]
    c = np.corrcoef(x[feat], x[y])[0, 1]
    print(f"   {label}: corr {c:+.2f} | {feat} above median: mean {hi.mean() * 100:+.2f}% ({len(hi)} cycles, "
          f"{(hi > 0).mean():.0%} positive) | below: {lo.mean() * 100:+.2f}% ({len(lo)}, {(lo > 0).mean():.0%})")


def a7_delta_hedged(o, fut, key, n, lots=10):
    """Short ATM straddle at TDTE n (lots), futures hedge rebalanced at each close in whole lots."""
    sym = DISCOVERY[key][0]
    mult = MINI_MULT[key]
    res = []
    for e, g in o.groupby("expiry"):
        g0 = g[g.tdte == n]
        if not len(g0):
            continue
        k = g0.iloc[(g0.strike - g0.F).abs().argsort().iloc[0]].strike
        legs = g[(g.strike == k)].pivot_table(index="date", columns="cp", values=["close", "delta", "F"], aggfunc="first")
        if not {"CE", "PE"} <= set(legs.columns.get_level_values(1)):
            continue                      # the ATM strike printed only one side
        legs = legs[legs.index >= g0.date.iloc[0]].dropna()
        if len(legs) < 3 or legs.index[-1] != e:
            continue
        straddle = legs["close"]["CE"] + legs["close"]["PE"]
        dlt = legs["delta"]["CE"] + legs["delta"]["PE"]
        F = legs["F"]["CE"]
        hedge = 0.0
        pnl = 0.0
        fees = 0.0
        prev_s, prev_F = straddle.iloc[0], F.iloc[0]
        s_entry = straddle.iloc[0] * (1 - SLIP)
        fees += 2 * mcx_option_leg(straddle.iloc[0] / 2, mult * lots, sell=True)["total"]
        for i in range(len(straddle)):
            if i > 0:
                pnl += hedge * (F.iloc[i] - prev_F) * mult
            prev_F = F.iloc[i]
            if i == len(straddle) - 1:
                break
            target = round(float(dlt.iloc[i]) * lots)        # long futures lots to offset a short straddle's -delta
            if target != hedge:
                ch = abs(target - hedge)
                fees += 20 * 1.18 + ch * mult * F.iloc[i] * (0.000021 * 1.18 + 0.0001 * 0.5 + 0.00002 * 0.5)
                pnl -= ch * mult * F.iloc[i] * 0.0002           # 2 bp futures slippage
                hedge = target
        s_exit = straddle.iloc[-1] * (1 + SLIP)
        fees += 2 * mcx_option_leg(max(straddle.iloc[-1] / 2, 0.05), mult * lots, sell=False)["total"]
        opt_pnl = (s_entry - s_exit) * mult * lots
        margin = 2 * 1.2 * RATE[key] * F.iloc[0] * mult * lots
        res.append({"expiry": e, "opt_pnl": opt_pnl, "hedge_pnl": pnl, "fees": fees, "net": opt_pnl + pnl - fees,
                    "unhedged_net": opt_pnl - fees, "margin": margin})
    r = pd.DataFrame(res)
    if len(r):
        print(f"   T-{n}: {len(r)} cycles | delta-hedged net per {lots}-lot straddle mean Rs{r.net.mean():,.0f} "
              f"(t {r.net.mean() / (r.net.std(ddof=1) / math.sqrt(len(r))):.2f}, {(r.net > 0).mean():.0%} positive, worst Rs{r.net.min():,.0f}) "
              f"| unhedged mean Rs{r.unhedged_net.mean():,.0f} (worst Rs{r.unhedged_net.min():,.0f}) | margin ~Rs{r.margin.mean():,.0f}")
    return r


def main(work):
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    for key in ("crude", "natgas"):
        o = panel(opt, fut, key)
        o.to_pickle(os.path.join(work, f"p2_panel_{key}.pkl"))
        print(f"\n################ {key.upper()} discovery: {o.expiry.nunique()} cycles, {len(o):,} traded option-days")
        a1_premium_map(o, key)
        rv = realised_vol(fut, DISCOVERY[key][0])
        um = ufut_map(fut, DISCOVERY[key][0])
        for n in (15, 10):
            ft = feature_table(o, key, n)
            ft["rv20"] = [rv.get((um(e), d), np.nan) for e, d in zip(ft.expiry, [o[(o.expiry == e) & (o.tdte == n)].date.iloc[0] for e in ft.expiry])]
            ft["iv_rv"] = ft.atm_iv / ft.rv20
            ft["strangle25_roc"] = ft.put25_roc + ft.call25_roc
            ft.to_csv(os.path.join(work, f"p2_features_{key}_T{n}.csv"), index=False)
            print(f"\n== A2/A3/A4 at T-{n} ({key}), {len(ft)} cycles")
            split_report(ft, "skew", "put25_roc", "A2 skew -> short 25-delta PUT")
            split_report(ft, "skew", "call25_roc", "A2 skew -> short 25-delta CALL")
            split_report(ft, "iv_rv", "strangle25_roc", "A3 IV/RV -> short 25-delta STRANGLE")
            split_report(ft, "atm_iv", "strangle25_roc", "A3 IV level -> short 25-delta STRANGLE")
            split_report(ft, "pcr_oi", "put25_roc", "A4 put/call OI ratio -> short PUT")
            split_report(ft, "pcr_oi", "call25_roc", "A4 put/call OI ratio -> short CALL")
            cw = ft.dropna(subset=["oi_call_wall"])
            pw = ft.dropna(subset=["oi_put_wall"])
            print(f"   A4 OI walls: futures finished ABOVE the max-OI call strike in {(cw.F_exp > cw.oi_call_wall).mean():.0%} of cycles "
                  f"(that call's delta said {cw.call_wall_delta.mean():.0%}); BELOW the max-OI put strike in "
                  f"{(pw.F_exp < pw.oi_put_wall).mean():.0%} (delta said {pw.put_wall_delta.mean():.0%})")
            print(f"   A4 selling AT the walls: call-wall mean {cw.call_wall_roc.mean() * 100:+.2f}% ({(cw.call_wall_roc > 0).mean():.0%} positive), "
                  f"put-wall mean {pw.put_wall_roc.mean() * 100:+.2f}% ({(pw.put_wall_roc > 0).mean():.0%} positive)")
        # A5 weekday: close-to-close P&L of a short ATM straddle (front month, TDTE 0..20), per unit
        # of the future - ONE straddle per day: the strike nearest the future with both legs traded
        rows = []
        for e, g in o[(o.tdte >= 0) & (o.tdte <= 20)].groupby("expiry"):
            pv = g.pivot_table(index=["date", "strike"], columns="cp", values="close", aggfunc="first").dropna()
            if not {"CE", "PE"} <= set(pv.columns):
                continue
            Fd = g.groupby("date").F.first()
            dates = sorted(Fd.index)
            have = set(pv.index)
            for d0, d1 in zip(dates[:-1], dates[1:]):
                ks = np.array([k for (d, k) in have if d == d0])
                if not len(ks):
                    continue
                k = ks[np.argmin(np.abs(ks - Fd[d0]))]
                if (d1, k) not in have:
                    continue
                s0 = float(pv.loc[(d0, k)].sum())
                s1 = float(pv.loc[(d1, k)].sum())
                rows.append({"expiry": e, "day": d1, "pnl": (s0 - s1) / Fd[d0]})
        wd = pd.DataFrame(rows)
        wd["wday"] = pd.to_datetime(wd.day).dt.day_name()
        print(f"\n== A5 weekday ({key}): short ATM straddle, close-to-close P&L as % of the future (positive = seller gains)")
        g = wd.groupby("wday").pnl.agg(["mean", "count"])
        g["mean"] = g["mean"] * 100
        print(g.reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]).round(3).to_string())
        print(f"\n== A7 delta-hedged short ATM straddle ({key}, 10 lots, hedged daily with mini futures)")
        for n in (20, 15, 10):
            a7_delta_hedged(o, fut, key, n)


if __name__ == "__main__":
    main(sys.argv[1])
