"""NIFTY 50 ATM same-week option opening-range breakout: the backtest, BUYING and its mirror, SELLING.

    python -I backend/research/nifty_options_orb_2026_10/nopt_run.py          (NOPT_CLOCK=flat for the first model)

SIGNALS: the NIFTYBEES study's rules (../niftybees_orb_2026_10/orb_engine.py) on the NIFTY 50 index, the
options' underlying. Opening range = high and low of NIFTY's 09:15-09:29 minutes. From 09:30 the first
move above the range high trades the ATM CALL, the first move below the low the ATM PUT; one trade a
day, no re-entry, no reversal, no entry from 15:00. The stop is the other side of the range and the target
rr x the distance from the entry level, both on the index (touch); anything open is closed at 15:15. The
index is walked minute by minute (the worse order inside a minute), so every fill has its minute.
BUY: the option is bought at the breakout and sold at the exit. SELL (the owner's "do the opposite"):
the same option is SOLD at the same moment and bought back at the same exits.
CONTRACT: the nearest NIFTY weekly expiry on or after the trade day (the expiry day itself included,
i.e. 0DTE), the strike nearest NIFTY at entry (50 apart), one lot of today's 65 units.
PRICES: nopt_price (previous session's real NSE smile for that contract, India VIX pass-through); every
fill pays half the spread (0.15% of the premium) and one tick: bought above the mid, sold below it.
CHARGES: Angel One's option charges at today's rates, STT on whichever leg sells.
CAPITAL: a buyer risks the premium; a seller blocks margin (the app's SPAN-lite engine plus the expiry-day
2% ELM). Drawdown and monthly returns are on a Rs2,00,000 account, no compounding.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402
from nopt_price import Pricer  # noqa: E402
from orb_engine import Config, Day, Sim  # noqa: E402
from orb_run import drawdown, inr  # noqa: E402

START, END = date(2021, 10, 25), date(2026, 10, 23)
ACCOUNT = 200_000.0
RATIOS = (2.0, 3.0, 4.0, 5.0, 6.0)
TAG = "" if C.CLOCK == "u" else f"_{C.CLOCK}"
INDEX_CFG = Config(name="nifty_index", entry="stop", max_trades=1, reverse=False, first_entry_min=15, last_entry_min=345,
                   exit_min=360, tick=1, slip_bp=0.0, target_fill="touch", intrabar="worst", costs=False, bars=1)


def load_days() -> list[Day]:
    z = np.load(C.DATA / "minutes.npz")
    out = []
    for d, o, h, l, c in zip(z["days"], z["o"], z["h"], z["l"], z["c"]):
        dd = date.fromisoformat(str(d))
        if not (START <= dd <= END):
            continue
        P = lambda a: np.rint(a * 100).astype(np.int64)  # noqa: E731
        o, h, l, c = P(o), P(h), P(l), P(c)
        out.append(Day(str(d), o, h, l, c, np.arange(375), 1, int(h[:15].max()), int(l[:15].min())))
    return out


def index_trades(days: list[Day], rr: float) -> list:
    sim = Sim(replace(INDEX_CFG, rr=rr))
    trades = []
    for day in days:
        t, _ = sim.run_day(day)
        trades.extend(t)
    return trades


class Contracts:
    """Which contract a trade uses, from what NSE listed at the previous session."""

    def __init__(self, px: Pricer):
        with gzip.open(C.DATA / "listing.json.gz", "rt") as f:
            raw = json.load(f)
        self.listing = {int(k): {int(e): v for e, v in s.items()} for k, s in raw.items()}
        self.lk = sorted(self.listing)
        self.px = px

    def pick(self, k: int, S: float, weeks_out: int = 0):
        from bisect import bisect_left
        i = bisect_left(self.lk, k) - 1
        if i < 0:
            return None
        lst = self.listing[self.lk[i]]
        exps = sorted(e for e in lst if e >= k)
        if len(exps) <= weeks_out:
            return None
        ek = exps[weeks_out]
        strikes = lst[ek]
        K = round(S / C.STEP) * C.STEP
        if K not in strikes:
            K = min(strikes, key=lambda x: abs(x - S))
        kp = self.px.anchor(k, ek)
        return (ek, float(K), kp) if kp is not None else None


def hm(minute_after_open: int) -> str:
    t = C.OPEN_MIN + minute_after_open
    return f"{t // 60:02d}:{t % 60:02d}"


def price_trades(trades: list, px: Pricer, cons: Contracts, sell: bool = False, weeks_out: int = 0,
                 half_spread: float | None = None, skip_expiry_day: bool = False) -> tuple[list[dict], Counter]:
    hs_saved = C.HALF_SPREAD
    if half_spread is not None:
        C.HALF_SPREAD = half_spread
    out, skipped = [], Counter()
    for t in trades:
        k = C.dk(date.fromisoformat(t.date))
        S_in, S_out = t.entry_fill / 100.0, t.exit_fill / 100.0
        pick = cons.pick(k, S_in, weeks_out)
        if pick is None:
            skipped["no contract or no previous-session surface"] += 1
            continue
        ek, K, kp = pick
        if skip_expiry_day and ek == k:
            continue
        call = t.side > 0
        e_in = C.at(k, C.OPEN_MIN + t.entry_bar) + 30
        e_out = C.at(k, C.OPEN_MIN + 360) if t.exit_reason == "eod" else C.at(k, C.OPEN_MIN + t.exit_bar) + 30
        m_in, m_out = px.premium(e_in, S_in, K, call, ek, kp), px.premium(e_out, S_out, K, call, ek, kp)
        if m_in < 1.0:
            skipped["premium under Rs1"] += 1
            continue
        if sell:
            f_in, f_out = C.sell_fill(m_in), C.buy_fill(m_out)
            ch = C.charges(f_in, f_out, side="SELL")
            gross = (f_in - f_out) * C.LOT
            before = (m_in - m_out) * C.LOT
            iv = px.vol(e_in, S_in, K, ek, kp)
            capital = C.short_margin(S_in, K, call, m_in, iv, max(C.T_cal(e_in, ek), 1e-5), ek == k)
        else:
            f_in, f_out = C.buy_fill(m_in), C.sell_fill(m_out)
            ch = C.charges(f_in, f_out, side="BUY")
            gross = (f_out - f_in) * C.LOT
            before = (m_out - m_in) * C.LOT
            capital = f_in * C.LOT
        out.append({"date": t.date, "position": "SELL" if sell else "BUY", "option": "CALL" if call else "PUT",
                    "entry_time": hm(t.entry_bar), "exit_time": "15:15" if t.exit_reason == "eod" else hm(t.exit_bar),
                    "exit_reason": t.exit_reason, "nifty_in": S_in, "nifty_out": S_out, "or_stop": t.stop / 100.0,
                    "nifty_target": t.target / 100.0, "expiry": str(C.kdate(ek)), "days_to_expiry": ek - k,
                    "sessions_to_expiry": C.trading_sessions_between(k, ek) - 1, "strike": K, "anchor": str(C.kdate(kp)),
                    "mid_in": round(m_in, 2), "mid_out": round(m_out, 2), "fill_in": round(f_in, 2), "fill_out": round(f_out, 2),
                    "premium": round(f_in, 2), "capital": round(capital, 2),
                    "before_costs": round(before, 2), "spread_slippage": round(before - gross, 2),
                    "charges": round(ch, 2), "gross": round(gross, 2), "net": round(gross - ch, 2),
                    "ret_on_premium": round((gross - ch) / (f_in * C.LOT), 4),
                    "index_points": round((t.exit_fill - t.entry_fill) * t.side / 100.0, 2)})
    C.HALF_SPREAD = hs_saved
    return out, skipped


def monthly(tr: list[dict], sessions: list[str], account: float = ACCOUNT) -> dict:
    """Per calendar month: trades, capital (premium spent by a buyer; margin blocked by a seller), net."""
    months = sorted({d[:7] for d in sessions})
    m = {k: {"trades": 0, "capital_sum": 0.0, "capital_max": 0.0, "net": 0.0} for k in months}
    for t in tr:
        x = m[t["date"][:7]]
        x["trades"] += 1
        x["capital_sum"] += t["capital"]
        x["capital_max"] = max(x["capital_max"], t["capital"])
        x["net"] += t["net"]
    nets = np.array([m[k]["net"] for k in months])
    traded = [k for k in months if m[k]["trades"]]
    return {"months": len(months), "trades_per_month": float(np.mean([m[k]["trades"] for k in months])),
            "capital_per_trade": float(np.mean([t["capital"] for t in tr])) if tr else 0.0,
            "capital_sum_per_month": float(np.mean([m[k]["capital_sum"] for k in months])),
            "largest_capital_in_a_month": float(np.mean([m[k]["capital_max"] for k in traded])) if traded else 0.0,
            "net_per_month": float(nets.mean()), "median_month": float(np.median(nets)),
            "return_pct_per_month_on_account": float(nets.mean() / account * 100),
            "months_positive": int((nets > 0).sum()), "best_month": float(nets.max()), "worst_month": float(nets.min()),
            "by_month": {k: {kk: round(v, 2) if isinstance(v, float) else v for kk, v in m[k].items()} for k in months}}


def stats(tr: list[dict], sessions: list[str], account: float = ACCOUNT) -> dict:
    if not tr:
        return {"trades": 0}
    net = np.array([t["net"] for t in tr])
    win = net > 0
    losses = -net[net < 0].sum()
    daily = defaultdict(float)
    for t in tr:
        daily[t["date"]] += t["net"]
    pnl = np.array([daily.get(d, 0.0) for d in sessions])
    dd = drawdown(sessions, pnl, account)
    eq = account + np.cumsum(pnl)
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    yrs = (np.datetime64(sessions[-1]) - np.datetime64(sessions[0])).astype(int) / 365.25
    ex = Counter(t["exit_reason"] for t in tr)
    by_reason = {r: {"trades": n, "avg_net": float(np.mean([t["net"] for t in tr if t["exit_reason"] == r])),
                     "win_rate": float(np.mean([t["net"] > 0 for t in tr if t["exit_reason"] == r]) * 100)} for r, n in ex.items()}
    by_side = {}
    for s in ("CALL", "PUT"):
        sub = [t for t in tr if t["option"] == s]
        if sub:
            by_side[s] = {"trades": len(sub), "win_rate": float(np.mean([t["net"] > 0 for t in sub]) * 100),
                          "net": float(sum(t["net"] for t in sub))}
    by_dte = {}
    for lab, lo, hi in (("expiry day (0DTE)", 0, 0), ("1 session left", 1, 1), ("2-4 sessions left", 2, 4), ("5+ sessions left", 5, 99)):
        sub = [t for t in tr if lo <= t["sessions_to_expiry"] <= hi]
        if sub:
            by_dte[lab] = {"trades": len(sub), "win_rate": float(np.mean([t["net"] > 0 for t in sub]) * 100),
                           "net": float(sum(t["net"] for t in sub)), "avg_net": float(np.mean([t["net"] for t in sub])),
                           "before_costs": float(sum(t["before_costs"] for t in sub)),
                           "avg_premium": float(np.mean([t["premium"] for t in sub])),
                           "avg_capital": float(np.mean([t["capital"] for t in sub])),
                           "avg_ret_on_premium_pct": float(np.mean([t["ret_on_premium"] for t in sub]) * 100)}
    return {
        "trades": len(tr), "sessions": len(sessions), "wins": int(win.sum()), "win_rate": float(win.mean() * 100),
        "before_costs": float(sum(t["before_costs"] for t in tr)), "spread_slippage": float(sum(t["spread_slippage"] for t in tr)),
        "charges": float(sum(t["charges"] for t in tr)), "net_pnl": float(net.sum()),
        "return_pct_of_account": float(net.sum() / account * 100), "annual_return_pct": float(net.sum() / account * 100 / yrs),
        "profit_factor": float(net[net > 0].sum() / losses) if losses > 0 else math.inf,
        "avg_trade": float(net.mean()), "avg_win": float(net[win].mean()) if win.any() else 0.0,
        "avg_loss": float(net[~win].mean()) if (~win).any() else 0.0, "t_stat": float(net.mean() / sd * math.sqrt(len(net))) if sd > 0 else 0.0,
        "avg_premium": float(np.mean([t["premium"] for t in tr])), "avg_capital": float(np.mean([t["capital"] for t in tr])),
        "max_capital": float(max(t["capital"] for t in tr)),
        "avg_ret_on_premium_pct": float(np.mean([t["ret_on_premium"] for t in tr]) * 100),
        "max_win": float(net.max()), "max_loss": float(net.min()),
        "exit_reasons": by_reason, "by_option": by_side, "by_days_to_expiry": by_dte,
        "lowest_equity": float(eq.min()), "account_wiped_out_on": next((d for d, e in zip(sessions, eq) if e <= 0), None), **dd}


def yearly(tr: list[dict], sessions: list[str]) -> list[dict]:
    rows = []
    for y in sorted({d[:4] for d in sessions}):
        ss = [d for d in sessions if d.startswith(y)]
        tt = [t for t in tr if t["date"].startswith(y)]
        s = stats(tt, ss) if tt else {"trades": 0}
        ex = s.get("exit_reasons", {})
        rows.append({"year": y, "from": ss[0], "to": ss[-1], "sessions": len(ss), "trades": s["trades"],
                     "win_rate": s.get("win_rate", 0.0), "before_costs": s.get("before_costs", 0.0),
                     "costs": s.get("spread_slippage", 0.0) + s.get("charges", 0.0), "net_pnl": s.get("net_pnl", 0.0),
                     "return_pct": s.get("return_pct_of_account", 0.0), "profit_factor": s.get("profit_factor", 0.0),
                     "max_dd": s.get("max_dd", 0.0), "targets": ex.get("target", {}).get("trades", 0),
                     "stops": ex.get("stop", {}).get("trades", 0), "eod": ex.get("eod", {}).get("trades", 0)})
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def real_check(tr: list[dict]) -> dict:
    """Trades inside the recorded-chain window, re-priced at the REAL mid quotes of their entry and exit minutes."""
    from nopt_intraday_check import load_chain
    out = []
    for t in tr:
        p = C.DATA / "optchain" / f"{t['date']}.jsonl.gz"
        if not p.exists():
            continue
        ch = load_chain(p)
        mm = lambda s: int(s[:2]) * 60 + int(s[3:])  # noqa: E731
        m_in, m_out = mm(t["entry_time"]), mm(t["exit_time"])
        key = (t["expiry"], float(t["strike"]), "C" if t["option"] == "CALL" else "P")
        a = ch.get(m_in) or ch.get(m_in + 1)
        b = ch.get(m_out) or ch.get(m_out - 1)
        base = {k: t[k] for k in ("date", "position", "option", "strike", "expiry", "entry_time", "exit_time", "exit_reason")}
        if not a or not b or key not in a[2] or key not in b[2]:
            out.append({**base, "real_in": None})
            continue
        r_in, r_out = a[2][key], b[2][key]
        sgn = -1 if t["position"] == "SELL" else 1
        out.append({**base, "model_in": t["mid_in"], "real_in": round(r_in, 2), "model_out": t["mid_out"], "real_out": round(r_out, 2),
                    "model_before_costs": t["before_costs"], "real_before_costs": round(sgn * (r_out - r_in) * C.LOT, 2)})
    ok = [r for r in out if r.get("real_in") is not None]
    return {"trades": out, "n_priced": len(ok),
            "model_sum": float(sum(r["model_before_costs"] for r in ok)), "real_sum": float(sum(r["real_before_costs"] for r in ok))}


def run_side(it_by_rr: dict, px: Pricer, cons: Contracts, sessions: list[str], sell: bool) -> dict:
    side = "sell" if sell else "buy"
    out = {}
    for rr, it in it_by_rr.items():
        tr, skipped = price_trades(it, px, cons, sell=sell)
        name = f"rr_1_{int(rr)}"
        s = stats(tr, sessions)
        out[name] = {"rr": rr, "index_trades": len(it), "skipped": dict(skipped), "stats": s, "yearly": yearly(tr, sessions),
                     "monthly": monthly(tr, sessions)}
        write_csv(C.RES / f"trades_{side}_{name}{TAG}.csv", tr)
        if rr == 2.0:
            out[name]["real_price_check"] = real_check(tr)
        ex, mo = s["exit_reasons"], out[name]["monthly"]
        print(f"{side.upper()} 1:{int(rr)}  trades {s['trades']}  win {s['win_rate']:.1f}%  net {inr(s['net_pnl'])}  PF {s['profit_factor']:.2f}  "
              f"maxDD {inr(s['max_dd'])}  before costs {inr(s['before_costs'])}  costs {inr(s['spread_slippage'] + s['charges'])}  "
              f"capital/trade {inr(s['avg_capital'])}  per month {inr(mo['net_per_month'])} ({mo['return_pct_per_month_on_account']:+.2f}% of 2L, "
              f"{mo['months_positive']}/{mo['months']} up)  t {s['t_stat']:+.2f}  T/S/E {ex.get('target', {}).get('trades', 0)}/"
              f"{ex.get('stop', {}).get('trades', 0)}/{ex.get('eod', {}).get('trades', 0)}  wiped {s['account_wiped_out_on']}", flush=True)
        if rr == 2.0:
            for lab, v in s["by_days_to_expiry"].items():
                print(f"     {lab:20} trades {v['trades']:4}  win {v['win_rate']:5.1f}%  net {inr(v['net']):>10}  before costs {inr(v['before_costs']):>10}  "
                      f"avg {inr(v['avg_net'])}  capital {inr(v['avg_capital'])}")
            for y in out[name]["yearly"]:
                print(f"     {y['year']} trades {y['trades']:3}  win {y['win_rate']:5.1f}%  net {inr(y['net_pnl']):>10}  PF {y['profit_factor']:.2f}")
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C.set_calendar()
    px = Pricer()
    cons = Contracts(px)
    days = load_days()
    sessions = [d.date for d in days]
    out = {"meta": {"window": [START.isoformat(), END.isoformat()], "sessions": len(sessions), "lot": C.LOT,
                    "account": ACCOUNT, "half_spread": C.HALF_SPREAD, "slip_ticks": C.SLIP_TICKS,
                    "beta": px.beta, "smile": px.smile, "clock": C.CLOCK}}
    it_by_rr = {rr: index_trades(days, rr) for rr in RATIOS}
    print(f"clock={C.CLOCK} beta={px.beta} smile={px.smile}", flush=True)
    out["buy"] = run_side(it_by_rr, px, cons, sessions, sell=False)
    out["sell"] = run_side(it_by_rr, px, cons, sessions, sell=True)
    # sensitivity at 1:2 (same index trades, re-priced)
    it2 = it_by_rr[2.0]
    sens = {"buy": {}, "sell": {}}
    alt_beta = 0.4 if abs(px.beta - 0.4) > 1e-9 else 1.0
    other_smile = "strike" if px.smile == "moneyness" else "moneyness"
    for lab, kw in ((f"VIX pass-through off (beta 0; chosen {px.beta:g})", {"beta": 0.0}),
                    (f"VIX pass-through beta {alt_beta:g} (chosen {px.beta:g})", {"beta": alt_beta}),
                    (f"smile rule '{other_smile}' (chosen '{px.smile}')", {"smile": other_smile})):
        p2 = Pricer(**kw)
        c2 = Contracts(p2)
        for side, sell in (("buy", False), ("sell", True)):
            tr, _ = price_trades(it2, p2, c2, sell=sell)
            sens[side][lab] = stats(tr, sessions)
    for side, sell in (("buy", False), ("sell", True)):
        tr, _ = price_trades(it2, px, cons, sell=sell, half_spread=0.003)
        sens[side]["double the spread (0.30% a side)"] = stats(tr, sessions)
        tr, _ = price_trades(it2, px, cons, sell=sell, weeks_out=1)
        sens[side]["next week's expiry instead"] = stats(tr, sessions)
        tr, _ = price_trades(it2, px, cons, sell=sell, skip_expiry_day=True)
        sens[side]["no trades on the contract's expiry day"] = stats(tr, sessions)
    out["sensitivity_rr_1_2"] = sens
    for side in ("buy", "sell"):
        for lab, s in sens[side].items():
            print(f"  [{side} 1:2] {lab:44} trades {s['trades']:4}  net {inr(s['net_pnl']):>11}  PF {s['profit_factor']:.2f}  before costs {inr(s['before_costs'])}")
    for side in ("buy", "sell"):
        rc = out[side]["rr_1_2"]["real_price_check"]
        print(f"real-price check {side}: {rc['n_priced']} trades, model {inr(rc['model_sum'])} vs real {inr(rc['real_sum'])} before costs")
    with open(C.RES / f"summary{TAG}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
