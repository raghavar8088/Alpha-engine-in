// Lists the playlists of the 20 selected channels (titles and video counts) through the Trading Video Lab's yt-dlp,
// one channel every 20 seconds, never retrying a "slow down" answer, and saves registry/playlists.json. Strategy-like
// playlists are then opened (one request each, same pacing) to see whether they hold strategy videos that are not in
// the channel's own upload list (e.g. guest videos).
//   node playlists.mjs
import { writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const YTDLP = tool('yt-dlp');
const CHANNELS = {
  dhanhq: 'UCEzHCpvFWoF85UabbzKTkOQ', abhishekxtrades: 'UCUJmHX01pQAsP8yQ_TfsmZw', upsurgeclub: 'UCQQojT_AmVWGb4Eg-QniuBA',
  deltaexchange: 'UCaw-1cUd74wvEatvZna0TzQ', tradewithpat: 'UC04-HvUvHG4hpMnQx07ObYQ', datatraders: 'UCwIsRM8qBXobpAnzVJ0c4IQ',
  tradinglabofficial: 'UCCbv0qixG-cyokxEY3kELtg', officialjesserogers: 'UCEAq-8Ih0WI6R7wYoCFiWmA', devanshrai: 'UCRem0cxZp0CNrJaFGRB2Tpw',
  stockinvestmentacademy: 'UCPtgdNLXi2QglhJBidB6QNw', thetradingschooltrafi: 'UCUzGUWt1zx8krC5i3Lzv7rA', holdwithpriyank: 'UCRI4NNcBZzBdVzfSlXdGwCw',
  tradingrush: 'UCgY_eHY4NCTcRnU6CCZXWng', tradbuilder: 'UCIaCP4uF4NpYXnx1Nq7JK-Q', protradingschool6692: 'UCB5dISM93_Vr5i5AvZgTGFg',
  transparentfxacademy: 'UC-vGMbd-jPqGpsuaObDHvmA', tradingdata1: 'UCV9hkwgSFkAwS4hN_0oxinA', vijaythakkar: 'UCHvscyzKoKxhLcaz1LQ6mHg',
  faizsmcfx: 'UC9N9JnSg9aL2w4D0kITQcaw', mulhamtrading: 'UCJFDZ3Xab4vXDSQJrvaFXIw',
};
const STRATEGY = /strateg|setup|scalp|intraday|swing|option (buying|selling)|price action|indicator|course|masterclass|gold|crypto|bitcoin|ict|smc|backtest/i;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const run = args => new Promise((resolve, reject) => {
  const p = spawn(YTDLP, args, { env: { ...process.env, PATH: toolPath() } });
  let out = '', err = '';
  p.stdout.on('data', d => out += d); p.stderr.on('data', d => err += d);
  p.on('close', code => code === 0 ? resolve(out) : reject(new Error(err.slice(-400) || 'exit ' + code)));
});
const OUT = join(HERE, 'registry', 'playlists.json');
const res = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
for (const [slug, id] of Object.entries(CHANNELS)) {
  if (res[slug]?.playlists) continue;
  try {
    const j = JSON.parse(await run(['--ignore-config', '--flat-playlist', '--dump-single-json', '--playlist-end', '200',
      '--socket-timeout', '20', 'https://www.youtube.com/channel/' + id + '/playlists']));
    const pls = (j.entries || []).map(e => ({ id: e.id, title: e.title, count: e.playlist_count ?? null }));
    res[slug] = { channel: id, playlists: pls, strategy_like: pls.filter(p => STRATEGY.test(p.title || '')).map(p => p.id) };
    console.log(slug.padEnd(24), pls.length, 'playlists,', res[slug].strategy_like.length, 'strategy-like');
  } catch (e) {
    res[slug] = { channel: id, error: String(e.message).slice(0, 300) };
    console.log(slug, 'ERROR', String(e.message).slice(0, 160));
    if (/429|Too Many|Sign in to confirm/i.test(e.message)) { console.log('YouTube asked to slow down: stopping here'); break; }
  }
  writeFileSync(OUT, JSON.stringify(res, null, 1));
  await sleep(20000);
}
writeFileSync(OUT, JSON.stringify(res, null, 1));
