"""Morning equity signals from session-anchored, completed five-minute bars."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from math import isfinite
from statistics import median

from app.services import intraday_store as store
from app.services.angel_fees import round_trip

RULES = {
    "orb15": "Close through the first 15-minute high or low.",
    "orb30": "Close through the first 30-minute high or low.",
    "vwap": "Two closes on the trend side of session VWAP, breaking the previous bar on elevated volume.",
    "relative": "Outperform or underperform Nifty and sector peers, then break the previous bar.",
    "pullback": "Previous candle retraces against opening momentum, followed by a close through its extreme.",
    "gap_go": "Gap of at least 0.5%, holding beyond the prior close, then an opening-range break on elevated volume.",
    "gap_fade": "Gap of at least 0.5%, then a break against the gap with room to the previous close.",
    "volume": "Close through the preceding three bars on elevated volume.",
}
POLICY = ("Five-minute close confirms. Enter at the following open with 5 bp adverse slippage per leg. "
          "Stop at signal candle extreme. Target twice initial risk, capped at previous close for gap-fade. "
          "Per trade: Rs 100 risk, Rs 10,000 notional, maximum 1% of signal-bar volume. "
          "Entries before 14:30 IST. Exit at 15:10 IST. Stop first on ambiguous candles. "
          "Ranking selects the ten strongest per direction. Sector benchmark is the median of other usable sector constituents.")
def move(a, b):
    return 100 * (a / b - 1)

def valid(row):
    _, o, h, l, c, v, _ = row
    return all(isfinite(x) for x in (o,h,l,c,v)) and 0 < l <= min(o,c) <= max(o,c) <= h and v >= 0

def opening(bars, start):
    i = bisect_left(bars.t, start)
    rows = list(bars.rows(i,min(i+3,len(bars))))
    if len(rows)==3 and all(r[0]==start+300*k and valid(r) for k,r in enumerate(rows)):
        return i, rows
    return None

def scan(start, members, load=store.read_file):
    rows, excluded = [], {}
    benchmark = opening(load("NIFTY","5m"), start)
    for symbol, sector in members.items():
        bars = load(symbol,"5m")
        current = opening(bars,start)
        if not benchmark or not current:
            excluded[symbol] = "Missing Nifty or stock opening bars"
            continue
        i, candles = current
        history = []
        j = i
        while j and len(history)<20:
            prior = store.day_start(bars.t[j-1])+33300
            j = bisect_left(bars.t,prior,0,j)
            sample = opening(bars,prior)
            if sample:
                history.append(sum(r[5] for r in sample[1]))
            if j and bars.t[j-1]>=prior-33300:
                j=bisect_left(bars.t,prior-33300,0,j)
        vol = sum(r[5] for r in candles)
        if (not sector or len(history)<5 or not median(history) or not vol or not i
                or not valid(next(bars.rows(i-1,i))) or store.session_minute(bars.t[i-1])!=925):
            excluded[symbol] = "Incomplete baseline, sector, or previous close"
            continue
        op, close = candles[0][1], candles[-1][4]
        vw = sum((r[2]+r[3]+r[4])/3*r[5] for r in candles)/vol
        rows.append(dict(symbol=symbol,sector=sector,change=move(close,op),gap=move(op,bars.c[i-1]),
                         prev=bars.c[i-1],market=move(close,op)-move(benchmark[1][-1][4],benchmark[1][0][1]),
                         vwap=move(close,vw),volume=vol/median(history),turnover=vol*vw))
    groups=defaultdict(list)
    for r in rows:
        groups[r["sector"]].append(r)
    usable=[]
    for r in rows:
        peers=[p["change"] for p in groups[r["sector"]] if p is not r]
        if not peers:
            excluded[r["symbol"]]="No usable sector peers"
            continue
        r["relative"]=r["change"]-median(peers)
        r["side"]=1 if r["change"]>0 else -1
        r["score"]=round((abs(r["change"])+r["side"]*(r["market"]+r["relative"]+r["vwap"]))*min(r["volume"],3),3)
        r["qualified"]=r["turnover"]>=1e7 and r["volume"]>=1 and min(r[k]*r["side"] for k in ("change","market","relative","vwap"))>0
        usable.append(r)
    usable.sort(key=lambda r:(-r["score"],r["symbol"]))
    for side in (1,-1):
        for rank,r in enumerate((r for r in usable if r["qualified"] and r["side"]==side),1):
            r["rank"]=rank
    return usable,excluded

def triggers(row, bars):
    i=len(bars)-1
    if i<3: return []
    last,prior=bars[-1],bars[-2]
    c=last[4]
    side=row["side"]
    def breaks(window,s):
        return c>max(b[2] for b in window) if s==1 else c<min(b[3] for b in window)
    strong=row["volume"]>=1.5
    prevbreak=breaks([prior],side)
    orb=breaks(bars[:3],side)
    vs=sum(b[5] for b in bars)
    vw=sum((b[2]+b[3]+b[4])/3*b[5] for b in bars)/vs if vs else c
    fade=-1 if row["gap"]>0 else 1
    return [(k,s) for k,s,ok in (
        ("orb15",side,orb),("orb30",side,i>=6 and breaks(bars[:6],side)),
        ("vwap",side,prevbreak and strong and min((c-vw)*side,(prior[4]-vw)*side)>0),
        ("relative",side,prevbreak and min(row["market"]*side,row["relative"]*side)>0),
        ("pullback",side,prevbreak and (prior[4]-prior[1])*side<0),
        ("gap_go",side,orb and strong and row["gap"]*side>=0.5 and (c-row["prev"])*side>0),
        ("gap_fade",fade,abs(row["gap"])>=0.5 and breaks(bars[:3],fade) and (row["prev"]-c)*fade>0),
        ("volume",side,strong and breaks(bars[-4:-1],side))) if ok]

def order(rule,side,row,signal,price):
    entry=price*(1+side*.0005)
    stop=signal[3 if side==1 else 2]
    risk=(entry-stop)*side
    if risk<=0: return
    qty=int(min(100/risk,10000/entry,signal[5]*.01))
    target=entry+side*2*risk
    if rule=="gap_fade" and (target-row["prev"])*side>0: target=row["prev"]
    edge=(target-entry)*side*qty
    if qty and edge>round_trip(entry,target,qty,"BUY" if side==1 else "SELL").total+target*qty*.0005:
        return dict(symbol=row["symbol"],rule=rule,side=side,entry=entry,qty=qty,stop=stop,target=target)

def resolve(p,bar,deadline):
    t,o,h,l,*_=bar
    s=p["side"]
    stop,target=p["stop"],p["target"]
    if t>=deadline: price=o
    elif (o-stop)*s<=0 or (o-target)*s>=0: price=o
    elif (l<=stop if s==1 else h>=stop): price=stop
    elif (h>=target if s==1 else l<=target): price=target
    else: return
    price*=1-s*.0005
    qty=p["qty"]
    fees=round_trip(p["entry"],price,qty,"BUY" if s==1 else "SELL").total
    return (price-p["entry"])*qty*s-fees
