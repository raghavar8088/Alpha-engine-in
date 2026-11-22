"""Sector strength and the market's condition at a checkpoint.

A sector is read four ways at bar k, so a move carried by one heavyweight shows:
  rel       the sector's move since 09:15 minus NIFTY's (its NSE sectoral index when there is one, otherwise the
            turnover-weighted move of its members in the universe)
  up_open   share of its members trading above their own 09:15 open
  adv       share above the previous close (advances vs declines)
  above_vwap  share above their session VWAP
  rvol      median same-time relative volume
  contributors  each member's turnover weight x move; `top_share` = largest |contribution| / sum of |contributions|
A sector whose index moves one way while most of its members move the other is NARROW; that is what removes a
sector-confirmed setup (owner's example: the bank index up on one heavyweight while most banks weaken).

Thresholds are fixed in advance (pis/prereg.json) and are not tuned on results.
"""
from __future__ import annotations

import json
import os
from statistics import median, pstdev

BENCH = "NIFTY"
_MAP = None
STRONG = {"rank_max": 2, "up_open": 0.60, "above_vwap": 0.60, "coverage": 0.60, "min_members": 3}
NARROW_TOP_SHARE = 0.50


def sector_map() -> dict:
    global _MAP
    if _MAP is None:
        p = os.path.join(os.path.dirname(__file__), "data", "sector_map.json")
        with open(p, encoding="utf-8") as f:
            _MAP = json.load(f)["symbols"]
    return _MAP


def sector_of(sym: str) -> tuple[str, str | None]:
    m = sector_map().get(sym)
    if not m:
        return "Other", None
    return m["sector"], m.get("index")


def _z(vals: dict) -> dict:
    xs = [v for v in vals.values() if v is not None]
    if len(xs) < 2:
        return {k: 0.0 for k in vals}
    mu, sd = sum(xs) / len(xs), pstdev(xs)
    return {k: ((v - mu) / sd if sd > 0 and v is not None else 0.0) for k, v in vals.items()}


def market_condition(state, k: int, members: list, ctxs: dict, index_prev: dict) -> dict:
    """bull_trend / bear_trend / range / mixed / insufficient, with the numbers it was decided on."""
    have = [s for s in members if state.complete(s, k)]
    cov = len(have) / len(members) if members else 0.0
    n_open = state.ret_open(BENCH, k)
    pc = index_prev.get(BENCH)
    n_pc = state.ret_pc(BENCH, k, pc) if pc else None
    up = [s for s in have if (state.ret_open(s, k) or 0) > 0]
    adv = [s for s in have if (state.ret_pc(s, k, ctxs[s].prev_close) or 0) > 0]
    abv = [s for s in have if (state.vwap(s, k) or 0) and state.close(s, k) > state.vwap(s, k)]
    up_open = len(up) / len(have) if have else None
    above = len(abv) / len(have) if have else None
    out = {"k": k, "coverage": round(cov, 3), "nifty_ret_open": n_open, "nifty_ret_pc": n_pc,
           "up_open": up_open, "adv": len(adv), "dec": len(have) - len(adv),
           "above_vwap": above, "members": len(members), "with_data": len(have)}
    if cov < 0.80 or n_open is None:
        out["condition"] = "insufficient"
        out["why"] = ("NIFTY bars missing" if n_open is None else f"only {cov:.0%} of the universe has every bar")
    elif n_open >= 0.20 and up_open >= 0.60 and above >= 0.60:
        out["condition"] = "bull_trend"
        out["why"] = "NIFTY up 0.20%+ since the open with 60%+ of stocks above their open and their VWAP"
    elif n_open <= -0.20 and up_open <= 0.40 and above <= 0.40:
        out["condition"] = "bear_trend"
        out["why"] = "NIFTY down 0.20%+ since the open with 60%+ of stocks below their open and their VWAP"
    elif abs(n_open) <= 0.10 and 0.40 <= up_open <= 0.60:
        out["condition"] = "range"
        out["why"] = "NIFTY within 0.10% of its open and participation split 40-60%"
    else:
        out["condition"] = "mixed"
        out["why"] = "neither a broad trend nor a balanced range"
    return out


