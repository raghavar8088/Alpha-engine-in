// Saves each picked video's evidence (details, description, captions; no media) in the Trading Video Lab's
// evidence folder, one video at a time with a pause between, through the Lab's own extractEvidence. Videos whose
// evidence is already saved are skipped. Captions only: a video without captions is reported, never downloaded.
//   node zg_fetch.mjs [--only id,id] [--lang en] [--fresh]
//   node zg_fetch.mjs --status
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { extractEvidence, evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const args = process.argv.slice(2);
const opt = k => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : ''; };
const only = new Set(opt('--only').split(',').filter(Boolean));
const lang = opt('--lang');
const fresh = args.includes('--fresh');
const rows = readFileSync(join(HERE, 'catalogue', 'picks.tsv'), 'utf8').split(/\r?\n/).slice(1).filter(Boolean).map(l => l.split('\t'));
const sleep = ms => new Promise(r => setTimeout(r, ms));

if (args.includes('--status')) {
  for (const [id, key] of rows) {
    const e = await evidenceFor(id);
    if (!e || !existsSync(join(e.folder, 'manifest.json'))) { console.log(`${id.padEnd(12)} ${key.padEnd(17)} -- none`); continue; }
    const m = JSON.parse(readFileSync(join(e.folder, 'manifest.json'), 'utf8'));
    console.log(`${id.padEnd(12)} ${key.padEnd(17)} ${String(m.transcript?.source || '-').padEnd(34)} ${String(m.transcript?.clean_words || 0).padStart(6)}w ${String(Math.round((m.duration || 0) / 60)).padStart(3)}m | ${String(m.title).slice(0, 70)}`);
  }
  process.exit(0);
}

let n = 0;
for (const [id, key] of rows) {
  if (only.size && !only.has(id)) continue;
  if (!fresh) {
    const e = await evidenceFor(id);
    if (e && existsSync(join(e.folder, 'manifest.json'))) {
      const m = JSON.parse(readFileSync(join(e.folder, 'manifest.json'), 'utf8'));
      if ((m.transcript?.clean_words || 0) > 0) { console.log(`${id} ${key}: kept (${m.transcript.clean_words} words)`); continue; }
    }
  }
  if (n++) await sleep(4000);
  const t0 = Date.now();
  try {
    const r = await extractEvidence({ source: id, lang, fresh, onProgress: () => {} });
    const t = r.manifest.transcript || {};
    const warn = (r.manifest.warnings || []).filter(w => !/untrusted/.test(w)).join('; ');
    console.log(`${id} ${key}: ${t.source || 'NO CAPTIONS'} ${t.clean_words || 0} words, ${Math.round((r.manifest.duration || 0) / 60)} min (${((Date.now() - t0) / 1000).toFixed(0)} s)${warn ? ' | ' + warn.slice(0, 160) : ''}`);
  } catch (e) {
    console.log(`${id} ${key}: FAILED ${String(e.message).slice(0, 200)}`);
    if (/429|Too Many Requests/i.test(String(e.message))) { console.log('rate limited: stopping'); break; }
  }
}
