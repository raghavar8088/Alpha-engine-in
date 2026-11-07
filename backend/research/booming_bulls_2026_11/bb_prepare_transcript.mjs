// Phase 2: prepare a readable transcript from one evidence folder made by the Video Explainer app
// (youtube-video-explainer-reviewed/extract.mjs). Collapses rolling auto-captions, romanizes
// Devanagari, groups into 30-second blocks, and writes data/transcripts/<id>.txt plus a stats line.
// Usage: node bb_prepare_transcript.mjs <evidence folder> [blockSeconds=30]
import { readFile, writeFile, readdir, mkdir } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { collapseRolling, romanize, blocks } from './bb_transcript_tools.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'data', 'transcripts');

export async function prepare(folder, blockSeconds = 30) {
  const cues = JSON.parse(await readFile(join(folder, 'transcript.json'), 'utf8'));
  const manifest = JSON.parse(await readFile(join(folder, 'manifest.json'), 'utf8'));
  const track = (await readdir(folder)).find(f => /^(captions|speech)\./.test(f)) || 'none';
  const id = basename(folder).replace(/-\d+$/, '');
  const words = collapseRolling(cues);
  const rawWords = cues.reduce((n, c) => n + c.text.split(/\s+/).filter(Boolean).length, 0);
  const lines = blocks(words, blockSeconds, romanize);
  const header = [
    `# ${manifest.title}`,
    `# id ${id} | track ${track} | duration ${Math.round(manifest.duration)} s | cues ${cues.length} | words raw ${rawWords} -> ${words.length}`,
    `# source evidence: ${folder}`,
    '',
  ];
  await mkdir(OUT, { recursive: true });
  const file = join(OUT, id + '.txt');
  await writeFile(file, header.join('\n') + lines.join('\n') + '\n');
  return { id, track, duration: Math.round(manifest.duration), cues: cues.length, rawWords, words: words.length, file };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const r = await prepare(process.argv[2], Number(process.argv[3]) || 30);
  console.log(JSON.stringify(r));
}
