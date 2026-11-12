// Video discovery for the four-topic intraday cycle (Nov 2026): YouTube's own search results for strategy queries in
// NIFTY intraday option buying, NSE stock intraday, bitcoin intraday and MCX commodity intraday, through the Trading
// Video Lab's yt-dlp (titles and details only, no media). Videos already covered (registry/covered.json) are marked,
// not dropped, so the selection shows what was skipped and why. The 20-channel study's search results
// (its registry/discovery.json) are merged in as a second pool for the three markets it also searched.
//   node zd_discover.mjs            -> registry/discovery.json  (resumes: a query already run is not asked again)
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run0 = promisify(execFile);
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const YTDLP = tool('yt-dlp');
const HERE = dirname(fileURLToPath(import.meta.url));
const YT = ['--ignore-config', '--no-warnings', '--socket-timeout', '20', '--retries', '2', '--flat-playlist', '-J'];
const sleep = ms => new Promise(r => setTimeout(r, ms));

export const QUERIES = {
  nifty_option_buying: [
    'nifty option buying strategy intraday', 'nifty option buying strategy hindi', 'option buying strategy nifty 5 minute',
    'nifty scalping strategy option buying', 'best option buying strategy for beginners nifty', 'nifty options intraday strategy vwap',
    'option buying strategy supertrend nifty', 'nifty expiry day option buying strategy', 'nifty 50 option buying setup rules stop loss target',
    'option buying strategy ema crossover nifty',
  ],
  stock_intraday: [
    'intraday trading strategy stocks india', 'intraday stock selection strategy hindi', 'opening range breakout intraday stocks nse',
    'intraday strategy 15 minute candle stocks', 'intraday trading strategy for beginners hindi rules', 'vwap intraday strategy stocks hindi',
    'intraday momentum stocks strategy 9:15', 'high probability intraday trading setup stocks india', 'intraday scalping strategy stocks 5 minute hindi',
    'intraday trading strategy ema stocks hindi',
  ],
  btc_intraday: [
    'bitcoin intraday trading strategy', 'btc scalping strategy 5 minute', 'bitcoin day trading strategy 15 minute',
    'crypto intraday trading strategy hindi', 'btc futures intraday strategy delta exchange', 'bitcoin scalping strategy 1 minute',
    'bitcoin trading strategy ema rsi', 'btc intraday strategy vwap', 'bitcoin opening range breakout strategy',
    'crypto scalping strategy that works backtest',
  ],
  commodity_intraday: [
    'crude oil intraday strategy mcx', 'natural gas intraday strategy mcx', 'mcx commodity intraday trading strategy hindi',
    'crude oil scalping strategy', 'mcx gold intraday strategy', 'silver intraday trading strategy mcx',
    'commodity trading strategy for beginners hindi', 'crude oil trading strategy 5 minute', 'crude oil intraday trading setup rules',
    'natural gas trading strategy hindi',
  ],
};
// the 20-channel study's queries mapped to this cycle's topics (gold was a separate market there; its MCX query counts here)
const PRIOR = { in_options: 'nifty_option_buying', in_equity: 'stock_intraday', crypto: 'btc_intraday' };
const PRIOR_EXTRA = { 'mcx gold intraday strategy': 'commodity_intraday' };

const covered = JSON.parse(readFileSync(join(HERE, 'registry', 'covered.json'), 'utf8'));
const OUT = join(HERE, 'registry', 'discovery.json');
const prev = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : { results: {} };
const results = prev.results || {};
let stopped = false;

for (const [topic, qs] of Object.entries(QUERIES)) {
  if (stopped) break;
  for (const q of qs) {
    if (results[q] && !results[q].error) continue;
    try {
      const { stdout } = await run0(YTDLP, [...YT, `ytsearch30:${q}`], { maxBuffer: 64 * 1024 * 1024, timeout: 180000, windowsHide: true,
        env: { ...process.env, PATH: toolPath() } });
      const j = JSON.parse(stdout);
      results[q] = { topic, at: new Date().toISOString(), entries: (j.entries || []).map(e => ({
        id: e.id, title: e.title, channel: e.channel, channel_id: e.channel_id, views: e.view_count ?? null, duration: e.duration ?? null })) };
      console.log(topic.padEnd(20), String(results[q].entries.length).padStart(3), q);
    } catch (e) {
      const msg = String(e.stderr || e.message).split('\n').find(l => l.includes('ERROR')) || String(e.message).slice(0, 160);
      results[q] = { topic, error: msg };
      console.log('ERROR', q, msg);
      if (/429|Too Many|sign in|bot/i.test(msg)) { console.log('YouTube asked to slow down: stopping here (resume later)'); stopped = true; break; }
    }
    writeFileSync(OUT, JSON.stringify({ results }, null, 1));
    await sleep(3000);
  }
}

// pool: this cycle's results plus the 20-channel study's, one row per video
const zc = JSON.parse(readFileSync(join(HERE, '..', 'youtube_channels20_2026_11', 'registry', 'discovery.json'), 'utf8')).results;
const pool = new Map();
const addRow = (e, topic, q, src) => {
  if (!e.id || e.id.length !== 11) return;
  const row = pool.get(e.id) || { ...e, topics: [], queries: [], sources: [] };
  if (!row.topics.includes(topic)) row.topics.push(topic);
  if (!row.queries.includes(q)) row.queries.push(q);
  if (!row.sources.includes(src)) row.sources.push(src);
  pool.set(e.id, row);
};
for (const [q, r] of Object.entries(results)) for (const e of r.entries || []) addRow(e, r.topic, q, 'zd');
for (const [q, r] of Object.entries(zc)) {
  const topic = PRIOR_EXTRA[q] || PRIOR[r.market];
  if (!topic) continue;
  for (const e of r.entries || []) addRow(e, topic, q, 'zc');
}
const rows = [...pool.values()].map(r => ({ ...r, covered: covered.videos[r.id] ? covered.videos[r.id].studies.join(',') : '' }));
writeFileSync(join(HERE, 'registry', 'pool.json'), JSON.stringify(rows, null, 1));
const byTopic = {};
for (const r of rows) for (const t of r.topics) {
  byTopic[t] = byTopic[t] || { all: 0, covered: 0 };
  byTopic[t].all++; if (r.covered) byTopic[t].covered++;
}
console.log('pool', rows.length, JSON.stringify(byTopic));
