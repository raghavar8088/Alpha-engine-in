"""Index intraday research, final stage: luck correction, robustness, status — then the holdout ONCE.

    python backend/research/index_intraday_2026_10/ii_final.py stage3     # 2016-2023 only
    python backend/research/index_intraday_2026_10/ii_final.py holdout    # opens 2024-2026 once

STAGE 3 (fixed before round 1 ran), for every (variant, index) that passed stages 1 and 2:
  luck        Deflated Sharpe Ratio >= 0.95 over 2016-2023 against ALL registered trials with
              >= 100 trades. The trial count is the EFFECTIVE number of independent strategies —
              the larger of the participation ratio and the 90%-variance component count of the
              trials' return correlation matrix (NIFTY / NIFTY 100 / SENSEX runs of one rule are
              nearly one trial, not three); the Sharpe variance is the null's, 1/(T-1).
  neighbours  the median 2016-2023 Sharpe of its parameter neighbours (same family, exit and
              index; one parameter one grid step away) >= half its own
  breadth     net positive over 2016-2023 on >= 2 OTHER indexes of its group (broad market:
              NIFTY, NIFTY100, SENSEX, NIFTYNXT50, MIDCPNIFTY; banks: BANKNIFTY, FINNIFTY, BANKEX)
  walk-fwd    choosing the best variant of its family on that index on a rolling 24 months and
              trading it the next 6 months is net positive over 2018-2023
  costs       net positive at 1.5x costs over 2016-2023
  tradable    (added 2026-10-11 after round 2, before any holdout number existed — the index
              NIFTY NEXT 50's minute returns are positively autocorrelated (+0.074) where its
              ETF's are not (-0.302): the stale-price signature of a less liquid index) net
              positive over 2020-2023 when the SAME rule runs wholly on the ETF's own minute bars
              (signals and fills on what traded, the ETF's costs). An index with no ETF cannot
              pass. (A cross route — index decides, ETF fills at its last print — was tried and
              rejected: a thin ETF's last print lags the index, so it rewarded stale prices.)
  monte carlo reported: 20-day block bootstrap of its daily returns — P(a losing year), and the
              95th-percentile max drawdown
STATUS   Backtested (registered and run) -> Validated (stages 1-3) -> Paper Trading Approved
         (Validated, then holdout 2024-01..2026-10 net > 0, Sharpe > 0, PF > 1 on the index route
         AND net > 0 trading the ETF: the index decides, the ETF fills at the next minute's open
         with its own costs). BANKEX has no ETF: at most "Validated (simulation only)".
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "shared", _ROOT / "backend"):          # the repo's own packages first
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.services.index_intraday import families as F  # noqa: E402
from app.services.index_intraday.costs import ROUTE  # noqa: E402
from app.services.index_intraday.data import align, load  # noqa: E402
from app.services.index_intraday.engine import Costs, Trade, deflated_sr, summarize  # noqa: E402
from ii_round import CUTOFF, SEL, VAL, costs_for, run_variant  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HOLD = ("2024-01-01", "2026-12-31")
MARKER = DATA / "holdout_opened.json"
GROUPS = {"broad": ["NIFTY", "NIFTY100", "SENSEX", "NIFTYNXT50", "MIDCPNIFTY"],
          "banks": ["BANKNIFTY", "FINNIFTY", "BANKEX"]}


def group_of(index: str) -> list[str]:
    return next(g for g in GROUPS.values() if index in g)


def load_returns() -> dict[str, pd.DataFrame]:
    """index -> DataFrame(days x trial keys) of daily net bp over 2016-2023."""
    out: dict[str, list] = {}
    for f in sorted(DATA.glob("returns_r*_*.npz")):
        index = f.stem.split("_", 2)[2]
        z = np.load(f, allow_pickle=True)
        # saved as datetime64[D] -> int64 (DAYS since the epoch), not nanoseconds
        df = pd.DataFrame(z["mat"], columns=list(z["keys"]),
                          index=pd.DatetimeIndex(np.asarray(z["dates"], dtype="int64").astype("datetime64[D]")))
        out.setdefault(index, []).append(df)
    return {k: pd.concat(v, axis=1).loc[:, lambda x: ~x.columns.duplicated()] for k, v in out.items()}


def effective_trials(rets: dict[str, pd.DataFrame], keys: set[str] | None = None) -> tuple[float, int, dict]:
    """How many INDEPENDENT strategies the trials amount to, from the eigenvalues of their daily
    return correlation matrix on the dates all indexes share: the participation ratio, and the
    number of components that explain 90% of the variance. The LARGER (more conservative for
    the luck correction) is used; the raw count is returned too."""
    frames = []
    for k, df in rets.items():
        cols = [c for c in df.columns if keys is None or f"{c}@{k}" in keys]
        frames.append(df[cols].add_suffix("@" + k))
    allr = pd.concat(frames, axis=1, join="inner")
    allr = allr.loc[:, allr.std() > 0]
    c = np.nan_to_num(np.corrcoef(allr.to_numpy().T))
    ev = np.sort(np.clip(np.linalg.eigvalsh(c), 0, None))[::-1]
    pr = float(ev.sum() ** 2 / (ev ** 2).sum()) if (ev ** 2).sum() > 0 else float(allr.shape[1])
    k90 = int(np.searchsorted(np.cumsum(ev) / ev.sum(), 0.90) + 1)
    return float(max(pr, k90)), int(allr.shape[1]), {"participation_ratio": round(pr, 1), "components_90pct": k90}


def neighbours(row: pd.Series, reg: pd.DataFrame) -> list[pd.Series]:
    p = json.loads(row["params"])
    fam = reg[(reg["family"] == row["family"]) & (reg["exit"] == row["exit"]) & (reg["index"] == row["index"])]
    grids: dict[str, list] = {}
    for _, r in fam.iterrows():
        for k, v in json.loads(r["params"]).items():
            grids.setdefault(k, [])
            if v not in grids[k]:
                grids[k].append(v)
    for k in grids:
        try:
            grids[k] = sorted(grids[k])
        except TypeError:
            pass
    out = []
    for _, r in fam.iterrows():
        q = json.loads(r["params"])
        if set(q) != set(p):
            continue
        diff = [k for k in p if q[k] != p[k]]
        if len(diff) == 1:
            k = diff[0]
            try:
                if abs(grids[k].index(q[k]) - grids[k].index(p[k])) == 1:
                    out.append(r)
            except ValueError:
                pass
    return out


def walk_forward(index: str, row: pd.Series, reg: pd.DataFrame, rets: dict[str, pd.DataFrame]) -> float:
    """Net bp of trading, each 6 months from 2018, the family's best variant (by Sharpe) over
    the previous 24 months. NaN when the family has fewer than 2 variants."""
    fam = reg[(reg["family"] == row["family"]) & (reg["index"] == index)]["key"].tolist()
    df = rets[index][[k for k in fam if k in rets[index].columns]]
    if df.shape[1] < 2:
        return float("nan")
    total = 0.0
    start = pd.Timestamp("2018-01-01")
    while start < pd.Timestamp("2024-01-01"):
        tr = df.loc[start - pd.DateOffset(months=24):start - pd.Timedelta(days=1)]
        te = df.loc[start:start + pd.DateOffset(months=6) - pd.Timedelta(days=1)]
        sd = tr.std().replace(0, np.nan)
        score = (tr.mean() / sd).dropna()
        if len(tr) >= 120 and len(score):
            total += float(te[score.idxmax()].sum())
        start += pd.DateOffset(months=6)
    return total


def monte_carlo(daily: np.ndarray, block: int = 20, paths: int = 3000, horizon: int = 248, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    n = len(daily)
    if n < block * 5:
        return {}
    ann, dds = [], []
    for _ in range(paths):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, n - block, horizon // block + 1)])[:horizon]
        x = daily[idx]
        eq = np.cumsum(x)
        ann.append(eq[-1])
        dds.append(float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)))
    ann = np.array(ann)
    return {"p_losing_year": float((ann < 0).mean()), "median_year_bp": float(np.median(ann)),
            "p5_year_bp": float(np.percentile(ann, 5)), "dd95_bp": float(np.percentile(dds, 95))}


def stage3() -> pd.DataFrame:
    reg = pd.read_csv(DATA / "registry.csv")
    rets = load_returns()
    # The luck baseline is measured on the trials that traded enough to have a Sharpe ratio
    # worth the name (>= 100 trades over 2016-2023); a 3-trade variant's Sharpe is noise.
    real = reg[reg["sv_trades"].fillna(0) >= 100]
    real_keys = set(real["key"] + "@" + real["index"])
    n_eff, n_raw, eff_detail = effective_trials(rets, real_keys)
    srs = []
    for index, df in rets.items():
        cols = [c for c in df.columns if f"{c}@{index}" in real_keys]
        sub = df[cols]
        sd = sub.std().replace(0, np.nan)
        srs += list((sub.mean() / sd).dropna())
    cross_var = float(np.var(srs, ddof=1))
    # The NULL variance of a daily Sharpe estimate over T days is ~1/T: how far a worthless
    # strategy's measured Sharpe wanders by chance. (The cross-sectional variance across these
    # trials is far larger — hundreds are deeply negative from costs, a real difference, not
    # luck — and would make the bar unreachable for the wrong reason. It is reported.)
    T = int(max(len(df) for df in rets.values()))
    sr_var = 1.0 / (T - 1)
    print(f"(trials with >= 100 trades: {len(real)} of {len(reg)}; effective-count detail {eff_detail}; "
          f"cross-sectional sd of Sharpe {math.sqrt(cross_var * 248):.2f} a year, reported only)")
    from statistics import NormalDist
    nd, g = NormalDist(), 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - g) * nd.inv_cdf(1 - 1 / n_eff) + g * nd.inv_cdf(1 - 1 / (n_eff * math.e)))
    print(f"trials: {n_raw} with >= 100 trades (variant x index); effective independent {n_eff:.0f}; "
          f"over {T} days the best Sharpe luck alone produces is ~{sr0 * math.sqrt(248):.2f} a year")
    (DATA / "stage3_summary.json").write_text(json.dumps({
        "trials": int(len(reg)), "trials_100_trades": int(n_raw), "effective_trials": round(float(n_eff), 1),
        "effective_detail": eff_detail, "days": T, "luck_sharpe": round(sr0 * math.sqrt(248), 2),
        "cross_sectional_sd_sharpe": round(math.sqrt(cross_var * 248), 2)}, indent=1, default=str), encoding="utf-8")
    out = []
    for _, row in reg.iterrows():
        rec = row.to_dict()
        df = rets.get(row["index"])
        x = df[row["key"]].to_numpy() if df is not None and row["key"] in df.columns else np.zeros(1)
        sd = x.std(ddof=1) if len(x) > 2 else 0.0
        sr = x.mean() / sd if sd > 0 else 0.0
        sk = float(pd.Series(x).skew()) if sd > 0 else 0.0
        ku = float(pd.Series(x).kurt()) + 3 if sd > 0 else 3.0
        rec["dsr_eff"] = deflated_sr(sr, len(x), sk, ku, sr_var, max(2, int(round(n_eff))))
        rec["dsr_raw"] = deflated_sr(sr, len(x), sk, ku, sr_var, max(2, n_raw))
        if row["stage2"]:
            nb = neighbours(row, reg)
            rec["nb_median_sharpe"] = float(np.median([r["sv_sharpe"] for r in nb])) if nb else float("nan")
            others = [k for k in group_of(row["index"]) if k != row["index"]]
            same = reg[(reg["key"] == row["key"]) & reg["index"].isin(others)]
            rec["breadth_pos"] = int((same["sv_mean_net_bp"] > 0).sum())
            rec["breadth_tested"] = int(len(same))
            rec["wf_bp"] = walk_forward(row["index"], row, reg, rets)
            rec.update({f"mc_{k}": v for k, v in monte_carlo(x).items()})
            rec.update(etf_check(row))
        out.append(rec)
    res = pd.DataFrame(out)
    ok_nb = res["nb_median_sharpe"].isna() | (res["nb_median_sharpe"] >= 0.5 * res["sv_sharpe"])
    res["validated"] = (res["stage2"] & (res["dsr_eff"] >= 0.95) & ok_nb & (res["breadth_pos"] >= 2)
                        & (res["wf_bp"] > 0) & (res.get("sv15_mean_net_bp", res["sel15_mean_net_bp"]) > 0)
                        & (res["etf_2023_net_bp"] > 0))
    res["status"] = np.where(res["validated"], "Validated", "Backtested")
    res.to_csv(DATA / "stage3.csv", index=False)
    cols = ["key", "index", "sv_trades", "sv_mean_net_bp", "sv_sharpe", "sv_profit_factor", "dsr_eff", "dsr_raw",
            "nb_median_sharpe", "breadth_pos", "breadth_tested", "wf_bp", "idx_2023_net_bp", "etf_2023_net_bp",
            "etf_2023_trades", "mc_p_losing_year", "stage2", "validated"]
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 70)
    top = res.sort_values("sv_sharpe", ascending=False).head(25)
    print(top[[c for c in cols if c in top.columns]].round(3).to_string(index=False))
    print(f"\nstage 1: {int(res.stage1.sum())} | stage 2: {int(res.stage2.sum())} | validated: {int(res.validated.sum())}")
    return res


def etf_route(index: str, trades: list[Trade], d_idx, costs: Costs) -> list[Trade]:
    """The index decides, the ETF fills: market entries / exits at that minute's ETF open; level
    fills (stop entries; stop, trail and target exits) at the NEXT minute's ETF open."""
    etf = ROUTE[index][0]
    if not etf:
        return []
    e = load(etf)
    ia, ib = align(d_idx, e)
    pos = {int(a): int(b) for a, b in zip(ia, ib)}
    out = []
    from app.services.index_intraday.data import SESSION_MIN
    for t in trades:
        j = pos.get(t.day)
        if j is None:
            continue
        em = t.entry_min if t.entry_min < SESSION_MIN else SESSION_MIN - 1
        xm = t.exit_min + (0 if t.reason in ("square_off", "signal", "time") else 1)
        xm = min(xm, SESSION_MIN - 1)
        if e.v[j, em] == 0 and e.v[j, max(em - 1, 0)] == 0:
            continue                                       # no ETF trading at that moment
        raw_in, raw_out = float(e.o[j, em]), float(e.o[j, xm])
        entry = raw_in * (1 + t.side * costs.slip_bp / 1e4)
        exit_ = raw_out * (1 - t.side * costs.slip_bp / 1e4)
        net = t.side * (exit_ - entry) / entry * 1e4 - costs.fee_rt_bp
        out.append(Trade(t.day, t.side, em, entry, xm, exit_, t.reason, t.side * (raw_out - raw_in) / raw_in * 1e4, net))
    return out


