"""Audit of the 54 tournament strategies — the replay (read-only; no rule is changed).

    python audit54.py --name audit54 --start 2024-11-04

Runs the production backtest from a git commit (stubpkg) ONCE and keeps three views of
every strategy, so the audit can separate the rule from the book it is traded in:

  signals.csv.gz     every signal the rule produced (taken or not): side, planned stop and
                     target in bp, priority, relative volume, and for Donchian whether the
                     previous bar had already closed beyond the channel
  candidates.csv.gz  every signal simulated as a trade (the backtest's tuple; ~opt rows are
                     the optimistic shadow of ORB trigger bars)
  taken_live.csv.gz  the trades the tournament's live rules accept (all strategies together:
                     five slots, cash, already-holding, two strategies per stock)
  taken_solo.csv.gz  the trades each strategy takes ALONE under the same per-strategy limits
                     (the two-per-stock cap never binds) — the strategy without interference
  meta.json          per-symbol turnover band and CAS flag (to split slippage from charges)
  summary.json       the backtest's own summary (live rules), as runner.py writes it
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import functools
import gzip
import json
import logging
import pathlib
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA, activate, build  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="audit54")
    ap.add_argument("--start", default="2024-11-04")
    ap.add_argument("--commit", default="HEAD")
    a = ap.parse_args()

    pkg = build(a.commit)
    activate(pkg)
    from app.services import intraday_v2_backtest as bt
    from app.services import intraday_v2_strategies as v2
    from app.services.intraday_v2_engine import MAX_STRATEGIES_PER_SYMBOL
    from app.services.intraday_v2_portfolio import accept_live

    out = DATA / "runs" / a.name
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # ── every signal, taken or not ──
    sf = gzip.open(out / "signals.csv.gz", "wt", encoding="utf-8", newline="")
    sw = csv.writer(sf)
    sw.writerow(["sid", "sym", "t", "side", "entry", "stop_bp", "tgt_bp", "trigger", "priority",
                 "rvol", "traded", "repeat_break"])
    n_sig = [0]

    def on_signal(spec, sig, ctx, t, tr):
        e = sig.entry or 0.0
        if sig.oco:
            tgt = None
        elif sig.target_price is not None:
            tgt = abs(sig.target_price - e)
        else:
            tgt = sig.target_dist
        rep = ""
        if spec.family == "donchian":
            s, i, n = ctx.s, ctx.i, spec.params.get("n", 20)
            if i >= n + 2:
                if sig.side == "BUY":
                    rep = int(s.c[i - 1] > max(s.h[i - 1 - n:i - 1]))
                else:
                    rep = int(s.c[i - 1] < min(s.l[i - 1 - n:i - 1]))
        sw.writerow([spec.strategy_id, ctx.symbol, t, sig.side, round(e, 4),
                     round(sig.stop_dist / e * 1e4, 2) if e else "",
                     round(tgt / e * 1e4, 2) if (e and tgt) else "",
                     int(sig.trigger is not None), round(float(sig.priority or 0.0), 4),
                     round(ctx.rvol, 3) if ctx.rvol is not None else "", int(tr is not None), rep])
        n_sig[0] += 1

    bt.replay_symbol = functools.partial(bt.replay_symbol, on_signal=on_signal)

    # ── the candidate table, and both acceptance passes ──
    skipped_out: dict = {}

    def live_accept(con, meta):
        with gzip.open(out / "candidates.csv.gz", "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sid", "sym", "et", "xt", "side", "ep", "xp", "qty", "gross", "fees", "net",
                        "reason", "prio"])
            for r in con.execute("SELECT * FROM c"):
                w.writerow(r)
        json.dump({s: {"turnover_cr": m.get("turnover_cr"), "cas": bool(m.get("cas", True)),
                       "slip_bp": bt.slippage_bp(m.get("turnover_cr"))} for s, m in meta.items()},
                  open(out / "meta.json", "w", encoding="utf-8"))
        own = {s.strategy_id for s in v2.CATALOG if s.params.get("own_book")}
        cat = {s.strategy_id: i for i, s in enumerate(v2.CATALOG)}

        def days():
            cur, batch = None, []
            for r in con.execute("SELECT * FROM c WHERE sid NOT LIKE ? ORDER BY et", (f"%{bt.OPT_SUFFIX}",)):
                dk = bt.day_key(r[2])
                if dk != cur and batch:
                    yield batch
                    batch = []
                cur = dk
                batch.append(tuple(r))
            if batch:
                yield batch

        def tiebreak(r):
            return (-((meta.get(r[1]) or {}).get("turnover_cr") or 0.0), cat.get(r[0], 999))

        res = {}
        for name, cap in (("live", MAX_STRATEGIES_PER_SYMBOL), ("solo", 10 ** 9)):
            sk: dict = {}
            taken = accept_live(days(), own, bt.CAPITAL, bt.SLOTS, cap, tiebreak=tiebreak, skipped=sk)
            skipped_out[name] = sk
            with gzip.open(out / f"taken_{name}.csv.gz", "wt", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["sid", "sym", "et"])
                for sid, rows in taken.items():
                    for r in rows:
                        w.writerow([sid, r[1], r[2]])
            res[name] = taken
        return res["live"], skipped_out["live"]

    bt._live_accept = live_accept

    days_back = (datetime.now(IST).date() - date.fromisoformat(a.start)).days
    t0 = time.time()
    summary = asyncio.run(bt.run(days_back, None, pit=True, save=False, live_rules=True))
    sf.close()
    results = summary.pop("results")
    meta = {"args": vars(a), "commit_pkg": pkg.name, "elapsed_s": round(time.time() - t0, 1),
            "signals": n_sig[0], "skipped": skipped_out, "capital_per_strategy": bt.CAPITAL}
    json.dump({"meta": meta, "summary": {k: v for k, v in summary.items() if k != "created_at"},
               "results": results}, open(out / "summary.json", "w", encoding="utf-8"), default=str, indent=1)
    print(json.dumps(meta, default=str))


if __name__ == "__main__":
    main()
