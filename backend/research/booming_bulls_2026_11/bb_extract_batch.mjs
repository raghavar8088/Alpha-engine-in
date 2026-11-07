// Phase 2: run the Video Explainer app's own extraction command (extract.mjs, captions only) for a
// set of videos, then prepare readable transcripts. Results go to data/transcripts/_index.json.
// Re-running skips videos whose evidence already has a transcript.
// Usage: node bb_extract_batch.mjs P1|P2|P3|<id,id,...> [concurrency=2]
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readdir, readFile, writeFile, mkdir, stat } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LABELS } from './bb_labels.mjs';
import { prepare } from './bb_prepare_transcript.mjs';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..', '..', '..', 'youtube-video-explainer-reviewed');
const EVIDENCE = join(APP, 'evidence');
const INDEX = join(HERE, 'data', 'transcripts', '_index.json');

const [selector = 'P1', conc = '2'] = process.argv.slice(2);
const ids = /^P\d$/.test(selector)
  ? [...new Set(LABELS.filter(l => l[3] === selector).map(l => l[0]))]
  : selector.split(',').map(s => s.trim()).filter(Boolean);

await mkdir(dirname(INDEX), { recursive: true });
let index = {};
try { index = JSON.parse(await readFile(INDEX, 'utf8')); } catch {}

async function existingFolder(id) {
  const names = (await readdir(EVIDENCE)).filter(n => n.startsWith(id + '-')).sort();
  for (const n of names.reverse()) {
    try {
      const t = JSON.parse(await readFile(join(EVIDENCE, n, 'transcript.json'), 'utf8'));
      if (t.length) return join(EVIDENCE, n);
    } catch {}
  }
  return null;
}

async function one(id) {
  let folder = await existingFolder(id);
  let note = '';
  if (!folder) {
    try {
      const { stdout } = await run('node', [join(APP, 'extract.mjs'), 'https://www.youtube.com/watch?v=' + id],
        { timeout: 600_000, windowsHide: true, maxBuffer: 64 * 1024 * 1024 });
      folder = stdout.match(/Evidence saved to (.+)$/m)?.[1]?.trim() || null;
    } catch (error) {
      const out = String(error.stdout || '');
      folder = out.match(/Evidence saved to (.+)$/m)?.[1]?.trim() || null;
      note = String(error.stderr || error.message).trim().split(/\r?\n/).filter(Boolean).slice(-2).join(' ').slice(0, 300);
    }
  }
  if (!folder) return { id, status: 'failed', note };
  try {
    const t = JSON.parse(await readFile(join(folder, 'transcript.json'), 'utf8'));
    if (!t.length) {
      const m = JSON.parse(await readFile(join(folder, 'manifest.json'), 'utf8'));
      return { id, status: 'no_captions', folder, duration: Math.round(m.duration || 0), note: note || 'no caption track; needs Whisper' };
    }
    const r = await prepare(folder, 30);
    return { status: 'ok', folder, ...r };
  } catch (error) {
    return { id, status: 'failed', folder, note: (note + ' ' + error.message).trim().slice(0, 300) };
  }
}

const queue = [...ids];
let done = 0;
await Promise.all(Array.from({ length: Number(conc) || 2 }, async () => {
  while (queue.length) {
    const id = queue.shift();
    const r = await one(id);
    index[id] = { ...r, at: new Date().toISOString() };
    done++;
    console.log(`${done}/${ids.length} ${id} ${r.status}${r.track ? ' ' + r.track : ''}${r.words ? ' words ' + r.words : ''}${r.note ? ' | ' + r.note : ''}`);
    await writeFile(INDEX, JSON.stringify(index, null, 2));
  }
}));
const counts = {};
for (const id of ids) counts[index[id]?.status] = (counts[index[id]?.status] || 0) + 1;
console.log('summary:', JSON.stringify(counts));