_ETF_CACHE: dict = {}


def etf_check(row: pd.Series) -> dict:
    """Over 2020-01 .. 2023-12 (never the holdout): the rule on the INDEX (signals and fills,
    ETF costs) and the same rule run wholly on the ETF's own minute bars (signals and fills on
    what actually traded, ETF costs). The ETF-only route is the tradability test: a cross-
    instrument route (index decides, ETF fills at its last print) was rejected because a thinly
    traded ETF's last print lags the index — it rewarded buying at a price nobody quoted."""
    index = row["index"]
    etf = ROUTE[index][0]
    if not etf:
        return {"etf_2023_net_bp": float("nan"), "etf_2023_trades": 0, "idx_2023_net_bp": float("nan")}
    key = (index, etf)
    if key not in _ETF_CACHE:
        _ETF_CACHE[key] = (load(index), load(etf), load("INDIAVIX"))
    d, e, vix = _ETF_CACHE[key]
    costs = costs_for(index)
    p = json.loads(row["params"])
    out = {}
    for tag, series in (("idx", d), ("etf", e)):
        ctx = F.Ctx(series, vix)
        upto = int(np.searchsorted(series.dates, np.datetime64("2023-12-31"), side="right"))
        lo = int(np.searchsorted(series.dates, np.datetime64("2020-01-01")))
        trades = [t for t in run_variant(ctx, row["family"], p, row["exit"], costs, upto) if lo <= t.day < upto]
        out[f"{tag}_2023_net_bp"] = float(np.mean([t.net_bp for t in trades])) if trades else float("nan")
        out[f"{tag}_2023_gross_bp"] = float(np.mean([t.gross_bp for t in trades])) if trades else float("nan")
        out[f"{tag}_2023_trades"] = len(trades)
    return out


