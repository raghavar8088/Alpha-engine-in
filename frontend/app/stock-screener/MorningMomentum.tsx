"use client";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

type Candidate = {symbol:string; sector:string; side:number; rank:number; score:number; change:number; gap:number; market:number; relative:number; vwap:number; volume:number};
type Result = {rule:string;mode:string;period:string;side:string;trades:number;win_pct:number|null;profit_factor:number|null;drawdown_rs:number;mean_net_pct:number|null;net_rs:number;failed_exits:number};
type Board = {day:string;asof:string;processed:string;total:number;usable:number;rows:Candidate[];excluded:Record<string,string>};
type Position = {id:string;symbol:string;rule:string;entry:number;qty:number;stop:number;target:number;side:number;net?:number};
type Desk = {scan:boolean;paper:boolean;approved:string[];board?:Board;rules:Record<string,string>;policy:string;report:{split:string;rows:Result[];coverage:[string,number,number][]};positions?:Position[];recent?:Position[];failed?:string[];rejected?:string[][]};
const number=(x:number|null)=>x===null?"—":x.toLocaleString("en-IN",{maximumFractionDigits:3});
function Grid({headers,rows}:{headers:string[];rows:(string|number)[][]}){
  return <div style={{overflowX:"auto"}}><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table></div>;
}
export default function MorningMomentum({index}:{index:string}){
  const [desk,setDesk]=useState<Desk>(),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [side,setSide]=useState("both"),[period,setPeriod]=useState("test");
  const url="/api/screener/morning/"+encodeURIComponent(index);
  const refresh=useCallback(async()=>{try{setDesk(await apiFetch(url+"?fresh=true"));setError("");}catch(e){setError(String(e));}},[url]);
  useEffect(()=>{void refresh();const id=setInterval(refresh,20000);return ()=>clearInterval(id);},[refresh]);
  async function update(values:Record<string,boolean|string>){
    setBusy(true);
    try{await apiFetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)});await refresh();}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  const b=desk?.board;
  return <section><h2>Stock Momentum Trading</h2>{error&&<p role="alert">{error}</p>}
    {!desk?<p>Loading morning desk…</p>:<>
    <div className="subcontrols"><strong>{index.toUpperCase()} · NSE equity paper book</strong>
      <button disabled={busy} onClick={()=>update({scan:!desk.scan})}>{desk.scan?"Pause scan":"Enable scan"}</button>
      <button disabled={busy} onClick={()=>update({paper:!desk.paper})}>{desk.paper?"Pause new entries":"Enable paper entries"}</button></div>
    <p>{b?("Opening snapshot "+b.asof+" · "+b.usable+" / "+b.total+" usable · processed "+b.processed):"Waiting for the 09:30 IST opening scan."}</p>
    <p>Ranks require ₹1 crore opening turnover, above-baseline volume, and agreement between the opening move, VWAP, Nifty and sector-relative returns. Volume uses the median opening interval of up to 20 previous sessions.</p>
    {[1,-1].map(s=><section key={s}><h3>{s===1?"Long":"Short"} candidates</h3>{b?.rows.some(r=>r.side===s)?
      <Grid headers={["Rank","Stock","Sector","Strength","Open %","Gap %","vs Nifty pp","vs sector peers pp","vs VWAP %","Volume ×"]} rows={b.rows.filter(r=>r.side===s).map(r=>[r.rank,r.symbol,r.sector,...[r.score,r.change,r.gap,r.market,r.relative,r.vwap,r.volume].map(number)])}/>:<p>No qualifying candidates.</p>}</section>)}
    {b&&<details><summary>Excluded symbols ({Object.keys(b.excluded).length})</summary><Grid headers={["Stock","Reason"]} rows={Object.entries(b.excluded)}/></details>}
    <h3>Execution gates</h3>
    <ul>
      <li>Completed five-minute bars only, with no missing opening bars or stale source data.</li>
      <li>Quote must contain a trade in the preceding five seconds. A missing or stale quote rejects the entry.</li>
      <li>Longs require the current intraday eligible universe. Shorts also require a listed F&amp;O underlying.</li>
      <li>₹1 crore opening turnover, above-baseline opening volume, rank within the top ten, and the strategy&apos;s confirmed closing trigger are required.</li>
      <li>Size is capped by ₹100 risk, ₹10,000 notional, one percent of signal-bar volume, available ₹100,000 margin, and five concurrent positions.</li>
      <li>No duplicate symbol-strategy signal. Entries stop at 14:30 IST. Open positions retain stop and 15:10 IST square-off monitoring after paper entries are paused.</li>
    </ul>
    <h3>Strategy review</h3><p>{desk.policy}</p>
    <p>Historical liquid universe from the preceding archived session. Test window {desk.report.coverage[0][0]} through {desk.report.coverage.at(-1)?.[0]}, with {desk.report.coverage.filter(day=>day[2]>0).length} usable sessions out of {desk.report.coverage.length}. Holdout begins {desk.report.split}. Results model individual trades. Drawdown is cumulative realized rupees.</p>
    <label>Sample <select value={period} onChange={e=>setPeriod(e.target.value)}><option value="test">Out of sample</option><option value="train">In sample</option></select></label>{" "}
    <label>Direction <select value={side} onChange={e=>setSide(e.target.value)}>{["both","long","short"].map(s=><option key={s}>{s}</option>)}</select></label>
    <Grid headers={["Strategy","Selection","Trades","Win %","Profit factor","Drawdown ₹","Mean net %","Net ₹","Failed exits"]} rows={desk.report.rows.filter(r=>r.period===period&&r.side===side).map(r=>[r.rule,r.mode,r.trades,...[r.win_pct,r.profit_factor,r.drawdown_rs,r.mean_net_pct,r.net_rs].map(number),r.failed_exits])}/>
    {Object.entries(desk.rules).map(([key,rule])=><p key={key}><strong>{key}</strong> · {rule} <button disabled={busy} onClick={()=>update({strategy:key,approve:!desk.approved.includes(key)})}>{desk.approved.includes(key)?"Revoke approval":"Approve for paper"}</button></p>)}
    <h3>Paper positions and exits</h3><Grid headers={["Stock","Strategy","Side","Qty","Entry","Stop","Target","Net ₹"]} rows={[...(desk.positions||[]),...(desk.recent||[]).slice(-10).reverse()].map(p=>[p.symbol,p.rule,p.side===1?"Long":"Short",p.qty,number(p.entry),number(p.stop),number(p.target),p.net===undefined?"Open":number(p.net)])}/>
    {!!desk.failed?.length&&<p role="alert">Missed square-off · {desk.failed.join(", ")}</p>}
    {!!desk.rejected?.length&&<details><summary>Entry gate decisions</summary><Grid headers={["Stock","Strategy","Reason"]} rows={desk.rejected}/></details>}
    </>}</section>;
}
