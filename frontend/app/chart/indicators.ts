/** Pure technical-indicator maths for the Chart module.
 *
 * Every function here is a pure transform of the OHLCV series the `history`
 * endpoint already returns — nothing in this file makes a network call, so
 * toggling indicators costs zero extra Dhan quota. Series come back as sparse
 * point arrays (leading warm-up bars are simply omitted rather than emitted as
 * nulls), which is what lightweight-charts' `setData` expects.
 */

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: number;
  value: number;
}

const IST_OFFSET_SECONDS = 5.5 * 3600;

/** IST calendar-day bucket for a UTC epoch second — the session key used by
 * VWAP, day high/low and the opening range. */
export function sessionKey(time: number): number {
  return Math.floor((time + IST_OFFSET_SECONDS) / 86400);
}

// --- moving averages -------------------------------------------------------

export function sma(bars: Bar[], period: number): Point[] {
  if (period < 1 || bars.length < period) return [];
  const out: Point[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
  }
  return out;
}

/** Wilder-style seeding: the first EMA value is the SMA of the first `period`
 * closes, then the standard 2/(n+1) multiplier. Matches what TradingView and
 * most Indian-market screeners report, so spot-checks line up. */
export function ema(bars: Bar[], period: number): Point[] {
  if (period < 1 || bars.length < period) return [];
  const k = 2 / (period + 1);
  const out: Point[] = [];
  let seed = 0;
  for (let i = 0; i < period; i++) seed += bars[i].close;
  let prev = seed / period;
  out.push({ time: bars[period - 1].time, value: prev });
  for (let i = period; i < bars.length; i++) {
    prev = bars[i].close * k + prev * (1 - k);
    out.push({ time: bars[i].time, value: prev });
  }
  return out;
}

/** EMA over a bare number series, used internally by MACD. */
function emaValues(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

// --- VWAP ------------------------------------------------------------------

/** Session-anchored VWAP: cumulative typical-price × volume over volume, reset
 * at each new IST trading day. Only meaningful on intraday resolutions — on
 * daily/weekly bars every bar is its own session, so VWAP degenerates to the
 * typical price and the UI hides the toggle. */
export function vwap(bars: Bar[]): Point[] {
  const out: Point[] = [];
  let day = -1;
  let pv = 0;
  let vol = 0;
  for (const b of bars) {
    const key = sessionKey(b.time);
    if (key !== day) {
      day = key;
      pv = 0;
      vol = 0;
    }
    const typical = (b.high + b.low + b.close) / 3;
    pv += typical * b.volume;
    vol += b.volume;
    out.push({ time: b.time, value: vol > 0 ? pv / vol : typical });
  }
  return out;
}

// --- Bollinger Bands -------------------------------------------------------

export interface Bands {
  upper: Point[];
  middle: Point[];
  lower: Point[];
}

export function bollinger(bars: Bar[], period = 20, mult = 2): Bands {
  const upper: Point[] = [];
  const middle: Point[] = [];
  const lower: Point[] = [];
  if (bars.length < period) return { upper, middle, lower };
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
    const mean = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) variance += (bars[j].close - mean) ** 2;
    const sd = Math.sqrt(variance / period);
    const time = bars[i].time;
    upper.push({ time, value: mean + mult * sd });
    middle.push({ time, value: mean });
    lower.push({ time, value: mean - mult * sd });
  }
  return { upper, middle, lower };
}

// --- ATR / Supertrend ------------------------------------------------------

/** Wilder's ATR. Index-aligned with `bars`; entries before the seed are null. */
function atrValues(bars: Bar[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  if (bars.length <= period) return out;
  const tr: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    if (i === 0) {
      tr.push(bars[i].high - bars[i].low);
      continue;
    }
    const prevClose = bars[i - 1].close;
    tr.push(Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - prevClose), Math.abs(bars[i].low - prevClose)));
  }
  let seed = 0;
  for (let i = 1; i <= period; i++) seed += tr[i];
  let prev = seed / period;
  out[period] = prev;
  for (let i = period + 1; i < bars.length; i++) {
    prev = (prev * (period - 1) + tr[i]) / period;
    out[i] = prev;
  }
  return out;
}

