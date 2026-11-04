"""Audit of the 54 tournament strategies — the numbers (read-only).

    python audit54_analyze.py [--name audit54]

Reads the replay (audit54.py), the code checks (audit54_checks.py) and the live tournament
export, and writes DATA/runs/<name>/tables.json plus tables.md. Four views per strategy:

  SIGNALS   what the rule asks for: count, planned stop / target in bp, planned reward:risk,
            share of signals that never became a trade, time of day, priority scale
  EVERY TRADE  every signal simulated as a trade (no slot, cash or per-stock limit): edge
            before any cost, slippage, charges, net per trade, t-stat, win rate, direction
            hit rate, realised payoff, exit mix; development vs the last six months
  SOLO BOOK the strategy alone with its live limits (Rs 50 lakh, five Rs 10 lakh slots, cash,
            no second position in a stock it holds): profit, return, win rate, profit factor,
            max drawdown, Sharpe, positive months, year 1 / year 2 / last six months
  TOURNAMENT the same with the other 53 strategies and the two-strategies-per-stock cap — the
            difference to SOLO is the interference
plus the LIVE paper record (6 Oct - 3 Nov 2026) with the entry drift live fills paid.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import pathlib
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
CAPITAL = 5_000_000.0
Y1_END = date(2025, 11, 3)
HOLDOUT = date(2026, 5, 4)          # the research convention: the last six months


def d_of(epoch: int) -> date:
    return datetime.fromtimestamp(int(epoch), IST).date()


def mod_of(epoch: int) -> int:
    d = datetime.fromtimestamp(int(epoch), IST)
    return d.hour * 60 + d.minute


def tstat(n, s, ss):
    if n < 3:
        return None
    m = s / n
    var = (ss - n * m * m) / (n - 1)
    return round(m / math.sqrt(var / n), 2) if var > 0 else None


def cluster_t(days: dict, k: int):
    """t of the per-trade mean of field k (1 = raw bp, 2 = net bp) with standard errors
    clustered by day: SE = sqrt(sum_d (S_d - n_d * mean)^2) / N."""
    n = sum(v[0] for v in days.values())
    if n < 3 or len(days) < 3:
        return None
    m = sum(v[k] for v in days.values()) / n
    se = math.sqrt(sum((v[k] - v[0] * m) ** 2 for v in days.values())) / n
    g = len(days)
    se *= math.sqrt(g / (g - 1))
    return round(m / se, 2) if se else None


def pct(v, q):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="audit54")
    a = ap.parse_args()
    run = DATA / "runs" / a.name
    meta = json.load(open(run / "meta.json", encoding="utf-8"))
    summ = json.load(open(run / "summary.json", encoding="utf-8"))
    order = [r["strategy_id"] for r in summ["results"]]
    gate = {r["strategy_id"]: r for r in summ["results"]}
    sys.path.insert(0, str(next((DATA / "pkg").glob(summ["meta"]["commit_pkg"]))))
    from app.services import intraday_v2_strategies as v2
    catalog = [s.strategy_id for s in v2.CATALOG]
    spec = {s.strategy_id: s for s in v2.CATALOG}

    # ── signals ──
    sig = defaultdict(lambda: {"n": 0, "traded": 0, "stop": [], "tgt": [], "rr": [], "prio": [],
                               "first_hour": 0, "rep": 0, "rep_n": 0, "buy": 0, "by_hour": Counter(),
                               "tiny": 0})
    days_all = set()
    last_sig: dict = {}
    tf_sec = {"15m": 900, "45m": 2700, "1h": 3600}
    with gzip.open(run / "signals.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = sig[r["sid"]]
            g["n"] += 1
            # the same rule, same stock, same side on the bar right before: a repeat signal
            t_, k_ = int(r["t"]), (r["sid"], r["sym"])
            prev = last_sig.get(k_)
            step = tf_sec.get(spec[r["sid"]].tf)
            if prev and step and prev[1] == r["side"] and 0 < t_ - prev[0] <= step and d_of(prev[0]) == d_of(t_):
                g["consec"] = g.get("consec", 0) + 1
            last_sig[k_] = (t_, r["side"])
            g["traded"] += int(r["traded"])
            g["buy"] += int(r["side"] == "BUY")
            if r["stop_bp"]:
                g["stop"].append(float(r["stop_bp"]))
            if r["tgt_bp"]:
                g["tgt"].append(float(r["tgt_bp"]))
                # entry slippage + the rate card (~4 bp a round trip at Rs 10 lakh); a target
                # exit is a limit order and pays no slippage of its own
                g["tiny"] += int(float(r["tgt_bp"]) < ((meta.get(r["sym"]) or {}).get("slip_bp") or 4.12) + 4.0)
                if r["stop_bp"] and float(r["stop_bp"]) > 0:
                    g["rr"].append(float(r["tgt_bp"]) / float(r["stop_bp"]))
            g["prio"].append(float(r["priority"]))
            t = int(r["t"])
            m = mod_of(t)
            g["first_hour"] += int(m <= 10 * 60 + 15)
            g["by_hour"][f"{m // 60:02d}"] += 1
            if r["repeat_break"] != "":
                g["rep_n"] += 1
                g["rep"] += int(r["repeat_break"])
            days_all.add(d_of(t))

    # ── which candidates each book took ──
    taken = {}
    for book in ("live", "solo"):
        with gzip.open(run / f"taken_{book}.csv.gz", "rt", encoding="utf-8") as f:
            taken[book] = {(r["sid"], r["sym"], int(r["et"])) for r in csv.DictReader(f)}

    # ── every trade + the books ──
    cand = defaultdict(lambda: {"n": 0, "s": 0.0, "ss": 0.0, "win": 0, "dir": 0, "raw": 0.0, "slip": 0.0,
                                "fee": 0.0, "wbp": 0.0, "lbp": 0.0, "nw": 0, "nl": 0, "exit": Counter(),
                                "hold": [], "dev": [0, 0.0, 0.0], "hold6": [0, 0.0, 0.0], "rep": {}})
    opt = defaultdict(lambda: [0, 0.0])
    books = {"live": defaultdict(list), "solo": defaultdict(list)}
    with gzip.open(run / "candidates.csv.gz", "rt", encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd)
        for sid, sym, et, xt, side, ep, xp, qty, gross, fees, net, reason, prio in rd:
            et, xt, ep, xp, qty = int(et), int(xt), float(ep), float(xp), int(qty)
            gross, fees, net = float(gross), float(fees), float(net)
            notional = ep * qty
            if notional <= 0:
                continue
            if sid.endswith("~opt"):
                o = opt[sid[:-4]]
                o[0] += 1
                o[1] += net / notional * 1e4
                continue
            sign = 1 if side == "BUY" else -1
            bp = (meta.get(sym) or {}).get("slip_bp") or 4.12
            e_raw = ep / (1 + sign * bp / 1e4)
            x_raw = xp if reason == "target" else xp / (1 - sign * bp / 1e4)
            raw = sign * (x_raw - e_raw) / e_raw * 1e4
            g_bp, f_bp, n_bp = gross / notional * 1e4, fees / notional * 1e4, net / notional * 1e4
            c = cand[sid]
            c["n"] += 1
            c["s"] += n_bp
            c["ss"] += n_bp * n_bp
            c["win"] += int(net > 0)
            c["dir"] += int(raw > 0)
            c["raw"] += raw
            c["rss"] = c.get("rss", 0.0) + raw * raw
            dd_ = c.setdefault("days", {}).setdefault(d_of(et), [0, 0.0, 0.0])
            dd_[0] += 1; dd_[1] += raw; dd_[2] += n_bp
            c["slip"] += raw - g_bp
            c["fee"] += f_bp
            if net > 0:
                c["wbp"] += n_bp; c["nw"] += 1
            elif net < 0:
                c["lbp"] += -n_bp; c["nl"] += 1
            c["exit"][reason] += 1
            c["hold"].append((xt - et) // 60)
            p = c["dev"] if d_of(et) < HOLDOUT else c["hold6"]
            p[0] += 1; p[1] += n_bp; p[2] += n_bp * n_bp
            # descriptive splits (not filters): entry in the first hour or later; F&O (CAS) or not
            q = c.setdefault("split", {"first_hour": [0, 0.0, 0.0], "later": [0, 0.0, 0.0],
                                       "fno": [0, 0.0, 0.0], "non_fno": [0, 0.0, 0.0]})
            for key in ("first_hour" if mod_of(et) <= 10 * 60 + 15 else "later",
                        "fno" if (meta.get(sym) or {}).get("cas", True) else "non_fno"):
                q[key][0] += 1; q[key][1] += raw; q[key][2] += n_bp
            row = (et, xt, net, gross, fees, n_bp)
            for book in ("live", "solo"):
                if (sid, sym, et) in taken[book]:
                    books[book][sid].append(row)

    sessions = sorted(days_all)
    years = len(sessions) / 247.5

    def book_stats(rows):
        if not rows:
            return {"trades": 0}
        nets = [r[2] for r in rows]
        wins = [x for x in nets if x > 0]
        losses = [-x for x in nets if x < 0]
        daily = defaultdict(float)
        months = defaultdict(float)
        per = {"y1": 0.0, "y2": 0.0, "h6": 0.0}
        for r in rows:
            d = d_of(r[1])
            daily[d] += r[2]
            months[d.strftime("%Y-%m")] += r[2]
            per["y1" if d <= Y1_END else "y2"] += r[2]
            if d >= HOLDOUT:
                per["h6"] += r[2]
        eq = peak = mdd = 0.0
        series = []
        for d in sessions:
            eq += daily.get(d, 0.0)
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
            series.append(daily.get(d, 0.0))
        m = statistics.fmean(series)
        sd = statistics.pstdev(series)
        tot = sum(nets)
        return {"trades": len(rows), "per_session": round(len(rows) / len(sessions), 2),
                "net": round(tot), "gross": round(sum(r[3] for r in rows)), "fees": round(sum(r[4] for r in rows)),
                "return_pct": round(tot / CAPITAL * 100, 1), "per_year_pct": round(tot / CAPITAL * 100 / years, 1),
                "win_rate": round(len(wins) / len(nets) * 100, 1),
                "profit_factor": round(sum(wins) / sum(losses), 3) if losses else None,
                "avg_win": round(statistics.fmean(wins)) if wins else 0,
                "avg_loss": round(statistics.fmean(losses)) if losses else 0,
                "payoff": round(statistics.fmean(wins) / statistics.fmean(losses), 2) if wins and losses else None,
                "max_dd": round(mdd), "max_dd_pct": round(mdd / CAPITAL * 100, 1),
                "sharpe": round(m / sd * math.sqrt(250), 2) if sd else None,
                "months_positive": f"{sum(1 for v in months.values() if v > 0)}/{len(months)}",
                "months_positive_share": round(sum(1 for v in months.values() if v > 0) / len(months), 2),
                "worst_month": round(min(months.values())), "best_month": round(max(months.values())),
                "y1": round(per["y1"]), "y2": round(per["y2"]), "h6": round(per["h6"]),
                "net_bp_per_trade": round(statistics.fmean(r[5] for r in rows), 2)}

    # ── live paper record ──
    live = defaultdict(lambda: {"n": 0, "net": 0.0, "win": 0, "drift": []})
    for line in open(DATA / "exports" / "live_v2.jsonl", encoding="utf-8"):
        p = json.loads(line)
        L = live[p["strategy_id"]]
        L["n"] += 1
        L["net"] += p.get("realized_pnl") or 0.0
        L["win"] += int((p.get("realized_pnl") or 0.0) > 0)
        sp, epx, sl = p.get("signal_price"), p.get("entry_price"), p.get("slippage_bp") or 0.0
        if sp and epx and spec.get(p["strategy_id"]) and spec[p["strategy_id"]].tf != "day":
            sign = 1 if p["side"] == "BUY" else -1
            raw = epx / (1 + sign * sl / 1e4)
            L["drift"].append(sign * (raw - sp) / sp * 1e4)

    out = []
    for sid in catalog:
        sp_ = spec[sid]
        g, c = sig.get(sid), cand.get(sid)
        row = {"sid": sid, "name": sp_.name, "family": sp_.family, "tf": sp_.tf, "kind": sp_.kind}
        if g:
            row["signals"] = {"n": g["n"], "per_session": round(g["n"] / len(sessions), 1),
                              "traded_pct": round(g["traded"] / g["n"] * 100, 1),
                              "buy_pct": round(g["buy"] / g["n"] * 100, 1),
                              "stop_bp_med": round(statistics.median(g["stop"]), 1) if g["stop"] else None,
                              "tgt_bp_med": round(statistics.median(g["tgt"]), 1) if g["tgt"] else None,
                              "rr_med": round(statistics.median(g["rr"]), 2) if g["rr"] else None,
                              "target_below_cost_pct": round(g["tiny"] / len(g["tgt"]) * 100, 1) if g["tgt"] else None,
                              "first_hour_pct": round(g["first_hour"] / g["n"] * 100, 1),
                              "prio_med": round(statistics.median(g["prio"]), 2), "prio_p90": round(pct(g["prio"], 0.9), 2),
                              "repeat_break_pct": round(g["rep"] / g["rep_n"] * 100, 1) if g["rep_n"] else None,
                              "consecutive_bar_repeat_pct": round(g.get("consec", 0) / g["n"] * 100, 1),
                              "by_hour": dict(sorted(g["by_hour"].items()))}
        if c and c["n"]:
            n = c["n"]
            row["every_trade"] = {
                "n": n, "raw_bp": round(c["raw"] / n, 2), "raw_t_trades": tstat(n, c["raw"], c["rss"]),
                # trades on one day share the market's move, so they are not independent: the
                # per-trade mean with a day-clustered standard error (cluster-robust t)
                "raw_t": cluster_t(c["days"], 1),
                "net_t_days": cluster_t(c["days"], 2),
                # the same edge with every DAY weighted equally (is it a few big days?)
                "raw_bp_day_weighted": round(statistics.fmean(v[1] / v[0] for v in c["days"].values()), 2),
                "days_traded": len(c["days"]),
                "slip_bp": round(c["slip"] / n, 2),
                "fee_bp": round(c["fee"] / n, 2), "net_bp": round(c["s"] / n, 2), "t": tstat(n, c["s"], c["ss"]),
                "win_pct": round(c["win"] / n * 100, 1), "direction_pct": round(c["dir"] / n * 100, 1),
                "payoff": round((c["wbp"] / c["nw"]) / (c["lbp"] / c["nl"]), 2) if c["nw"] and c["nl"] else None,
                "exit_pct": {k: round(v / n * 100, 1) for k, v in c["exit"].items()},
                "hold_min_med": statistics.median(c["hold"]),
                "dev": {"n": c["dev"][0], "net_bp": round(c["dev"][1] / c["dev"][0], 2) if c["dev"][0] else None,
                        "t": tstat(*c["dev"])},
                "last6m": {"n": c["hold6"][0], "net_bp": round(c["hold6"][1] / c["hold6"][0], 2) if c["hold6"][0] else None,
                           "t": tstat(*c["hold6"])},
                "cost_share_of_target_pct": (round((c["slip"] + c["fee"]) / n / statistics.median(g["tgt"]) * 100, 1)
                                             if g and g["tgt"] else None)}
            if sid in opt:
                row["every_trade"]["optimistic_orb_net_bp"] = round(opt[sid][1] / opt[sid][0], 2)
            row["every_trade"]["splits"] = {k: {"n": v[0], "raw_bp": round(v[1] / v[0], 2) if v[0] else None,
                                                "net_bp": round(v[2] / v[0], 2) if v[0] else None}
                                            for k, v in c.get("split", {}).items()}
        row["solo"] = book_stats(books["solo"].get(sid, []))
        row["tournament"] = book_stats(books["live"].get(sid, []))
        sk = {(r[0], r[1]) for r in books["solo"].get(sid, [])}
        lk = {(r[0], r[1]) for r in books["live"].get(sid, [])}
        row["interference"] = {"solo_only_trades": len(sk - lk), "tournament_only_trades": len(lk - sk),
                               "net_difference": round(row["tournament"].get("net", 0) - row["solo"].get("net", 0))}
        L = live.get(sid)
        if L and L["n"]:
            row["live_paper"] = {"trades": L["n"], "net": round(L["net"]), "win_pct": round(L["win"] / L["n"] * 100, 1),
                                 "entry_drift_bp_mean": round(statistics.fmean(L["drift"]), 2) if L["drift"] else None,
                                 "entry_drift_bp_med": round(statistics.median(L["drift"]), 2) if L["drift"] else None}
        gr = gate.get(sid) or {}
        row["gate"] = {"passed": gr.get("passed"), "dsr": gr.get("dsr"),
                       "failed": [k for k, v in (gr.get("checks") or {}).items() if v is False]}
        out.append(row)

    totals = {}
    for book in ("solo", "tournament"):
        totals[book] = {"net": sum(r[book].get("net", 0) for r in out), "trades": sum(r[book].get("trades", 0) for r in out),
                        "profitable_strategies": sum(1 for r in out if r[book].get("net", 0) > 0)}
    allc = [r["every_trade"] for r in out if "every_trade" in r]
    totals["every_trade"] = {"n": sum(x["n"] for x in allc),
                             "raw_bp": round(sum(x["raw_bp"] * x["n"] for x in allc) / sum(x["n"] for x in allc), 2),
                             "net_bp": round(sum(x["net_bp"] * x["n"] for x in allc) / sum(x["n"] for x in allc), 2),
                             "raw_positive_strategies": sum(1 for x in allc if x["raw_bp"] > 0),
                             "net_positive_strategies": sum(1 for x in allc if x["net_bp"] > 0)}
    res = {"sessions": len(sessions), "first": str(sessions[0]), "last": str(sessions[-1]), "years": round(years, 2),
           "replay": summ["meta"], "backtest_summary": {k: summ["summary"].get(k) for k in
                                                        ("sessions", "symbols", "coverage_median", "candidate_trades",
                                                         "taken_trades", "live_rules_skipped", "pbo", "passed")},
           "totals": totals, "strategies": out}
    chk = run / "checks.json"
    if chk.exists():
        res["checks"] = json.load(open(chk, encoding="utf-8"))
    json.dump(res, open(run / "tables.json", "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({"sessions": len(sessions), "totals": totals}, default=str))


if __name__ == "__main__":
    main()
