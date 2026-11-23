"""Imported Top 25: the existing Intraday Stocks (54) and Stock Momentum Trading (8) strategies on ONE harness -
the same dates, universe, capital, costs and fills - then ranked, de-duplicated and cut to 25 distinct strategies.

Sources (read only; nothing in either module is run, refreshed or approved):
  tournament  the signals recorded by the app's own audit replay of the 54 rules (D:/intraday_ai_data/runs/audit54/
              signals.csv.gz; code at c64c7b7, intraday_v2_strategies.py md5 010bc509..., byte-identical to the box)
  momentum    backend/app/services/screener/morning.py as committed on origin/main (2252267e, md5 7be4ff8b...),
              executed unmodified through pis.imported.load_morning
Window: 1 May 2025 - 3 Nov 2026 (before May 2025 the tournament's point-in-time universe held ~26 stocks a day).
Universe: this desk's (top 150 by traded value), so every strategy sees the same stocks.

Two views per strategy:
  rule    every signal as a trade, sized at 0.25% risk, no slot limits - what the rule itself earns
  book    the desk's Rs 10 lakh book with its limits (3 positions, 0.75% open risk, sector caps, partial fills)
"""
import csv
import gzip
import json
import math
import pickle
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev

from common import DATA, PANEL, RUNS, HERE, ROOT
from pis import costs as C
from pis.book import Book, exit_check
from pis.config import Settings
from pis.imported import BarsAdapter, load_morning, morning_intent, tournament_time_exit, tournament_tf, MORNING_RULES
from pis.replay import Panel, day_context, INDICES
from pis.stats import summarize
from pis.state import DayState
from pis.timeutil import bar_index, day_of, minute, OPEN_MIN, open_epoch, hhmm

START, END = date(2025, 5, 1), date(2026, 11, 3)
SIGNALS = "D:/intraday_ai_data/runs/audit54/signals.csv.gz"
MORNING = "D:/premium_intraday_data/vendor/morning_origin_2252267e.py"
OUT = RUNS / "imported"
S = Settings()
BUDGET = S.risk.risk_per_trade * S.risk.capital


