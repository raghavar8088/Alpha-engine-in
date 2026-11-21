"""Morning scanner scheduler and isolated simulated equity books.

21 Nov 2026 (the module moved to its own page, /stock-momentum, with its own Main Control switch):
- EXITS no longer need the five-second quote that ENTRIES need. A stop or target is judged on a quote up to
  EXIT_QUOTE_S old; once a position is due (15:10) any quote from the last LATE_QUOTE_S closes it; still nothing
  LAST_BAR_AFTER_S after the deadline, it closes at its last stored five-minute close. A position left from an
  earlier session (the loop stops at 15:30) closes at its last close before its own square-off, never at the next
  day's price. Every close records its exit price, why it closed and on what price.
- The 09:30 board is scanned again (at most once a minute, until 09:45) while stocks still lack their opening bars,
  so a scan that ran a few seconds before the last opening bar arrived does not freeze a partial board for the day.
- The loop runs through desk_switches.gated("stock_momentum"): OFF stops new entries, open positions are still
  managed to their exits, and a flat book pauses. open_count() is the module's open-position probe.
"""
import asyncio
import logging
from bisect import bisect_right
from datetime import datetime
import json
from pathlib import Path
import time

from app.core.db import screener_meta_collection as db, stock_universe_collection
from app.services import market_calendar
from app.services.intraday_universe import symbols
from app.services.paper_broker.market import fno_underlyings
from app.services.mcx_market import parse_trade_time
from app.services.screener import morning as m
from app.services.screener.momentum import _live_quotes
from app.services.screener.morning_gates import EntryEvidence, entry_rejections
from app.services.stocks_range import INDEX_LABELS

log=logging.getLogger(__name__)
REPORT=json.loads((Path(__file__).resolve().parents[2]/"data/morning_replay.json").read_text())
_eligibility_cache = (0.0, set(), set())
MODULE_KEY = "stock_momentum"          # its Main Control switch (module_registry)
BOOK_RS = 100000                       # each universe's paper book
MAX_POSITIONS = 5
ENTRY_QUOTE_S = 5                      # an entry needs a quote this fresh (morning_gates)
EXIT_QUOTE_S = 60                      # a stop or a target is judged on a quote up to a minute old
LATE_QUOTE_S = 900                     # once due, any quote from the last 15 minutes closes the position
LAST_BAR_AFTER_S = 600                 # 10 minutes past the deadline and still no quote: the last 5-minute close
RESCAN_S = 60                          # rescans of an incomplete 09:30 board, at most once a minute until 09:45
MISSING_OPEN = "Missing Nifty or stock opening bars"
LIMITS = dict(book_rs=BOOK_RS, risk_rs=100, notional_rs=10000, max_positions=MAX_POSITIONS, entry_until="14:30",
              square_off="15:10", entry_quote_s=ENTRY_QUOTE_S, exit_quote_s=EXIT_QUOTE_S, late_quote_s=LATE_QUOTE_S)


def key(index):
    return "morning-equity-"+index

async def state(index):
    return await db.find_one({"_id":key(index)}) or dict(_id=key(index),scan=True,paper=False,approved=[],positions=[],recent=[])

async def controls(index,values):
    await db.update_one({"_id":key(index)},{"$set":values,"$inc":{"revision":1}},upsert=True)


async def open_count() -> int:
    """Open paper positions across every universe's book: Main Control's probe for this module."""
    n = 0
    async for d in db.find({"_id": {"$regex": "^morning-equity-"}}, {"positions": 1}):
        n += len(d.get("positions") or [])
    return n


def _live_bars(symbol, timeframe):
    """Combine the historical baseline with unflushed live five-minute candles."""
    disk = m.store.read_file(symbol, timeframe)
    if timeframe == "5m":
        disk.merge(m.store.store5.get(symbol).rows())
    return disk


def _last_close(symbol, before):
    """The close of the last five-minute bar that ended by `before` (epoch), or None."""
    try:
        b = m.store.store5.get(symbol)
        i = bisect_right(b.t, before - 300)
        return float(b.c[i - 1]) if i else None
    except Exception:  # noqa: BLE001 - a missing file must not stop the other exits
        log.exception("morning desk: no bars for %s", symbol)
        return None


def _close(p, price, now_ts, basis):
    """A closed position's record: net after costs (morning.resolve), exit price, why and on what price."""
    s = p["side"]
    net = m.resolve(p, (int(now_ts), price, price, price), p["deadline"])
    if net is None:
        return None
    why = "square-off" if now_ts >= p["deadline"] else ("stop" if (price - p["stop"]) * s <= 0 else "target")
    return {**p, "net": round(net, 2), "exit": round(price * (1 - s * .0005), 4), "why": why, "basis": basis}


async def _eligible_symbols():
    """Cache broker eligibility because every selected screener index shares it."""
    global _eligibility_cache
    cached_at, longs, shorts = _eligibility_cache
    if time.monotonic() - cached_at < 300:
        return longs, shorts
    longs = set(await symbols())
    shorts = {item["symbol"] for item in await fno_underlyings()}
    _eligibility_cache = (time.monotonic(), longs, shorts)
    return longs, shorts


def _entries_blocked() -> bool:
    """Main Control's drain flag. An older Main Control (no draining, as the box ran on 21 Nov) has no such
    function: then nothing is blocked from here, as before this module had a switch of its own."""
    try:
        from app.services.desk_switches import entries_blocked
    except ImportError:
        return False
    return entries_blocked()


