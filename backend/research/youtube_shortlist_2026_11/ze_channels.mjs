// The owner's channel shortlist (12 Nov 2026): three pasted lists - 50 cross-market channels, 50 more (51-100) and 50
// Indian intraday-stock channels - merged into one list of unique channels; a fourth list (13 Nov 2026) of 50 crypto
// and gold channels adds 31 new ones (group 'gold' = gold / metals channels), and ten more crypto channels (14 Nov,
// D51-D60) add nine, and ten more (D61-D70) add ten; the ranks 11-20 crypto list (14 Nov) adds one, SCryptoTrader
// (D71; the other nine were already listed); the list 21-40 (14 Nov) adds 14 (D72-D91; six were already listed);
// the NIFTY option-buying list (14 Nov, list E) adds 32 (E1-E50; 18 were already listed). Each row:
//   [key, name as listed, search query, star (owner's list marked it a priority), list positions, market group, earlier]
// `earlier` names the study that already covered the channel (or screened and skipped it), so this study can skip
// the videos it read. Market groups: in = Indian stocks / index / options, crypto, fx = forex and cross-market price
// action, fut = futures, commodities and order flow, sys = systematic trading and coding, broker = Indian broker
// education channels.
//   node ze_channels.mjs resolve     -> registry/channels.json (YouTube channel search, top 5 candidates, a pick)
//   node ze_channels.mjs catalogue   -> the Lab's catalogue of every picked channel (videos + streams, no Shorts)
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, writeFileSync, existsSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const run0 = promisify(execFile);
const APP = 'D:/INDIAN MARKET/youtube-video-explainer-reviewed';
const { tool, toolPath } = await import('file:///' + APP + '/lib/tools.mjs');
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'registry', 'channels.json');

