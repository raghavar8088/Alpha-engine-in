"""S4 — the opening-range-break family on 5-minute bars. READ ONLY (writes /out only).

The one direction rule that survived the stock-selection research was the two-sided break
of the opening range on the stocks with the highest EXPECTED move: ~+11 bp gross a trade on
15-minute bars, about break-even after costs. 15-minute bars could not say whether the entry
or the stop came first inside the trigger bar; 5-minute bars mostly can. This tests the whole
family at once, and counts EVERY variant as a trial.

Selection, point in time:
  OR30  range 09:15-09:45; stocks ranked at 09:45 by the expected-move model (relative volume,
        ATR, gap, first 30 min, previous range, results day), refitted monthly on days BEFORE
        the month; breaks from 09:45.
  OR15  range 09:15-09:30; ranked at 09:15 by the opening variant (ATR, gap, previous range,
        results day); breaks from 09:30.
  Each day only stocks in THAT morning's top 200 by traded value.
Entries   touch    stop order at the range edge (or the bar's open if it gapped through);
                   a bar breaking both edges = no trade
          close    a 5m close beyond the edge, entered at the next bar's open
          closevol close, with that bar's volume >= 1.5x the range's average 5m bar
          retest   after a touch-break, a limit at the broken edge (no slippage)
          windows  entry bar starting before 11:00 or before 14:30
Stops     opp (other edge), mid (range midpoint), atr (0.5 x 14-day ATR from the fill)
Exits     eod (15:05 bar open for closing-auction stocks, 15:10 otherwise), t2r (2R limit
          target, else eod), trail (break-even at +1R, then 1R below the best high)
Pessimistic fills: a stop reached in the fill bar counts as hit; a bar reaching stop and
target counts as the stop; a bar opening beyond the stop fills at its open.
Costs: Angel intraday rate card at Rs 10 lakh a trade + the live engine's slippage by
liquidity (1-4 bp per side) on every market/stop fill.
Variants: + top-N (5/10/20) x side (both/long/short) x filter (all / VIX high / relative
volume >= 1.5 / no results day).

Periods: DEVELOPMENT up to 2026-03-31 picks; HOLDOUT 2026-04-01 onward is read once. The
holdout overlaps the research's confirm period (from 2026-01-22), where the plain rule was
already seen — so the clean test of anything chosen here is forward paper trading.

RESULT (2026-10-02, results/s4_orb_study_2026-10-02.json; all 5,184 variants in the bar
volume at backtests/s4_orb_study_2026-10-02_all_variants.json):
  - Nothing passes the gate. The development winners (15-minute range, short side) fell
    from +32 bp to +2..8 bp in the holdout; development vs holdout Sharpe across variants
    correlates at -0.07. The best candidate's Deflated Sharpe over 5,184 trials is 0.05.
  - What held in BOTH periods, averaged over whole families: stop-order entries (+3.8 /
    +4.0 bp) beat close-confirmed (-3.3 / -0.9) and volume-confirmed (-13.9 / -16.8) ones;
    a relative-volume >= 1.5 filter (+3.3 / +2.7); two-sided trading (long-only went
    -11 -> +12 bp and short-only +4 -> -21: a one-sided ORB is a bet on the market).
  - "Stop-order break, both sides, top expected-move names with relative volume >= 1.5"
    was positive in both periods at 42-43 of its 54 settings (all 18 with entries until
    14:30, for the 30-minute range). Two settings were pre-registered for forward
    incubation (intraday_v2_registry.PREREGISTERED).
  - A look-ahead found and fixed in this script: the 15-minute range's volume filter first
    used the 09:45 relative volume though its trades start at 09:30; it now reads only the
    09:15 bar's.

RUN (read-only; the bar volume mounted read-only, results to /out):
  docker run --rm -m 1000m --network alpha-engine_default --env-file .env \\
    -e PYTHONPATH=/app/backend -w /app/backend \\
    -v alpha-engine_intraday_data:/data/intraday:ro -v /tmp/s4out:/out \\
    -v $PWD/backend/research/selection_s4_orb_study.py:/tmp/r.py:ro \\
    alpha-engine-backend python /tmp/r.py
"""
import asyncio
import itertools
import json
import math
import sys
import time
from array import array
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

