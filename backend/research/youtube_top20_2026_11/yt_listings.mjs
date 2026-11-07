// Phase 1b: full long-form upload lists for the candidate channels, and the content screen used to decide
// whether a channel is a trading-strategy channel: of its 50 most-viewed videos, how many titles are about
// trading (strategies, technical analysis, intraday, options trading, forex...) vs investing / personal finance /
// business. Output: data/listings/<channel_id>.json and data/screen.json.
// Usage: node yt_listings.mjs [minFollowers=900000]
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = join(HERE, 'data');
const LIST = join(DATA, 'listings');
const YT = ['--ignore-config', '--no-warnings', '--socket-timeout', '20', '--retries', '3'];
const minFollowers = Number(process.argv[2] || 900000);

import { TRADING, INVESTING } from './yt_listings_rules.mjs';

async function exists(p) { try { await access(p); return true; } catch { return false; } }

const cands = [
  ...JSON.parse(await readFile(join(DATA, 'candidates.json'), 'utf8')).candidates,
  ...JSON.parse(await readFile(join(DATA, 'candidates2.json'), 'utf8')).candidates,
].filter(c => c.channel_id && (c.followers || 0) >= minFollowers);
await mkdir(LIST, { recursive: true });
const screen = [];
for (const c of cands) {
  const path = join(LIST, `${c.channel_id}.json`);
  let entries;
  if (await exists(path)) entries = JSON.parse(await readFile(path, 'utf8')).entries;
  else {
    try {
      const { stdout } = await run('yt-dlp', [...YT, '--flat-playlist', '-J', `https://www.youtube.com/channel/${c.channel_id}/videos`],
        { maxBuffer: 512 * 1024 * 1024, timeout: 900000, windowsHide: true });
      const j = JSON.parse(stdout);
      entries = (j.entries || []).map(e => ({ id: e.id, title: e.title, duration: e.duration ?? null, views: e.view_count ?? null }));
      await writeFile(path, JSON.stringify({ channel_id: c.channel_id, channel: c.channel, fetchedAt: new Date().toISOString(), entries }));
    } catch (e) {
      console.log(`${c.name}: listing FAILED ${String(e.message).slice(0, 120)}`);
      continue;
    }
  }
  const top = entries.filter(e => e.views != null).sort((a, b) => b.views - a.views).slice(0, 50);
  const tr = top.filter(e => TRADING.test(e.title)).length;
  const inv = top.filter(e => INVESTING.test(e.title) && !TRADING.test(e.title)).length;
  const row = { name: c.name, channel: c.channel, channel_id: c.channel_id, handle: c.handle, region: c.region, followers: c.followers,
                videos: entries.length, top50_trading: tr, top50_investing_only: inv, top10: top.slice(0, 10).map(e => `${e.views} | ${e.title}`) };
  screen.push(row);
  console.log(`${c.name.padEnd(26)} ${String(c.followers).padStart(9)} videos ${String(entries.length).padStart(5)} | top-50 trading ${String(tr).padStart(2)} investing-only ${String(inv).padStart(2)}`);
}
await writeFile(join(DATA, 'screen.json'), JSON.stringify(screen, null, 1));
