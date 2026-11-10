"""Walk-forward validation of the NSE Stock Ratings forward-return estimates.

Usage:  python validate.py <history dir from fetch_history.py> [out dir]

WHAT IS BEING VALIDATED
For every NSE mainboard stock and horizon h (1 day, 1 week, 1 month, 3 months), the tab
shows a base case, an 80% range (bear = 10th percentile, bull = 90th), and a 1-in-20
downside (5th percentile). The model is deliberately simple, and every part of it is fitted
on one period and judged on a later one:

  log return over h  ~  mu_h + z * sigma_h
    sigma_h = sqrt(w_h * EWMA variance + (1 - w_h) * 1-year variance) * sqrt(h)
    mu_h    = long-run market drift * h, plus a signal tilt ONLY if one passes the rule below
    z       = empirical quantiles of standardised outcomes, pooled across stocks and taken
              from the training period, re-centred so the median is 0. The training
              period's own drift is never carried forward, because 2022-24 was a broad
              small-cap rally and would bias every base case upward.

PRE-REGISTERED RULES (fixed before any result was seen)
  train      evaluation dates Nov 2022 - Oct 2024 (Oct 2021 - Oct 2022 is warm-up only)
  hold-out   Nov 2024 - Nov 2026; nothing below is refitted on it
  w_h        chosen on train from {0, .25, .5, .75, 1} by average pinball loss
  tilt       a signal (12-1 momentum, 1-month reversal, 52-week-high proximity, low
             volatility) tilts mu_h only if its cross-sectional rank IC has the same
             sign with |t| >= 2 in BOTH train and hold-out. Otherwise the base case is the
             market drift alone, and the report says so.
  pass bar   80% range coverage in hold-out within 75-85%; 5th-percentile exceedance
             within 3-8%. A horizon that misses is shown as "low confidence".

DATA HYGIENE
  * Closes are adjusted with NSE's corporate-actions feed (bonuses, splits,
    consolidations), and symbols are joined across NSE's symbol-change list.
  * Rights issues, demergers and capital reductions cannot be adjusted with a share
    count. Their ex-dates are breaks: no daily return and no outcome spans one.
  * A daily move beyond |ln| 0.40 (-33% / +49%) is outside every NSE price band, so it
    is an unrecorded corporate action or a data error, and is treated as a break.
  * An outcome is only scored when the stock trades within 3 sessions of the horizon's
    end. Stale prices are not marked to anything.
"""

import csv
import gzip
import json
import math
import sys
import warnings
from datetime import date
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)   # all-NaN slices are expected

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from app.services.nse_ratings_logic import parse_action, parse_nse_date  # noqa: E402  (pure)

DATA = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE

HORIZONS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63}
QUANTS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
TRAIN = (date(2022, 11, 1), date(2024, 10, 31))
TEST = (date(2024, 11, 1), date(2026, 11, 9))
LAMBDA = 0.94
LR_WINDOW = 252
MIN_RETURNS = 120
BREAK = 0.40
EVAL_EVERY = 5
DRIFT_LOG_PER_SESSION = math.log(1.11) / 250     # ~11%/yr, India's long-run nominal equity drift
W_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
VOL_FLOOR, VOL_CAP = 0.004, 0.10                 # daily sigma bounds


def gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ── symbols across renames ───────────────────────────────────────────────────────

renames: dict[str, tuple[str, date]] = {}
with open(DATA / "symbolchange.csv", encoding="utf-8", errors="replace") as fh:
    for raw in csv.DictReader(fh):
        x = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        old, new = x.get("OLD SYMBOL", "").upper(), x.get("NEW SYMBOL", "").upper()
        eff = parse_nse_date(x.get("EFFECTIVE DATE"))
        if old and new and eff and old != new:
            if old not in renames or renames[old][1] < eff:
                renames[old] = (new, eff)


def canon(sym: str, d: date) -> str:
    for _ in range(5):
        hit = renames.get(sym)
        if not hit or d >= hit[1]:
            return sym
        sym = hit[0]
    return sym


# ── the matrices ─────────────────────────────────────────────────────────────────

files = sorted((DATA / "prices").glob("*.json.gz"))
dates = [date.fromisoformat(f.name[:10]) for f in files]
T = len(dates)
symset = set()
for f, d in zip(files, dates):
    for s in gz(f):
        symset.add(canon(s, d))
