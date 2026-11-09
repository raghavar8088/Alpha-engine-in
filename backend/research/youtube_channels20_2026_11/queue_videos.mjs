// Queues the selected videos (catalogue/selection/<slug>.tsv: id, role, family, note) in the Trading Video Lab, which
// saves each video's captions, details and chapters (and, for a video without captions, transcribes its audio with
// Whisper). The app paces YouTube itself and rests 15 minutes when asked to slow down.
//   node queue_videos.mjs <slug> [<slug> ...]      (no card building: the reading is done here, with timestamps)
//   node queue_videos.mjs --status                   -> which selected videos have evidence yet
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const API = 'http://127.0.0.1:8765';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const SEL = join(HERE, 'catalogue', 'selection');
const rowsOf = slug => readFileSync(join(SEL, slug + '.tsv'), 'utf8').split(/\r?\n/).slice(1).filter(Boolean).map(l => l.split('\t'));

if (process.argv[2] === '--status') {
  for (const f of readdirSync(SEL).filter(x => x.endsWith('.tsv'))) {
    const rows = rowsOf(f.replace(/\.tsv$/, ''));
    const missing = [];
    let have = 0;
    for (const [id] of rows) { if (await evidenceFor(id)) have++; else missing.push(id); }
    console.log(`${f.padEnd(34)} ${have}/${rows.length}` + (missing.length ? '  missing: ' + missing.join(' ') : ''));
  }
  process.exit(0);
}
for (const slug of process.argv.slice(2)) {
  if (!existsSync(join(SEL, slug + '.tsv'))) { console.log('no selection for', slug); continue; }
  const raw = readdirSync(join(HERE, 'catalogue', 'raw')).map(f => JSON.parse(readFileSync(join(HERE, 'catalogue', 'raw', f), 'utf8')));
  const byId = new Map(raw.flatMap(c => c.entries.map(e => [e.id, { ...e, channel: c.channel.title }])));
  const videos = [];
  for (const [id] of rowsOf(slug)) {
    if (await evidenceFor(id)) continue;                         // already saved: never fetched twice
    const e = byId.get(id) || {};
    videos.push({ id, title: e.title || '', channel: e.channel || slug });
  }
  if (!videos.length) { console.log(slug, 'all selected videos already have evidence'); continue; }
  const r = await fetch(API + '/api/queue', { method: 'POST', headers: { 'content-type': 'application/json', origin: API },
    body: JSON.stringify({ videos, label: `${slug} (${videos.length}) for the 20-channel study`, card: false, budget_usd: 0 }) });
  console.log(slug, r.status, JSON.stringify(await r.json()).slice(0, 200));
}
