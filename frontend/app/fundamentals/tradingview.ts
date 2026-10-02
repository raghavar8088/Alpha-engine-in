/** TradingView watchlist interop, shared by every list in Fundamental Rating.
 *
 * Two shapes, because TradingView takes lists in through two different doors:
 *
 *   * PASTE into a watchlist's "Add symbol" box: a flat comma-separated list. Section
 *     markers are not understood there, so the clipboard copy is always flat.
 *   * IMPORT a .txt file (watchlist menu -> Import list): TradingView's own export format,
 *     which is the same comma list with "###Section" entries inline. That is where grade
 *     sections survive, so sections go in the file only.
 *
 * Symbols are stored bare here ("BAJAJ-AUTO", "J&KBANK"). TradingView spells NSE tickers
 * with "&" and "-" turned into "_" (NSE:BAJAJ_AUTO, NSE:J_KBANK, NSE:M_M). Prefixing the bare
 * symbol with "NSE:" - which is what the Universe tab used to do - hands TradingView a ticker
 * it cannot find, and the import drops it silently. Every export goes through tvSymbol.
 */

/** A bare or prefixed symbol, as TradingView spells it. A numeric code is a BSE scrip. */
export function tvSymbol(raw: string): string {
  const s = (raw || "")
    .trim()
    .toUpperCase()
    .replace(/^(NSE|BSE|NSE_EQ|BSE_EQ)[:-]/, "")
    .replace(/\.(NS|BO)$/, "");
  if (/^\d+$/.test(s)) return `BSE:${s}`;
  return `NSE:${s.replace(/[&-]/g, "_")}`;
}

export interface TvItem {
  symbol: string;
  /** Section the symbol belongs in when exported with sections - a grade, a band, a list. */
  group?: string | null;
}

function dedupe(items: TvItem[]): TvItem[] {
  const seen = new Set<string>();
  const out: TvItem[] = [];
  for (const it of items) {
    const t = tvSymbol(it.symbol);
    if (!it.symbol || seen.has(t)) continue;
    seen.add(t);
    out.push(it);
  }
  return out;
}

/** Flat comma list - what TradingView's Add symbol box accepts on paste. */
export function tvFlat(items: TvItem[]): string {
  return dedupe(items).map((i) => tvSymbol(i.symbol)).join(",");
}

/** A section name TradingView will keep: no commas (they separate entries), no "#". */
function sectionName(s: string): string {
  return s.replace(/[,#]/g, " ").replace(/\s+/g, " ").trim() || "Other";
}

/** TradingView's .txt format with a "###Section" per group, groups in `order` first. */
export function tvSections(
  items: TvItem[],
  order: string[] = [],
  label: (g: string) => string = (g) => g,
): string {
  const groups = new Map<string, string[]>();
  for (const it of dedupe(items)) {
    const g = it.group || "other";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(tvSymbol(it.symbol));
  }
  const keys = [
    ...order.filter((g) => groups.has(g)),
    ...[...groups.keys()].filter((g) => !order.includes(g)),
  ];
  // One group is not worth a section header - it would just be the list's own name again.
  if (keys.length <= 1) return tvFlat(items);
  return keys
    .flatMap((g) => [`###${sectionName(label(g))}`, ...groups.get(g)!])
    .join(",");
}

export function groupCount(items: TvItem[]): number {
  return new Set(dedupe(items).map((i) => i.group || "other")).size;
}

/** A filename TradingView and every OS will accept. */
export function tvFilename(name: string): string {
  const base = (name || "watchlist").replace(/[^A-Za-z0-9 _.-]+/g, " ").replace(/\s+/g, " ").trim();
  return `${base || "watchlist"}.txt`;
}

export function downloadTxt(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "very-good" -> "Very good", "not-in-book" -> "Not in book". */
export function prettyGroup(g: string): string {
  const s = (g || "other").replace(/-/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
