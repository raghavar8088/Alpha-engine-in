// The owner's gold channel list 21-40 (22 Nov 2026), resolved into this study's own file
// (catalogue/channels.json) so the shared shortlist registry stays untouched. Ten of the twenty channels are
// already in that registry (their YouTube id is taken from it); the other ten are found with a YouTube channel
// search (top 5 candidates scored on the name, the best one picked). The catalogue step fills the Video Lab's
// channel files (data/channels/<UCid>.json: every upload's title, length, views and date); the gold step lists
// each channel's uploads whose titles name gold.
//   node zg_channels.mjs resolve | catalogue | gold [key]
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, writeFileSync, existsSync, statSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run0 = promisify(execFile);
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'catalogue', 'channels.json');
const SHORTLIST = join(HERE, '..', 'youtube_shortlist_2026_11', 'registry', 'channels.json');

// [key, name as listed, search query, list position, the shortlist registry key ('' = not there)]
export const CHANNELS = [
  ['axiafutures', 'Axia Futures', '', 21, 'axiafutures'],
  ['bikotrading', 'BikoTrading - Futures Trading', 'BikoTrading futures trading', 22, ''],
  ['tradingorbit', 'Trading Orbit', 'Trading Orbit delta exchange', 23, ''],
  ['propfirmtrader', 'PropFirmTrader', 'PropFirmTrader', 24, ''],
  ['themovingaverage', 'The Moving Average', '', 25, 'themovingaverage'],
  ['atas', 'ATAS - English', '', 26, 'atas'],
  ['fractalflow', 'Fractal Flow - Pro Trading Strategies', 'Fractal Flow Pro trading strategies', 27, ''],
  ['ttrades', 'TTrades', 'TTrades', 28, ''],
  ['cammycapital', 'Cammy Capital', 'Cammy Capital', 29, ''],
  ['hannahforex', 'HANNAH FOREX', 'HANNAH FOREX', 30, ''],
  ['tradingrush', 'Trading Rush', '', 31, 'tradingrush'],
  ['tradepro', 'Trade Pro', '', 32, 'tradepro'],
  ['orderflows', 'Orderflows - Michael Valtos', 'Orderflows Michael Valtos', 33, ''],
  ['jigsawtrading', 'Jigsaw Trading', '', 34, 'jigsawtrading'],
  ['optimusfutures', 'Optimus Futures', '', 35, 'optimusfutures'],
  ['ninjatrader', 'NinjaTrader', '', 36, 'ninjatrader'],
  ['karenfoo', 'Karen Foo', 'Karen Foo trader', 37, ''],
  ['sahasra', 'Sahasra - A Trading Community', 'Sahasra A Trading Community', 38, ''],
  ['ukspreadbetting', 'UKspreadbetting', '', 39, 'ukspreadbetting'],
  ['pepperstone', 'Pepperstone', '', 40, 'pepperstone'],
];

const ytdlp = (args, timeout = 300_000) =>
  run0(tool('yt-dlp'), args, { env: { ...process.env, PATH: toolPath() }, maxBuffer: 1 << 28, timeout });
const norm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').trim();
const STOP = ['the', 'by', 'with', 'trading', 'and', 'of', 'a', 'pro', 'strategies', 'futures', 'community', 'english'];
const toks = s => new Set(norm(s).split(' ').filter(t => t.length > 1 && !STOP.includes(t)));
function score(name, title) {
  const want = toks(name);
  const got = toks(title);
  if (!want.size || !got.size) return 0;
  let hit = 0;
  for (const t of got) if (want.has(t)) hit++;
  return hit / got.size;
}

