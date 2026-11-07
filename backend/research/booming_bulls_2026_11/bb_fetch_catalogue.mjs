// Phase 1, step 1: list every public upload on the official Booming Bulls channel with yt-dlp
// (Videos, Shorts and Live tabs, plus every public playlist) and save the raw listings.
// Writes data/catalogue/raw/*.json (not in git). Needs yt-dlp on PATH.
// Usage: node bb_fetch_catalogue.mjs
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const RAW = join(HERE, 'data', 'catalogue', 'raw');
export const CHANNEL_ID = 'UC2sIhf108S02F0Qlb2a88eQ';
const CHANNEL = 'https://www.youtube.com/channel/' + CHANNEL_ID;

async function ytJson(args, timeout = 900_000) {
  try {
    const { stdout, stderr } = await run('yt-dlp', ['--ignore-config', ...args],
      { maxBuffer: 1024 * 1024 * 1024, timeout, windowsHide: true });
    const warnings = stderr.split(/\r?\n/).filter(line => /WARNING|ERROR/.test(line));
    return { json: JSON.parse(stdout), warnings };
  } catch (error) {
    return { json: null, warnings: [String(error.stderr || error.message).trim().split(/\r?\n/).slice(-3).join(' ')] };
  }
}

await mkdir(RAW, { recursive: true });
const fetchedAt = new Date().toISOString();
const log = { fetchedAt, channel: CHANNEL, tabs: {}, playlists: [] };

for (const tab of ['videos', 'shorts', 'streams']) {
  const { json, warnings } = await ytJson(['--flat-playlist', '-J', '--extractor-args', 'youtubetab:approximate_date', CHANNEL + '/' + tab]);
  const entries = json?.entries ?? [];
  await writeFile(join(RAW, `tab_${tab}.json`), JSON.stringify(json));
  log.tabs[tab] = { count: entries.length, warnings };
  console.log(`${tab}: ${entries.length} entries${warnings.length ? ' | ' + warnings.join(' | ') : ''}`);
  if (tab === 'videos' && json) {
    log.channelMeta = {
      channel: json.channel, channel_id: json.channel_id, uploader_id: json.uploader_id,
      channel_url: json.channel_url, channel_follower_count: json.channel_follower_count,
      title: json.title,
    };
  }
}

const { json: plist, warnings: pw } = await ytJson(['--flat-playlist', '-J', CHANNEL + '/playlists']);
const playlists = plist?.entries ?? [];
console.log(`playlists: ${playlists.length}${pw.length ? ' | ' + pw.join(' | ') : ''}`);
for (const p of playlists) {
  const { json, warnings } = await ytJson(['--flat-playlist', '-J', 'https://www.youtube.com/playlist?list=' + p.id]);
  const n = json?.entries?.length ?? 0;
  await writeFile(join(RAW, `playlist_${p.id}.json`), JSON.stringify(json));
  log.playlists.push({ id: p.id, title: p.title, count: n, warnings });
  console.log(`  playlist ${p.id}: ${n} | ${p.title}${warnings.length ? ' | ' + warnings.join(' | ') : ''}`);
}
await writeFile(join(RAW, 'fetch_log.json'), JSON.stringify(log, null, 2));
console.log('channel:', JSON.stringify(log.channelMeta));
