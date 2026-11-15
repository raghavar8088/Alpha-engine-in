// The YouTube channels index for the Premium Strategies "YouTube channels" tab: every channel whose videos the research
// studies analysed, each analysed video (title, date, link, study, the strategies it gave) and the channel's other
// uploads that were not analysed, grouped by why not.
//
// Analysed videos come from the studies' own published data (frontend/app/premium-strategies): the channel shortlist
// (shortlistData.ts), the 20-channel study (channels20Data.ts), the four intraday topics (intraday4Data.ts) and the
// strategy library (library.ts: Booming Bulls, the top-20 traders, the 11 channels, the crypto playlist and others).
// Titles, channels and dates come from the Trading Video Lab's saved evidence; each channel's full upload list and the
// title classes come from the Lab's channel catalogues (yt-dlp listings, titles only), so the reasons for videos not
// analysed are read from titles, the way the studies chose what to read. Nothing here is fetched from the network.
//
//   node build_channel_index.mjs        -> frontend/app/premium-strategies/ytChannelsData.ts
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..', '..');
const FRONT = join(ROOT, 'frontend', 'app', 'premium-strategies');
const OUT = join(FRONT, 'ytChannelsData.ts');
const APP = join(ROOT, 'youtube-video-explainer-reviewed');
const { evidenceFor } = await import('file:///' + join(APP, 'lib', 'evidence.mjs').replace(/\\/g, '/'));
const { dedupe } = await import('file:///' + join(APP, 'lib', 'channels.mjs').replace(/\\/g, '/'));

const ID = /^[A-Za-z0-9_-]{11}$/;
const P1_LIST = 40, EXAMPLES = 3, TITLE = 110;
const clip = (s, n = TITLE) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

export const STUDIES = {
  shortlist: 'Channel shortlist study', channels20: '20-channel study', intraday4: 'Intraday 4 topics study',
  booming_bulls: 'Booming Bulls study', youtube_top20: 'Top-20 traders study', youtube_channels11: '11-channel study',
  crypto_playlist: 'Crypto playlist study', liquidity_sweep: 'Liquidity sweep study', sniper_headshot: 'Sniper headshot study',
};
export const REASONS = {
  waiting: 'Picked for a study but not read yet: most have no captions, and transcribing needs Whisper (your OK to download the audio)',
  strategy_not_picked: 'Its title names a strategy, but it was not picked: each study read the clearest strategy titles first, a few per channel',
  setup: 'About a setup, indicator or market, not clearly a complete strategy (judged from the title)',
  calls: 'Market calls, live trading or recaps (judged from the title)',
  stream: 'A live stream (live trading or market commentary)',
  off_topic: 'Not about trading rules (judged from the title)',
  short: 'A YouTube Short: too short to teach complete rules',
  reupload: 'A re-upload of another video on this channel',
};

/** The JSON literals of a generated TypeScript data file, by export name ("export const X: T = [...];"). */
function tsExports(text) {
  const out = {};
  const head = /export\s+const\s+(\w+)\s*(?::[^=;]+)?=\s*/g;
  let m;
  while ((m = head.exec(text))) {
    const start = m.index + m[0].length;
    if (text[start] !== '[' && text[start] !== '{') continue;
    let depth = 0, inString = false, escaped = false, end = start;
    for (; end < text.length; end++) {
      const ch = text[end];
      if (inString) { if (escaped) escaped = false; else if (ch === '\\') escaped = true; else if (ch === '"') inString = false; continue; }
      if (ch === '"') inString = true;
      else if (ch === '[' || ch === '{') depth++;
      else if ((ch === ']' || ch === '}') && --depth === 0) break;
    }
    try { out[m[1]] = JSON.parse(text.slice(start, end + 1)); } catch { /* an expression, not data */ }
    head.lastIndex = end + 1;
  }
  return out;
}
const data = file => tsExports(readFileSync(join(FRONT, file), 'utf8'));

