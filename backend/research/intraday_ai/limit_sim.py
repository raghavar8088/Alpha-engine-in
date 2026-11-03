"""Phase 3, pre-registered test P3_limit_entry: limit entries vs market entries for the six rules.

Every signal in DATA/runs/<run>/features.jsonl.gz is replayed twice on 5-minute bars with the
SAME exit walk: entered at market (signal price + measured cost) and with a limit order at the
signal price (filled only on a trade-through within 15 minutes). The rule is read from
prereg/P3_limit_entry.json; the verdict is per rule, on the holdout.

    python limit_sim.py y2        -> report + DATA/runs/y2/limit_sim.json
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from prereg import load  # noqa: E402
from stubpkg import DATA, activate, build  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
RULE = load("P3_limit_entry")
NOTIONAL = 1_000_000.0
HOLDOUT_FROM = "2026-05-04"
TF_SECONDS = {"15m": 900, "45m": 2700, "1h": 3600}


def day_key(t: int) -> int:
    return (t + 19800) // 86400


def at(dk: int, hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return dk * 86400 - 19800 + (h * 60 + m) * 60


class Turnover:
    """Point-in-time 20-session average traded value (Rs crore) before each day, from bars1d."""
    def __init__(self):
        self.k: dict[str, list[int]] = defaultdict(list)
        self.v: dict[str, list[float]] = defaultdict(list)
        with open(DATA / "exports" / "bars1d.tsv", encoding="utf-8") as f:
            rows = sorted((s, day_key(int(t)), float(c) * float(v)) for s, t, c, v in
                          (line.rstrip("\n").split("\t") for line in f))
        for s, dk, tv in rows:
            self.k[s].append(dk)
            self.v[s].append(tv)

    def get(self, sym: str, dk: int) -> float | None:
        ks = self.k.get(sym)
        if not ks:
            return None
        i = bisect_left(ks, dk)
        w = self.v[sym][max(0, i - 20):i]
        return sum(w) / len(w) / 1e7 if len(w) >= 15 else None


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else "y2"
    activate(build("HEAD"))
    from app.services.angel_fees import round_trip
    from app.services.intraday_fills import slippage_bp
    from app.services.intraday_store import read_file

    cas = {d["symbol"]: bool(d.get("is_cas_enabled")) for d in
           json.load(open(DATA / "exports" / "export1.json", encoding="utf-8"))["instruments"]}
    turn = Turnover()
    sigs = defaultdict(list)
    for line in gzip.open(DATA / "runs" / run / "features.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if r["sid"] in RULE["rules"] and r["side"] in (1, -1):
            sigs[r["sym"]].append(r)

    out = []
    for sym, rows in sigs.items():
        b = read_file(sym, "5m")
        T, O, H, L, C = list(b.t), list(b.o), list(b.h), list(b.l), list(b.c)
        is_cas = cas.get(sym, True)
        for r in rows:
            out.append(simulate(r, T, O, H, L, C, is_cas, turn, slippage_bp, round_trip))
    report(out, run)


def simulate(r, T, O, H, L, C, is_cas, turn, slippage_bp, round_trip) -> dict:
    side, entry, t_sig = r["side"], r["entry"], r["t"]
    dk = day_key(t_sig)
    bp = slippage_bp(turn.get(r["sym"], dk), NOTIONAL)
    k0 = bisect_left(T, t_sig)
    sq_t = at(dk, "15:00") if is_cas else at(dk, "15:10")      # the square-off bar's start
    res = {"sid": r["sid"], "day": r["day"], "hold": r["day"] >= HOLDOUT_FROM, "bp": bp}

    def levels(fill):
        stop = r["stop_price"] if r.get("stop_price") is not None else fill - side * r["stop_dist"]
        if r.get("target_price") is not None:
            tgt = r["target_price"]
        elif r.get("target_dist"):
            tgt = fill + side * r["target_dist"]
        else:
            tgt = None
        return stop, tgt

    def walk(k, fill, t_entry):
        """Exit (price, market?) walking 5m bars from index k, on the signal's day."""
        stop, tgt = levels(fill)
        if side * (fill - stop) <= 0 or (tgt is not None and side * (tgt - fill) <= 0):
            return None                                          # the engine would not open it
        t_stop = t_entry + r["max_bars"] * TF_SECONDS.get(r["tf"], 900) if r.get("max_bars") else None
        last = None
        while k < len(T) and day_key(T[k]) == dk:
            t, o, h, lo, c = T[k], O[k], H[k], L[k], C[k]
            if t >= sq_t:
                return (o if is_cas else c), True
            if side * (o - stop) <= 0:
                return o, True
            if tgt is not None and side * (o - tgt) >= 0:
                return o, False
            if (lo if side > 0 else -h) <= side * stop:
                return stop, True
            if tgt is not None and (h if side > 0 else -lo) >= side * tgt:
                return tgt, False
            if t_stop is not None and t + 300 >= t_stop:
                return c, True
            last = c
            k += 1
        return (last if last is not None else fill), True

    def book(fill, ex):
        if ex is None:
            return None
        px, market = ex
        xp = px * (1 - side * bp / 1e4) if market else px
        qty = int(NOTIONAL // fill)
        if qty < 1:
            return None
        gross = side * (xp - fill) * qty
        fees = round_trip(entry_price=fill, exit_price=xp, qty=qty, side="BUY" if side > 0 else "SELL",
                          product="INTRADAY").total
        n = fill * qty
        return gross / n * 1e4, (gross - fees) / n * 1e4

    # market entry: the live engine's fill
    fill_m = entry * (1 + side * bp / 1e4)
    m = book(fill_m, walk(k0, fill_m, t_sig))
    res["m"] = m is not None
    res["m_gross"], res["m_net"] = m if m else (0.0, 0.0)
    # limit entry at the signal price, a trade-through within three 5-minute bars
    thr = max(0.05, entry * 1e-4)
    res["l"], res["l_gross"], res["l_net"] = False, 0.0, 0.0
    for k in range(k0, min(k0 + 3, len(T))):
        if day_key(T[k]) != dk or T[k] >= sq_t:
            break
        if (side > 0 and L[k] <= entry - thr) or (side < 0 and H[k] >= entry + thr):
            stop, _tgt = levels(entry)
            if (L[k] if side > 0 else -H[k]) <= side * stop:      # the fill bar also reached the stop
                ex = (stop, True) if side * (entry - stop) > 0 else None
            else:
                ex = walk(k + 1, entry, T[k])
            lb = book(entry, ex)
            if lb is not None:
                res["l"], (res["l_gross"], res["l_net"]) = True, lb
            break
    return res


def clustered(rows: list[dict], key: str) -> tuple[float, float, int]:
    """Mean of `key` per signal and its t-statistic clustered by session."""
    by_day = defaultdict(lambda: [0.0, 0])
    for r in rows:
        by_day[r["day"]][0] += r[key]
        by_day[r["day"]][1] += 1
    n = sum(c for _s, c in by_day.values())
    if n == 0 or len(by_day) < 3:
        return 0.0, 0.0, n
    mean = sum(s for s, _c in by_day.values()) / n
    D = len(by_day)
    var = sum((s - mean * c) ** 2 for s, c in by_day.values()) / (n * n) * D / (D - 1)
    return mean, (mean / math.sqrt(var) if var > 0 else 0.0), n


def report(out: list[dict], run: str) -> None:
    res = {}
    print(f"{'rule':<24} {'period':<5} {'signals':>7} {'fill%':>6} {'mkt net/sig':>11} {'lim net/sig':>11} {'t(lim)':>7} "
          f"{'adverse':>8} {'missed mkt gross':>16}  verdict")
    for sid in RULE["rules"]:
        for period, sel in (("dev", False), ("hold", True)):
            rows = [r for r in out if r["sid"] == sid and r["hold"] == sel and r["m"]]
            if not rows:
                continue
            fill = sum(r["l"] for r in rows) / len(rows)
            m_mean, m_t, n = clustered(rows, "m_net")
            l_mean, l_t, _ = clustered(rows, "l_net")
            filled = [r for r in rows if r["l"]]
            adverse = (sum(r["l_gross"] for r in filled) / len(filled) - sum(r["m_gross"] for r in filled) / len(filled)) if filled else None
            missed = [r for r in rows if not r["l"]]
            missed_g = sum(r["m_gross"] for r in missed) / len(missed) if missed else None
            verdict = ""
            if sel:
                go = l_mean > 0 and l_t >= 2 and fill >= 0.40
                verdict = "GO" if go else "NO-GO"
            res[f"{sid}:{period}"] = {"signals": n, "fill_rate": round(fill, 3), "market_net_bp": round(m_mean, 3),
                                      "market_t": round(m_t, 2), "limit_net_bp": round(l_mean, 3), "limit_t": round(l_t, 2),
                                      "adverse_selection_bp": round(adverse, 3) if adverse is not None else None,
                                      "missed_market_gross_bp": round(missed_g, 3) if missed_g is not None else None,
                                      "verdict": verdict or None}
            print(f"{sid:<24} {period:<5} {n:>7} {fill * 100:>5.1f}% {m_mean:>11.2f} {l_mean:>11.2f} {l_t:>7.2f} "
                  f"{adverse if adverse is not None else float('nan'):>8.2f} {missed_g if missed_g is not None else float('nan'):>16.2f}  {verdict}")
    json.dump({"rule_fingerprint_name": "P3_limit_entry", "results": res}, open(DATA / "runs" / run / "limit_sim.json", "w"), indent=1)


if __name__ == "__main__":
    main()
