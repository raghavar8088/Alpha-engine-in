"""Historical backtests of the 20-channel strategies through the exact code the paper desk runs (yc_run.run on the
11-channel study's fill engine): orders fill on the next row at the bid / ask, with slippage and fees from each market's
cost model (yt_markets.COSTS: NSE futures and equity charges, the bitcoin and gold spreads), and the strategy's own
exits and forced exits. Pools of stocks keep the desk's book rule (catalog.MONEY: at most 4 positions open, taken in
time order, ties to the more liquid stock).

    python -I zc_backtest.py [SID,SID,...]      -> results/backtest.json (and results/BACKTEST.md via zc_report.py)

Windows, fixed before any result was seen (nothing is tuned on them): the last 500 sessions of Nifty and Bank Nifty
minutes, 520 sessions of gold, 730 days of bitcoin, all the ether the research store has (Aug-Oct 2026), 520 sessions
of the NSE 5-minute pool, NSE daily stocks from 2019 and daily Nifty from 2016. Results are per trade in R (the
result over the risk taken at entry), net of costs; "% at 1% risk" adds them up at 1% of equity a trade (no
compounding). A positive number here is not evidence of an edge: these rules were written from videos, the windows
include the periods the videos were made in, and paper trading is their first out-of-sample test."""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
YC1 = HERE.parent / "youtube_channels11_2026_11"
for _p in (HERE, YC1):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import yc_markets as MK  # noqa: E402
import yc_run as R  # noqa: E402
import zc_strategies as ZS  # noqa: E402

DAYS = {"NIFTY": 500, "BANKNIFTY": 500, "XAUUSD": 520, "BTCUSD": 730}
POOL_DAYS = 520
NSED_FROM = "2019-01-01"
POOL_MAX_OPEN = {"NSE5": 4, "NSE15": 4, "NSED": 10}
POOL_RISK = {"NSE5": 0.25, "NSE15": 0.25, "NSED": 1.0}       # % of equity a position risks on the desk


def stats(trades, risk_pct: float = 1.0) -> dict:
    r = np.array([t.r_net for t in trades], float)
    if not len(r):
        return {"n": 0}
    g = np.array([t.r_gross for t in trades], float)
    cum = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0.0, cum])[1:] - cum).max())
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    years = defaultdict(list)
    for t in trades:
        years[t.date[:4]].append(t.r_net)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.reason] += 1
    half = len(r) // 2
    return {
        "n": int(len(r)), "win_rate": round(float((r > 0).mean()), 3), "mean_r": round(float(r.mean()), 3),
        "mean_r_gross": round(float(g.mean()), 3), "cost_r": round(float((g - r).mean()), 3),
        "total_r": round(float(r.sum()), 1), "pf": round(float(wins / losses), 2) if losses > 0 else None,
        "max_dd_r": round(dd, 1), "pct": round(float(r.sum()) * risk_pct, 1), "risk_pct": risk_pct,
        "t_stat": round(float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), 2) if len(r) > 2 and r.std() > 0 else None,
        "first_half_mean_r": round(float(r[:half].mean()), 3) if half else None,
        "second_half_mean_r": round(float(r[half:].mean()), 3) if half else None,
        "by_year": {y: [len(v), round(float(np.sum(v)), 1)] for y, v in sorted(years.items())}, "exits": dict(reasons),
        "first": trades[0].date, "last": trades[-1].date,
    }


def load(markets: set) -> dict:
    data = {}
    for nm in markets & set(DAYS):
        data[nm] = MK.window(nm, DAYS[nm])
    if "NSED" in markets:
        data["NSED"] = [m for m in MK.nsed() if str(m.date[-1]) >= NSED_FROM]
    if markets & {"NSE5", "NSE15"}:
        names = sorted(p.stem for p in Path("D:/intraday_ai_data/intraday/5m").glob("*.ibar"))
        data["NSE5"] = data["NSE15"] = MK.nse_pool(names, POOL_DAYS)
    if "NIFTY_D" in markets:
        data["NIFTY_D"] = MK.full("NIFTY_D")
    if "ETHUSD" in markets:
        data["ETHUSD"] = MK.full("ETHUSD")
    if "BANKNIFTY" not in data and any("BANKNIFTY" in s.needs for s in ZS.NEW.values()):
        data["BANKNIFTY"] = MK.window("BANKNIFTY", DAYS["BANKNIFTY"])
    return data


def _liquidity(ms) -> dict:
    """A fixed liquidity order for the pool (median traded value a row over the window): the desk's tie-break."""
    out = {}
    for m in ms:
        v = np.asarray(m.vol, float) * np.asarray(m.c, float)
        out[m.name] = float(np.median(v)) if len(v) else 0.0
    order = sorted(out, key=lambda k: -out[k])
    return {k: i for i, k in enumerate(order)}


def take_slots(items, max_open):
    """The desk's pool rule (runner.take_slots): time order, ties to the more liquid; at most max_open open at once."""
    items = sorted(items, key=lambda x: (x[0], x[1], x[2]))
    taken, busy = [], []
    for entry_t, rank, sym, exit_t, t in items:
        busy = [x for x in busy if x >= entry_t]
        if len(busy) < max_open:
            taken.append(t)
            busy.append(exit_t)
    return taken


def run_one(sid: str, data: dict) -> dict:
    st = ZS.NEW[sid]
    out = {}
    for market in st.markets:
        ms = data.get(market)
        if ms is None:
            out[market] = {"error": "no research data"}
            continue
        pool = isinstance(ms, list)
        cx = R.contexts(set(st.needs), nifty=data.get("NIFTY"), nsed=data.get("NSED"), pool=ms if pool else None)
        p = {"ctx": cx} if cx else {}
        other = data.get("BANKNIFTY") if "BANKNIFTY" in st.needs else None
        trades = []
        if pool:
            rank = _liquidity(ms)
            items = []
            for m in ms:
                tr, _, _ = R.run(sid, market, m, {}, p, None, risk_pct=0.01)
                for t in tr:
                    items.append((int(m.t[t.entry_k]), rank.get(m.name, 10**6), m.name, int(m.t[t.exit_k]), t))
            trades = take_slots(items, POOL_MAX_OPEN.get(market, 4))
            raw = len(items)
        else:
            tr, _, _ = R.run(sid, market, ms, {}, p, other, risk_pct=0.01)
            trades = tr
            raw = len(tr)
        trades.sort(key=lambda t: (t.date, t.entry_k))
        s = stats(trades, POOL_RISK.get(market, 1.0))
        s["window"] = [str(ms[0].date[0]) if pool else str(ms.date[0]), str(ms[0].date[-1]) if pool else str(ms.date[-1])]
        if pool:
            s["candidates"] = raw
            s["stocks"] = len(ms)
        out[market] = s
    return out


def main():
    only = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
    sids = [s for s in ZS.NEW if (only is None or s in only)]
    markets = {m for s in sids for m in ZS.NEW[s].markets}
    t0 = time.time()
    data = load(markets)
    print("data loaded", round(time.time() - t0), "s", {k: (len(v) if isinstance(v, list) else len(v.t)) for k, v in data.items()},
          flush=True)
    path = HERE / "results" / "backtest.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    for sid in sids:
        t1 = time.time()
        try:
            res[sid] = run_one(sid, data)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            res[sid] = {"error": repr(exc)[:300]}
        brief = {k: ({kk: v.get(kk) for kk in ("n", "win_rate", "mean_r", "total_r", "pf")} if isinstance(v, dict) else v)
                 for k, v in res[sid].items()}
        print(sid, json.dumps(brief), round(time.time() - t1, 1), "s", flush=True)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
