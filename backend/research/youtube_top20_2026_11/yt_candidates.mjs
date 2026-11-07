// Phase 1a: the candidate pool for "the top 20 trading YouTubers". Each candidate's live subscriber count,
// channel id, upload count and description come from YouTube itself (yt-dlp), never from blog lists.
// A guessed handle that fails is resolved by a YouTube search for the channel name (the result whose
// channel title matches). Output: data/candidates.json.  Usage: node yt_candidates.mjs
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'data');
const YT = ['--ignore-config', '--no-warnings', '--socket-timeout', '20', '--retries', '2'];

// [display name, guessed handle, search query, region]. Pool built from published lists
// (Pocketful, Analytics Insight, Feedspot, daytradingz, AskTraders, Benzinga) plus well-known channels.
export const CANDIDATES = [
  ['Pushkar Raj Thakur', '@PushkarRajThakur', 'Pushkar Raj Thakur stock market', 'IN'],
  ['FinnovationZ by Prasad', '@FinnovationZ', 'FinnovationZ Prasad', 'IN'],
  ['Asset Yogi', '@AssetYogi', 'Asset Yogi', 'IN'],
  ['Trading Chanakya', '@TradingChanakya', 'Trading Chanakya', 'IN'],
  ['Ghanshyam Tech', '@GhanshyamTech', 'Ghanshyam Tech trading', 'IN'],
  ['Theta Gainers', '@ThetaGainers', 'Theta Gainers', 'IN'],
  ['Power of Stocks', '@powerofstocks', 'Power of Stocks Subasish Pani', 'IN'],
  ['Nitin Bhatia', '@NitinBhatia', 'Nitin Bhatia technical analysis', 'IN'],
  ['Super Trader Lakshya', '@SuperTraderLakshya', 'Super Trader Lakshya', 'IN'],
  ['CA Rachana Phadke Ranade', '@CARachanaRanade', 'CA Rachana Phadke Ranade', 'IN'],
  ['Pranjal Kamra', '@pranjalkamra', 'Pranjal Kamra', 'IN'],
  ['Elearnmarkets', '@Elearnmarkets', 'Elearnmarkets Vivek Bajaj', 'IN'],
  ['Siddharth Bhanushali', '@SiddharthBhanushali', 'Siddharth Bhanushali trading', 'IN'],
  ['Abhishek Kar', '@AbhishekKar', 'Abhishek Kar trading', 'IN'],
  ['Trade Swing', '@TradeSwing', 'Trade Swing intraday', 'IN'],
  ['Stock Market Telugu', '@StockMarketTelugu', 'Stock Market Telugu intraday', 'IN'],
  ['DAY TRADER Telugu', '@DAYTRADERTelugu', 'DAY TRADER Telugu', 'IN'],
  ['Wealth Secret', '@WealthSecret', 'Wealth Secret stock market', 'IN'],
  ['Trading Fuel', '@TradingFuel', 'Trading Fuel', 'IN'],
  ['Market Gurukul', '@MarketGurukul', 'Market Gurukul', 'IN'],
  ['Vishal Malkan', '@VishalMalkan', 'Vishal B Malkan', 'IN'],
  ['Sahi Trade', '@sahitrade', 'Sahi Trade', 'IN'],
  ['Trade with Trend', '@TradewithTrend', 'Trade with Trend', 'IN'],
  ['Invest Aaj For Kal', '@InvestAajForKal', 'Invest Aaj For Kal', 'IN'],
  ['Sunil Minglani', '@SunilMinglani', 'Sunil Minglani', 'IN'],
  ['The Trading Channel', '@TheTradingChannel', 'The Trading Channel Steven Hart', 'GL'],
  ['Rayner Teo', '@RaynerTeo', 'Rayner Teo trading', 'GL'],
  ['Warrior Trading', '@DaytradeWarrior', 'Warrior Trading Ross Cameron', 'GL'],
  ['Humbled Trader', '@HumbledTrader', 'Humbled Trader', 'GL'],
  ['Trading Rush', '@TradingRush', 'Trading Rush strategy tested 100 times', 'GL'],
  ['Adam Khoo', '@AdamKhoo', 'Adam Khoo trading', 'GL'],
  ['The Inner Circle Trader', '@InnerCircleTrader', 'The Inner Circle Trader ICT', 'GL'],
  ['Wysetrade', '@Wysetrade', 'Wysetrade', 'GL'],
  ['Ricky Gutierrez', '@rickygutierrezz', 'Ricky Gutierrez trading', 'GL'],
  ['Bear Bull Traders', '@BearBullTraders', 'Bear Bull Traders Andrew Aziz', 'GL'],
  ['Chart Fanatics', '@ChartFanatics', 'Chart Fanatics', 'GL'],
  ['ClayTrader', '@ClayTrader', 'ClayTrader', 'GL'],
  ['UKspreadbetting', '@UKspreadbetting', 'UKspreadbetting', 'GL'],
  ['Trader Nick', '@TraderNick', 'Trader Nick', 'GL'],
  ['Hannah Forex', '@HannahForex', 'Hannah Forex', 'GL'],
  ['Urban Forex', '@UrbanForex', 'Urban Forex Navin Prithyani', 'GL'],
  ['MJ OPO Forex', '@MJOPO', 'MJ OPO Forex Trading', 'GL'],
  ['Thomas Kralow', '@ThomasKralow', 'Thomas Kralow trading', 'GL'],
  ['The Secret Mindset', '@TheSecretMindset', 'The Secret Mindset trading', 'GL'],
  ['Smart Risk', '@SmartRisk', 'Smart Risk trading', 'GL'],
  ['Tori Trades', '@ToriTrades', 'Tori Trades forex', 'GL'],
  ['Casper SMC', '@CasperSMC', 'Casper SMC', 'GL'],
  ['The Moving Average', '@TheMovingAverage', 'The Moving Average Ziad', 'GL'],
  ['Investors Underground', '@InvestorsUnderground', 'Investors Underground', 'GL'],
  ['StocksToTrade', '@StocksToTrade', 'StocksToTrade Tim Sykes', 'GL'],
  ['Data Trader', '@DataTrader', 'Data Trader backtest strategy', 'GL'],
  ['Benjamin Cowen', '@intothecryptoverse', 'Into The Cryptoverse Benjamin Cowen', 'GL'],
  ['Krown Crypto Cave', '@KrownsCryptoCave', 'Krowns Crypto Cave', 'GL'],
  ['Waqar Asim', '@WaqarAsim', 'Waqar Asim trading', 'GL'],
  ['Jason Graystone', '@JasonGraystone', 'Jason Graystone', 'GL'],
];

