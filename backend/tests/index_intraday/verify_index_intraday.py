"""Indian Index Intraday — the paper engine trades exactly what the backtest tested, and its risk,
fills and accounting are right. No Mongo, no Angel, no network.

Run:  python backend/tests/index_intraday/verify_index_intraday.py

EXITS     live_exit.step (minute by minute) == engine.walk_exit (whole path) on random paths
NO PEEK   every family, run on a real day cut off at minute u (later minutes unknown), signals
          exactly what the full-day backtest signals — and never before its trigger minute
          (needs the research data; skipped, and said so, without it)
RISK      every limit of risk.allow, sizing, the losing-streak pause, the drawdown halt
ENGINE    minute-by-minute ticks over a synthetic breakout day: the paper position opens and
          closes at the backtest's minutes and prices; a stale signal is not entered late; 15:12
          squares off; the emergency stop flattens; the ETF model fills at the touch with Angel's
          charges and the liquidity cap
CATALOG   1,208 trials, unique ids, a status from the ladder, a stated failure for each
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gold_desk"))
from _harness import ROOT, Coll, check, finish, section  # noqa: E402

import numpy as np  # noqa: E402

from app.services.index_intraday import catalog as cat  # noqa: E402
from app.services.index_intraday import data as DM  # noqa: E402
from app.services.index_intraday import engine as E  # noqa: E402
from app.services.index_intraday import families as F  # noqa: E402
from app.services.index_intraday import risk as R  # noqa: E402
from app.services.index_intraday.costs import ROUTE, fee_rt_bp, max_etf_order  # noqa: E402
from app.services.index_intraday.live_exit import start as live_start  # noqa: E402
from app.services.index_intraday.live_exit import step  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
asyncio.set_event_loop(asyncio.new_event_loop())


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════════════════
section("EXITS — the live checker is the backtest's exit rule, minute for minute")

rng = random.Random(20261012)
bad, n = 0, 0
for trial in range(3000):
    N = 375
    o, h, l, c = (np.zeros(N) for _ in range(4))
    px = 1000.0
    for m in range(N):
        gap = rng.gauss(0, 0.6) if rng.random() < 0.05 else rng.gauss(0, 0.05)
        o[m] = px + gap
        moves = [o[m] + rng.gauss(0, 0.5) for _ in range(3)]
        h[m], l[m], c[m] = max(o[m], *moves), min(o[m], *moves), moves[-1]
        px = c[m]
    side = rng.choice([1, -1])
    m0 = rng.randint(5, 300)
    kind = rng.choice(["market", "stop"])
    entry = float(o[m0]) if kind == "market" else float(o[m0]) + side * rng.uniform(0, 0.3)
    stop = entry - side * rng.uniform(0.5, 4) if rng.random() < 0.85 else None
    target = entry + side * rng.uniform(0.5, 6) if rng.random() < 0.6 else None
    trail = rng.uniform(0.5, 3) if rng.random() < 0.4 else None
    sig = m0 + rng.randint(1, 80) if rng.random() < 0.3 else None
    hold = m0 + rng.randint(1, 120) if rng.random() < 0.3 else None
    sq = E.SQUARE_OFF
    full = E.walk_exit(o, h, l, c, m0, sq, side, entry, stop, target, trail, sig, hold, kind)
    lv = live_start(side, m0, entry, kind, stop, target, trail)
    got = None
    for upto in range(m0 + 1, sq + 1):
        got = step(lv, o, h, l, upto, sq, sig, hold)
        if got:
            break
    n += 1
    if got is None or got[0] != full[0] or abs(got[1] - full[1]) > 1e-12 or got[2] != full[2]:
        bad += 1
check(f"step == walk_exit on {n} random paths (gaps, both sides, trails, signal / time exits)", bad == 0, f"{bad} mismatches")

# ═════════════════════════════════════════════════════════════════════════════════
section("DATA — the research loader, plus the price-sanity corrections")


def research_loader(name, since=None):
    """The loader the research rounds used, frozen verbatim (row tuples, dict of minutes)."""
    import csv
    import gzip
    rows = []
    files = sorted((DM.DATA / name).glob("*.csv.gz"))
    if since is not None:
        files = [f for f in files if date.fromisoformat(f.name[:10]) >= since - timedelta(days=31)]
    for f in files:
        with gzip.open(f, "rt") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            for r in rd:
                try:
                    rows.append((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)))
                except (ValueError, IndexError):
                    continue
    rows.sort()
    by_day, outside = {}, 0
    for ts, o, h, l, c, v in rows:
        t = datetime.fromtimestamp(ts, IST)
        m = t.hour * 60 + t.minute - DM.OPEN_MIN
        if not 0 <= m < DM.SESSION_MIN:
            outside += 1
            continue
        by_day.setdefault(t.date(), {})[m] = (o, h, l, c, v)
    kept, short, late, filled = [], 0, 0, 0
    for d in sorted(by_day):
        if 0 not in by_day[d]:
            late += 1
        elif len(by_day[d]) < DM.MIN_MINUTES:
            short += 1
        else:
            kept.append(d)
    n = len(kept)
    O, H, L, C, V = (np.empty((n, DM.SESSION_MIN)) for _ in range(5))
    for i, d in enumerate(kept):
        mins, last = by_day[d], by_day[d][0][0]
        for m in range(DM.SESSION_MIN):
            bar = mins.get(m)
            if bar is None:
                O[i, m] = H[i, m] = L[i, m] = C[i, m] = last
                V[i, m] = 0.0
                filled += 1
            else:
                O[i, m], H[i, m], L[i, m], C[i, m], V[i, m] = bar
                H[i, m] = max(H[i, m], O[i, m], C[i, m])
                L[i, m] = min(L[i, m], O[i, m], C[i, m])
                last = C[i, m]
    q = {"rows": len(rows), "outside_session": outside, "days_seen": len(by_day), "days_kept": n,
         "dropped_no_0915": late, "dropped_short": short, "minutes_filled_flat": filled,
         "first": str(kept[0]) if kept else None, "last": str(kept[-1]) if kept else None}
    return np.array(kept, dtype="datetime64[D]"), (O, H, L, C, V), q


if not (DM.DATA / "NIFTY").exists():
    print("  SKIP  research data not present — the loader was not compared here")
else:
    NEW_KEYS = ("bad_prints_dropped", "vix_rows_rescaled")
    differ = []
    for name, since in (("NIFTY", date(2025, 6, 1)), ("INDIAVIX", date(2025, 1, 1)), ("FINNIFTY", date(2024, 1, 1)),
                        ("BANKBEES", date(2024, 1, 1))):
        od, oarr, oq = research_loader(name, since)
        nd = DM._build(name, DM._read(name, since))
        nq = {k: v for k, v in nd.quality.items() if k not in NEW_KEYS}
        if not (np.array_equal(od, nd.dates) and oq == nq and not any(nd.quality[k] for k in NEW_KEYS)
                and all(np.array_equal(a, b) for a, b in zip(oarr, (nd.o, nd.h, nd.l, nd.c, nd.v)))):
            differ.append(name)
    check("where the data has no defect, the vectorised loader is the research's original loader bit for bit "
          "(NIFTY, INDIAVIX, FINNIFTY, BANKBEES)", not differ, differ)

    fin_old = research_loader("FINNIFTY", date(2022, 7, 15))
    fin = DM._build("FINNIFTY", DM._read("FINNIFTY", date(2022, 7, 15)))
    aug = [k for k, d in enumerate(fin.dates.astype(object)) if d in (date(2022, 8, 8), date(2022, 8, 10), date(2022, 8, 11))]
    check("FINNIFTY August 2022: Angel's -0.01 placeholders are dropped, the three days kept (the minutes flat)",
          len(aug) == 3 and float(np.min(fin.l[aug])) > 10_000 and fin.quality["bad_prints_dropped"] == 4
          and float(np.min(fin_old[1][2][aug])) < 0, (len(aug), float(np.min(fin.l[aug])) if aug else None))
    vx = DM.load("INDIAVIX")
    k16 = int(np.searchsorted(vx.dates, np.datetime64("2016-01-04")))
    k21 = int(np.searchsorted(vx.dates, np.datetime64("2021-03-01")))
    check("India VIX served divided by 100 (2016-01 .. 09, 2021-03-01) is rescaled: never below 8 again",
          float(vx.c.min()) > 8 and 10 < vx.c[k16, -1] < 30 and str(vx.dates[k21]) == "2021-03-01" and vx.c[k21, -1] > 10,
          (float(vx.c.min()), float(vx.c[k16, -1]), float(vx.c[k21, -1])))
    nb = DM.load("NIFTYBEES")
    check("NIFTYBEES 2020-03-05 is not kept: its only 09:15 print was 19% off the day's prices",
          np.datetime64("2020-03-05") not in set(nb.dates.tolist()) and nb.quality["bad_prints_dropped"] == 10)
    worst = {}
    for name in ("NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYNXT50", "NIFTY100", "MIDCPNIFTY", "SENSEX", "BANKEX",
                 "NIFTYBEES", "BANKBEES", "JUNIORBEES", "FINIETF", "MIDSELIETF", "NIF100BEES", "SENSEXIETF"):
        d = DM.load(name)
        med = np.median(d.c, axis=1)[:, None]
        worst[name] = float(np.max(np.abs(np.stack([d.o, d.h, d.l, d.c]) / med - 1)))
    check("no index or ETF minute is at or below zero or more than 15% from its day's median, anywhere",
          max(worst.values()) <= 0.15, max(worst.items(), key=lambda kv: kv[1]))


def _session(day, drop):
    base = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
    return [[base + 60 * k, 100.0, 101.0, 99.0, 100.5, 0.0] for k in range(375) if k not in drop]


gaps = set(range(360, 375)) | set(range(100, 110))          # the closing window, and 10 minutes mid-day
synthetic = DM._build("NIFTY", np.array(_session(date(2023, 9, 15), gaps) + _session(date(2026, 9, 15), gaps)))
check("from NSE's closing auction (2026-08-03) a day missing 15:15-15:29 and 10 more minutes is kept; "
      "the same day before it is not (the research's rule, unchanged)",
      [str(x) for x in synthetic.dates] == ["2026-09-15"] and synthetic.quality["dropped_short"] == 1,
      [str(x) for x in synthetic.dates])

# ═════════════════════════════════════════════════════════════════════════════════
section("NO PEEK — what the engine sees at minute u gives what the research computed")

if not (DM.DATA / "NIFTY").exists():
    print("  SKIP  research data not present — live/backtest parity not checked here")
else:
    from app.services.index_intraday.paper import HISTORY_DAYS
    full = DM.load("NIFTY")
    vix_full = DM.load("INDIAVIX")
    # the research's own computation: each family on the whole 2016-2026 history, every day complete
    ref_ctx = F.Ctx(full, vix_full)
    k0 = int(np.searchsorted(full.dates, np.datetime64("2023-01-01")))
    vix_days = set(vix_full.dates.tolist())
    # days the VIX series has (on the ~3% it dropped as incomplete the research had no regime;
    # live, today's VIX row always exists — a difference no engine could avoid, stated in the report)
    days = [k for k in range(k0 + 5, k0 + 245, 12) if full.dates[k].astype(object) in vix_days]
    probes = [("orb", {"orm": 15, "entry": "stop", "stop": "opp"}), ("orb", {"orm": 30, "entry": "close", "stop": "mid"}),
              ("pdhl", {"start": "09:30", "until": "14:30"}), ("volbreak", {"k": 0.5}), ("volbreak", {"k": 0.75, "vix": "low"}),
              ("volbreak", {"k": 0.5, "vix": "high"}),
              ("imom", {"signal_end": "09:45", "enter": "14:40", "from": "prev_close", "thr": 0.0}),
              ("ema", {"tf": 5, "fast": 9, "slow": 21, "mode": "state"}), ("supertrend", {"tf": 15, "n": 10, "mult": 3.0, "adx": 25}),
              ("rsi", {"tf": 5, "n": 14, "mode": "revert", "hi": 80, "lo": 20}), ("bollinger", {"tf": 5, "n": 20, "k": 2.0, "mode": "revert"}),
              ("vwap", {"tf": 5, "mode": "trend", "first": "10:00"}), ("pullback", {"first": "09:45"}), ("mtf", {"first": "09:45"}),
              ("gap", {"k": 0.3, "mode": "fade"}), ("trendday", {"at": "12:15", "k": 0.4}), ("regime", {})]

    def close(a, b):
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))

    def sl(d, a, b):
        return DM.Days(d.name, d.dates[a:b], d.o[a:b], d.h[a:b], d.l[a:b], d.c[a:b], d.v[a:b])

    mismatches, checked, early, signalled, sessions = [], 0, 0, 0, []
    for fam, p in probes:
        ref_specs = F.FAMILIES[fam](ref_ctx, p)[0]
        for di in days:
            day = full.dates[di].astype(object)
            since = np.datetime64(day - timedelta(days=HISTORY_DAYS))
            hist = sl(full, int(np.searchsorted(full.dates, since)), di)          # what load_recent gives the engine
            vk = int(np.searchsorted(vix_full.dates, full.dates[di]))
            vh = sl(vix_full, int(np.searchsorted(vix_full.dates, since)), vk)
            sessions.append(len(hist.dates))
            base = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
            mins = {base + 60 * m: (full.o[di, m], full.h[di, m], full.l[di, m], full.c[di, m], full.v[di, m]) for m in range(375)}
            vmins = {base + 60 * m: (vix_full.o[vk, m], vix_full.h[vk, m], vix_full.l[vk, m], vix_full.c[vk, m],
                                     vix_full.v[vk, m]) for m in range(375)}
            ref = ref_specs(di)(0)
            signalled += ref is not None
            # a market entry at minute m acts on bars up to m-1, so it is knowable once m-1 completes (u = m);
            # a stop entry at m triggers on minute m's own high / low, so it is knowable only at u = m + 1
            known = None if ref is None else ref.minute + (1 if ref.kind == "stop" else 0)
            checkpoints = [10, 45, 120, 200, 300] + ([ref.minute - 1, ref.minute, known, known + 1] if ref else [])
            for u in sorted({u for u in checkpoints if 1 <= u <= 375}):
                D_u = DM.with_today(hist, mins, day, u)
                V_u = DM.with_today(vh, vmins, day, u)
                got = F.FAMILIES[fam](F.Ctx(D_u, V_u), p)[0](len(D_u.dates) - 1)(0)
                checked += 1
                if ref is None or u < known:
                    # before the trigger is knowable the live call may not act: nothing, or a later minute
                    if got is not None and got.minute < u + (1 if got.kind == "stop" else 0):
                        early += 1
                        mismatches.append((fam, str(day), u, "early", got.minute))
                elif (got is None or got.minute != ref.minute or got.side != ref.side or got.kind != ref.kind
                      or not close(got.level, ref.level) or not close(got.stop, ref.stop)):
                    mismatches.append((fam, str(day), u, "differs", None if got is None else (got.minute, got.side, got.level),
                                       (ref.minute, ref.side, ref.level)))
    check(f"the engine's {HISTORY_DAYS}-day history ({min(sessions)}-{max(sessions)} sessions) is enough for the "
          f"VIX regime's 250-session median", min(sessions) >= 251, min(sessions))
    check(f"{len(probes)} families x {len(days)} real days, cut off at minute u: the engine's call gives the research's "
          f"full-history entry ({checked} checks, {signalled} entries)", not mismatches, mismatches[:4])
    check("…and never acts before its trigger minute (no look-ahead)", early == 0, early)

# ═════════════════════════════════════════════════════════════════════════════════
section("RISK — every limit, sizing, the streak pause, the drawdown halt")

cfg = R.RiskConfig()
st = R.DayState("2026-10-12", peak_equity=1_000_000.0)
at = lambda hh, mm: datetime(2026, 10, 12, hh, mm, tzinfo=IST)  # noqa: E731
check("defaults validate", cfg.validate() == [])
check("an entry inside the window with room under every limit is allowed", R.allow(cfg, st, at(10, 0), 0, 0.0, 1e6)[0])
check("before 09:20 and after 14:30 are refused", not R.allow(cfg, st, at(9, 17), 0, 0.0, 1e6)[0]
      and not R.allow(cfg, st, at(14, 31), 0, 0.0, 1e6)[0])
check("…but a last-half-hour family may enter until 14:45", R.allow(cfg, st, at(14, 40), 0, 0.0, 1e6, family_until="14:45")[0])
check("the concurrent-position cap refuses", not R.allow(cfg, st, at(10, 0), 3, 0.0, 1e6)[0])
st.trades = 10
check("the trades-per-day cap refuses", not R.allow(cfg, st, at(10, 0), 0, 0.0, 1e6)[0])
st.trades = 0
check("the daily loss limit counts open losses too", not R.allow(cfg, st, at(10, 0), 1, -15_001.0, 1e6)[0]
      and R.allow(cfg, st, at(10, 0), 1, -14_000.0, 1e6)[0])
cfg_e = R.RiskConfig(emergency_stop=True)
check("the emergency stop refuses every entry", not R.allow(cfg_e, st, at(10, 0), 0, 0.0, 1e6)[0])
nt, how = R.size(cfg, 1e6, 22000.0, 21780.0, None)
check("size follows the risk budget: 0.5% of equity to a stop 1% away = Rs5 lakh",
      abs(nt - 500_000.0) < 1e-6 and "cap" not in how, (round(nt), how))
nt2, how2 = R.size(cfg, 1e6, 22000.0, 21990.0, None)
check("a tight stop is capped at the position limit (no leverage)", nt2 == 1e6 and "cap" in how2)
nt3, _ = R.size(cfg, 1e6, 22000.0, None, 400.0)
check("no stop: sized as if the stop were half an ATR away (ATR 400 -> 200 points -> Rs5.5 lakh)",
      abs(nt3 - 0.005 * 1e6 / 200.0 * 22000.0) < 1e-6, round(nt3))
s2 = R.DayState("2026-10-12", peak_equity=1e6)
for k in range(3):
    s2 = R.after_close(cfg, s2, -1000.0, at(11, 0), 1e6 - 1000 * (k + 1))
check("three losses in a row pause entries for an hour", s2.paused_until == "12:00"
      and not R.allow(cfg, s2, at(11, 30), 0, 0.0, 1e6)[0] and R.allow(cfg, s2, at(12, 0), 0, 0.0, 1e6)[0])
s3 = R.after_close(cfg, R.DayState("2026-10-12", peak_equity=1e6), -80_000.0, at(11, 0), 920_000.0)
check("a drawdown of 8% from peak halts entries until reset", s3.halted and not R.allow(cfg, s3, at(11, 5), 0, 0.0, 9.2e5)[0])
check("invalid settings are refused with the reason", any("leverage" in p for p in R.RiskConfig(max_position_pct=200).validate()))

# ═════════════════════════════════════════════════════════════════════════════════
section("COSTS — Angel's charges, measured spreads, the liquidity cap")

check("an ETF intraday round trip at Rs10 lakh costs ~4.0 bp in charges", 3.9 < fee_rt_bp(280.0) < 4.1, round(fee_rt_bp(280.0), 3))
check("the slippage table is the measured half-spread (NIFTYBEES 1.0, NIF100BEES 21.2 bp)",
      ROUTE["NIFTY"][2] == 1.0 and ROUTE["NIFTY100"][2] == 21.2 and ROUTE["BANKEX"][0] is None)
check("an ETF order is capped at a quarter of a median minute's value (NIFTYBEES Rs5.05 lakh)",
      abs(max_etf_order("NIFTYBEES") - 505_000) < 1 and max_etf_order(None) == 0.0)

# ═════════════════════════════════════════════════════════════════════════════════
section("HISTORY HEAL — a missing or refused day is fetched again until stored; today only after its close")

import shutil  # noqa: E402
import tempfile  # noqa: E402

from app.services import market_calendar as MC  # noqa: E402
from app.services.index_intraday import feed as FD  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="idx1m_"))
real_store, real_data, real_client = FD.STORE, DM.DATA, FD.angel_client
FD.STORE, DM.DATA = str(tmp), tmp
asked = []


def _day_rows(d):
    """A full session: 375 one-minute candles, 09:15 .. 15:29."""
    out = []
    for m in range(375):
        t = 9 * 60 + 15 + m
        out.append([f"{d.isoformat()}T{t // 60:02d}:{t % 60:02d}:00+05:30", 100.0, 101.0, 99.0, 100.5, 0])
    return out


async def fake_candles(exch, tok, interval, frm, to, bulk=False):
    asked.append((frm, to))
    a, b = date.fromisoformat(frm[:10]), date.fromisoformat(to[:10])
    out, d = [], a
    while d <= b:
        if MC.is_trading_day(d):
            out += _day_rows(d)
        d += timedelta(days=1)
    return out


try:
    FD.angel_client = types.SimpleNamespace(candles=fake_candles)
    now = datetime(2026, 10, 12, 9, 2, tzinfo=IST)                 # a Monday, before the open
    trading = [date(2026, 9, 12) + timedelta(days=k) for k in range(30)]
    trading = [d for d in trading if d < now.date() and MC.is_trading_day(d)]
    gone = {trading[3], trading[-1]}                                 # one old gap, and "yesterday" (Friday)
    for d in trading:
        if d not in gone:
            FD.feed._write_day("NIFTY", d, _day_rows(d))
    out = run(FD.feed.heal(["NIFTY"], now=now))
    filled = set(out.get("NIFTY", {}).get("filled", []))
    check("the missing trading days — an old gap and the last session — are fetched and written",
          filled == {d.isoformat() for d in gone}, out)
    check("one request, spanning only the missing days, and never reaching today",
          len(asked) == 1 and asked[0][0].startswith(min(gone).isoformat()) and asked[0][1].startswith(max(gone).isoformat()),
          asked)
    check("weekends and the Gandhi Jayanti holiday (2 Oct) are not 'missing'", date(2026, 10, 2) not in trading
          and all(MC.is_trading_day(d) for d in trading))
    asked.clear()
    run(FD.feed.heal(["NIFTY"], now=now))
    check("a second heal finds nothing missing and asks for nothing", not asked, asked)
    d = DM._build("NIFTY", DM._read("NIFTY", date(2026, 9, 12)))
    check("the healed store loads as complete sessions (none dropped, the gap closed)",
          set(d.dates.astype(object).tolist()) == set(trading), (len(d.dates), len(trading)))

    # today: never before its session is over; once it is, fetched like any missing day
    asked.clear()
    run(FD.feed.heal(["NIFTY"], now=datetime(2026, 10, 12, 14, 0, tzinfo=IST), include_today=True))
    check("include_today before 15:35: today's unfinished session is not fetched", not asked, asked)
    out = run(FD.feed.heal(["NIFTY"], now=datetime(2026, 10, 12, 16, 0, tzinfo=IST), include_today=True))
    check("include_today after the close: today is fetched, stored and its rows reported",
          out.get("NIFTY", {}).get("rows") == {"2026-10-12": 375} and len(asked) == 1, (out, asked))

    # nothing missing = no broker call and no data read: each day is its own file
    reads = []
    real_dwr = FD.days_with_rows
    FD.days_with_rows = lambda *a, **k: (reads.append(a), real_dwr(*a, **k))[1]
    asked.clear()
    run(FD.feed.heal(["NIFTY"], now=datetime(2026, 10, 12, 16, 5, tzinfo=IST), include_today=True))
    FD.days_with_rows = real_dwr
    check("a heal with nothing missing makes no broker call and reads no history file", not asked and not reads,
          (asked, reads))

    # a refused fetch: reported as an error; the next out-of-hours pass fills it and fixes the report
    from app.services import desk_switches as DS
    from app.services.index_intraday import report as REP
    from app.services.index_intraday import scheduler as SCH
    os.remove(os.path.join(FD.STORE, "NIFTY", "2026-10-12.csv.gz"))

    async def refused(*a, **k):
        asked.append(a[3:5])
        raise RuntimeError("Angel returned non-JSON (403)")
    FD.angel_client = types.SimpleNamespace(candles=refused)
    asked.clear()
    out = run(FD.feed.heal(["NIFTY"], now=datetime(2026, 10, 12, 16, 10, tzinfo=IST), include_today=True))
    check("a refused fetch is reported as an error, nothing is written",
          str(out.get("NIFTY", "")).startswith("error") and
          not os.path.exists(os.path.join(FD.STORE, "NIFTY", "2026-10-12.csv.gz")), out)
    FD.angel_client = types.SimpleNamespace(candles=fake_candles)
    real_reports, real_is_on, real_instruments = REP.REPORTS, DS.is_on, FD.INSTRUMENTS
    REP.REPORTS = Coll("reports")
    REP.REPORTS.docs.append({"_id": "2026-10-12", "history_appended": {"NIFTY": "error: Angel returned non-JSON (403)"}})
    # a day stored by some other path (an old heal, a restart, by hand) while its report kept the error
    REP.REPORTS.docs.append({"_id": "2026-10-09", "history_appended": {"NIFTY": "error: Angel returned non-JSON (403)",
                                                                       "BANKNIFTY": "error: Angel returned non-JSON (403)"}})

    async def on(key):
        return True
    DS.is_on = on
    FD.INSTRUMENTS = {"NIFTY": real_instruments["NIFTY"]}
    try:
        asked.clear()
        busy = run(SCH.history_pass(datetime(2026, 10, 12, 15, 50, tzinfo=IST)))
        check("the hourly pass stays out of the trading day (until 16:30): no heal at 15:50", busy == {} and not asked,
              (busy, asked))
        done = run(SCH.history_pass(datetime(2026, 10, 12, 18, 0, tzinfo=IST)))
        check("…after it, the refused day is fetched again and stored",
              done.get("NIFTY", {}).get("filled") == ["2026-10-12"] and
              os.path.exists(os.path.join(FD.STORE, "NIFTY", "2026-10-12.csv.gz")), done)
        check("…and the day's report now shows the instrument stored, not the error",
              REP.REPORTS.docs[0]["history_appended"]["NIFTY"] == 375, REP.REPORTS.docs[0])
        check("…and an older report is reconciled with the store: NIFTY's file exists (375 rows), BANKNIFTY's does "
              "not (its error stays)",
              REP.REPORTS.docs[1]["history_appended"]["NIFTY"] == 375
              and str(REP.REPORTS.docs[1]["history_appended"]["BANKNIFTY"]).startswith("error"), REP.REPORTS.docs[1])
        asked.clear()
        again = run(SCH.history_pass(datetime(2026, 10, 12, 19, 0, tzinfo=IST)))
        check("…and the next hour has nothing to do: no broker call", again == {} and not asked, (again, asked))
    finally:
        REP.REPORTS, DS.is_on, FD.INSTRUMENTS = real_reports, real_is_on, real_instruments
finally:
    FD.STORE, DM.DATA, FD.angel_client = real_store, real_data, real_client
    shutil.rmtree(tmp, ignore_errors=True)

# ═════════════════════════════════════════════════════════════════════════════════
section("ENGINE — minute-by-minute paper trading equals the backtest")

from app.services import market_calendar  # noqa: E402
from app.services.index_intraday import paper as P  # noqa: E402

market_calendar.is_trading_day = lambda *a, **k: True
P.STATE, P.POS, P.TRADES, P.EQUITY, P.EVENTS = Coll("state"), Coll("pos"), Coll("trades"), Coll("equity"), Coll("events")

# 30 quiet days, then a breakout day: up through open + 0.5 ATR at 09:55, on to the 2R target
rs = np.random.default_rng(7)
H = 30
hd = np.array([np.datetime64("2026-09-01") + np.timedelta64(k, "D") for k in range(H)])
base_px = 20000.0
ho = np.full((H, 375), base_px)
hc = ho + rs.normal(0, 5, (H, 375)).cumsum(axis=1) * 0.2
hh = np.maximum(ho, hc) + 20.0
hl = np.minimum(ho, hc) - 20.0
hist = DM.Days("NIFTY", hd, ho, hh, hl, hc, np.zeros((H, 375)))
vhist = DM.Days("INDIAVIX", hd, np.full((H, 375), 14.0), np.full((H, 375), 14.5), np.full((H, 375), 13.5),
                np.full((H, 375), 14.0), np.zeros((H, 375)))
DAY = date(2026, 10, 12)
ctx_h = F.Ctx(DM.with_today(hist, {}, DAY, 0), None)
atr = float(ctx_h.day_atr[-1])
o0 = 20000.0
lvl = o0 + 0.5 * atr
path = np.r_[np.linspace(o0, lvl - 1, 40), np.linspace(lvl + 1, lvl + 2.2 * 0.5 * atr, 60),
             np.full(275, lvl + 2.2 * 0.5 * atr)]
t_open = path.copy()
t_close = np.r_[path[1:], path[-1]]
t_high = np.maximum(t_open, t_close) + 0.2
t_low = np.minimum(t_open, t_close) - 0.2
base = int(datetime(2026, 10, 12, 9, 15, tzinfo=IST).timestamp())
TODAY = {base + 60 * m: (float(t_open[m]), float(t_high[m]), float(t_low[m]), float(t_close[m]), 0.0) for m in range(375)}


class FakeFeed:
    def __init__(self):
        self.upto = 0

    def today(self, symbol, now=None):
        if symbol == "INDIAVIX":
            return {}
        return {t: b for t, b in TODAY.items() if t < base + 60 * self.upto}

    def holes(self, symbol, now=None):
        return 0

    async def backfill(self, *a, **k):
        return 0

    def ltp(self, symbol, max_age_s=90):
        return float(t_open[min(self.upto, 374)]) if symbol == "NIFTY" else None


ff = FakeFeed()
P.feed = ff
P.load_recent = lambda sym, days=120: vhist if sym == "INDIAVIX" else hist

volb = [s for s in cat.strategies(index="NIFTY", family="volbreak", limit=2000) if s["params"] == {"k": 0.5} and s["exit"] == "r2"]
check("the catalogue holds the volatility breakout k 0.5 / 2R on NIFTY", len(volb) == 1)
sid = volb[0]["id"]
run(P.set_config({"capital": 1_000_000.0, "risk_per_trade_pct": 5.0}))      # size to the Rs10 lakh cap
run(P.set_deployment(sid, True, "index"))
opened_at = closed_at = None
for upto in range(1, 376):
    ff.upto = upto
    now = datetime(2026, 10, 12, 9, 15, tzinfo=IST) + timedelta(minutes=upto, seconds=5)
    r = run(P.engine.tick(now, entries_allowed=True))
    if r["opened"] and opened_at is None:
        opened_at = upto
    if r["closed"] and closed_at is None:
        closed_at = upto
pos = P.POS.docs[0] if P.POS.docs else {}
tr = P.TRADES.docs[0] if P.TRADES.docs else {}
# the backtest on the same day
D_full = DM.with_today(hist, TODAY, DAY, 375)
ctx_f = F.Ctx(D_full, None)
spec_fn, _x, _mt = F.FAMILIES["volbreak"](ctx_f, {"k": 0.5})
from app.services.index_intraday.costs import costs_for  # noqa: E402
bt = E.simulate_day(D_full.o[-1], D_full.h[-1], D_full.l[-1], D_full.c[-1], spec_fn(len(D_full.dates) - 1),
                    F.EXITS["r2"], ctx_f.day_atr[-1], costs_for("NIFTY"))
check("the backtest takes one trade that day: a long stop entry, out at its 2R target",
      len(bt) == 1 and bt[0].side == 1 and bt[0].reason == "target", [(t.entry_min, t.exit_min, t.reason) for t in bt])
check("paper opens on the minute the backtest entered, at the same price (level + slippage)",
      pos.get("entry_min") == bt[0].entry_min and abs(pos.get("fill", 0) - bt[0].entry_px) < 1e-6,
      (pos.get("entry_min"), bt[0].entry_min, pos.get("fill"), round(bt[0].entry_px, 4)))
check("…and closes on the backtest's exit minute, at its price, for the same reason",
      tr.get("exit_min") == bt[0].exit_min and abs(tr.get("exit", 0) - bt[0].exit_px) < 1e-6 and tr.get("exit_reason") == "target",
      (tr.get("exit_min"), bt[0].exit_min, tr.get("exit"), round(bt[0].exit_px, 4)))
check("net = gross - the ETF's charges at the actual notional",
      abs(tr["net"] - (tr["gross"] - tr["notional"] * fee_rt_bp(ROUTE["NIFTY"][1], tr["notional"]) / 1e4)) < 0.02)
check("one trade only (the family's limit)", len(P.TRADES.docs) == 1 and P.POS.docs[0]["status"] == "CLOSED")

# a restart after the trigger: the signal is seen too late and NOT entered
P.POS.docs.clear(); P.TRADES.docs.clear(); P.EVENTS.docs.clear()
ff.upto = 80
now = datetime(2026, 10, 12, 9, 15, tzinfo=IST) + timedelta(minutes=80, seconds=5)
r = run(P.engine.tick(now, entries_allowed=True))
check("a signal older than two minutes (an engine restart) is logged as missed, never entered late",
      r["opened"] == 0 and any(e["kind"] == "missed" for e in P.EVENTS.docs))

# square-off: a position still open at 15:12 is closed at that minute's (live) price
P.POS.docs.clear(); P.TRADES.docs.clear(); P.STATE.docs = [d for d in P.STATE.docs if not str(d.get("_id", "")).startswith("missed")]
run(P.set_deployment(sid, False, "index"))
P.POS.docs.append({"_id": "p1", "sid": sid, "key": volb[0]["key"], "family": "volbreak", "params": {"k": 0.5}, "exit": "eod",
                   "index": "NIFTY", "model": "index", "instrument": "NIFTY", "status": "OPEN", "side": 1, "day": "2026-10-12",
                   "entry_min": 200, "entry_time": "x", "entry_kind": "market", "entry_raw": 20100.0, "fill": 20102.0,
                   "units": 49.0, "notional": 49 * 20102.0, "stop": None, "target": None, "trail": None, "best": 20100.0,
                   "next_min": 200, "entry_cost": 0.0})
ff.upto = E.SQUARE_OFF
run(P.engine.tick(datetime(2026, 10, 12, 15, 12, 5, tzinfo=IST), entries_allowed=True))
check("15:12: an open position is squared off at the live price, labelled", P.TRADES.docs and
      P.TRADES.docs[0]["exit_reason"] == "square_off" and P.POS.docs[0]["status"] == "CLOSED")

# emergency stop: flatten everything and refuse entries
P.TRADES.docs.clear()
P.POS.docs[0] = {**P.POS.docs[0], "status": "OPEN", "_id": "p2", "next_min": 201}
ff.upto = 250
run(P.set_config({"emergency_stop": True}))
run(P.engine.tick(datetime(2026, 10, 12, 13, 25, 5, tzinfo=IST), entries_allowed=True))
check("the emergency stop flattens open positions at once", P.TRADES.docs and P.TRADES.docs[0]["exit_reason"] == "emergency_stop")
run(P.set_config({"emergency_stop": False}))

# the ETF model: fills at the touch, Angel's charges, the liquidity cap
P.POS.docs.clear(); P.TRADES.docs.clear()


async def touch(etf):
    return {"bid": 279.90, "ask": 280.00, "ltp": 279.95}
P.etf_touch = touch
run(P.set_deployment(sid, True, "etf"))
marks = []
for upto in range(1, 120):
    ff.upto = upto
    run(P.engine.tick(datetime(2026, 10, 12, 9, 15, tzinfo=IST) + timedelta(minutes=upto, seconds=5), entries_allowed=True))
    marks += [d["mark"] for d in P.POS.docs if d["status"] == "OPEN"]
ep = P.POS.docs[0] if P.POS.docs else {}
check("…an open ETF position is marked at an ETF price even with no ETF tick (never at the index level)",
      marks and max(marks) < 300, (min(marks or [0]), max(marks or [0])))
check("ETF model: the entry buys at the ask, in whole units, inside the liquidity cap",
      ep.get("fill") == 280.00 and float(ep.get("units", 0)).is_integer() and ep.get("units", 0) * 280.0 <= max_etf_order("NIFTYBEES"),
      (ep.get("fill"), ep.get("units")))
et = P.TRADES.docs[0] if P.TRADES.docs else {}
from app.services.angel_fees import round_trip  # noqa: E402
check("…exits at the bid and is charged Angel's intraday round trip on the real turnover",
      et.get("exit") == 279.90 and abs(et.get("costs", 0) - round_trip(280.0, 279.90, int(ep["units"]), "BUY", "INTRADAY").total) < 0.01,
      (et.get("exit"), et.get("costs")))
try:
    run(P.set_deployment([s for s in cat.strategies(index="BANKEX", limit=5)][0]["id"], True, "etf"))
    bankex_refused = False
except ValueError:
    bankex_refused = True
check("BANKEX cannot run on the ETF model — it has no ETF", bankex_refused)

# the cooldown after an exit: a strategy that just closed waits before its next entry
P.POS.docs.clear(); P.TRADES.docs.clear(); P.EVENTS.docs.clear()
P.STATE.docs = [d for d in P.STATE.docs if not str(d.get("_id", "")).startswith("day:") and d.get("_id") != "peak"]
run(P.set_deployment(sid, True, "index"))
run(P.set_config({"cooldown_after_exit_min": 30}))
P.TRADES.docs.append({"sid": sid, "key": volb[0]["key"], "index": "NIFTY", "model": "index", "day": "2026-10-12",
                      "exit_min": 93, "net": 50.0, "gross": 90.0, "costs": 40.0, "exit_reason": "target"})
real_volbreak = F.FAMILIES["volbreak"]
F.FAMILIES["volbreak"] = lambda ctx, p: (
    lambda i: (lambda after: E.EntrySpec(1, ff.upto - 1, "market", None, None) if after <= ff.upto - 1 else None),
    None, 5)
try:
    ff.upto = 100                                                  # 10:55, seven minutes after a 10:48 exit
    r1 = run(P.engine.tick(datetime(2026, 10, 12, 9, 15, tzinfo=IST) + timedelta(minutes=100, seconds=5), entries_allowed=True))
    ff.upto = 124                                                  # 11:19, past the 30-minute cooldown
    r2 = run(P.engine.tick(datetime(2026, 10, 12, 9, 15, tzinfo=IST) + timedelta(minutes=124, seconds=5), entries_allowed=True))
finally:
    F.FAMILIES["volbreak"] = real_volbreak
    run(P.set_config({"cooldown_after_exit_min": 0}))
check("the cooldown after an exit holds that strategy's next entry, then lets it through",
      r1["opened"] == 0 and any("cooldown" in n for n in r1["notes"]) and r2["opened"] == 1, (r1["notes"], r2["opened"]))

# ═════════════════════════════════════════════════════════════════════════════════
section("BACKTEST LAB — on the research's cost table a run reproduces the catalogue")

import json  # noqa: E402

from app.services.index_intraday import backtest as BT  # noqa: E402

if not (DM.DATA / "NIFTY").exists():
    print("  SKIP  research data not present — the Lab was not run here")
else:
    picks = [s for s in cat.strategies(limit=5000) if s["stage2"]][:3]
    picks += [cat.strategies(index="NIFTY", family="orb", min_trades=150, limit=1)[0],
              cat.strategies(index="BANKNIFTY", family="ema", min_trades=150, limit=1)[0]]
    rows = []
    for s in picks:
        r = BT.run_sync(s["family"], s["params"], s["exit"], s["index"], date(2022, 1, 1), date(2023, 12, 31),
                        cost_basis="research")
        rows.append((s["id"], s["key"], s["index"], s["val"]["trades"], r["stats"].get("trades"),
                     s["val"]["mean_net_bp"], r["stats"].get("mean_net_bp")))
    off = [x for x in rows if x[3] != x[4] or abs((x[5] or 0) - (x[6] or 0)) > 0.01]
    check(f"{len(rows)} catalogued strategies run over 2022-23 give the catalogue's validation trades and net bp",
          not off, off or [(x[0], x[4], round(x[6], 2)) for x in rows])
    r = BT.run_sync("volbreak", {"k": 0.5}, "r2", "NIFTY", date(2023, 1, 1), date(2023, 6, 30))
    check("a Lab result is plain JSON (no NaN / Infinity), whatever its stats",
          json.dumps(r, allow_nan=False) is not None and r["costs"]["basis"] == "measured")
    try:
        BT.run_sync("volbreak", {}, "r2", "NIFTY", date(2023, 1, 1), date(2023, 3, 1))
        msg = ""
    except ValueError as exc:
        msg = str(exc)
    check("a parameter the family needs but was not given is a readable error, not a crash", "needs the parameter" in msg, msg)
    try:
        BT.run_sync("volbreak", {"k": 0.5}, "r2", "NIFTY", date(2020, 1, 1), date(2023, 6, 30))
        msg = ""
    except ValueError as exc:
        msg = str(exc)
    check("more than three years a run is refused", "three years" in msg, msg)

# ═════════════════════════════════════════════════════════════════════════════════
section("CATALOG — the research, as the dashboard reads it")

hdr = cat.header()
alls = cat.strategies(limit=5000)
check("every registered trial is there (>= 1,208), ids unique", len(alls) >= 1208 and len({s["id"] for s in alls}) == len(alls),
      len(alls))
check("every status is on the ladder; the header's validated count matches",
      all(s["status"] in cat.STATUSES for s in alls) and hdr["validated"] == sum(s["status"] == "Validated" for s in alls))
check("every strategy that is not Validated states the first gate it failed",
      all(s["failed"] for s in alls if s["status"] != "Validated"))
check("no strategy is Paper Trading Approved (the holdout was never reached)",
      not any(s["status"] == "Paper Trading Approved" for s in alls))

finish()