syms = sorted(symset)
col = {s: i for i, s in enumerate(syms)}
N = len(syms)
print(f"{T} sessions {dates[0]}..{dates[-1]}, {N} symbols", flush=True)

C = np.full((T, N), np.nan)          # close
V = np.full((T, N), np.nan)          # turnover, Rs lakh
for t, (f, d) in enumerate(zip(files, dates)):
    for s, row in gz(f).items():
        j = col[canon(s, d)]
        if row[0]:
            C[t, j] = row[0]
            V[t, j] = row[3] or 0.0

# Corporate actions: adjust what a share count describes; mark the rest as breaks.
didx = {d: i for i, d in enumerate(dates)}
breaks = np.zeros((T, N), dtype=bool)
n_adj = n_break = 0
for it in json.load(open(DATA / "ca_5y.json")):
    if (it.get("series") or "EQ") not in ("EQ", "BE", "BZ"):
        continue
    act = parse_action(it.get("subject") or "")
    ex = parse_nse_date(it.get("exDate"))
    if not act or not ex or ex <= dates[0] or ex > dates[-1]:
        continue
    j = col.get(canon((it.get("symbol") or "").upper(), ex))
    if j is None:
        continue
    t_ex = next((i for i in range(T) if dates[i] >= ex), None)
    if t_ex is None:
        continue
    if act.get("factor"):
        C[:t_ex, j] *= act["factor"]
        n_adj += 1
    if act.get("unadjusted"):
        breaks[t_ex, j] = True
        n_break += 1

# Daily log returns between consecutive traded closes; implausible jumps become breaks.
traded = ~np.isnan(C)
last = np.full(N, np.nan)
R = np.full((T, N), np.nan)
for t in range(T):
    ok = traded[t]
    r = np.log(C[t] / last)
    jump = ok & ~np.isnan(r) & (np.abs(r) > BREAK)
    breaks[t] |= jump
    r[~ok | breaks[t]] = np.nan
    R[t] = r
    last = np.where(ok, C[t], last)
print(f"adjusted {n_adj} share-count actions, {n_break} unadjustable breaks, "
      f"{int(breaks.sum()) - n_break} implausible jumps treated as breaks", flush=True)

# ── volatility state at every session ────────────────────────────────────────────

R0 = np.nan_to_num(R)
valid = ~np.isnan(R)
ew = np.full((T, N), np.nan)
v = np.full(N, np.nan)
for t in range(T):
    x2 = R0[t] ** 2
    seeded = ~np.isnan(v)
    v = np.where(valid[t], np.where(seeded, LAMBDA * v + (1 - LAMBDA) * x2, x2), v)
    ew[t] = v

cs1 = np.cumsum(R0, axis=0)
cs2 = np.cumsum(R0 ** 2, axis=0)
csn = np.cumsum(valid, axis=0)


def window(arr, t, w):
    return arr[t] - (arr[t - w] if t - w >= 0 else 0)


def lr_var(t):
    n = window(csn, t, LR_WINDOW)
    s1, s2 = window(cs1, t, LR_WINDOW), window(cs2, t, LR_WINDOW)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (s2 - s1 ** 2 / n) / (n - 1)
    var[n < MIN_RETURNS] = np.nan
    return var, n


trc = np.cumsum(traded, axis=0)
cbreak = np.cumsum(breaks, axis=0)

# Forward-filled close, for marking an outcome on a day the stock did not trade.
Cf = C.copy()
age = np.zeros(N)
for t in range(1, T):
    m = np.isnan(Cf[t])
    age = np.where(m, age + 1, 0)
    Cf[t] = np.where(m & (age <= 3), Cf[t - 1], Cf[t])

idx_file = {f.name[:10]: f for f in (DATA / "indices").glob("*.json.gz")}
nifty500 = np.array([gz(idx_file[d.isoformat()]).get("Nifty 500", np.nan)
                     if d.isoformat() in idx_file else np.nan for d in dates])


def rank(x):
    """Cross-sectional percentile rank in (0, 1), NaN stays NaN."""
    out = np.full_like(x, np.nan)
    ok = ~np.isnan(x)
    if ok.sum() < 3:
        return out
    order = x[ok].argsort().argsort()
    out[ok] = (order + 0.5) / ok.sum()
    return out


