// Re-fetches one video's captions in a named language (a new evidence folder; the old one is kept), for videos whose
// first fetch took the wrong track - e.g. Hindi auto-captions of an English talk, which read as garbled Hindi spelling.
//   node ze_refetch.mjs <video id> <lang, e.g. en>
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { extractEvidence, evidenceFor } = await import('file:///' + APP + '/lib/evidence.mjs');
const [id, lang = 'en'] = process.argv.slice(2);
const r = await extractEvidence({ source: id, lang, fresh: true, onProgress: () => {} });
const t = r.manifest.transcript || {};
console.log(id, 'saved', r.folder.split(/[\\/]/).pop(), '|', t.source, '|', t.clean_words, 'words');
const now = await evidenceFor(id);
console.log('evidenceFor ->', now.folder.split(/[\\/]/).pop());
