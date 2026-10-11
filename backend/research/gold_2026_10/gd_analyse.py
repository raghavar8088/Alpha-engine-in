"""Gold Desk replay, stage 3: trades, costs, and whether anything survives them.

    python backend/research/gold_2026_10/gd_analyse.py [DATASET ...]

Reads data/replay/signals/*.npz (gd_replay.py) and, per dataset:

  1. TRADES. A signal is taken only if the strategy is flat when its bar closes — the desk
     holds one position per (template, timeframe, symbol). Honest exits for the honest stream,
     the desk's polled exits for the as-built stream.
  2. COSTS, in bp of notional per round trip, three ways:
       gross      none.
       desk       what the desk charges: 5 bp slippage a side + the venue fee.
       actual     measured: venue fee + the spread the book actually showed + Delta funding.
                  Delta  fee 0.01% x 1.18 GST a side (product spec); spread XAUT 0.07 / PAXG 0.24
                         bp round trip (gd_l2_sampler, 2026-10-10); funding 0.005% per 8 h paid by
                         longs = 1.5 bp/day (the venue's FUNDING series is that constant 96-100%
                         of hours; 'high' case 3.0 bp/day if the rate is per 4 h exchange).
                  MCX    one GOLDM lot: Rs 305 = 2.03 bp (tradingai_shared.mcx_fees) + the median
                         quoted GOLDM spread 1.28 bp (mcx_quote_log, 568 samples 2026-10-05..09).
  3. STATISTICS per strategy, pooled by timeframe / family / side, persistence from the first
     half of each dataset to the second, the deflated Sharpe ratio, the probability of
     backtest overfitting (CSCV), and ex-ante regime cuts.

Writes data/analysis/<DATASET>_strategies.csv and prints the summaries.
"""

from __future__ import annotations

import itertools
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SIG = HERE / "data" / "replay" / "signals"
BARS = HERE / "data" / "replay" / "bars"
OUT = HERE / "data" / "analysis"
ROOT = HERE.parents[2]
for p in (ROOT / "backend", ROOT / "strategy-service", ROOT / "shared"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TF_ORDER = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]
VENUE = {"A_XAUT": "delta", "A_PAXG": "delta", "B_PAXG": "delta",
         "C_GC": "mcx", "D_GOLDM": "mcx", "E_GCD": "mcx"}
SPREAD_RT = {"A_XAUT": 0.07, "A_PAXG": 0.24, "B_PAXG": 0.24, "C_GC": 1.28, "D_GOLDM": 1.28, "E_GCD": 1.28}
DELTA_FEE_RT = 2 * 0.0001 * 1.18 * 1e4          # 2.36 bp
MCX_FEE_RT = 2.034                               # one GOLDM lot at Rs 15 L notional
DESK_SLIP_RT = 2 * 5.0
FUNDING_BP_DAY = {"base": 1.5, "high": 3.0}
SPLIT = {"A_XAUT": "2026-07-14", "A_PAXG": "2026-06-15", "B_PAXG": "2025-11-20",
         "C_GC": "2025-07-28", "D_GOLDM": None, "E_GCD": "2013-07-01"}


def _family() -> dict:
    from app.services.commodity_patterns import TEMPLATES
    return {k: v[0] for k, v in TEMPLATES.items()}


def load_signals(ds: str) -> dict:
    out = {}
    for f in sorted(SIG.glob(f"{ds}__*.npz")):
        _, tf, tmpl = f.stem.split("__")
        try:
            z = np.load(f)
            out[(tf, tmpl)] = {k: z[k] for k in z.files}
        except Exception:  # noqa: BLE001 - a file still being written by a running replay
            continue
    return out


def take_flat(sig: dict, tc: np.ndarray, polled: bool = False) -> np.ndarray:
    """Indices of the signals the desk would act on: flat when the signal bar closes."""
    if len(sig["i"]) == 0:
        return np.array([], dtype=int)
    ex = sig["p_exit_ts"] if polled else sig["exit_ts"]
    t_sig = tc[sig["i"]]
    taken = []
    free_at = -1
    for j in range(len(t_sig)):
        if t_sig[j] >= free_at:
            taken.append(j)
            free_at = ex[j]
    return np.asarray(taken, dtype=int)