// --- 1. analysed videos, from the studies' own data ---------------------------------------------------------
const analysed = new Map();          // video -> { studies:Set, strategies: Map(id -> status) }
const touch = (video, study, id, status, channel = '') => {
  if (!ID.test(String(video || ''))) return;
  if (!analysed.has(video)) analysed.set(video, { studies: new Set(), strategies: new Map(), names: new Set() });
  const a = analysed.get(video);
  a.studies.add(study);
  if (channel) a.names.add(String(channel));
  if (id) a.strategies.set(id, status || a.strategies.get(id) || 'analysed');
};
const waiting = new Map();           // picked but not read: video -> { study, channel (the study's channel name) }
const channelSkip = new Map();       // channel id or name -> reason (studies that looked at a channel and passed)

const sl = data('shortlistData.ts');
for (const s of sl.SL || []) touch(s.video, 'shortlist', s.id, s.status, s.channel);
for (const c of sl.SL_CHANNELS || []) {
  for (const p of c.picked || []) { if (p.analysed) touch(p.video, 'shortlist', p.id || null, null); else if (ID.test(p.video)) waiting.set(p.video, { study: 'shortlist', channel: c.name }); }
  if (c.skip) channelSkip.set('name:' + c.name.toLowerCase(), c.skip);
}
const c20 = data('channels20Data.ts');
for (const s of c20.CH20 || []) for (const v of s.videos || []) touch(v, 'channels20', s.id, 'coded', s.channel);
for (const s of c20.CH20_BLOCKED || []) for (const v of s.videos || []) touch(v, 'channels20', s.id, 'blocked', s.channel);
for (const s of c20.CH20_DUPLICATES || []) touch(s.video, 'channels20', String(s.what || '').match(/\(([A-Z]{1,4}-\d+)\)/)?.[1] || null, 'duplicate', s.channel);
for (const s of c20.CH20_SKIPPED || []) if (s.id) channelSkip.set(s.id, s.reason);
const i4 = data('intraday4Data.ts');
for (const s of i4.I4 || []) touch(s.video, 'intraday4', s.id, s.status, s.channel);
const lib = data('library.ts');
for (const s of lib.LIBRARY || []) for (const v of s.videos || []) touch(v, STUDIES[s.source] ? s.source : 'youtube_top20', s.id, 'coded', s.channel);
for (const v of analysed.keys()) waiting.delete(v);

// --- 2. titles, channels and dates from the Lab's evidence --------------------------------------------------
const meta = new Map();
const fetchState = new Map();        // video -> 'none' (never fetched) | 'unfinished' (evidence folder without a manifest)
for (const video of [...analysed.keys(), ...waiting.keys()]) {
  const e = await evidenceFor(video);
  if (!e) { fetchState.set(video, 'none'); continue; }
  let man = null;
  try { man = JSON.parse(readFileSync(join(e.folder, 'manifest.json'), 'utf8')); } catch { /* unreadable */ }
  if (!man) { fetchState.set(video, 'unfinished'); continue; }
  const m = man.meta || {};
  meta.set(video, { title: m.title || man.title || '', channel: m.channel || man.channel || '', channel_id: m.channel_id || man.channel_id || null,
    date: m.upload_date || m.published_at?.slice(0, 10) || null, minutes: Math.round((man.duration || m.duration || 0) / 60) || null,
    words: Number(man.transcript?.clean_words) || 0 });
}
// A picked video not read yet: no captions (it needs Whisper), or captions saved and waiting for its turn.
const waitNote = v => (meta.get(v)?.words || 0) > 50 ? 'captions saved; not read yet'
  : fetchState.get(v) === 'unfinished' ? 'caption fetch did not finish' : fetchState.get(v) === 'none' ? 'not fetched yet' : 'no captions';

