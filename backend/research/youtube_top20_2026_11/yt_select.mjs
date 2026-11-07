// Phase 1c/2a: the final 20 channels and, per channel, the most-viewed long-form videos whose titles
// name a strategy, setup, system or indicator (the pool from which 2-4 signature strategy videos per
// channel are picked by hand in yt_picks.mjs). Output: data/top20.json, data/strategy_pool.json.
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TRADING, INVESTING } from './yt_listings_rules.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = join(HERE, 'data');
const screen = JSON.parse(await readFile(join(DATA, 'screen.json'), 'utf8'));
const EXCLUDED_ALREADY_DONE = ['UC2sIhf108S02F0Qlb2a88eQ'];   // Booming Bulls (backend/research/booming_bulls_2026_11)

// the inclusion rule (README): >= 25 of the 50 most-viewed titles trading-related, and more trading than investing-only
const qualifies = r => r.top50_trading >= 25 && r.top50_trading > r.top50_investing_only;
const ranked = screen.filter(r => !EXCLUDED_ALREADY_DONE.includes(r.channel_id)).sort((a, b) => b.followers - a.followers);
const top20 = ranked.filter(qualifies).slice(0, 20);
const excluded = ranked.filter(r => !qualifies(r) && r.followers >= top20[top20.length - 1].followers);
await writeFile(join(DATA, 'top20.json'), JSON.stringify({ rule: 'top-50 titles: trading >= 25 and > investing-only', top20, excluded }, null, 1));

const STRAT = /\b(strateg\w*|setup|system|rules?|indicator|rsi|macd|ema|sma|moving averages?|vwap|bollinger|stochastic|supertrend|heikin|ichimoku|fibonacci|breakout|pullback|scalp\w*|price action|candlestick|order block|liquidity|smc|silver bullet|judas|opening range|orb|gap (and|&) go|bull flag|abcd|trend ?line|support|resistance|supply|demand|divergence|crossover|pattern|win rate|backtest\w*|tested|profitable|how i (trade|day trade|make)|my (trading|best|favorite|favourite)|options? (buying|selling|strategy)|straddle|strangle|iron condor|hedg\w*)\b/i;
const pool = {};
for (const c of top20) {
  const L = JSON.parse(await readFile(join(DATA, 'listings', `${c.channel_id}.json`), 'utf8')).entries;
  pool[c.channel_id] = L.filter(e => e.views != null && (e.duration ?? 0) >= 240 && STRAT.test(e.title))
    .sort((a, b) => b.views - a.views).slice(0, 14);
}
await writeFile(join(DATA, 'strategy_pool.json'), JSON.stringify(pool, null, 1));
for (const [i, c] of top20.entries()) {
  console.log(`\n#${i + 1} ${c.channel} (${(c.followers / 1e6).toFixed(2)}M, ${c.videos} videos) ${c.channel_id}`);
  for (const e of pool[c.channel_id].slice(0, 10)) console.log(`   ${e.id} ${String(Math.round(e.views / 1000)).padStart(6)}k ${String(Math.round((e.duration || 0) / 60)).padStart(3)}m  ${e.title.slice(0, 88)}`);
}
console.log('\nexcluded above the cut:', excluded.map(r => `${r.name} (${r.top50_trading}/${r.top50_investing_only})`).join(', '));
