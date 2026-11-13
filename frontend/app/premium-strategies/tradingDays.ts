// Capital, total return and per-trading-day averages for the Premium Strategies leaderboards (13 Nov 2026).
//
// TRADING DAYS are the market's sessions a strategy has been live for since it STARTED trading, whether or not it traded
// in them: a session counts once it has opened, if the strategy started before it closed. Each market keeps its own
// calendar:
//   NSE (Nifty, Bank Nifty, NSE stocks)  09:15-15:30 IST, weekdays minus NSE's holidays
//   US (Nasdaq 100, S&P 500, Apple)      09:30-16:00 New York time, weekdays minus the NYSE/Nasdaq full-day closures
//   gold (Delta XAUTUSD), forex          each Indian weekday: these strategies follow the gold and forex week, as tested
//   crypto (Bitcoin, Ether)              each Indian calendar day
// The desk trades only bars from a book's start on, so a book that started after NSE's 15:30 close begins with the next
// session, and one that started during a US session has that session. An account on several markets counts a date once
// if any of its markets had a session on it (each from its own start); a US session counts on its New York date.
//
// STARTS mirror premium-paper-service (cycle.py _yc_start / _btc_start, segments.py _start_of, settings.py): the 11-,
// 20-channel and shortlist books from their study's start; bitcoin books of the Crypto playlist at btc_start and of
// Sniper headshot at sh_start; every other book at paper_start (an Indian date: its midnight). The desk publishes
// paper_start, btc_start, sh_start and yc2_start in its status; the 11-channel start is settings.PREMIUM_YC_START, and
// each shortlist strategy carries its own start in shortlistData.
//
// The figures are NET of brokerage, exchange fees, taxes and slippage, and INCLUDE open positions marked to the last bar.
// The daily averages are arithmetic (total / days), not compounded.
import { SL } from "./shortlistData";

// NSE closures on weekdays, 2026 - a copy of shared/tradingai_shared/nse_calendar.py NSE_HOLIDAYS, the list every
// backend service reads. Add the next year's circular there and here.
const NSE_HOLIDAYS = new Set([
  "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
  "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
]);
// NYSE / Nasdaq full-day closures, 2026 (an early close is still a trading day).
const US_HOLIDAYS = new Set([
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
  "2026-11-26", "2026-12-25",
]);
const YC_START = "2026-11-09T10:00:00Z";      // settings.PREMIUM_YC_START: the 11 YouTube channels
const SL_START = new Map(SL.map((s) => [s.id, s.paperStart]));

export type Cal = "nse" | "us" | "weekdays" | "crypto";
export type StartStatus = { paper_start?: string; btc_start?: string; sh_start?: string; yc2_start?: string };

/** The calendar a market label (as the desk shows it) trades on; null for a market this page does not know. */
export function calendarOf(market: string): Cal | null {
  const m = market.toLowerCase();
  if (/bitcoin|ether|btc|eth/.test(m)) return "crypto";
  if (/^(nifty|bank nifty|nse)/.test(m)) return "nse";
  if (/nasdaq|s&p|apple|dow/.test(m)) return "us";
  if (/gold|silver|eur|gbp|jpy|usd/.test(m)) return "weekdays";
  return null;
}

function trades(cal: Cal, iso: string): boolean {
  if (cal === "crypto") return true;
  const dow = new Date(`${iso}T00:00:00Z`).getUTCDay();
  if (dow === 0 || dow === 6) return false;
  if (cal === "nse") return !NSE_HOLIDAYS.has(iso);
  if (cal === "us") return !US_HOLIDAYS.has(iso);
  return true;
}