// --- 3. channels, with their catalogues ----------------------------------------------------------------------
const CAT_DIR = join(APP, 'data', 'channels');
const catalogues = new Map();
for (const f of existsSync(CAT_DIR) ? readdirSync(CAT_DIR).filter(n => n.endsWith('.json')) : []) {
  try { const j = JSON.parse(readFileSync(join(CAT_DIR, f), 'utf8')); if (j?.channel?.id) catalogues.set(j.channel.id, j); } catch { /* skip */ }
}
const channels = new Map();          // key -> channel
const keyOf = m => m.channel_id || 'name:' + m.channel.toLowerCase();
// Older evidence (manifest v1) has no channel: take the study's own channel name, and the channel's id from another
// analysed video of the same name or from a catalogue with that title.
const norm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '');
// Study labels like "Booming Bulls (Crypto Trading playlist)" or "A; B": try the name, then without the note, then the first.
const tryNames = name => [name, name.replace(/\s*\([^)]*\)\s*/g, ' '), name.split(/[;/]| and /)[0]];
const idByName = new Map();
for (const m of meta.values()) if (m.channel && m.channel_id && !idByName.has(norm(m.channel))) idByName.set(norm(m.channel), m.channel_id);
for (const [id, cat] of catalogues) if (!idByName.has(norm(cat.channel.title))) idByName.set(norm(cat.channel.title), id);
const nameById = new Map([...catalogues].map(([id, cat]) => [id, cat.channel.title]));
for (const m of meta.values()) if (m.channel && m.channel_id && !nameById.has(m.channel_id)) nameById.set(m.channel_id, m.channel);
for (const [video, a] of analysed) {
  const m = { ...(meta.get(video) || { title: '', channel: '', channel_id: null, date: null, minutes: null }) };
  if (!m.channel_id) {
    const name = m.channel || [...a.names][0] || '';
    m.channel_id = tryNames(name).map(n => idByName.get(norm(n))).find(Boolean) || null;
    m.channel = (m.channel_id && nameById.get(m.channel_id)) || name || '(unknown channel)';
  }
  if (!m.channel) m.channel = nameById.get(m.channel_id) || '(unknown channel)';
  meta.set(video, m);
  const key = keyOf(m);
  if (!channels.has(key)) channels.set(key, { id: m.channel_id, name: m.channel || '(unknown channel)', videos: [], studies: new Set() });
  const ch = channels.get(key);
  for (const s of a.studies) ch.studies.add(s);
  ch.videos.push({ v: video, t: clip(m.title), d: m.date, m: m.minutes, s: [...a.studies], x: [...a.strategies].map(([id, st]) => ({ id, st })) });
}
// Picked videos not read yet: those without a Lab manifest take their channel from the study's own record, and the
// title and date from that channel's upload list.
for (const [video, w] of waiting) {
  const m = { ...(meta.get(video) || { title: '', channel: '', channel_id: null, date: null, minutes: null, words: 0 }) };
  if (!m.channel_id) {
    const name = m.channel || w.channel || '';
    m.channel_id = tryNames(name).map(n => idByName.get(norm(n))).find(Boolean) || null;
    m.channel = (m.channel_id && nameById.get(m.channel_id)) || name || '(unknown channel)';
  }
  const e = m.channel_id ? catalogues.get(m.channel_id)?.entries.find(x => x.id === video) : null;
  if (e) { m.title = m.title || e.title || ''; m.date = m.date || e.published?.slice(0, 10) || null; m.views = e.views ?? null; }
  meta.set(video, m);
}

// A strategy built from several videos counts once (ids are unique across channels); a record without an id counts per video.
const distinctStrategies = videos => {
  const seen = { coded: new Set(), blocked: new Set(), duplicate: new Set() };
  for (const v of videos) for (const x of v.x) seen[x.st]?.add(x.id || v.v);
  return { coded: seen.coded.size, blocked: seen.blocked.size, duplicate: seen.duplicate.size };
};
const reasonOf = (e, picked) => picked ? 'waiting' : e.dup_of ? 'reupload' : e.kind === 'short' ? 'short' : e.priority === 'P1' ? 'strategy_not_picked'
  : e.kind === 'stream' ? 'stream' : e.priority === 'P2' ? 'setup' : e.priority === 'P3' ? 'calls' : 'off_topic';