def sector_table(state, k: int, members: list, ctxs: dict, index_prev: dict) -> list[dict]:
    """One row per sector with 3+ universe members, ranked by strength (strongest first)."""
    n_open = state.ret_open(BENCH, k)
    by: dict[str, list] = {}
    for s in members:
        by.setdefault(ctxs[s].sector, []).append(s)
    rows = []
    for sec, names in by.items():
        have = [s for s in names if state.complete(s, k)]
        idx = ctxs[names[0]].index
        idx_ret = state.ret_open(idx, k) if idx else None
        w = {s: ctxs[s].tv_cr for s in have}
        wt = sum(w.values()) or 1.0
        r_open = {s: state.ret_open(s, k) for s in have}
        tw = sum(w[s] / wt * r_open[s] for s in have) if have else None
        contrib = sorted(((s, w[s] / wt * r_open[s]) for s in have), key=lambda x: -abs(x[1]))
        tot = sum(abs(c) for _, c in contrib) or 1.0
        base = idx_ret if idx_ret is not None else tw
        rel = base - n_open if base is not None and n_open is not None else None
        up = sum(1 for s in have if r_open[s] > 0)
        adv = sum(1 for s in have if (state.ret_pc(s, k, ctxs[s].prev_close) or 0) > 0)
        abv = sum(1 for s in have if state.close(s, k) > (state.vwap(s, k) or 1e18))
        rv = [state.rvol(s, k, ctxs[s].cum_base) for s in have]
        rv = [x for x in rv if x is not None]
        up_share = up / len(have) if have else None
        narrow = None
        if rel is not None and up_share is not None:
            narrow = (rel > 0 and up_share < 0.5) or (rel < 0 and up_share > 0.5)
        rows.append({
            "sector": sec, "index": idx, "index_ret_open": idx_ret, "tw_ret_open": tw, "ret_used": base,
            "ret_source": "index" if idx_ret is not None else "members", "rel": rel,
            "members": len(names), "with_data": len(have), "coverage": len(have) / len(names),
            "up_open": up_share, "adv": adv, "dec": len(have) - adv,
            "above_vwap": abv / len(have) if have else None, "rvol_med": median(rv) if rv else None,
            "top": [{"symbol": s, "contribution": c, "ret_open": r_open[s], "weight": w[s] / wt} for s, c in contrib[:3]],
            "top_share": abs(contrib[0][1]) / tot if contrib else None,
            "narrow": narrow,
            "heavyweight": bool(contrib) and abs(contrib[0][1]) / tot > NARROW_TOP_SHARE and len(have) >= 3,
        })
    ok = [r for r in rows if r["with_data"] >= STRONG["min_members"] and r["rel"] is not None]
    ok_names = {r["sector"] for r in ok}
    zr = _z({r["sector"]: r["rel"] for r in ok})
    zu = _z({r["sector"]: r["up_open"] for r in ok})
    za = _z({r["sector"]: r["above_vwap"] for r in ok})
    for r in rows:
        r["score"] = ((zr.get(r["sector"], 0) + zu.get(r["sector"], 0) + za.get(r["sector"], 0))
                      if r["sector"] in ok_names else None)
    ranked = sorted(ok, key=lambda r: (-r["score"], r["sector"]))
    n = len(ranked)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
        r["strong"] = (i <= STRONG["rank_max"] and r["rel"] > 0 and r["up_open"] >= STRONG["up_open"]
                       and r["above_vwap"] >= STRONG["above_vwap"] and not r["narrow"]
                       and r["coverage"] >= STRONG["coverage"])
        r["weak"] = (i > n - STRONG["rank_max"] and r["rel"] < 0 and r["up_open"] <= 1 - STRONG["up_open"]
                     and r["above_vwap"] <= 1 - STRONG["above_vwap"] and not r["narrow"]
                     and r["coverage"] >= STRONG["coverage"])
        r["why"] = _why(r)
    rest = [r for r in rows if r["sector"] not in ok_names]
    for r in rest:
        r.update(rank=None, strong=False, weak=False,
                 why=f"only {r['with_data']} members with every bar (needs {STRONG['min_members']})")
    return ranked + sorted(rest, key=lambda r: r["sector"])


def _why(r: dict) -> str:
    bits = [f"{r['rel']:+.2f}% vs NIFTY ({'its index' if r['ret_source'] == 'index' else 'its members'})",
            f"{r['up_open']:.0%} above their open", f"{r['above_vwap']:.0%} above VWAP"]
    if r["narrow"]:
        bits.append("NARROW: most members move against the sector's headline move")
    if r["heavyweight"]:
        t = r["top"][0]
        bits.append(f"{t['symbol']} carries {r['top_share']:.0%} of the move")
    return "; ".join(bits)


def stock_vs_sector(state, k: int, sym: str, members_by_sector: dict) -> float | None:
    """The stock's move since 09:15 minus the median move of the OTHER members of its sector."""
    r = state.ret_open(sym, k)
    if r is None:
        return None
    peers = [state.ret_open(p, k) for p in members_by_sector if p != sym]
    peers = [x for x in peers if x is not None]
    return r - median(peers) if peers else None
