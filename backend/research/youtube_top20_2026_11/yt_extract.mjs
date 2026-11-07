// Phase 2b: run the Video Explainer app's own extract step (youtube-video-explainer-reviewed/extract.mjs)
// on every picked video, then prepare a readable transcript (rolling auto-captions collapsed, Devanagari
// romanized, 30-second blocks) into data/transcripts/<id>.txt. Index: data/transcripts/_index.json.
// Usage: node yt_extract.mjs [conc=2] [ids...]
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, readdir, mkdir } from 'node:fs/promises';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PICKS } from './yt_picks.mjs';
import { collapseRolling, romanize, blocks } from '../booming_bulls_2026_11/bb_transcript_tools.mjs';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..', '..', '..', 'youtube-video-explainer-reviewed');
const OUT = join(HERE, 'data', 'transcripts');
const [concArg, ...only] = process.argv.slice(2);
const conc = Number(concArg) || 2;
// per-video caption language overrides (the app's --lang): videos that declare Hindi but carry a better track
const LANG = { bj6hVKjweZ8: 'en' };   // human-made en-GB subtitles; the hi-orig auto track is garbled

async function prepare(folder) {
  const cues = JSON.parse(await readFile(join(folder, 'transcript.json'), 'utf8'));
  const manifest = JSON.parse(await readFile(join(folder, 'manifest.json'), 'utf8'));
  const track = (await readdir(folder)).find(f => /^(captions|speech)\./.test(f)) || 'none';
  const id = basename(folder).replace(/-\d+$/, '');
  const words = collapseRolling(cues);
  const rawWords = cues.reduce((n, c) => n + c.text.split(/\s+/).filter(Boolean).length, 0);
  const lines = blocks(words, 30, romanize);
  const header = [`# ${manifest.title}`, `# id ${id} | track ${track} | duration ${Math.round(manifest.duration)} s | cues ${cues.length} | words raw ${rawWords} -> ${words.length}`,
    `# source evidence: ${folder}`, ''];
  await writeFile(join(OUT, id + '.txt'), header.join('\n') + lines.join('\n') + '\n');
  return { id, track, duration: Math.round(manifest.duration), words: words.length, warnings: manifest.warnings || [] };
}

await mkdir(OUT, { recursive: true });
const idxPath = join(OUT, '_index.json');
let index = {};
try { index = JSON.parse(await readFile(idxPath, 'utf8')); } catch {}
const todo = PICKS.filter(p => !only.length || only.includes(p[2])).filter(p => only.length || index[p[2]]?.status !== 'ok');
let k = 0;
async function worker() {
  while (k < todo.length) {
    const [rank, , id] = todo[k++];
    try {
      const args = [join(APP, 'extract.mjs'), `https://www.youtube.com/watch?v=${id}`, ...(LANG[id] ? [`--lang=${LANG[id]}`] : [])];
      const { stdout } = await run('node', args,
        { cwd: APP, timeout: 600000, maxBuffer: 64 * 1024 * 1024, windowsHide: true });
      const folder = (stdout.match(/Evidence saved to (.+)$/m) || [])[1]?.trim();
      const r = await prepare(folder);
      index[id] = { status: r.words > 50 ? 'ok' : 'no_captions', rank, folder, ...r };
      console.log(`#${rank} ${id} ${index[id].status} ${r.track} words ${r.words}`);
    } catch (e) {
      index[id] = { status: 'failed', rank, error: String(e.message).slice(0, 200) };
      console.log(`#${rank} ${id} FAILED ${String(e.message).slice(0, 100)}`);
    }
    await writeFile(idxPath, JSON.stringify(index, null, 1));
  }
}
await Promise.all(Array.from({ length: conc }, worker));
const st = Object.values(index).reduce((m, v) => (m[v.status] = (m[v.status] || 0) + 1, m), {});
console.log('summary', JSON.stringify(st));
