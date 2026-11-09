"""Correctness checks of the 103 strategies (counts only: nothing here measures performance).

1. Look-ahead (the truncation test of the earlier studies): every market is cut at random minutes and the books are run
   again on the shorter data. The signals already known at the cut (signal row < cut - 1) must equal the full run's,
   field by field (side, stop, entry orders, target, per-trade settings), and so must every trade already closed at the
   cut (exit row < cut - 1). A rule that peeks at later bars, or an exit that does, fails it.
2. Smoke replay: every book runs on recent data; each trade's fills lie inside its rows' price range (plus the spread
   and slippage), its rows are in order and its numbers are finite.
Writes results/checks.json.      python -I yc_checks.py [cuts=3] [SID,SID,...]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import yc_markets as MK  # noqa: E402
import yc_run as R  # noqa: E402
from yc_strategies import STRATEGIES  # noqa: E402

CUTS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
DAYS = {"NIFTY": 45, "BANKNIFTY": 45, "XAUUSD": 45, "EURUSD": 45, "GBPUSD": 45, "NAS100": 45, "BTCUSD": 75}
POOL_SYMBOLS = 8
NSED_STOCKS = 40
SKIP_INFO = {"k_last"}           # a time exit at the next session's end: known by the calendar, cut by the data


def r6(x):
    return None if x is None else round(float(x), 6)


def sig_key(s):
    info = tuple(sorted((k, r6(v) if isinstance(v, (float, np.floating, int, np.integer)) and not isinstance(v, bool) else repr(v))
                        for k, v in s.info.items() if k not in SKIP_INFO))
    alt = None if s.alt is None else (s.alt.side, r6(s.alt.stop), r6(s.alt.entry_stop))
    return (int(s.k), int(s.side), r6(s.stop), r6(s.entry_stop), r6(s.entry_limit), r6(s.target_px), s.setup, info, alt)


def trade_key(t):
    return (int(t.entry_k), int(t.exit_k), int(t.side), r6(t.entry), r6(t.exit), t.reason, t.setup)


def fill_ok(m, t) -> tuple[list[str], int]:
    """(problems, conservative fills) of one trade. A problem is a broken row order, a number that is not finite, or an
    optimistic fill: a price better than anything the row traded (beyond the spread and slippage the engine charges).
    A conservative fill (worse than the row's range: the YouTube engine fills a gap through a target at the target, and
    prices exit slippage off the entry) is only counted."""
    bad, worse = [], 0
    n = len(m.t)
    if not (0 <= t.entry_k <= t.exit_k < n):
        return [f"rows {t.entry_k}..{t.exit_k} of {n}"], 0
    for nm in ("entry", "exit", "r_net", "r_gross", "risk"):
        if not np.isfinite(getattr(t, nm)):
            bad.append(f"{nm} not finite")
    cost = m.cost
    for k, px, what, buying in ((t.entry_k, t.entry, "entry", t.side > 0), (t.exit_k, t.exit, "exit", t.side < 0)):
        half = float(m.half[k]) if np.isfinite(m.half[k]) else 0.0
        ref = max(abs(float(t.entry)), abs(float(t.exit)), float(m.h[k]))
        slip = float(getattr(cost, "slip", 0.0) or 0.0) + float(getattr(cost, "pct_slip", 0.0) or 0.0) * ref
        tol = (half + slip) * 1.001 + 1e-9 * ref
        lo, hi = float(m.l[k]) - tol, float(m.h[k]) + tol
        if buying and px < lo or (not buying) and px > hi:
            bad.append(f"{what} {px:.6g} better than row {k} [{m.l[k]:.6g}, {m.h[k]:.6g}]")
        elif px < lo or px > hi:
            worse += 1
    return bad, worse


class Universe:
    """The research markets of one cut (cut=None: the full window), with each market's cache."""

    def __init__(self, base: dict, t_cut: int | None):
        self.base, self.t_cut = base, t_cut
        self.m: dict = {}
        self.cache: dict = {}

    def market(self, name):
        if name not in self.m:
            self.m[name] = self._cut(self.base.get(name), name)
            self.cache[name] = {}
        return self.m[name]

    def _cut(self, m, name):
        if m is None:
            return None
        if isinstance(m, list):
            out = []
            for x in m:
                y = self._cut(x, name)
                if y is not None and len(y.t) > 10:
                    out.append(y)
            return out
        if self.t_cut is None:
            return m
        if name == "NSED":                       # the bhavcopy of the cut day is not published until the evening
            day = np.datetime64(int(self.t_cut // 86400 + (19800 // 86400)), "D")
            k = int(np.searchsorted(m.date, day, "left"))
        else:
            k = int(np.searchsorted(m.t, self.t_cut, "right"))
        return None if k < 2 else MK.cut(m, k - 1)


def load_base() -> dict:
    t0 = time.time()
    base = {nm: MK.window(nm, d) for nm, d in DAYS.items()}
    btc = base["BTCUSD"]
    eth = MK.full("ETHUSD")
    if eth is not None and btc is not None:
        a = int(np.searchsorted(eth.t, int(btc.t[0]), "left"))
        z = int(np.searchsorted(eth.t, int(btc.t[-1]), "right"))
        base["ETHUSD"] = MK.cut(eth, z - 1, first_row=a) if z - a > 1000 else None
    nifty_full = MK.full("NIFTY_D")
    base["NIFTY_D"] = MK._cut_daily(nifty_full, max(0, len(nifty_full.t) - 400), len(nifty_full.t))
    nsed = MK.nsed(limit=NSED_STOCKS)
    base["NSED"] = nsed
    have = set(p.stem for p in Path("D:/intraday_ai_data/intraday/5m").glob("*.ibar"))
    syms = [m.name for m in nsed if m.name in have][:POOL_SYMBOLS]
    pool = MK.nse_pool(syms, 45)
    base["NSE5"] = base["NSE15"] = pool
    print("data loaded in", round(time.time() - t0, 1), "s; pool", syms, flush=True)
    return base


def run_strategy(sid: str, U: Universe) -> dict:
    """{market or 'market|symbol': (signal keys, trades, market)} of one strategy on one universe."""
    st = STRATEGIES[sid]
    out = {}
    for market in st.markets:
        ms = U.market(market)
        if ms is None:
            continue
        if st.kind == "basket":
            res = R.run_basket(sid, ms)
            by = {m.name: m for m in ms}
            for sym, tr in res.items():
                out[f"{market}|{sym}"] = (set(), tr, by[sym])
            continue
        cx = R.contexts(set(st.needs), nifty=U.market("NIFTY") if "nifty_gap" in st.needs else None,
                        nsed=U.market("NSED") if "nj20" in st.needs else None,
                        pool=U.market(market) if "ss03" in st.needs else None)
        p = {"ctx": cx} if cx else {}
        if "box" in st.needs:
            p["box"] = 1000.0                    # a fixed box, as the desk fixes it once
        other = U.market("ETHUSD") if "ETHUSD" in st.needs else None
        for m in (ms if isinstance(ms, list) else [ms]):
            cache = U.cache.setdefault((market, m.name), {})
            tr, _, S = R.run(sid, market, m, cache, p, other)
            out[f"{market}|{m.name}"] = ({sig_key(s) for s in S}, tr, m)
    return out


def main():
    base = load_base()
    rng = np.random.default_rng(11)
    sids = [s for s in STRATEGIES if ONLY is None or s in ONLY]
    full = Universe(base, None)
    ref_t = {nm: (base[nm][0].t if isinstance(base[nm], list) else base[nm].t) for nm in base if base[nm] is not None}
    results, problems = {}, {}
    t_all = time.time()
    # cut minutes per market family, drawn once so every strategy on a market sees the same cuts
    cut_times = {}
    for nm, t in ref_t.items():
        if nm == "ETHUSD":
            continue
        lo = len(t) // 3
        cut_times[nm] = [int(t[i]) for i in rng.integers(lo, len(t) - 5, CUTS)]
    cut_univ = {}
    for sid in sids:
        st = STRATEGIES[sid]
        t1 = time.time()
        try:
            F = run_strategy(sid, full)
        except Exception as exc:  # noqa: BLE001
            results[sid] = {"error": repr(exc)}
            print(sid, "ERROR", repr(exc), flush=True)
            continue
        smoke = {"signals": sum(len(v[0]) for v in F.values()), "trades": sum(len(v[1]) for v in F.values()),
                 "reasons": dict(Counter(t.reason for v in F.values() for t in v[1]))}
        bad, worse = [], 0
        for key, (_, tr, m) in F.items():
            for t in tr:
                msgs, w = fill_ok(m, t)
                worse += w
                bad += [f"{key} {t.setup} {msg}" for msg in msgs]
        smoke["conservative_fills"] = worse
        look = True
        diffs = []
        for market in st.markets:
            fam = "NSE5" if market == "NSE15" else market
            for ci, tc in enumerate(cut_times.get(fam, [])):
                ck = (fam, ci)
                if ck not in cut_univ:
                    cut_univ[ck] = Universe(base, tc)
                U = cut_univ[ck]
                try:
                    P = run_strategy(sid, U)
                except Exception as exc:  # noqa: BLE001
                    look = False
                    diffs.append(f"cut {ci}: {exc!r}")
                    continue
                for key, (fs, ftr, fm) in F.items():
                    if not key.startswith(market + "|"):
                        continue
                    ps, ptr, pm = P.get(key, (set(), [], None))
                    if pm is None:
                        continue
                    cut_row = len(pm.t) - 1
                    ks = {x for x in fs if x[0] < cut_row - 1}
                    kp = {x for x in ps if x[0] < cut_row - 1}
                    kt = {trade_key(t) for t in ftr if t.exit_k < cut_row - 1}
                    kq = {trade_key(t) for t in ptr if t.exit_k < cut_row - 1}
                    if ks != kp:
                        look = False
                        diffs.append(f"{key} cut {ci} signals: " + "; ".join(map(str, sorted(ks ^ kp, key=str)[:2])))
                    if kt != kq:
                        look = False
                        diffs.append(f"{key} cut {ci} trades: " + "; ".join(map(str, sorted(kt ^ kq, key=str)[:2])))
        results[sid] = {**smoke, "lookahead_ok": look, "fill_problems": len(bad), "seconds": round(time.time() - t1, 1)}
        if diffs or bad:
            problems[sid] = {"lookahead": diffs[:6], "fills": bad[:6]}
        print(f"{sid:6s} signals {smoke['signals']:6d} trades {smoke['trades']:5d} look-ahead {'ok' if look else 'DIFFERS'}"
              f"  fills {'ok' if not bad else len(bad)}  {results[sid]['seconds']}s", flush=True)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "checks.json").write_text(json.dumps({"results": results, "problems": problems}, indent=1, default=str))
    failed = [s for s, r in results.items() if r.get("error") or not r.get("lookahead_ok") or r.get("fill_problems")]
    print("strategies", len(results), "failed", failed, "in", round(time.time() - t_all), "s")


if __name__ == "__main__":
    main()
