"""Market segments, data freshness, and why each strategy book is or is not trading.

After every cycle, `refresh(db, group, info)` adds to the desk's status document (premium_meta "status"):
  feeds.<feed>        where the data comes from, its instrument, the last bar that really arrived and its price, and a
                      state: live / closed / stale / no data, with the reason in plain words
  recorder            Delta Exchange's order-flow recorder (CP-14, CP-15): connected or not, since when, last message
  books.<account>     every book of the account: its segment, trades, P&L, state and the reason for that state
  segments.<segment>  the segment's totals, its latest closed trades and its open positions

A feed's state is worked out again at every refresh from the time of its last real bar, so a feed that stops shows as
stale within minutes. Nothing is ever substituted for a missing or old price: a book on a stale or closed feed simply
does not trade, and its row says why. Paper only: this module reads the desk's own records and data stores.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

import catalog as C
import feeds as F
from settings import BTC_START_T, DATA, IST, NY, PAPER_START, SH_START_T, YC_START_T
from settings import YC2_START_T  # noqa: E402

log = logging.getLogger("premium.segments")

SEGMENT = {"NIFTY": "in_options", "BANKNIFTY": "in_options", "NIFTY_D": "in_options",
           "VWAP": "in_equity", "NSE15": "in_equity", "NSE5": "in_equity", "MIRROR15": "in_equity", "NSED": "in_equity_daily",
           "BTCUSD": "crypto", "BTC_SPOT": "crypto", "ETHUSD": "crypto", "XAUUSD": "gold", "XAUTUSD": "gold",
           "EURUSD": "global", "GBPUSD": "global", "NAS100": "global", "AAPL": "global", "SPX500_D": "global", "NAS100_D": "global"}
FEED_OF = {"XAUTUSD": "XAUUSD", "BTC_SPOT": "BTCUSD", "VWAP": "NSE", "NSE15": "NSE", "NSE5": "NSE", "MIRROR15": "NSE"}
DAILY = ("NSED", "NIFTY_D", "SPX500_D", "NAS100_D")
SOURCE = {
    "BTCUSD": ("Delta Exchange India", "BTCUSD perpetual, 1-minute candles"),
    "ETHUSD": ("Delta Exchange India", "ETHUSD perpetual, 1-minute candles"),
    "XAUUSD": ("Delta Exchange India", "XAUTUSD perpetual (Tether Gold, 1 token = 1 troy ounce), 1-minute candles"),
    "XAGUSD": ("Yahoo Finance", "SI=F COMEX silver futures, 1-minute (CP-24's companion)"),
    "EURUSD": ("Yahoo Finance", "6E=F CME euro futures, 1-minute"), "GBPUSD": ("Yahoo Finance", "6B=F CME pound futures, 1-minute"),
    "NAS100": ("Yahoo Finance", "NQ=F Nasdaq 100 futures, cash hours"), "AAPL": ("Yahoo Finance", "AAPL, regular session"),
    "SPX500_D": ("Yahoo Finance", "^GSPC daily"), "NAS100_D": ("Yahoo Finance", "^NDX daily"),
    "NIFTY": ("Angel One, through the app's backend", "Nifty 50 index, 1-minute"),
    "BANKNIFTY": ("Angel One, through the app's backend", "Nifty Bank index, 1-minute"),
    "NIFTY_D": ("Angel One", "Nifty 50 daily, from the 1-minute store"),
    "NSE": ("Angel One, through the app's backend", "NSE stocks, 5-minute"), "NSED": ("NSE", "daily bhavcopy"),
}
STALE_S = {"crypto": 600, "gold": 600, "global": 1500, "in_options": 600, "in_equity": 1800}


def _ny(now_utc: datetime) -> datetime:
    return now_utc.astimezone(NY)


def weekly_closed(now_utc: datetime) -> bool:
    """Gold and forex trade from Sunday 17:00 to Friday 17:00 New York."""
    n = _ny(now_utc)
    wd, hm = n.weekday(), n.hour * 60 + n.minute
    return wd == 5 or (wd == 4 and hm >= 17 * 60) or (wd == 6 and hm < 17 * 60)


def next_week_open_ist(now_utc: datetime) -> str:
    n = _ny(now_utc)
    opens = (n + timedelta(days=(6 - n.weekday()) % 7)).replace(hour=17, minute=0, second=0, microsecond=0)
    if opens <= n:
        opens += timedelta(days=7)
    return opens.astimezone(IST).strftime("%a %d %b, %H:%M IST")


def india_open(now_utc: datetime) -> bool:
    n = now_utc.astimezone(IST)
    return n.weekday() < 5 and "09:15" <= n.strftime("%H:%M") < "15:30"


def cash_open_ny(now_utc: datetime) -> bool:
    n = _ny(now_utc)
    return n.weekday() < 5 and 9 * 60 + 30 <= n.hour * 60 + n.minute < 16 * 60


def _ist(t: int | None) -> str:
    return datetime.fromtimestamp(t, IST).strftime("%d %b %H:%M") if t else "-"


def feed_state(fid: str, fd: dict, now_utc: datetime) -> tuple[str, str, str]:
    """(state, reason, short reason for a strategy's row) of one feed now, from the time of its last real bar."""
    seg = SEGMENT.get(fid, "in_equity" if fid == "NSE" else "global")
    if fid in DAILY:
        ls = fd.get("last_session")
        if not ls:
            return "no data", "No daily bars yet.", "No daily bars yet."
        age_d = (now_utc.astimezone(IST).date() - date.fromisoformat(ls)).days
        if age_d > 4:
            return ("stale", f"The last daily bar is {ls}, {age_d} days ago: not trading on old prices.",
                    f"Last daily bar {ls}: not trading on old prices.")
        return "live", f"Daily bars up to {ls}; the next one arrives after that market's next close.", ""
    last_t = fd.get("last_t")
    if fid == "XAUUSD" and weekly_closed(now_utc):
        nxt = next_week_open_ist(now_utc)
        return ("closed", "Gold's trading week is closed (Friday 17:00 to Sunday 17:00 New York). XAUTUSD keeps trading on Delta, "
                          f"but the gold strategies follow the gold week, as tested. Next session {nxt}.",
                f"Gold's week is closed; next session {nxt}.")
    if fid in ("EURUSD", "GBPUSD", "XAGUSD") and weekly_closed(now_utc):
        nxt = next_week_open_ist(now_utc)
        return "closed", f"Forex and metals futures are closed for the weekend. Next session {nxt}.", f"Weekend; next session {nxt}."
    if fid in ("NAS100", "AAPL") and not cash_open_ny(now_utc):
        return ("closed", "The US cash session is closed (09:30-16:00 New York, Monday to Friday).",
                "US cash session closed (opens 09:30 New York).")
    if fid in ("NIFTY", "BANKNIFTY", "NSE") and not india_open(now_utc):
        return "closed", "NSE is closed (09:15-15:30 IST, Monday to Friday).", "NSE closed (opens 09:15 IST, Monday to Friday)."
    if last_t is None:
        if fid in ("NIFTY", "BANKNIFTY", "NSE"):
            return ("no data", "No live bars have arrived today from the app's backend (on an NSE holiday this is expected).",
                    "No live bars today yet.")
        return "no data", "No bars received yet.", "No bars received yet."
    age = now_utc.timestamp() - last_t
    if age > STALE_S.get(seg, 900):
        why = f"No new bar since {_ist(last_t)} IST ({int(age // 60)} min ago): not trading on old prices."
        if fd.get("fetch_error"):
            why += f" Last fetch failed: {fd['fetch_error']}"
        return "stale", why, f"No new bar for {int(age // 60)} min: not trading on old prices."
    return "live", f"Last bar {_ist(last_t)} IST.", ""


def recorder_status() -> dict:
    try:
        return json.loads((DATA / "flow" / "status.json").read_text())
    except Exception:  # noqa: BLE001
        return {"connected": False, "error": "no status from the recorder yet (it writes one every 20 seconds while it runs)"}


def _last_bar(store: str) -> tuple[int | None, float | None]:
    t, c = F._read_cols(store, F._ym(int(time.time()) - 40 * 86400), ("t", "c"))
    if not len(t):
        return None, None
    return int(t[-1]), float(c[-1])


def feeds_now(group: str, info: dict) -> dict:
    """What this cycle learnt about its group's feeds (a feed it did not see keeps its previous entry)."""
    out: dict = {}
    errors = info.get("errors") or {}
    if group == "global":
        for fid, store in (("BTCUSD", F.DELTA_STORES["BTCUSD"]), ("ETHUSD", F.DELTA_STORES["ETHUSD"]),
                           ("XAUUSD", F.DELTA_STORES["XAUTUSD"]), ("EURUSD", "EURUSD"),
                           ("GBPUSD", "GBPUSD"), ("NAS100", "NAS100"), ("AAPL", "AAPL"), ("XAGUSD", "XAGUSD")):
            t, p = _last_bar(store)
            out[fid] = {"last_t": t, "last_price": p, "fetch_error": errors.get(f"feed {fid}")}
    elif group == "index":
        for fid in ("NIFTY", "BANKNIFTY"):
            t = F.LIVE_LAST.get(fid)
            out[fid] = {"last_t": t, "last_price": None, "fetch_error": None}
    elif group == "stocks":
        out["NSE"] = {"last_t": F.LIVE_LAST.get("NSE"), "last_price": None, "fetch_error": None}
    elif group == "daily":
        nse = info.get("nse") or {}
        if nse.get("last"):
            out["NSED"] = {"last_session": nse["last"]}
        for fid, ls in (info.get("lasts") or {}).items():
            out[fid] = {"last_session": ls}
    return out


def _start_of(mk: str, acct=None) -> datetime:
    if acct is not None and acct.source == getattr(C, "YC2", None):
        return datetime.fromtimestamp(YC2_START_T, timezone.utc)
    if acct is not None and acct.source == getattr(C, "YC", None):
        return datetime.fromtimestamp(YC_START_T, timezone.utc)
    if mk == "BTCUSD" and acct is not None and acct.source == getattr(C, "SH", None):
        return datetime.fromtimestamp(SH_START_T, timezone.utc)
    if mk == "BTCUSD":
        return datetime.fromtimestamp(BTC_START_T, timezone.utc)
    return datetime(PAPER_START.year, PAPER_START.month, PAPER_START.day, tzinfo=IST)


def refresh(db, group: str, info: dict) -> None:
    """Never raises: a status panel must not stop the desk."""
    try:
        _refresh(db, group, info)
    except Exception:  # noqa: BLE001
        log.exception("segment status")


def _book_state(a, mk: str, key: str, s: dict, fd: dict | None, sig: dict, errors: dict, rec: dict, now: datetime) -> tuple[str, str]:
    start = _start_of(mk, a)
    if key in errors:
        return "error", f"This book could not run in the last cycle: {errors[key]}"
    if now < start:
        return "waiting", f"Starts {start.astimezone(IST).strftime('%d %b, %H:%M IST')}; nothing is back-filled before that."
    if fd is None:
        return "no data", "No market data has reached the desk yet."
    if s["open"]:
        why = f"In a trade since {_ist(s['open_since'])} IST, marked at the last bar."
        if fd["state"] != "live":
            why += f" Its feed: {fd.get('short') or fd['reason']}"
        return "in trade", why
    yc2 = a.source == getattr(C, "YC2", None)
    if fd["state"] != "live":
        if yc2 and fd["state"] == "closed":
            return "armed", f"Armed — waiting for market open. {fd.get('short') or fd['reason']}"
        if yc2:
            return fd["state"], f"No new entries: {fd.get('short') or fd['reason']}"
        return fd["state"], fd.get("short") or fd["reason"]
    if a.id in ("CP-14", "CP-15", "SH-02") and mk == "BTCUSD" and not rec.get("connected"):
        return "waiting", ("Delta's trade feed is not connected, so the order-flow delta of new minutes is unknown: "
                           "no trade on those minutes until it reconnects.")
    if sig.get("today") and sig.get("last_t") and sig.get("taken") is False:
        return "live", f"Latest setup at {_ist(sig['last_t'])} IST was not taken: {sig.get('why') or 'see the rules'}."
    if mk in DAILY or mk == "BTC_SPOT":
        return "live", "A daily book: it acts once a day, on each finished daily bar."
    n = sig.get("n_today") or 0
    if yc2:
        return "running", ("Running — waiting for signal." if not n
                           else f"Running — {n} setup{'s' if n != 1 else ''} in the current session.")
    return "live", ("Watching every new bar; no setup yet in the current session." if not n
                    else f"{n} setup{'s' if n != 1 else ''} in the current session.")


def _refresh(db, group: str, info: dict) -> None:
    import runner as R
    now = datetime.now(timezone.utc)
    status = db.premium_meta.find_one({"_id": "status"}) or {}
    # 1. feeds: this cycle's news, then every feed's state worked out again for now
    feeds = {k: dict(v) for k, v in (status.get("feeds") or {}).items()}
    for fid, new in feeds_now(group, info).items():
        feeds.setdefault(fid, {}).update(new)
        feeds[fid]["checked_at"] = now.isoformat()
    for fid, fd in feeds.items():
        src, inst = SOURCE.get(fid, ("", fid))
        fd["source"], fd["instrument"] = src, inst
        fd["state"], fd["reason"], fd["short"] = feed_state(fid, fd, now)
    rec = recorder_status()
    # 2. the latest setup of every book this cycle ran
    for key, s in R.LAST_SIGNALS.items():
        db.premium_books.update_one({"_id": key}, {"$set": {"signal": s, "signal_at": now}}, upsert=True)
    signals = {d["_id"]: d.get("signal") or {} for d in db.premium_books.find({}, {"signal": 1})}
    errors: dict = {}
    for g in (status.get("groups") or {}).values():
        errors.update((g.get("info") or {}).get("errors") or {})
    errors.update(info.get("errors") or {})
    # 3. each book's trades
    blank = {"trades": 0, "closed": 0, "wins": 0, "pnl": 0.0, "open": 0, "unrealised": 0.0, "skipped": 0, "open_since": None}
    stats: dict = {}
    for d in db.premium_trades.find({}, {"acct": 1, "mkt": 1, "pnl": 1, "qty": 1, "open": 1, "entry_t": 1, "skip": 1}):
        s = stats.setdefault(f"{d['acct']}|{d['mkt']}", dict(blank))
        if not d.get("qty"):
            s["skipped"] += bool(d.get("skip"))
            continue
        s["trades"] += 1
        s["pnl"] += d.get("pnl") or 0.0
        if d.get("open"):
            s["open"] += 1
            s["unrealised"] += d.get("pnl") or 0.0
            s["open_since"] = min(s["open_since"] or d["entry_t"], d["entry_t"])
        else:
            s["closed"] += 1
            s["wins"] += (d.get("pnl") or 0) > 0
    # 4. every book's state, and the segments' totals
    books: dict = {}
    seg_tot: dict = {}
    for a in C.ACCOUNTS:
        rows = []
        for mk, _v in a.books:
            seg = SEGMENT.get(mk, "global")
            key = f"{a.id}|{mk}"
            s = stats.get(key, blank)
            fid = FEED_OF.get(mk, mk)
            state, why = _book_state(a, mk, key, s, feeds.get(fid), signals.get(key) or {}, errors, rec, now)
            if a.source == getattr(C, "YC2", None):
                sg = signals.get(key) or {}
                extra = {"signal": {k: sg.get(k) for k in ("last_t", "today", "taken", "why", "n_today")}}
            else:
                extra = {}
            rows.append({**extra, "mkt": mk, "market": C.LABEL.get(mk, mk), "segment": seg, "feed": fid, "state": state, "reason": why,
                         **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()}})
            t = seg_tot.setdefault(seg, {"books": 0, "trades": 0, "closed": 0, "wins": 0, "pnl": 0.0, "open": 0, "unrealised": 0.0,
                                         "states": {}})
            t["books"] += 1
            t["states"][state] = t["states"].get(state, 0) + 1
            for k in ("trades", "closed", "wins", "open"):
                t[k] += s[k]
            t["pnl"] += s["pnl"]
            t["unrealised"] += s["unrealised"]
        books[a.id] = rows
    recent: dict = {}
    for d in db.premium_trades.find({"open": False, "qty": {"$gt": 0}}, {"_id": 0}).sort("exit_t", -1).limit(800):
        seg = SEGMENT.get(d.get("mkt"), "global")
        if len(recent.setdefault(seg, [])) < 40:
            recent[seg].append(_trade_row(d))
    positions: dict = {}
    for d in db.premium_trades.find({"open": True, "qty": {"$gt": 0}}, {"_id": 0}).sort("entry_t", -1):
        positions.setdefault(SEGMENT.get(d.get("mkt"), "global"), []).append(_trade_row(d))
    segs = {seg: {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()},
                  "recent": recent.get(seg, []), "positions": positions.get(seg, [])} for seg, t in seg_tot.items()}
    db.premium_meta.update_one({"_id": "status"}, {"$set": {"feeds": feeds, "recorder": rec, "books": books, "segments": segs,
                                                            "segments_at": now.isoformat(),
                                                            "sh_start": datetime.fromtimestamp(SH_START_T, timezone.utc).isoformat(),
                                                            "yc2_start": datetime.fromtimestamp(YC2_START_T, timezone.utc).isoformat()}},
                               upsert=True)


def _trade_row(d: dict) -> dict:
    return {"acct": d.get("acct"), "mkt": d.get("mkt"), "market": C.LABEL.get(d.get("mkt"), d.get("mkt")), "sym": d.get("sym"),
            "side": d.get("side"), "setup": d.get("setup"), "entry_t": d.get("entry_t"), "exit_t": d.get("exit_t"),
            "entry": d.get("entry"), "exit": d.get("exit"), "last": d.get("last"), "stop": d.get("stop"), "target": d.get("target"),
            "qty": d.get("qty"), "pnl": d.get("pnl"), "reason": d.get("reason"), "sealed": d.get("sealed")}
