// The owner's crypto channel list 21-40 (14 Nov 2026), resolved into its own file so the shared registry stays untouched
// while another session's batch is open: catalogue/selection/channels_r21.json. Same search and pick logic as
// ze_channels.mjs (YouTube channel search, top 5 candidates, a pick); the catalogue step fills the Lab's channel files.
//   node ze_channels_r21.mjs resolve | catalogue
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, writeFileSync, existsSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run0 = promisify(execFile);
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'catalogue', 'selection', 'channels_r21.json');

// [key, name as listed, search query, list position, market group]; the six channels already in the registry are listed
// with their registry key and are not resolved again (their picks come from registry/channels.json).
export const CHANNELS = [
  ['codetrading', 'CodeTrading', '', 21, 'sys', 'registry'],
  ['algovibes', 'Algovibes', '', 22, 'sys', 'registry'],
  ['robottraders', 'Robot Traders', 'Robot Traders algorithmic trading', 23, 'sys', ''],
  ['quantnomad', 'QuantNomad', 'QuantNomad', 24, 'sys', ''],
  ['chadthackray', 'Chad Thackray', 'Chad Thackray vectorbt', 25, 'sys', ''],
  ['qubitquants', 'Qubit Quants', 'Qubit Quants', 26, 'sys', ''],
  ['pyquantnews', 'PyQuant News', 'PyQuant News', 27, 'sys', ''],
  ['tradescience', 'Trade Science', 'Trade Science walk forward', 28, 'sys', ''],
  ['artoftrading', 'The Art of Trading', '', 29, 'fx', 'registry'],
  ['tradingrush', 'Trading Rush', '', 30, 'fx', 'registry'],
  ['altfins', 'altFINS', 'altFINS crypto', 31, 'crypto', ''],
  ['altrady', 'Altrady', 'Altrady crypto trading', 32, 'crypto', ''],
  ['wundertrading', 'WunderTrading', 'WunderTrading', 33, 'crypto', ''],
  ['threecommas', '3Commas', '3Commas official', 34, 'crypto', ''],
  ['cryptohopper', 'Cryptohopper', 'Cryptohopper', 35, 'crypto', ''],
  ['coinrule', 'Coinrule', 'Coinrule', 36, 'crypto', ''],
  ['bitsgap', 'Bitsgap', 'Bitsgap', 37, 'crypto', ''],
  ['secretmindset', 'The Secret Mindset', 'The Secret Mindset trading', 38, 'fx', 'top20'],
  ['quantinsti', 'QuantInsti', '', 39, 'sys', 'registry'],
  ['quantconnect', 'QuantConnect', '', 40, 'sys', 'registry'],
];

const ytdlp = (args, timeout = 300_000) =>
  run0(tool('yt-dlp'), args, { env: { ...process.env, PATH: toolPath() }, maxBuffer: 1 << 28, timeout });
const norm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').trim();
const toks = s => new Set(norm(s).split(' ').filter(t => t.length > 1 && !['the', 'by', 'with', 'trading', 'and', 'of'].includes(t)));
function score(name, query, title) {
  const want = new Set([...toks(name), ...toks(query)]);
  const got = toks(title);
  if (!want.size || !got.size) return 0;
  let hit = 0;
  for (const t of got) if (want.has(t)) hit++;
  return hit / got.size;
}

async function resolve() {
  const out = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
  const reg = JSON.parse(readFileSync(join(HERE, 'registry', 'channels.json'), 'utf8'));
  for (const [key, name, query, pos, group, src] of CHANNELS) {
    if (out[key]?.pick) continue;
    if (src === 'registry') {
      const r = reg[key];
      out[key] = { key, name, pos, group, earlier: 'shortlist ' + (r?.lists || ''), pick: r?.pick || null, pick_title: r?.pick_title || null };
      continue;
    }
    const url = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(query) + '&sp=EgIQAg%253D%253D';
    try {
      const { stdout } = await ytdlp(['--ignore-config', '--no-warnings', '--flat-playlist', '-J', '--playlist-end', '5', url], 120_000);
      const j = JSON.parse(stdout);
      const candidates = (j.entries || []).filter(e => /^UC[\w-]{22}$/.test(e.id || '')).map(e => ({
        id: e.id, title: e.title || e.channel, followers: e.channel_follower_count ?? null,
        about: String(e.description || '').slice(0, 140).replace(/\s+/g, ' '), score: +score(name, query, e.title || e.channel).toFixed(2),
      }));
      const good = candidates.filter(c => c.score >= 0.5);
      const pick = (good.length ? good : candidates).slice().sort((a, b) => (b.score >= 0.5) - (a.score >= 0.5) || (b.followers || 0) - (a.followers || 0))[0] || null;
      out[key] = { key, name, query, pos, group, earlier: src, candidates, pick: pick?.id || null, pick_title: pick?.title || null, pick_followers: pick?.followers ?? null };
    } catch (e) {
      out[key] = { key, name, query, pos, group, earlier: src, error: String(e.message).slice(0, 200) };
    }
    writeFileSync(OUT, JSON.stringify(out, null, 1));
    process.stdout.write(`${key}: ${out[key].pick_title || out[key].error} (${out[key].pick_followers ?? '-'})\n`);
  }
  writeFileSync(OUT, JSON.stringify(out, null, 1));
}

async function catalogue() {
  const { catalogueChannel } = await import('file:///' + APP + '/lib/channels.mjs');
  const reg = JSON.parse(readFileSync(OUT, 'utf8'));
  const todo = Object.values(reg).filter(r => r.pick);
  const fresh = id => { const f = join(APP, 'data', 'channels', id + '.json'); return existsSync(f) && Date.now() - statSync(f).mtimeMs < 7 * 86400e3; };
  let i = 0;
  const worker = async () => {
    while (i < todo.length) {
      const r = todo[i++];
      if (fresh(r.pick)) { process.stdout.write(`${r.key}: catalogue fresh, kept\n`); continue; }
      const t0 = Date.now();
      try {
        const s = await catalogueChannel('https://www.youtube.com/channel/' + r.pick, { tabs: ['videos', 'streams'], limit: 2500 });
        process.stdout.write(`${r.key}: ${s.total} uploads, P1 ${s.p1}, P2 ${s.p2} (${((Date.now() - t0) / 1000).toFixed(0)} s)\n`);
      } catch (e) {
        process.stdout.write(`${r.key}: FAILED ${String(e.message).slice(0, 160)}\n`);
      }
    }
  };
  await Promise.all([worker(), worker(), worker()]);
}

const cmd = process.argv[2];
if (cmd === 'resolve') await resolve();
else if (cmd === 'catalogue') await catalogue();
