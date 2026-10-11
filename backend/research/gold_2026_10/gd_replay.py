"""Gold Desk replay, stages 0-2: every strategy in the desk's catalogue, on gold, honestly.

    python backend/research/gold_2026_10/gd_replay.py build      # stage 0: bars -> data/replay/bars/*.npz
    python backend/research/gold_2026_10/gd_replay.py run [N]    # stages 1-2 on N worker processes (default 8)

WHAT IS REPLAYED
----------------
The catalogue the desk itself trades (`commodity_patterns.COMMODITY_CATALOG`, 353 strategies =
46 templates x 8 timeframes), evaluated by the desk's own `evaluate()` on a window of the last
250 bars — the desk loads `max(need, 250)` — on CLOSED bars only (the desk as built evaluates
the bar still forming; that defect is measured separately in `gd_forming.py`).

EVERY signal is recorded with what would have happened had it been taken, so stage 3 can
apply the desk's position rules (one position per strategy per symbol; a shared book with
slots) without re-running the patterns.

HOW A SIGNAL IS FILLED (the honest model)
-----------------------------------------
  entry   the first 1-minute open after the signal bar closes (MCX: the next session minute,
          so a signal at the close fills at the next morning's open). The signal's target and
          stop are scaled by fill / signal close, exactly as `gold_desk._open` does.
  exits   walked minute by minute: a stop or target touched inside a minute fills at its level;
          a minute that OPENS beyond a level fills at that open (worse for a stop, better for a
          resting target); a minute touching both is a stop. Hold limit: the close of the 60th
          bar of the strategy's own timeframe.
  costs   none here — stage 3 applies each cost model to the gross prices.

THE DESK AS BUILT (the polled model, recorded alongside)
--------------------------------------------------------
`gold_desk.manage_cycle` reads one price every 180 s and exits at THAT price once it is past a
level — a target overshot between polls fills beyond the target, a stop beyond the stop — and
counts the hold in wall-clock time. Recorded per signal as `p_*` so the artefact can be sized.

DATASETS (see gd_quality.py for why each is trusted only where it is)
---------------------------------------------------------------------
  A_XAUT, A_PAXG  Delta's own XAUTUSD / PAXGUSD perps, 1m since launch. 24/7, UTC days.
  B_PAXG          Binance PAXG/USDT 1m from 2025-01-01 (before 2025 the token was too thin:
                  49-81% of minutes had no trade). 24/7, UTC days.
  C_GC            COMEX gold (GC=F) hourly 2024-05..2026-10 inside MCX hours, IST days, 1h/4h/1d;
                  exits on hourly bars.
  D_GOLDM         MCX GOLDM itself — the production bar store, joined across contracts the way
                  `commodity_bars.load_bars` joins them. Short: 1m from 2026-08-11.
  E_GCD           COMEX gold daily 2000-2026, 1d templates only, exits on daily bars.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BARS = DATA / "replay" / "bars"
OUT = DATA / "replay" / "signals"
ROOT = HERE.parents[2]
for p in (ROOT / "backend", ROOT / "strategy-service", ROOT / "shared"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

W = 250          # bars the desk hands a pattern
MAX_HOLD = 60    # bars of the strategy's own timeframe
POLL_MIN = 3     # the desk's manage cycle, minutes
IST = timezone(timedelta(hours=5, minutes=30))
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "4h": 240, "1d": 1440}
ALL_TFS = list(TF_MIN)

DATASETS = {
    "A_XAUT": dict(kind="utc", src="delta_XAUTUSD_1m.csv.gz", start=None, tfs=ALL_TFS),
    "A_PAXG": dict(kind="utc", src="delta_PAXGUSD_1m.csv.gz", start=None, tfs=ALL_TFS),
    "B_PAXG": dict(kind="utc", src="binance_PAXGUSDT_1m.csv.gz", start="2025-01-01", tfs=ALL_TFS),
    "C_GC": dict(kind="mcx_from_1h", src="yahoo_GC_1h.csv.gz", tfs=["1h", "4h", "1d"]),
    "D_GOLDM": dict(kind="mcx_native", src="gd_mcx_bars.csv.gz", tfs=ALL_TFS),
    "E_GCD": dict(kind="daily", src="yahoo_GC_1d.csv.gz", tfs=["1d"]),
}


# ═════════════════════════════════════════════════════════════════════════════
# stage 0 — bars
# ═════════════════════════════════════════════════════════════════════════════


def _save(name: str, ts_open, ts_close, o, h, l, c, v, tz: str) -> None:
    BARS.mkdir(parents=True, exist_ok=True)
    ts_open = np.asarray(ts_open, dtype=np.int64)
    ts_close = np.asarray(ts_close, dtype=np.int64)
    # a print stamped at or after the session close (seen on 7 MCX bars) still lasts a minute
    ts_close = np.where(ts_close <= ts_open, ts_open + 60, ts_close)
    np.savez_compressed(BARS / f"{name}.npz", ts=np.asarray(ts_open, dtype=np.int64),
                        tc=np.asarray(ts_close, dtype=np.int64), o=np.asarray(o, float),
                        h=np.asarray(h, float), l=np.asarray(l, float), c=np.asarray(c, float),
                        v=np.asarray(v, float), tz=np.array(tz))


def _epoch(idx) -> np.ndarray:
    """UTC epoch seconds, whatever unit pandas chose to store the index in."""
    return idx.tz_convert("UTC").as_unit("s").asi8.astype(np.int64)


def _continuous(rows):
    """`commodity_bars._continuous`, verbatim in logic: newest contract first, stepping to the
    next-older one where it runs out, ratio-adjusted at the latest time both printed."""
    import pandas as pd
    by_ts: dict = {}
    for r in rows.itertuples(index=False):
        by_ts.setdefault(r.ts, {})[str(r.expiry)] = r
    ts_desc = sorted(by_ts, reverse=True)
    if not ts_desc:
        return pd.DataFrame()
    cur = max(by_ts[ts_desc[0]])
    factor = 1.0
    out = []
    joins = 0
    for ts in ts_desc:
        row = by_ts[ts]
        if cur not in row:
            older = sorted((e for e in row if e < cur), reverse=True) or sorted(row)
            nxt = older[0]
            for t2 in ts_desc:
                both = by_ts[t2]
                if cur in both and nxt in both and both[nxt].close:
                    factor *= float(both[cur].close) / float(both[nxt].close)
                    joins += 1
                    break
            cur = nxt
        d = row[cur]
        out.append((ts, d.open * factor, d.high * factor, d.low * factor, d.close * factor, d.volume, cur))
    out.reverse()
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume", "expiry"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df.set_index("ts")


def build() -> None:
    import pandas as pd

    import gd_data as D

    def mcx_close_epoch(idx_ist) -> np.ndarray:
        """Session close (UTC epoch) for each bar's IST date."""
        days = idx_ist.normalize()
        cache = {}
        out = np.empty(len(idx_ist), dtype=np.int64)
        for j, d in enumerate(days):
            if d not in cache:
                cache[d] = int((d + pd.Timedelta(minutes=9 * 60 + D.mcx_close_minutes(d))).timestamp())
            out[j] = cache[d]
        return out

    for name, cfg in DATASETS.items():
        t0 = time.time()
        if cfg["kind"] == "utc":
            df = D.load_1m(cfg["src"])
            if cfg["start"]:
                df = df.loc[cfg["start"]:]
            last_min = df.index[-1]
            _save(f"{name}__exit", _epoch(df.index), _epoch(df.index) + 60, df.open, df.high, df.low,
                  df.close, df.volume, "UTC")
            for tf in cfg["tfs"]:
                b = D.resample_utc(df, tf)
                ts = _epoch(b.index)
                tc = ts + TF_MIN[tf] * 60
                keep = tc <= int(last_min.timestamp()) + 60          # drop the bar still forming
                _save(f"{name}__{tf}", ts[keep], tc[keep], b.open[keep], b.high[keep], b.low[keep],
                      b.close[keep], b.volume[keep], "UTC")
        elif cfg["kind"] == "mcx_from_1h":
            g = D.load_1m(cfg["src"])                       # hourly, UTC
            gi = g.copy()
            gi.index = gi.index.tz_convert(IST)
            mins = (gi.index.hour * 60 + gi.index.minute) - 9 * 60
            close_m = np.array([D.mcx_close_minutes(d) for d in gi.index.normalize()])
            gi = gi[(gi.index.dayofweek < 5) & (mins >= 0) & (mins < close_m)]
            sess_close = mcx_close_epoch(gi.index)
            ts = _epoch(gi.index)
            _save(f"{name}__exit", ts, np.minimum(ts + 3600, sess_close), gi.open, gi.high, gi.low,
                  gi.close, gi.volume, "IST")
            for tf in cfg["tfs"]:
                b = gi if tf == "1h" else D.resample_mcx(gi, tf)
                ts = _epoch(b.index)
                sc = mcx_close_epoch(b.index.tz_convert(IST))
                tc = sc if tf == "1d" else np.minimum(ts + TF_MIN[tf] * 60, sc)
                _save(f"{name}__{tf}", ts, tc, b.open, b.high, b.low, b.close, b.volume, "IST")
        elif cfg["kind"] == "mcx_native":
            m = pd.read_csv(DATA / cfg["src"])
            m = m[m.symbol == "GOLDM"]
            native = {}
            for tf in ("1m", "5m", "15m", "1h", "1d"):
                rows = m[m.timeframe == tf][["ts", "expiry", "open", "high", "low", "close", "volume"]]
                df = _continuous(rows)
                df.index = df.index.tz_convert(IST)
                native[tf] = df
            e = native["1m"]
            _save(f"{name}__exit", _epoch(e.index), _epoch(e.index) + 60, e.open, e.high, e.low, e.close,
                  e.volume, "IST")
            for tf in cfg["tfs"]:
                if tf in native:
                    b = native[tf]
                elif tf in ("30m", "45m"):
                    b = D.resample_mcx(native["15m"], tf)
                else:                                       # 4h from 1h, like the store
                    b = D.resample_mcx(native["1h"], "4h")
                ts = _epoch(b.index)
                sc = mcx_close_epoch(b.index.tz_convert(IST))
                tc = sc if tf == "1d" else np.minimum(ts + TF_MIN[tf] * 60, sc)
                _save(f"{name}__{tf}", ts, tc, b.open, b.high, b.low, b.close, b.volume, "IST")
                # the store's own fallback exit series for signals before the 1m history begins
                _save(f"{name}__exit_{tf}", ts, tc, b.open, b.high, b.low, b.close, b.volume, "IST")
        elif cfg["kind"] == "daily":
            g = D.load_1m(cfg["src"]).dropna()
            ts = _epoch(g.index)
            _save(f"{name}__1d", ts, ts + 86400, g.open, g.high, g.low, g.close, g.volume, "UTC")
            _save(f"{name}__exit", ts, ts + 86400, g.open, g.high, g.low, g.close, g.volume, "UTC")
        print(f"built {name} in {time.time() - t0:.1f}s", flush=True)


