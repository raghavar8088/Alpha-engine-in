// Prints one video's saved transcript from the Trading Video Lab, in paragraphs of about 40 seconds with their start
// times (the shortlist study's ze_read.mjs, plus a stricter rules view for long streams).
//   node zg_read.mjs <video id> [from_seconds] [to_seconds]
//   node zg_read.mjs <video id> --rules [--max N]   only paragraphs that state a rule (entry, stop, target, timeframe,
//                                                   indicator settings, session...), no neighbours, at most N (60)
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const argv = process.argv.slice(2);
const rules = argv.includes('--rules');
const mi = argv.indexOf('--max');
const max = mi >= 0 ? Number(argv[mi + 1]) : 60;
const pos = argv.filter((a, i) => !a.startsWith('--') && !(mi >= 0 && i === mi + 1));
const [id, from = '0', to = '1e9'] = pos;
const e = await evidenceFor(id);
if (!e) { console.log('no evidence for', id); process.exit(1); }
const m = JSON.parse(readFileSync(join(e.folder, 'manifest.json'), 'utf8'));
const roman = join(e.folder, 'transcript.roman.txt');
const file = existsSync(roman) && m.transcript?.hindi_script ? roman : join(e.folder, 'transcript.txt');
const desc = existsSync(join(e.folder, 'description.txt')) ? readFileSync(join(e.folder, 'description.txt'), 'utf8') : '';
console.log(`# ${m.title}\n${m.meta?.channel || ''} | ${m.meta?.upload_date || ''} | ${Math.round(m.duration / 60)} min | https://youtu.be/${id}`);
console.log(`transcript: ${m.transcript?.source} (${m.transcript?.clean_words} words)${file === roman ? ', read in Latin letters' : ''}`);
const chapters = (m.meta?.chapters || []).map(c => { const t = c.start_time ?? c.start ?? 0; return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')} ${c.title}`; });
if (chapters.length) console.log('chapters: ' + chapters.join(' | '));
console.log('description: ' + desc.replace(/https?:\/\/\S+/g, '').replace(/#\S+/g, '').replace(/\s+/g, ' ').trim().slice(0, 700));
console.log('---');
const lines = readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean);
let cur = null;
const out = [];
const sec = s => { const [h, mm, ss] = s.split(':').map(Number); return h * 3600 + mm * 60 + ss; };
for (const line of lines) {
  const mm = /^\[(\d\d:\d\d:\d\d)\]\s*(.*)$/.exec(line);
  if (!mm) continue;
  const t = sec(mm[1]);
  if (t < Number(from) || t > Number(to)) continue;
  if (!cur || t - cur.t >= 40) { if (cur) out.push(cur); cur = { t, label: mm[1].replace(/^00:/, ''), text: [] }; }
  cur.text.push(mm[2]);
}
if (cur) out.push(cur);
const RULE = /stop ?loss|stop is|my stop|stop (goes|at|below|above|under|over)|target|take profit|risk (to|reward)|reward|\d ?r\b|1:\d|entry|enter|i (buy|sell|go long|go short|get long|get short)|rule|condition|setting|period|length|time ?frame|\d+ ?(minute|min|hour|hr)\b|candle clos|close (above|below|back)|closes (above|below|back)|break(s|out)? (above|below|of)|crosses|crossover|moving average|\bema\b|\bsma\b|bollinger|rsi|vwap|atr|heikin|supertrend|macd|stochastic|session|london|new york|asia|open(ing)? range|previous day|yesterday'?s (high|low)|inside (day|bar)|engulf|pin ?bar|fair value gap|order block|sweep|liquidity/i;
if (rules) {
  let n = 0, last = -1;
  out.forEach((p, i) => {
    const txt = p.text.join(' ');
    const hits = (txt.match(new RegExp(RULE.source, 'gi')) || []).length;
    if (hits < 2 || n >= max) return;
    if (last >= 0 && i > last + 1) console.log('...');
    console.log(`[${p.label}] ${txt}`);
    n++; last = i;
  });
  console.log(`(rules: ${n} of ${out.length} paragraphs${n >= max ? ', capped' : ''})`);
} else for (const p of out) console.log(`[${p.label}] ${p.text.join(' ')}`);
