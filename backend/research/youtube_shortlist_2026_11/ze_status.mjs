// Status of every picked video (catalogue/selection/picks.tsv): evidence saved, caption track, words, card written,
// and a garble check - the share of very common English words in the transcript, which is near zero when an English
// talk was captioned by the Hindi recogniser (re-fetch those with ze_refetch.mjs <id> en).
//   node ze_status.mjs [--todo]      (--todo: only videos with evidence but no card yet)
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const todo = process.argv.includes('--todo');
const rows = readFileSync(join(HERE, 'catalogue', 'selection', 'picks.tsv'), 'utf8').split(/\r?\n/).slice(1).filter(Boolean).map(l => l.split('\t'));
const COMMON = new Set('the and you to a is that this of in it so we on for be will with have are can when what at if your as'.split(' '));
for (const [id, key, wave] of rows) {
  const card = existsSync(join(HERE, 'cards', id + '.txt'));
  const e = await evidenceFor(id);
  if (!e) { if (!todo) console.log(`${id.padEnd(12)} ${key.padEnd(18)} -- no evidence yet`); continue; }
  if (todo && card) continue;
  if (!existsSync(join(e.folder, 'manifest.json'))) { if (!todo) console.log(`${id.padEnd(12)} ${key.padEnd(18)} -- fetching`); continue; }
  const m = JSON.parse(readFileSync(join(e.folder, 'manifest.json'), 'utf8'));
  const tf = join(e.folder, 'transcript.txt');
  const words = existsSync(tf) ? readFileSync(tf, 'utf8').toLowerCase().replace(/\[[^\]]*\]/g, ' ').split(/[^a-z']+/).filter(Boolean) : [];
  const en = words.length ? words.filter(w => COMMON.has(w)).length / words.length : 0;
  const hindi = !!m.transcript?.hindi_script;
  // Hindi speech in Latin letters is full of these function words; an English talk mis-captioned as Hindi is not
  const rf = join(e.folder, 'transcript.roman.txt');
  const HI = new Set('hai ke ki ka aur se ko men mein to ye yah jo par hain tha bhee bhi nahin nahi kya isake usake aap ham'.split(' '));
  const rw = hindi && existsSync(rf) ? readFileSync(rf, 'utf8').toLowerCase().replace(/\[[^\]]*\]/g, ' ').split(/[^a-z]+/).filter(Boolean) : [];
  const hi = rw.length ? rw.filter(w => HI.has(w)).length / rw.length : 0;
  console.log(`${id.padEnd(12)} ${key.padEnd(18)} ${String(m.transcript?.source || '-').padEnd(34)} ${String(m.transcript?.clean_words || 0).padStart(6)}w ` +
    `${Math.round(m.duration / 60)}m en=${en.toFixed(2)}${hindi ? ' hi=' + hi.toFixed(2) + (hi < 0.08 ? ' GARBLED?' : '') : ''}${card ? ' CARD' : ''} | ${String(m.title).slice(0, 60)}`);
}
