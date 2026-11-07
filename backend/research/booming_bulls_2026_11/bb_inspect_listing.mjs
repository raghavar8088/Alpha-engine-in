// Phase 1 helper: summarise the raw channel listings (fields present, dates, durations)
// and write a compact one-line-per-upload text file for reading the titles.
// Usage: node bb_inspect_listing.mjs
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const RAW = join(HERE, 'data', 'catalogue', 'raw');
const fmtDur = s => s == null ? '?' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// Flat listings carry only an approximate timestamp ("3 years ago"), so these dates are approximate.
const approxDate = e => e.upload_date || (e.timestamp ? new Date(e.timestamp * 1000).toISOString().slice(0, 10) : '');

for (const tab of ['videos', 'shorts', 'streams']) {
  const json = JSON.parse(await readFile(join(RAW, `tab_${tab}.json`), 'utf8'));
  const entries = json.entries;
  const fields = {};
  for (const e of entries) for (const [k, v] of Object.entries(e)) if (v != null && v !== '') fields[k] = (fields[k] || 0) + 1;
  console.log(`\n== ${tab}: ${entries.length} entries; fields present (count): ` +
    Object.entries(fields).map(([k, n]) => `${k}=${n}`).join(', '));
  const years = {};
  for (const e of entries) { const y = (approxDate(e) || '????').slice(0, 4); years[y] = (years[y] || 0) + 1; }
  console.log('approx upload year:', JSON.stringify(Object.fromEntries(Object.entries(years).sort())));
  const durs = entries.map(e => e.duration).filter(d => d != null).sort((a, b) => a - b);
  if (durs.length) {
    const q = p => fmtDur(durs[Math.floor(p * (durs.length - 1))]);
    console.log(`duration min ${q(0)} p25 ${q(0.25)} median ${q(0.5)} p75 ${q(0.75)} max ${q(1)}; total hours ${(durs.reduce((a, b) => a + b, 0) / 3600).toFixed(0)}`);
  }
  const withDesc = entries.filter(e => e.description).length;
  console.log('entries with a description snippet:', withDesc);
  const lines = entries.map(e => [e.id, approxDate(e).slice(0, 7), fmtDur(e.duration), (e.title || '').replace(/\s+/g, ' ')].join(' | '));
  await writeFile(join(RAW, `titles_${tab}.txt`), lines.join('\n') + '\n');
}
