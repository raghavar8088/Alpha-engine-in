// Queues the picked videos (catalogue/selection/picks.tsv) in the Trading Video Lab for their captions and details
// (evidence only: no card, no model budget). Videos whose evidence is already saved are skipped.
//   node ze_queue.mjs [--lang en] [--only id,id]     -> one Lab batch
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const API = 'http://127.0.0.1:8765';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const args = process.argv.slice(2);
const opt = k => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : ''; };
const lang = opt('--lang');
const only = new Set(opt('--only').split(',').filter(Boolean));

const cand = JSON.parse(readFileSync(join(HERE, 'registry', 'candidates.json'), 'utf8'));
const info = {};
for (const c of Object.values(cand)) for (const e of c.candidates || []) info[e.id] = { title: e.title, channel: (c.titles || [c.name])[0] };
const rows = readFileSync(join(HERE, 'catalogue', 'selection', 'picks.tsv'), 'utf8').split(/\r?\n/).slice(1).filter(Boolean).map(l => l.split('\t'));
const videos = [];
for (const [id, key] of rows) {
  if (only.size && !only.has(id)) continue;
  if (await evidenceFor(id)) continue;
  videos.push({ id, title: info[id]?.title || '', channel: info[id]?.channel || key });
}
if (!videos.length) { console.log('nothing to queue'); process.exit(0); }
const r = await fetch(API + '/api/queue', { method: 'POST', headers: { 'content-type': 'application/json', origin: API },
  body: JSON.stringify({ videos, label: 'Channel shortlist study' + (lang ? ' (' + lang + ')' : ''), card: false, budget_usd: 0, lang }) });
const j = await r.json();
console.log(r.status, 'batch', j.batch?.id, 'added', j.added, 'skipped', j.skipped);
