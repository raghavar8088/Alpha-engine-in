// Reading lists for the selected channels: copies each channel's Trading Video Lab list into catalogue/raw/<id>.json and
// writes catalogue/review/<slug>.txt with every non-Short upload (title, date, minutes, views, the app's priority and
// families), strategy titles first, so the videos to analyse can be chosen by reading titles and descriptions.
//   node dump_review.mjs <channelId> [<channelId> ...]
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { classify, dedupe } = await import('file:///' + APP + '/lib/channels.mjs');
const OUT = join(HERE, 'catalogue');
mkdirSync(join(OUT, 'raw'), { recursive: true });
mkdirSync(join(OUT, 'review'), { recursive: true });
const mins = s => s == null ? '?' : (s / 60).toFixed(0);
const views = v => v == null ? '?' : v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? Math.round(v / 1e3) + 'k' : String(v);
const slug = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 40) || 'channel';
for (const id of process.argv.slice(2)) {
  const f = join(APP, 'data', 'channels', id + '.json');
  if (!existsSync(f)) { console.log(id, 'NOT LISTED'); continue; }
  const c = JSON.parse(readFileSync(f, 'utf8'));
  for (const e of c.entries) Object.assign(e, classify(e.title), { dup_of: undefined });
  dedupe(c.entries, c.channel.title);
  writeFileSync(join(OUT, 'raw', id + '.json'), JSON.stringify(c, null, 1));
  const rows = c.entries.filter(e => !e.dup_of && e.kind !== 'short');
  const rank = { P1: 0, P2: 1, P3: 2, '-': 3 };
  rows.sort((a, b) => rank[a.priority] - rank[b.priority] || (b.views || 0) - (a.views || 0));
  const lines = [`# ${c.channel.title} ${c.channel.handle || ''} (${id}) listed ${c.fetched_at || ''}`,
    `# rows ${rows.length}; idx id date kind minutes views priority families | title`];
  rows.forEach((e, i) => lines.push([String(i).padStart(4), e.id, e.published || '----------', (e.kind || 'v')[0], mins(e.duration).padStart(4),
    views(e.views).padStart(5), e.priority.padEnd(2), (e.families || []).slice(0, 3).join(',').padEnd(40), '|', e.title].join(' ')));
  const name = slug(c.channel.handle?.replace('@', '') || c.channel.title);
  writeFileSync(join(OUT, 'review', name + '.txt'), lines.join('\n') + '\n');
  console.log(name.padEnd(30), rows.length, 'rows,', rows.filter(e => e.priority === 'P1').length, 'P1');
}