# ═════════════════════════════════════════════════════════════════════════════
# stages 1-2 — signals and their outcomes
# ═════════════════════════════════════════════════════════════════════════════


class Bar:
    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def _load(name: str) -> dict:
    z = np.load(BARS / f"{name}.npz")
    return {k: z[k] for k in z.files}


def _resolve(side: int, k0: int, ke: int, tgt: float, stp: float, X: dict):
    """Honest exit: (k, price, reason) — reason 0 target, 1 stop, 2 hold limit, 3 data ended."""
    o, h, l, c = X["o"], X["h"], X["l"], X["c"]
    if ke < k0:
        return k0, float(o[k0]), 3
    hs, ls = h[k0:ke + 1], l[k0:ke + 1]
    if side > 0:
        s_hit, t_hit = ls <= stp, hs >= tgt
    else:
        s_hit, t_hit = hs >= stp, ls <= tgt
    ks = int(np.argmax(s_hit)) if s_hit.any() else None
    kt = int(np.argmax(t_hit)) if t_hit.any() else None
    if ks is None and kt is None:
        return ke, float(c[ke]), 2 if X["full"][ke] else 3
    if kt is not None and (ks is None or kt < ks):
        k = k0 + kt
        px = float(o[k])
        better = px >= tgt if side > 0 else px <= tgt
        return k, (px if (better and k > k0) else tgt), 0
    k = k0 + ks
    px = float(o[k])
    if kt is not None and kt == ks:            # one minute touched both
        if k > k0 and (px >= tgt if side > 0 else px <= tgt):
            return k, px, 0
        return k, (px if (k > k0 and (px <= stp if side > 0 else px >= stp)) else stp), 1
    worse = px <= stp if side > 0 else px >= stp
    return k, (px if (worse and k > k0) else stp), 1


