"""Sector rotation across day / week / month / 6 months, and what is driving it.

TWO INDEPENDENT READS, SHOWN SIDE BY SIDE.

  1. NSE's own sectoral indices (`/api/allIndices`) — official, cap-weighted, and what the
     market actually quotes. Day change comes straight off the endpoint.
  2. Our own constituent roll-up — the mean return of a sector's stocks from
     `stock_universe.sector` and the stored daily bars, on every horizon, with no NSE
     dependency at all.

They disagree, and the disagreement is the useful part. A cap-weighted index can be +2%
because two heavyweights moved while most of the sector fell; the equal-weighted roll-up
and the breadth count expose exactly that. Neither number is "right" — showing one alone
would be.

THEY ARE ALSO NOT THE SAME TAXONOMY. `stock_universe.sector` is the "Industry" column from
the niftyindices constituent CSVs. It does not map one-to-one onto NSE's sectoral indices,
so the two reads are labelled separately and never merged into a single "sector return".
Silently equating them would produce a number that is not measuring anything.

WHAT IS DRIVING THE TREND is decomposed rather than described: each stock's contribution
(return x weight), the breadth (how many names are actually participating), turnover
against the sector's own habit, and how persistently the sector has beaten the index. All
arithmetic, all checkable.
"""

from __future__ import annotations

import logging

from app.services.screener import horizons as H

logger = logging.getLogger("screener.sectors")

# A sector needs a few names before its mean means anything. Below this the roll-up is
# still computed but flagged `thin`, so a two-stock "sector" cannot top the board on one
# stock's move.
MIN_CONSTITUENTS = 3
BROAD_BREADTH_PCT = 70.0   # share of names up for a move to count as broad-based
NARROW_TOP_SHARE = 60.0    # share of the move from the top 2 names to count as narrow


def roll_up(snapshot: dict, horizon: str) -> dict:
    """Sector board for one horizon, computed from the momentum snapshot.

    Pure and synchronous — it reads the snapshot the momentum module already built, so the
    board, the drill-down and the stock drawer all agree by construction instead of each
    recomputing sector returns slightly differently.
    """
    rows = [r for r in snapshot["rows"] if r["returns"].get(horizon) is not None]
    bench = snapshot["benchmark"]["returns"].get(horizon)

    by_sector: dict[str, list[dict]] = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append(r)

    out = []
    for sector, members in by_sector.items():
        rets = [m["returns"][horizon] for m in members]
        equal_weighted = sum(rets) / len(rets)

        # Turnover-weighted stands in for cap-weighted: we store daily turnover but not
        # market cap or free-float factors, and inventing a weighting we cannot source
        # would make the "cap-weighted" column a fiction. Turnover weighting is a real,
        # stated measure — it answers "where did the money actually go" — and is labelled
        # as such rather than dressed up as the index construction.
        weights = [(m["turnover"] or 0.0) for m in members]
        total_w = sum(weights)
        weighted = (sum(r * w for r, w in zip(rets, weights)) / total_w) if total_w > 0 else None

        up = sum(1 for r in rets if r > 0)
        vol_x = [m["volume_x"] for m in members if m["volume_x"] is not None]

        ranked = sorted(members, key=lambda m: m["returns"][horizon], reverse=True)
        out.append({
            "sector": sector,
            "count": len(members),
            "thin": len(members) < MIN_CONSTITUENTS,
            "return_pct": round(equal_weighted, 2),
            "return_weighted_pct": round(weighted, 2) if weighted is not None else None,
            "breadth_up": up,
            "breadth_pct": round(up / len(members) * 100, 1),
            "rs_index": _r(H.relative_strength(equal_weighted, bench)),
            "volume_x": round(sum(vol_x) / len(vol_x), 2) if vol_x else None,
            "leader": {"symbol": ranked[0]["symbol"], "return_pct": ranked[0]["returns"][horizon]},
            "laggard": {"symbol": ranked[-1]["symbol"], "return_pct": ranked[-1]["returns"][horizon]},
        })

    out.sort(key=lambda s: -s["return_pct"])
    for i, s in enumerate(out, 1):
        s["rank"] = i

    return {
        "horizon": horizon,
        "horizon_label": H.HORIZON_LABELS[horizon],
        "benchmark_pct": bench,
        "count": len(out),
        "sectors": out,
        "basis": "niftyindices Industry label, equal-weighted mean of constituent returns",
    }


