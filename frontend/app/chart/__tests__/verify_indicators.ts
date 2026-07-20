import { sma, ema, rsi, macd, bollinger, vwap, heikinAshi, supertrend, referenceLevels, valueAt, Bar } from "../indicators";

function bar(time: number, o: number, h: number, l: number, c: number, v = 1000): Bar {
  return { time, open: o, high: h, low: l, close: c, volume: v };
}

let failures = 0;
function check(name: string, got: number | null, want: number, tol = 1e-6) {
  const ok = got !== null && Math.abs(got - want) < tol;
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}: got=${got} want=${want}`);
}

// --- SMA: closes 1..20, SMA(20) = mean(1..20) = 10.5 -----------------------
const linear: Bar[] = [];
for (let i = 1; i <= 20; i++) linear.push(bar(i * 60, i, i, i, i));
const s = sma(linear, 20);
check("SMA(20) of closes 1..20", s.length === 1 ? s[0].value : null, 10.5);

// SMA(5) over closes 1..20, last value = mean(16..20) = 18
const s5 = sma(linear, 5);
check("SMA(5) last of closes 1..20", s5[s5.length - 1].value, 18);
check("SMA(5) count", s5.length, 16);

// --- EMA: constant series must equal the constant ---------------------------
const flat: Bar[] = [];
for (let i = 0; i < 30; i++) flat.push(bar(i * 60, 50, 50, 50, 50));
const e = ema(flat, 10);
check("EMA(10) of constant 50", e[e.length - 1].value, 50);

// EMA(3) hand-computed on closes [1,2,3,4,5]:
// seed = SMA(1,2,3) = 2 ; k = 0.5
// i=3: 4*0.5 + 2*0.5 = 3 ; i=4: 5*0.5 + 3*0.5 = 4
const e3src: Bar[] = [1, 2, 3, 4, 5].map((c, i) => bar(i * 60, c, c, c, c));
const e3 = ema(e3src, 3);
check("EMA(3) seed", e3[0].value, 2);
check("EMA(3) [3]", e3[1].value, 3);
check("EMA(3) [4]", e3[2].value, 4);

// --- RSI: monotonically rising series => 100 --------------------------------
const rising: Bar[] = [];
for (let i = 0; i < 40; i++) rising.push(bar(i * 60, i, i, i, i));
const r = rsi(rising, 14);
check("RSI(14) of monotonic rise", r[r.length - 1].value, 100);

// falling => 0
const falling: Bar[] = [];
for (let i = 0; i < 40; i++) falling.push(bar(i * 60, 100 - i, 100 - i, 100 - i, 100 - i));
const rf = rsi(falling, 14);
check("RSI(14) of monotonic fall", rf[rf.length - 1].value, 0);

// Alternating +1/-1: Wilder smoothing weights the most recent tick, so RSI sits
// just above 50 after an up-tick and symmetrically below it after a down-tick.
// (A simple-average RSI would give exactly 50 — this asymmetry is the signature
// that Wilder smoothing is actually being applied.)
const zig: Bar[] = [];
for (let i = 0; i < 60; i++) { const c = 100 + (i % 2); zig.push(bar(i * 60, c, c, c, c)); }
const rz = rsi(zig, 14);
const afterUp = rz[rz.length - 1].value;   // bar 59 closed at 101, up from 100
const afterDown = rz[rz.length - 2].value; // bar 58 closed at 100, down from 101
check("RSI(14) zigzag after up-tick", afterUp, 51.92, 0.05);
// Near-symmetric, not exactly: 60 bars is short of full Wilder convergence.
check("RSI(14) zigzag after down-tick", afterDown, 100 - afterUp, 0.25);
console.log(`${afterUp > 50 && afterDown < 50 ? "PASS" : "FAIL"}  RSI zigzag straddles 50 symmetrically`);
if (!(afterUp > 50 && afterDown < 50)) failures++;

// --- Bollinger: constant series => zero-width bands at the mean -------------
const b = bollinger(flat, 20, 2);
check("BB middle on constant", b.middle[b.middle.length - 1].value, 50);
check("BB upper on constant (sd=0)", b.upper[b.upper.length - 1].value, 50);

// known sd: closes 1..20, SMA=10.5, population sd = sqrt(33.25) = 5.766281...
const bl = bollinger(linear, 20, 2);
check("BB middle 1..20", bl.middle[0].value, 10.5);
check("BB upper 1..20", bl.upper[0].value, 10.5 + 2 * Math.sqrt(33.25), 1e-9);

// --- MACD: constant series => macd and signal both 0 ------------------------
const longFlat: Bar[] = [];
for (let i = 0; i < 80; i++) longFlat.push(bar(i * 60, 50, 50, 50, 50));
const m = macd(longFlat);
check("MACD line on constant", m.macd[m.macd.length - 1].value, 0);
check("MACD signal on constant", m.signal[m.signal.length - 1].value, 0);
check("MACD histogram on constant", m.histogram[m.histogram.length - 1].value, 0);
// alignment: signal and histogram must share timestamps
const aligned = m.signal.every((p, i) => p.time === m.histogram[i].time);
console.log(`${aligned ? "PASS" : "FAIL"}  MACD signal/histogram timestamps aligned`);
if (!aligned) failures++;

// --- VWAP: single session, hand-computed -----------------------------------
// two bars, typical prices 10 and 20, volumes 100 and 300
// cumulative VWAP after bar2 = (10*100 + 20*300) / 400 = 17.5
const vsrc: Bar[] = [bar(0, 10, 10, 10, 10, 100), bar(60, 20, 20, 20, 20, 300)];
const vw = vwap(vsrc);
check("VWAP bar1", vw[0].value, 10);
check("VWAP bar2 cumulative", vw[1].value, 17.5);

// VWAP resets across IST session boundary (IST midnight = 18:30 UTC prev day)
const dayTwo = 86400; // next UTC day -> different IST bucket than t=0? verify reset happens
const vsrc2: Bar[] = [bar(0, 10, 10, 10, 10, 100), bar(dayTwo, 20, 20, 20, 20, 300)];
const vw2 = vwap(vsrc2);
check("VWAP resets on new session", vw2[1].value, 20);

// --- Heikin-Ashi: hand-computed first two bars -----------------------------
// bar0: o=10 h=14 l=9 c=12 -> haClose=(10+14+9+12)/4=11.25 ; haOpen=(10+12)/2=11
// bar1: o=12 h=16 l=11 c=15 -> haClose=(12+16+11+15)/4=13.5 ; haOpen=(11+11.25)/2=11.125
const ha = heikinAshi([bar(0, 10, 14, 9, 12), bar(60, 12, 16, 11, 15)]);
check("HA[0] close", ha[0].close, 11.25);
check("HA[0] open", ha[0].open, 11);
check("HA[0] high", ha[0].high, 14);
check("HA[0] low", ha[0].low, 9);
check("HA[1] close", ha[1].close, 13.5);
check("HA[1] open", ha[1].open, 11.125);
check("HA[1] low", ha[1].low, 11);

// --- Supertrend: strong uptrend must end bullish, band below price ---------
const trendUp: Bar[] = [];
for (let i = 0; i < 60; i++) { const c = 100 + i * 2; trendUp.push(bar(i * 60, c - 1, c + 1, c - 2, c)); }
const st = supertrend(trendUp, 10, 3);
const lastDir = st.direction[st.direction.length - 1];
console.log(`${lastDir === 1 ? "PASS" : "FAIL"}  Supertrend direction in uptrend: ${lastDir}`);
if (lastDir !== 1) failures++;
const lastUp = st.up[st.up.length - 1];
const belowPrice = lastUp && lastUp.value < trendUp[trendUp.length - 1].close;
console.log(`${belowPrice ? "PASS" : "FAIL"}  Supertrend band sits below price in uptrend`);
if (!belowPrice) failures++;

const trendDown: Bar[] = [];
for (let i = 0; i < 60; i++) { const c = 300 - i * 2; trendDown.push(bar(i * 60, c + 1, c + 2, c - 1, c)); }
const st2 = supertrend(trendDown, 10, 3);
const lastDir2 = st2.direction[st2.direction.length - 1];
console.log(`${lastDir2 === -1 ? "PASS" : "FAIL"}  Supertrend direction in downtrend: ${lastDir2}`);
if (lastDir2 !== -1) failures++;

// --- reference levels -------------------------------------------------------
// Build two IST sessions of 1m bars. IST day boundary = 18:30 UTC.
// Use 04:00 UTC (09:30 IST) as session start.
const day1Start = 4 * 3600;
const day2Start = day1Start + 86400;
const refBars: Bar[] = [];
for (let i = 0; i < 30; i++) refBars.push(bar(day1Start + i * 60, 100, 105, 95, 100));
for (let i = 0; i < 30; i++) {
  const h = 200 + i;
  refBars.push(bar(day2Start + i * 60, 200, h, 190 - i, 200));
}
const lvl = referenceLevels(refBars, true, 15);
check("prevClose = last close of prior session", lvl.previousClose, 100);
check("dayHigh of current session", lvl.dayHigh, 229);
check("dayLow of current session", lvl.dayLow, 161);
// opening range = first 15 minutes of session 2 => bars i=0..14 => high max(200..214)=214, low min(190..176)=176
check("openingRangeHigh (15m)", lvl.openingRangeHigh, 214);
check("openingRangeLow (15m)", lvl.openingRangeLow, 176);

// daily mode: day high/low come from the final bar, OR undefined
const dailyLvl = referenceLevels([bar(0, 10, 20, 5, 15), bar(86400, 15, 25, 12, 22)], false);
check("daily prevClose", dailyLvl.previousClose, 15);
check("daily dayHigh", dailyLvl.dayHigh, 25);
check("daily dayLow", dailyLvl.dayLow, 12);
console.log(`${dailyLvl.openingRangeHigh === null ? "PASS" : "FAIL"}  daily openingRange is null`);
if (dailyLvl.openingRangeHigh !== null) failures++;

// --- valueAt: sparse series lookup -----------------------------------------
const sparse = [{ time: 100, value: 1 }, { time: 300, value: 3 }, { time: 500, value: 5 }];
check("valueAt exact", valueAt(sparse, 300), 3);
check("valueAt between (takes earlier)", valueAt(sparse, 400), 3);
check("valueAt after end", valueAt(sparse, 9999), 5);
console.log(`${valueAt(sparse, 50) === null ? "PASS" : "FAIL"}  valueAt before start is null`);
if (valueAt(sparse, 50) !== null) failures++;

// --- empty / short input must not throw ------------------------------------
try {
  sma([], 20); ema([], 20); rsi([], 14); macd([]); bollinger([], 20); vwap([]);
  heikinAshi([]); supertrend([], 10, 3); referenceLevels([], true);
  sma(linear.slice(0, 3), 20); rsi(linear.slice(0, 3), 14);
  console.log("PASS  empty/short inputs return empty without throwing");
} catch (err) {
  console.log("FAIL  empty/short inputs threw:", err);
  failures++;
}

console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
