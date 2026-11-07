"""Run with the VWAP study's environment:  D:/NSE-Intraday-Research/env/Scripts/python.exe -I test_vwap_port.py
Feeds the study's own data (its Yahoo arrays and liquidity ranks) through vwap_run.py and compares every signal with the
study's saved trades over its last sessions. Same trades = the paper desk's VWAP glue is faithful to the study."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"D:\NSE-Intraday-Research\code")
sys.path.insert(0, r"D:\NSE-Intraday-Research\vwap")
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import vwap_engine as E  # noqa: E402
from lib_data import Market  # noqa: E402

import vwap_run  # noqa: E402


class FakePanel:
    def __init__(self, m, dates, stocks):
        self.ents = list(stocks)
        self.names = [stocks[e]["sym"] for e in self.ents]
        self.stocks, self.m, self.dates = stocks, m, dates
        self.days = [str(d.date()) for d in dates]
        self.day_keys = np.array([(d - pd.Timestamp("1970-01-01")).days for d in dates])
        self.live_day = None

    def rank_on(self, r, i):
        ent = self.ents[i]
        rk = self.m.rank.at[self.dates[r], ent] if ent in self.m.rank.columns else np.nan
        return float(rk) if rk == rk else None

    def matrix(self, i):
        return self.stocks[self.ents[i]]["arr"]


m = Market(start="2025-06-01", verbose=False)
dates, stocks, _ = E.load_data(m)
panel = FakePanel(m, dates, stocks)
days = set(panel.days[-15:])
out = vwap_run.run(panel, days)
OUT = os.path.join(E.OUT)
v0 = pd.read_parquet(os.path.join(OUT, "trades_V0.parquet"))
rows = {"A": v0[v0.setup == "A"], "B": v0[v0.setup == "B"]}
for ver in ("U1", "U2", "U3", "U4"):
    rows[ver] = pd.read_parquet(os.path.join(OUT, f"trades_{ver}.parquet"))
total_same = total_saved = total_paper = 0
for setup, t in rows.items():
    t = t[t.date.astype(str).str[:10].isin(days)]
    want = {(str(r.date)[:10], r.symbol, int(r.side)): (round(float(r.entry), 3), round(float(r.exit), 3), r.reason) for r in t.itertuples()}
    got = {(d["date"], d["sym"], d["side"]): (round(d["entry"], 3), round(d["exit"], 3), d["reason"]) for d in out[setup]}
    # the study drops trades whose size rounds to zero; the paper desk decides that when it sizes them
    same = sum(1 for k in want if got.get(k) == want[k])
    extra = [k for k in got if k not in want]
    miss = [k for k in want if k not in got]
    print(setup, "saved", len(want), "paper", len(got), "identical", same, "only paper", len(extra), "only saved", len(miss), extra[:3], miss[:3], flush=True)
    total_same += same; total_saved += len(want); total_paper += len(got)
print("TOTAL saved", total_saved, "paper", total_paper, "identical", total_same)
