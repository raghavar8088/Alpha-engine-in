"use client";

// The margin account of an Intraday Stocks paper book (2026-11-16): the owner asked for the module's
// accounts to trade with the 5x leverage an Indian broker gives on intraday equity. The account's own
// capital is unchanged; buying power is leverage x capital; each position blocks value / leverage as
// margin. P&L is the price move on the shares held - never a multiplied figure. Shared by the Live
// Intraday, Top 10, A Grade and Patterns paper books and the Premium paper desk, so they all state the
// same six numbers. It carries its own styles: a parent's <style jsx> does not reach a child component.

export type MarginFigures = {
  capital?: number | null;
  leverage?: number | null;
  buying_power?: number | null;
  margin_used?: number | null;
  available_margin?: number | null;
  available_buying_power?: number | null;
  exposure?: number | null;
  open_positions?: number | null;
};

const rupees = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("en-IN");

export default function MarginTiles({ m, eligibility }: { m: MarginFigures | null | undefined; eligibility?: string }) {
  if (!m || m.leverage == null) return null;
  const lev = m.leverage;
  const used = m.margin_used ?? 0;
  const bp = m.buying_power ?? 0;
  const exposurePct = bp > 0 ? ((m.exposure ?? 0) / bp) * 100 : 0;
  const marginPct = lev > 0 ? Math.round(100 / lev) : 100;
  return (
    <div className="mt-tiles" role="group" aria-label="Margin account">
      <div className="mt-tile">
        <div className="mt-label">Capital</div>
        <div className="mt-value">₹{rupees(m.capital)}</div>
        <div className="mt-sub">the account&apos;s own money, unchanged by leverage</div>
      </div>
      <div className="mt-tile">
        <div className="mt-label">Leverage</div>
        <div className="mt-value">{lev.toFixed(lev % 1 ? 1 : 0)}×</div>
        <div className="mt-sub">{eligibility ?? `intraday (MIS) equity · ${marginPct}% margin per position`}</div>
      </div>
      <div className="mt-tile">
        <div className="mt-label">Buying power</div>
        <div className="mt-value">₹{rupees(m.buying_power)}</div>
        <div className="mt-sub">{lev}× capital · ₹{rupees(m.available_buying_power)} available now</div>
      </div>
      <div className="mt-tile">
        <div className="mt-label">Margin used</div>
        <div className="mt-value">₹{rupees(used)}</div>
        <div className="mt-sub">blocked by {m.open_positions ?? 0} open position{(m.open_positions ?? 0) === 1 ? "" : "s"}</div>
      </div>
      <div className="mt-tile">
        <div className="mt-label">Available margin</div>
        <div className={`mt-value${(m.available_margin ?? 0) < 0 ? " mt-neg" : ""}`}>₹{rupees(m.available_margin)}</div>
        <div className="mt-sub">capital + realised P&amp;L − margin used</div>
      </div>
      <div className="mt-tile">
        <div className="mt-label">Exposure</div>
        <div className="mt-value">₹{rupees(m.exposure)}</div>
        <div className="mt-sub">value of open positions · {exposurePct.toFixed(0)}% of buying power</div>
      </div>
      <style jsx>{`
        .mt-tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
        .mt-tile { padding: 12px 14px; border-radius: 10px; background: var(--panel); border: 1px solid var(--panel-border); min-width: 0; }
        .mt-label { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .mt-value { margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 16px; font-weight: 600; }
        .mt-value.mt-neg { color: var(--loss, #dc2626); }
        .mt-sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
      `}</style>
    </div>
  );
}