const ORDER = Object.keys(REASONS);
const totals = Object.fromEntries(ORDER.map(r => [r, 0]));
const placed = new Set();            // waiting videos already shown under an analysed channel
const out = [];
for (const ch of channels.values()) {
  const cat = ch.id ? catalogues.get(ch.id) : null;
  const not = [];
  if (cat) {
    const done = new Set(ch.videos.map(v => v.v));
    const entries = dedupe(cat.entries.map(e => ({ ...e })), cat.channel.title);
    const groups = new Map();
    for (const e of entries) {
      if (done.has(e.id)) continue;
      const r = reasonOf(e, waiting.has(e.id));
      if (!groups.has(r)) groups.set(r, []);
      groups.get(r).push(e);
    }
    for (const r of ORDER) {
      const list = groups.get(r);
      if (!list?.length) continue;
      totals[r] += list.length;
      list.sort((a, b) => (b.views || 0) - (a.views || 0));
      const keep = r === 'waiting' ? list.length : r === 'strategy_not_picked' ? P1_LIST : EXAMPLES;
      not.push({ r, n: list.length, list: list.slice(0, keep).map(e => ({ v: e.id, t: clip(e.title), d: e.published || null, w: e.views ?? null,
        ...(r === 'waiting' ? { q: waitNote(e.id) } : {}) })) });
    }
  }
  // Picked videos not read that the catalogue does not list (or with no catalogue) still show.
  const shown = new Set(not.flatMap(g => g.list.map(x => x.v)));
  const extra = [...waiting.keys()].filter(v => !shown.has(v) && meta.get(v) && keyOf(meta.get(v)) === (ch.id || 'name:' + ch.name.toLowerCase()));
  if (extra.length) {
    const g = not.find(x => x.r === 'waiting') || (not.unshift({ r: 'waiting', n: 0, list: [] }), not[0]);
    for (const v of extra) { g.list.push({ v, t: clip(meta.get(v).title), d: meta.get(v).date, w: meta.get(v).views ?? null, q: waitNote(v) }); g.n++; totals.waiting++; }
  }
  for (const g of not) if (g.r === 'waiting') for (const x of g.list) placed.add(x.v);
  ch.videos.sort((a, b) => String(b.d || '').localeCompare(String(a.d || '')));
  const counts = distinctStrategies(ch.videos);
  out.push({ id: ch.id, name: ch.name, handle: cat?.channel?.handle || null, uploads: cat ? cat.entries.length : null, listed: cat?.fetched_at?.slice(0, 10) || null,
    studies: [...ch.studies], counts, analysed: ch.videos, not });
}
out.sort((a, b) => (b.analysed.length - a.analysed.length) || a.name.localeCompare(b.name));

// --- 4. channels the studies listed but analysed nothing from ----------------------------------------------
const analysedIds = new Set(out.map(c => c.id).filter(Boolean));
const analysedNames = new Set(out.map(c => c.name.toLowerCase()));
const waitingBy = new Map();         // channel key -> waiting videos not shown under an analysed channel
for (const v of waiting.keys()) {
  if (placed.has(v)) continue;
  const m = meta.get(v);
  const key = m ? keyOf(m) : 'name:(unknown channel)';
  if (!waitingBy.has(key)) waitingBy.set(key, { name: m?.channel || '(unknown channel)', id: m?.channel_id || null, list: [] });
  waitingBy.get(key).list.push({ v, t: clip(m?.title || '(title not saved)'), d: m?.date || null, w: m?.views ?? null, q: waitNote(v) });
  totals.waiting++;
}
const waitingReason = list => 'Picked ' + list.length + ' video' + (list.length === 1 ? '' : 's') + ' for a study, not read yet ('
  + [...new Set(list.map(x => x.q))].join('; ') + '): ' + (list.some(x => x.q === 'no captions') ? 'transcribing needs Whisper, which needs your OK to download the audio'
    : list.some(x => x.q !== 'captions saved; not read yet') ? 'its captions have to be fetched again' : 'waiting for its turn');