export const CHANNELS = [
  // ── list 1: Indian markets (1-15)
  ['elearnmarkets', 'Elearnmarkets / Face2Face', 'Elearnmarkets', 1, 'A1 C3 E23', 'in', 'top20'],
  ['tradewithtrend', 'Trade With Trend - Raunak A', 'Trade With Trend Raunak', 1, 'A2 C1 E20', 'in', ''],
  ['definedge', 'Definedge', 'Definedge', 1, 'A3 C2 E6', 'in', ''],
  ['powerofstocks', 'POWER OF STOCKS - Subasish Pani', 'Power of Stocks Subasish Pani', 1, 'A4 C22 E8', 'in', 'top20'],
  ['vivekbajaj', 'Vivek Bajaj', 'Vivek Bajaj', 0, 'A5 C11', 'in', ''],
  ['boomingbulls', 'Booming Bulls - Anish Singh Thakur', 'Booming Bulls', 0, 'A6 C21 E16', 'in', 'booming_bulls'],
  ['siddharthbhanushali', 'Siddharth Bhanushali', 'Siddharth Bhanushali', 0, 'A7 C10 E26', 'in', 'top20'],
  ['malkansview', 'Malkansview - Vishal Malkan', 'Malkansview', 0, 'A8 C12', 'in', ''],
  ['tradingchanakya', 'Trading Chanakya', 'Trading Chanakya', 0, 'A9 C9 E37', 'in', 'channels20-skipped'],
  ['sensibull', 'Be Sensibull', 'Sensibull', 1, 'A10 E34', 'in', ''],
  ['zerodhavarsity', 'Zerodha Varsity', 'Varsity by Zerodha', 0, 'A11 C46', 'broker', ''],
  ['dhan', 'Dhan', 'Dhan', 0, 'A12 C16 E13', 'broker', 'channels20'],
  ['tradeachievers', 'Trade Achievers', 'Trade Achievers', 0, 'A13 C8', 'in', ''],
  ['marketgurukul', 'Market Gurukul', 'Market Gurukul', 0, 'A14 C28', 'in', ''],
  ['equity2commodity', 'Equity2Commodity', 'Equity2Commodity', 0, 'A15', 'in', 'channels20-skipped'],
  // ── list 1: crypto (16-25)
  ['cryptocred', 'CryptoCred', 'CryptoCred', 1, 'A16 D1', 'crypto', ''],
  ['technicalroundup', 'TechnicalRoundup', 'TechnicalRoundup', 1, 'A17', 'crypto', ''],
  ['tradermayne', 'Trader Mayne', 'Trader Mayne', 1, 'A18 D2', 'crypto', ''],
  ['thechartguys', 'The Chart Guys', 'The Chart Guys', 1, 'A19 D5', 'crypto', ''],
  ['krown', 'Krown / Eric Krown', 'Eric Krown', 1, 'A20 D3', 'crypto', ''],
  ['koroushak', 'Koroush AK', 'Koroush AK', 0, 'A21', 'crypto', ''],
  ['birbnest', 'The Birb Nest', 'The Birb Nest', 0, 'A22', 'crypto', ''],
  ['datadash', 'DataDash', 'DataDash', 0, 'A23 D17', 'crypto', ''],
  ['coindcx', 'CoinDCX', 'CoinDCX', 0, 'A24', 'crypto', ''],
  ['deltaexchange', 'Delta Exchange', 'Delta Exchange', 1, 'A25', 'crypto', 'channels20'],
  // ── list 1: forex and cross-market (26-40)
  ['raynerteo', 'Rayner Teo / TradingwithRayner', 'Rayner Teo', 1, 'A26 D41', 'fx', 'top20'],
  ['thetradingchannel', 'The Trading Channel - Steven Hart', 'The Trading Channel Steven Hart', 1, 'A27 D42', 'fx', 'top20'],
  ['tradeciety', 'Tradeciety', 'Tradeciety', 1, 'A28 D43', 'fx', ''],
  ['tradingnut', 'Trading Nut', 'Trading Nut', 1, 'A29', 'fx', ''],
  ['tradernick', 'TraderNick', 'TraderNick', 1, 'A30 D26', 'fx', 'channels20-skipped'],
  ['desiretotrade', 'Etienne Crete - Desire To TRADE', 'Desire To Trade Etienne Crete', 0, 'A31', 'fx', ''],
  ['nononsenseforex', 'No Nonsense Forex', 'No Nonsense Forex', 1, 'A32', 'fx', ''],
  ['ukspreadbetting', 'UKspreadbetting', 'UKspreadbetting', 0, 'A33 D44', 'fx', ''],
  ['ict', 'The Inner Circle Trader - ICT', 'The Inner Circle Trader', 0, 'A34', 'fx', 'top20'],
  ['themovingaverage', 'The Moving Average', 'The Moving Average trading', 0, 'A35', 'fx', 'top20'],
  ['tradingrush', 'Trading Rush', 'TRADING RUSH', 1, 'A36 D81', 'fx', 'channels20'],
  ['traderdale', 'Trader Dale', 'Trader Dale', 0, 'A37', 'fx', ''],
  ['adamkhoo', 'Adam Khoo', 'Adam Khoo', 0, 'A38 D47', 'fx', 'top20'],
  ['akilstokes', 'Akil Stokes', 'Akil Stokes', 0, 'A39 D45', 'fx', ''],
  ['forexsignalstv', 'ForexSignals TV', 'ForexSignals TV', 0, 'A40', 'fx', ''],
  // ── list 1: commodities and futures (41-50)
  ['cmegroup', 'CME Group', 'CME Group', 1, 'A41 D32', 'fut', ''],
  ['mcxindia', 'MCX - Multi Commodity Exchange of India', 'MCX India Multi Commodity Exchange', 0, 'A42', 'fut', ''],
  ['axiafutures', 'Axia Futures', 'Axia Futures', 1, 'A43', 'fut', ''],
  ['bookmap', 'Bookmap', 'Bookmap', 1, 'A44', 'fut', ''],
  ['optimusfutures', 'Optimus Futures', 'Optimus Futures', 1, 'A45', 'fut', ''],
  ['ninjatrader', 'NinjaTrader', 'NinjaTrader', 0, 'A46', 'fut', ''],
  ['futurestrader71', 'FuturesTrader71', 'FuturesTrader71', 0, 'A47', 'fut', ''],
  ['tastylive', 'tastylive', 'tastylive', 0, 'A48 D50', 'fut', ''],
  ['nexusfi', 'futures io / NexusFi', 'NexusFi futures io', 0, 'A49', 'fut', ''],
  ['smbcapital', 'SMB Capital', 'SMB Capital', 0, 'A50 D48', 'fut', ''],
  // ── list 2: Indian markets (51-60)
  ['pivotcall', 'Pivot Call - Vikram Prabhu', 'Pivot Call Vikram Prabhu', 1, 'B51 C13 E15', 'in', ''],
  ['cprbykgs', 'CPR by KGS - Gomathi Shankar', 'CPR by KGS', 1, 'B52 C5', 'in', ''],
  ['thetagainers', 'Theta Gainers', 'Theta Gainers', 1, 'B53', 'in', 'channels11'],
  ['tradingcafeindia', 'Trading Cafe India', 'Trading Cafe India', 0, 'B54 C23', 'in', ''],
  ['upsurgeclub', 'Upsurge Club', 'Upsurge Club', 0, 'B55 C4 E18', 'in', 'channels20'],
  ['learnapp', 'LearnApp', 'LearnApp', 0, 'B56 C14', 'in', ''],
  ['fyers', 'FYERS', 'Trading with FYERS', 0, 'B57 C17 E33', 'broker', ''],
  ['samco', 'Samco Securities', 'Samco Securities', 0, 'B58 C19', 'broker', ''],
  ['fessorpro', 'FessorPro', 'FessorPro', 1, 'B59 C50', 'sys', ''],
  ['stockphoenix', 'Stock Phoenix', 'Stock Phoenix', 0, 'B60 C27', 'in', ''],
  // ── list 2: crypto (61-70)
  ['traderxo', 'TraderXO', 'TraderXO', 1, 'B61', 'crypto', ''],
  ['tradersz', 'TraderSZ', 'TraderSZ', 0, 'B62', 'crypto', ''],
  ['chartchampions', 'Chart Champions', 'Chart Champions', 1, 'B63 D6', 'crypto', ''],
  ['exocharts', 'Exocharts', 'Exocharts', 0, 'B64', 'crypto', ''],
  ['deribit', 'Deribit', 'Deribit', 1, 'B65', 'crypto', ''],
  ['glassnode', 'Glassnode', 'Glassnode', 0, 'B66', 'crypto', ''],
  ['cryptoquant', 'CryptoQuant', 'CryptoQuant', 0, 'B67', 'crypto', ''],
  ['benjamincowen', 'Benjamin Cowen', 'Benjamin Cowen Into The Cryptoverse', 0, 'B68 D14', 'crypto', ''],
  ['cryptojebb', 'Crypto Jebb', 'Crypto Jebb', 0, 'B69 D16', 'crypto', ''],
  ['wolfofallstreets', 'The Wolf of All Streets', 'The Wolf Of All Streets', 0, 'B70', 'crypto', ''],
  // ── list 2: forex and price action (71-75)
  ['wysetrade', 'Wysetrade', 'Wysetrade', 1, 'B71', 'fx', 'top20'],
  ['urbanforex', 'Urban Forex - Navin Prithyani', 'Urban Forex Navin Prithyani', 0, 'B72 D46', 'fx', ''],
  ['nickshawn', 'Nick Shawn', 'Nick Shawn', 0, 'B73', 'fx', ''],
  ['doyleexchange', 'Doyle Exchange', 'Doyle Exchange', 0, 'B74', 'fx', ''],
  ['2ndskies', '2nd Skies Trading - Chris Capre', '2ndSkies Trading Chris Capre', 0, 'B75', 'fx', ''],
  // ── list 2: futures and order flow (76-90)
  ['jigsawtrading', 'Jigsaw Trading', 'Jigsaw Trading', 1, 'B76', 'fut', ''],
  ['atas', 'ATAS', 'ATAS order flow trading', 1, 'B77', 'fut', ''],
  ['albrooks', 'Al Brooks / Brooks Trading Course', 'Brooks Trading Course Al Brooks', 1, 'B78', 'fut', ''],
  ['patstrading', 'PATsTrading - Mack', 'PATs Trading Mack', 0, 'B79', 'fut', ''],
  ['aaronkorbs', 'Aaron Korbs', 'Aaron Korbs', 0, 'B80', 'fut', ''],
  ['carminerosato', 'Carmine Rosato', 'Carmine Rosato', 0, 'B81', 'fut', ''],
  ['anthonycrudele', 'Anthony Crudele', 'Anthony Crudele', 0, 'B82', 'fut', ''],
  ['pavtrader', 'Price Action Volume Trader', 'Price Action Volume Trader', 0, 'B83', 'fut', ''],
  ['toritrades', 'Tori Trades', 'Tori Trades', 0, 'B84', 'fut', 'top20'],
  ['imantrading', 'ImanTrading', 'ImanTrading', 0, 'B85', 'fut', ''],
  ['flowzonetrader', 'Flow Zone Trader', 'Flow Zone Trader', 0, 'B86', 'fut', ''],
  ['futuresfanatic', 'Roderick Casilli - Futures Fanatic', 'Futures Fanatic Roderick Casilli', 0, 'B87', 'fut', ''],
  ['lumitraders', 'LumiTraders', 'LumiTraders', 0, 'B88', 'fut', ''],
  ['tanjatrades', 'Tanja Trades', 'Tanja Trades', 0, 'B89', 'fut', ''],
  ['covetrader', 'Cove Trader', 'Cove Trader', 0, 'B90', 'fut', ''],
  // ── list 2: systematic trading and coding (91-100)
  ['quantinsti', 'QuantInsti', 'QuantInsti', 1, 'B91 C49 D90', 'sys', ''],
  ['quantconnect', 'QuantConnect', 'QuantConnect', 1, 'B92 D91', 'sys', ''],
  ['parttimelarry', 'Part Time Larry', 'Part Time Larry', 1, 'B93 D56', 'sys', ''],
  ['codetrading', 'CodeTrading', 'CodeTrading', 1, 'B94 D72', 'sys', ''],
  ['algovibes', 'Algovibes', 'Algovibes', 1, 'B95 D73', 'sys', ''],
  ['kevindavey', 'Algo Trading With Kevin Davey', 'Kevin Davey algo trading', 1, 'B96', 'sys', ''],
  ['strategyquant', 'StrategyQuant', 'StrategyQuant', 0, 'B97', 'sys', ''],
  ['artoftrading', 'The Art of Trading - Matthew J. Slabosz', 'The Art of Trading Matthew Slabosz', 1, 'B98 D80', 'sys', ''],
  ['quantpy', 'QuantPy', 'QuantPy', 0, 'B99', 'sys', ''],
  ['bettersystemtrader', 'Better System Trader', 'Better System Trader', 1, 'B100', 'sys', ''],
  // ── list 3: Indian intraday stock channels not in lists 1-2
  ['nitinbhatia', 'Nitin Bhatia', 'Nitin Bhatia', 0, 'C6 E50', 'in', 'top20'],
  ['kunalsaraogi', 'Kunal Saraogi', 'Kunal Saraogi', 0, 'C7', 'in', ''],
  ['stockpro', 'StockPro - Dr Seema Jain', 'StockPro Seema Jain', 0, 'C15', 'in', ''],
  ['groww', 'Trading with Groww', 'Groww', 0, 'C18 E22', 'broker', ''],
  ['upstox', 'Upstox', 'Upstox', 1, 'C20 E5', 'broker', ''],
  ['vibhorvarshney', 'Vibhor Varshney', 'Vibhor Varshney', 0, 'C24', 'in', ''],
  ['prakashgaba', 'Prakash Gaba', 'Prakash Gaba', 0, 'C25', 'in', ''],
  ['traderchitra', 'Trader Chitra', 'Trader Chitra', 0, 'C26', 'in', ''],
  ['eqsis', 'EQSIS', 'EQSIS', 0, 'C29', 'in', ''],
  ['vijaythakkar', 'Vijay Thakkar', 'Vijay Thakkar', 0, 'C30', 'in', 'channels20'],
  ['bharatjhunjhunwala', 'Bharat Jhunjhunwala', 'Bharat Jhunjhunwala', 0, 'C31 E11', 'in', 'channels20-skipped'],
  ['sunilminglani', 'Sunil Minglani', 'Sunil Minglani', 0, 'C32', 'in', 'top20'],
  ['pushkarrajthakur', 'Pushkar Raj Thakur', 'Pushkar Raj Thakur', 0, 'C33 E27', 'in', 'top20+channels11'],
  ['stockedge', 'StockEdge', 'StockEdge', 0, 'C34', 'in', ''],
  ['tradingcampus', 'Trading Campus', 'Trading Campus', 0, 'C35', 'in', ''],
  ['angelone', 'Angel One', 'Angel One', 0, 'C36', 'broker', ''],
  ['icicidirect', 'ICICI Direct', 'ICICI Direct', 0, 'C37', 'broker', ''],
  ['5paisa', '5paisa', '5paisa', 0, 'C38', 'broker', ''],
  ['aliceblue', 'Alice Blue', 'Alice Blue Online', 0, 'C39', 'broker', ''],
  ['sharekhan', 'Mirae Asset Sharekhan', 'Sharekhan', 0, 'C40', 'broker', ''],
  ['hdfcsec', 'HDFC Securities', 'HDFC Securities', 0, 'C41', 'broker', ''],
  ['motilaloswal', 'Breakout with Motilal Oswal', 'Motilal Oswal', 0, 'C42', 'broker', ''],
  ['kotakstockshaala', 'Kotak Stockshaala', 'Kotak Stockshaala', 0, 'C43', 'broker', ''],
  ['tradejini', 'Tradejini', 'Tradejini', 0, 'C44', 'broker', ''],
  ['tradesmart', 'TradeSmart', 'TradeSmart Online', 0, 'C45', 'broker', ''],
  ['streak', 'Streak', 'Streak Tech algo', 0, 'C47', 'sys', ''],
  ['marketcalls', 'Marketcalls - Rajandran', 'Marketcalls Rajandran', 0, 'C48 E21', 'sys', ''],
  // ── list 4 (13 Nov 2026): 50 crypto and gold channels, D1-D50; the 19 already above carry their D position
  ['bitcointradingchallenge', 'Bitcoin Trading Challenge', 'Bitcoin Trading Challenge', 1, 'D4', 'crypto', ''],
  ['bitcoinhyper', 'Bitcoin Hyper', 'Bitcoin Hyper', 1, 'D7', 'crypto', ''],
  ['morecryptoonline', 'More Crypto Online', 'More Crypto Online', 0, 'D8', 'crypto', ''],
  ['cryptoanup', 'Crypto Anup', 'Crypto Anup', 0, 'D9', 'crypto', ''],
  ['cryptoface', 'Crypto Face', 'Crypto Face', 0, 'D10', 'crypto', ''],
  ['tradingparrot', 'The Trading Parrot', 'The Trading Parrot', 0, 'D11', 'crypto', ''],
  ['cryptocrewuniversity', 'Crypto Crew University', 'Crypto Crew University', 0, 'D12', 'crypto', ''],
  ['jasonpizzino', 'Jason Pizzino', 'Jason Pizzino', 0, 'D13', 'crypto', ''],
  ['rektcapital', 'Rekt Capital', 'Rekt Capital', 0, 'D15', 'crypto', ''],
  ['alessiorastani', 'Alessio Rastani', 'Alessio Rastani', 0, 'D18', 'crypto', ''],
  ['cryptobanter', 'Crypto Banter', 'Crypto Banter', 0, 'D19', 'crypto', ''],
  ['cryptokirby', 'Crypto Kirby', 'Crypto Kirby', 0, 'D20', 'crypto', ''],
  ['tylers', 'Tyler S', 'Tyler S bitcoin', 0, 'D21', 'crypto', ''],
  ['opticalartcrypto', 'OpticalArt Crypto', 'OpticalArt', 0, 'D22', 'crypto', ''],
  ['investanswers', 'InvestAnswers', 'InvestAnswers', 0, 'D23', 'crypto', ''],
  ['cryptozombie', 'Crypto Zombie', 'Crypto Zombie', 0, 'D24', 'crypto', ''],
  ['larkdavis', 'Lark Davis', 'Lark Davis', 0, 'D25', 'crypto', ''],
  ['vasilytrader', 'VasilyTrader', 'VasilyTrader', 1, 'D27', 'gold', ''],
  ['garethsoloway', 'Gareth Soloway', 'Gareth Soloway', 0, 'D28', 'gold', ''],
  ['goldsilverclub', 'The Gold & Silver Club', 'The Gold and Silver Club', 0, 'D29', 'gold', ''],
  ['pepperstone', 'Pepperstone', 'Pepperstone', 0, 'D30', 'gold', ''],
  ['capitalcom', 'Capital.com', 'Capital.com', 0, 'D31', 'gold', ''],
  ['interactivebrokers', 'Interactive Brokers', 'Interactive Brokers', 0, 'D33', 'gold', ''],
  ['tradewithpat', 'Trade with Pat', 'Trade with Pat', 0, 'D34', 'gold', 'channels20'],
  ['smartrisk', 'Smart Risk', 'Smart Risk', 0, 'D35', 'gold', ''],
  ['mambafx', 'MambaFx', 'MambaFx', 0, 'D36', 'gold', ''],
  ['faizsmc', 'Faiz SMC', 'Faiz SMC', 0, 'D37', 'gold', 'channels20'],
  ['mrpfx', 'Mr P Fx', 'Mr P Fx', 0, 'D38', 'gold', ''],
  ['tradewithaaro', 'Trade With Aaro', 'Trade With Aaro', 0, 'D39', 'gold', ''],
  ['forextradinglions', 'Forex Trading Lions', 'Forex Trading Lions', 0, 'D40', 'gold', ''],
  ['tradingview', 'TradingView', 'TradingView', 0, 'D49', 'sys', ''],
  // ── ten more (14 Nov 2026): crypto channels D51-D60 after the fourth list; Part Time Larry above carries D56
  ['daviddtech', 'Trading with DaviddTech', 'DaviddTech', 0, 'D51', 'crypto', ''],
  ['mangoresearch', 'Mango Research', 'Mango Research', 0, 'D52', 'crypto', ''],
  ['coinbureautrading', 'Coin Bureau Trading', 'Coin Bureau Trading', 0, 'D53', 'crypto', ''],
  ['mooninpapa', 'Moonin Papa', 'Moonin Papa', 0, 'D54', 'crypto', ''],
  ['tomcrown', 'Tom Crown', 'Tom Crown', 0, 'D55', 'crypto', ''],
  ['hummingbot', 'Hummingbot', 'Hummingbot', 0, 'D57', 'sys', ''],
  ['tradinglab', 'TradingLab', 'TradingLab', 0, 'D58', 'fx', 'channels20'],
  ['cryptoworldjosh', 'Crypto World - Josh', 'Crypto World Josh', 0, 'D59', 'crypto', ''],
  ['cryptowendyo', 'CryptoWendyO', 'CryptoWendyO', 0, 'D60', 'crypto', ''],
  // ── ten more (14 Nov 2026): crypto channels D61-D70
  ['tradepro', 'Trade Pro', 'Trade Pro trading', 0, 'D61', 'crypto', ''],
  ['josholszewicz', 'Josh Olszewicz', 'Josh Olszewicz crypto trading', 0, 'D62', 'crypto', ''],
  ['algotradingsaleh', 'Algo-trading with Saleh', 'Algo-trading with Saleh', 0, 'D63', 'sys', ''],
  ['moondev', 'Moon Dev', 'Moon Dev trading bots', 0, 'D64', 'sys', ''],
  ['kevinsvenson', 'Kevin Svenson', 'Kevin Svenson', 0, 'D65', 'crypto', ''],
  ['charthackers', 'Chart Hackers - Dylan', 'Chart Hackers', 0, 'D66', 'crypto', ''],
  ['cheekycrypto', 'Cheeky Crypto', 'Cheeky Crypto', 0, 'D67', 'crypto', ''],
  ['tradinglatino', 'Trading Latino - Jaime Merino', 'Trading Latino Jaime Merino', 0, 'D68', 'crypto', ''],
  ['bravenewcoin', 'Brave New Coin', 'Brave New Coin', 0, 'D69', 'crypto', ''],
  ['cryptosavy', 'Crypto Savy', 'Crypto Savy', 0, 'D70', 'crypto', ''],
  // ── ranks 11-20 crypto list (14 Nov 2026): the one channel not listed before
  ['scryptotrader', 'SCryptoTrader - Arslan Afzal', 'SCryptoTrader', 0, 'D71', 'fut', ''],
  // ── the list 21-40 (14 Nov 2026): 14 channels not listed before (D72-D91; six were already listed)
  ['robottraders', 'Robot Traders', 'Robot Traders algorithmic trading', 1, 'D74', 'sys', ''],
  ['quantnomad', 'QuantNomad', 'QuantNomad', 1, 'D75', 'sys', ''],
  ['chadthackray', 'Chad Thackray', 'Chad Thackray vectorbt', 0, 'D76', 'sys', ''],
  ['qubitquants', 'Qubit Quants', 'Qubit Quants', 0, 'D77', 'sys', ''],
  ['pyquantnews', 'PyQuant News', 'PyQuant News', 0, 'D78', 'sys', ''],
  ['tradescience', 'Trade Science', 'Trade Science walk forward', 0, 'D79', 'sys', ''],
  ['altfins', 'altFINS', 'altFINS crypto', 1, 'D82', 'crypto', ''],
  ['altrady', 'Altrady', 'Altrady crypto trading', 0, 'D83', 'crypto', ''],
  ['wundertrading', 'WunderTrading', 'WunderTrading', 0, 'D84', 'crypto', ''],
  ['threecommas', '3Commas', '3Commas official', 0, 'D85', 'crypto', ''],
  ['cryptohopper', 'Cryptohopper', 'Cryptohopper', 0, 'D86', 'crypto', ''],
  ['coinrule', 'Coinrule', 'Coinrule', 0, 'D87', 'crypto', ''],
  ['bitsgap', 'Bitsgap', 'Bitsgap', 0, 'D88', 'crypto', ''],
  ['secretmindset', 'The Secret Mindset', 'The Secret Mindset trading', 0, 'D89', 'fx', 'top20'],
  // ── list E (14 Nov 2026): the owner's NIFTY option-buying list (50 channels; 18 were already listed)
  ['inthemoney', 'In The Money by Zerodha', 'In The Money by Zerodha', 1, 'E1', 'in', ''],
  ['algotest', 'AlgoTest', 'AlgoTest', 1, 'E2', 'in', ''],
  ['aatradingblog', 'A&A Trading Blog', 'A&A Trading Blog', 1, 'E3', 'in', ''],
  ['quantsapp', 'Quantsapp', 'Quantsapp', 1, 'E4', 'in', ''],
  ['dhantamil', 'Dhan Tamil', 'Dhan Tamil', 0, 'E7', 'in', ''],
  ['quantman', 'QuantMan', 'QuantMan algo trading', 0, 'E9', 'in', ''],
  ['stockmock', 'Stockmock', 'Stockmock', 0, 'E10', 'in', ''],
  ['tradingwithsidhant', 'Trading With Sidhant', 'Trading With Sidhant', 0, 'E12', 'in', ''],
  ['studentsofmarket', 'Students of Market', 'Students of Market', 0, 'E14', 'in', ''],
  ['optionsscalpingsiva', 'Options Scalping - Siva', 'Options Scalping Siva', 0, 'E17', 'in', ''],
  ['investarindia', 'InvestarIndia', 'InvestarIndia', 0, 'E19', 'in', ''],
  ['strategicstocks', 'Strategic Stocks', 'Strategic Stocks', 0, 'E24', 'in', ''],
  ['traderinsights', 'Trader Insights', 'Trader Insights', 0, 'E25', 'in', ''],
  ['artofoptionlearning', 'Art of Option Learning - Ghanshyam', 'Art of Option Learning', 0, 'E28', 'in', ''],
  ['sakethramakrishna', 'Saketh Ramakrishna', 'Saketh Ramakrishna', 0, 'E29', 'in', ''],
  ['niftylearningbrijesh', 'Nifty Learning with Brijesh', 'Nifty Learning with Brijesh', 0, 'E30', 'in', ''],
  ['kevalkhimsariya', 'CA Keval Khimsariya', 'CA Keval Khimsariya', 0, 'E31', 'in', ''],
  ['tradetron', 'Tradetron', 'Tradetron', 0, 'E32', 'in', ''],
  ['nitinmurarka', 'Nitin Murarka', 'Nitin Murarka', 0, 'E35', 'in', ''],
  ['moneytalkspayal', 'Money Talks With Payal', 'Money Talks With Payal', 0, 'E36', 'in', ''],
  ['tradingwithvivek', 'Trading With Vivek', 'Trading With Vivek', 0, 'E38', 'in', ''],
  ['daytradertelugu', 'Day Trader Telugu', 'Day Trader Telugu', 0, 'E39', 'in', ''],
  ['moneypurse', 'Money Purse', 'Money Purse', 0, 'E40', 'in', ''],
  ['tradingkannada', 'Trading Kannada', 'Trading Kannada', 0, 'E41', 'in', ''],
  ['buycryrepeat', 'BuyCryRepeat Kannada', 'BuyCryRepeat Kannada', 0, 'E42', 'in', ''],
  ['shariquesamsudheen', 'Sharique Samsudheen', 'Sharique Samsudheen', 0, 'E43', 'in', ''],
  ['arunishoptionbuyer', 'Arunish Intraday Option Buyer', 'Arunish Intraday Option Buyer', 0, 'E44', 'in', ''],
  ['uniquetelugutrader', 'Unique Telugu Trader', 'Unique Telugu Trader', 0, 'E45', 'in', ''],
  ['dpthetrader', 'DP The Trader', 'DP The Trader', 0, 'E46', 'in', ''],
  ['zebutelugu', 'Zebu Telugu', 'Zebu Telugu', 0, 'E47', 'in', ''],
  ['derivativetradersameer', 'Derivative Trader Sameer', 'Derivative Trader Sameer', 0, 'E48', 'in', ''],
  ['abhishekxtrades', 'AbhishekXTrades', 'AbhishekXTrades', 0, 'E49', 'in', ''],
];

