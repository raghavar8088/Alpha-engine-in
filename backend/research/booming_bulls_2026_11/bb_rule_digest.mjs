// Phase 2 helper for the long 2020–2024 videos: a "rule digest" of a prepared transcript.
// Keeps the first N blocks (where the strategy is usually announced) plus every 30-second block
// that scores on rule vocabulary (entry, stop, target, ratios, indicators, timing, candles),
// best-scoring first, up to a cap, then prints them in time order. Analyses built from a digest
// say so: it is a partial read.
// Usage: node bb_rule_digest.mjs <id> [maxBlocks=14] [headBlocks=3]
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const [id, maxArg, headArg] = process.argv.slice(2);
const max = Number(maxArg) || 14, head = Number(headArg) || 3;
const text = await readFile(join(HERE, 'data', 'transcripts', id + '.txt'), 'utf8');
const lines = text.split(/\r?\n/);
const header = lines.filter(l => l.startsWith('#') && !l.startsWith('# source'));
const blocks = lines.filter(l => l.startsWith('['));

const TERMS = [
  /stop ?los/g, /taaraget/g, /entree/g, /\brool/g, /setaap/g, /1:\d|1 \d\.\d/g, /risk rivo?a?rd/g,
  /eemae|eeemae|\bema\b|mooving evarej|dema/g, /aaraesaaee|\brsi\b|daayavarjens|daaivarajens/g,
  /eedeeeks|\badx\b|vee ?vaip|\bvwap\b|pivo?t|stokaast|bilinjar|phibonaachee|supar ?trend/g,
  /kaindal/g, /brekaaaut|brekadaaun|reeitest|reetest|traip/g, /taaim phrem|\d+ minat/g,
  /\d{1,2}:\d{2}|baje/g, /\bsel\b|\bbaay\b|short|long/g, /premiyam|preemiyam|straaik|ekspaayaree|opshan/g,
];
const score = b => TERMS.reduce((n, re) => n + (b.match(re) || []).length, 0);
const ranked = blocks.map((b, i) => ({ b, i, s: score(b) })).filter(x => x.i >= head).sort((a, b) => b.s - a.s).slice(0, Math.max(0, max - head));
const keep = new Set([...blocks.slice(0, head).map((_, i) => i), ...ranked.map(x => x.i)]);
console.log(header.join('\n'));
console.log(`# digest: ${keep.size} of ${blocks.length} blocks (first ${head} + top-scoring rule blocks)`);
for (const [i, b] of blocks.entries()) if (keep.has(i)) console.log(b);