def trade_frame(ds: str, signals: dict, polled: bool = False) -> pd.DataFrame:
    fam = _family()
    rows = []
    cache: dict[str, np.ndarray] = {}
    for (tf, tmpl), s in signals.items():
        if tf not in cache:
            cache[tf] = np.load(BARS / f"{ds}__{tf}.npz")["tc"]
        tc = cache[tf]
        idx = take_flat(s, tc, polled)
        if len(idx) == 0:
            continue
        side = s["side"][idx].astype(float)
        e = s["entry_px"][idx]
        x = (s["p_exit_px"] if polled else s["exit_px"])[idx]
        xt = (s["p_exit_ts"] if polled else s["exit_ts"])[idx]
        rows.append(pd.DataFrame({
            "tf": tf, "template": tmpl, "family": fam.get(tmpl, "?"),
            "side": side, "sig_ts": tc[s["i"][idx]], "entry_ts": s["entry_ts"][idx], "exit_ts": xt,
            "entry": e, "exit": x, "reason": (s["p_reason"] if polled else s["reason"])[idx],
            "coarse": s["coarse"][idx], "tgt": s["tgt"][idx], "stp": s["stp"][idx],
        }))
    if not rows:
        return pd.DataFrame()
    t = pd.concat(rows, ignore_index=True)
    t = t[t.reason != 3].copy()                       # still open when the data ended
    t["gross"] = t.side * (t.exit - t.entry) / t.entry * 1e4
    t["hold_d"] = (t.exit_ts - t.entry_ts) / 86400.0
    venue = VENUE[ds]
    fee = DELTA_FEE_RT if venue == "delta" else MCX_FEE_RT
    t["cost_desk"] = DESK_SLIP_RT + fee
    fund = 0.0
    if venue == "delta":
        fund = t.side * FUNDING_BP_DAY["base"] * t.hold_d          # longs pay, shorts receive
        t["fund_high"] = t.side * FUNDING_BP_DAY["high"] * t.hold_d
    t["cost_actual"] = fee + SPREAD_RT[ds] + fund
    t["net_desk"] = t.gross - t.cost_desk
    t["net_actual"] = t.gross - t.cost_actual
    if venue == "delta":
        t["net_actual_high"] = t.gross - (fee + SPREAD_RT[ds] + t["fund_high"])
    t["date"] = pd.to_datetime(t.sig_ts, unit="s", utc=True)
    # Drift: what a random trade on the same side, held as long, earns from the trend alone —
    # the mean log return per calendar day over the span THAT TIMEFRAME's trades come from
    # (its own bar series; on D_GOLDM the 1d series starts in 2025, the 1m one in August 2026).
    drift = {}
    for tf in t.tf.unique():
        z = np.load(BARS / f"{ds}__{tf}.npz")
        days = (int(z["tc"][-1]) - int(z["ts"][0])) / 86400.0
        drift[tf] = math.log(float(z["c"][-1]) / float(z["o"][0])) / days * 1e4 if days > 0 else 0.0
    t["drift_bp_day"] = t.tf.map(drift)
    t["excess"] = t.gross - t.side * t.drift_bp_day * t.hold_d
    return t


# ── statistics ───────────────────────────────────────────────────────────────


def tstat(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))


def stats(x: pd.Series) -> dict:
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return {"n": 0}
    w, l = x[x > 0], x[x < 0]
    eq = np.cumsum(x)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    return {"n": n, "win": len(w) / n, "avg_win": w.mean() if len(w) else 0.0,
            "avg_loss": l.mean() if len(l) else 0.0, "mean": x.mean(), "t": tstat(x),
            "pf": (w.sum() / -l.sum()) if len(l) and l.sum() < 0 else float("inf"),
            "sr": x.mean() / x.std(ddof=1) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
            "maxdd_bp": dd, "sum": x.sum()}


def deflated_sr(sr: float, n: int, skew: float, kurt: float, sr_var: float, trials: int) -> float:
    """Bailey & Lopez de Prado (2014): P(true SR > 0) after `trials` attempts, per-trade SR."""
    from statistics import NormalDist
    nd = NormalDist()
    if n < 3 or not np.isfinite(sr) or trials < 2:
        return float("nan")
    g = 0.5772156649
    sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - g) * nd.inv_cdf(1 - 1 / trials) + g * nd.inv_cdf(1 - 1 / (trials * math.e)))
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return float(nd.cdf((sr - sr0) * math.sqrt(n - 1) / den))


