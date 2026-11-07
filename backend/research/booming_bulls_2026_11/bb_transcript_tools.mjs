// Phase 2 helpers: turn the app's evidence (transcript.json from extract.mjs) into a compact,
// readable transcript, without changing any words.
//  1. collapseRolling: YouTube auto-captions repeat each phrase ("A", "A B", "B", "B C", ...).
//     Keep only the new words of each cue (longest overlap with the tail of the text so far).
//  2. romanize: Devanagari -> plain Latin letters (Hunterian-style, Hindi schwa dropped at word
//     ends), so Hindi and its many English loanwords read cheaply ("स्टॉप लॉस" -> "stop los").
//     Non-Devanagari text passes through unchanged.
//  3. blocks: words grouped into timestamped blocks (default 30 s).

const CONS = {
  'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng', 'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
  'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
  'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ल': 'l', 'ळ': 'l', 'व': 'v',
  'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
  'क़': 'q', 'ख़': 'kh', 'ग़': 'gh', 'ज़': 'z', 'ड़': 'r', 'ढ़': 'rh', 'फ़': 'f', 'य़': 'y',
};
const NUKTA_BASE = { 'क': 'q', 'ख': 'kh', 'ग': 'gh', 'ज': 'z', 'ड': 'r', 'ढ': 'rh', 'फ': 'f', 'य': 'y' };
const VOWELS = { 'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri', 'ए': 'e', 'ऐ': 'ai',
  'ओ': 'o', 'औ': 'au', 'ऑ': 'o', 'ऍ': 'e', 'ऎ': 'e', 'ऒ': 'o' };
const MATRAS = { 'ा': 'aa', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o',
  'ौ': 'au', 'ॉ': 'o', 'ॅ': 'e', 'ॆ': 'e', 'ॊ': 'o' };
const VIRAMA = '्', NUKTA = '़', ANUSVARA = 'ं', CHANDRA = 'ँ', VISARGA = 'ः';
const DIGITS = '०१२३४५६७८९';

function romanizeWord(word) {
  if (!/[ऀ-ॿ]/.test(word)) return word;
  let out = '';
  const chars = [...word];
  for (let i = 0; i < chars.length; i++) {
    let c = chars[i];
    if (chars[i + 1] === NUKTA && NUKTA_BASE[c]) { out += NUKTA_BASE[c]; i++; c = null; }
    else if (CONS[c] !== undefined) { out += CONS[c]; c = null; }
    if (c === null) {
      const next = chars[i + 1];
      if (next === VIRAMA) { i++; continue; }
      if (next !== undefined && MATRAS[next] !== undefined) { out += MATRAS[next]; i++; continue; }
      if (next === ANUSVARA || next === CHANDRA) { out += 'a'; continue; }
      // inherent vowel: dropped at the end of a word (Hindi schwa deletion), kept elsewhere
      if (next !== undefined && /[ऀ-ॣ०-ॿ]/.test(next)) out += 'a';   // not before a danda
      continue;
    }
    if (VOWELS[c] !== undefined) out += VOWELS[c];
    else if (MATRAS[c] !== undefined) out += MATRAS[c];
    else if (c === ANUSVARA || c === CHANDRA) out += 'n';
    else if (c === VISARGA) out += 'h';
    else if (c === '।' || c === '॥') out += '.';
    else if (DIGITS.includes(c)) out += String(DIGITS.indexOf(c));
    else if (c === VIRAMA || c === NUKTA) { /* stray mark */ }
    else out += c;
  }
  return out;
}

export function romanize(text) {
  return text.split(/(\s+)/).map(romanizeWord).join('');
}

export function collapseRolling(cues) {
  const words = [];
  for (const cue of cues) {
    const incoming = cue.text.split(/\s+/).filter(Boolean);
    let overlap = 0;
    for (let k = Math.min(incoming.length, words.length); k > 0; k--) {
      let same = true;
      for (let i = 0; i < k; i++) if (words[words.length - k + i].word !== incoming[i]) { same = false; break; }
      if (same) { overlap = k; break; }
    }
    for (const word of incoming.slice(overlap)) words.push({ word, at: cue.start });
  }
  return words;
}

export const clock = s => {
  const n = Math.floor(s);
  return [Math.floor(n / 3600), Math.floor(n / 60) % 60, n % 60].map(x => String(x).padStart(2, '0')).join(':');
};

export function blocks(words, seconds = 30, transform = x => x) {
  const map = new Map();
  for (const { word, at } of words) {
    const key = Math.floor(at / seconds) * seconds;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(word);
  }
  return [...map.entries()].sort((a, b) => a[0] - b[0]).map(([t, w]) => `[${clock(t)}] ${transform(w.join(' '))}`);
}
