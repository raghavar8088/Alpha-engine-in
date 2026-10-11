"""The Gold Desk as a SYSTEM: each book replayed with the desk's own rules.

    python backend/research/gold_2026_10/gd_book.py

The per-strategy replay (gd_analyse.py) asks whether any pattern has an edge. This asks what
the desk itself would have done with all of them at once, under its own rules
(`gold_desk.scan_cycle` / `_sizing` / `_open`):

  * ONE shared book per venue, a fixed number of slots, first come first served in the desk's
    scan order (symbol, then timeframe 1m..1d, then catalogue order);
  * one open position per (template, timeframe, symbol);
  * sizing — Delta: an equal slot share of the book at 1x, whole 0.001 oz contracts;
    MCX: one GOLDM lot (GOLD's 1 kg lot is always refused), margin at the measured 9.2%;
  * the daily loss breaker (3% of capital; today's realised + the open P&L of positions opened
    today, as `today_pnl` computes it) and the book floor (no entries below 50% of capital).

Fills and exits are the honest replay's (gd_replay.py); costs are applied both as the desk
charges them (5 bp a side) and as measured. Signals reach the book when their bar closes.

Books replayed:
  DELTA  $10,000, 6 slots, XAUTUSD + PAXGUSD — on Delta's own 2026 data (A_XAUT + A_PAXG)
  MCX    Rs 30,00,000, 4 slots, GOLDM — on the MCX store (D_GOLDM), the window where every
         timeframe has data (2026-08-11..10-09); and 1h/4h/1d only on COMEX hours data
         (C_GC, 2024-05..2026-10) mapped to GOLDM notional.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

import gd_analyse as A

HERE = Path(__file__).resolve().parent
BARS = HERE / "data" / "replay" / "bars"
TF_ORDER = A.TF_ORDER


def catalogue_order() -> dict:
    from app.services.commodity_patterns import COMMODITY_CATALOG
    return {(s.timeframe, s.template): k for k, s in enumerate(COMMODITY_CATALOG)}


def all_signals(ds: str, symbol_rank: int) -> pd.DataFrame:
    """Every signal of every strategy with its honest outcome (taken or not)."""
    rows = []
    for (tf, tmpl), s in A.load_signals(ds).items():
        if len(s["i"]) == 0:
            continue
        tc = np.load(BARS / f"{ds}__{tf}.npz")["tc"]
        rows.append(pd.DataFrame({
            "ds": ds, "sym_rank": symbol_rank, "tf": tf, "template": tmpl,
            "t_sig": tc[s["i"]], "side": s["side"], "entry_ts": s["entry_ts"], "entry": s["entry_px"],
            "exit_ts": s["exit_ts"], "exit": s["exit_px"], "reason": s["reason"]}))
    df = pd.concat(rows, ignore_index=True)
    return df[df.reason != 3]


def run_book(sig: pd.DataFrame, *, capital: float, slots: int, venue: str, costs: str,
             spread_bp: dict, start=None, end=None, funding_bp_day: float = 1.5,
             mcx_notional_of=None) -> dict:
    order = catalogue_order()
    sig = sig.copy()
    sig["tf_rank"] = sig.tf.map({t: k for k, t in enumerate(TF_ORDER)})
    sig["cat"] = [order.get((a, b), 9999) for a, b in zip(sig.tf, sig.template)]
    if start is not None:
        sig = sig[sig.t_sig >= start]
    if end is not None:
        sig = sig[sig.t_sig < end]
    sig = sig.sort_values(["t_sig", "sym_rank", "tf_rank", "cat"]).reset_index(drop=True)

    realized = 0.0
    open_pos: list[dict] = []
    trades = []
    held_keys: set = set()
    day_key = None
    day_realized = 0.0
    breaker_days: set = set()
    floor_hit = False
    refused = {"slots": 0, "dup": 0, "cash": 0, "breaker": 0, "floor": 0}
    eq_curve = []

    def close_until(t):
        nonlocal realized, day_realized
        keep = []
        for p in open_pos:
            if p["exit_ts"] <= t:
                realized += p["pnl"]
                if day_of(p["exit_ts"]) == day_key:
                    day_realized += p["pnl"]
                held_keys.discard(p["key"])
                trades.append(p)
            else:
                keep.append(p)
        open_pos[:] = keep

    def day_of(ts):
        if venue == "mcx":
            return int((ts + 19800) // 86400)
        return int(ts // 86400)

    for r in sig.itertuples(index=False):
        t = int(r.t_sig)
        d = day_of(t)
        if d != day_key:
            day_key, day_realized = d, 0.0
        close_until(t)
        equity = capital + realized                     # open P&L not marked between events
        if equity <= capital * 0.5:
            floor_hit = True
            refused["floor"] += 1
            continue
        if day_realized <= -0.03 * capital:
            breaker_days.add(d)
            refused["breaker"] += 1
            continue
        if len(open_pos) >= slots:
            refused["slots"] += 1
            continue
        key = (r.ds, r.tf, r.template)
        if key in held_keys:
            refused["dup"] += 1
            continue
        side = float(r.side)
        if venue == "delta":
            deployed = sum(p["committed"] for p in open_pos)
            free = capital + realized - deployed
            budget = min(capital / slots, free)
            unit = r.entry * 0.001
            units = int(budget // unit) if unit > 0 else 0
            if units < 1:
                refused["cash"] += 1
                continue
            notional = units * unit
            committed = notional
        else:
            notional = mcx_notional_of(r.entry)
            margin = 0.092 * notional
            deployed = sum(p["committed"] for p in open_pos)
            free = capital + realized - deployed
            if free < margin or notional > capital:
                refused["cash"] += 1
                continue
            committed = margin
        gross_bp = side * (r.exit - r.entry) / r.entry * 1e4
        hold_d = (r.exit_ts - r.entry_ts) / 86400.0
        sym = r.ds
        if venue == "delta":
            fee = A.DELTA_FEE_RT
            if costs == "desk":
                cost_bp = A.DESK_SLIP_RT + fee
            else:
                cost_bp = fee + spread_bp[sym] + side * funding_bp_day * hold_d
        else:
            fee = A.MCX_FEE_RT
            cost_bp = (A.DESK_SLIP_RT + fee) if costs == "desk" else (fee + spread_bp[sym])
        pnl = (gross_bp - cost_bp) / 1e4 * notional
        p = {"key": key, "exit_ts": int(r.exit_ts), "pnl": pnl, "committed": committed, "tf": r.tf, "side": side,
             "template": r.template, "ds": r.ds, "gross_bp": gross_bp, "net_bp": gross_bp - cost_bp,
             "notional": notional, "day": d, "entry_ts": int(r.entry_ts)}
        open_pos.append(p)
        held_keys.add(key)
        eq_curve.append((t, capital + realized))
    close_until(2**62)
    tr = pd.DataFrame(trades)
    # daily book P&L, realised on the day each position closed (calendar days, zeros included)
    daily = pd.Series(dtype=float)
    if len(tr):
        d = pd.to_datetime(tr.exit_ts, unit="s", utc=True).dt.floor("D")
        daily = tr.groupby(d).pnl.sum()
        daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"), fill_value=0.0)
    eq = capital + daily.cumsum()
    peak = eq.cummax()
    dd = float(((peak - eq) / peak).max()) if len(eq) else 0.0
    under = (eq < peak).astype(int)
    longest_under = int(under.groupby((under == 0).cumsum()).sum().max()) if len(under) else 0
    r = daily / capital
    sharpe = float(r.mean() / r.std() * math.sqrt(365)) if len(r) > 2 and r.std() > 0 else float("nan")
    down = r[r < 0]
    sortino = float(r.mean() / math.sqrt((down ** 2).mean()) * math.sqrt(365)) if len(down) > 2 else float("nan")
    return {"trades": tr, "final": capital + realized, "ret_pct": realized / capital * 100,
            "max_dd_pct": dd * 100, "refused": refused, "breaker_days": len(breaker_days),
            "floor_hit": floor_hit, "sharpe": sharpe, "sortino": sortino,
            "longest_underwater_days": longest_under, "days": len(daily)}


def summarise(label: str, res: dict, ccy: str, buy_hold_pct: float | None = None) -> None:
    tr = res["trades"]
    print(f"\n{label}: {len(tr):,} trades, return {res['ret_pct']:+.2f}% (final {ccy}{res['final']:,.0f}), "
          f"max drawdown {res['max_dd_pct']:.1f}%, Sharpe {res['sharpe']:+.2f}, Sortino {res['sortino']:+.2f} "
          f"(daily, {res['days']} days), longest under water {res['longest_underwater_days']} days, "
          f"breaker days {res['breaker_days']}, floor hit {res['floor_hit']}"
          + (f" | gold itself {buy_hold_pct:+.1f}% over the window" if buy_hold_pct is not None else ""))
    if len(tr):
        print(f"   refused entries: {res['refused']}")
        by = tr.groupby("tf").agg(n=("pnl", "size"), pnl=("pnl", "sum"), net_bp=("net_bp", "mean"), gross_bp=("gross_bp", "mean"))
        by = by.reindex([t for t in TF_ORDER if t in by.index])
        print("   by timeframe: " + " | ".join(f"{tf} n={int(r.n)} {ccy}{r.pnl:,.0f} ({r.gross_bp:+.1f}g/{r.net_bp:+.1f}n bp)" for tf, r in by.iterrows()))
        print(f"   share of fills on 1m+5m: {tr.tf.isin(['1m', '5m']).mean():.0%}; mean gross {tr.gross_bp.mean():+.2f} bp, net {tr.net_bp.mean():+.2f} bp")


def buy_hold(ds: str, start: int, end: int) -> float:
    z = np.load(BARS / f"{ds}__exit.npz")
    m = (z["ts"] >= start) & (z["ts"] < end)
    c = z["c"][m]
    return (c[-1] / c[0] - 1) * 100 if len(c) else float("nan")


def main() -> None:
    # ── Delta book on Delta's own data ───────────────────────────────────────
    sx = all_signals("A_XAUT", 0)
    sp = all_signals("A_PAXG", 1)
    sig = pd.concat([sx, sp], ignore_index=True)
    start = int(sx.t_sig.min())                         # both tokens live (XAUT launched later)
    end = int(min(sx.t_sig.max(), sp.t_sig.max()))
    spread = {"A_XAUT": A.SPREAD_RT["A_XAUT"], "A_PAXG": A.SPREAD_RT["A_PAXG"]}
    bh = buy_hold("A_XAUT", start, end)
    for costs in ("desk", "actual"):
        res = run_book(sig, capital=10_000, slots=6, venue="delta", costs=costs, spread_bp=spread,
                       start=start, end=end)
        summarise(f"DELTA book ($10k, 6 slots) {pd.Timestamp(start, unit='s'):%Y-%m-%d}..{pd.Timestamp(end, unit='s'):%Y-%m-%d}, costs={costs}",
                  res, "$", bh)

    # ── MCX book on the MCX store ────────────────────────────────────────────
    sd = all_signals("D_GOLDM", 0)
    x1 = np.load(BARS / "D_GOLDM__exit.npz")
    start, end = int(x1["ts"][0]), int(sd.t_sig.max())
    bh = buy_hold("D_GOLDM", start, end)
    for costs in ("desk", "actual"):
        res = run_book(sd, capital=3_000_000, slots=4, venue="mcx", costs=costs,
                       spread_bp={"D_GOLDM": A.SPREAD_RT["D_GOLDM"]}, start=start, end=end,
                       mcx_notional_of=lambda px: px * 10.0)
        summarise(f"MCX book (Rs 30 L, 4 slots, GOLDM) {pd.Timestamp(start, unit='s'):%Y-%m-%d}..{pd.Timestamp(end, unit='s'):%Y-%m-%d}, costs={costs}",
                  res, "Rs ", bh)

    # ── MCX book, 1h/4h/1d, on COMEX hours data, mapped to one GOLDM lot ─────
    sc = all_signals("C_GC", 0)
    start, end = int(sc.t_sig.min()), int(sc.t_sig.max())
    bh = buy_hold("C_GC", start, end)
    for costs in ("desk", "actual"):
        res = run_book(sc, capital=3_000_000, slots=4, venue="mcx", costs=costs,
                       spread_bp={"C_GC": A.SPREAD_RT["C_GC"]}, start=start, end=end,
                       mcx_notional_of=lambda px: 1_500_000.0)
        summarise(f"MCX book, 1h/4h/1d only, COMEX-hours proxy {pd.Timestamp(start, unit='s'):%Y-%m-%d}..{pd.Timestamp(end, unit='s'):%Y-%m-%d}, costs={costs}",
                  res, "Rs ", bh)


if __name__ == "__main__":
    main()