export interface SupertrendResult {
  /** The band itself, split so the rising (support) and falling (resistance)
   * legs can be drawn in different colours without one connecting line jumping
   * across the price on every flip. */
  up: Point[];
  down: Point[];
  /** +1 while price is above the band (bullish), -1 below. */
  direction: number[];
}

export function supertrend(bars: Bar[], period = 10, mult = 3): SupertrendResult {
  const up: Point[] = [];
  const down: Point[] = [];
  const direction: number[] = new Array(bars.length).fill(0);
  const atr = atrValues(bars, period);
  if (bars.length <= period) return { up, down, direction };

  let finalUpper = 0;
  let finalLower = 0;
  let prevFinalUpper = 0;
  let prevFinalLower = 0;
  let trendUp = true;
  let started = false;

  for (let i = period; i < bars.length; i++) {
    const a = atr[i];
    if (a === null) continue;
    const mid = (bars[i].high + bars[i].low) / 2;
    const basicUpper = mid + mult * a;
    const basicLower = mid - mult * a;
    const prevClose = bars[i - 1].close;

    if (!started) {
      finalUpper = basicUpper;
      finalLower = basicLower;
      trendUp = bars[i].close >= basicLower;
      started = true;
    } else {
      finalUpper = basicUpper < prevFinalUpper || prevClose > prevFinalUpper ? basicUpper : prevFinalUpper;
      finalLower = basicLower > prevFinalLower || prevClose < prevFinalLower ? basicLower : prevFinalLower;
      if (trendUp) trendUp = bars[i].close >= finalLower;
      else trendUp = bars[i].close > finalUpper;
    }

    direction[i] = trendUp ? 1 : -1;
    const point = { time: bars[i].time, value: trendUp ? finalLower : finalUpper };
    if (trendUp) up.push(point);
    else down.push(point);

    prevFinalUpper = finalUpper;
    prevFinalLower = finalLower;
  }
  return { up, down, direction };
}

// --- RSI -------------------------------------------------------------------

/** Wilder's RSI (the standard 14-period smoothing, not a simple average). */
export function rsi(bars: Bar[], period = 14): Point[] {
  const out: Point[] = [];
  if (bars.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const change = bars[i].close - bars[i - 1].close;
    if (change >= 0) gain += change;
    else loss -= change;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  const toRsi = (g: number, l: number) => (l === 0 ? 100 : 100 - 100 / (1 + g / l));
  out.push({ time: bars[period].time, value: toRsi(avgGain, avgLoss) });
  for (let i = period + 1; i < bars.length; i++) {
    const change = bars[i].close - bars[i - 1].close;
    avgGain = (avgGain * (period - 1) + Math.max(change, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-change, 0)) / period;
    out.push({ time: bars[i].time, value: toRsi(avgGain, avgLoss) });
  }
  return out;
}

// --- MACD ------------------------------------------------------------------

export interface MacdResult {
  macd: Point[];
  signal: Point[];
  histogram: (Point & { color: string })[];
}

export function macd(bars: Bar[], fast = 12, slow = 26, signalPeriod = 9): MacdResult {
  const empty: MacdResult = { macd: [], signal: [], histogram: [] };
  if (bars.length < slow + signalPeriod) return empty;
  const closes = bars.map((b) => b.close);
  const fastEma = emaValues(closes, fast);
  const slowEma = emaValues(closes, slow);

  const macdLine: Point[] = [];
  const macdVals: number[] = [];
  const macdIdx: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    const f = fastEma[i];
    const s = slowEma[i];
    if (f === null || s === null) continue;
    macdLine.push({ time: bars[i].time, value: f - s });
    macdVals.push(f - s);
    macdIdx.push(i);
  }

  const signalVals = emaValues(macdVals, signalPeriod);
  const signal: Point[] = [];
  const histogram: (Point & { color: string })[] = [];
  for (let k = 0; k < macdVals.length; k++) {
    const s = signalVals[k];
    if (s === null) continue;
    const time = bars[macdIdx[k]].time;
    signal.push({ time, value: s });
    const diff = macdVals[k] - s;
    histogram.push({ time, value: diff, color: diff >= 0 ? "rgba(38,166,154,0.6)" : "rgba(239,83,80,0.6)" });
  }
  return { macd: macdLine, signal, histogram };
}

