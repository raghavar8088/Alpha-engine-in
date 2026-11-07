// Phase 1 deliverable: build the searchable catalogue of every public Booming Bulls upload.
// Inputs: data/catalogue/raw/tab_*.json (bb_fetch_catalogue.mjs), bb_labels.mjs (hand labels),
// data/catalogue/meta/*.json (bb_fetch_meta.mjs), data/transcripts/_index.json (bb_extract_batch.mjs),
// analyses/*.md (Phase 2 analyses). Outputs catalogue/catalogue.csv, catalogue/catalogue.json and
// catalogue/CATALOGUE.md (tracked in git; holds titles, links and labels only, no transcripts).
// Usage: node bb_build_catalogue.mjs
import { readFile, writeFile, readdir, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LABELS, FAMILIES } from './bb_labels.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const RAW = join(HERE, 'data', 'catalogue', 'raw');
const META = join(HERE, 'data', 'catalogue', 'meta');
const OUT = join(HERE, 'catalogue');
const ANALYSES = join(HERE, 'analyses');
await mkdir(OUT, { recursive: true });

const readJson = async (p, d = null) => { try { return JSON.parse(await readFile(p, 'utf8')); } catch { return d; } };
const label = new Map(LABELS.map(([id, family, market, priority, note]) => [id, { family, market, priority, note }]));
const transcripts = await readJson(join(HERE, 'data', 'transcripts', '_index.json'), {});
const failures = await readJson(join(META, '_failures.json'), {});
// How each analysis file treats a video id. Combined files (batch_*, shorts_*) cover many videos.
//   analysed:  the id is in the file name, a heading line, a bold label (**id**, **id:**, **id + ...), or a watch link
//   duplicate: the id is on a line that calls it a duplicate (its content was checked against the original)
//   referenced: any other mention (an earlier version, a cross-reference), which is not an analysis
const ID = '[A-Za-z0-9_-]{11}';
const analysedIn = new Map(), duplicateIn = new Map(), referencedIn = new Map();
const note = (map, id, f) => { const s = map.get(id) || []; if (!s.includes(f)) s.push(f); map.set(id, s); };
try {
  for (const f of (await readdir(ANALYSES)).filter(f => f.endsWith('.md'))) {
    const text = await readFile(join(ANALYSES, f), 'utf8');
    for (const m of f.matchAll(new RegExp(ID, 'g'))) note(analysedIn, m[0], f);
    for (const line of text.split('\n')) {
      const strong = new Set();
      if (/^#+\s/.test(line)) for (const m of line.matchAll(new RegExp(`(?<![A-Za-z0-9_-])(${ID})(?![A-Za-z0-9_-])`, 'g'))) strong.add(m[1]);
      for (const m of line.matchAll(new RegExp(`\\*\\*(${ID})(?=\\*\\*|:\\*\\*| \\+|,)`, 'g'))) strong.add(m[1]);
      for (const m of line.matchAll(new RegExp(`(?:watch\\?v=|shorts/|youtu\\.be/)(${ID})`, 'g'))) strong.add(m[1]);
      for (const id of strong) note(analysedIn, id, f);
      for (const m of line.matchAll(new RegExp(`(?<![A-Za-z0-9_-])(${ID})(?![A-Za-z0-9_-])`, 'g'))) {
        if (strong.has(m[1])) continue;
        note(/duplicate/i.test(line) ? duplicateIn : referencedIn, m[1], f);
      }
    }
  }
} catch {}
const analysed = new Set(analysedIn.keys());

// Rule-based categories for unlabelled uploads, checked in this order.
const RULES = [
  ['trade_recap', /trade logic|pnl|p&l|profits? (&|and) loss|trading results|results for the week|my trades this week|trades this week|this week.?s (trades|best|market|top)|worked this week|trades of the week|setups? (of|this) (the )?week|top setups/i],
  ['commentary', /market analysis|analysis for|analysis \d|analysis \|\||forex analysis|crypto analysis|gold analysis|bitcoin analysis|prediction|next move|what next|what's next|post market|pre market|post - market|levels|news|crash|budget special|rbi|fed meeting|stocks in news|war |impact|technical analysis for tomorrow|nifty (bounces|tested|testing|towards|broke|showed|in a range|important|bullish|pullback|near|took|make or break|breakout\?|pre-budget|at 200)|bank ?nifty (at|is|near|in a|trap|retests|important|double|rejection|pinbar|sideways|volatile|choppy|-)|bulls|bears|reversal confirmed|v shape|sharp|market (trend|retests|volatile|opened|ready)|expiry( day)? (special|trade idea)|panic expiry|volatile expiry|choppy expiry|zeel|adani|gold (cracks|going|fell|all time|crash|entering|’s|'s)|is gold|weekly crypto|cardano|ethereum (merge|2\.0|trade update|can be)|what is happening/i],
  ['live_trading', /live trad|live trade|live profit|live example|lakhs? ?\+|lakh ?\+|crore|\$\d|profits?!|profit\b|expiry trading vlog|trader life/i],
  ['promo_lifestyle', /giveaway|birthday|house|vlog|trading floor|event|hybrid center|foundation|announcement|summit|tour|unbox|podcast|battle|exposed|charity|school|share the care|theme music|subscriber|day in (a|the) life|documentary|behind the scenes|bali|celebrat|course forever|ending my course|life mastery|goa|untold story|booming realm|properties|play button|conclave|happy new year|ice bath|blessed|students performance|student summit|neem karoli|my team|my subscriber|new business|coinbase champions|traders battle|life management|mind movie|visionboard|seminar|workshop|delhi|mumbai|ahmedabad|surat|meet|job opportunity/i],
  ['tools_brokers_prop', /broker|demat|zerodha|upstox|fyers|account|prop firm|funding|funded|tax|tradingview|trading view|sensibull|opstra|tickertape|\bapp\b|exness|delta exchange|coinbase|deposit|journal|tradezella|leverage|lot size|market genius|vauld|deto|instant funding|cms prime|screen (trading )?setup|trading setup of indian|how to use coinbase/i],
  ['psychology_mindset', /psycholog|mindset|meditation|habits?|mistakes?|motivat|life\b|success|rich|visuali|manifest|subconscious|luck|story of|story\b|rules successful|advice|truth|fail|discipline|patience|recover|losing streak|loss|greed|fear|emotion|millionaire|change your life|win while|routine|break loop|time travel|criticism|humble|struggle|lazy|carpenter|monk|deer|pot\b|donkey|buddha|doctor|joker|brothers|crow|stallone|frog|inequality|mentor|public speaking|flexing|maintaining success/i],
  ['education_basics', /what is|what are|how to start|basics|beginner|course|explained|guide|learn|tutorial|roadmap|q&a|qna|questions|faq|doubt|how to (invest|read|use|trade|select|identify|draw|manage|master|control|write|grow|recover|shift|backtest|calculate)|vs\.? |versus|introduction|nifty 50|india vix|option chain|option greeks|open interest|fii data|dow theory|case study|short selling|paper trading|singapore nifty|dollar index|spot trading|mutual funds|us stocks|metaverse|nft|bitcoin\?|cryptocurrenc|time ?frame|basic words|trading plan|algo trading|hedging|volatility/i],
];
// Strip the channel and presenter names first: nearly every title carries them ("bulls" is a commentary word).
const ruleCategory = title => {
  const t = title.replace(/booming ?bulls?|boomingbulls|boomingbull|anish (singh )?thakur|#\w+/gi, ' ');
  return (RULES.find(([, re]) => re.test(t)) || ['other'])[0];
};
const fmtDate = d => d && d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : '';

const rows = [];
for (const kind of ['videos', 'shorts', 'streams']) {
  const tab = await readJson(join(RAW, `tab_${kind}.json`), { entries: [] });
  for (const e of tab.entries) {
    const meta = await readJson(join(META, e.id + '.json'));
    const lab = label.get(e.id);
    const approx = e.timestamp ? new Date(e.timestamp * 1000).toISOString().slice(0, 7) : '';
    const tr = transcripts[e.id];
    const title = meta?.title || e.title || '';
    let category = lab ? (lab.priority === 'P1' ? 'strategy' : lab.priority === 'P2' ? 'concept' : 'applied_example')
      : kind === 'streams' ? 'live_stream' : ruleCategory(title);
    const status = analysed.has(e.id) ? 'analysed' : duplicateIn.has(e.id) ? 'duplicate_noted'
      : tr?.status === 'ok' ? 'transcript_ready'
      : tr?.status === 'no_captions' ? 'blocked_no_captions' : tr?.status === 'failed' ? 'extraction_failed'
      : failures[e.id] ? 'unavailable' : lab ? 'queued' : 'not_selected';
    rows.push({
      id: e.id, url: (kind === 'shorts' ? 'https://www.youtube.com/shorts/' : 'https://www.youtube.com/watch?v=') + e.id,
      kind: kind.replace(/s$/, ''), title,
      upload_date: fmtDate(meta?.upload_date) || approx, date_exact: !!meta?.upload_date,
      duration_s: meta?.duration ?? e.duration ?? '', language: meta?.language ?? '',
      caption_tracks: meta ? [...(meta.manual_subs || []).map(k => 'manual:' + k), ...(meta.auto_orig || [])].join(' ') : '',
      dubbed_audio: meta ? (meta.audio_languages || []).filter(l => l && !String(l).startsWith(meta.language || '~')).join(' ') : '',
      chapters: meta?.chapters?.length || 0,
      category, family: lab?.family || '', family_name: lab ? FAMILIES[lab.family] : '',
      market: lab?.market || '', priority: lab?.priority || 'X', relevance: lab?.note || '',
      analysis_status: status, views: meta?.view_count ?? e.view_count ?? '',
      transcript_words: tr?.words || '', caption_track_used: tr?.track || '',
      analysis_files: (analysedIn.get(e.id) || duplicateIn.get(e.id) || []).join(' '),
      referenced_in: (referencedIn.get(e.id) || []).filter(f => !(analysedIn.get(e.id) || []).includes(f)).join(' '),
    });
  }
}

const cols = Object.keys(rows[0]);
const csvCell = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
await writeFile(join(OUT, 'catalogue.csv'), '﻿' + [cols.join(','), ...rows.map(r => cols.map(c => csvCell(r[c])).join(','))].join('\r\n') + '\r\n');
await writeFile(join(OUT, 'catalogue.json'), JSON.stringify(rows, null, 1));

// Summary for CATALOGUE.md
const count = (list, key) => list.reduce((m, r) => (m[r[key]] = (m[r[key]] || 0) + 1, m), {});
const byKind = {};
for (const r of rows) { byKind[r.kind] ??= {}; byKind[r.kind][r.category] = (byKind[r.kind][r.category] || 0) + 1; }
const summary = { total: rows.length, byKind, byPriority: count(rows, 'priority'), byStatus: count(rows, 'analysis_status'),
  unavailable: Object.keys(failures).length };
await writeFile(join(OUT, 'summary.json'), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 1));

