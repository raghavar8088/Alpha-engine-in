"""Run with PYTHONPATH=backend;shared and INTRADAY_DATA_DIR pointing at the archive."""
import argparse
import json
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.services.screener import morning as m

def metrics(trades):
    wins=sum(p for _,p,_ in trades if p>0)
    loss=-sum(p for _,p,_ in trades if p<0)
    balance=peak=draw=0
    for _,p,_ in sorted(trades,key=lambda x:x[0]):
        balance+=p
        peak=max(peak,balance)
        draw=max(draw,peak-balance)
    n=len(trades)
    return dict(trades=n,win_pct=round(100*sum(p>0 for _,p,_ in trades)/n,2) if n else None,
                profit_factor=round(wins/loss,2) if loss else None,drawdown_rs=round(draw,2),
                mean_net_pct=round(sum(x[2] for x in trades)/n,4) if n else None,net_rs=round(balance,2))

def run(exports):
    universe=sorted(json.loads((exports/"universe_days.json").read_text()),key=lambda x:x["_id"])
    sectors=json.loads((exports/"sectors.json").read_text())
    load=lru_cache(None)(m.store.read_file)
    trades=defaultdict(list)
    failures=defaultdict(int)
    split=int(len(universe)*.7)
    coverage=[]
    for j,day in enumerate(universe[1:],1):
        start=int(datetime.fromisoformat(day["_id"]+"T09:15:00+05:30").timestamp())
        # Last known universe avoids using membership selected later on the replay date.
        members={s:sectors.get(s) for s in universe[j-1]["members"]}
        rows,_=m.scan(start,members,load)
        coverage.append([day["_id"],len(members),len(rows)])
        for r in rows:
            if r["turnover"]<1e7: continue
            b=load(r["symbol"],"5m")
            i=m.bisect_left(b.t,start)
            bars=list(b.rows(i,min(i+72,len(b))))
            used=set()
            for k in range(3,min(62,len(bars)-1)):
                if bars[k+1][0]!=start+(k+1)*300 or not m.valid(bars[k+1]) or not m.valid(bars[k]): break
                for rule,side in m.triggers(r,bars[:k+1]):
                    if rule in used: continue
                    p=m.order(rule,side,r,bars[k],bars[k+1][1])
                    if not p: continue
                    used.add(rule)
                    modes=["all"]
                    if r.get("rank",999)<=10 and r["side"]==side: modes.append("ranked")
                    net=None
                    for z in range(k+1,len(bars)):
                        if bars[z][0]!=start+z*300 or not m.valid(bars[z]): break
                        net=m.resolve(p,bars[z],start+21300)
                        if net is not None: break
                    for mode in modes:
                        for direction in ("both","long" if side==1 else "short"):
                            key=(rule,mode,"test" if j>=split else "train",direction)
                            if net is None: failures[key]+=1
                            else: trades[key].append((bars[z][0],net,100*net/(p["qty"]*p["entry"])))
    return dict(coverage=coverage,split=universe[split]["_id"],rows=[
        dict(rule=r,mode=mde,period=t,side=s,failed_exits=failures[r,mde,t,s],**metrics(trades[r,mde,t,s]))
        for r in m.RULES for mde in ("all","ranked") for t in ("train","test") for s in ("both","long","short")])

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("exports",type=Path)
    parser.add_argument("output",type=Path)
    a=parser.parse_args()
    a.output.write_text(json.dumps(run(a.exports),indent=1))