def load_signals():
    by_day = defaultdict(list)
    with gzip.open(SIGNALS, "rt", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        for sid, sym, t, side, entry, stop_bp, tgt_bp, trig, prio, rvol, traded, rep in r:
            t = int(t)
            d = day_of(t)
            if not (START <= d <= END):
                continue
            by_day[d].append((sid, sym, t, 1 if side == "BUY" else -1, float(entry), float(stop_bp or 0),
                              float(tgt_bp) if tgt_bp else None, trig == "1", float(prio or 0)))
    return by_day


def rule_trade(by_k, k_entry, ref, stop, target, side, slip, time_exit_min, vol):
    """One signal, alone: same fill and exit rules as pis.book (exit_check), sized at 0.25% risk.
    by_k: {bar index: bar} of the stock's day."""
    fill = ref * (1 + side * slip / 1e4)
    psr = abs(fill - stop)
    if psr <= 0:
        return None
    cps = C.est_cost_per_share(fill, max(1, int(BUDGET / psr)), side, slip)
    qty = int(BUDGET // (psr + cps))
    qty = min(qty, int(S.risk.max_notional_frac * S.risk.capital // fill), int(S.risk.max_participation * vol))
    if qty < 1:
        return None
    ex = None
    for k in range(k_entry + 1, 75):
        b = by_k.get(k)
        if b is None:
            continue
        ex = exit_check(side, stop, target, slip, time_exit_min, b, k)
        if ex is None and k >= 69:
            ex = (b[4], b[4] * (1 - side * slip / 1e4), "square-off 15:05")
        if ex is not None:
            t_exit = b[0] + 300
            break
    if ex is None:
        last = by_k[max(by_k)]
        ex, t_exit = (last[4], last[4] * (1 - side * slip / 1e4), "FAILED EXIT"), last[0] + 300
    gross = (ex[1] - fill) * side * qty
    fees = C.charges(fill, ex[1], qty, side)
    net = gross - fees["total"]
    return {"entry": fill, "ref": ref, "exit": ex[1], "exit_ref": ex[0], "qty": qty, "side": side, "net": net,
            "gross": gross, "fees": fees, "r_net": net / (qty * (psr + cps)), "notional": fill * qty,
            "reason": ex[2], "t_entry": by_k[k_entry][0] + 300 if k_entry in by_k else 0, "t_exit": t_exit,
            "failed_exit": ex[2] == "FAILED EXIT", "partial": False}


def trigger_fill(bars, k_from, trig, side, stop_dist):
    """ORB-style stop entry armed after bar k_from: first bar crossing the trigger until the 14:30 close.
    Returns (k, ref, stop_hit_same_bar)."""
    for b in bars:
        k = bar_index(b[0])
        if k <= k_from or OPEN_MIN + (k + 1) * 5 > 14 * 60 + 30:
            continue
        crossed = b[2] >= trig if side > 0 else b[3] <= trig
        if crossed:
            ref = max(trig, b[1]) if side > 0 else min(trig, b[1])
            stop = ref - side * stop_dist
            same = (b[3] <= stop) if side > 0 else (b[2] >= stop)
            return k, ref, same
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    panel = Panel(str(PANEL), DATA)
    days = [d for d in panel.days if START <= d <= END]
    sigs = load_signals()
    print("signals loaded", sum(len(v) for v in sigs.values()), flush=True)
    rule = defaultdict(list)              # strategy -> trades (every signal)
    books = {}
    keys = defaultdict(set)               # strategy -> {(sym, day, 30-min bucket, side)} for overlap
    window = []                           # last 25 sessions' bars for the momentum scan baselines
    morning = load_morning(MORNING)

    def book(name):
        if name not in books:
            books[name] = Book(name, S.risk)
        return books[name]

    for n, d in enumerate(days):
        dc = day_context(panel, d, S)
        if dc is None:
            continue
        members = dc["members"]
        mset = set(members)
        bars = panel.bars(d)
        BK = {s_: {bar_index(b[0]): b for b in v} for s_, v in bars.items()}
        for b in books.values():
            b.start_day(d)
        state = DayState(d)
        # ---- tournament signals in this desk's universe -> intents at their bar k
        intents = defaultdict(list)       # k -> [(prio, name, intent, trig?)]
        armed = []
        for sid, sym, t, side, entry, stop_bp, tgt_bp, trig, prio in sigs.get(d, []):
            if sym not in mset or sym not in bars:
                continue
            c = dc["ctx"][sym]
            k_sig = (t - open_epoch(d)) // 300 - 1          # the 5-minute bar that closes at t
            stop_dist = stop_bp / 1e4 * entry
            tgt_dist = tgt_bp / 1e4 * entry if tgt_bp else None
            if trig:
                tf = trigger_fill(bars[sym], k_sig, entry, side, stop_dist)
                if tf is None:
                    continue
                k, ref, same = tf
            else:
                k = k_sig
                b = BK[sym].get(k)
                if b is None:
                    continue
                ref, same = b[4], False
            if OPEN_MIN + (k + 1) * 5 > 14 * 60 + 30:
                continue
            stop = ref - side * stop_dist
            target = ref + side * tgt_dist if tgt_dist else None
            tex = tournament_time_exit(sid, OPEN_MIN + (k + 1) * 5)
            vol = BK[sym][k][5] if k in BK[sym] else 0
            tr = rule_trade(BK[sym], k, ref, stop, target, side, c.slip_bp, tex, vol)
            if tr is not None:
                if same:                                  # pessimistic: stop inside the trigger bar
                    fill = tr["entry"]
                    xp = stop * (1 - side * c.slip_bp / 1e4)
                    tr.update(exit=xp, exit_ref=stop, reason="stop (trigger bar)")
                    tr["gross"] = (xp - fill) * side * tr["qty"]
                    tr["fees"] = C.charges(fill, xp, tr["qty"], side)
                    tr["net"] = tr["gross"] - tr["fees"]["total"]
                    tr["r_net"] = tr["net"] / (tr["qty"] * (abs(fill - stop) + C.est_cost_per_share(fill, tr["qty"], side, c.slip_bp)))
                tr.update(symbol=sym, sector=c.sector, day=str(d))
                rule[sid].append(tr)
                keys[sid].add((sym, str(d), (OPEN_MIN + (k + 1) * 5) // 30, side))
            intents[k].append((-prio, sid, {"strategy": sid, "variant": "as-built", "level": "imported",
                                            "symbol": sym, "sector": c.sector, "side": side, "ref": ref, "stop": stop,
                                            "target": target, "slip_bp": c.slip_bp, "bar_volume": vol,
                                            "time_exit_min": tex, "knew": {}}, same))
        # ---- Stock Momentum Trading: the desk's own 09:30 scan and triggers
        window.append(bars)
        if len(window) > 26:
            window.pop(0)
        hist_rows = defaultdict(list)
        for wb in window:
            for s in members + ["NIFTY"]:
                hist_rows[s] += wb.get(s, [])
        adapters = {s: BarsAdapter(v) for s, v in hist_rows.items()}
        start = open_epoch(d)
        from pis.sectors import sector_map
        smap = sector_map()
        sm_members = {s: (smap.get(s) or {}).get("industry") for s in members}
        rows, _ex = morning.scan(start, sm_members, lambda sym, tf="5m": adapters.get(sym, BarsAdapter([])))
        for r in rows:
            if r.get("rank", 999) > 10 or r["turnover"] < 1e7:
                continue
            sym = r["symbol"]
            day_bars = [x for x in bars.get(sym, [])]
            if len(day_bars) < 5:
                continue
            used = set()
            c = dc["ctx"][sym]
            for k in range(3, min(62, len(day_bars) - 1)):
                if day_bars[k][0] != start + k * 300:
                    break
                for rl, side in morning.triggers(r, day_bars[:k + 1]):
                    if rl in used or side != r["side"] or (side < 0 and not c.fno):
                        continue
                    it = morning_intent(rl, side, r, day_bars[k], k, c.slip_bp, c.sector)
                    if it is None:
                        continue
                    used.add(rl)
                    name = f"SM:{rl}"
                    tr = rule_trade(BK[sym], k, it["ref"], it["stop"], it["target"], side, c.slip_bp, it["time_exit_min"], it["bar_volume"])
                    if tr is not None:
                        tr.update(symbol=sym, sector=c.sector, day=str(d))
                        rule[name].append(tr)
                        keys[name].add((sym, str(d), (OPEN_MIN + (k + 1) * 5) // 30, side))
                    intents[k].append((-r["score"], name, it, False))
        # ---- the consistent books, bar by bar
        feed = [s for s in members + list(INDICES) if s in bars]
        by_k = defaultdict(list)
        for s in feed:
            for b in bars[s]:
                by_k[bar_index(b[0])].append((s, b))
        for k in range(75):
            for s, b in by_k.get(k, ()):
                state.add(s, b)
            t_close = open_epoch(d) + (k + 1) * 300
            for bk in books.values():
                bk.manage(state, k, t_close)
                if k in (69, 70):
                    bk.square_off(state, k, t_close, final=(k == 70))
            for prio, name, it, same in sorted(intents.get(k, []), key=lambda x: (x[0], x[1], x[2]["symbol"])):
                bk = book(name)
                p, why = bk.admit(it, k, t_close, 14 * 60 + 30)
                if p is not None and same:
                    bk._close(p, it["stop"], it["stop"] * (1 - it["side"] * it["slip_bp"] / 1e4), k, t_close, "stop (trigger bar)")
        for bk in books.values():
            bk.square_off(state, 74, open_epoch(d) + 75 * 300, final=True)
        if n % 25 == 0:
            print(d, "rule trades", sum(len(v) for v in rule.values()), flush=True)
    res = {"rule": dict(rule), "book": {k: [p.public() | {"side": p.side} for p in b.closed] for k, b in books.items()},
           "keys": {k: list(v) for k, v in keys.items()}, "sessions": len(days)}
    with open(OUT / "imported.pkl", "wb") as f:
        pickle.dump(res, f)
    print("saved", OUT / "imported.pkl")


if __name__ == "__main__":
    main()
