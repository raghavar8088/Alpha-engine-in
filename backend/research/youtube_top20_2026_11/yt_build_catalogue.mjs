// Phase 1 deliverable: catalogue/CATALOGUE.md (selection evidence + picks per channel) and catalogue/catalogue.csv
// (every long-form upload of the 20 channels: id, channel, title, views, length, strategy-pool / picked / analysis status).
// Usage: node yt_build_catalogue.mjs
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PICKS } from './yt_picks.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = join(HERE, 'data');
const OUT = join(HERE, 'catalogue');
await mkdir(OUT, { recursive: true });
const J = async p => JSON.parse(await readFile(p, 'utf8'));
const top = await J(join(DATA, 'top20.json'));
const pool = await J(join(DATA, 'strategy_pool.json'));
const tx = await J(join(DATA, 'transcripts', '_index.json'));
const c1 = (await J(join(DATA, 'candidates.json'))).candidates, c2 = (await J(join(DATA, 'candidates2.json'))).candidates;
const picked = new Map(PICKS.map(([rank, cid, vid, why]) => [vid, { rank, cid, why }]));
const md = s => String(s ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim();
const mmss = s => s == null ? '' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const fmtN = n => n == null ? '' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'K' : String(n);

const rows = [];
for (const [i, c] of top.top20.entries()) {
  const L = (await J(join(DATA, 'listings', `${c.channel_id}.json`))).entries;
  const inPool = new Set((pool[c.channel_id] || []).map(e => e.id));
  for (const e of L) {
    const t = tx[e.id];
    rows.push({ rank: i + 1, channel: c.name, channel_id: c.channel_id, id: e.id, url: `https://www.youtube.com/watch?v=${e.id}`,
      title: e.title, views: e.views ?? '', duration_s: e.duration ?? '', strategy_pool: inPool.has(e.id),
      picked: picked.has(e.id), analysis: !picked.has(e.id) ? '' : t?.status === 'ok' ? 'analysed' : 'no captions',
      caption_track: t?.track || '' });
  }
}
const cols = Object.keys(rows[0]);
const csv = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
await writeFile(join(OUT, 'catalogue.csv'), '﻿' + [cols.join(','), ...rows.map(r => cols.map(c => csv(r[c])).join(','))].join('\r\n') + '\r\n');

const L = [];
L.push('# The 20 largest trading-strategy YouTube channels: catalogue', '');
L.push(`Built ${new Date().toISOString().slice(0, 10)} by \`yt_build_catalogue.mjs\`. Every number comes from YouTube via yt-dlp on 7 Nov 2026.`, '');
L.push('## Selection', '');
L.push(`- **Candidates:** ${c1.length + c2.length} candidate channels, from published "best trading YouTubers" lists plus well-known channels. Each channel's live subscriber count, id and full upload list were read with yt-dlp.`);
L.push('- **Inclusion rule:** of a channel\'s 50 most-viewed long-form videos, at least 25 titles are about trading, and more than are investing-only (`yt_listings_rules.mjs`).');
L.push('- **Booming Bulls** (4.21M) is excluded, since it was studied separately (`../booming_bulls_2026_11`).');
L.push('- **Not covered:** channels outside the candidate pool can be missed. This is the top 20 of the pool, not a census of YouTube.', '');
L.push('| # | Channel | Subscribers | Long-form videos | Top-50 titles: trading / investing-only | Channel id |', '|--:|---|--:|--:|---|---|');
for (const [i, c] of top.top20.entries()) L.push(`| ${i + 1} | ${md(c.name)} | ${fmtN(c.followers)} | ${c.videos} | ${c.top50_trading} / ${c.top50_investing_only} | \`${c.channel_id}\` |`);
L.push('', '**Excluded by the rule** (above the 20th channel\'s size):', '');
L.push('| Channel | Subscribers | Top-50 titles: trading / investing-only |', '|---|--:|---|');
for (const c of top.excluded) L.push(`| ${md(c.name)} | ${fmtN(c.followers)} | ${c.top50_trading} / ${c.top50_investing_only} |`);
L.push('', '## Strategy videos per channel', '');
L.push('The pool for each channel holds its most-viewed long-form videos (4 minutes or more) whose titles name a strategy, setup, system or indicator. **Picked** videos were analysed (`../analyses/`). Videos with "no captions" could not be read, because Whisper is not installed.', '');
for (const [i, c] of top.top20.entries()) {
  L.push(`### #${i + 1} ${md(c.name)}`, '');
  L.push('| Video | Views | Length | Title | Status |', '|---|--:|--:|---|---|');
  for (const e of (pool[c.channel_id] || []).slice(0, 10)) {
    const p = picked.get(e.id);
    const st = p ? (tx[e.id]?.status === 'ok' ? `**picked, analysed**: ${md(p.why)}` : '**picked, no captions**') : '';
    L.push(`| [${e.id}](https://www.youtube.com/watch?v=${e.id}) | ${fmtN(e.views)} | ${mmss(e.duration)} | ${md(e.title).slice(0, 90)} | ${st} |`);
  }
  for (const [vid, p] of picked) {
    if (p.cid === c.channel_id && !(pool[c.channel_id] || []).slice(0, 10).some(e => e.id === vid)) {
      L.push(`| [${vid}](https://www.youtube.com/watch?v=${vid}) | | | (outside the top 10 of the pool) | **picked, ${tx[vid]?.status === 'ok' ? 'analysed' : 'no captions'}**: ${md(p.why)} |`);
    }
  }
  L.push('');
}
await writeFile(join(OUT, 'CATALOGUE.md'), L.join('\n'));
console.log('catalogue:', rows.length, 'uploads,', [...picked.keys()].length, 'picks');