def all_horizons(snapshot: dict) -> dict:
    """Every sector on every horizon, plus the rank change that shows rotation.

    Rank change is the point of the whole board: a sector at rank 12 over six months and
    rank 2 today is money moving INTO it, which the four raw return columns do not say on
    their own.
    """
    boards = {h: roll_up(snapshot, h) for h in H.HORIZON_ORDER}

    merged: dict[str, dict] = {}
    for h in H.HORIZON_ORDER:
        for s in boards[h]["sectors"]:
            m = merged.setdefault(s["sector"], {
                "sector": s["sector"], "count": s["count"], "thin": s["thin"],
                "returns": {}, "breadth": {}, "ranks": {},
            })
            m["returns"][h] = s["return_pct"]
            m["breadth"][h] = s["breadth_pct"]
            m["ranks"][h] = s["rank"]
            if h == "1d":
                m["leader"] = s["leader"]
                m["laggard"] = s["laggard"]
                m["volume_x"] = s["volume_x"]
                m["rs_index"] = s["rs_index"]

    rows = list(merged.values())
    for r in rows:
        long_rank = r["ranks"].get("6m")
        short_rank = r["ranks"].get("1w")
        # Positive = climbing the table over the last week relative to its 6-month standing.
        r["rank_change"] = (long_rank - short_rank) if (long_rank and short_rank) else None
        r["rotation"] = _rotation_label(r["rank_change"], r["returns"].get("1w"),
                                        r["returns"].get("6m"))

    rows.sort(key=lambda r: -(r["returns"].get("1m") or -999))
    return {
        "count": len(rows),
        "sectors": rows,
        "benchmark": {h: boards[h]["benchmark_pct"] for h in H.HORIZON_ORDER},
        "horizons": [{"key": h, "label": H.HORIZON_LABELS[h]} for h in H.HORIZON_ORDER],
        "basis": boards["1d"]["basis"],
    }


def _rotation_label(rank_change: int | None, short: float | None, long: float | None) -> str:
    """The RRG quadrant, named in words rather than plotted.

    Leading   strong and still strengthening
    Weakening strong over six months but fading in the last week
    Lagging   weak and still weak
    Improving weak over six months but turning up — where rotation starts
    """
    if short is None or long is None:
        return "unknown"
    strong_long = long > 0
    improving = (rank_change or 0) > 0
    if strong_long and improving:
        return "leading"
    if strong_long and not improving:
        return "weakening"
    if not strong_long and improving:
        return "improving"
    return "lagging"