const ytdlp = (args, timeout = 300_000) =>
  run0(tool('yt-dlp'), args, { env: { ...process.env, PATH: toolPath() }, maxBuffer: 1 << 28, timeout });
const norm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').trim();
const toks = s => new Set(norm(s).split(' ').filter(t => t.length > 1 && !['the', 'by', 'with', 'trading', 'and', 'of'].includes(t)));
function score(name, query, title) {
  const want = new Set([...toks(name.split(/ [-/] /)[0]), ...toks(query)]);
  const got = toks(title);
  if (!want.size || !got.size) return 0;
  let hit = 0;
  for (const t of got) if (want.has(t)) hit++;
  return hit / got.size;
}

async function resolve() {
  const out = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : {};
  for (const [key, name, query, star, lists, group, earlier] of CHANNELS) {
    if (out[key]?.candidates) continue;
    const url = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(query) + '&sp=EgIQAg%253D%253D';
    try {
      const { stdout } = await ytdlp(['--ignore-config', '--no-warnings', '--flat-playlist', '-J', '--playlist-end', '5', url], 120_000);
      const j = JSON.parse(stdout);
      const candidates = (j.entries || []).filter(e => /^UC[\w-]{22}$/.test(e.id || '')).map(e => ({
        id: e.id, title: e.title || e.channel, followers: e.channel_follower_count ?? null,
        about: String(e.description || '').slice(0, 140).replace(/\s+/g, ' '), score: +score(name, query, e.title || e.channel).toFixed(2),
      }));
      const good = candidates.filter(c => c.score >= 0.5);
      const pick = (good.length ? good : candidates).slice().sort((a, b) => (b.score >= 0.5) - (a.score >= 0.5) || (b.followers || 0) - (a.followers || 0))[0] || null;
      out[key] = { key, name, query, star: !!star, lists, group, earlier, candidates, pick: pick?.id || null, pick_title: pick?.title || null, pick_followers: pick?.followers ?? null, sure: !!(pick && pick.score >= 0.5) };
    } catch (e) {
      out[key] = { key, name, query, star: !!star, lists, group, earlier, error: String(e.message).slice(0, 200) };
    }
    writeFileSync(OUT, JSON.stringify(out, null, 1));
    process.stdout.write(`${key}: ${out[key].pick_title || out[key].error} (${out[key].pick_followers ?? '-'}) ${out[key].sure ? '' : '  <-- CHECK'}\n`);
  }
}