def _resolve_polled(side: int, k0: int, tgt: float, stp: float, wall_end: int, X: dict):
    """The desk as built: one look every POLL_MIN minutes at the latest close, exit AT that
    price once past a level; the hold is wall-clock (`bars_held` from elapsed time)."""
    c, ts = X["c"], X["ts"]
    kmax = int(np.searchsorted(ts, wall_end, side="left")) - 1
    kmax = min(kmax, len(c) - 1)
    if kmax < k0:
        return k0, float(c[k0]), 3
    idx = np.arange(k0 + POLL_MIN - 1, kmax + 1, POLL_MIN)
    if len(idx) == 0:
        return kmax, float(c[kmax]), 2
    cs = c[idx]
    if side > 0:
        hit = (cs >= tgt) | (cs <= stp)
    else:
        hit = (cs <= tgt) | (cs >= stp)
    if hit.any():
        j = int(idx[int(np.argmax(hit))])
        px = float(c[j])
        tgt_hit = px >= tgt if side > 0 else px <= tgt
        return j, px, 0 if tgt_hit else 1
    return kmax, float(c[kmax]), 2 if X["full"][kmax] else 3


def run_job(job: tuple) -> tuple:
    dataset, tf, templates = job
    from app.services.commodity_patterns import COMMODITY_CATALOG, evaluate

    t0 = time.time()
    B = _load(f"{dataset}__{tf}")
    X = _load(f"{dataset}__exit")
    X["full"] = np.ones(len(X["c"]), dtype=bool)
    X["full"][-1] = False                          # the last minute of the data is not a real exit
    fallback = None
    if dataset == "D_GOLDM" and (BARS / f"{dataset}__exit_{tf}.npz").exists():
        fallback = _load(f"{dataset}__exit_{tf}")
        fallback["full"] = np.ones(len(fallback["c"]), dtype=bool)
        fallback["full"][-1] = False
    tz = timezone.utc if str(B["tz"]) == "UTC" else IST
    specs = [s for s in COMMODITY_CATALOG if s.timeframe == tf and s.template in templates]
    n = len(B["c"])
    dq: deque = deque(maxlen=W)
    raw: dict[str, list] = {s.template: [] for s in specs}
    for i in range(n):
        dq.append(Bar(datetime.fromtimestamp(int(B["ts"][i]), tz), float(B["o"][i]), float(B["h"][i]),
                      float(B["l"][i]), float(B["c"][i]), float(B["v"][i])))
        if i + 1 < 65 or i == n - 1:               # the desk skips a series under 65 bars; no next bar
            continue
        window = list(dq)
        for s in specs:
            if i + 1 < s.min_bars + 5:
                continue
            sig = evaluate(s, window)
            if sig is None:
                continue
            raw[s.template].append((i, 1 if sig.side == "BUY" else -1, float(sig.entry),
                                    float(sig.target), float(sig.stoploss)))

    OUT.mkdir(parents=True, exist_ok=True)
    tc = B["tc"]
    total = 0
    for s in specs:
        rows = raw[s.template]
        cols = {k: [] for k in ("i", "side", "sig_close", "sig_tgt", "sig_stp", "entry_ts", "entry_px",
                                "tgt", "stp", "exit_ts", "exit_px", "reason", "bars_held",
                                "p_exit_ts", "p_exit_px", "p_reason", "coarse")}
        for (i, side, close, tgt0, stp0) in rows:
            t_sig = int(tc[i])
            end_i = min(i + MAX_HOLD, n - 1)
            t_end = int(tc[end_i])
            Xs = X
            coarse = 0
            if fallback is not None and t_sig < int(X["ts"][0]):
                Xs, coarse = fallback, 1           # before the 1m history: exits on the TF bars
            k0 = int(np.searchsorted(Xs["ts"], t_sig, side="left"))
            if k0 >= len(Xs["c"]):
                continue
            ke = int(np.searchsorted(Xs["ts"], t_end, side="left")) - 1
            ke = min(max(ke, k0), len(Xs["c"]) - 1)
            entry = float(Xs["o"][k0])
            if close <= 0 or entry <= 0:
                continue
            ratio = entry / close
            tgt, stp = tgt0 * ratio, stp0 * ratio
            k, px, why = _resolve(side, k0, ke, tgt, stp, Xs)
            exit_ts = int(Xs["tc"][k])
            held = int(np.searchsorted(tc, exit_ts, side="left")) - i
            if Xs is X and dataset not in ("C_GC", "E_GCD"):
                wall_end = int(Xs["ts"][k0]) + MAX_HOLD * TF_MIN[tf] * 60
                pk, ppx, pwhy = _resolve_polled(side, k0, tgt, stp, wall_end, Xs)
                p_ts = int(Xs["tc"][pk])
            else:
                pk, ppx, pwhy, p_ts = k, px, why, exit_ts
            for key, val in (("i", i), ("side", side), ("sig_close", close), ("sig_tgt", tgt0),
                             ("sig_stp", stp0), ("entry_ts", int(Xs["ts"][k0])), ("entry_px", entry),
                             ("tgt", tgt), ("stp", stp), ("exit_ts", exit_ts), ("exit_px", px),
                             ("reason", why), ("bars_held", held), ("p_exit_ts", p_ts),
                             ("p_exit_px", ppx), ("p_reason", pwhy), ("coarse", coarse)):
                cols[key].append(val)
        np.savez_compressed(OUT / f"{dataset}__{tf}__{s.template}.npz",
                            **{k: np.asarray(v) for k, v in cols.items()})
        total += len(cols["i"])
    return dataset, tf, len(specs), total, round(time.time() - t0, 1)


