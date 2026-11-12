// Prints one video's saved evidence from the Trading Video Lab for reading: its details, then the clean transcript
// (Hindi in Latin letters when the captions are Hindi) in paragraphs of about 40 seconds, each with its start time.
//   node zd_read.mjs <video id> [from_seconds] [to_seconds]
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const [id, from = '0', to = '1e9'] = process.argv.slice(2);
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
for (const p of out) console.log(`[${p.label}] ${p.text.join(' ')}`);
