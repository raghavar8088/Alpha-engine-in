"""Intraday check of the premium model against REAL NIFTY option quotes the app recorded (2026-10-05 .. 10-23).

    python -I backend/research/nifty_options_orb_2026_10/nopt_intraday_check.py

The option-chain recorder (app/services/option_chain_recorder.py) kept, every minute, NIFTY's current
and next weekly expiry, ATM +-10 strikes, best bid and ask. For every session, entry times 09:30,
10:00 .. 14:30 and holds of 30 / 60 / 120 minutes and to 15:15, at the strike nearest the spot at entry,
calls and puts, the model's premium (nopt_price, anchored on the previous session's real NSE closes)
is compared with the real mid quote (spread under 3% of the mid): the level at entry, and the CHANGE
over the hold, which is what a trade's P&L depends on. These sessions are after the calibration window,
so this is out of sample. Output: results/intraday_check.json.
"""

from __future__ import annotations

import gzip
import json
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402
from nopt_price import Pricer  # noqa: E402


def load_chain(path: Path):
    """minute-of-day -> (epoch, spot, {(expiry, strike, 'C'|'P'): mid})"""
    out = {}
    for ln in gzip.open(path, "rt"):
        m = json.loads(ln)
        t, spot, exps = m["t"], m.get("spot"), m.get("exp") or []
        if not spot:
            continue
        mids = {}
        for r in m["rows"]:
            ei, K, cp, ltp, bid, _, ask = r[:7]
            if bid and ask and ask > bid > 0 and (ask - bid) / ((ask + bid) / 2) < 0.03:
                mids[(exps[ei], float(K), cp)] = (ask + bid) / 2
        out[C.minute_of_day(t)] = (t, float(spot), mids)
    return out


def bucket(days: int) -> str:
    return "0" if days == 0 else "1" if days == 1 else "2-4" if days <= 4 else "5+"


def summ(xs):
    return {"n": len(xs), "mean": statistics.mean(xs), "median": statistics.median(xs), "sd": statistics.pstdev(xs)} if xs else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C.set_calendar()
    px = Pricer()
    level, change = {}, {}
    rows_out = []
    for f in sorted((C.DATA / "optchain").glob("*.jsonl.gz")):
        d = date.fromisoformat(f.name[:10])
        k = C.dk(d)
        ch = load_chain(f)
        for m0 in range(9 * 60 + 30, 14 * 60 + 31, 30):
            if m0 not in ch:
                continue
            e0, S0, mids0 = ch[m0]
            K = round(S0 / C.STEP) * C.STEP
            for exp in sorted({key[0] for key in mids0}):
                ek = C.dk(date.fromisoformat(exp))
                kp = px.anchor(k, ek)
                if kp is None:
                    continue
                b = bucket(ek - k)
                for cp in ("C", "P"):
                    r0 = mids0.get((exp, float(K), cp))
                    if not r0:
                        continue
                    call = cp == "C"
                    p0 = px.premium(e0, S0, K, call, ek, kp)
                    level.setdefault(b, []).append((p0 - r0) / r0)
                    for hold, m1 in (("30", m0 + 30), ("60", m0 + 60), ("120", m0 + 120), ("to 15:15", 15 * 60 + 15)):
                        if m1 > 15 * 60 + 15 or m1 not in ch:
                            continue
                        e1, S1, mids1 = ch[m1]
                        r1 = mids1.get((exp, float(K), cp))
                        if not r1:
                            continue
                        p1 = px.premium(e1, S1, K, call, ek, kp)
                        err = ((p1 - p0) - (r1 - r0)) / r0
                        change.setdefault(hold, {}).setdefault(b, []).append(err)
                        rows_out.append([d.isoformat(), m0, hold, exp, K, cp, round(r0, 2), round(r1, 2), round(p0, 2), round(p1, 2)])
    res = {"beta": px.beta, "smile": px.smile, "level_error_at_entry": {b: summ(v) for b, v in level.items()},
           "change_error": {h: {b: summ(v) for b, v in bb.items()} for h, bb in change.items()},
           "change_error_all": {h: summ([x for v in bb.values() for x in v]) for h, bb in change.items()}}
    for b, v in sorted(level.items()):
        s = res["level_error_at_entry"][b]
        print(f"level at entry, {b:>3} days to expiry: n {s['n']:4d}  mean {s['mean'] * 100:+6.2f}%  median {s['median'] * 100:+6.2f}%  sd {s['sd'] * 100:5.2f}%")
    for h, bb in change.items():
        a = res["change_error_all"][h]
        print(f"change over {h:>8}: n {a['n']:4d}  mean {a['mean'] * 100:+6.2f}%  median {a['median'] * 100:+6.2f}%  sd {a['sd'] * 100:5.2f}% of premium   "
              + "  ".join(f"[{b}: {s['mean'] * 100:+.2f}% n{s['n']}]" for b, s in sorted(res['change_error'][h].items())))
    tag = "" if C.CLOCK == "u" else f"_{C.CLOCK}"
    res["clock"] = C.CLOCK
    with open(C.RES / f"intraday_check{tag}.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    with gzip.open(C.DATA / f"intraday_check_rows{tag}.json.gz", "wt") as g:
        json.dump(rows_out, g)


if __name__ == "__main__":
    main()
