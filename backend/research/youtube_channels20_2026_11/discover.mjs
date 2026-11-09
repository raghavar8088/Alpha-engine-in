// Channel discovery for the 20-channel cycle: YouTube's own search results for strategy-specific queries in the four
// markets (Indian equity intraday, Indian options, crypto, gold), aggregated per channel. Channels already covered
// (registry/covered.json: analyzed or partial) are marked, not dropped, so the report shows what was skipped and why.
// The ranking is by how many DIFFERENT strategy queries surface a channel's videos, never by subscribers.
//   node discover.mjs            -> registry/discovery.json
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run0 = promisify(execFile);
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const YTDLP = tool('yt-dlp');
const run = (prog, args, opts) => run0(prog === 'yt-dlp' ? YTDLP : prog, args, { ...opts, env: { ...process.env, PATH: toolPath() } });
const HERE = dirname(fileURLToPath(import.meta.url));
const YT = ['--ignore-config', '--no-warnings', '--socket-timeout', '20', '--retries', '2', '--flat-playlist', '-J'];
const sleep = ms => new Promise(r => setTimeout(r, ms));

export const QUERIES = {
  in_equity: [
    'intraday trading strategy hindi stocks rules', 'opening range breakout strategy intraday stocks india',
    'vwap intraday strategy indian stocks', 'intraday scalping strategy nse stocks 5 minute',
    'price action intraday strategy hindi', 'supertrend intraday strategy stocks hindi',
    'gap up gap down intraday strategy stocks', 'intraday trading setup with stop loss target hindi',
    'momentum stocks intraday strategy india', 'swing trading strategy indian stocks rules',
  ],
  in_options: [
    'nifty option buying strategy hindi', 'bank nifty option scalping strategy', 'nifty option selling strategy rules',
    'short straddle strategy nifty backtest', 'expiry day option strategy nifty', 'iron condor nifty weekly strategy',
    'option buying strategy 9:20 nifty', 'sensex expiry option strategy', 'bank nifty intraday option strategy hindi',
    'nifty options intraday strategy ema rsi',
  ],
  crypto: [
    'bitcoin scalping strategy', 'crypto trading strategy that works', 'bitcoin day trading strategy rules',
    'crypto futures trading strategy hindi', 'btc 15 minute strategy', 'crypto indicator strategy tested',
    'delta exchange trading strategy', 'ethereum trading strategy rules', 'bitcoin swing trading strategy',
    'crypto scalping strategy 5 minute',
  ],
  gold: [
    'xauusd scalping strategy', 'gold trading strategy rules', 'gold day trading strategy london session',
    'xauusd 15 minute strategy', 'gold trading strategy hindi', 'gold scalping strategy 1 minute',
    'xauusd smart money strategy', 'gold breakout strategy new york session', 'mcx gold intraday strategy',
    'gold swing trading strategy',
  ],
};

const covered = JSON.parse(readFileSync(join(HERE, 'registry', 'covered.json'), 'utf8'));
const skip = new Map();
for (const c of covered.channels) if (c.id && (c.status === 'analyzed' || c.status === 'partial')) skip.set(c.id, c.studies.join(','));
const OUT = join(HERE, 'registry', 'discovery.json');
const prev = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : { results: {} };
const results = prev.results || {};

for (const [market, qs] of Object.entries(QUERIES)) {
  for (const q of qs) {
    if (results[q]) continue;                              // resume: a query already run is not asked again
    try {
      const { stdout } = await run('yt-dlp', [...YT, `ytsearch30:${q}`], { maxBuffer: 64 * 1024 * 1024, timeout: 180000, windowsHide: true });
      const j = JSON.parse(stdout);
      results[q] = { market, at: new Date().toISOString(), entries: (j.entries || []).map(e => ({
        id: e.id, title: e.title, channel: e.channel, channel_id: e.channel_id, views: e.view_count ?? null, duration: e.duration ?? null })) };
      console.log(market.padEnd(10), String(results[q].entries.length).padStart(3), q);
    } catch (e) {
      const msg = String(e.stderr || e.message).split('\n').find(l => l.includes('ERROR')) || String(e.message).slice(0, 160);
      results[q] = { market, error: msg };
      console.log('ERROR', q, msg);
      if (/429|Too Many|sign in|bot/i.test(msg)) { console.log('YouTube asked to slow down: stopping here (resume later)'); break; }
    }
    writeFileSync(OUT, JSON.stringify({ results }, null, 1));
    await sleep(2500);
  }
}

// aggregate per channel
const per = new Map();
for (const [q, r] of Object.entries(results)) {
  for (const e of r.entries || []) {
    if (!e.channel_id) continue;
    const c = per.get(e.channel_id) || { channel: e.channel, channel_id: e.channel_id, queries: new Set(), markets: new Set(), videos: new Map() };
    c.queries.add(q); c.markets.add(r.market);
    if (!c.videos.has(e.id)) c.videos.set(e.id, { id: e.id, title: e.title, views: e.views, duration: e.duration, market: r.market });
    per.set(e.channel_id, c);
  }
}
const rows = [...per.values()].map(c => ({
  channel: c.channel, channel_id: c.channel_id, n_queries: c.queries.size, markets: [...c.markets], n_videos: c.videos.size,
  covered: skip.get(c.channel_id) || null, videos: [...c.videos.values()].slice(0, 12),
})).sort((a, b) => b.n_queries - a.n_queries || b.n_videos - a.n_videos);
writeFileSync(OUT, JSON.stringify({ results, channels: rows }, null, 1));
console.log('channels', rows.length);
for (const r of rows.slice(0, 70)) {
  console.log(String(r.n_queries).padStart(2), String(r.n_videos).padStart(3), r.markets.join('+').padEnd(28), (r.covered ? '[covered] ' : '') + r.channel, r.channel_id);
}