const unanalysed = [];
for (const [id, cat] of catalogues) {
  if (analysedIds.has(id) || analysedNames.has(String(cat.channel.title || '').toLowerCase())) continue;
  const e = cat.entries;
  const p1 = e.filter(x => x.priority === 'P1').length;
  const wait = waitingBy.get(id)?.list || [];
  waitingBy.delete(id);
  const reason = wait.length ? waitingReason(wait) : channelSkip.get(id) || channelSkip.get('name:' + String(cat.channel.title || '').toLowerCase())
    || (p1 ? 'Listed and classified; none of its ' + p1 + ' strategy titles has been picked yet' : 'No upload title names a strategy');
  unanalysed.push({ id, name: cat.channel.title || id, handle: cat.channel.handle || null, uploads: e.length, strategy_titles: p1, reason, waiting: wait });
}
for (const [key, w] of waitingBy) unanalysed.push({ id: w.id || key, name: w.name, handle: null, uploads: null, strategy_titles: 0, reason: waitingReason(w.list), waiting: w.list });
unanalysed.sort((a, b) => b.waiting.length - a.waiting.length || b.strategy_titles - a.strategy_titles || a.name.localeCompare(b.name));

const metaOut = {
  channels: out.length, videos: out.reduce((n, c) => n + c.analysed.length, 0), with_uploads_listed: out.filter(c => c.uploads !== null).length,
  uploads: out.reduce((n, c) => n + (c.uploads || 0), 0), not_analysed: totals, listed_not_analysed: unanalysed.length,
  ...(({ coded, blocked, duplicate }) => ({ strategies: coded, no_rule: blocked, repeats: duplicate }))(distinctStrategies(out.flatMap(c => c.analysed))),
  built: new Date().toISOString().slice(0, 10),
};
const head = '// GENERATED by backend/research/youtube_channel_index/build_channel_index.mjs - do not edit by hand.\n'
  + '// Every YouTube channel the research studies analysed: its analysed videos (title, upload date, minutes, study, the\n'
  + '// strategies it gave) and its other uploads not analysed, grouped by reason (read from titles, as the studies chose).\n\n'
  + 'export type YtVideo = { v: string; t: string; d: string | null; m: number | null; s: string[]; x: { id: string | null; st: string }[] };\n'
  + 'export type YtUpload = { v: string; t: string; d: string | null; w: number | null; q?: string };\n'
  + 'export type YtNot = { r: string; n: number; list: YtUpload[] };\n'
  + 'export type YtChannel = { id: string | null; name: string; handle: string | null; uploads: number | null; listed: string | null; studies: string[];\n'
  + '  counts: { coded: number; blocked: number; duplicate: number }; analysed: YtVideo[]; not: YtNot[] };\n'
  + 'export type YtListedChannel = { id: string; name: string; handle: string | null; uploads: number | null; strategy_titles: number; reason: string;\n'
  + '  waiting: YtUpload[] };\n\n';
const body = 'export const YT_META = ' + JSON.stringify(metaOut) + ';\n\n'
  + 'export const YT_STUDIES: Record<string, string> = ' + JSON.stringify(STUDIES, null, 1) + ';\n\n'
  + 'export const YT_REASONS: Record<string, string> = ' + JSON.stringify(REASONS, null, 1) + ';\n\n'
  + 'export const YT_CHANNELS: YtChannel[] = ' + JSON.stringify(out) + ';\n\n'
  + 'export const YT_LISTED_NOT_ANALYSED: YtListedChannel[] = ' + JSON.stringify(unanalysed) + ';\n';
writeFileSync(OUT, head + body);
console.log('wrote', OUT, Math.round((head + body).length / 1024) + ' KB', JSON.stringify(metaOut));
const noMeta = [...analysed.keys()].filter(v => !meta.has(v));
if (noMeta.length) console.log('analysed videos without Lab evidence (titles unknown):', noMeta.length);
