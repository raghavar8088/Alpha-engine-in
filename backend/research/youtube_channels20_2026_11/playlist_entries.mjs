// Opens each strategy-like playlist of the 20 selected channels (registry/playlists.json) and records its videos, then
// flags the ones that are NOT in the channel's own upload list (guest / other-channel videos the upload review would
// miss). One request every 15 seconds; a "slow down" answer stops the run (re-run later to resume).
//   node playlist_entries.mjs
import { writeFileSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const YTDLP = tool('yt-dlp');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const run = args => new Promise((resolve, reject) => {
  const p = spawn(YTDLP, args, { env: { ...process.env, PATH: toolPath() } });
  let out = '', err = '';
  p.stdout.on('data', d => out += d); p.stderr.on('data', d => err += d);
  p.on('close', code => code === 0 ? resolve(out) : reject(new Error(err.slice(-400) || 'exit ' + code)));
});
const PL = JSON.parse(readFileSync(join(HERE, 'registry', 'playlists.json'), 'utf8'));
const uploads = new Set();
for (const f of readdirSync(join(HERE, 'catalogue', 'raw'))) {
  for (const e of JSON.parse(readFileSync(join(HERE, 'catalogue', 'raw', f), 'utf8')).entries) uploads.add(e.id);
}
const OUT = join(HERE, 'registry', 'playlist_entries.json');
const res = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
for (const [slug, c] of Object.entries(PL)) {
  for (const pid of c.strategy_like || []) {
    if (res[pid] && !res[pid].error) continue;
    const meta = c.playlists.find(p => p.id === pid) || {};
    try {
      const j = JSON.parse(await run(['--ignore-config', '--flat-playlist', '--dump-single-json', '--playlist-end', '300',
        '--socket-timeout', '20', 'https://www.youtube.com/playlist?list=' + pid]));
      const vids = (j.entries || []).map(e => ({ id: e.id, title: e.title, channel: e.channel || e.uploader || null }));
      const outside = vids.filter(v => !uploads.has(v.id));
      res[pid] = { channel: slug, title: meta.title, n: vids.length, not_in_uploads: outside };
      console.log(slug.padEnd(22), (meta.title || '').slice(0, 50).padEnd(52), vids.length, 'videos,', outside.length, 'outside uploads');
    } catch (e) {
      res[pid] = { channel: slug, title: meta.title, error: String(e.message).slice(0, 200) };
      console.log(slug, pid, 'ERROR', String(e.message).slice(0, 120));
      if (/429|Too Many|Sign in to confirm/i.test(e.message)) { writeFileSync(OUT, JSON.stringify(res, null, 1)); console.log('slow down: stopping'); process.exit(0); }
    }
    writeFileSync(OUT, JSON.stringify(res, null, 1));
    await sleep(15000);
  }
}
writeFileSync(OUT, JSON.stringify(res, null, 1));
