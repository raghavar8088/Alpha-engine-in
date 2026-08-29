/**
 * Copying a symbol list to the clipboard, in the two formats that matter here.
 *
 * Extracted because this is now wanted on four tables and the fallback below is the part
 * that must not drift between them: `navigator.clipboard` is undefined on insecure
 * origins and can be refused outright by permissions policy, and a copy button that
 * silently does nothing looks broken rather than blocked.
 */

export type SymbolFormat = "tv" | "plain";

/** TradingView's watchlist import wants `NSE:AAA,NSE:BBB` with no spaces. That same
 *  string also feeds the All Time High watchlist, whose parser strips the prefix — so one
 *  format covers both destinations. */
export function formatSymbols(symbols: string[], fmt: SymbolFormat): string {
  return fmt === "tv"
    ? symbols.map((s) => `NSE:${s}`).join(",")
    : symbols.join(", ");
}

/** Returns true when the clipboard took it, false when the user got the prompt instead. */
export async function copySymbols(
  symbols: string[], fmt: SymbolFormat,
): Promise<boolean> {
  const text = formatSymbols(symbols, fmt);
  if (!text) return false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to the prompt
    }
  }
  window.prompt("Copy the list below (Ctrl/⌘ + C):", text);
  return false;
}