def spearman(a, b):
    ok = ~np.isnan(a) & ~np.isnan(b)
    if ok.sum() < 50:
        return np.nan
    ra, rb = rank(a[ok]), rank(b[ok])
    return float(np.corrcoef(ra, rb)[0, 1])


# ── one sample per (evaluation date, stock, horizon) ─────────────────────────────

samples = {h: [] for h in HORIZONS}
ics = {h: {k: {"train": [], "test": []} for k in ("mom_12_1", "rev_1m", "prox_52w", "low_vol")} for h in HORIZONS}
liq_cut = None
for t in range(LR_WINDOW, T, EVAL_EVERY):
    d = dates[t]
    period = "train" if TRAIN[0] <= d <= TRAIN[1] else "test" if TEST[0] <= d <= TEST[1] else None
    if period is None:
        continue
    lv, n = lr_var(t)
    ok = traded[t] & ~np.isnan(lv) & ~np.isnan(ew[t])
    notrade = 1 - window(trc, t, 126) / 126
    tv = np.nanmedian(np.where(np.isnan(V[max(0, t - 62):t + 1]), 0, V[max(0, t - 62):t + 1]), axis=0) / 100
    # signals, all known at t
    c0 = C[t]
    with np.errstate(invalid="ignore", divide="ignore"):
        mom = np.log(Cf[t - 21] / Cf[t - 252]) if t >= 252 else np.full(N, np.nan)
        rev = np.log(c0 / Cf[t - 21])
        hi = np.nanmax(C[t - 251:t + 1], axis=0)
        prox = c0 / hi
        lowv = -np.sqrt(lv)
    for hk, h in HORIZONS.items():
        if t + h >= T:
            continue
        brk = window(cbreak, t + h, h) > 0
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.log(Cf[t + h] / c0)
        good = ok & ~np.isnan(out) & ~brk
        if good.sum() < 100:
            continue
        for name, sig in (("mom_12_1", mom), ("rev_1m", -rev), ("prox_52w", prox), ("low_vol", lowv)):
            ic = spearman(np.where(good, sig, np.nan), np.where(good, out, np.nan))
            if not np.isnan(ic):
                ics[hk][name][period].append(ic)
        jj = np.nonzero(good)[0]
        samples[hk].append(np.column_stack([
            np.full(len(jj), t), jj, out[jj], ew[t, jj], lv[jj], notrade[jj], tv[jj],
            rank(np.where(good, np.sqrt(lv), np.nan))[jj],
            rank(np.where(good, mom, np.nan))[jj], rank(np.where(good, prox, np.nan))[jj],
            rank(np.where(good, lowv, np.nan))[jj],
        ]))

for hk in HORIZONS:
    samples[hk] = np.vstack(samples[hk])
    print(f"{hk}: {len(samples[hk]):,} scored outcomes", flush=True)

PERIOD = np.array([0 if TRAIN[0] <= d <= TRAIN[1] else 1 if TEST[0] <= d <= TEST[1] else -1 for d in dates])


def pinball(y, q, p):
    e = y - q
    return float(np.mean(np.maximum(p * e, (p - 1) * e)))


report: dict = {"horizons": {}, "signals": {}, "data": {
    "sessions": T, "first": dates[0].isoformat(), "last": dates[-1].isoformat(), "symbols": N,
    "adjusted_actions": n_adj, "breaks": int(breaks.sum()),
    "train": [TRAIN[0].isoformat(), TRAIN[1].isoformat()], "test": [TEST[0].isoformat(), TEST[1].isoformat()]}}
calib: dict = {"version": "2026-11-10", "drift_log_per_session": DRIFT_LOG_PER_SESSION,
               "lambda": LAMBDA, "lr_window": LR_WINDOW, "min_returns": MIN_RETURNS,
               "vol_floor": VOL_FLOOR, "vol_cap": VOL_CAP, "horizons": {}}

