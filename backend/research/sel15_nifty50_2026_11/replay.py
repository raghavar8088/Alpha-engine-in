"""Selected ORB 15 and 30 on a chosen stock list (the NIFTY 50), 1:1 and as registered, at a chosen leverage.

The app's Intraday Stocks tournament runs iv2_orb_sel15 / iv2_orb_sel30 on its top-200 universe. This replays them with
only the NIFTY 50 allowed to be picked (--universe nifty50); the ranking model is trained as live, on the module's
universe. The production backtest cannot replay these rules
(it has no expected-move selection), so this rebuilds what the live engine does at 09:30 / 09:45
with the production code from git HEAD: scanner_board._features / predict / _train_sync, the
day's universe, weights retrained weekly on data before each Saturday.

Fills: fills5m.py on 5-minute bars (15-minute where no 5-minute bars exist).
Runs per rule:
    base_legacy  the rule as registered (sel15 no target, sel30 2R), legacy slippage: validation
    orig_legacy  1:1, legacy slippage: regression against the earlier 1:1 run
    orig         1:1, the measured slippage all other 52 strategies pay
    mirror       1:1, measured slippage

Data: INTRADAY_AI_DATA (default D:/intraday_ai_data) holding the box's intraday store (intraday/15m, intraday/5m) and
its exports (exports/universe_days.json, export1.json, results_reactions.json, live_v2.jsonl, bars1d.tsv), plus
exports/nse_results_raw.json from fetch_results.py (NSE board meetings, for the results-day flag).

    python replay.py --start 2026-10-01 --tag n50x1 --universe nifty50 --n50 nifty50_constituents_2026-11-08.csv \
        --windows trailing:2026-10-06:2026-11-05,october:2026-10-01:2026-10-31 --leverage 1
"""
from __future__ import annotations

import argparse
import csv
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault("INTRADAY_AI_DATA", r"D:/intraday_ai_data")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "intraday_ai"))
from fills5m import Reader, at, sim_entry  # noqa: E402
from stubpkg import DATA, REPO, activate, build  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--start", required=True)
ap.add_argument("--tag", required=True)
ap.add_argument("--universe", choices=("module", "nifty50"), default="nifty50")
ap.add_argument("--n50", default=None, help="NIFTY 50 constituent CSV (niftyindices.com ind_nifty50list.csv)")
ap.add_argument("--windows", default="", help="name:first:last,... (ISO dates) computed standalone")
ap.add_argument("--leverage", type=float, default=1.0, help="position size per slot = leverage x Rs 10 lakh; capital stays Rs 50 lakh")
ap.add_argument("--fixed", action="store_true", help="5 slots x Rs 10L throughout: the book never runs out of cash")
A = ap.parse_args()

base = build("HEAD")
pkg = HERE / "work" / f"pkg_sel_{A.tag}"
if pkg.exists():
    shutil.rmtree(pkg)
shutil.copytree(base, pkg)
(pkg / "app/services/scanner_board.py").write_bytes(subprocess.run(
    ["git", "show", "HEAD:backend/app/services/scanner_board.py"], cwd=REPO, capture_output=True,
    check=True).stdout.replace(b"\r\n", b"\n"))
for name in ("market_calendar", "nse_archives", "preopen", "results_calendar"):
    (pkg / f"app/services/{name}.py").write_text('"""Stand-in: unused by the replay."""\n', encoding="utf-8")
with open(pkg / "app/core/db.py", "a", encoding="utf-8") as f:
    f.write("\n\nclass _Dummy:\n    def __getitem__(self, name):\n        return None\n\n\ndb = _Dummy()\n")
with open(pkg / "app/services/intraday_universe.py", "a", encoding="utf-8") as f:
    f.write("\n\nSECTOR_INDEX = {}\nINDEX_TOKENS = {}\n\n\ndef sector_index(sector):\n    return 'NIFTY'\n")
activate(pkg)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from app.services import intraday_store as store  # noqa: E402
from app.services import intraday_v2_backtest as bt  # noqa: E402
from app.services import intraday_v2_strategies as v2  # noqa: E402
from app.services import scanner_board as sb  # noqa: E402
from app.services.intraday_fills import legacy_slippage_bp, slippage_bp as fills_slip  # noqa: E402

