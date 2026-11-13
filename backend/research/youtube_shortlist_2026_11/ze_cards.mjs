// Strategy cards for the channel-shortlist study (12 Nov 2026), written in a compact form (cards/<video id>.txt) and turned into
// the Trading Video Lab's card format (card.draft.json in the video's evidence folder), then imported through the Lab's
// own "Import card from Claude Code" route, which checks the schema and the timestamps. The same files feed the
// analyses (analyses/<channel>.md) and the strategy registry.
//   node ze_cards.mjs <video id> [...]      build + import the named cards
//   node ze_cards.mjs --all                 every cards/*.txt
//   node ze_cards.mjs --parse-only <id>     print the parsed card (no import)
//
// cards/<id>.txt format (one item per line; " | " separates fields):
//   video: <id>            topic: <india_index | india_stocks | crypto | gold | forex_us>  (the desk tab the strategy belongs to)
//   = <SID> | <strategy name>                         starts a strategy (a video may teach several)
//   R <kind> <E|I|A> <mm:ss,mm:ss|-> | <rule text> | <quote as spoken, "" for A>
//   T <ready|with_assumptions|concept_only|not_testable> | <reason>; <reason>     the current strategy's status
//   D <duplicate-of id> | <why>                        the current strategy repeats a library strategy
//   summary: / instruments: a; b* (* = not as taught) / timeframes: a, b / style: <enum>
//   V <term> | <rule no.> | <mm:ss> | <why vague> | <suggestion>
//   C <kind> | <mm:ss> | <value> | <period> | <quote>
//   X <date|-> | <mm:ss> | <instrument> | <long|short|none|unclear> | <setup> | <entry> | <stop> | <target> | <outcome> | <note>
//   P <from mm:ss> | <to mm:ss> | <what>        O <mm:ss> | <what shown, not said>        U <question>
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const API = 'http://127.0.0.1:8765';
const KINDS = ['market', 'timeframe', 'session', 'indicator', 'setup', 'entry', 'stop', 'target', 'exit', 'filter', 'no_trade', 'sizing', 'management'];
const STATUS = ['ready', 'with_assumptions', 'concept_only', 'not_testable'];
const ts = s => {
  s = String(s || '').trim();
  if (!s || s === '-') return '';
  const p = s.split(':').map(Number);
  const sec = p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  if (!Number.isFinite(sec)) throw new Error('bad time ' + s);
  return [Math.floor(sec / 3600), Math.floor(sec / 60) % 60, sec % 60].map(x => String(x).padStart(2, '0')).join(':');
};
const split = (s, n) => { const a = s.split(' | ').map(x => x.trim()); while (a.length < n) a.push(''); return a; };