IST = timezone(timedelta(hours=5, minutes=30))
NOTIONAL = 1_000_000.0
HOLDOUT_FROM = date(2026, 4, 1)
MIN_TRAIN_DAYS = 60
OUT = "/out/s4.json"

ORS = ("OR30", "OR15")
ENTRIES = ("touch", "close", "closevol", "retest")
WINDOWS = (("w11", 660), ("w1430", 870))
STOPS = ("opp", "mid", "atr")
EXITS = ("eod", "t2r", "trail")
TOPN = (5, 10, 20)
SIDES = ("both", "long", "short")
FILTERS = ("all", "vixhigh", "rvol15", "nores")
REASON = {"stop": 0, "target": 1, "eod": 2, "be": 3}


def dk(t):
    return (t + 19800) // 86400


def mins(t):
    return ((t + 19800) % 86400) // 60


def kdate(k):
    return date(1970, 1, 1) + timedelta(days=k)


# ── pass 1: daily features from 15m, walk-forward expected move ──────────────────

def features_15m(sym, read_file, reaction):
    b = read_file(sym)
    if len(b) < 1000:
        return []
    days = defaultdict(list)
    for i in range(len(b)):
        days[dk(b.t[i])].append(i)
    keys = sorted(days)
    summ = {k: (max(b.h[i] for i in days[k]), min(b.l[i] for i in days[k]), b.c[days[k][-1]],
                sum(b.v[i] for i in days[k][:2]), b.v[days[k][0]]) for k in keys}
    out = []
    for n in range(16, len(keys)):
        k = keys[n]
        ix = days[k]
        if len(ix) < 22 or mins(b.t[ix[0]]) != 555 or mins(b.t[ix[1]]) != 570:
            continue
        prev = [summ[keys[j]] for j in range(n - 15, n)]
        pc = prev[-1][2]
        trs = [max(d[0] - d[1], abs(d[0] - p[2]), abs(d[1] - p[2])) for p, d in zip(prev[:-1], prev[1:])]
        atr = sum(trs) / len(trs)
        base = sum(p[3] for p in prev[-14:]) / 14
        if not atr or not base or not pc or not summ[k][3]:
            continue
        o, p0945 = b.o[ix[0]], b.c[ix[1]]
        p1500 = next((b.o[i] for i in ix if mins(b.t[i]) == 900), None)
        rvol = summ[k][3] / base
        base15 = sum(p[4] for p in prev[-14:]) / 14
        # the OR15 trades start at 09:30, so their filter may only see the 09:15 bar's volume
        rvol15 = summ[k][4] / base15 if base15 else 0.0
        res = 1.0 if k in reaction.get(sym, ()) else 0.0
        x9 = (math.log(max(rvol, 0.05)), atr / pc * 100, abs(o / pc - 1) * 100, abs(p0945 / o - 1) * 100,
              (prev[-1][0] - prev[-1][1]) / atr, res)
        y = abs(p1500 / p0945 - 1) * 1e4 if p1500 else None
        out.append((k, sym, x9, y, atr, rvol, res, rvol15))
    return out


def walk_forward(samples):
    """pred0945[(k,sym)], predopen[(k,sym)] — weights fitted only on days before each month."""
    by_month = defaultdict(list)
    for s in samples:
        d = kdate(s[0])
        by_month[(d.year, d.month)].append(s)
    months = sorted(by_month)
    p9, p0 = {}, {}
    hist = []
    for ym in months:
        cur = by_month[ym]
        train = [s for s in hist if s[3] is not None]
        if len({s[0] for s in train}) >= MIN_TRAIN_DAYS:
            X9 = np.array([list(s[2]) + [1.0] for s in train])
            X0 = np.array([[s[2][1], s[2][2], s[2][4], s[2][5], 1.0] for s in train])
            y = np.array([s[3] for s in train])
            w9 = np.linalg.lstsq(X9, y, rcond=None)[0]
            w0 = np.linalg.lstsq(X0, y, rcond=None)[0]
            for s in cur:
                p9[(s[0], s[1])] = float(np.dot(list(s[2]) + [1.0], w9))
                p0[(s[0], s[1])] = float(np.dot([s[2][1], s[2][2], s[2][4], s[2][5], 1.0], w0))
        hist.extend(cur)
    return p9, p0