def drill_down(snapshot: dict, sector: str, horizon: str) -> dict:
    """One sector: its constituents ranked, and the decomposition of its move."""
    board = roll_up(snapshot, horizon)
    row = next((s for s in board["sectors"] if s["sector"] == sector), None)
    if row is None:
        raise KeyError(sector)

    members = [r for r in snapshot["rows"]
               if r["sector"] == sector and r["returns"].get(horizon) is not None]
    rets = [m["returns"][horizon] for m in members]
    weights = [(m["turnover"] or 0.0) for m in members]
    total_w = sum(weights)

    # Contribution: each name's share of the sector's weighted move. Signed, so a stock
    # that dragged the sector down shows as a negative contributor rather than being
    # dropped from the story.
    contributions = []
    for m, w in zip(members, weights):
        share = (w / total_w) if total_w > 0 else (1 / len(members))
        contrib = m["returns"][horizon] * share
        contributions.append({
            "symbol": m["symbol"],
            "name": m.get("name"),
            "return_pct": m["returns"][horizon],
            "weight_pct": round(share * 100, 2),
            "contribution_pp": round(contrib, 3),
            "volume_x": m["volume_x"],
            "ltp": m["ltp"],
        })
    contributions.sort(key=lambda c: -abs(c["contribution_pp"]))

    total_contrib = sum(abs(c["contribution_pp"]) for c in contributions) or 1.0
    top2_share = sum(abs(c["contribution_pp"]) for c in contributions[:2]) / total_contrib * 100

    up = sum(1 for r in rets if r > 0)
    breadth_pct = up / len(members) * 100

    # CONCENTRATION IS TESTED BEFORE BREADTH, and the order matters more than it looks.
    # The two measure different things: breadth counts how many names are up, while
    # contribution measures how much of the MOVE they account for. A sector can be broad by
    # count and narrow by contribution at the same time — four of five IT names green, but
    # two megacaps on huge turnover supplying 99% of the return while the rest drift +0.2%.
    # Checking breadth first reported exactly that case as "the whole sector moving, not a
    # couple of heavyweights", which is the opposite of the truth and the single most
    # misleading sentence this module could print. Concentration wins, because the number
    # the reader carries away — the sector return — is the weighted one those two names own.
    names = ", ".join(c["symbol"] for c in contributions[:2])
    if len(members) < 4:
        shape = "thin"
        shape_text = (f"Only {len(members)} names in this sector — too few to tell a broad "
                      f"move from a concentrated one, so neither is claimed")
    elif top2_share >= NARROW_TOP_SHARE:
        shape = "narrow"
        broad_caveat = (f" — and note {up} of {len(members)} names are green, so this is "
                        f"concentrated by SIZE, not by direction"
                        if breadth_pct >= BROAD_BREADTH_PCT else
                        ", and the average stock in it is not doing this")
        shape_text = (f"{top2_share:.0f}% of the move is {names} — the sector number is "
                      f"carried by two names{broad_caveat}")
    elif breadth_pct >= BROAD_BREADTH_PCT:
        shape = "broad"
        shape_text = (f"{up} of {len(members)} names are up and no name dominates the move "
                      f"(top two are {top2_share:.0f}% of it) — this is the whole sector")
    else:
        shape = "mixed"
        shape_text = (f"{up} of {len(members)} names up, top two are {top2_share:.0f}% of "
                      f"the move — a mixed picture")

    vol_x = [m["volume_x"] for m in members if m["volume_x"] is not None]
    avg_vol_x = sum(vol_x) / len(vol_x) if vol_x else None

    drivers = [shape_text]
    if avg_vol_x is not None and avg_vol_x >= 1.3:
        drivers.append(f"Sector turnover is running {avg_vol_x:.1f}x its 20-day average — "
                       f"real participation behind the move")
    elif avg_vol_x is not None and avg_vol_x < 0.8:
        drivers.append(f"Sector volume is only {avg_vol_x:.1f}x its average — the move is "
                       f"happening on thin participation")
    if row["rs_index"] is not None:
        verb = "outperforming" if row["rs_index"] > 0 else "underperforming"
        drivers.append(f"{verb} NIFTY by {abs(row['rs_index']):.1f} points over this horizon")

    breakouts = [m["symbol"] for m in members if m.get("breakout")]
    if breakouts:
        drivers.append(f"{len(breakouts)} constituent(s) broke a multi-month high: "
                       f"{', '.join(breakouts[:5])}")

    ranked = sorted(members, key=lambda m: m["returns"][horizon], reverse=True)
    return {
        "sector": sector,
        "horizon": horizon,
        "horizon_label": H.HORIZON_LABELS[horizon],
        "summary": row,
        "shape": shape,
        "breadth_pct": round(breadth_pct, 1),
        "top2_share_pct": round(top2_share, 1),
        "drivers": drivers,
        "contributions": contributions[:15],
        "constituents": [{k: v for k, v in m.items() if not k.startswith("_")}
                         | {"return_pct": m["returns"][horizon]} for m in ranked],
        "note": ("Weights are daily TURNOVER share, not market cap — this app does not "
                 "store free-float factors, and a weighting we cannot source would be a "
                 "fiction. It answers 'where did the money go', not 'what does the index do'."),
    }


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None