# Signals: mean rank IC per period and its t-stat across evaluation dates.
for hk in HORIZONS:
    report["signals"][hk] = {}
    for name, d_ in ics[hk].items():
        row = {}
        for per in ("train", "test"):
            a = np.array(d_[per])
            row[per] = {"mean_ic": round(float(a.mean()), 4) if len(a) else None,
                        "t": round(float(a.mean() / (a.std(ddof=1) / math.sqrt(len(a)))), 2) if len(a) > 2 else None,
                        "dates": len(a)}
        tr_, te_ = row["train"], row["test"]
        passes = bool(tr_["t"] is not None and te_["t"] is not None and abs(tr_["t"]) >= 2 and abs(te_["t"]) >= 2
                      and np.sign(tr_["mean_ic"]) == np.sign(te_["mean_ic"]))
        row["passes"] = passes
        report["signals"][hk][name] = row


TRAIN_MID = date(2023, 11, 1)        # the variant choice is made inside the training window
QK = [str(q) for q in QUANTS]


def tercile(rank_col):
    return np.minimum((rank_col * 3).astype(int), 2)


def zfit(z, terc=None):
    """Re-centred quantiles of z, pooled (terc None) or one row per volatility tercile."""
    if terc is None:
        q = np.quantile(z, QUANTS)
        return q - q[QUANTS.index(0.5)]
    out = np.zeros((3, len(QUANTS)))
    for b in range(3):
        q = np.quantile(z[terc == b], QUANTS)
        out[b] = q - q[QUANTS.index(0.5)]
    return out


def quant_matrix(zq, terc, n):
    """Per-sample quantile multipliers, shape (n, len(QUANTS))."""
    return np.tile(zq, (n, 1)) if zq.ndim == 1 else zq[terc]


def score_set(y, mu, s, zmat):
    q = mu + zmat * s[:, None]
    i10, i50, i90, i05 = (QUANTS.index(x) for x in (0.10, 0.50, 0.90, 0.05))
    return {
        "n": int(len(y)),
        "coverage_80": round(float(np.mean((y >= q[:, i10]) & (y <= q[:, i90]))), 4),
        "below_p05": round(float(np.mean(y < q[:, i05])), 4),
        "above_base": round(float(np.mean(y > q[:, i50])), 4),
        "median_outcome_pct": round(float(np.expm1(np.median(y)) * 100), 3),
        "base_pct": round(float(np.expm1(mu) * 100), 3),
        "pinball": round(float(np.mean([pinball(y, q[:, k], p) for k, p in enumerate(QUANTS)])), 6),
    }


def score_set_mu(y, mu_arr, s, zmat):
    q = mu_arr[:, None] + zmat * s[:, None]
    i10, i50, i90, i05 = (QUANTS.index(x) for x in (0.10, 0.50, 0.90, 0.05))
    return {
        "n": int(len(y)),
        "coverage_80": round(float(np.mean((y >= q[:, i10]) & (y <= q[:, i90]))), 4),
        "below_p05": round(float(np.mean(y < q[:, i05])), 4),
        "above_base": round(float(np.mean(y > q[:, i50])), 4),
        "median_outcome_pct": round(float(np.expm1(np.median(y)) * 100), 3),
        "base_pct": round(float(np.expm1(np.median(mu_arr)) * 100), 3),
        "pinball": round(float(np.mean([pinball(y, q[:, k], p) for k, p in enumerate(QUANTS)])), 6),
    }