def ranks(pred, pit):
    by_day = defaultdict(list)
    for (k, sym), v in pred.items():
        if pit.get(k) is None or sym in pit[k]:
            by_day[k].append((v, sym))
    out = {}
    for k, xs in by_day.items():
        xs.sort(reverse=True)
        for r, (_v, sym) in enumerate(xs[:max(TOPN)], 1):
            out[(k, sym)] = r
    return out


# ── pass 2: simulate on 5m bars ──────────────────────────────────────────────────

class Day5:
    __slots__ = ("t", "o", "h", "l", "c", "v", "m")

    def __init__(self, b, ix):
        self.t = [b.t[i] for i in ix]
        self.o = [b.o[i] for i in ix]
        self.h = [b.h[i] for i in ix]
        self.l = [b.l[i] for i in ix]
        self.c = [b.c[i] for i in ix]
        self.v = [b.v[i] for i in ix]
        self.m = [mins(t) for t in self.t]


def find_entries(d, or_bars, start_min, slip):
    """{(entry, window): (side, fill_index, fill_price, is_limit)} for one day."""
    n_or = or_bars
    if len(d.m) < 60 or d.m[0] != 555 or d.m[n_or - 1] != 555 + 5 * (n_or - 1):
        return None, None
    hi, lo = max(d.h[:n_or]), min(d.l[:n_or])
    if hi <= lo:
        return None, None
    avg_v = sum(d.v[:n_or]) / n_or
    first = next((i for i in range(n_or, len(d.m)) if d.m[i] >= start_min), None)
    if first is None:
        return None, None
    out = {}
    # touch
    touch = None
    for i in range(first, len(d.m)):
        if d.m[i] >= 870:
            break
        up, dn = d.h[i] > hi, d.l[i] < lo
        if up and dn:
            touch = ("both", i)
            break
        if up or dn:
            touch = ("LONG" if up else "SHORT", i)
            break
    # close / closevol
    close_sig = closevol_sig = None
    for i in range(first, len(d.m) - 1):
        if d.m[i + 1] >= 870:
            break
        side = "LONG" if d.c[i] > hi else "SHORT" if d.c[i] < lo else None
        if side and close_sig is None:
            close_sig = (side, i + 1)
        if side and closevol_sig is None and d.v[i] >= 1.5 * avg_v:
            closevol_sig = (side, i + 1)
        if close_sig and closevol_sig:
            break
    for wname, wend in WINDOWS:
        if touch and touch[0] != "both" and d.m[touch[1]] < wend:
            side, i = touch
            px = max(hi, d.o[i]) if side == "LONG" else min(lo, d.o[i])
            px = px * (1 + slip) if side == "LONG" else px * (1 - slip)
            out[("touch", wname)] = (side, i, px, False)
        for name, sig in (("close", close_sig), ("closevol", closevol_sig)):
            if sig and d.m[sig[1]] < wend:
                side, i = sig
                px = d.o[i] * (1 + slip) if side == "LONG" else d.o[i] * (1 - slip)
                out[(name, wname)] = (side, i, px, False)
        if touch and touch[0] != "both":
            side, i0 = touch
            lvl = hi if side == "LONG" else lo
            for i in range(i0 + 1, len(d.m)):
                if d.m[i] >= wend:
                    break
                if (side == "LONG" and d.l[i] <= lvl) or (side == "SHORT" and d.h[i] >= lvl):
                    px = min(lvl, d.o[i]) if side == "LONG" else max(lvl, d.o[i])
                    out[("retest", wname)] = (side, i, px, True)
                    break
    return out, (hi, lo)