export function parseCard(id) {
  const file = join(HERE, 'cards', id + '.txt');
  const text = readFileSync(file, 'utf8');
  const card = { video: id, topic: '', strategies: [], summary: '', instruments: [], timeframes: [], style: 'intraday',
    vague: [], claims: [], examples: [], promotions: [], screen: [], unclear: [] };
  let cur = null, n = 0;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    let m;
    if ((m = /^(video|topic|summary|instruments|timeframes|style):\s*(.*)$/.exec(line))) {
      const [, k, v] = m;
      if (k === 'video' && v !== id) throw new Error(file + ': video id mismatch');
      if (k === 'topic') card.topic = v;
      if (k === 'summary') card.summary = v;
      if (k === 'style') card.style = v;
      if (k === 'timeframes') card.timeframes = v.split(',').map(x => x.trim()).filter(Boolean);
      if (k === 'instruments') card.instruments = v.split(';').map(x => x.trim()).filter(Boolean)
        .map(x => ({ name: x.replace(/\*$/, '').trim(), as_taught: !x.endsWith('*') }));
      continue;
    }
    const tag = line[0], rest = line.slice(1).trim();
    if (tag === '=') { const [sid, name] = split(rest, 2); cur = { sid, name, rules: [], status: null, reasons: [], duplicate: null }; card.strategies.push(cur); continue; }
    if (tag === 'R') {
      if (!cur) throw new Error(file + ': rule before the first "=" strategy line');
      m = /^(\w+)\s+([EIA])\s+(\S+)\s*\|\s*(.*)$/.exec(rest);
      if (!m) throw new Error(file + ': bad rule line: ' + line);
      const [, kind, t, times, body] = m;
      if (!KINDS.includes(kind)) throw new Error(file + ': unknown kind ' + kind);
      const [textR, quote] = split(body, 2);
      n++;
      cur.rules.push({ id: 'R' + n, kind, text: textR, tag: t, timestamps: times === '-' ? [] : times.split(',').map(ts), quote: quote.replace(/^"|"$/g, '') });
      continue;
    }
    if (tag === 'T') { const [st, why] = split(rest, 2); if (!STATUS.includes(st)) throw new Error(file + ': bad status ' + st); cur.status = st; cur.reasons = why.split(';').map(x => x.trim()).filter(Boolean); continue; }
    if (tag === 'D') { const [of, why] = split(rest, 2); cur.duplicate = { of, why }; continue; }
    if (tag === 'V') { const [term, rule, at, why, suggestion] = split(rest, 5); card.vague.push({ term, rule_id: rule, timestamp: ts(at), why, suggestion }); continue; }
    if (tag === 'C') { const [kind, at, value, period, quote] = split(rest, 5); card.claims.push({ timestamp: ts(at), quote, kind, value, period }); continue; }
    if (tag === 'X') {
      const [date, at, instrument, direction, setup, entry, stop, target, outcome, note] = split(rest, 10);
      card.examples.push({ timestamp: ts(at), date: date === '-' ? '' : date, instrument, direction, setup, entry, stop, target, outcome, note });
      continue;
    }
    if (tag === 'P') { const [from, to, what] = split(rest, 3); card.promotions.push({ from: ts(from), to: ts(to), what }); continue; }
    if (tag === 'O') { const [at, what] = split(rest, 2); card.screen.push({ timestamp: ts(at), what }); continue; }
    if (tag === 'U') { card.unclear.push(rest); continue; }
    throw new Error(file + ': cannot read line: ' + line);
  }
  if (!card.topic || !card.strategies.length) throw new Error(file + ': topic and at least one strategy are required');
  for (const s of card.strategies) if (!s.status) throw new Error(file + ': ' + s.sid + ' has no T status line');
  return card;
}

const ORDER = { ready: 0, with_assumptions: 1, concept_only: 2, not_testable: 3 };
export function labCard(c) {
  const multi = c.strategies.length > 1;
  const best = c.strategies.map(s => s.status).sort((a, b) => ORDER[a] - ORDER[b])[0];
  return {
    strategy_name: c.strategies.map(s => (multi ? s.sid + ' ' : '') + s.name).join(' / '),
    summary: c.summary,
    instruments: c.instruments,
    timeframes: c.timeframes,
    style: c.style,
    rules: c.strategies.flatMap(s => s.rules.map(r => ({ ...r, text: (multi ? '[' + s.sid + '] ' : '') + r.text }))),
    vague_terms: c.vague,
    claims: c.claims,
    examples: c.examples,
    promotions: c.promotions,
    on_screen_only: c.screen,
    unclear: c.unclear,
    testability: { status: best, reasons: c.strategies.flatMap(s => s.reasons.map(r => (multi ? s.sid + ': ' : '') + r)) },
  };
}

async function importOne(id) {
  const { evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
  const e = await evidenceFor(id);
  if (!e) throw new Error('no evidence for ' + id);
  const c = parseCard(id);
  writeFileSync(join(e.folder, 'card.draft.json'), JSON.stringify(labCard(c), null, 2));
  const r = await fetch(API + '/api/cards/' + id + '/import', { method: 'POST', headers: { 'content-type': 'application/json', origin: API }, body: '{}' });
  const j = await r.json();
  if (!r.ok) throw new Error(id + ': import refused: ' + JSON.stringify(j).slice(0, 400));
  const w = j.record?.built?.warnings || j.built?.warnings || [];
  console.log(id, 'imported', c.strategies.map(s => s.sid + ':' + s.status).join(' '), w.length ? 'warnings: ' + w.join('; ') : '');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  if (args[0] === '--parse-only') { console.log(JSON.stringify(labCard(parseCard(args[1])), null, 1)); process.exit(0); }
  const ids = args[0] === '--all' ? readdirSync(join(HERE, 'cards')).filter(f => f.endsWith('.txt')).map(f => f.slice(0, -4)) : args;
  let bad = 0;
  for (const id of ids) {
    try { await importOne(id); } catch (err) { bad++; console.log('ERROR', err.message); }
  }
  if (bad) process.exitCode = 1;
}