for m in (store, bt, v2, sb):
    assert os.path.abspath(m.__file__).startswith(str(pkg)), m.__file__

SPECS = {"open": v2.BY_ID["iv2_orb_sel15"], "0945": v2.BY_ID["iv2_orb_sel30"]}
assert SPECS["open"].params == {"range": 15, "top": 5, "rvol_key": "rvol_first", "min_rvol": 1.5, "stop": "opp",
                                "eval_at": "09:30", "entry_from": "09:30", "own_book": True}
assert SPECS["0945"].params == {"range": 30, "top": 5, "rvol_key": "rvol30", "min_rvol": 1.5, "stop": "atr",
                                "stop_atr": 0.5, "target_r": 2.0, "eval_at": "09:45", "own_book": True}
assert v2.SLOT_NOTIONAL == 1_000_000.0
bt.SLOT = v2.SLOT_NOTIONAL * A.leverage                 # the order size of each of the 5 slots
bt.CAPITAL = bt.SLOT * v2.SLOTS_PER_STRATEGY            # exposure the book may carry: leverage x own capital
CAP = v2.SLOT_NOTIONAL * v2.SLOTS_PER_STRATEGY          # own capital, Rs 50 lakh: returns and drawdown are on this
print(f"leverage {A.leverage:g}: Rs {bt.SLOT:,.0f} a slot, up to Rs {bt.CAPITAL:,.0f} open, on Rs {CAP:,.0f} capital", flush=True)
if A.fixed:
    bt.CAPITAL = 1e15
START = date.fromisoformat(A.start)