def jobs() -> list[tuple]:
    from app.services.commodity_patterns import COMMODITY_CATALOG

    out = []
    for ds, cfg in DATASETS.items():
        for tf in cfg["tfs"]:
            if not (BARS / f"{ds}__{tf}.npz").exists():
                continue
            temps = [s.template for s in COMMODITY_CATALOG if s.timeframe == tf]
            done = [t for t in temps if (OUT / f"{ds}__{tf}__{t}.npz").exists()]
            temps = [t for t in temps if t not in done]
            n = len(np.load(BARS / f"{ds}__{tf}.npz")["c"])
            # chunk so no single job dominates: ~3M bar x template evaluations (~10 min) each
            per = max(1, min(46, 3_000_000 // max(n, 1)))
            for j in range(0, len(temps), per):
                out.append((ds, tf, tuple(temps[j:j + per]), n * len(temps[j:j + per])))
    out.sort(key=lambda x: -x[3])
    return [(a, b, c) for a, b, c, _ in out]


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "build":
        build()
        return
    from multiprocessing import Pool

    nproc = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    js = jobs()
    print(f"{len(js)} jobs on {nproc} processes", flush=True)
    t0 = time.time()
    with Pool(nproc, maxtasksperchild=4) as pool:
        for k, r in enumerate(pool.imap_unordered(run_job, js), 1):
            print(f"[{k}/{len(js)} {time.time() - t0:7.0f}s] {r}", flush=True)
    print("done", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    main()