for hk, h in HORIZONS.items():
    S = samples[hk]
    per = PERIOD[S[:, 0].astype(int)]
    sdate = np.array([dates[int(i)] for i in S[:, 0]])
    y, ewv, lrv = S[:, 2], S[:, 3], S[:, 4]
    terc = tercile(S[:, 7])
    tr, te = per == 0, per == 1
    tr1, tr2 = tr & (sdate < TRAIN_MID), tr & (sdate >= TRAIN_MID)
    mu = DRIFT_LOG_PER_SESSION * h

    def sig(w, ewv=ewv, lrv=lrv):
        return np.clip(np.sqrt(w * ewv + (1 - w) * lrv), VOL_FLOOR, VOL_CAP) * math.sqrt(h)

    # 1. the EWMA weight, on the whole training window
    best = None
    for w in W_GRID:
        s = sig(w)
        zq = zfit((y[tr] - mu) / s[tr])
        loss = score_set(y[tr], mu, s[tr], quant_matrix(zq, terc[tr], int(tr.sum())))["pinball"]
        if best is None or loss < best[0]:
            best = (loss, w)
    w = best[1]
    s = sig(w)
    z_all = (y - mu) / s
    # 2. pooled or by volatility tercile: fitted on the first training year, judged on the second
    pooled_score = score_set(y[tr2], mu, s[tr2], quant_matrix(zfit(z_all[tr1]), terc[tr2], int(tr2.sum())))["pinball"]
    bucket_score = score_set(y[tr2], mu, s[tr2], quant_matrix(zfit(z_all[tr1], terc[tr1]), terc[tr2], int(tr2.sum())))["pinball"]
    use_buckets = bool(bucket_score < pooled_score)
    # 3. refit the chosen variant on all of training; test once on the hold-out
    zq_pooled = zfit(z_all[tr])
    zq_bucket = zfit(z_all[tr], terc[tr])
    zq_final = zq_bucket if use_buckets else zq_pooled
    test = score_set(y[te], mu, s[te], quant_matrix(zq_final, terc[te], int(te.sum())))
    train = score_set(y[tr], mu, s[tr], quant_matrix(zq_final, terc[tr], int(tr.sum())))
    untilted_test = dict(test)

    # 4. The tilt. PRE-REGISTERED, fixed before this block was first run:
    #    composite c = mean percentile of the signals that passed the IC rule at this
    #    horizon; slope b = OLS of the outcome on (c - 0.5), fitted on training only;
    #    base case mu_i = drift + b * (c_i - 0.5); the tilt ships only if it lowers the
    #    hold-out pinball loss against the untilted model with the same range model.
    passing = [n for n in ("mom_12_1", "prox_52w", "low_vol") if report["signals"][hk][n]["passes"]]
    colmap = {"mom_12_1": 8, "prox_52w": 9, "low_vol": 10}
    if passing:
        c = np.nanmean(S[:, [colmap[n] for n in passing]], axis=1)
    else:
        c = np.full(len(y), 0.5)
    c = np.where(np.isnan(c), 0.5, c)
    x = c - 0.5

    def ols(mask, x=x, y=y):
        xm, ym = x[mask], y[mask]
        vx = float(np.var(xm))
        return float(np.cov(xm, ym, ddof=0)[0, 1] / vx) if vx > 0 else 0.0

    beta = ols(tr) if passing else 0.0
    mu_t = mu + beta * x
    zt_all = (y - mu_t) / s
    zq_t = zfit(zt_all[tr], terc[tr]) if use_buckets else zfit(zt_all[tr])
    test_t = score_set_mu(y[te], mu_t[te], s[te], quant_matrix(zq_t, terc[te], int(te.sum())))
    keep_tilt = bool(passing) and test_t["pinball"] < untilted_test["pinball"]
    quint = []
    for qi in range(5):
        hi_ = (qi + 1) / 5 if qi < 4 else 1.01
        m = te & (c >= qi / 5) & (c < hi_)
        if m.sum():
            quint.append({"quintile": qi + 1, "n": int(m.sum()),
                          "predicted_median_pct": round(float(np.expm1(np.median(mu_t[m])) * 100), 2),
                          "realized_median_pct": round(float(np.expm1(np.median(y[m])) * 100), 2),
                          "realized_mean_pct": round(float(np.mean(np.expm1(y[m])) * 100), 2)})
    if keep_tilt:
        test = test_t

    # 5. What ships: the chosen model refitted on ALL outcomes, the rally and the decline.
    al = tr | te
    beta_all = ols(al) if keep_tilt else 0.0
    mu_all = mu + beta_all * x
    z_ship = (y - mu_all) / s
    zq_pooled_ship = zfit(z_ship[al])
    zq_bucket_ship = zfit(z_ship[al], terc[al])
    naive_s = np.clip(np.sqrt(lrv), VOL_FLOOR, VOL_CAP) * math.sqrt(h)
    normal = np.array([-1.645, -1.2816, -0.6745, 0.0, 0.6745, 1.2816, 1.645])
    naive = score_set(y[te], mu, naive_s[te], quant_matrix(normal, terc[te], int(te.sum())))
    by_liq, by_vol = {}, {}
    liq = S[:, 6]
    mu_used = mu_t if keep_tilt else np.full(len(y), mu)
    zq_used = zq_t if keep_tilt else zq_final
    for name, m in (("liquid", liq >= 5), ("mid", (liq >= 0.5) & (liq < 5)), ("thin", liq < 0.5)):
        mm = te & m
        by_liq[name] = score_set_mu(y[mm], mu_used[mm], s[mm], quant_matrix(zq_used, terc[mm], int(mm.sum())))
    for b in range(3):
        mm = te & (terc == b)
        by_vol[str(b)] = score_set_mu(y[mm], mu_used[mm], s[mm], quant_matrix(zq_used, terc[mm], int(mm.sum())))
    passed = bool(0.75 <= test["coverage_80"] <= 0.85 and 0.03 <= test["below_p05"] <= 0.08)
    report["horizons"][hk] = {"sessions": h, "ewma_weight": w, "use_buckets": use_buckets,
                              "tilt": {"signals": passing, "beta_train": round(beta, 5), "beta_all": round(beta_all, 5),
                                       "kept": keep_tilt, "untilted_test": untilted_test, "tilted_test": test_t,
                                       "quintiles_test": quint},
                              "variant_choice": {"pooled_pinball": pooled_score, "bucket_pinball": bucket_score},
                              "z_pooled": dict(zip(QK, np.round(zq_pooled, 4).tolist())),
                              "z_by_vol_tercile": {str(b): np.round(zq_bucket[b], 4).tolist() for b in range(3)},
                              "train": train, "test": test, "naive_test": naive, "passed": passed,
                              "test_by_liquidity": by_liq, "test_by_vol": by_vol}
    calib["horizons"][hk] = {"sessions": h, "ewma_weight": w, "use_buckets": use_buckets,
                             "z": dict(zip(QK, np.round(zq_pooled_ship, 4).tolist())),
                             "z_by_vol_tercile": {str(b): np.round(zq_bucket_ship[b], 4).tolist() for b in range(3)},
                             "tilt": ({"beta": round(beta_all, 5), "signals": passing} if keep_tilt else None)}