async function channelMeta(url) {
  const { stdout } = await run('yt-dlp', [...YT, '--flat-playlist', '-J', '--playlist-items', '1', url], { maxBuffer: 64 * 1024 * 1024, timeout: 120000, windowsHide: true });
  const j = JSON.parse(stdout);
  return {
    url, channel: j.channel || j.uploader || j.title, channel_id: j.channel_id || j.id, handle: j.uploader_id,
    followers: j.channel_follower_count ?? null, description: String(j.description || '').slice(0, 600),
    tags: (j.tags || []).slice(0, 15),
  };
}

async function resolveBySearch(name, query) {
  const { stdout } = await run('yt-dlp', [...YT, '--flat-playlist', '-J', `ytsearch12:${query}`], { maxBuffer: 64 * 1024 * 1024, timeout: 120000, windowsHide: true });
  const j = JSON.parse(stdout);
  const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const want = norm(name);
  const hit = (j.entries || []).find(e => norm(e.channel).includes(want) || want.includes(norm(e.channel)) && norm(e.channel).length > 4);
  if (!hit) return null;
  return hit.channel_url || (hit.channel_id ? `https://www.youtube.com/channel/${hit.channel_id}` : null);
}

// second pass: handles that failed or matched the wrong channel in pass 1, plus large channels missing from it
export const CANDIDATES2 = [
  ['Waqar Asim', '@WaqarAsimOfficial', 'Waqar Asim forex crypto trading', 'GL'],
  ['SMART RISK', '@SMARTRISK1', 'Smart Risk trading strategy', 'GL'],
  ['Chart Fanatics', '@chartfanatics', 'Chart Fanatics trader interview', 'GL'],
  ['Casper SMC', '@caspersmc', 'Casper SMC smart money concepts', 'GL'],
  ['Malkan View', '@MalkanView', 'Malkan View Vishal Malkan', 'IN'],
  ['Data Trader', '@DataTraderYT', 'Data Trader strategy backtest results', 'GL'],
  ['tastylive', '@tastyliveshow', 'tastylive options', 'GL'],
  ['Option Alpha', '@OptionAlpha', 'Option Alpha', 'GL'],
  ['InTheMoney', '@InTheMoneyAdam', 'InTheMoney Adam options', 'GL'],
  ['PR Sundar', '@PRSundar', 'PR Sundar option selling', 'IN'],
  ['Tom Nash', '@TomNashTV', 'Tom Nash trading', 'GL'],
  ['Vivek Singh Trader', '@VivekSinghTrader', 'Vivek Singh Booming Bulls trader', 'IN'],
];
const LIST = process.argv[2] === '2' ? CANDIDATES2 : CANDIDATES;
const OUTFILE = process.argv[2] === '2' ? 'candidates2.json' : 'candidates.json';
await mkdir(OUT, { recursive: true });
const out = [];
for (const [name, handle, query, region] of LIST) {
  let meta = null, how = 'handle', err = '';
  try { meta = await channelMeta(`https://www.youtube.com/${handle}/videos`); }
  catch (e) { err = String(e.stderr || e.message).split('\n').find(l => l.includes('ERROR')) || String(e.message).slice(0, 120); }
  if (!meta) {
    try {
      const url = await resolveBySearch(name, query);
      if (url) { meta = await channelMeta(url.replace(/\/$/, '') + '/videos'); how = 'search'; }
    } catch (e) { err += ' | search: ' + String(e.message).slice(0, 100); }
  }
  const row = { name, region, how, ...(meta || { followers: null, error: err.slice(0, 200) }) };
  out.push(row);
  console.log(`${name.padEnd(26)} ${String(row.followers ?? '-').padStart(10)}  ${row.channel ?? ''} ${row.handle ?? ''} (${how}${meta ? '' : ' FAILED'})`);
}
await writeFile(join(OUT, OUTFILE), JSON.stringify({ fetchedAt: new Date().toISOString(), candidates: out }, null, 1));