/** When one book (account x market) started trading, as the desk runs it; null when unknown. */
export function startOf(source: string, id: string, market: string, status: StartStatus | undefined): string | null {
  if (source === "youtube_channels11") return YC_START;
  if (source === "youtube_channels20") return status?.yc2_start ?? null;
  if (source === "youtube_shortlist") return SL_START.get(id) ?? null;
  if (calendarOf(market) === "crypto") return (source === "sniper_headshot" ? status?.sh_start : status?.btc_start) ?? null;
  return status?.paper_start ?? null;
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const isoOf = (ms: number): string => new Date(ms).toISOString().slice(0, 10);       // an instant's UTC date
const nextDay = (iso: string): string => isoOf(Date.parse(`${iso}T00:00:00Z`) + DAY);

/** The n-th Sunday of a month (1-12) as a date. */
function nthSunday(year: number, month: number, n: number): string {
  const first = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  return isoOf(Date.UTC(year, month - 1, 1 + ((7 - first) % 7) + 7 * (n - 1)));
}

/** Hours New York is behind UTC on a date: 4 in US daylight time (second Sunday of March to first Sunday of November), else 5. */
function nyBehind(iso: string): number {
  const y = Number(iso.slice(0, 4));
  return iso >= nthSunday(y, 3, 2) && iso < nthSunday(y, 11, 1) ? 4 : 5;
}

/** A market's session on a date as [open, close) in epoch ms; null when it does not trade that day. */
function session(cal: Cal, iso: string): [number, number] | null {
  if (!trades(cal, iso)) return null;
  const utc0 = Date.parse(`${iso}T00:00:00Z`);
  if (cal === "nse") return [utc0 + 3.75 * HOUR, utc0 + 10 * HOUR];                     // 09:15-15:30 IST
  if (cal === "us") {
    const behind = nyBehind(iso);
    return [utc0 + (9.5 + behind) * HOUR, utc0 + (16 + behind) * HOUR];                  // 09:30-16:00 New York
  }
  return [utc0 - 5.5 * HOUR, utc0 + 18.5 * HOUR];                                       // the Indian calendar day
}

/** A start as an instant; a bare date is that Indian date's midnight (the desk's paper_start). */
const startAt = (start: string): number =>
  Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(start) ? `${start}T00:00:00+05:30` : start);

/** Trading days a strategy has been live for, a date counted once across its markets. null when none of its books has
 *  started (or its market or start is unknown); 0 when it started but none of its markets has had a session since. */
export function tradingDays(books: { start: string | null; market: string }[], now = Date.now()): number | null {
  const live = books
    .map((b) => ({ cal: calendarOf(b.market), at: b.start ? startAt(b.start) : NaN }))
    .filter((b): b is { cal: Cal; at: number } => b.cal !== null && Number.isFinite(b.at) && b.at <= now);
  if (!live.length) return null;
  // every date from the day before the first start (an Indian day begins on the previous UTC date) to the day after
  // now; the session test decides which count. The guard caps a broken start at about eleven years.
  const last = isoOf(now + DAY);
  let n = 0;
  for (let d = isoOf(Math.min(...live.map((b) => b.at)) - DAY), guard = 0; d <= last && guard < 4000; d = nextDay(d), guard++) {
    if (live.some((b) => {
      const s = session(b.cal, d);
      return s !== null && s[0] <= now && s[1] > b.at;
    })) n++;
  }
  return n;
}

/** Total return (% of capital), and the arithmetic daily averages over the trading days. Null where not computable. */
export function dailyFigures(net: number | null | undefined, capital: number | null | undefined, days: number | null) {
  const ret = net != null && capital ? (net / capital) * 100 : null;
  return {
    ret,
    days,
    avgPct: ret != null && days ? ret / days : null,
    avgRs: net != null && days ? net / days : null,
  };
}

export const DAYS_NOTE =
  "Capital is the strategy's own paper account. Total return and the daily averages are after brokerage, exchange fees, " +
  "taxes and slippage, and include open positions marked to the last bar (unrealised P&L). Trading days are the " +
  "market's sessions since the strategy started, whether or not it traded in them: a session counts once it has opened, " +
  "if the strategy started before it closed, so a start after NSE's 15:30 close counts from the next session. Weekends " +
  "and exchange holidays are left out (NSE's calendar for Indian markets, the US exchanges' for Nasdaq, S&P 500 and " +
  "Apple, weekdays for gold and forex), and crypto counts every day. Average daily return is the total return divided " +
  "by those days, not compounded. N/A means the strategy has not started, its capital is not known, or it has had no " +
  "session yet.";
