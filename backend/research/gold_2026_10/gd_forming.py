"""Defect D1 sized: the desk evaluates the bar that is still FORMING.

    python backend/research/gold_2026_10/gd_forming.py

`gold_desk.scan_cycle` calls `load_bars` without `closed_only`, so `bars[-1]` — the bar every
pattern reads as "the latest" — is the candle still being built, and the desk takes the FIRST
scan on which a pattern fires on it ("one decision per strategy per bar"). This replays that
behaviour exactly on Delta XAUTUSD (2026-04..10) for 12 templates on 15m / 1h / 4h / 1d:

  every 180 s: the forming bar = the minutes of the current bucket completed so far; the
  window = the 249 closed bars before it + the forming bar; first signal per (template, bar)
  is taken at the next minute's open, levels scaled to that fill, exits walked honestly.

and compares it with the closed-bar signals of the same templates (gd_replay.py output):
how many of the desk's trades a closed-bar backtest would ever have produced, how far into
the bar the desk decided, and what each set earned before costs.
"""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime, timezone
from multiprocessing import Pool

import numpy as np

import gd_replay as R

TEMPLATES = ("donchian_fast", "keltner_break", "bollinger_pctb", "prior_session_break", "round_number_break",
             "ema_pullback", "atr_thrust", "engulfing", "marubozu", "inside_bar", "hammer_star", "double_top_bottom")
TFS = ("15m", "1h", "4h", "1d")
DS = "A_XAUT"
SCAN_S = 180


def run_tf(tf: str) -> dict:
    from app.services.commodity_patterns import COMMODITY_CATALOG, evaluate

    specs = [s for s in COMMODITY_CATALOG if s.timeframe == tf and s.template in TEMPLATES]
    B = R._load(f"{DS}__{tf}")
    X = R._load(f"{DS}__exit")
    X["full"] = np.ones(len(X["c"]), dtype=bool)
    X["full"][-1] = False
    n = len(B["c"])
    closed = [R.Bar(datetime.fromtimestamp(int(B["ts"][i]), timezone.utc), float(B["o"][i]), float(B["h"][i]),
                    float(B["l"][i]), float(B["c"][i]), float(B["v"][i])) for i in range(n)]
    start = 64                                   # the desk needs >= 65 bars incl. the forming one
    t_first = int(B["ts"][start]) // SCAN_S * SCAN_S + SCAN_S
    t_last = int(B["tc"][-1])
    decided: set = set()
    out = []
    f = start
    for t in range(t_first, t_last, SCAN_S):
        while f < n and int(B["tc"][f]) <= t:
            f += 1
        if f >= n:
            break
        s0 = int(B["ts"][f])
        k_a = int(np.searchsorted(X["ts"], s0, side="left"))
        k_b = int(np.searchsorted(X["ts"], t - 60, side="right"))      # minutes completed by t
        if k_b <= k_a:
            continue
        part = R.Bar(datetime.fromtimestamp(s0, timezone.utc), float(X["o"][k_a]), float(X["h"][k_a:k_b].max()),
                     float(X["l"][k_a:k_b].min()), float(X["c"][k_b - 1]), float(X["v"][k_a:k_b].sum()))
        window = closed[max(0, f - R.W + 1):f] + [part]
        for s in specs:
            key = (s.template, f)
            if key in decided or len(window) < s.min_bars + 5:
                continue
            sig = evaluate(s, window)
            if sig is None:
                continue
            decided.add(key)
            k0 = int(np.searchsorted(X["ts"], t, side="left"))
            if k0 >= len(X["c"]):
                continue
            entry = float(X["o"][k0])
            ratio = entry / float(sig.entry)
            tgt, stp = float(sig.target) * ratio, float(sig.stoploss) * ratio
            side = 1 if sig.side == "BUY" else -1
            end_i = min(f + R.MAX_HOLD, n - 1)
            ke = min(int(np.searchsorted(X["ts"], int(B["tc"][end_i]), side="left")) - 1, len(X["c"]) - 1)
            k, px, why = R._resolve(side, k0, max(ke, k0), tgt, stp, X)
            if why == 3:
                continue
            out.append((s.template, f, side, (t - s0) / (int(B["tc"][f]) - s0), side * (px - entry) / entry * 1e4))
    # the closed-bar signals of the same templates, from the replay
    closed_sig = {}
    for tmpl in TEMPLATES:
        p = R.OUT / f"{DS}__{tf}__{tmpl}.npz"
        if p.exists():
            z = np.load(p)
            for i, side, ex, en, why in zip(z["i"], z["side"], z["exit_px"], z["entry_px"], z["reason"]):
                if why != 3:
                    closed_sig[(tmpl, int(i))] = (int(side), int(side) * (ex - en) / en * 1e4)
    forming = {(a, b): (c, d, e) for a, b, c, d, e in out}
    same = [k for k, v in forming.items() if k in closed_sig and closed_sig[k][0] == v[0]]
    flip = [k for k, v in forming.items() if k in closed_sig and closed_sig[k][0] != v[0]]
    only_f = [k for k in forming if k not in closed_sig]
    only_c = [k for k in closed_sig if k not in forming]
    g_f = np.array([v[2] for v in forming.values()])
    g_c = np.array([v[1] for v in closed_sig.values()])
    g_only = np.array([forming[k][2] for k in only_f]) if only_f else np.array([])
    frac = np.array([v[1] for v in forming.values()])
    return {"tf": tf, "desk_trades": len(forming), "closed_trades": len(closed_sig), "same": len(same),
            "flipped": len(flip), "desk_only": len(only_f), "closed_only": len(only_c),
            "desk_gross": float(g_f.mean()) if len(g_f) else float("nan"),
            "closed_gross": float(g_c.mean()) if len(g_c) else float("nan"),
            "desk_only_gross": float(g_only.mean()) if len(g_only) else float("nan"),
            "median_bar_elapsed": float(np.median(frac)) if len(frac) else float("nan")}


def main() -> None:
    nproc = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    with Pool(nproc) as pool:
        for r in pool.imap_unordered(run_tf, TFS):
            print(f"{r['tf']:4}: desk-as-built trades {r['desk_trades']:6,} vs closed-bar {r['closed_trades']:6,} | "
                  f"same bar+side {r['same']:5,} ({r['same'] / max(r['desk_trades'], 1):.0%} of the desk's) | "
                  f"side flipped {r['flipped']:4,} | desk-only {r['desk_only']:6,} ({r['desk_only'] / max(r['desk_trades'], 1):.0%}) | "
                  f"closed-only {r['closed_only']:6,} | decided at {r['median_bar_elapsed']:.0%} of the bar (median) | "
                  f"gross bp: desk {r['desk_gross']:+.2f}, closed {r['closed_gross']:+.2f}, desk-only {r['desk_only_gross']:+.2f}",
                  flush=True)


if __name__ == "__main__":
    main()
