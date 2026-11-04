"""Audit of the 54 tournament strategies — code-level checks (read-only; no rule is changed).

    python audit54_checks.py --symbols 30 --days 10

1. LOOK-AHEAD. Every rule, at every bar close of a sampled day, is evaluated on a series that
   runs FIVE SESSIONS PAST that close (as the backtest holds it) and on a series CUT at the
   close (fresh objects, nothing after it exists). Both start at the same bar, so warm-up is
   identical and any difference means the rule or its context read the future.
2. LIVE WINDOW. The same close evaluated on the live engine's own window (420 x 15m bars;
   220 x 45m / 1h bars aggregated exactly as intraday_store.series does). Differences are
   signals the live tournament and the backtest disagree on because of indicator warm-up.
3. SWALLOWED ERRORS. evaluate() turns IndexError / ValueError / ZeroDivisionError / TypeError
   into "no signal". Each rule is called directly here and every exception is counted.
4. INDICATOR DEFINITIONS. RSI, MACD, Bollinger, CCI, stochastic and VWAP against plain
   reference formulas; ATR, ADX and Supertrend against Wilder's definitions (what charting
   platforms show) — how often ADX's cross of 25 and Supertrend's flips coincide.
5. BAR STRUCTURE. The 15:15-15:30 stub bar that ends every 45m and 1h session, and how often
   the volume filter (bar volume >= 1.2 x the last 20 bars, not time-of-day adjusted) passes
   at each bar of the day.
Writes DATA/runs/audit54/checks.json.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA, activate, build  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
LIVE_WINDOW = {"15m": 420, "45m": 220, "1h": 220}
FACTOR = {"15m": 1, "45m": 3, "1h": 4}
MIN = {"15m": 15, "45m": 45, "1h": 60}


def wilder(vals, n):
    out, prev = [], None
    for k, x in enumerate(vals):
        if k < n - 1:
            out.append(float("nan"))
        elif k == n - 1:
            prev = sum(vals[:n]) / n
            out.append(prev)
        else:
            prev = (prev * (n - 1) + x) / n
            out.append(prev)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--seed", type=int, default=54)
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--order-only", action="store_true",
                    help="only test 6: the rules give the same signals in catalog and in reversed order")
    a = ap.parse_args()
    activate(build(a.commit))
    from app.services import intraday_v2_strategies as v2
    from app.services import nifty_scalp_strategies as ns
    from app.services.intraday_store import aggregate, day_key, read_file
    from app.services.intraday_v2_backtest import _days, _rvol, _series

    rng = random.Random(a.seed)
    files = sorted(p.stem for p in (DATA / "intraday" / "15m").glob("*.ibar") if p.stem not in ("NIFTY",))
    pool = [s for s in files if len(read_file(s)) > 25 * 300]
    syms = sorted(rng.sample(pool, min(a.symbols, len(pool))))
    specs = [s for s in v2.CATALOG if not s.family.startswith("orb_sel")]

    def sig_key(sig):
        if sig is None:
            return None
        r = lambda x: None if x is None else round(float(x), 6)  # noqa: E731
        return (sig.side, r(sig.entry), r(sig.stop_dist), r(sig.target_dist), r(sig.target_price), r(sig.trigger))

    if a.order_only:
        # 6. INDEPENDENCE. Indicator arrays are cached on each Series and shared by every rule
        # that asks for the same key; the per-day ATR cache is shared by all rules. Evaluate
        # every close twice on FRESH series - catalog order, then reversed - so each cache is
        # filled by a different rule first. Any difference = one rule's state leaks into another.
        compared = differ = 0
        for sym in syms:
            rows = list(read_file(sym).rows())
            times = [r[0] for r in rows]
            sess = sorted({day_key(t) for t in times})
            for dk in sorted(rng.sample(sess[45:-6], min(a.days, len(sess) - 51))):
                ds = dk * 86400 - 19800
                for mins in range(9 * 60 + 45, 14 * 60 + 30, 15):
                    b = ds + mins * 60
                    kc = bisect_right(times, b - 900)
                    lo = max(0, kc - 1200)
                    m = mins - (9 * 60 + 15)
                    tfs = ["15m"] + (["45m"] if m % 45 == 0 else []) + (["1h"] if m % 60 == 0 else [])
                    now = datetime.fromtimestamp(b, IST)
                    got = []
                    for order in (specs, list(reversed(specs))):
                        v2._ATR_DAY.clear()
                        ser = {"15m": _series(rows[lo:kc]), "45m": _series(aggregate(rows[lo:kc], 45, b)),
                               "1h": _series(aggregate(rows[lo:kc], 60, b))}
                        ctxs = {}
                        for tf in tfs + (["day"] if mins == 9 * 60 + 45 else []):
                            stf = "15m" if tf == "day" else tf
                            ctxs[tf] = v2.build_ctx(sym, stf, now, ser[stf], ser["15m"], 1.0, 1, None, None)
                        res = {}
                        for spec in order:
                            ctx = ctxs.get(spec.tf)
                            if ctx is not None:
                                res[spec.strategy_id] = sig_key(v2.evaluate(spec, ctx))
                        got.append(res)
                    for sid in got[0]:
                        compared += 1
                        differ += int(got[0][sid] != got[1].get(sid))
            print(f"{sym}: {compared} compared, {differ} differ", flush=True)
        p = DATA / "runs" / "audit54" / "checks.json"
        doc = json.load(open(p, encoding="utf-8")) if p.exists() else {}
        doc["order_independence"] = {"symbols": syms, "days_per_symbol": a.days, "compared": compared, "differ": differ}
        json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, default=str)
        print(json.dumps(doc["order_independence"]))
        return

    def run_rules(ctx, tf, errors=None):
        out = {}
        for spec in specs:
            if spec.tf != tf:
                continue
            try:
                sig = v2._FN[spec.family](ctx, spec.params)
            except Exception as e:  # noqa: BLE001 - counted, as evaluate() would swallow it
                if errors is not None:
                    errors[spec.strategy_id][type(e).__name__] += 1
                sig = None
            if sig is not None and (sig.stop_dist <= 0 or sig.entry <= 0):
                sig = None
            out[spec.strategy_id] = sig_key(sig)
        return out

    look = defaultdict(lambda: Counter())       # sid -> {compared, signals_full, mismatch}
    window = defaultdict(lambda: Counter())
    errors = defaultdict(Counter)
    examples = {"look_ahead": [], "live_window": []}
    t0 = time.time()
    n_points = 0
    for sym in syms:
        rows = list(read_file(sym).rows())
        times = [r[0] for r in rows]
        keys = [day_key(r[0]) for r in rows]
        sess = sorted(set(keys))
        first_of = {}
        for k, dk in enumerate(keys):
            first_of.setdefault(dk, k)
        cands = sess[45:-6]
        for dk in sorted(rng.sample(cands, min(a.days, len(cands)))):
            si = sess.index(dk)
            S = first_of[sess[si - 40]]
            E = first_of[sess[si + 6]]            # five full sessions after the test day
            seg = rows[S:E]
            full = {"15m": _series(seg), "45m": _series(aggregate(seg, 45, 2 ** 40)),
                    "1h": _series(aggregate(seg, 60, 2 ** 40))}
            dlist = _days(full["15m"])
            di = next(k for k, d in enumerate(dlist) if d.key == dk)
            ds = dk * 86400 - 19800
            for mins in range(9 * 60 + 45, 14 * 60 + 30, 15):
                b = ds + mins * 60
                m = mins - (9 * 60 + 15)
                tfs = ["15m"] + (["45m"] if m % 45 == 0 else []) + (["1h"] if m % 60 == 0 else [])
                day_setup = mins == 9 * 60 + 45
                j_full = bisect_right(full["15m"].epochs, b - 900) - 1
                kk = j_full - dlist[di].j0 + 1
                if kk < 1 or full["15m"].epochs[j_full] != b - 900:
                    continue
                rv = _rvol(dlist, di, kk)
                now = datetime.fromtimestamp(b, IST)
                kc = bisect_right(times, b - 900, S)   # rows closed by b
                cut_rows = rows[S:kc]
                cut = {"15m": _series(cut_rows), "45m": _series(aggregate(cut_rows, 45, b)),
                       "1h": _series(aggregate(cut_rows, 60, b))}
                live = {}
                for tf in ("15m", "45m", "1h"):
                    lo = max(0, kc - (LIVE_WINDOW[tf] + 2) * FACTOR[tf] - 25)
                    rr = rows[lo:kc]
                    if tf != "15m":
                        rr = aggregate(rr, MIN[tf], b)
                        if lo > 0 and rr:
                            rr = rr[1:]
                    live[tf] = _series(rr[-LIVE_WINDOW[tf]:])
                for tf in tfs + (["day"] if day_setup else []):
                    stf = "15m" if tf == "day" else tf
                    if tf == "day":
                        i_full = j_full
                    else:
                        i_full = bisect_left(full[stf].epochs, b - MIN[stf] * 60)
                        if i_full >= len(full[stf]) or full[stf].epochs[i_full] != b - MIN[stf] * 60:
                            continue
                    res = {}
                    for name, ser, i, j in (("full", full, i_full, j_full),
                                            ("cut", cut, len(cut[stf]) - 1, len(cut["15m"]) - 1),
                                            ("live", live, len(live[stf]) - 1, len(live["15m"]) - 1)):
                        v2._ATR_DAY.clear()
                        ctx = v2.build_ctx(sym, stf, now, ser[stf], ser["15m"], rv, 1, None, None, i=i, j=j)
                        res[name] = run_rules(ctx, tf, errors if name == "full" else None) if ctx else {}
                    n_points += 1
                    for spec in specs:
                        if spec.tf != tf:
                            continue
                        sid = spec.strategy_id
                        f, c, lv = (res[x].get(sid) for x in ("full", "cut", "live"))
                        look[sid]["compared"] += 1
                        look[sid]["signals"] += int(f is not None or c is not None)
                        if f != c:
                            look[sid]["mismatch"] += 1
                            if len(examples["look_ahead"]) < 20:
                                examples["look_ahead"].append([sid, sym, now.isoformat(), f, c])
                        window[sid]["compared"] += 1
                        window[sid]["signals"] += int(c is not None or lv is not None)
                        if c != lv:
                            window[sid]["mismatch"] += 1
                            if lv is None or c is None or lv[0] != c[0]:
                                window[sid]["different_decision"] += 1
                            if len(examples["live_window"]) < 30:
                                examples["live_window"].append([sid, sym, now.isoformat(), c, lv])
        print(f"{sym}: {n_points} evaluation points, {time.time() - t0:.0f}s", flush=True)

    # ── 4. indicator definitions ──
    ind = defaultdict(list)
    for sym in syms:
        rows = list(read_file(sym).rows())
        for tf in ("15m", "45m", "1h"):
            s = _series(rows if tf == "15m" else aggregate(rows, MIN[tf], 2 ** 40))
            n = len(s)
            if n < 400:
                continue
            c = s.c
            # RSI(14): Wilder, seeded with the mean of the first 14 changes
            d = [0.0] + [c[k] - c[k - 1] for k in range(1, n)]
            g = wilder([max(x, 0.0) for x in d[1:]], 14)
            lo = wilder([max(-x, 0.0) for x in d[1:]], 14)
            ref_rsi = [float("nan")] + [100 - 100 / (1 + gg / ll) if ll else 100.0 for gg, ll in zip(g, lo)]
            imp_rsi = ns.rsi(c, 14)
            ind[f"rsi14_maxdiff_after300_{tf}"].append(max(abs(x - y) for x, y in zip(imp_rsi[300:], ref_rsi[300:])))
            # MACD(12,26,9): EMAs seeded with SMA
            def ema_sma(v, p):
                out = [float("nan")] * (p - 1) + [sum(v[:p]) / p]
                for x in v[p:]:
                    out.append(x * 2 / (p + 1) + out[-1] * (1 - 2 / (p + 1)))
                return out
            line = [x - y for x, y in zip(ema_sma(c, 12), ema_sma(c, 26))]
            sig = [float("nan")] * 25 + ema_sma(line[25:], 9)
            ref_h = [x - y for x, y in zip(line, sig)]
            _l, _s, imp_h = ns.macd(c, 12, 26, 9)
            ind[f"macd_hist_maxdiff_after300_rel_{tf}"].append(
                max(abs(x - y) / c[k] for k, (x, y) in enumerate(zip(imp_h, ref_h)) if k >= 300))
            # Bollinger 20/2: population SD
            sd_imp = ns.stdev(c, 20)
            ind[f"bollinger_sd_maxdiff_{tf}"].append(max(abs(sd_imp[k] - statistics.pstdev(c[k - 19:k + 1]))
                                                         for k in range(19, n, 7)))
            # CCI(20): mean absolute deviation around the SMA
            tp = [(s.h[k] + s.l[k] + s.c[k]) / 3 for k in range(n)]
            cci_imp = ns.cci(s, 20)
            dmax = 0.0
            for k in range(19, n, 7):
                w = tp[k - 19:k + 1]
                mm = sum(w) / 20
                md = sum(abs(x - mm) for x in w) / 20
                ref = (tp[k] - mm) / (0.015 * md) if md else 0.0
                dmax = max(dmax, abs(ref - cci_imp[k]))
            ind[f"cci20_maxdiff_{tf}"].append(dmax)
            # ATR(14), ADX(14), Supertrend(10,3): as implemented (EMA, alpha 2/(n+1)) vs Wilder
            tr = ns.true_range(s)
            atr_imp = ns.ema(tr, 14)
            atr_w = wilder(tr, 14)
            ratios = sorted(atr_imp[k] / atr_w[k] for k in range(100, n) if atr_w[k])
            ind[f"atr14_impl_over_wilder_p10_{tf}"].append(ratios[len(ratios) // 10])
            ind[f"atr14_impl_over_wilder_p90_{tf}"].append(ratios[len(ratios) * 9 // 10])
            adx_imp, _p, _n = ns.adx_di(s, 14)
            pdm, ndm = [0.0], [0.0]
            for k in range(1, n):
                up, dn = s.h[k] - s.h[k - 1], s.l[k - 1] - s.l[k]
                pdm.append(up if up > dn and up > 0 else 0.0)
                ndm.append(dn if dn > up and dn > 0 else 0.0)
            trw, pw, nw = wilder(tr[1:], 14), wilder(pdm[1:], 14), wilder(ndm[1:], 14)
            dx = []
            for t_, p_, n_ in zip(trw, pw, nw):
                if t_ != t_ or not t_:
                    dx.append(float("nan"))
                    continue
                pdi, ndi = 100 * p_ / t_, 100 * n_ / t_
                dx.append(100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi else 0.0)
            first = next(k for k, x in enumerate(dx) if x == x)
            adx_w = [float("nan")] * (first + 1) + wilder(dx[first:], 14)
            adx_w = adx_w[:n]

            def crosses(arr, lvl=25.0):
                return {k for k in range(200, n) if arr[k - 1] == arr[k - 1] and arr[k] == arr[k]
                        and arr[k - 1] < lvl <= arr[k]}
            A, W = crosses(adx_imp), crosses(adx_w)
            ind[f"adx25_cross_impl_{tf}"].append(len(A))
            ind[f"adx25_cross_wilder_{tf}"].append(len(W))
            ind[f"adx25_cross_impl_matched_by_wilder_pm1_{tf}"].append(
                sum(1 for k in A if {k - 1, k, k + 1} & W))
            ind[f"adx_impl_below20_share_{tf}"].append(sum(1 for x in adx_imp[200:] if x < 20) / (n - 200))
            ind[f"adx_wilder_below20_share_{tf}"].append(sum(1 for x in adx_w[200:] if x == x and x < 20) / (n - 200))
            st_imp = ns.supertrend(s, 10, 3.0)
            a_w = wilder(tr, 10)
            dirs, pu, pd_, dd = [], None, None, 1
            for k in range(n):
                if a_w[k] != a_w[k]:
                    dirs.append(1)
                    continue
                mid = (s.h[k] + s.l[k]) / 2
                up, dn = mid - 3 * a_w[k], mid + 3 * a_w[k]
                if pu is not None:
                    up = max(up, pu) if s.c[k - 1] > pu else up
                    dn = min(dn, pd_) if s.c[k - 1] < pd_ else dn
                    dd = 1 if s.c[k] > dn else -1 if s.c[k] < up else dd
                dirs.append(dd)
                pu, pd_ = up, dn
            F1 = {k for k in range(200, n) if st_imp[k] != st_imp[k - 1]}
            F2 = {k for k in range(200, n) if dirs[k] != dirs[k - 1]}
            ind[f"supertrend_flips_impl_{tf}"].append(len(F1))
            ind[f"supertrend_flips_wilder_{tf}"].append(len(F2))
            ind[f"supertrend_flips_matched_pm1_{tf}"].append(sum(1 for k in F1 if {k - 1, k, k + 1} & F2))
    indicators = {k: (round(sum(v), 4) if any(x in k for x in ("cross", "flips")) else
                      round(statistics.median(v), 6)) for k, v in ind.items()}

    # ── 5. bar structure ──
    bars = defaultdict(list)
    volpass = defaultdict(lambda: [0, 0])
    for sym in syms:
        rows = list(read_file(sym).rows())
        for tf in ("15m", "45m", "1h"):
            s = _series(rows if tf == "15m" else aggregate(rows, MIN[tf], 2 ** 40))
            mod = [(datetime.fromtimestamp(t, IST).hour * 60 + datetime.fromtimestamp(t, IST).minute) for t in s.epochs]
            if tf != "15m":
                stub = [k for k in range(len(s)) if mod[k] == 15 * 60 + 15]
                fulls = [k for k in range(len(s)) if mod[k] != 15 * 60 + 15]
                rng_ = lambda k: (s.h[k] - s.l[k]) / s.c[k]  # noqa: E731
                bars[f"stub_range_over_full_{tf}"].append(statistics.median(rng_(k) for k in stub) /
                                                          statistics.median(rng_(k) for k in fulls))
                bars[f"stub_volume_over_full_{tf}"].append(statistics.median(s.v[k] for k in stub) /
                                                           max(statistics.median(s.v[k] for k in fulls), 1))
            for k in range(25, len(s)):
                avg = sum(s.v[k - 20:k]) / 20
                key = f"{tf} {mod[k] // 60:02d}:{mod[k] % 60:02d}"
                volpass[key][1] += 1
                volpass[key][0] += int(bool(avg) and s.v[k] >= 1.2 * avg)
    bar_struct = {k: round(statistics.median(v), 3) for k, v in bars.items()}
    bar_struct["volume_filter_pass_rate_by_bar_start"] = {k: round(p / n_, 3) for k, (p, n_) in sorted(volpass.items())}

    out = {"symbols": syms, "days_per_symbol": a.days, "evaluation_points": n_points,
           "look_ahead": {k: dict(v) for k, v in look.items()},
           "live_window": {k: dict(v) for k, v in window.items()},
           "swallowed_errors": {k: dict(v) for k, v in errors.items()},
           "examples": examples, "indicators": indicators, "bar_structure": bar_struct,
           "elapsed_s": round(time.time() - t0, 1)}
    p = DATA / "runs" / "audit54"
    p.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(p / "checks.json", "w", encoding="utf-8"), indent=1, default=str)
    tot = lambda d, k: sum(v.get(k, 0) for v in d.values())  # noqa: E731
    print(json.dumps({"points": n_points, "look_ahead_mismatch": tot(out["look_ahead"], "mismatch"),
                      "look_ahead_compared": tot(out["look_ahead"], "compared"),
                      "live_window_mismatch": tot(out["live_window"], "mismatch"),
                      "errors": {k: dict(v) for k, v in errors.items()}}, default=str))


if __name__ == "__main__":
    main()
