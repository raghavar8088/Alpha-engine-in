// Prints one video's saved evidence from the Trading Video Lab for reading: its details, then the clean transcript
// (Hindi in Latin letters when the captions are Hindi) in paragraphs of about 40 seconds, each with its start time.
//   node ze_read.mjs <video id> [from_seconds] [to_seconds]
//   node ze_read.mjs <video id> --skim      only the paragraphs that state rules (entry, stop, target, settings,
//                                          timeframe, session...) and one paragraph either side; gaps shown as ...
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const argv = process.argv.slice(2);
const skim = argv.includes('--skim');
const [id, from = '0', to = '1e9'] = argv.filter(a => a !== '--skim');
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
// description: links and hashtags removed, first 600 characters
console.log('description: ' + desc.replace(/https?:\/\/\S+/g, '').replace(/#\S+/g, '').replace(/\s+/g, ' ').trim().slice(0, 600));
console.log('---');
const lines = readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean);
let cur = null, out = [];
const sec = s => { const [h, mi, se] = s.split(':').map(Number); return h * 3600 + mi * 60 + se; };
for (const line of lines) {
  const mm = /^\[(\d\d:\d\d:\d\d)\]\s*(.*)$/.exec(line);
  if (!mm) continue;
  const t = sec(mm[1]);
  if (t < Number(from) || t > Number(to)) continue;
  if (!cur || t - cur.t >= 40) { if (cur) out.push(cur); cur = { t, label: mm[1].replace(/^00:/, ''), text: [] }; }
  cur.text.push(mm[2]);
}
if (cur) out.push(cur);
const RULE = /stop ?loss|stoploss|sl|target|entry|enter|exit|rule|condition|risk|reward|setting|period|length|time ?frame|minute|min|candle clos|close (above|below)|breaks? (above|below)|crosses|crossover|when (to|you) (buy|sell|enter)|kab (buy|sell|lena)|lena hai|lenge|bechn|kharid|stap ?los|taaraget|taaragat|entree|egjit|kandeeshan|niyam|seting|kaindal kloj|kloj|traling|trail|backtest|win ?rate|percent|ratio|1:2|1:3|lot|quantity|position siz/i;
if (skim) {
  const keep = new Set();
  out.forEach((p, i) => { if (RULE.test(p.text.join(' '))) { keep.add(i - 1); keep.add(i); keep.add(i + 1); } });
  keep.add(0); keep.add(1);
  let last = -1;
  out.forEach((p, i) => { if (!keep.has(i)) return; if (last >= 0 && i > last + 1) console.log('...'); console.log(`[${p.label}] ${p.text.join(' ')}`); last = i; });
  console.log(`(skim: ${keep.size > out.length ? out.length : [...keep].filter(i => i >= 0 && i < out.length).length} of ${out.length} paragraphs)`);
} else for (const p of out) console.log(`[${p.label}] ${p.text.join(' ')}`);
