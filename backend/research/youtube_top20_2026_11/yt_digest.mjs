// Phase 2c: a "rule digest" of a prepared transcript (English or romanized Hindi): the opening blocks plus the
// 30-second blocks that score highest on rule vocabulary (entry, stop, target, ratios, indicators and their
// settings, timeframes, clock times, candle conditions), printed in time order. An analysis built from a
// digest says so: it is a partial read. Usage: node yt_digest.mjs <id> [maxBlocks=12] [headBlocks=2]
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const [id, maxArg, headArg] = process.argv.slice(2);
const max = Number(maxArg) || 12, head = Number(headArg) || 2;
const text = await readFile(join(HERE, 'data', 'transcripts', id + '.txt'), 'utf8');
const lines = text.split(/\r?\n/);
const header = lines.filter(l => l.startsWith('#') && !l.startsWith('# source'));
const blocks = lines.filter(l => l.startsWith('['));

const TERMS = [
  // English
  /stop[- ]?loss|\bstop\b|\bsl\b/gi, /take[- ]?profit|\btarget\b|\btp\b/gi, /\bentry|\benter\b|\bexit\b/gi, /\brules?\b|\bcondition/gi,
  /\d+ ?(to|:) ?\d+(\.\d+)?|risk[- ]?(to[- ]?)?reward|r:r|\b\d(\.\d)? ?r\b/gi,
  /\bema\b|\bsma\b|moving average|\bmacd\b|\brsi\b|stochastic|\bvwap\b|bollinger|supertrend|heikin|heiken|vortex|fibonacci|\batr\b|\badx\b|pivot|\bcpr\b/gi,
  /\bperiod\b|setting|length|\b(9|20|21|50|100|200)\b/gi, /\bcandle|wick|engulf|pin ?bar|hammer|inside bar|doji/gi,
  /breakout|break(s)? (above|below)|retest|pullback|bounce|reject|cross(es|over)?\b/gi,
  /time ?frame|\b\d+[- ]?minute|\b\d+ ?(min|m)\b|hourly|daily chart|\b4[- ]?hour/gi,
  /\b\d{1,2}(:\d{2})? ?(am|pm)\b|new york|london|asian? session|open(ing)? range/gi,
  /\bbuy\b|\bsell\b|\blong\b|\bshort\b|above|below/gi,
  /win rate|%|percent|backtest/gi,
  // romanized Hindi (from the Devanagari transliteration)
  /stop ?los|taaraget|entree|\brool|setaap|eemae|mooving evarej|aaraesaaee|kaindal|brekaaaut|brekadaaun|reetest|taaim phrem|\d+ minat|baje|\bsel\b|\bbaay\b|premiyam|preemiyam|straaik|opshan/gi,
];
const score = s => TERMS.reduce((n, re) => n + (s.match(re) || []).length, 0);
const scored = blocks.map((b, i) => ({ i, b, s: score(b) }));
const pick = new Set(scored.slice(0, head).map(x => x.i));
for (const x of [...scored].sort((a, b) => b.s - a.s)) { if (pick.size >= max) break; pick.add(x.i); }
console.log(header.join('\n'));
console.log(`# digest: ${pick.size} of ${blocks.length} blocks (first ${head} + top-scoring rule blocks)`);
for (const x of scored) if (pick.has(x.i)) console.log(x.b);
