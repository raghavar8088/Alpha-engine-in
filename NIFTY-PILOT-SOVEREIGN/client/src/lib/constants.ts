export type StrategyType =
  | "scalping"
  | "intraday"
  | "swing"
  | "options"
  | "index_options";

export type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "1d" | "1w";

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  type: StrategyType;
  timeframe: Timeframe;
  instruments: string[];
}

export const STRATEGIES: StrategyMeta[] = [
  // S1–S9  Original ORB / momentum (orb.go + s2_s9_momentum.go)
  { id: "S1",  name: "OpeningRangeBreakout",       description: "5-min ORB with ATR-scaled target, Futures",              type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S2",  name: "EMAMomentum",                description: "EMA9/EMA21 cross + ADX>25",                              type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S3",  name: "VWAPReversion",              description: "Price reverts to VWAP after 1.5σ deviation",             type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S4",  name: "RSIExtreme",                 description: "RSI<25 long / RSI>75 short with EMA filter",             type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S5",  name: "BollingerSqueeze",           description: "BB width < 20-bar min, breakout long/short",             type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S6",  name: "MACDHistogramReversal",      description: "MACD histogram sign flip at momentum extreme",           type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S7",  name: "ATRBreakout",                description: "1.5×ATR range break above/below prior bar",              type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S8",  name: "GapFill",                    description: "Gap >0.3% fill trade back to prior close",               type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S9",  name: "PCRContrarianOptions",       description: "PCR<0.7 → PE sell; PCR>1.3 → CE sell",                  type: "options",     timeframe: "15m", instruments: ["CE", "PE"] },

  // S10–S16 Scalping (s10_s16_scalping.go)
  { id: "S10", name: "HighFreqScalp1mORB",         description: "1-min ORB in 09:15–09:30 window",                       type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S11", name: "VWAPCrossScalp",             description: "Price crosses VWAP with volume surge >1.5×",            type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S12", name: "ATRMicroScalp",              description: "0.5×ATR breakout within 10:00–11:30 window",            type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S13", name: "TickMomentumScalp",          description: "3-bar momentum with volume confirmation",                type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S14", name: "BidAskImbalanceScalp",       description: "OI change imbalance >8% triggers CE/PE entry",          type: "scalping",    timeframe: "1m",  instruments: ["CE", "PE"] },
  { id: "S15", name: "SpreadCaptureScalp",         description: "ATM options spread capture on low-vol sessions",         type: "scalping",    timeframe: "5m",  instruments: ["CE", "PE"] },
  { id: "S16", name: "VIXSpikeFadeScalp",          description: "VIX spike >18 fade: sell premium via strangle",         type: "scalping",    timeframe: "5m",  instruments: ["CE", "PE"] },

  // S17–S22 Intraday advanced (s17_s22_intraday.go)
  { id: "S17", name: "PDIMDICrossover",            description: "DI+/DI- cross with ADX trend filter",                   type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S18", name: "IntradayMomentumRotation",   description: "Session rotation: 09:30–11:00 trend, 13:00 reversal",   type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S19", name: "OptionPremiumDecay",         description: "Theta decay play: sell ATM straddle at 10:00",          type: "options",     timeframe: "1h",  instruments: ["CE", "PE"] },
  { id: "S20", name: "NiftyBankNiftySpread",       description: "Spread divergence > 2σ mean-reversion",                 type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S21", name: "IntradayGammaScalp",         description: "High-gamma ATM options scalp around news",              type: "options",     timeframe: "5m",  instruments: ["CE", "PE"] },
  { id: "S22", name: "VWAPBounceOptions",          description: "VWAP bounce + OI spike → directional CE/PE",            type: "options",     timeframe: "5m",  instruments: ["CE", "PE"] },

  // S23–S29 Swing (s23_s29_swing.go)
  { id: "S23", name: "MultiDayBreakout",           description: "20-day channel breakout on daily closes",               type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S24", name: "WeeklyTrendFollowing",       description: "EMA50 slope weekly trend with ADX>20",                  type: "swing",       timeframe: "1w",  instruments: ["FUTURE"] },
  { id: "S25", name: "SwingHighLowCapture",        description: "Prior day H/L breakout with volume confirmation",       type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S26", name: "PivotPointRebound",          description: "Daily PP/S1/R1 rebound with RSI extreme",               type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S27", name: "EMA50Retest",               description: "Price retests EMA50 after breakout, ADX filter",        type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S28", name: "VolatilityBreakoutSwing",    description: "BB width expansion after 5-day squeeze",                type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S29", name: "PositionalOITrend",          description: "Cumulative OI buildup over 3 days → trend follow",      type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },

  // S30–S36 Advanced scalping (s30_s36_advanced_scalping.go)
  { id: "S30", name: "SuperTrendScalper",          description: "ATR(7)×3 SuperTrend band crossover + volume >1.5×avg",  type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S31", name: "VWAPBandBounce",             description: "±1.5σ VWAP band with RSI divergence",                   type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S32", name: "Opening15minORBFutures",     description: "15-min ORB with 1.5×ATR target",                        type: "scalping",    timeframe: "15m", instruments: ["FUTURE"] },
  { id: "S33", name: "TickVelocityScalp",          description: "1-min velocity z-score >2σ momentum burst",             type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S34", name: "DeltaWeightedOptionsScalp",  description: "PCR<0.8→CE / PCR>1.2→PE + OI change >5%",              type: "scalping",    timeframe: "1m",  instruments: ["CE", "PE"] },
  { id: "S35", name: "EMA921ZeroLagScalp",         description: "EMA9/EMA21 zero-lag crossover, ADX>25, SL=0.3%",       type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },
  { id: "S36", name: "ATRChannelBreakoutScalp",    description: "20-bar close channel ±1×ATR breakout, volume >1.5×",   type: "scalping",    timeframe: "1m",  instruments: ["FUTURE"] },

  // S37–S43 Advanced intraday (s37_s43_intraday_advanced.go)
  { id: "S37", name: "OpeningGapStrategy",         description: "Gap >0.5% direction by VIX<16+PCR vs fade",            type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S38", name: "VWAPMultiTouchBreakout",     description: "≥3 VWAP touches within 0.3×ATR then breakout",         type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S39", name: "IntradayFibonacciRetracement", description: "38.2–61.8% fib from first 30-min swing",             type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S40", name: "StochasticRSIDivergence",    description: "StochRSI<0.2 bull-div / >0.8 bear-div, ADX<20",        type: "intraday",    timeframe: "15m", instruments: ["CE", "PE"] },
  { id: "S41", name: "TimeOfDayMomentum",          description: "10:15–10:45 and 14:00–14:30 momentum windows",         type: "intraday",    timeframe: "5m",  instruments: ["FUTURE"] },
  { id: "S42", name: "IntradayOIReversal",         description: "PE OI drop >10% → CE; CE OI drop >10% → PE",           type: "intraday",    timeframe: "5m",  instruments: ["CE", "PE"] },
  { id: "S43", name: "CPRPivotBreakout",           description: "CPR=(H+L+C)/3 of prior session, TC/BC breakout",       type: "intraday",    timeframe: "15m", instruments: ["FUTURE"] },

  // S44–S47 Advanced swing (s44_s47_swing_advanced.go)
  { id: "S44", name: "WeeklyOptionsMomentum",      description: "Monday EMA50 direction → CE/PE weekly options",         type: "swing",       timeframe: "1w",  instruments: ["CE", "PE"] },
  { id: "S45", name: "PositionalBreakoutSwing",    description: "20-day channel + EMA50 slope breakout",                 type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S46", name: "MeanReversionSwing",         description: "Price z-score >2σ from 20-day SMA + RSI extreme",      type: "swing",       timeframe: "1d",  instruments: ["FUTURE"] },
  { id: "S47", name: "EarningsEventStrangle",      description: "Event risk + VIX<22 → ATM STRANGLE long",              type: "swing",       timeframe: "1d",  instruments: ["STRANGLE"] },

  // S48–S50 Index options (s48_s50_index_options.go)
  { id: "S48", name: "BankNiftyOptionsStraddle",   description: "Wed/Thu expiry 09:20 VIX<18 short STRANGLE",           type: "index_options", timeframe: "1d", instruments: ["STRANGLE"] },
  { id: "S49", name: "NiftyIronCondor",            description: "Monday 100-pt OTM short + 150-pt hedge IRON_CONDOR",   type: "index_options", timeframe: "1w", instruments: ["IRON_CONDOR"] },
  { id: "S50", name: "NiftyATMCalendarSpread",     description: "Monday next-week vs this-week ATM calendar spread",    type: "index_options", timeframe: "1w", instruments: ["STRANGLE"] },
];

export const STRATEGY_MAP: Record<string, StrategyMeta> = Object.fromEntries(
  STRATEGIES.map((s) => [s.id, s])
);

export const DATA_SOURCES = ["Synthetic", "SyntheticMultiYear", "Kite", "NSE"] as const;
export type DataSource = (typeof DATA_SOURCES)[number];

export const OUTPUT_FORMATS = ["json", "csv", "both"] as const;
export type OutputFormat = (typeof OUTPUT_FORMATS)[number];

export const DEFAULT_BACKTEST_CONFIG = {
  years: 1,
  capital: 10_000_000,
  instruments: "NIFTY50,BANKNIFTY",
  data_source: "Synthetic" as DataSource,
  strategies: [] as string[],
  max_concurrent: 0,
} as const;
