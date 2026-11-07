"""The six VWAP strategies on the 5-minute panel, as vwap_engine.run + vwap_upgrades.prepare/run_version do it, for
the sessions not yet final. The rules are vwap_rules.py (verbatim). Universe: the box's intraday store (about 258 liquid
stocks) rather than the study's 500 Yahoo symbols; the top-200 liquidity filter is the same."""

from __future__ import annotations

import numpy as np

import vwap_rules as R
from vwap_rules import BARS5, P, find_a, find_b, find_u1, find_u3, find_u4, indicators, manage, manage_trail, ok, rvol

SETUPS = ("A", "B", "U1", "U2", "U3", "U4")
ACCOUNT = {"A": "VWAP-A", "B": "VWAP-B", "U1": "VWAP-U1", "U2": "VWAP-U2", "U3": "VWAP-U3", "U4": "VWAP-U4"}
VOL_CAP = 0.05


def tier_slippage(rank) -> float:
    return 0.0003 if rank <= 50 else 0.0005 if rank <= 200 else 0.0008


def run(panel, replay_days: set[str]) -> dict[str, list[dict]]:
    """{setup: [document, ...]}, before the 4-position book rule."""
    p0, p_up = P(), P(be=False)
    n_days, n_stocks = len(panel.days), len(panel.names)
    replay_rows = [r for r, d in enumerate(panel.days) if d in replay_days and r >= R.WARMUP]
    mats, inds, rvols = {}, {}, {}
    bsum, bcnt = np.zeros((n_days, R.NB5)), np.zeros((n_days, R.NB5))
    for i in range(n_stocks):
        m = panel.matrix(i)
        c = m["c"]
        good = np.isfinite(c).any(1)
        if not good.any():
            continue
        vw, at = indicators(m, good, p0)
        mats[i], inds[i], rvols[i] = (m, good), (vw, at), rvol(m, good)
        for r in replay_rows:
            rk = panel.rank_on(r, i)
            if good[r] and rk is not None and rk <= R.TOPN:
                valid = ~np.isnan(c[r]) & ~np.isnan(vw[r])
                bsum[r] += np.where(valid, c[r] > vw[r], 0)
                bcnt[r] += valid
    with np.errstate(all="ignore"):
        breadth = np.where(bcnt > 0, bsum / bcnt, np.nan)

    out: dict[str, list[dict]] = {k: [] for k in SETUPS}
    for r in replay_rows:
        date = panel.days[r]
        is_live = date == panel.live_day
        base = panel.day_keys[r] * 86400 - 19800 + 9 * 3600 + 15 * 60
        for i, (m, good) in mats.items():
            if not good[r]:
                continue
            rk = panel.rank_on(r, i)
            if rk is None or rk > R.TOPN:
                continue
            o, h, l, c, v = (m[k][r] for k in "ohlcv")
            vw, at = inds[i][0][r], inds[i][1][r]
            rv = rvols[i][r]
            br = breadth[r]
            sym = panel.names[i]

            def add(setup, sig, how):
                s, si, stop = sig
                e = si + 1
                entry = o[e]
                risk_e = s * (entry - stop)
                risk_sig = s * (c[si] - stop)
                if how == "fixed":
                    tgt = entry + s * 2.0 * (risk_e if risk_e > 0 else risk_sig)
                    xi, xp, why = manage(s, e, stop, tgt, False, o, h, l, c, vw, p0 if setup == "A" else p_up)
                elif how == "vwap":
                    tgt = float(vw[si])
                    xi, xp, why = manage(s, e, stop, None, True, o, h, l, c, vw, p0 if setup == "B" else p_up)
                else:
                    tgt = None
                    xi, xp, why = manage_trail(s, e, stop, o, h, l, c, vw, at, p_up)
                unit = risk_e if risk_e > 0 else risk_sig
                still_open = is_live and why == "time" and xi < p0.exit_idx
                entry_t, exit_t = int(base + 300 * e), int(base + 300 * xi)
                last = next((float(c[j]) for j in range(R.NB5 - 1, -1, -1) if ok(c[j])), float(entry))
                out[setup].append({
                    "_id": f"{ACCOUNT[setup]}|VWAP|{sym}|{entry_t}|{s}", "acct": ACCOUNT[setup], "book": f"{ACCOUNT[setup]}|VWAP",
                    "mkt": "VWAP", "sym": sym, "variant": setup, "setup": setup, "side": int(s), "date": date, "entry_t": entry_t,
                    "exit_t": None if still_open else exit_t, "exit_date": date, "entry": float(entry), "stop": float(stop),
                    "target": None if tgt is None else float(tgt), "exit": float(xp), "reason": "open" if still_open else why,
                    "unit": float(unit), "open": bool(still_open), "last": last, "liq_rank": rk,
                    "rank": -float(rv[si]) if setup == "U4" else rk,
                    "slip": tier_slippage(rk), "vol_cap": float(VOL_CAP * v[si]), "vwap_costs": True,
                })

            args = (o, h, l, c, v, vw, at, p0)
            sig = find_a(*args)
            if sig:
                add("A", sig, "fixed")
            sig = find_b(*args)
            if sig:
                add("B", sig, "vwap")
            sig = find_u1(o, h, l, c, v, vw, at, rv, br, p_up)
            if sig:
                add("U1", sig, "fixed")
                add("U2", sig, "trail")
            sig = find_u3(o, h, l, c, v, vw, at, br, p_up)
            if sig:
                add("U3", sig, "vwap")
            sig = find_u4(o, h, l, c, v, vw, at, rv, br, p_up)
            if sig:
                add("U4", sig, "trail")
    return out


__all__ = ["run", "SETUPS", "ACCOUNT", "BARS5"]