def weekly_t(t: pd.DataFrame, col: str) -> float:
    """t of the WEEKLY sums: trades overlap and share bars, so a pooled per-trade t overstates."""
    w = t.groupby(pd.to_datetime(t.exit_ts, unit="s", utc=True).dt.to_period("W"))[col].sum()
    return tstat(w.to_numpy())


def pbo_cscv(mat: np.ndarray, S: int = 10) -> tuple[float, int]:
    """Probability of backtest overfitting by combinatorially symmetric cross-validation
    (Bailey, Borwein, Lopez de Prado & Zhu 2017). mat: periods x strategies of returns."""
    T, N = mat.shape
    if N < 3 or T < S * 2:
        return float("nan"), 0
    blocks = np.array_split(np.arange(T), S)
    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[k] for k in comb])
        oos_idx = np.concatenate([blocks[k] for k in range(S) if k not in comb])
        def sharpe(m):
            sd = m.std(axis=0, ddof=1)
            return np.where(sd > 0, m.mean(axis=0) / np.where(sd > 0, sd, 1), -np.inf)
        best = int(np.argmax(sharpe(mat[is_idx])))
        oos = sharpe(mat[oos_idx])
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1)
        w = (rank + 1) / (N + 1)
        lam.append(math.log(w / (1 - w)))
    lam = np.asarray(lam)
    return float((lam <= 0).mean()), len(lam)


# ── reports ──────────────────────────────────────────────────────────────────


def per_strategy(t: pd.DataFrame, ds: str, col: str = "net_actual") -> pd.DataFrame:
    split = SPLIT.get(ds)
    if split is None:
        split = t.date.min() + (t.date.max() - t.date.min()) / 2
    split = pd.Timestamp(split, tz="UTC") if not isinstance(split, pd.Timestamp) else split
    rows = []
    for (tf, tmpl), g in t.groupby(["tf", "template"]):
        s_g = stats(g.gross)
        s_n = stats(g[col])
        s_d = stats(g.net_desk)
        a, b = g[g.date < split], g[g.date >= split]
        rows.append({
            "tf": tf, "template": tmpl, "family": g.family.iloc[0], "n": s_n["n"],
            "win": s_n["win"], "avg_win": s_n["avg_win"], "avg_loss": s_n["avg_loss"],
            "gross_bp": s_g["mean"], "gross_t": s_g["t"], "net_desk_bp": s_d["mean"],
            "net_bp": s_n["mean"], "net_t": s_n["t"], "pf": s_n["pf"], "sr": s_n["sr"],
            "maxdd_bp": s_n["maxdd_bp"], "sum_bp": s_n["sum"],
            "skew": float(pd.Series(g[col]).skew()) if len(g) > 2 else 0.0,
            "kurt": float(pd.Series(g[col]).kurt() + 3) if len(g) > 3 else 3.0,
            "hold_h": g.hold_d.mean() * 24, "long_share": (g.side > 0).mean(),
            "excess_bp": g.excess.mean(), "excess_t": tstat(g.excess),
            "tgt_share": (g.reason == 0).mean(), "stop_share": (g.reason == 1).mean(),
            "n_a": len(a), "net_a": a[col].mean() if len(a) else np.nan, "t_a": tstat(a[col]),
            "n_b": len(b), "net_b": b[col].mean() if len(b) else np.nan, "t_b": tstat(b[col]),
        })
    df = pd.DataFrame(rows)
    sr_var = df.loc[df.n >= 20, "sr"].var()
    trials = int((df.n >= 20).sum())
    df["dsr"] = [deflated_sr(r.sr, r.n, r.skew, r.kurt, sr_var, trials) if r.n >= 20 else np.nan
                 for r in df.itertuples()]
    return df


def weekly_matrix(t: pd.DataFrame, col: str) -> np.ndarray:
    t = t.copy()
    t["week"] = pd.to_datetime(t.exit_ts, unit="s", utc=True).dt.to_period("W")
    m = t.pivot_table(index="week", columns=["tf", "template"], values=col, aggfunc="sum", fill_value=0.0)
    return m.to_numpy()


