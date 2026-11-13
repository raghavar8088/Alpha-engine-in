// Capital, total return and per-trading-day averages for the Premium Strategies leaderboards (13 Nov 2026).
//
// TRADING DAYS are market days since the strategy STARTED trading, counted in Indian dates, today included, whether or not
// it traded on them. Each market keeps its own calendar:
//   NSE (Nifty, Bank Nifty, NSE stocks)  weekdays minus NSE's holidays
//   US (Nasdaq 100, S&P 500, Apple)      weekdays minus the NYSE/Nasdaq full-day closures
//   gold (Delta XAUTUSD), forex          weekdays: these strategies follow the gold and forex week, as they were tested
//   crypto (Bitcoin, Ether)              every calendar day
// An account on several markets counts a day once if any of its markets traded that day (each from its own start).
//
// STARTS mirror premium-paper-service (cycle.py _yc_start / _btc_start, settings.py): the 11-, 20-channel and shortlist
// books from their study's start; bitcoin books of the Crypto playlist at btc_start and of Sniper headshot at sh_start;
// every other book at paper_start. The desk publishes paper_start, btc_start, sh_start and yc2_start in its status; the
// 11-channel start is settings.PREMIUM_YC_START, and each shortlist strategy carries its own start in shortlistData.
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

/** A start as an Indian date (a bare date stays as it is). */
const istDate = (start: string): string =>
  /^\d{4}-\d{2}-\d{2}$/.test(start) ? start : new Date(Date.parse(start) + 19_800_000).toISOString().slice(0, 10);
const nextDay = (iso: string): string => new Date(Date.parse(`${iso}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);

/** Trading days from each market's start to today (IST), a day counted once if any market traded; null if not started. */
export function tradingDays(books: { start: string | null; market: string }[], now = Date.now()): number | null {
  const today = new Date(now + 19_800_000).toISOString().slice(0, 10);
  const known = books
    .map((b) => ({ cal: calendarOf(b.market), from: b.start ? istDate(b.start) : null, at: b.start ? Date.parse(b.start) : NaN }))
    .filter((b): b is { cal: Cal; from: string; at: number } => b.cal !== null && b.from !== null)
    .filter((b) => !(b.at > now));                // a book that has not started yet adds no days
  if (!known.length) return null;
  let d = known.reduce((m, b) => (b.from < m ? b.from : m), known[0].from);
  let n = 0;
  for (let guard = 0; d <= today && guard < 4000; guard++, d = nextDay(d)) {
    if (known.some((b) => d >= b.from && trades(b.cal, d))) n++;
  }
  return n > 0 ? n : null;
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
  "taxes and slippage, and include open positions marked to the last bar (unrealised P&L). Trading days are market days " +
  "since the strategy started, today included, whether or not it traded: weekends and exchange holidays are left out " +
  "(NSE's calendar for Indian markets, the US exchanges' for Nasdaq, S&P 500 and Apple, weekdays for gold and forex), " +
  "and crypto counts every day. Average daily return is the total return divided by those days, not compounded; " +
  "N/A means the strategy has not started or its capital is not known.";