def holdout(force: bool = False) -> None:
    if MARKER.exists() and not force:
        print(f"The holdout was already opened ({json.loads(MARKER.read_text())['opened_at']}); not re-run.")
        return
    res = pd.read_csv(DATA / "stage3.csv")
    cand = res[res["validated"]]
    MARKER.write_text(json.dumps({"opened_at": datetime.now(timezone.utc).isoformat(),
                                  "candidates": (cand["key"] + "@" + cand["index"]).tolist()}, indent=1))
    if cand.empty:
        print("No strategy reached Validated — the holdout stays unopened in substance: nothing to test.")
        return
    vix = load("INDIAVIX")
    rows = []
    for _, row in cand.iterrows():
        d = load(row["index"])
        ctx = F.Ctx(d, vix)
        costs = costs_for(row["index"])
        p = json.loads(row["params"])
        trades = run_variant(ctx, row["family"], p, row["exit"], costs, len(d))
        hold_mask = d.mask(*HOLD)
        idx = np.nonzero(hold_mask)[0]
        lo = idx[0]
        sub = [Trade(t.day - lo, t.side, t.entry_min, t.entry_px, t.exit_min, t.exit_px, t.reason, t.gross_bp, t.net_bp)
               for t in trades if t.day >= lo]
        st = summarize(sub, len(idx), d.dates[lo:])
        etf_tr = etf_route(row["index"], [t for t in trades if t.day >= lo], d, costs)
        etf_sub = [Trade(t.day - lo, t.side, t.entry_min, t.entry_px, t.exit_min, t.exit_px, t.reason, t.gross_bp, t.net_bp)
                   for t in etf_tr]
        se = summarize(etf_sub, len(idx), d.dates[lo:]) if etf_sub else {"trades": 0}
        approved = (st.get("mean_net_bp", -1) > 0 and st.get("sharpe", -1) > 0 and st.get("profit_factor", 0) > 1.0
                    and se.get("mean_net_bp", -1) > 0)
        rows.append({"key": row["key"], "index": row["index"],
                     **{f"hold_{k}": v for k, v in st.items() if k != "reasons"},
                     **{f"etf_{k}": v for k, v in se.items() if k != "reasons"},
                     "status": "Paper Trading Approved" if approved else (
                         "Validated (simulation only)" if not ROUTE[row["index"]][0] and st.get("mean_net_bp", -1) > 0
                         else "Validated — failed holdout")})
    out = pd.DataFrame(rows)
    out.to_csv(DATA / "holdout.csv", index=False)
    pd.set_option("display.width", 260)
    print(out[["key", "index", "hold_trades", "hold_mean_net_bp", "hold_sharpe", "hold_profit_factor",
               "etf_trades", "etf_mean_net_bp", "status"]].round(3).to_string(index=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stage3"
    if cmd == "stage3":
        stage3()
    elif cmd == "holdout":
        holdout(force="--force" in sys.argv)
