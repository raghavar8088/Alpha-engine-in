"""Data audit for the Gold Desk research: is each history fit to test patterns on?

    python backend/research/gold_2026_10/gd_quality.py

Settles, per source: coverage and gaps, dead minutes (no trade: O=H=L=C, zero volume),
how closely each tracks COMEX gold (GC=F) hour by hour, how closely the long proxy tracks
MCX GOLDM itself, the Delta funding series, and the XAUT-PAXG token basis.
"""

import numpy as np
import pandas as pd

import gd_data as D


def hourly_returns(df: pd.DataFrame) -> pd.Series:
    h = df["close"].resample("1h", label="left", closed="left").last().dropna()
    return np.log(h).diff().dropna()


def describe_1m(name: str, df: pd.DataFrame) -> None:
    span = (df.index[-1] - df.index[0]).total_seconds() / 60 + 1
    flat = ((df.high == df.low) & (df.volume <= 0)).mean()
    still = (df.high == df.low).mean()
    print(f"\n{name}: {len(df):,} bars {df.index[0]} .. {df.index[-1]}  coverage {len(df) / span:.1%} of minutes")
    print(f"  dead minutes (no trade, H=L, vol 0): {flat:.1%};  H=L at all: {still:.1%}")
    by_year = df.groupby(df.index.year).apply(
        lambda g: pd.Series({"bars": len(g), "H=L": (g.high == g.low).mean(),
                             "median_range_bp": ((g.high - g.low) / g.close * 1e4).median(),
                             "usd_volume_m": (g.volume * g.close).sum() / 1e6}))
    print(by_year.round(3).to_string())
    gaps = df.index.to_series().diff().dt.total_seconds().div(60)
    big = gaps[gaps > 30]
    print(f"  gaps > 30 min: {len(big)}; largest {big.max() if len(big) else 0:.0f} min")


def main() -> None:
    gc = D.load_1m("yahoo_GC_1h.csv.gz")
    gc_r = np.log(gc["close"]).diff().dropna()
    gc_r = gc_r[gc.index.to_series().diff().dt.total_seconds().reindex(gc_r.index) == 3600]

    srcs = {
        "binance PAXGUSDT": D.load_1m("binance_PAXGUSDT_1m.csv.gz"),
        "delta XAUTUSD": D.load_1m("delta_XAUTUSD_1m.csv.gz"),
        "delta PAXGUSD": D.load_1m("delta_PAXGUSD_1m.csv.gz"),
    }
    for name, df in srcs.items():
        describe_1m(name, df)
        r = hourly_returns(df)
        j = pd.concat([r.rename("x"), gc_r.rename("gc")], axis=1, join="inner").dropna()
        j = j[(j.gc.abs() < 0.05) & (j.x.abs() < 0.05)]
        wk = j[j.index.dayofweek < 5]
        print(f"  hourly log-return correlation with COMEX GC=F: {wk.x.corr(wk.gc):.3f} "
              f"(n={len(wk):,}; weekday hours both printed); beta {np.polyfit(wk.gc, wk.x, 1)[0]:.3f}")
        for yr, g in wk.groupby(wk.index.year):
            if len(g) > 200:
                print(f"     {yr}: corr {g.x.corr(g.gc):.3f}  n={len(g)}")
        # weekend activity: how much of the token's movement happens when COMEX is shut
        wkend = df[df.index.dayofweek >= 5]
        if len(wkend):
            rng_wk = ((df.high - df.low) / df.close).groupby(df.index.dayofweek >= 5).median() * 1e4
            print(f"  median 1m range bp — weekdays {rng_wk.get(False, np.nan):.2f}, weekends {rng_wk.get(True, np.nan):.2f}")

    # MCX GOLDM itself, against the long proxy, hour by hour in MCX hours
    m = pd.read_csv(D.DATA / "gd_mcx_bars.csv.gz")
    m["ts"] = pd.to_datetime(m["ts"], unit="s", utc=True)
    print("\nMCX store: rows by symbol/timeframe/expiry")
    print(m.groupby(["symbol", "timeframe", "expiry"]).size().to_string())
    gm = m[(m.symbol == "GOLDM") & (m.timeframe == "1h")].copy()
    # one row per hour: the nearest contract that printed it (front month first)
    gm = gm.sort_values(["ts", "expiry"]).drop_duplicates("ts", keep="first").set_index("ts")
    gm_r = np.log(gm["close"]).diff()
    gm_r = gm_r[gm.index.to_series().diff().dt.total_seconds() == 3600]
    same_c = gm["expiry"].eq(gm["expiry"].shift())
    gm_r = gm_r[same_c.reindex(gm_r.index).fillna(False)]
    px = srcs["binance PAXGUSDT"]["close"].resample("1h", label="left", closed="left").last()
    inr = D.load_1m("yahoo_INR_1h.csv.gz")["close"].resample("1h").last().ffill()
    for label, ref in (("PAXG (USD)", np.log(px).diff()),
                       ("PAXG x USDINR", np.log(px * inr.reindex(px.index).ffill()).diff()),
                       ("GC=F", gc_r)):
        j = pd.concat([gm_r.rename("mcx"), ref.rename("ref")], axis=1, join="inner").dropna()
        j = j[(j.mcx.abs() < 0.05) & (j.ref.abs() < 0.05)]
        if len(j) > 30:
            print(f"  MCX GOLDM 1h vs {label:14}: corr {j.mcx.corr(j.ref):.3f}  n={len(j)}  "
                  f"vol ratio {j.mcx.std() / j.ref.std():.2f}")

    # Delta funding
    print("\nDelta funding (FUNDING:<SYM>, hourly samples of the rate):")
    for s in ("XAUTUSD", "PAXGUSD"):
        f = D.load_1m(f"delta_{s}_funding.csv.gz")["close"]
        print(f"  {s}: n={len(f)} mean {f.mean():.5f} median {f.median():.5f} min {f.min():.5f} max {f.max():.5f}; "
              f"share at 0.005: {(f.round(5) == 0.005).mean():.1%}; share > 0: {(f > 0).mean():.1%}")
        print(f"     distinct values (top): {f.round(5).value_counts().head(6).to_dict()}")

    # XAUT - PAXG token basis on Delta
    a = srcs["delta XAUTUSD"]["close"]
    b = srcs["delta PAXGUSD"]["close"]
    j = pd.concat([a.rename("x"), b.rename("p")], axis=1, join="inner").dropna()
    bp = (j.x / j.p - 1) * 1e4
    print(f"\nDelta XAUT/PAXG basis (bp): n={len(bp):,} mean {bp.mean():.1f} sd {bp.std():.1f} "
          f"p5 {bp.quantile(.05):.1f} p50 {bp.median():.1f} p95 {bp.quantile(.95):.1f}")
    daily = bp.resample("1D").mean()
    print("  daily mean basis, monthly:", daily.resample("MS").mean().round(1).to_dict())
    ac = bp.resample("15min").last().dropna()
    print(f"  15m basis autocorrelation lag1 {ac.autocorr(1):.3f}, lag 96 (1 day) {ac.autocorr(96):.3f}")


if __name__ == "__main__":
    main()
