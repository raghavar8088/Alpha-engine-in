"""Statistics for the Fundamental Rank validation, applying PLAN.md's fixed rules.

    python report.py <panel.csv> <selfcheck.csv> <out dir>

Selection uses the four development years only; the composite it implies is then tested once on the 2025 hold-out.
Writes <out>/report.json and REPORT.md beside this script."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DEV = ["2021-10-01", "2022-10-01", "2023-10-01", "2024-10-01"]
HOLD = "2025-10-01"
CANDIDATES = ["c_quality", "c_growth", "c_valuation", "c_strength"]
REPORTED = ["c_quarter", "fund", "pnl", "val_rel", "p_returns", "p_growth", "p_profitability", "p_balance_sheet",
            "p_cash", "p_valuation", "p_ownership", "rating_fund_parts"]
LABEL = {"c_quality": "Quality", "c_growth": "Growth", "c_valuation": "Valuation", "c_strength": "Strength",
         "c_quarter": "Quarterly results", "fund": "Fundamentals score (7 pillars)", "pnl": "P&L record",
         "val_rel": "P/E vs sector", "p_returns": "Return on capital", "p_growth": "Growth pillar",
         "p_profitability": "Profitability", "p_balance_sheet": "Balance sheet", "p_cash": "Cash conversion",
         "p_valuation": "Valuation pillar", "p_ownership": "Ownership", "rating_fund_parts":
         "Today's stock rating without momentum", "composite": "Fundamental Rank composite"}
MIN_IC, MIN_POS, MIN_N = 0.02, 3, 50
RATING_W = {"c_quality": 0.25, "c_growth": 0.20, "c_quarter": 0.15, "c_valuation": 0.15, "c_strength": 0.15}


def ic(d: pd.DataFrame, sig: str, ret: str = "ret12") -> tuple[float | None, int]:
    m = d[sig].notna() & d[ret].notna()
    n = int(m.sum())
    if n < MIN_N or d.loc[m, sig].nunique() < 3:
        return None, n
    return float(spearmanr(d.loc[m, sig], d.loc[m, ret]).correlation), n


def sector_ic(d: pd.DataFrame, sig: str, ret: str = "ret12") -> float | None:
    x = d[d[sig].notna() & d[ret].notna()].copy()
    x = x[x.groupby("sector")["symbol"].transform("count") >= 10]
    if len(x) < MIN_N:
        return None
    x["a"] = x.groupby("sector")[sig].rank(pct=True)
    x["b"] = x.groupby("sector")[ret].rank(pct=True)
    return float(spearmanr(x["a"], x["b"]).correlation)


def quintiles(d: pd.DataFrame, sig: str, ret: str = "ret12") -> dict | None:
    x = d[d[sig].notna() & d[ret].notna()]
    if len(x) < MIN_N:
        return None
    q = pd.qcut(x[sig].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    g = x.groupby(q, observed=True)[ret]
    med, mean = g.median(), g.mean()
    return {"median": [round(float(v) * 100, 1) for v in med], "mean": [round(float(v) * 100, 1) for v in mean],
            "n": [int(v) for v in g.count()],
            "top_minus_bottom_median": round(float(med.iloc[-1] - med.iloc[0]) * 100, 1),
            "top_minus_bottom_mean": round(float(mean.iloc[-1] - mean.iloc[0]) * 100, 1)}


def composite(d: pd.DataFrame, comps: list[str]) -> pd.Series:
    """Equal-weighted mean of the components' percentiles within each date; needs all but one (and >= 2).

    PLAN.md did not foresee a single passing component, where "at least 2" cannot be met: the composite is then that
    component alone (no weights involved). This reading was written down when the development results showed it."""
    need = 1 if len(comps) == 1 else max(2, len(comps) - 1)
    pct = pd.concat([d.groupby("asof")[c].rank(pct=True) for c in comps], axis=1)
    out = pct.mean(axis=1)
    out[pct.notna().sum(axis=1) < need] = np.nan
    return out


def summarise(d: pd.DataFrame, sig: str, years: list[str], ret: str = "ret12") -> dict:
    per = {}
    for y in years:
        v, n = ic(d[d["asof"] == y], sig, ret)
        per[y] = {"ic": None if v is None else round(v, 4), "n": n}
    vals = [p["ic"] for p in per.values() if p["ic"] is not None]
    mean = float(np.mean(vals)) if vals else None
    t = (mean / (np.std(vals, ddof=1) / np.sqrt(len(vals)))) if len(vals) >= 2 and np.std(vals, ddof=1) > 0 else None
    return {"per_year": per, "mean_ic": None if mean is None else round(mean, 4),
            "t": None if t is None else round(float(t), 2), "positive_years": sum(v > 0 for v in vals),
            "years": len(vals)}


def main() -> None:
    panel, selfc, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    df = pd.read_csv(panel)
    df = df[(df.data_ok == 1) & df.ret12.notna()].copy()
    df["brk12"] = df["brk12"].astype(str).str.lower().eq("true")
    # today's stock rating without its momentum part, as the table weights it (missing parts' weight redistributed)
    num = sum(df[c].fillna(0) * w for c, w in RATING_W.items())
    den = sum(df[c].notna() * w for c, w in RATING_W.items())
    df["rating_fund_parts"] = num / den.replace(0, np.nan)
    dev = df[df["asof"].isin(DEV)]

    # 1) selection on the development years only
    sel = {c: summarise(dev, c, DEV) for c in CANDIDATES}
    passing = [c for c in CANDIDATES if sel[c]["mean_ic"] is not None and sel[c]["mean_ic"] >= MIN_IC
               and sel[c]["positive_years"] >= MIN_POS]
    rep = {c: summarise(df, c, DEV + [HOLD]) for c in REPORTED}

    result: dict = {"universe": {y: int((df["asof"] == y).sum()) for y in DEV + [HOLD]},
                    "selection": {c: sel[c] for c in CANDIDATES}, "passing": passing, "reported": rep}
    # 2) the composite the rule implies, and its single hold-out test
    if passing:
        df["composite"] = composite(df, passing)
        comp_dev = summarise(df[df["asof"].isin(DEV)], "composite", DEV)
        hv, hn = ic(df[df["asof"] == HOLD], "composite")
        hq = quintiles(df[df["asof"] == HOLD], "composite")
        verdict = bool(hv is not None and hv > 0 and hq and hq["median"][-1] > hq["median"][0])
        result["composite"] = {
            "components": passing, "dev": comp_dev,
            "dev_quintiles": {y: quintiles(df[df["asof"] == y], "composite") for y in DEV},
            "holdout": {"ic": None if hv is None else round(hv, 4), "n": hn, "quintiles": hq,
                        "passes": verdict},
            "robustness": {
                "within_sector_ic": {y: (lambda v: None if v is None else round(v, 4))(
                    sector_ic(df[df["asof"] == y], "composite")) for y in DEV + [HOLD]},
                "breaks_dropped": summarise(df[~df.brk12], "composite", DEV + [HOLD]),
                "top_1000_by_mcap": summarise(
                    df[df.groupby("asof")["mcap"].rank(ascending=False) <= 1000], "composite", DEV + [HOLD]),
                "horizon_6m": summarise(df.dropna(subset=["ret6"]), "composite", DEV + [HOLD], ret="ret6"),
            },
        }
    else:
        result["composite"] = None

    s = pd.read_csv(selfc)
    result["selfcheck"] = {}
    for k in ("quality", "growth", "valuation", "strength", "fund"):
        a, b = s[f"mine_{k}"], s[f"live_{k}"]
        m = a.notna() & b.notna()
        result["selfcheck"][k] = {"n": int(m.sum()), "corr": round(float(np.corrcoef(a[m], b[m])[0, 1]), 3),
                                  "median_abs_diff": round(float((a[m] - b[m]).abs().median()), 2)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"passing": passing, "selection": {c: {k: sel[c][k] for k in ("mean_ic", "t", "positive_years")}
                                                        for c in CANDIDATES},
                      "per_year": {c: {y: sel[c]["per_year"][y]["ic"] for y in DEV} for c in CANDIDATES}}, indent=1))


if __name__ == "__main__":
    main()