period = f"{TEST[0].strftime('%b %Y')} - {dates[-1].strftime('%b %Y')}"
calib["quantiles"] = list(QUANTS)
calib["validation"] = {}
for hk, hr in report["horizons"].items():
    te_ = hr["test"]
    calib["validation"][hk] = {
        "period": period, "passed": hr["passed"], "n": te_["n"], "coverage_80": te_["coverage_80"],
        "below_p05": te_["below_p05"], "above_base": te_["above_base"],
        "median_outcome_pct": te_["median_outcome_pct"], "base_pct": te_["base_pct"],
        "naive_coverage_80": hr["naive_test"]["coverage_80"],
        "by_liquidity": {k: v["coverage_80"] for k, v in hr["test_by_liquidity"].items() if v["n"] >= 500},
        "by_vol": {k: v["coverage_80"] for k, v in hr["test_by_vol"].items() if v["n"] >= 500},
    }
passing = [f"{hk}: " + " + ".join(hr["tilt"]["signals"]) for hk, hr in report["horizons"].items() if hr["tilt"]["kept"]]
calib["signals_summary"] = (
    "No price signal (12-1 month momentum, 1-month reversal, 52-week-high proximity, low volatility) "
    "predicted returns in both the training and the hold-out period, so the base case is India's "
    "long-run market drift alone and the estimates make no call on direction."
    if not passing else
    "Price signals that ranked NSE stocks' later returns in BOTH 2022-24 and 2024-26 (rank IC with "
    "|t| >= 2 in each) tilt the base case: " + "; ".join(passing) + ". The tilt was sized on 2022-24 "
    "only and kept because it lowered the 2024-26 test loss; the range stays centred on it.")
calib["method"] = (
    "Each range is the stock's own daily volatility (a blend of a fast EWMA and its one-year level, "
    "fitted per horizon), scaled to the horizon and stretched to the fat-tailed outcomes NSE stocks "
    "actually showed in 2022-24, around India's long-run market drift of about 11% a year. Bear and "
    "bull are the 10th and 90th percentiles, the downside the 5th. The model was fitted on Nov 2022 - "
    "Oct 2024 and tested once, unchanged, on what happened from Nov 2024.")
calib["data"] = report["data"]

OUT.mkdir(parents=True, exist_ok=True)
json.dump(report, open(OUT / "validation_report.json", "w"), indent=2)
json.dump(calib, open(OUT / "calibration.json", "w"), indent=2)
print(json.dumps(report, indent=1)[:6000])