def regime_cuts(t: pd.DataFrame, ds: str, col: str = "net_actual") -> None:
    """Ex-ante cuts from the dataset's own daily bars: trend (close vs its 50-day mean on the
    day BEFORE the signal) and volatility (20-day realised vol tercile, same lag)."""
    d = np.load(BARS / f"{ds}__1d.npz")
    dd = pd.DataFrame({"c": d["c"]}, index=pd.to_datetime(d["ts"], unit="s", utc=True))
    dd["trend"] = np.where(dd.c > dd.c.rolling(50).mean(), "up", "down")
    dd["vol"] = np.log(dd.c).diff().rolling(20).std()
    dd = dd.shift(1).dropna()                         # yesterday's reading only — no look-ahead
    q = dd.vol.quantile([1 / 3, 2 / 3]).to_numpy()
    dd["volr"] = np.where(dd.vol < q[0], "low", np.where(dd.vol < q[1], "mid", "high"))
    day = t.date.dt.floor("D")
    if str(d["tz"]) == "IST":
        day = (t.date + pd.Timedelta(hours=5, minutes=30)).dt.floor("D") - pd.Timedelta(hours=5, minutes=30)
    m = dd.reindex(day, method="ffill")
    t = t.assign(trend=m.trend.to_numpy(), volr=m.volr.to_numpy())
    hours = t.date.dt.hour if VENUE[ds] == "delta" else (t.date + pd.Timedelta(hours=5, minutes=30)).dt.hour
    if VENUE[ds] == "delta":
        t["session"] = pd.cut(hours, [-1, 6, 12, 20, 24], labels=["Asia 00-07", "London 07-13", "NY 13-21", "late 21-24"])
        t["weekend"] = np.where(t.date.dt.dayofweek >= 5, "weekend", "weekday")
        keys = ["trend", "volr", "session", "weekend"]
    else:
        t["session"] = pd.cut(hours, [-1, 13, 18, 24], labels=["IST 09-14", "IST 14-19 (London)", "IST 19-24 (US)"])
        keys = ["trend", "volr", "session"]
    t["hold"] = pd.cut(t.hold_d * 24 * 60, [-1, 15, 60, 240, 1440, 7200, 1e9],
                       labels=["<15m", "15m-1h", "1-4h", "4h-1d", "1-5d", ">5d"])
    keys = keys + ["hold"]
    for k in keys:
        g = t.groupby(k, observed=True)[col].agg(["count", "mean", tstat])
        print(f"    by {k:8}: " + " | ".join(f"{i} n={int(r['count'])} {r['mean']:+.2f}bp t{r['tstat']:+.1f}"
                                          for i, r in g.iterrows()))


