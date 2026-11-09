// Lists every shortlisted channel through the Trading Video Lab (titles and details only; videos and live streams,
// no Shorts) and summarises how much of it teaches strategies: the app's title classifier marks P1 = a strategy word
// plus a setup family. Language is read from the titles (Devanagari or common Hinglish words).
//   node list_candidates.mjs            -> registry/candidates.json (resumes: a channel already listed is reused)
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const API = 'http://127.0.0.1:8765';
const { classify } = await import('file:///' + APP + '/lib/channels.mjs');
const sleep = ms => new Promise(r => setTimeout(r, ms));

// [name, channel id, market focus from discovery]
export const SHORTLIST = [
  ['Dhan', 'UCEzHCpvFWoF85UabbzKTkOQ', 'in_equity+in_options'],
  ['TradingLab', 'UCCbv0qixG-cyokxEY3kELtg', 'crypto+gold'],
  ['AbhishekXTrades', 'UCUJmHX01pQAsP8yQ_TfsmZw', 'in_equity+in_options+crypto'],
  ['Umar Punjabi', 'UCJsptLfnA0JQUU8Hs0Qqakw', 'in_equity+crypto+gold'],
  ['Upsurge Club', 'UCQQojT_AmVWGb4Eg-QniuBA', 'in_equity+in_options'],
  ['Delta Exchange', 'UCaw-1cUd74wvEatvZna0TzQ', 'crypto'],
  ['The Trading School', 'UCUzGUWt1zx8krC5i3Lzv7rA', 'in_equity+in_options'],
  ['Trade with Pat', 'UC04-HvUvHG4hpMnQx07ObYQ', 'crypto+gold'],
  ['HOLD with Priyank', 'UCRI4NNcBZzBdVzfSlXdGwCw', 'crypto+in_equity'],
  ['Jesse Rogers | Casper Trading', 'UCEAq-8Ih0WI6R7wYoCFiWmA', 'crypto+gold'],
  ['Smart Risk', 'UCX_LoZNPSLM4pm31TKDB6jw', 'gold'],
  ['Stock Investment Academy by Amar Bhatia Sir', 'UCPtgdNLXi2QglhJBidB6QNw', 'in_equity+in_options'],
  ['Data Trader', 'UCwIsRM8qBXobpAnzVJ0c4IQ', 'crypto+gold'],
  ['Devansh Rai', 'UCRem0cxZp0CNrJaFGRB2Tpw', 'crypto+gold'],
  ['Equity2Commodity', 'UCfJDLFYo0sSdBTGnrJGyCjw', 'in_equity+in_options+gold'],
  ['Bharat Jhunjhunwala', 'UCiyqiag20iAsOwL9SHJMQ4g', 'in_equity+in_options'],
  ['Mulham Trading', 'UCJFDZ3Xab4vXDSQJrvaFXIw', 'gold'],
  ['Inter Equity Trading', 'UCL2l3Lj4Oob7D3pLVogQ3_w', 'crypto+gold'],
  ['Faiz SMC', 'UC9N9JnSg9aL2w4D0kITQcaw', 'gold'],
  ['Simpy Gupta Live Trading', 'UCHtotjpc0-410ejn-pDJ30A', 'in_equity+in_options'],
  ['Nifty Trading by Prabhat Sir', 'UCA71H00KgPQzwFIK5ps4zuw', 'in_options'],
  ['Vijay Thakkar', 'UCHvscyzKoKxhLcaz1LQ6mHg', 'in_equity+in_options'],
  ['Anant Ladha', 'UCWHCXSKASuSzao_pplQ7SPw', 'in_equity'],
  ['The Simple Trade', 'UCYRB8kDbaW6a1Gufr_qwVTA', 'in_equity+in_options'],
  ['Gautam Jha', 'UCTS8wjQ3Ivzh4q99QMiZchQ', 'in_options'],
  ['Pro Trading School', 'UCB5dISM93_Vr5i5AvZgTGFg', 'crypto+gold'],
  ['TraderNick', 'UCPCPE5MoI7DS1WiVB_-mzNw', 'gold'],
  ['MambaFx', 'UCHOZ2K5iX4dDxNtNsiDt2eg', 'crypto+gold'],
  ['Option Sailor', 'UC9bkz7xOrjVWqRVFuqVRtAA', 'in_options'],
  ['THE OPTION SCHOOL', 'UCO58BCT-aHHcm6L0tOF4DrQ', 'in_options'],
  ['TradBuilder', 'UCIaCP4uF4NpYXnx1Nq7JK-Q', 'in_options'],
  ['Trading Chanakya', 'UCUgUjyt6jcyxfM4FCmxZcgw', 'in_equity+in_options'],
  ['CA Sumeet Mongia', 'UC0kTPPgxY_Yh9uatUTsbcxA', 'in_options'],
  ['P R Sundar', 'UCS2NdYUmv_PUyyKeDAo5zYA', 'in_options'],
  ['Abhishek Kar', 'UCcanCrgSWVYW7ZFNKQZso0g', 'in_equity+in_options'],
  ['DAY TRADER Telugu', 'UCeEP6GESh2t4-e2132uj3Sg', 'in_equity+in_options'],
  ['TRADING RUSH', 'UCgY_eHY4NCTcRnU6CCZXWng', 'crypto+gold'],
  ['Transparent Fx Academy', 'UC-vGMbd-jPqGpsuaObDHvmA', 'gold'],
  ['Forex Insights', 'UCB_RAechvtcNpWWyDP269SQ', 'gold'],
  ['Trading Data', 'UCV9hkwgSFkAwS4hN_0oxinA', 'in_options+crypto+gold'],
];