def dk_of(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def iso(dk: int) -> str:
    return (date(1970, 1, 1) + timedelta(days=dk)).isoformat()


# ── data ─────────────────────────────────────────────────────────────────────────
EXP = DATA / "exports"
nf = store.read_file("NIFTY")
sessions = sorted({store.day_key(t) for t in nf.t if store.day_key(t) >= dk_of(START)})
stored_u = {dk_of(date.fromisoformat(u["_id"])): u for u in json.load(open(EXP / "universe_days.json", encoding="utf-8"))}
pit = asyncio.run(bt.pit_universe(START - timedelta(days=21), date(2026, 11, 5),
                                  set(sessions) | {s - k for s in sessions for k in range(1, 8)}))
exp1 = json.load(open(EXP / "export1.json", encoding="utf-8"))
today_members = {m["symbol"]: m for m in exp1["members"]}
cas = {d["symbol"]: bool(d.get("is_cas_enabled")) for d in exp1["instruments"]}
files = {p.stem for p in (DATA / "intraday" / "15m").glob("*.ibar")} - {"NIFTY"}
reaction: dict[str, set[int]] = defaultdict(set)
react_day: dict[int, set[str]] = defaultdict(set)
for sym, days in json.load(open(EXP / "results_reactions.json", encoding="utf-8")).items():
    for d in days:
        k = dk_of(date.fromisoformat(d))
        reaction[sym].add(k)
        react_day[k].add(sym)
for x in json.load(open(EXP / "nse_results_raw.json", encoding="utf-8"))["scheduled"]:
    if x.get("bm_symbol") and "result" in (x.get("bm_purpose") or "").lower():
        react_day[dk_of(datetime.strptime(x["bm_date"], "%d-%b-%Y").date())].add(x["bm_symbol"])


N50 = None
if A.universe == "nifty50":
    with open(A.n50, encoding="utf-8") as f:
        N50 = {r["Symbol"].strip() for r in csv.DictReader(f) if r.get("Symbol")}
    assert len(N50) == 50, len(N50)
    print("NIFTY 50 with stored 15m bars:", len(N50 & files), "| missing:", sorted(N50 - files), flush=True)
    missing = sorted(s_ for s_ in N50 if s_ not in today_members)
    if missing:                      # turnover for the slippage bucket, from the stock's own daily bars
        tv = defaultdict(list)
        for line in open(EXP / "bars1d.tsv", encoding="utf-8"):
            p_ = line.rstrip("\n").split("\t")
            if p_[0] in missing:
                tv[p_[0]].append((int(p_[1]), float(p_[2]) * float(p_[3])))
        for s_ in missing:
            rows_ = sorted(tv[s_])[-20:]
            if rows_:
                today_members[s_] = {"symbol": s_, "turnover_cr": sum(v for _, v in rows_) / len(rows_) / 1e7}
        print("turnover filled from daily bars (Rs cr):", {s_: round((today_members.get(s_) or {}).get("turnover_cr") or 0) for s_ in missing}, flush=True)


def universe(dk: int):
    if dk in stored_u:
        u = stored_u[dk]
        return set(u["members"]) & files, u.get("turnover") or {}, "stored"
    return pit.get(dk, set()) & files, {s: (today_members.get(s) or {}).get("turnover_cr") for s in files}, "rebuilt"


FULL: dict[str, store.Bars] = {}


def full(sym: str) -> store.Bars:
    if sym not in FULL:
        FULL[sym] = store.read_file(sym)
    return FULL[sym]


def truncated(b: store.Bars, cut: int) -> store.Bars:
    k = bisect_left(b.t, cut)
    out = store.Bars()
    for name in store.Bars.__slots__:
        setattr(out, name, getattr(b, name)[:k])
    return out


class _FullStore:
    def get(self, sym):
        return full(sym)


sb.store = _FullStore()

# ── weekly model, point in time ──────────────────────────────────────────────────
MODELS: dict[int, dict | None] = {}


def model_for(dk: int):
    sat = dk - ((date(1970, 1, 1) + timedelta(days=dk)).weekday() + 2) % 7   # most recent Saturday <= dk
    if sat not in MODELS:
        cut = at(sat, "00:00")
        cands = [s for s in pit if s <= sat]
        prev = max(cands) if cands else min(pit)
        syms = sorted(universe(prev)[0])
        sb.read_file = lambda sym, tf="15m", _c=cut: truncated(full(sym), _c)
        try:
            res = sb._train_sync(syms, reaction)
        except (RuntimeError, IndexError, ValueError, np.linalg.LinAlgError) as e:
            MODELS[sat] = None
            print(f"no model for week of {iso(sat)}: {e}", flush=True)
            return None
        MODELS[sat] = res
        print(f"model for week of {iso(sat)}: {res['samples']} samples, {res['sessions']} sessions, "
              f"oos IC open {res['oos']['open'].get('rank_ic')} / 0945 {res['oos']['0945'].get('rank_ic')}", flush=True)
    return MODELS[sat]


# ── selection, as evaluate_close does ────────────────────────────────────────────
class _S:
    """What daily_atr reads, over the stored arrays."""

    def __init__(self, b):
        self.h, self.l, self.c, self.epochs = b.h, b.l, b.c, b.t


def select(dk: int) -> dict[str, list[dict]]:
    """Both rules' picks on this day: variant -> [signal dicts]. The model is trained on the module's
    universe as live; with --universe nifty50 only NIFTY 50 stocks can be ranked and picked."""
    members, turnover, _src = universe(dk)
    if N50 is not None:
        members = N50 & files
        turnover = {s: turnover.get(s) or (today_members.get(s) or {}).get("turnover_cr") for s in members}
    model = model_for(dk)
    out: dict[str, list[dict]] = {"open": [], "0945": []}
    if model is None:
        return out
    ctx = {"nifty_chg": None, "sector_chg": {}, "sector_of": {}, "cm_last": {}, "habit": {}, "fo_last": {},
           "results": {s: {"kind": "filed", "at": None} for s in react_day.get(dk, ())}, "pre": None}
    for variant, hhmm in (("open", "09:30"), ("0945", "09:45")):
        cutoff = at(dk, hhmm) + 1
        feats = []
        for sym in sorted(members):
            f = sb._features(sym, cutoff, ctx)
            if f is None:
                continue
            f["expected_move_bp"], f["em_variant"] = sb.predict(model, f)
            feats.append(f)
        ranked = sorted((f for f in feats if f.get("expected_move_bp") is not None and f.get("em_variant") == variant),
                        key=lambda f: -f["expected_move_bp"])
        for f in ranked[:5]:
            if variant == "open":
                first_only = f.get("bars_today") == 1
                rv = f.get("rvol") if first_only else None
                hi, lo = (f.get("day_high"), f.get("day_low")) if first_only else (None, None)
                sd = None
            else:
                rv, hi, lo = f.get("rvol30"), f.get("or_high"), f.get("or_low")
                b = full(f["symbol"])
                atr = v2.daily_atr(_S(b), None, j0=bisect_left(b.t, at(dk, "09:15")))
                sd = 0.5 * atr if atr else None
                if sd is None:
                    continue
            if rv is None or rv < 1.5 or not hi or not lo or hi <= lo:
                continue
            out[variant].append({"dk": dk, "symbol": f["symbol"], "hi": hi, "lo": lo, "sd": sd,
                                 "turnover_cr": turnover.get(f["symbol"]), "cas": cas.get(f["symbol"], False),
                                 "em": f["expected_move_bp"], "rvol": rv})
    return out


signals: dict[str, list[dict]] = {"open": [], "0945": []}
for n, dk in enumerate(sessions):
    day = select(dk)
    for v in day:
        signals[v].extend(day[v])
    if n % 25 == 0:
        print(iso(dk), "signals so far", {k: len(x) for k, x in signals.items()}, flush=True)
FULL.clear()

# ── fills: one symbol at a time ──────────────────────────────────────────────────
reader = Reader(store.read_file)
RUNS = {"base_legacy": (None, False, True), "orig_legacy": (1.0, False, True),
        "orig": (1.0, False, False), "mirror": (1.0, True, False), "base": (None, False, False)}
results: dict[str, dict] = {}
notes = Counter()
for variant, spec in SPECS.items():
    p = spec.params
    runs: dict[str, list] = {k: [] for k in RUNS}
    for s in sorted(signals[variant], key=lambda x: (x["symbol"], x["dk"])):
        dk = s["dk"]
        tf, step, rows = reader.day(s["symbol"], dk)
        if not rows:
            notes[variant, "no bars"] += 1
            continue
        if variant == "open":
            legs = [(1, s["hi"], s["lo"]), (-1, s["lo"], s["hi"])]
            rr0 = None
        else:
            legs = [(1, s["hi"], None), (-1, s["lo"], None)]
            rr0 = 2.0
        t_from = at(dk, "09:30" if variant == "open" else "09:45")
        sq = (at(dk, "15:05" if s["cas"] else "15:10"), "open")
        for name, (rr, mirror, legacy) in RUNS.items():
            bp = legacy_slippage_bp(s["turnover_cr"]) if legacy else fills_slip(s["turnover_cr"], notional=bt.SLOT)

            def book(t, x, side, fill, px, reason, market, bp_):
                return bt._book(spec, s["symbol"], t, x, side, fill, px, reason, market, bp_, s["em"])
            tr, note = sim_entry(rows, step, legs, t_from, at(dk, "14:30"), sq, s["sd"],
                                 rr if name != "base_legacy" else rr0, mirror, bp, book)
            notes[variant, name, note] += 1
            if name == "orig":
                notes[variant, "fill_tf", tf] += 1 if tr else 0
            if tr:
                runs[name].append(tr)
    results[spec.strategy_id] = runs


def stats(tr: list) -> dict:
    n = len(tr)
    w = sum(1 for t in tr if t[10] > 0)
    gp = sum(t[10] for t in tr if t[10] > 0)
    gl = -sum(t[10] for t in tr if t[10] < 0)
    net = sum(t[10] for t in tr)
    pd = defaultdict(float)
    for t in tr:
        pd[store.day_key(t[3])] += t[10]
    eq = pk = mdd = 0.0
    for s_ in sessions:
        eq += pd.get(s_, 0.0)
        pk = max(pk, eq)
        mdd = max(mdd, pk - eq)
    return {"trades": n, "win_pct": round(w / n * 100, 2) if n else None, "pf": round(gp / gl, 3) if gl else None,
            "gross": round(sum(t[8] for t in tr), 2), "fees": round(sum(t[9] for t in tr), 2), "net": round(net, 2),
            "ret_pct": round(net / CAP * 100, 3), "max_dd": round(mdd, 2), "max_dd_pct": round(mdd / CAP * 100, 3),
            "avg": round(net / n, 2) if n else None, "reasons": dict(Counter(t[11] for t in tr)),
            "longs": sum(1 for t in tr if t[4] == "BUY"), "green_days": sum(1 for v in pd.values() if v > 0),
            "red_days": sum(1 for v in pd.values() if v < 0)}


WINDOWS = [w.split(":") for w in A.windows.split(",") if w]
out = {"args": vars(A), "pkg": base.name, "sessions": [iso(d) for d in sessions],
       "first_model_week": iso(min((k for k, v in MODELS.items() if v), default=0)),
       "rules": {}, "notes": {" | ".join(k): v for k, v in sorted(notes.items())}}
for sid, runs in results.items():
    out["rules"][sid] = {}
    for name, tr in runs.items():
        taken = bt.accept(tr).get(sid, []) if tr else []
        st = stats(taken)
        st["candidates"] = len(tr)
        st["first_trade"] = iso(store.day_key(min(t[2] for t in taken))) if taken else None
        st["windows"] = {}
        for wname, w0, w1 in WINDOWS:
            k0, k1 = dk_of(date.fromisoformat(w0)), dk_of(date.fromisoformat(w1))
            sub = [t for t in tr if k0 <= store.day_key(t[2]) <= k1]
            tk = bt.accept(sub).get(sid, []) if sub else []
            keep = sessions
            sessions = [s_ for s_ in keep if k0 <= s_ <= k1]
            ws = stats(tk)
            ws["sessions"] = len(sessions)
            ws["days_traded"] = len({store.day_key(t[2]) for t in tk})
            ws["trades_list"] = tk
            sessions = keep
            st["windows"][wname] = ws
            print(f"   window {wname} {w0}..{w1}: {ws['sessions']} sessions, tr {ws['trades']}, win {ws['win_pct']}, net {ws['net']:,.0f}, "
                  f"{ws['ret_pct']:+.2f}%, PF {ws['pf']}, DD {ws['max_dd_pct']:.2f}%, avg {ws['avg']}", flush=True)
        out["rules"][sid][name] = {**st, "trades_list": taken}
        print(f"{sid:<16} {name:<12} cand {len(tr):>4} tr {st['trades']:>4} win {st['win_pct'] or 0:5.1f}% PF {st['pf']} net "
              f"{st['net']:>12,.0f} {st['ret_pct']:+7.2f}% DD {st['max_dd_pct']:.2f}% avg {st['avg'] or 0:>8,.0f} {st['reasons']}", flush=True)

# ── validation against the live record ───────────────────────────────────────────
live_all = [json.loads(x) for x in open(EXP / "live_v2.jsonl", encoding="utf-8")]
for sid in (results if N50 is None else []):
    live = [r for r in live_all if r["strategy_id"] == sid and r.get("status") == "CLOSED"]
    if not live:
        continue
    first = min(store.day_key(r["opened_at"]) for r in live)
    if sessions[0] > first:
        continue
    lset = {(iso(store.day_key(r["opened_at"])), r["symbol"], r["side"]) for r in live}
    tr = out["rules"][sid]["base_legacy"]["trades_list"]
    rset = {(iso(store.day_key(t[2])), t[1], t[4]) for t in tr if store.day_key(t[2]) >= first}
    shared = lset & rset
    ln = {(iso(store.day_key(r["opened_at"])), r["symbol"], r["side"]): r["realized_pnl"] for r in live}
    rn = {(iso(store.day_key(t[2])), t[1], t[4]): t[10] for t in tr}
    val = {"from": iso(first), "live": len(lset), "replay": len(rset), "same_day_stock_side": len(shared),
           "live_net": round(sum(r["realized_pnl"] for r in live)),
           "replay_net": round(sum(t[10] for t in tr if store.day_key(t[2]) >= first)),
           "shared_live_net": round(sum(ln[k] for k in shared)), "shared_replay_net": round(sum(rn[k] for k in shared))}
    out["rules"][sid]["validation"] = val
    print("VALIDATION", sid, json.dumps(val), flush=True)
print("first model week", out["first_model_week"], "| notes", json.dumps(out["notes"]))
(HERE / "work").mkdir(exist_ok=True)
json.dump(out, open(HERE / "work" / f"sel_n50_{A.tag}.json", "w", encoding="utf-8"), default=str)
print("saved", HERE / "work" / f"sel_n50_{A.tag}.json")