// --- Heikin-Ashi -----------------------------------------------------------

/** Heikin-Ashi transform. Returns bars in the same shape, volume carried
 * through unchanged.
 *
 * This is a *rendering* toggle only: the chart page deliberately keeps
 * computing indicators from the raw bars, so an RSI or VWAP reading here still
 * matches what any other screener reports for the same symbol. Feeding HA bars
 * into the indicators would double-smooth them and quietly disagree with every
 * other tool the user cross-checks against. */
export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i === 0 ? (b.open + b.close) / 2 : (out[i - 1].open + out[i - 1].close) / 2;
    out.push({
      time: b.time,
      open,
      high: Math.max(b.high, open, close),
      low: Math.min(b.low, open, close),
      close,
      volume: b.volume,
    });
  }
  return out;
}

// --- session reference levels ---------------------------------------------

export interface ReferenceLevels {
  previousClose: number | null;
  dayHigh: number | null;
  dayLow: number | null;
  openingRangeHigh: number | null;
  openingRangeLow: number | null;
}

/** Levels for the most recent session in the series.
 *
 * On intraday resolutions "session" means the last IST trading day present, and
 * the opening range is the first `openingRangeMinutes` of it. On D/W bars each
 * bar *is* a session, so day high/low come from the final bar and the opening
 * range is undefined (the UI hides those toggles). */
export function referenceLevels(bars: Bar[], intraday: boolean, openingRangeMinutes = 15): ReferenceLevels {
  const none: ReferenceLevels = {
    previousClose: null, dayHigh: null, dayLow: null, openingRangeHigh: null, openingRangeLow: null,
  };
  if (!bars.length) return none;

  if (!intraday) {
    const last = bars[bars.length - 1];
    return {
      previousClose: bars.length >= 2 ? bars[bars.length - 2].close : null,
      dayHigh: last.high,
      dayLow: last.low,
      openingRangeHigh: null,
      openingRangeLow: null,
    };
  }

  const lastKey = sessionKey(bars[bars.length - 1].time);
  let firstIdx = bars.length - 1;
  while (firstIdx > 0 && sessionKey(bars[firstIdx - 1].time) === lastKey) firstIdx--;

  const session = bars.slice(firstIdx);
  const previousClose = firstIdx > 0 ? bars[firstIdx - 1].close : null;
  const dayHigh = Math.max(...session.map((b) => b.high));
  const dayLow = Math.min(...session.map((b) => b.low));

  const orCutoff = session[0].time + openingRangeMinutes * 60;
  const orBars = session.filter((b) => b.time < orCutoff);
  const openingRangeHigh = orBars.length ? Math.max(...orBars.map((b) => b.high)) : null;
  const openingRangeLow = orBars.length ? Math.min(...orBars.map((b) => b.low)) : null;

  return { previousClose, dayHigh, dayLow, openingRangeHigh, openingRangeLow };
}

/** Nearest-at-or-before lookup used by the crosshair HUD: indicator series are
 * sparse (warm-up bars omitted), so a plain time-equality match misses. */
export function valueAt(points: Point[], time: number): number | null {
  let lo = 0;
  let hi = points.length - 1;
  let found: number | null = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].time <= time) {
      found = points[mid].value;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}
