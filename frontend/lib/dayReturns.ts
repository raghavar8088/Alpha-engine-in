// Trading-day columns for strategy tables (Gold Desk, 18 Nov 2026): days traded, days since the start, total return
// and that return per day traded. One set of definitions for every table that shows them, so no two tables can
// disagree on what "a day" or "the return" means. Each table renders its own <td>s (its scoped styles must reach
// them); these only compute and format.
//
//   Days traded   the days a strategy closed at least one trade on (IST dates) - the server counts them
//   Total days    the days since it started trading there, today counted; Delta's XAUTUSD trades every day
//   Total return  realised + open P&L as a share of the strategy's own capital
//   Avg / day     total return / days traded ("—" until it has traded a day)

const DAY_MS = 86_400_000;

/** The IST calendar date of a moment, as a UTC midnight timestamp (so two of them subtract to whole days). */
function istMidnight(d: Date): number {
  return Date.parse(`${d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })}T00:00:00Z`);
}

/** IST calendar days from the day `startIso` falls on to today, both counted. null when there is no start. */
export function istDaysSince(startIso: string | null | undefined, now: Date = new Date()): number | null {
  if (!startIso) return null;
  const t = new Date(startIso);
  if (Number.isNaN(t.getTime())) return null;
  const n = Math.round((istMidnight(now) - istMidnight(t)) / DAY_MS) + 1;
  return n >= 1 ? n : null;
}

/** Total return as a percent of `capital`: realised + open P&L. null when either is unknown. */
export function totalReturnPct(realised: number | null | undefined, open: number | null | undefined,
                               capital: number | null | undefined): number | null {
  if (realised === null || realised === undefined || !capital) return null;
  return ((realised + (open ?? 0)) / capital) * 100;
}

/** The total return spread over the days the strategy actually traded; null before its first day. */
export function perDayTraded(returnPct: number | null | undefined, daysTraded: number | null | undefined): number | null {
  if (returnPct === null || returnPct === undefined || !daysTraded) return null;
  return returnPct / daysTraded;
}

/** "+1.23%", "−0.045%" (a third decimal under 0.1%), "—" when unknown. Plain text, so the page-wide table sort can
 *  read it as a number. */
export function pctCell(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const dp = a > 0 && a < 0.1 ? 3 : 2;
  const s = a.toFixed(dp);
  return `${v > 0 && Number(s) !== 0 ? "+" : v < 0 && Number(s) !== 0 ? "−" : ""}${s}%`;
}

/** A day count as cell text: "—" when unknown. */
export function dayCell(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : String(v);
}

export const toneOf = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");

/** Header tooltips, shared so every table explains its columns the same way. */
export const DAY_COL_TITLES = {
  traded: "Days it closed at least one trade on (IST dates)",
  total: "Days since it started trading here, today counted (Delta's XAUTUSD trades every day)",
  ret: "Total return: realised + open P&L as a share of the strategy's own capital",
  avg: "Average return per day traded: total return ÷ days traded",
};