// CATALOGUE.md: a readable index. Every upload is in catalogue.csv; this file lists the 222 selected ones by family.
const log = await readJson(join(RAW, 'fetch_log.json'), {});
const cm = log.channelMeta || {};
const mmss = s => s === '' || s == null ? '' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const md = s => String(s ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim();
const STATUS = { analysed: 'analysed', duplicate_noted: 'duplicate noted', transcript_ready: 'transcript only', blocked_no_captions: 'no captions',
  extraction_failed: 'extraction failed', unavailable: 'unavailable', queued: 'queued', not_selected: 'not selected' };
const kinds = ['video', 'short', 'stream'];
const cats = [...new Set(rows.map(r => r.category))];
const L = [];
L.push('# Booming Bulls catalogue', '');
L.push(`Built ${new Date().toISOString().slice(0, 10)} by \`bb_build_catalogue.mjs\` from a listing fetched ${String(log.fetchedAt || '').slice(0, 16).replace('T', ' ')} UTC.`, '');
L.push('## Source', '');
L.push(`- **Channel:** ${cm.channel || ''} (${cm.uploader_id || ''}), id \`${cm.channel_id || ''}\`, ${cm.channel_url || ''}`);
const metaFiles = (await readdir(META)).filter(f => /^[A-Za-z0-9_-]{11}\.json$/.test(f));
let verifiedCount = 0, sameChannel = 0;
for (const f of metaFiles) { const j = await readJson(join(META, f), {}); if (j.channel_is_verified) verifiedCount++; if (j.channel_id === cm.channel_id) sameChannel++; }
L.push(`- **Verified:** YouTube's \`channel_is_verified\` flag is true on ${verifiedCount} of ${metaFiles.length} fetched video pages, and ${sameChannel} of ${metaFiles.length} carry this channel id; ${((cm.channel_follower_count || 0) / 1e6).toFixed(2)} million subscribers at fetch time.`);
L.push(`- **Listing:** yt-dlp flat listings of the Videos (${log.tabs?.videos?.count}), Shorts (${log.tabs?.shorts?.count}) and Live (${log.tabs?.streams?.count}) tabs, ${rows.length} uploads in all. The Playlists tab listed ${(log.playlists || []).length} playlists.`);
L.push('- **Not covered:** members-only, private, unlisted and deleted videos, community posts, and paid course material. A public listing cannot show them, so this is the complete *public* upload list on the fetch date, not everything the channel has published.', '');
L.push('## Counts', '');
L.push(`| Category | ${kinds.join(' | ')} | All |`, `|---|${kinds.map(() => '--:').join('|')}|--:|`);
for (const c of cats) {
  const n = kinds.map(k => byKind[k]?.[c] || 0);
  L.push(`| ${c} | ${n.join(' | ')} | ${n.reduce((a, b) => a + b, 0)} |`);
}
L.push('', 'Categories `strategy` (P1), `concept` (P2) and `applied_example` (P3) are hand labels on the 222 uploads selected as strategy-related. The rest come from title rules, so they are rough.', '');
L.push('| Status | Uploads |', '|---|--:|');
for (const [s, n] of Object.entries(summary.byStatus)) L.push(`| ${STATUS[s] || s} | ${n} |`);
L.push('', `Metadata could not be fetched for ${summary.unavailable} selected uploads.`, '');
L.push('## Selected uploads by family', '');
L.push('P1 = a strategy video (rules wanted), P2 = a concept or definition, P3 = a worked example. Status `analysed` names the file in `analyses/`.', '');
const selected = rows.filter(r => r.priority !== 'X');
for (const fam of Object.keys(FAMILIES)) {
  const list = selected.filter(r => r.family === fam).sort((a, b) => a.priority.localeCompare(b.priority) || b.upload_date.localeCompare(a.upload_date));
  if (!list.length) continue;
  L.push(`### ${fam} ${FAMILIES[fam]} (${list.length})`, '');
  L.push('| Video | Date | Length | P | Market | Status | Title | Note |', '|---|---|--:|---|---|---|---|---|');
  for (const r of list) {
    const link = files => files.split(' ').filter(Boolean).map(f => `[${f.replace(/\.md$/, '').slice(0, 28)}](../analyses/${f})`).join(', ');
    const st = (r.analysis_files ? `${STATUS[r.analysis_status]}: ${link(r.analysis_files)}` : STATUS[r.analysis_status])
      + (r.referenced_in ? `; cited in ${link(r.referenced_in)}` : '');
    L.push(`| [${r.id}](${r.url}) | ${r.upload_date} | ${mmss(r.duration_s)} | ${r.priority} | ${r.market} | ${st} | ${md(r.title).slice(0, 90)} | ${md(r.relevance).slice(0, 90)} |`);
  }
  L.push('');
}
await writeFile(join(OUT, 'CATALOGUE.md'), L.join('\n'));