async function catalogue() {
  const { catalogueChannel } = await import('file:///' + APP + '/lib/channels.mjs');
  const reg = JSON.parse(readFileSync(OUT, 'utf8'));
  const todo = Object.values(reg).filter(r => r.pick && !r.skip_catalogue)
    .flatMap(r => [r, ...(r.extra || []).map(x => ({ key: r.key + '+' + x.title, pick: x.id }))]);
  const fresh = id => { const f = join(APP, 'data', 'channels', id + '.json'); return existsSync(f) && Date.now() - statSync(f).mtimeMs < 7 * 86400e3; };
  let i = 0;
  const worker = async () => {
    while (i < todo.length) {
      const r = todo[i++];
      if (fresh(r.pick)) { process.stdout.write(`${r.key}: catalogue fresh, kept\n`); continue; }
      const t0 = Date.now();
      try {
        const s = await catalogueChannel('https://www.youtube.com/channel/' + r.pick, { tabs: ['videos', 'streams'], limit: 2500 });
        process.stdout.write(`${r.key}: ${s.total} uploads, P1 ${s.p1}, P2 ${s.p2} (${((Date.now() - t0) / 1000).toFixed(0)} s)\n`);
      } catch (e) {
        process.stdout.write(`${r.key}: FAILED ${String(e.message).slice(0, 160)}\n`);
      }
    }
  };
  await Promise.all([worker(), worker(), worker()]);
}

const cmd = process.argv[2];
if (cmd === 'resolve') await resolve();
else if (cmd === 'catalogue') await catalogue();
else if (cmd === 'count') console.log(CHANNELS.length, 'channels;', new Set(CHANNELS.map(c => c[0])).size, 'unique keys');
