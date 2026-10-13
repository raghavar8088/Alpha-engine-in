"""Replay the 66 BANKNIFTY-specific INTRADAY rules (app/services/banknifty_strategies.py - the
same code the live desk runs) over 2016-01 .. 2026-10-09.

Each rule sees, at every closed 5m bar, only today's closed bars, the previous 20 sessions and
NIFTY's closed bars; at most one trade a session. On an Entry it buys 1 lot (30) of the ATM
CE/PE of the nearest monthly with >= 7 sessions left, priced by bn_price at the bar's close.
Exits, checked on every later 5m bar: index stop / target on the bar's low/high (stop first,
filled at the level), the rule's own time exit, 15:15 at the latest. Costs and the spread as
in bn_common. Output: results/fam/<rule>.json, the same columns as the library replay.
"""

import json
import os
import sys
import time
from datetime import date
from multiprocessing import Pool

import bn_common as C
from bn_price import Pricer

sys.path.insert(0, os.path.join(C.REPO, "backend"))
from app.services import banknifty_strategies as B  # noqa: E402

OUT = os.path.join(C.DATA, "results", "fam")
G: dict = {}


def init_worker():
    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    nf = C.Sessions("NIFTY", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    G.update(bn=bn, nf=nf, px=Pricer(spot=bn), rules={r.id: r for r in B.intraday_rules()})


def simulate(rule, k, j, entry, bars, ek, kp):
    px = G["px"]
    e0 = int(bars[j][0]) + 300
    S0 = bars[j][4]
    call = entry.side > 0
    K = round(S0 / C.STEP) * C.STEP
    p0 = px.premium(e0, S0, K, call, ek, kp)
    if not p0 or p0 < 5:
        return None
    exit_min = min(entry.exit_min, C.SQUARE_OFF_MIN)
    for i in range(j + 1, len(bars)):
        b = bars[i]
        end = C.minute(int(b[0])) + 5
        te = int(b[0]) + 300
        if end > exit_min:
            break
        lo, hi = b[3], b[2]
        if entry.stop is not None and ((call and lo <= entry.stop) or (not call and hi >= entry.stop)):
            return te, K, p0, px.premium(te, entry.stop, K, call, ek, kp), "stop", entry.stop
        if entry.target is not None and ((call and hi >= entry.target) or (not call and lo <= entry.target)):
            return te, K, p0, px.premium(te, entry.target, K, call, ek, kp), "target", entry.target
        if end == exit_min:
            return te, K, p0, px.premium(te, b[4], K, call, ek, kp), "time", b[4]
    # out at the last bar ending at or before the exit minute
    last = [b for b in bars if C.minute(int(b[0])) + 5 <= exit_min][-1]
    te = int(last[0]) + 300
    return te, K, p0, px.premium(te, last[4], K, call, ek, kp), "time", last[4]


def replay(rule_id):
    path = os.path.join(OUT, f"{rule_id}.json")
    if os.path.exists(path):
        return rule_id, -1, 0.0
    t0 = time.time()
    rule = G["rules"][rule_id]
    bn, nf, px = G["bn"], G["nf"], G["px"]
    days = [k for k in bn.days if C.kdate(k) >= C.RESEARCH_START]
    idx = {k: i for i, k in enumerate(bn.days)}
    out = []
    for k in days:
        i = idx[k]
        if i < 20:
            continue
        cp = px.contract_for(k)
        if cp is None:
            continue
        ek, kp = cp
        bars = bn.bars[k]
        hist = [bn.bars[x] for x in bn.days[i - 20:i]]
        nbars = nf.bars.get(k)
        for j in range(len(bars)):
            if C.minute(int(bars[j][0])) + 5 > C.SQUARE_OFF_MIN:
                break
            day = B.Day(bars=bars[:j + 1], hist=hist, nifty=nbars[:j + 1] if nbars and len(nbars) == len(bars) else None)
            try:
                entry = rule.decide(day)
            except Exception:
                entry = None
            if entry is None:
                continue
            r = simulate(rule, k, j, entry, bars, ek, kp)
            if r:
                te, K, p0, p1, why, S1 = r
                e0, S0 = int(bars[j][0]) + 300, bars[j][4]
                out.append([k, e0, entry.side, C.trading_sessions_left(k, ek), round(S0, 2), K, round(p0, 2), round(p1, 2),
                            why, round((te - e0) / 60), round(C.net_pnl(p0, p1), 2), round(entry.side * (S1 / S0 - 1) * 1e4, 2)])
            break                                   # one trade a session
    with open(path + ".tmp", "w") as f:
        json.dump({"sid": rule_id, "tf": "5m", "family": rule.family, "label": rule.label, "params": rule.params,
                   "cols": ["k", "entry_e", "side", "sessions_left", "S0", "K", "p0", "p1", "why", "hold_min", "net", "fav_bp"],
                   "trades": out}, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    return rule_id, len(out), time.time() - t0


def main():
    os.makedirs(OUT, exist_ok=True)
    ids = [r.id for r in B.intraday_rules()]
    if len(sys.argv) > 1:
        ids = [i for i in ids if any(a in i for a in sys.argv[1:])]
    nproc = int(os.environ.get("BN_PROCS", "10"))
    print(f"{len(ids)} intraday rules on {nproc} processes", flush=True)
    t0 = time.time()
    with Pool(nproc, initializer=init_worker) as pool:
        for n, (rid, ntr, secs) in enumerate(pool.imap_unordered(replay, ids), 1):
            print(f"{n}/{len(ids)} {rid}: {ntr} trades {secs:.0f}s (wall {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