async def tick(index,now):
    doc=await state(index)
    day=now.date().isoformat()
    start=int(now.replace(hour=9,minute=15,second=0,microsecond=0).timestamp())
    elapsed=int(now.timestamp())-start
    if elapsed<900: return
    board=doc.get("board",{})
    rescan=(elapsed<1800 and (not board.get("rows") or MISSING_OPEN in (board.get("excluded") or {}).values())
            and now.timestamp()-float(board.get("scanned_at") or 0)>=RESCAN_S)
    if doc.get("scan",True) and (board.get("day")!=day or rescan):
        members={d["symbol"]:d.get("sector") async for d in stock_universe_collection.find({"indices":index},{"symbol":1,"sector":1})}
        rows,excluded=await asyncio.to_thread(m.scan,start,members,_live_bars)
        board=dict(day=day,asof=day+"T09:30:00+05:30",processed=now.isoformat(),scanned_at=now.timestamp(),total=len(members),
                   usable=len(rows),rows=[r for r in rows if r.get("rank",999)<=10],excluded=excluded)
        await db.update_one({"_id":key(index)},{"$set":{"board":board}},upsert=True)
    positions=doc.get("positions",[])
    approved=doc.get("approved",[])
    enabled=(doc.get("paper",False) and approved and board.get("day")==day and elapsed<18900
             and not _entries_blocked())   # Main Control OFF: manage what is open, open nothing
    rows=board.get("rows",[]) if enabled else []
    if not rows and not positions: return
    quotes=await _live_quotes(sorted({p["symbol"] for p in positions+rows}))
    now=datetime.now(m.store.IST)
    held=[]
    recent=doc.get("recent",[])
    used=doc.get("used",[]) if doc.get("used_day")==day else []
    failed=list(doc.get("failed",[]))
    rejected=[]
    def quote(sym, max_age=ENTRY_QUOTE_S):
        q=quotes.get(sym,{})
        stamp=parse_trade_time(q.get("trade_time"))
        price=q.get("ltp") or 0
        if stamp and 0<price and 0<=(now-stamp).total_seconds()<=max_age:
            return float(price),stamp
        return None,None
    ts=now.timestamp()
    for p in positions:
        due=ts>=p["deadline"]
        if p["deadline"]<start:
            # left from an earlier session: its own square-off price, never today's (a quote only if no bar is stored)
            price,basis=_last_close(p["symbol"],p["deadline"]),"last 5-minute close before its square-off"
            if price is None:
                price,_=quote(p["symbol"],LATE_QUOTE_S)
                basis="quote (no stored close before its square-off)"
        else:
            price,_=quote(p["symbol"],LATE_QUOTE_S if due else EXIT_QUOTE_S)
            basis="quote"
            if price is None and ts>=p["deadline"]+LAST_BAR_AFTER_S:
                price,basis=_last_close(p["symbol"],p["deadline"]),"last 5-minute close (no quote)"
        if due and not price and p["id"] not in failed: failed.append(p["id"])
        done=_close(p,price,ts,basis) if price else None
        if done is None: held.append(p)
        else: recent.append({**done,"closed":now.isoformat()})
    eligible, short_eligible = await _eligible_symbols() if rows else (set(), set())
    # Intraday equity sells are admitted only for names that have a current F&O
    # underlying.  This makes the desk's paper behaviour match the short-selling
    # universe used by the broker-facing desks.
    for r in rows:
        sym=r["symbol"]
        b=m.store.store5.get(sym)
        count=int((now.timestamp()-start)//300)
        i=m.bisect_left(b.t,start)
        bars=list(b.rows(i,min(i+count,len(b))))
        if len(bars)!=count or any(x[0]!=start+300*k or not m.valid(x) for k,x in enumerate(bars)): continue
        for rule,side in m.triggers(r,bars):
            if rule not in approved or side!=r["side"]: continue
            identity=f"{day}/{sym}/{rule}"
            price,stamp=quote(sym)
            if not price:
                rejected.append([sym,rule,"stale_quote"])
                continue
            p=m.order(rule,side,r,bars[-1],price)
            if not p: continue
            margin=sum(x["qty"]*x["entry"] for x in held)
            ev=EntryEvidence(sym,"LONG" if side==1 else "SHORT",datetime.fromtimestamp(start+count*300,m.store.IST),
                stamp,p["entry"],p["stop"],p["target"],p["qty"],m.round_trip(p["entry"],p["target"],p["qty"],"BUY" if side==1 else "SELL").total,
                p["entry"]*p["qty"],BOOK_RS-margin)
            reasons=entry_rejections(ev,now,trading_session=market_calendar.in_session(now),opening_minutes=30 if rule=="orb30" else 15,
                complete_data=True,eligible=sym in eligible and (side == 1 or sym in short_eligible),paper_enabled=True,approved=True,confirmed=True,
                liquidity_ok=r["turnover"]>=1e7,limits_ok=len(held)<MAX_POSITIONS and not any(x["symbol"]==sym for x in held),
                duplicate=identity in used)
            if reasons:
                rejected.append([sym,rule,", ".join(reasons)])
                continue
            held.append({**p,"id":identity,"opened":now.isoformat(),"deadline":start+21300})
            used.append(identity)
    # A simultaneous pause, approval change or worker fill invalidates this cycle.
    await db.update_one({"_id":key(index),"revision":doc.get("revision")},{"$inc":{"revision":1},"$set":{
        "positions":held,"recent":recent[-100:],"used":used,"used_day":day,"failed":failed[-100:],"rejected":rejected}})


async def _cycle(now):
    for index in INDEX_LABELS:
        await tick(index, now)
    return {}


async def loop():
    from app.services import desk_switches
    while True:
        try:
            now=datetime.now(m.store.IST)
            if market_calendar.is_trading_day(now) and 570<=now.hour*60+now.minute<=930:
                # ON: as before. OFF with open positions: exits only. OFF and flat: skipped.
                await desk_switches.gated(MODULE_KEY, _cycle, now)
        except Exception:
            log.exception("Morning equity cycle failed")
        await asyncio.sleep(12)
