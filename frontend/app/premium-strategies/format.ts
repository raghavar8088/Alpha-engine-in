// Number and date formats shared by the Premium Strategies page and its paper desk.

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const day = (iso: string) => `${parseInt(iso.slice(8, 10), 10)} ${MONTHS[parseInt(iso.slice(5, 7), 10) - 1]}`;
export const sign = (x: number) => (x > 0 ? "+" : x < 0 ? "−" : "");
export const pct = (x: number | null | undefined, d = 2) => (x == null ? "—" : `${sign(x)}${Math.abs(x).toFixed(d)}%`);
export const num = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${sign(x)}${Math.abs(x).toFixed(d)}`);
export const tone = (x: number | null | undefined) => (x == null || x === 0 ? "" : x > 0 ? "ps-pos" : "ps-neg");

export function inr(n: number): string {
  // Indian digit grouping (1,24,138), done by hand so server and browser render the same text.
  const s = Math.round(Math.abs(n)).toString();
  if (s.length <= 3) return `${sign(n)}₹${s}`;
  let rest = s.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${sign(n)}₹${parts.join(",")},${s.slice(-3)}`;
}

/** A balance rather than a gain: no sign unless it is negative. */
export const rupees = (n: number) => (n < 0 ? inr(n) : inr(n).replace("+", ""));

/** A price with as many decimals as its size needs (EUR/USD 1.08345, Nifty 25,123.45). */
export function price(x: number | null | undefined): string {
  if (x == null) return "—";
  const a = Math.abs(x);
  return x.toLocaleString("en-US", { minimumFractionDigits: a < 10 ? 5 : 2, maximumFractionDigits: a < 10 ? 5 : 2 });
}

/** Epoch seconds as "9 Nov, 09:45" in Indian time, whatever the viewer's clock says. */
export function istTime(t: number | null | undefined): string {
  if (t == null) return "—";
  const d = new Date((t + 19800) * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${hh}:${mm}`;
}

export function ago(iso: string | null | undefined, now: number): string {
  if (!iso) return "not yet";
  const s = iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`;
  const mins = Math.max(0, Math.round((now - Date.parse(s)) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
