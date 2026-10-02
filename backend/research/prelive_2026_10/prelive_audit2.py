"""READ ONLY, part 2: daily-history mismatch, real premium decay calibration, the selling desk
and the live paper books for comparison, and data export for the offline research."""
import asyncio
import json
import math
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def p(*a):
    print(*a, flush=True)


def to_ist(v):
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(IST)


async def main():
    from app.core.db import db
    from app.services.intraday_store import read_file
    from tradingai_shared import nse_calendar as cal

    trades = [t async for t in db["prelive_trades"].find({})]
    for t in trades:
        t["entry_ts"], t["exit_ts"] = to_ist(t.get("entry_ts")), to_ist(t.get("exit_ts"))
    if False:
        pass
    # ── 1. daily history vs trades ──
    by_s = defaultdict(float)
    for t in trades:
        by_s[t["session"]] += t["pnl"]
    dp = {d["session"]: d async for d in db["prelive_daily_pnl"].find({})}
    p("daily docs vs trades:")
    for s in sorted(set(by_s) | set(dp)):
        a, b = round(by_s.get(s, 0)), round((dp.get(s) or {}).get("net_pnl") or 0)
        if abs(a - b) > 1:
            p(f"  {s}: trades {a:>10,}  daily doc {b:>10,}  {'(no doc)' if s not in dp else ''}")

    # ── 2. how the bought premiums really behaved ──
    nb = read_file("NIFTY", "5m")
    nt = list(nb.t)

    def spot_at(ts):
        e = int(ts.timestamp())
        i = bisect_right(nt, e - 300) - 1
        return nb.c[i] if i >= 0 and e - nt[i] < 1800 else None

    def expiry_for(d):
        x = d
        while x.weekday() != 1:
            x += timedelta(days=1)
        while not cal.is_listed_trading_day(x):
            x -= timedelta(days=1)
        return x
    rows = []
    for t in trades:
        if not t["entry_ts"] or not t["exit_ts"] or t["qty"] != 75:
            continue
        s0, s1 = spot_at(t["entry_ts"]), spot_at(t["exit_ts"])
        if not s0 or not s1:
            continue
        d = date.fromisoformat(t["session"])
        dte = (expiry_for(d) - d).days
        hold = (t["exit_ts"] - t["entry_ts"]).total_seconds() / 60
        sgn = 1 if t["option_type"] == "CE" else -1
        mny = sgn * (s0 - t["strike"]) / s0 * 100          # % in the money at entry
        rows.append({"dte": dte, "hold": hold, "fav_pts": sgn * (s1 - s0), "fav_bp": sgn * (s1 / s0 - 1) * 1e4,
                     "prem0": t["entry_premium"], "prem1": t["exit_premium"], "ret": t["exit_premium"] / t["entry_premium"] - 1,
                     "dprem": t["exit_premium"] - t["entry_premium"], "mny": mny, "spot0": s0,
                     "hour": t["entry_ts"].hour, "pnl": t["pnl"], "reason": t["exit_reason"]})
    p(f"\nPREMIUM BEHAVIOUR on {len(rows)} one-lot trades:")
    # premium points per NIFTY point (an empirical delta) and decay per hour, by expiry distance
    import numpy as np
    for lab, sel in (("expiry day (0DTE)", lambda r: r["dte"] == 0), ("1 day to expiry", lambda r: r["dte"] == 1),
                     ("4-6 days to expiry", lambda r: r["dte"] >= 4)):
        xs = [r for r in rows if sel(r)]
        if len(xs) < 50:
            continue
        X = np.array([[r["fav_pts"], r["hold"] / 60, 1.0] for r in xs])
        y = np.array([r["dprem"] for r in xs])
        w = np.linalg.lstsq(X, y, rcond=None)[0]
        prem = statistics.median(r["prem0"] for r in xs)
        flat = [r for r in xs if abs(r["fav_bp"]) < 5]
        p(f"  {lab}: n {len(xs)}, premium median Rs{prem:.0f}; per NIFTY point {w[0]:+.3f}, per hour held {w[1]:+.2f} pts "
          f"({w[1] / prem * 100:+.2f}%/h), entry offset {w[2]:+.2f}; flat-NIFTY trades: n {len(flat)}, "
          f"premium {statistics.mean(r['ret'] for r in flat) * 100 if flat else float('nan'):+.1f}% over "
          f"{statistics.median(r['hold'] for r in flat) if flat else 0:.0f} min")
        # break-even favourable NIFTY move for the median hold
        h = statistics.median(r["hold"] for r in xs) / 60
        be_pts = -(w[1] * h + w[2]) / w[0] if w[0] > 0 else float("nan")
        fees = 2 * 20 * 1.18 + prem * 75 * 0.0015
        p(f"     break-even NIFTY move over the median {h:.1f} h hold: {be_pts:.1f} pts "
          f"({be_pts / statistics.median(r['spot0'] for r in xs) * 1e4:.1f} bp) before fees; "
          f"+{fees / 75 / max(w[0], 1e-6):.1f} pts for fees")
    # stop/target geometry: how often the premium hit -30% vs +60% given direction
    p("  exits:", Counter(r["reason"] for r in rows))

    # ── 3. NIFTY over the period: did the desk just pay for the market's direction? ──
    first = min(t["entry_ts"] for t in trades if t["entry_ts"])
    last = max(t["exit_ts"] for t in trades if t["exit_ts"] and t["session"] < "2026-10-02")
    s_first, s_last = spot_at(first), spot_at(last)
    p(f"\nNIFTY {first:%Y-%m-%d} {s_first} -> {last:%Y-%m-%d} {s_last} ({(s_last / s_first - 1) * 100:+.1f}%)")

    # ── 4. the selling desk and the live paper books, for comparison ──
    st = [t async for t in db["prelive_selling_trades"].find({}, {"pnl": 1, "net_pnl": 1, "session": 1, "strategy_id": 1,
                                                                  "charges": 1, "exit_reason": 1, "realized_pnl": 1})]
    k = next((f for f in ("pnl", "net_pnl", "realized_pnl") if st and f in st[0]), None)
    if k:
        nets = [t.get(k) or 0 for t in st]
        sess = sorted({t.get("session") for t in st if t.get("session")})
        p(f"\nSELLING DESK: {len(st)} trades, {len(sess)} sessions ({sess[0] if sess else ''}..{sess[-1] if sess else ''}), "
          f"net {round(sum(nets)):,}, win {sum(1 for x in nets if x > 0) / len(nets):.3f}, "
          f"zero-P&L trades {sum(1 for x in nets if abs(x) < 1)}")
        per = defaultdict(list)
        for t in st:
            per[t.get("strategy_id")].append(t.get(k) or 0)
        rws = [(s, len(v), sum(v)) for s, v in per.items()]
        p(f"  {len(rws)} strategies; positive {sum(1 for r in rws if r[2] > 0)}")
    lp = [t async for t in db["live_paper_trades"].find({})]
    if lp:
        p(f"\nLIVE PAPER BOOK trades: {len(lp)}, keys {sorted(lp[0].keys())[:20]}")
        kk = next((f for f in ("pnl", "net_pnl", "realized_pnl") if f in lp[0]), None)
        if kk:
            by_book = defaultdict(list)
            for t in lp:
                by_book[t.get("book") or t.get("book_key") or "?"].append(t.get(kk) or 0)
            p("  per book:", {b: (len(v), round(sum(v))) for b, v in by_book.items()})

    # ── 5. export for the offline research (NIFTY 5m, INDIA VIX 15m, the trades) ──
    def bars(sym, tf):
        b = read_file(sym, tf)
        return [[b.t[i], b.o[i], b.h[i], b.l[i], b.c[i]] for i in range(len(b))]
    json.dump({"NIFTY_5m": bars("NIFTY", "5m"), "NIFTY_15m": bars("NIFTY", "15m"), "INDIAVIX_15m": bars("INDIAVIX", "15m"),
               "INDIAVIX_5m": bars("INDIAVIX", "5m")}, open("/out/nifty_bars.json", "w"))
    json.dump([{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in t.items() if k != "_id"} for t in trades],
              open("/out/prelive_trades.json", "w"))
    p("\nexported bars and trades")


asyncio.run(main())