def report(ds: str) -> None:
    sig = load_signals(ds)
    if not sig:
        print(f"{ds}: no signals yet")
        return
    t = trade_frame(ds, sig)
    tp = trade_frame(ds, sig, polled=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"\n{'=' * 100}\n{ds} ({VENUE[ds]} costs) — {len(sig)} strategy files, {len(t):,} trades taken, "
          f"{t.date.min():%Y-%m-%d} .. {t.date.max():%Y-%m-%d}\n{'=' * 100}")
    print(f"  mean bp/trade: gross {t.gross.mean():+.2f} (weekly t {weekly_t(t, 'gross'):+.1f}) | desk-charged {t.net_desk.mean():+.2f} "
          f"| actual {t.net_actual.mean():+.2f} (weekly t {weekly_t(t, 'net_actual'):+.1f})"
          + (f" | actual, high funding {t.net_actual_high.mean():+.2f}" if "net_actual_high" in t else ""))
    print(f"  DRIFT-ADJUSTED (gross minus side x the period's trend x hold; trend by tf "
          + ", ".join(f"{k} {v:+.1f}" for k, v in t.groupby('tf').drift_bp_day.first().items()) + " bp/day): "
          f"{t.excess.mean():+.2f} bp/trade (weekly t {weekly_t(t, 'excess'):+.2f}); long {t[t.side > 0].excess.mean():+.2f}, "
          f"short {t[t.side < 0].excess.mean():+.2f}; long share {(t.side > 0).mean():.0%}")
    print(f"  cost per trade: desk {t.cost_desk.mean():.2f} bp, actual {t.cost_actual.mean():.2f} bp; "
          f"median |gross| move {t.gross.abs().median():.1f} bp; exits: "
          + ", ".join(f"{k} {v:.0%}" for k, v in t.reason.map({0: 'target', 1: 'stop', 2: 'hold'}).value_counts(normalize=True).items()))
    # the desk as built: polled exits
    print(f"  AS BUILT (polled exits every {3} min, filled at the polled price): gross {tp.gross.mean():+.2f} bp "
          f"vs honest {t.gross.mean():+.2f} bp over {len(tp):,} trades")
    if len(tp):
        tgt_o = tp[tp.reason == 0]
        if len(tgt_o):
            over = (tgt_o.side * (tgt_o.exit - tgt_o.tgt) / tgt_o.entry * 1e4)
            print(f"    target exits filled {over.mean():+.2f} bp beyond their own target on average (honest: 0 unless the minute opened past it)")
    # drift
    side_g = t.groupby("side").gross.agg(["count", "mean"])
    print("  by side (gross):", " | ".join(f"{'long' if s > 0 else 'short'} n={int(r['count'])} {r['mean']:+.2f}bp" for s, r in side_g.iterrows()))
    print("  by timeframe:")
    for tf in TF_ORDER:
        g = t[t.tf == tf]
        if len(g):
            print(f"    {tf:4} n={len(g):7,}  gross {g.gross.mean():+7.2f} bp (wk t {weekly_t(g, 'gross'):+5.1f})  desk {g.net_desk.mean():+7.2f}"
                  f"  actual {g.net_actual.mean():+7.2f} (wk t {weekly_t(g, 'net_actual'):+5.1f})  excess {g.excess.mean():+7.2f} (wk t {weekly_t(g, 'excess'):+5.1f})"
                  f"  long {(g.side > 0).mean():.0%}  |move| med {g.gross.abs().median():6.1f}  stop {(abs(g.entry - g.stp) / g.entry * 1e4).median():6.1f}  hold {g.hold_d.mean() * 24:6.1f} h")
    print("  by family (actual):", " | ".join(f"{k} n={len(g)} {g.net_actual.mean():+.2f}bp t{tstat(g.net_actual):+.1f}" for k, g in t.groupby("family")))
    print("  ex-ante regimes (actual):")
    regime_cuts(t, ds)

    ps = per_strategy(t, ds)
    ps.to_csv(OUT / f"{ds}_strategies.csv", index=False)
    ok = ps[ps.n >= 20]
    print(f"  drift-adjusted: strategies with excess > 0: {(ok.excess_bp > 0).sum()} of {len(ok)}, excess t > 2: {(ok.excess_t > 2).sum()}, t > 3: {(ok.excess_t > 3).sum()}")
    print(f"  strategies with >= 20 trades: {len(ok)} of {len(ps)}; gross > 0: {(ok.gross_bp > 0).sum()}, "
          f"net (actual) > 0: {(ok.net_bp > 0).sum()}, net t > 2: {(ok.net_t > 2).sum()}, net t > 3: {(ok.net_t > 3).sum()}, "
          f"DSR > 0.95: {(ok.dsr > 0.95).sum()}; desk-charged > 0: {(ok.net_desk_bp > 0).sum()}")
    both = ok.dropna(subset=["net_a", "net_b"])
    both = both[(both.n_a >= 10) & (both.n_b >= 10)]
    if len(both) > 5:
        rho = both.net_a.rank().corr(both.net_b.rank())
        sel = both[(both.net_a > 0) & (both.t_a > 2)]
        print(f"  persistence first half -> second half (n_a,n_b >= 10, {len(both)} strategies): Spearman {rho:+.3f}; "
              f"t > 2 in the first half: {len(sel)}, of which positive in the second: {(sel.net_b > 0).sum()}")
    try:
        mat = weekly_matrix(t[t.tf.isin(ok.tf.unique())], "net_actual")
        pbo, ncomb = pbo_cscv(mat)
        print(f"  PBO (CSCV, weekly net, {mat.shape[1]} strategies x {mat.shape[0]} weeks, {ncomb} splits): {pbo:.2f}")
    except Exception as exc:  # noqa: BLE001
        print("  PBO failed:", exc)
    top = ok.sort_values("net_t", ascending=False).head(8)
    print("  top 8 by net t:")
    for r in top.itertuples():
        print(f"    {r.tf:4} {r.template:22} n={r.n:5} gross {r.gross_bp:+7.2f} net {r.net_bp:+7.2f} t {r.net_t:+5.2f} "
              f"DSR {r.dsr:.2f} | 1st {r.net_a:+7.2f} (n {r.n_a}) 2nd {r.net_b:+7.2f} (n {r.n_b})")
    t.to_parquet(OUT / f"{ds}_trades.parquet") if _has_parquet() else t.to_pickle(OUT / f"{ds}_trades.pkl")


def _has_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    for ds in (sys.argv[1:] or list(VENUE)):
        report(ds)