def simulate(d, side, i0, entry, stop, exit_rule, eod_i, slip):
    """Walk bars from the fill bar. Returns (exit_price, reason)."""
    sgn = 1 if side == "LONG" else -1
    R = abs(entry - stop)
    if R <= 0:
        return None
    target = entry + sgn * 2 * R if exit_rule == "t2r" else None
    cur_stop = stop
    best = entry
    moved_be = False
    for i in range(i0, eod_i):
        o, h, l = d.o[i], d.h[i], d.l[i]
        # stop first (pessimistic), including the fill bar itself
        if i > i0 and ((sgn > 0 and o <= cur_stop) or (sgn < 0 and o >= cur_stop)):
            px = o * (1 - slip) if sgn > 0 else o * (1 + slip)
            return px, "be" if moved_be and cur_stop == entry else "stop"
        if (sgn > 0 and l <= cur_stop) or (sgn < 0 and h >= cur_stop):
            px = cur_stop * (1 - slip) if sgn > 0 else cur_stop * (1 + slip)
            return px, "be" if moved_be and cur_stop == entry else "stop"
        if target is not None and i > i0:
            if (sgn > 0 and h >= target) or (sgn < 0 and l <= target):
                return (max(target, o) if sgn > 0 else min(target, o)), "target"
        if exit_rule == "trail":
            best = max(best, h) if sgn > 0 else min(best, l)
            if not moved_be and (best - entry) * sgn >= R:
                moved_be = True
                cur_stop = entry
            if moved_be:
                trail = best - sgn * R
                cur_stop = max(cur_stop, trail) if sgn > 0 else min(cur_stop, trail)
    o = d.o[eod_i]
    return (o * (1 - slip) if sgn > 0 else o * (1 + slip)), "eod"


