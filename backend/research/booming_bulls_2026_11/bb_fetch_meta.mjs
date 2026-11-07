// Phase 1, step 2: full metadata (exact upload date, language, caption tracks, chapters,
// description) for every hand-labelled upload. Writes data/catalogue/meta/<id>.json (compact)
// and data/catalogue/meta/_failures.json. Skips ids already fetched. Needs yt-dlp on PATH.
// Usage: node bb_fetch_meta.mjs [concurrency=4]
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LABELS } from './bb_labels.mjs';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const META = join(HERE, 'data', 'catalogue', 'meta');
const concurrency = Number(process.argv[2]) || 4;
await mkdir(META, { recursive: true });

const exists = p => access(p).then(() => true, () => false);
const compact = j => ({
  id: j.id, title: j.title, upload_date: j.upload_date, duration: j.duration, language: j.language ?? null,
  channel: j.channel, channel_id: j.channel_id, uploader_id: j.uploader_id,
  channel_is_verified: j.channel_is_verified ?? null, channel_follower_count: j.channel_follower_count ?? null,
  view_count: j.view_count, like_count: j.like_count ?? null, availability: j.availability ?? null,
  live_status: j.live_status ?? null, media_type: j.media_type ?? null,
  chapters: (j.chapters || []).map(c => ({ start: c.start_time, title: c.title })),
  manual_subs: Object.keys(j.subtitles || {}).filter(k => k !== 'live_chat'),
  auto_orig: Object.keys(j.automatic_captions || {}).filter(k => k.endsWith('-orig')),
  auto_count: Object.keys(j.automatic_captions || {}).length,
  audio_languages: [...new Set((j.formats || []).filter(f => f.vcodec === 'none' && f.language).map(f => f.language))],
  tags: (j.tags || []).slice(0, 30),
  description: (j.description || '').slice(0, 4000),
});

const ids = [...new Set(LABELS.map(l => l[0]))];
const todo = [];
for (const id of ids) if (!(await exists(join(META, id + '.json')))) todo.push(id);
console.log(`labelled ids: ${ids.length}; to fetch: ${todo.length}`);

const failures = {};
let done = 0;
async function fetchOne(id) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const { stdout } = await run('yt-dlp', ['--ignore-config', '--no-warnings', '--skip-download', '--no-playlist', '-J', '--',
        'https://www.youtube.com/watch?v=' + id], { maxBuffer: 256 * 1024 * 1024, timeout: 180_000, windowsHide: true });
      await writeFile(join(META, id + '.json'), JSON.stringify(compact(JSON.parse(stdout))));
      delete failures[id];
      return;
    } catch (error) {
      failures[id] = String(error.stderr || error.message).trim().split(/\r?\n/).filter(Boolean).slice(-2).join(' ').slice(0, 300);
    }
  }
}
const queue = [...todo];
await Promise.all(Array.from({ length: concurrency }, async () => {
  while (queue.length) {
    const id = queue.shift();
    await fetchOne(id);
    if (++done % 20 === 0) console.log(`  ${done}/${todo.length}`);
  }
}));
let previous = {};
try { previous = JSON.parse(await readFile(join(META, '_failures.json'), 'utf8')); } catch {}
for (const id of Object.keys(previous)) if (await exists(join(META, id + '.json'))) delete previous[id];
const allFailures = { ...previous, ...failures };
await writeFile(join(META, '_failures.json'), JSON.stringify(allFailures, null, 2));
console.log(`done: ${todo.length - Object.keys(failures).length} fetched, ${Object.keys(failures).length} failed`);
for (const [id, why] of Object.entries(failures)) console.log(`  FAILED ${id}: ${why}`);
