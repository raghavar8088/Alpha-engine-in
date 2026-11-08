"""Writes frontend/app/premium-strategies/sel15Nifty50Data.ts and results/summary.json from the saved replay runs.

    python -I export_app_data.py [run folder]

The run folder holds replay.py's outputs: sel_n50_n50x1.json (NIFTY 50, 1x), sel_n50_n50x5.json (NIFTY 50, 5x) and
sel_n50_module.json (the rule's usual top-200 universe, 1x). Default: D:/intraday_ai_data/runs/mirror_1to1_20261107/
sel15_nifty50_20261108. The headline totals are asserted, so the page cannot drift from the runs.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:/intraday_ai_data/runs/mirror_1to1_20261107/sel15_nifty50_20261108")
IST = timezone(timedelta(hours=5, minutes=30))
SID = "iv2_orb_sel15"
WINDOWS = {"trailing": "Last month", "october": "October"}
VERSIONS = {"orig": "1:1 target", "base": "As registered (held to the close)"}


def load(name: str) -> dict:
    return json.loads((RUN / name).read_text(encoding="utf-8"))["rules"][SID]


x1, x5, mod = load("sel_n50_n50x1.json"), load("sel_n50_n50x5.json"), load("sel_n50_module.json")
meta = json.loads((RUN / "sel_n50_n50x1.json").read_text(encoding="utf-8"))
assert meta["args"]["universe"] == "nifty50" and meta["args"]["leverage"] == 1.0, meta["args"]
assert json.loads((RUN / "sel_n50_n50x5.json").read_text(encoding="utf-8"))["args"]["leverage"] == 5.0
assert json.loads((RUN / "sel_n50_module.json").read_text(encoding="utf-8"))["args"]["universe"] == "module"
spans = dict(w.split(":", 1) for w in meta["args"]["windows"].split(","))

rows = []
for w, wlabel in WINDOWS.items():
    first, last = spans[w].split(":")
    for v, vlabel in VERSIONS.items():
        for lev, run in ((1, x1), (5, x5)):
            s = run[v]["windows"][w]
            rows.append({"window": wlabel, "first": first, "last": last, "sessions": s["sessions"], "version": vlabel, "leverage": lev,
                         "trades": s["trades"], "winRate": s["win_pct"], "net": round(s["net"]), "retPct": round(s["ret_pct"], 2),
                         "pf": None if s["pf"] is None else round(s["pf"], 3), "maxDdPct": round(s["max_dd_pct"], 2),
                         "avg": round(s["avg"]) if s["avg"] is not None else None})


def row(w, v, lev):
    return next(r for r in rows if r["window"] == WINDOWS[w] and r["version"] == VERSIONS[v] and r["leverage"] == lev)


# the figures quoted to the owner on 8 Nov 2026
for (w, v, lev), net in {("trailing", "orig", 1): 221593, ("trailing", "orig", 5): 1074497, ("october", "orig", 1): 185242,
                         ("october", "orig", 5): 910060, ("trailing", "base", 1): 172854, ("trailing", "base", 5): 791384,
                         ("october", "base", 1): 128972, ("october", "base", 5): 587891}.items():
    assert row(w, v, lev)["net"] == net, (w, v, lev, row(w, v, lev)["net"], net)
assert row("trailing", "orig", 1)["trades"] == 40 and row("trailing", "orig", 1)["sessions"] == 22

# every trade of the last month, 1:1 target; the same trades at 5x (same signals, larger orders)
t1 = x1["orig"]["windows"]["trailing"]["trades_list"]
t5 = {(t[1], t[2]): t for t in x5["orig"]["windows"]["trailing"]["trades_list"]}
assert len(t1) == len(t5) and all((t[1], t[2]) in t5 for t in t1)
REASON = {"target": "Target", "stoploss": "Stop", "eod": "Close"}
trades = []
for t in sorted(t1, key=lambda t: (t[2], t[1])):
    d = datetime.fromtimestamp(t[2], IST)
    trades.append({"day": d.strftime("%Y-%m-%d"), "time": d.strftime("%H:%M"), "sym": t[1], "side": t[4], "entry": round(t[5], 2),
                   "exit": round(t[6], 2), "reason": REASON.get(t[11], t[11]), "net1x": round(t[10]), "net5x": round(t5[(t[1], t[2])][10])})
assert round(sum(t["net1x"] for t in trades)) == 221593 or abs(sum(t["net1x"] for t in trades) - 221593) <= len(trades)

m1, mb = mod["orig"]["windows"]["trailing"], mod["base"]["windows"]["trailing"]
compare = {"orig": {"trades": m1["trades"], "retPct": round(m1["ret_pct"], 2), "net": round(m1["net"])},
           "base": {"trades": mb["trades"], "retPct": round(mb["ret_pct"], 2), "net": round(mb["net"])}}
assert compare["orig"]["net"] == 139752 and compare["base"]["net"] == 244232, compare

RULES = [
    {"label": "Stocks", "text": "The 50 stocks of the NIFTY 50 (niftyindices.com list of 8 Nov 2026, after the September rebalance)."},
    {"label": "Pick at 09:30", "text": "The app's Scanner Board model ranks the 50 by expected move from 09:45 to 15:00, using each stock's ATR %, "
                                      "its opening gap, yesterday's range in ATRs and whether it reports results that day. The 5 highest are "
                                      "the candidates. The model is the live one: refitted every Saturday on earlier data only, on the "
                                      "Intraday Stocks universe (the top 200 by traded value)."},
    {"label": "Volume filter", "text": "The 09:15-09:30 candle traded at least 1.5 times the average of the same candle over the previous 14 sessions."},
    {"label": "Entry", "text": "A buy stop at the 09:15-09:30 high and a sell stop at its low, live from 09:30 to 14:30. The first one hit cancels the other."},
    {"label": "Stop", "text": "The opposite edge of the 15-minute range."},
    {"label": "Target", "text": "1R: as far from the fill as the stop. The tournament's registered rule has no target and holds to the close."},
    {"label": "Exit", "text": "Stop, target, or the square-off at 15:05 (stocks in the closing auction) or 15:10."},
    {"label": "Sizing", "text": "5 slots of Rs 10 lakh on a Rs 50 lakh book (1x). With intraday 5x leverage, 5 slots of Rs 50 lakh on the same Rs 50 lakh."},
    {"label": "Costs", "text": "Angel One's intraday charges, short-side STT included, and slippage measured from Angel's order book: 1.5-4.1 bp a "
                              "side for a Rs 10 lakh order by the stock's liquidity, more for a Rs 50 lakh order (scaled by the square root "
                              "of the size). A target is a limit order and pays no slippage."},
]
METHOD = [
    {"label": "Period", "text": "Last month = 6 Oct to 5 Nov 2026, 22 sessions. 6 Nov was not yet in the stored bars."},
    {"label": "Fills", "text": "5-minute candles (15-minute on 4-5 Nov). A candle that crosses both range edges counts as a stop-out; on the "
                               "entry candle only the stop can fill; a candle touching both stop and target counts as the stop."},
    {"label": "Results day", "text": "From NSE's board-meeting calendar: a meeting that day whose purpose names results."},
    {"label": "Checked", "text": "The same code on the rule's usual universe matches 27 of the 33 live tournament trades from 6 Oct, and run "
                                 "at 1x it reproduces the figures above exactly."},
    {"label": "Caution", "text": "One month and 40 trades: luck cannot be ruled out. Over two years on its usual universe the 1:1 version "
                                 "made +15.81% (t 1.36, short of what 108 tries would need), and the rule was chosen in a study that used "
                                 "that same period. Leverage multiplies losing months the same way."},
]

data = {"generated": datetime.now(IST).strftime("%Y-%m-%d"), "id": "IS-01", "name": "Selected ORB 15-min, 1:1, NIFTY 50 stocks",
        "source": "The app's Intraday Stocks tournament (rule iv2_orb_sel15), limited to the NIFTY 50, with a 1R target",
        "verdict": "Needs more evidence", "rows": rows, "compare": compare, "trades": trades, "rules": RULES, "method": METHOD}
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "summary.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
head = """// GENERATED by backend/research/sel15_nifty50_2026_11/export_app_data.py - do not edit by hand.
// Selected ORB 15-min with a 1R target on the NIFTY 50 stocks: its rules and its last-month backtest at 1x and 5x.

export type SelRule = { label: string; text: string };
export type SelRow = { window: string; first: string; last: string; sessions: number; version: string; leverage: number; trades: number;
  winRate: number; net: number; retPct: number; pf: number | null; maxDdPct: number; avg: number | null };
export type SelTrade = { day: string; time: string; sym: string; side: string; entry: number; exit: number; reason: string;
  net1x: number; net5x: number };
export type SelCompare = { trades: number; retPct: number; net: number };
export type SelStrategy = { generated: string; id: string; name: string; source: string; verdict: string; rows: SelRow[];
  compare: { orig: SelCompare; base: SelCompare }; trades: SelTrade[]; rules: SelRule[]; method: SelRule[] };

export const SEL15_N50: SelStrategy = """
out = ROOT / "frontend" / "app" / "premium-strategies" / "sel15Nifty50Data.ts"
out.write_text(head + json.dumps(data, indent=1, ensure_ascii=False) + ";\n", encoding="utf-8", newline="\n")
print("rows", len(rows), "trades", len(trades), "->", out)