const OUT = join(HERE, 'registry', 'candidates.json');
const out = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
const post = async (path, body) => (await fetch(API + path, { method: 'POST', headers: { 'content-type': 'application/json', origin: API }, body: JSON.stringify(body) })).json();
const get = async path => { const r = await fetch(API + path); if (!r.ok) throw new Error(path + ' ' + r.status); return r.json(); };
const hindi = t => /[\u0900-\u097F]/.test(t) || /\b(kaise|kya|kare|karo|sikhe|ke saath|wala|bina|paisa|hindi|kamaye|kamao|kiya|bhai)\b/i.test(t);
const telugu = t => /[\u0C00-\u0C7F]/.test(t) || /\btelugu\b/i.test(t);
const urdu = t => /[\u0600-\u06FF]/.test(t) || /\burdu\b/i.test(t);

for (const [name, id, focus] of SHORTLIST) {
  if (out[id]?.entries) { continue; }
  let cat = null;
  try { cat = await get('/api/channels/' + id); } catch { /* not listed yet */ }
  if (!cat) {
    const job = await post('/api/channels/catalogue', { url: 'https://www.youtube.com/channel/' + id, shorts: false });
    const jid = job.id || job.job?.id;
    for (let i = 0; i < 180; i++) {
      await sleep(5000);
      const j = await get('/api/jobs/' + jid).catch(() => null);
      const st = j?.state || j?.status || j?.job?.state;
      if (st && !['queued', 'running', 'waiting'].includes(st)) { if (st !== 'done') console.log(name, 'job', st, JSON.stringify(j).slice(0, 300)); break; }
    }
    try { cat = await get('/api/channels/' + id); } catch (e) { out[id] = { name, focus, error: String(e.message) }; console.log('FAILED', name, e.message); writeFileSync(OUT, JSON.stringify(out, null, 1)); continue; }
  }
  const entries = (cat.entries || []).filter(e => !e.dup_of);
  const cls = entries.map(e => ({ ...e, ...classify(e.title) }));
  const p1 = cls.filter(e => e.priority === 'P1');
  const fam = {};
  for (const e of p1) for (const f of e.families) fam[f] = (fam[f] || 0) + 1;
  const titles = entries.map(e => e.title || '');
  const lang = telugu(titles.join(' ')) ? 'Telugu' : urdu(titles.join(' ')) ? 'Urdu/Hindi' :
    titles.filter(hindi).length > titles.length * 0.15 ? 'Hindi' : 'English';
  out[id] = {
    name, focus, channel: cat.channel, n: entries.length, p1: p1.length, p2: cls.filter(e => e.priority === 'P2').length,
    share_p1: entries.length ? +(p1.length / entries.length).toFixed(3) : 0, families: fam, lang,
    last: entries.map(e => e.published).filter(Boolean).sort().pop() || null,
    top_p1: p1.sort((a, b) => (b.views || 0) - (a.views || 0)).slice(0, 15).map(e => [e.id, e.title, e.views, e.duration, e.published]),
    entries: true,
  };
  console.log(`${name.padEnd(44)} n=${String(entries.length).padStart(4)} P1=${String(p1.length).padStart(3)} (${(100 * out[id].share_p1).toFixed(0)}%) ${lang}`);
  writeFileSync(OUT, JSON.stringify(out, null, 1));
  await sleep(3000);
}
console.log('done', Object.keys(out).length);