async function resolve() {
  mkdirSync(dirname(OUT), { recursive: true });
  const out = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
  const reg = JSON.parse(readFileSync(SHORTLIST, 'utf8'));
  for (const [key, name, query, pos, regKey] of CHANNELS) {
    if (out[key]?.pick) continue;
    if (regKey) {
      const r = reg[regKey];
      out[key] = { key, name, pos, earlier: 'shortlist ' + (r?.lists || ''), pick: r?.pick || null, pick_title: r?.pick_title || null,
        pick_followers: r?.pick_followers ?? null };
      continue;
    }
    const url = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(query) + '&sp=EgIQAg%253D%253D';
    try {
      const { stdout } = await ytdlp(['--ignore-config', '--no-warnings', '--flat-playlist', '-J', '--playlist-end', '5', url], 120_000);
      const j = JSON.parse(stdout);
      const candidates = (j.entries || []).filter(e => /^UC[\w-]{22}$/.test(e.id || '')).map(e => ({
        id: e.id, title: e.title || e.channel, followers: e.channel_follower_count ?? null,
        about: String(e.description || '').slice(0, 140).replace(/\s+/g, ' '), score: +score(name, e.title || e.channel).toFixed(2),
      }));
      const good = candidates.filter(c => c.score >= 0.5);
      const pick = (good.length ? good : candidates).slice().sort((a, b) => (b.score >= 0.5) - (a.score >= 0.5) || b.score - a.score || (b.followers || 0) - (a.followers || 0))[0] || null;
      out[key] = { key, name, query, pos, earlier: '', candidates, pick: pick?.id || null, pick_title: pick?.title || null, pick_followers: pick?.followers ?? null };
    } catch (e) {
      out[key] = { key, name, query, pos, earlier: '', error: String(e.message).slice(0, 200) };
    }
    writeFileSync(OUT, JSON.stringify(out, null, 1));
    process.stdout.write(`${key}: ${out[key].pick_title || out[key].error} (${out[key].pick_followers ?? '-'})\n`);
  }
  writeFileSync(OUT, JSON.stringify(out, null, 1));
  for (const r of Object.values(out)) process.stdout.write(`${String(r.pos).padStart(2)} ${r.key.padEnd(17)} ${r.pick} ${r.pick_title} (${r.pick_followers ?? '-'})${r.earlier ? ' [' + r.earlier + ']' : ''}\n`);
}

async function catalogue() {
  const { catalogueChannel } = await import('file:///' + APP + '/lib/channels.mjs');
  const reg = JSON.parse(readFileSync(OUT, 'utf8'));
  const only = process.argv[3] ? new Set(process.argv[3].split(',')) : null;
  const todo = Object.values(reg).filter(r => r.pick && (!only || only.has(r.key)));
  const fresh = id => { const f = join(APP, 'data', 'channels', id + '.json'); return existsSync(f) && Date.now() - statSync(f).mtimeMs < 7 * 86400e3; };
  let i = 0;
  const worker = async () => {
    while (i < todo.length) {
      const r = todo[i++];
      if (fresh(r.pick) && !only) { process.stdout.write(`${r.key}: catalogue fresh, kept\n`); continue; }
      const t0 = Date.now();
      try {
        const s = await catalogueChannel('https://www.youtube.com/channel/' + r.pick, { tabs: ['videos', 'streams'], limit: 3000 });
        process.stdout.write(`${r.key}: ${s.total} uploads, P1 ${s.p1}, P2 ${s.p2} (${((Date.now() - t0) / 1000).toFixed(0)} s)\n`);
      } catch (e) {
        process.stdout.write(`${r.key}: FAILED ${String(e.message).slice(0, 160)}\n`);
      }
    }
  };
  await Promise.all([worker(), worker(), worker()]);
}

const GOLD = /\bgold\b|xau|xaut|paxg|\bgc\b|\bmgc\b|metals?\b|bullion/i;
function gold() {
  const reg = JSON.parse(readFileSync(OUT, 'utf8'));
  const only = process.argv[3] || '';
  for (const r of Object.values(reg)) {
    if (only && r.key !== only) continue;
    const f = join(APP, 'data', 'channels', r.pick + '.json');
    if (!existsSync(f)) { process.stdout.write(`\n## ${r.pos} ${r.key}: no catalogue\n`); continue; }
    const c = JSON.parse(readFileSync(f, 'utf8'));
    const hits = c.entries.filter(e => GOLD.test(e.title)).sort((a, b) => (b.views || 0) - (a.views || 0));
    process.stdout.write(`\n## ${r.pos} ${r.key} (${c.channel?.title}): ${c.entries.length} uploads, ${hits.length} gold titles\n`);
    for (const e of hits.slice(0, only ? 80 : 25)) {
      process.stdout.write(`  ${e.id} ${String(e.published || '').padEnd(10)} ${String(Math.round((e.duration || 0) / 60)).padStart(3)}m ${String(e.views ?? '').padStart(8)} ${e.kind} ${e.title.slice(0, 110)}\n`);
    }
  }
}

const cmd = process.argv[2];
if (cmd === 'resolve') await resolve();
else if (cmd === 'catalogue') await catalogue();
else if (cmd === 'gold') gold();
else console.log('usage: node zg_channels.mjs resolve | catalogue [keys] | gold [key]');
