"""The Gold Desk strategy assessment, generated rather than transcribed.

    python backend/research/gold_2026_10/gd_strategy_table.py   (after gd_analyse.py, gd_benchmark.py)

Reads the replay's trade files (data/analysis/<DATASET>_trades.pkl) and writes
gd_strategy_table_out.md:

  1. per TEMPLATE (46 rows), split the way the evidence splits:
       below 4h   pooled over 1m..1h — Delta-like (Binance PAXG 2025-26) and MCX (GOLDM store)
       4h         Binance PAXG, Delta's own XAUT+PAXG 2026, COMEX in MCX hours 2024-26
       1d         26 years of COMEX daily: net bp, and against HOLDING gold (alpha t,
                  held-out Sharpe vs gold's) from gd_benchmark.py
     and a decision by the rule below;
  2. every STRATEGY (353 rows): trades, gross and net bp, t, halves, per venue, with the
     mechanical per-strategy rule.

THE TEMPLATE RULE (mechanical):
  below 4h  DISABLE if pooled net <= 0 on BOTH venues (it is, for every template).
  4h        H1 for the nine breakout / trend-structure templates when net > 0 on the longest 24/7
            history — admitted only as part of the pooled forward test, never on its own;
            "4h+ (regime, not H1)" for any other template positive there; else DISABLE.
  1d        DISABLE unless it beats holding gold on both of the Lab's tests (held-out Sharpe
            above gold's AND alpha t >= 2) — then RESEARCH ONLY, because the Lab already ran
            the same template as a five-commodity basket.
  Delta     gap_fade / opening_range: STRUCTURAL (no session on a 24/7 market).

THE PER-STRATEGY RULE (appendix): INSUFFICIENT (< 30 trades) · DISABLE-RAW (gross <= 0) ·
DISABLE-COST (gross > 0, net <= 0) · RESEARCH ONLY (net > 0, not robust) · CANDIDATE (both
halves > 0, net t >= 3, DSR >= 0.95, same sign on the confirming history).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AN = HERE / "data" / "analysis"
ROOT = HERE.parents[2]
for p in (ROOT / "backend", ROOT / "strategy-service", ROOT / "shared"):
    sys.path.insert(0, str(p))
TF_ORDER = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]
SUB4H = ["1m", "5m", "15m", "30m", "45m", "1h"]
SESSION_TEMPLATES = {"gap_fade", "opening_range"}
# The plan's H1: the breakout / trend-structure family, the one 4h result with the same sign on
# every history that has it. Other templates positive at 4h are labelled, not admitted.
H1_TEMPLATES = {"donchian_fast", "donchian_slow", "keltner_break", "prior_session_break", "round_number_break",
                "pivot_break", "hh_hl_shift", "atr_thrust", "ema_ribbon"}


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def trades(ds: str) -> pd.DataFrame:
    return pd.read_pickle(AN / f"{ds}_trades.pkl")


def cell(t: pd.DataFrame, col: str = "net_actual") -> tuple[int, float, float]:
    return (len(t), float(t[col].mean()) if len(t) else float("nan"), tstat(t[col]) if len(t) else float("nan"))


def f(v, d=1) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:+.{d}f}"


def main() -> None:
    from app.services.commodity_patterns import COMMODITY_CATALOG, TEMPLATES

    B, AX, AP, C, D, E = (trades(x) for x in ("B_PAXG", "A_XAUT", "A_PAXG", "C_GC", "D_GOLDM", "E_GCD"))
    A = pd.concat([AX, AP], ignore_index=True)
    vs = pd.read_csv(AN / "E_GCD_vs_always_long.csv").set_index("template")

    rows = []
    for tmpl, (family, label, *_rest) in TEMPLATES.items():
        bs = B[(B.template == tmpl) & B.tf.isin(SUB4H)]
        ds_ = D[(D.template == tmpl) & D.tf.isin(SUB4H)]
        b4, a4, c4 = (x[(x.template == tmpl) & (x.tf == "4h")] for x in (B, A, C))
        e1 = E[E.template == tmpl]
        r = {"template": tmpl, "label": label, "family": family}
        r["sub_d_n"], r["sub_d_g"], _ = cell(bs, "gross")
        _, r["sub_d_net"], r["sub_d_t"] = cell(bs)
        r["sub_m_n"], r["sub_m_g"], _ = cell(ds_, "gross")
        _, r["sub_m_net"], r["sub_m_t"] = cell(ds_)
        r["b4_n"], r["b4_net"], r["b4_t"] = cell(b4)
        r["a4_n"], r["a4_net"], _ = cell(a4)
        r["c4_n"], r["c4_net"], _ = cell(c4)
        r["e_n"], r["e_net"], _ = cell(e1)
        if tmpl in vs.index:
            r["alpha_t"], r["sr_ho"], r["sr_gold"] = vs.loc[tmpl, "alpha_t"], vs.loc[tmpl, "sr_heldout"], vs.loc[tmpl, "sr_gold_heldout"]
        else:
            r["alpha_t"] = r["sr_ho"] = r["sr_gold"] = float("nan")
        pos = [(n, t) for n, net, t in ((r["sub_d_n"], r["sub_d_net"], r["sub_d_t"]),
                                         (r["sub_m_n"], r["sub_m_net"], r["sub_m_t"])) if net > 0]
        if not pos:
            sub = "DISABLE"
        elif all(n < 100 or not (t >= 2) for n, t in pos):
            sub = "DISABLE (+ on < 100 trades or t < 2)"
        else:
            sub = "RESEARCH ONLY"
        if tmpl in SESSION_TEMPLATES:
            four = "REMOVE on Delta; DISABLE on MCX"
        elif r["b4_n"] < 10:
            four = "INSUFFICIENT"
        elif r["b4_net"] <= 0:
            four = "DISABLE"
        elif tmpl in H1_TEMPLATES:
            four = "H1"
        else:
            four = "4h+ (regime, not H1)"
        if r["e_n"] < 20:
            day = "INSUFFICIENT"
        elif np.isfinite(r["alpha_t"]) and r["alpha_t"] >= 2 and r["sr_ho"] > r["sr_gold"]:
            day = "RESEARCH ONLY"
        else:
            day = "DISABLE — holding gold did better"
        r["dec_sub"], r["dec_4h"], r["dec_1d"] = sub, four, day
        rows.append(r)
    T = pd.DataFrame(rows).sort_values(["family", "label"])

    L = ["# Gold Desk — strategy assessment (generated by gd_strategy_table.py)", "",
         "bp per trade, net of MEASURED costs unless marked gross; n = trades. Below 4h: Delta-like = Binance PAXG "
         "2025-01..2026-10 (24/7), MCX = the GOLDM store (sub-hour from Jul/Aug 2026 — thin). 4h: Binance PAXG, "
         "Delta's own XAUT+PAXG 2026, COMEX in MCX hours 2024-05..2026-10. 1d: COMEX daily 2000-2026, and against "
         "HOLDING gold (alpha t; held-out Sharpe 2013-07.. vs gold's 0.64).", "",
         "## Decisions, counted", "",
         f"- **Below 4h:** {({k: int(v) for k, v in T.dec_sub.value_counts().items()})}",
         f"- **4h:** {({k: int(v) for k, v in T.dec_4h.value_counts().items()})}",
         f"- **1d:** {({k: int(v) for k, v in T.dec_1d.value_counts().items()})}", "",
         "## By template (46)", "",
         "| Template | Family | <4h Delta-like: gross / net (n) | <4h MCX: gross / net (n) | 4h Binance: net (n, t) | 4h Delta 2026: net (n) | 4h COMEX/MCX hrs: net (n) | 1d 26-yr: net (n) | 1d vs holding gold: alpha t · held-out SR | Decision <4h · 4h · 1d |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in T.itertuples():
        L.append(f"| {r.label} | {r.family} | {f(r.sub_d_g, 2)} / {f(r.sub_d_net, 2)} ({r.sub_d_n:,}) | "
                 f"{f(r.sub_m_g, 2)} / {f(r.sub_m_net, 2)} ({r.sub_m_n:,}) | {f(r.b4_net)} ({r.b4_n}, t {f(r.b4_t)}) | "
                 f"{f(r.a4_net)} ({r.a4_n}) | {f(r.c4_net)} ({r.c4_n}) | {f(r.e_net)} ({r.e_n}) | "
                 f"{f(r.alpha_t, 2)} · {f(r.sr_ho, 2)} | {r.dec_sub} · {r.dec_4h} · {r.dec_1d} |")

    # ── appendix: every strategy, per venue, mechanical rule ─────────────────────
    def per(df, split):
        out = {}
        for (tf, tmpl), g in df.groupby(["tf", "template"]):
            a, b = g[g.date < split], g[g.date >= split]
            out[(tf, tmpl)] = {"n": len(g), "g": g.gross.mean(), "net": g.net_actual.mean(), "t": tstat(g.net_actual),
                               "a": a.net_actual.mean() if len(a) else np.nan, "b": b.net_actual.mean() if len(b) else np.nan}
        return out

    pB = per(B, pd.Timestamp("2025-11-20", tz="UTC"))
    pA = per(A, pd.Timestamp("2026-07-01", tz="UTC"))
    mC = per(C, pd.Timestamp("2025-07-28", tz="UTC"))
    mD = per(D, pd.Timestamp("2026-09-10", tz="UTC"))
    dsr = {}
    for ds in ("B_PAXG", "C_GC", "D_GOLDM"):
        s = pd.read_csv(AN / f"{ds}_strategies.csv")
        dsr[ds] = {(r.tf, r.template): r.dsr for r in s.itertuples()}

    def decide(p, conf, d, venue, tmpl):
        if venue == "delta" and tmpl in SESSION_TEMPLATES:
            return "STRUCTURAL"
        if p is None or p["n"] < 30:
            return "INSUFFICIENT"
        if p["g"] <= 0:
            return "DISABLE-RAW"
        if p["net"] <= 0:
            return "DISABLE-COST"
        ok = (p["a"] > 0 and p["b"] > 0 and p["t"] >= 3 and (d or 0) >= 0.95 and conf is not None and conf["net"] > 0)
        return "CANDIDATE" if ok else "RESEARCH ONLY"

    L += ["", "## Every strategy (353)", "",
          "Delta = Binance PAXG 2025-01..2026-10 (confirming: Delta XAUT+PAXG 2026). MCX = COMEX in MCX hours for "
          "1h/4h/1d (confirming: the GOLDM store), the GOLDM store alone below 1h. a / b = first / second half net.", "",
          "| TF | Template | Δ n | Δ gross | Δ net | Δ t | Δ a / b | Δ conf net (n) | Δ decision | M n | M gross | M net | M t | M a / b | M decision |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    counts = {"delta": {}, "mcx": {}}
    cat = sorted(COMMODITY_CATALOG, key=lambda s: (TEMPLATES[s.template][0], s.template, TF_ORDER.index(s.timeframe)))
    for s in cat:
        k = (s.timeframe, s.template)
        p, c = pB.get(k), pA.get(k)
        dd = decide(p, c, dsr["B_PAXG"].get(k), "delta", s.template)
        if s.timeframe in ("1h", "4h", "1d"):
            m, mc, md = mC.get(k), mD.get(k), dsr["C_GC"].get(k)
        else:
            m, mc, md = mD.get(k), None, dsr["D_GOLDM"].get(k)
        dm = decide(m, mc, md, "mcx", s.template)
        counts["delta"][dd] = counts["delta"].get(dd, 0) + 1
        counts["mcx"][dm] = counts["mcx"].get(dm, 0) + 1
        g = lambda x, key, d=2: f(x[key], d) if x else "—"
        L.append(f"| {s.timeframe} | {s.template} | {p['n'] if p else 0} | {g(p, 'g')} | {g(p, 'net')} | {g(p, 't', 1)} | "
                 f"{g(p, 'a', 1)} / {g(p, 'b', 1)} | {g(c, 'net', 1)} ({c['n'] if c else 0}) | {dd} | {m['n'] if m else 0} | "
                 f"{g(m, 'g')} | {g(m, 'net')} | {g(m, 't', 1)} | {g(m, 'a', 1)} / {g(m, 'b', 1)} | {dm} |")
    L.insert(L.index("## By template (46)"), f"- **Per strategy (appendix rule):** Delta {counts['delta']}; MCX {counts['mcx']}\n")
    (HERE / "gd_strategy_table_out.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(L[:12]))
    T.to_csv(AN / "template_table.csv", index=False)


if __name__ == "__main__":
    main()
