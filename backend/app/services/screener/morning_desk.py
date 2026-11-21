"""Morning scanner scheduler and isolated simulated equity books."""
import asyncio
import logging
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
def key(index):
    return "morning-equity-"+index

async def state(index):
    return await db.find_one({"_id":key(index)}) or dict(_id=key(index),scan=True,paper=False,approved=[],positions=[],recent=[])

async def controls(index,values):
    await db.update_one({"_id":key(index)},{"$set":values,"$inc":{"revision":1}},upsert=True)


def _live_bars(symbol, timeframe):
    """Combine the historical baseline with unflushed live five-minute candles."""
    disk = m.store.read_file(symbol, timeframe)
    if timeframe == "5m":
        disk.merge(m.store.store5.get(symbol).rows())
    return disk


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


async def tick(index,now):
    doc=await state(index)
    day=now.date().isoformat()
    start=int(now.replace(hour=9,minute=15,second=0,microsecond=0).timestamp())
    elapsed=int(now.timestamp())-start
    if elapsed<900: return
    board=doc.get("board",{})
    if doc.get("scan",True) and (board.get("day")!=day or (not board.get("rows") and elapsed<1800)):
        members={d["symbol"]:d.get("sector") async for d in stock_universe_collection.find({"indices":index},{"symbol":1,"sector":1})}
        rows,excluded=await asyncio.to_thread(m.scan,start,members,_live_bars)
        board=dict(day=day,asof=day+"T09:30:00+05:30",processed=now.isoformat(),total=len(members),
                   usable=len(rows),rows=[r for r in rows if r.get("rank",999)<=10],excluded=excluded)
        await db.update_one({"_id":key(index)},{"$set":{"board":board}},upsert=True)
    positions=doc.get("positions",[])
    approved=doc.get("approved",[])
    enabled=doc.get("paper",False) and approved and board.get("day")==day and elapsed<18900
    rows=board.get("rows",[]) if enabled else []
    if not rows and not positions: return
    quotes=await _live_quotes(sorted({p["symbol"] for p in positions+rows}))
    now=datetime.now(m.store.IST)
    held=[]
    recent=doc.get("recent",[])
    used=doc.get("used",[]) if doc.get("used_day")==day else []
    failed=list(doc.get("failed",[]))
    rejected=[]
    def quote(sym):
        q=quotes.get(sym,{})
        stamp=parse_trade_time(q.get("trade_time"))
        price=q.get("ltp") or 0
        if stamp and 0<price and 0<=(now-stamp).total_seconds()<=5:
            return float(price),stamp
        return None,None
    for p in positions:
        price,_=quote(p["symbol"])
        due=now.timestamp()>=p["deadline"]
        if due and not price and p["id"] not in failed: failed.append(p["id"])
        net=m.resolve(p,(int(now.timestamp()),price,price,price),p["deadline"]) if price else None
        if net is None: held.append(p)
        else: recent.append({**p,"net":round(net,2),"closed":now.isoformat()})
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
                p["entry"]*p["qty"],100000-margin)
            reasons=entry_rejections(ev,now,trading_session=market_calendar.in_session(now),opening_minutes=30 if rule=="orb30" else 15,
                complete_data=True,eligible=sym in eligible and (side == 1 or sym in short_eligible),paper_enabled=True,approved=True,confirmed=True,
                liquidity_ok=r["turnover"]>=1e7,limits_ok=len(held)<5 and not any(x["symbol"]==sym for x in held),
                duplicate=identity in used)
            if reasons:
                rejected.append([sym,rule,", ".join(reasons)])
                continue
            held.append({**p,"id":identity,"opened":now.isoformat(),"deadline":start+21300})
            used.append(identity)
    # A simultaneous pause, approval change or worker fill invalidates this cycle.
    await db.update_one({"_id":key(index),"revision":doc.get("revision")},{"$inc":{"revision":1},"$set":{
        "positions":held,"recent":recent[-100:],"used":used,"used_day":day,"failed":failed[-100:],"rejected":rejected}})

async def loop():
    while True:
        try:
            now=datetime.now(m.store.IST)
            if market_calendar.is_trading_day(now) and 570<=now.hour*60+now.minute<=930:
                for index in INDEX_LABELS:
                    await tick(index,now)
        except Exception:
            log.exception("Morning equity cycle failed")
        await asyncio.sleep(12)