async def main():
    from app.core.db import db
    from app.services import intraday_universe
    from app.services.angel_fees import round_trip
    from app.services.intraday_store import read_file
    from app.services.intraday_v2_backtest import pit_universe, deflated_sharpe
    from app.services.intraday_v2_engine import slippage_bp

    t_start = time.time()
    members = await intraday_universe.members()
    syms = [m["symbol"] for m in members]
    if len(sys.argv) > 1:                      # smoke test on the first few names
        syms = syms[:int(sys.argv[1])]
    meta = {m["symbol"]: m for m in members}
    reaction = defaultdict(set)
    async for r in db["results_calendar"].find({"kind": "filed"}, {"symbol": 1, "reaction_day": 1}):
        try:
            noon = datetime.fromisoformat(r["reaction_day"]).replace(hour=12, tzinfo=IST)
            reaction[r["symbol"]].add(dk(int(noon.timestamp())))
        except (KeyError, TypeError, ValueError):
            pass

    # pass 1
    samples = []
    for s in syms:
        samples.extend(features_15m(s, read_file, reaction))
    print(f"pass 1: {len(samples)} stock-days in {time.time() - t_start:.0f}s", flush=True)
    feat = {(s[0], s[1]): s for s in samples}
    all_days = sorted({s[0] for s in samples})
    pit = await pit_universe(kdate(all_days[0]), kdate(all_days[-1]), set(all_days))
    p9, p0 = walk_forward(samples)
    r9, r0 = ranks(p9, pit), ranks(p0, pit)
    pred_days = sorted({k for k, _s in p9})
    print(f"walk-forward predictions: {len(p9)} stock-days over {len(pred_days)} days "
          f"({kdate(pred_days[0])} .. {kdate(pred_days[-1])}); pit days {len(pit)}", flush=True)
    # VIX regime per day: previous close's percentile over the trailing 250 sessions
    vb = read_file("INDIAVIX")
    vclose = {}
    for i in range(len(vb)):
        vclose[dk(vb.t[i])] = vb.c[i]
    vk = sorted(vclose)
    vix_high = {}
    for k in pred_days:
        prior = [vclose[x] for x in vk if x < k][-250:]
        if len(prior) >= 60:
            vix_high[k] = sum(1 for x in prior if x <= prior[-1]) / len(prior) >= 2 / 3

    # pass 2: trades per base key, columnar
    base_keys = list(itertools.product(ORS, ENTRIES, [w for w, _ in WINDOWS], STOPS, EXITS))
    cols = {bk: {"day": array("i"), "rank": array("b"), "side": array("b"), "net": array("d"),
                 "gross_bp": array("d"), "reason": array("b"), "flags": array("b")} for bk in base_keys}
    stats = defaultdict(int)
    t2 = time.time()
    for si, sym in enumerate(syms):
        need = {}
        for (k, s_), r in r9.items():
            if s_ == sym:
                need.setdefault(k, {})["OR30"] = r
        for (k, s_), r in r0.items():
            if s_ == sym:
                need.setdefault(k, {})["OR15"] = r
        if not need:
            continue
        b = read_file(sym, "5m")
        days = defaultdict(list)
        for i in range(len(b)):
            k = dk(b.t[i])
            if k in need:
                days[k].append(i)
        slip = slippage_bp(meta[sym].get("turnover_cr")) / 1e4
        cas = bool(meta[sym].get("cas"))
        for k, ix in days.items():
            d = Day5(b, ix)
            f = feat.get((k, sym))
            atr = f[4] if f else None
            base_flags = (1 if vix_high.get(k) else 0) | (4 if f and f[6] else 0)
            flags_by_or = {"OR30": base_flags | (2 if f and f[5] >= 1.5 else 0),
                           "OR15": base_flags | (2 if f and f[7] >= 1.5 else 0)}
            eod_min = 905 if cas else 910
            eod_i = next((i for i, m in enumerate(d.m) if m == eod_min), None)
            if eod_i is None:
                stats["no_eod_bar"] += 1
                continue
            for orname, rank in need[k].items():
                ents, rng = find_entries(d, 6 if orname == "OR30" else 3, 585 if orname == "OR30" else 570, slip)
                if ents is None:
                    stats["bad_day"] += 1
                    continue
                hi, lo = rng
                flags = flags_by_or[orname]
                for (ename, wname), (side, i0, px, _lim) in ents.items():
                    for stop_name in STOPS:
                        if stop_name == "opp":
                            stop = lo if side == "LONG" else hi
                        elif stop_name == "mid":
                            stop = (hi + lo) / 2
                        else:
                            if not atr:
                                continue
                            stop = px - 0.5 * atr if side == "LONG" else px + 0.5 * atr
                        if (side == "LONG" and stop >= px) or (side == "SHORT" and stop <= px):
                            stats["stop_beyond_fill"] += 1
                            continue
                        for ex in EXITS:
                            r = simulate(d, side, i0, px, stop, ex, eod_i, slip)
                            if r is None:
                                continue
                            xp, reason = r
                            qty = int(NOTIONAL // px)
                            if qty <= 0:
                                continue
                            sgn = 1 if side == "LONG" else -1
                            gross = (xp - px) * qty * sgn
                            fee = round_trip(px, xp, qty, "BUY" if side == "LONG" else "SELL").total
                            c = cols[(orname, ename, wname, stop_name, ex)]
                            c["day"].append(k); c["rank"].append(rank); c["side"].append(sgn)
                            c["net"].append(gross - fee); c["gross_bp"].append((xp / px - 1) * 1e4 * sgn)
                            c["reason"].append(REASON[reason]); c["flags"].append(flags)
                            stats["trades"] += 1
        if si % 20 == 19:
            print(f"  pass 2: {si + 1}/{len(syms)} symbols, {stats['trades']} trades, {time.time() - t2:.0f}s", flush=True)
    print(f"pass 2 done: {dict(stats)} in {time.time() - t2:.0f}s", flush=True)

    # variants
    dev_days = [k for k in pred_days if kdate(k) < HOLDOUT_FROM]
    ho_days = [k for k in pred_days if kdate(k) >= HOLDOUT_FROM]
    dev_idx = {k: i for i, k in enumerate(dev_days)}
    ho_idx = {k: i for i, k in enumerate(ho_days)}
    variants = []
    dev_mat = []
    for bk in base_keys:
        c = cols[bk]
        day = np.frombuffer(c["day"], dtype=np.int32) if len(c["day"]) else np.zeros(0, np.int32)
        rank = np.frombuffer(c["rank"], dtype=np.int8) if len(c["rank"]) else np.zeros(0, np.int8)
        side = np.frombuffer(c["side"], dtype=np.int8) if len(c["side"]) else np.zeros(0, np.int8)
        net = np.frombuffer(c["net"], dtype=np.float64) if len(c["net"]) else np.zeros(0)
        gbp = np.frombuffer(c["gross_bp"], dtype=np.float64) if len(c["gross_bp"]) else np.zeros(0)
        reason = np.frombuffer(c["reason"], dtype=np.int8) if len(c["reason"]) else np.zeros(0, np.int8)
        flags = np.frombuffer(c["flags"], dtype=np.int8) if len(c["flags"]) else np.zeros(0, np.int8)
        isdev = np.array([kdate(int(x)) < HOLDOUT_FROM for x in day], dtype=bool) if len(day) else np.zeros(0, bool)
        dpos = np.array([dev_idx.get(int(x), -1) for x in day], dtype=np.int64)
        hpos = np.array([ho_idx.get(int(x), -1) for x in day], dtype=np.int64)
        for N in TOPN:
            for sd in SIDES:
                for flt in FILTERS:
                    m = rank <= N
                    if sd == "long":
                        m &= side > 0
                    elif sd == "short":
                        m &= side < 0
                    if flt == "vixhigh":
                        m &= (flags & 1) > 0
                    elif flt == "rvol15":
                        m &= (flags & 2) > 0
                    elif flt == "nores":
                        m &= (flags & 4) == 0
                    cap = N * NOTIONAL
                    md, mh = m & isdev & (dpos >= 0), m & ~isdev & (hpos >= 0)
                    dd = np.zeros(len(dev_days))
                    hd = np.zeros(len(ho_days))
                    np.add.at(dd, dpos[md], net[md])
                    np.add.at(hd, hpos[mh], net[mh])

                    def summ(mask, daily):
                        n = int(mask.sum())
                        nets = net[mask]
                        wins, losses = nets[nets > 0].sum(), -nets[nets < 0].sum()
                        r = daily / cap
                        eq = np.cumsum(daily)
                        mdd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])) if len(eq) else 0.0
                        return {"trades": n, "net": round(float(nets.sum()), 0),
                                "net_mean": round(float(nets.mean()), 2) if n else None,
                                "net_sd": round(float(nets.std(ddof=1)), 2) if n > 1 else None,
                                "gross_bp": round(float(gbp[mask].mean()), 2) if n else None,
                                "net_bp": round(float(nets.sum() / n / NOTIONAL * 1e4), 2) if n else None,
                                "pf": round(float(wins / losses), 3) if losses > 0 else None,
                                "win": round(float((nets > 0).mean()), 3) if n else None,
                                "sr_daily": float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std() > 0 else 0.0,
                                "mdd_pct": round(mdd / cap * 100, 2),
                                "stops": int((reason[mask] == 0).sum()), "targets": int((reason[mask] == 1).sum())}
                    variants.append({"key": "|".join(map(str, bk + (f"top{N}", sd, flt))), "dev": summ(md, dd),
                                     "holdout": summ(mh, hd), "_dev_daily": dd / cap, "_ho_daily": hd / cap})
                    dev_mat.append(dd / cap)
    V = len(variants)
    print(f"{V} variants", flush=True)
    srs = np.array([v["dev"]["sr_daily"] for v in variants])
    sr_var = float(srs.var(ddof=1))
    order = np.argsort(-srs)

    # CSCV PBO on the development matrix (numpy)
    M = np.array(dev_mat).T          # days x variants
    T = M.shape[0]
    blocks = 16
    size = T // blocks
    bs = np.array([M[b * size:(b + 1) * size].sum(0) for b in range(blocks)])
    bq = np.array([(M[b * size:(b + 1) * size] ** 2).sum(0) for b in range(blocks)])
    logits = []
    for combo in itertools.combinations(range(blocks), blocks // 2):
        isb = np.zeros(blocks, bool)
        isb[list(combo)] = True

        def sr(sel):
            cnt = size * sel.sum()
            s, q = bs[sel].sum(0), bq[sel].sum(0)
            mu = s / cnt
            var = np.maximum((q - cnt * mu * mu) / (cnt - 1), 1e-18)
            return mu / np.sqrt(var)
        a, o = sr(isb), sr(~isb)
        best = int(np.argmax(a))
        rank = (o <= o[best]).sum()
        w = rank / (V + 1)
        logits.append(math.log(w / (1 - w)))
    pbo = sum(1 for x in logits if x <= 0) / len(logits)
    print(f"PBO over {V} variants: {pbo:.3f}", flush=True)

    top = []
    for j in order[:25]:
        v = variants[j]
        dsr = deflated_sharpe(list(v["_dev_daily"]), sr_var, V)
        top.append({"key": v["key"], "dsr": round(dsr, 4) if dsr is not None else None, "dev": v["dev"],
                    "holdout": v["holdout"]})
    dev_sr = srs
    ho_sr = np.array([v["holdout"]["sr_daily"] for v in variants])
    persist = float(np.corrcoef(dev_sr, ho_sr)[0, 1])

    def family(part_idx, values):
        out = {}
        for val in values:
            idx = [i for i, v in enumerate(variants) if v["key"].split("|")[part_idx] == val]
            out[val] = {"variants": len(idx), "dev_net_bp_mean": round(float(np.mean([variants[i]["dev"]["net_bp"] or 0 for i in idx])), 2),
                        "ho_net_bp_mean": round(float(np.mean([variants[i]["holdout"]["net_bp"] or 0 for i in idx])), 2),
                        "dev_gross_bp_mean": round(float(np.mean([variants[i]["dev"]["gross_bp"] or 0 for i in idx])), 2),
                        "ho_gross_bp_mean": round(float(np.mean([variants[i]["holdout"]["gross_bp"] or 0 for i in idx])), 2),
                        "dev_positive": sum(1 for i in idx if (variants[i]["dev"]["net"] or 0) > 0),
                        "ho_positive": sum(1 for i in idx if (variants[i]["holdout"]["net"] or 0) > 0)}
        return out
    fams = {"or": family(0, ORS), "entry": family(1, ENTRIES), "window": family(2, [w for w, _ in WINDOWS]),
            "stop": family(3, STOPS), "exit": family(4, EXITS), "topn": family(5, [f"top{n}" for n in TOPN]),
            "side": family(6, SIDES), "filter": family(7, FILTERS)}
    plain = next(v for v in variants if v["key"] == "OR30|touch|w1430|opp|eod|top20|both|all")

    # Sub-family robustness: does an (OR, entry, side, filter) idea hold across ALL its
    # stop/exit/window/top-N settings, or only at a lucky one?
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None
    groups = defaultdict(list)
    for i, v in enumerate(variants):
        p = v["key"].split("|")
        groups[(p[0], p[1], p[6], p[7])].append(i)
    subfam = []
    for g, idx in groups.items():
        subfam.append({"group": "|".join(g), "variants": len(idx),
                       "dev_net_bp_mean": mean([variants[i]["dev"]["net_bp"] for i in idx]),
                       "ho_net_bp_mean": mean([variants[i]["holdout"]["net_bp"] for i in idx]),
                       "dev_trades_mean": mean([variants[i]["dev"]["trades"] for i in idx]),
                       "both_positive": sum(1 for i in idx if variants[i]["dev"]["net"] > 0 and variants[i]["holdout"]["net"] > 0)})
    subfam.sort(key=lambda r: -min(r["dev_net_bp_mean"] or -99, r["ho_net_bp_mean"] or -99))

    # Candidates chosen with the holdout in view (so the holdout is USED UP for them): their
    # whole-period record, deflated for every one of the V trials.
    all_days = dev_days + ho_days
    month_of = [kdate(k).strftime("%Y-%m") for k in all_days]
    full_sr = np.array([np.r_[v["_dev_daily"], v["_ho_daily"]].mean() / max(np.r_[v["_dev_daily"], v["_ho_daily"]].std(ddof=1), 1e-12)
                        for v in variants])
    full_sr_var = float(full_sr.var(ddof=1))
    eligible = [i for i, v in enumerate(variants) if v["dev"]["trades"] >= 200 and v["holdout"]["trades"] >= 100
                and (v["dev"]["net_bp"] or -99) > 0 and (v["holdout"]["net_bp"] or -99) > 0]
    eligible.sort(key=lambda i: -min(variants[i]["dev"]["net_bp"], variants[i]["holdout"]["net_bp"]))
    cands = []
    for i in eligible[:12]:
        v = variants[i]
        daily = np.r_[v["_dev_daily"], v["_ho_daily"]]
        mon = defaultdict(float)
        for mth, x in zip(month_of, daily):
            mon[mth] += x
        n_tr = v["dev"]["trades"] + v["holdout"]["trades"]
        net_bp_all = (v["dev"]["net_bp"] * v["dev"]["trades"] + v["holdout"]["net_bp"] * v["holdout"]["trades"]) / n_tr
        dsr_full = deflated_sharpe(list(daily), full_sr_var, V)
        cands.append({"key": v["key"], "trades": n_tr, "net_bp": round(net_bp_all, 2),
                      "net_bp_plus_2bp_per_side": round(net_bp_all - 4, 2),
                      "sharpe_annual": round(float(daily.mean() / daily.std(ddof=1) * math.sqrt(250)), 2),
                      "dsr_all_trials": round(dsr_full, 4) if dsr_full is not None else None,
                      "dsr_if_one_trial": round(deflated_sharpe(list(daily), full_sr_var, 2) or 0, 4),
                      "positive_months": f"{sum(1 for x in mon.values() if x > 0)}/{len(mon)}",
                      "months_pct": {m: round(x * 100, 2) for m, x in sorted(mon.items())}})
    out = {"ran_at": datetime.now(IST).isoformat(), "seconds": round(time.time() - t_start),
           "dev_days": len(dev_days), "holdout_days": len(ho_days),
           "dev_from": str(kdate(dev_days[0])), "holdout_from": str(kdate(ho_days[0])) if ho_days else None,
           "holdout_to": str(kdate(ho_days[-1])) if ho_days else None,
           "variants": V, "pbo": round(pbo, 3), "sr_var": sr_var, "dev_vs_holdout_sr_corr": round(persist, 3),
           "dev_positive_variants": int(sum(1 for v in variants if v["dev"]["net"] > 0)),
           "holdout_positive_variants": int(sum(1 for v in variants if v["holdout"]["net"] > 0)),
           "both_positive_variants": int(sum(1 for v in variants if v["dev"]["net"] > 0 and v["holdout"]["net"] > 0)),
           "plain_rule": {"key": plain["key"], "dev": plain["dev"], "holdout": plain["holdout"]},
           "top25_by_dev_sharpe": top, "families": fams, "subfamilies": subfam,
           "candidates_holdout_used": cands, "stats": dict(stats)}
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    # all variants, compact, for later study
    with open(OUT.replace(".json", "_all.json"), "w") as fh:
        json.dump([{"key": v["key"], "dev": v["dev"], "holdout": v["holdout"]} for v in variants], fh, default=float)
    print(json.dumps({k: out[k] for k in ("variants", "pbo", "dev_vs_holdout_sr_corr", "dev_positive_variants",
                                           "holdout_positive_variants", "both_positive_variants", "plain_rule")},
                     indent=1, default=float))
    for t in top[:12]:
        print(t["key"], "dsr", t["dsr"], "dev", {k: t["dev"][k] for k in ("trades", "net_bp", "gross_bp", "pf", "mdd_pct")},
              "ho", {k: t["holdout"][k] for k in ("trades", "net_bp", "gross_bp", "pf")})
    print("\nsub-families (all stop/exit/window/top-N settings of each idea):")
    for r in subfam[:15]:
        print(" ", r)
    print("\ncandidates (chosen WITH the holdout in view):")
    for c in cands:
        print(" ", {k: c[k] for k in c if k != "months_pct"})


asyncio.run(main())
