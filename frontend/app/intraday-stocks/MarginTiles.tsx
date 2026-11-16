"use client";

// The margin account of an Intraday Stocks paper book (2026-11-16): the owner asked for the module's
// accounts to trade with the 5x leverage an Indian broker gives on intraday equity. The account's own
// capital is unchanged; buying power is leverage x capital; each position blocks value / leverage as
// margin. P&L is the price move on the shares held - never a multiplied figure. Shared by the Live
// Intraday, Top 10, A Grade and Patterns paper books so they all state the same six numbers.

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
    <div className="tiles">
      <div className="tile">
        <div className="tile-label">Capital</div>
        <div className="tile-value">₹{rupees(m.capital)}</div>
        <div className="tile-sub">the account&apos;s own money, unchanged by leverage</div>
      </div>
      <div className="tile">
        <div className="tile-label">Leverage</div>
        <div className="tile-value">{lev.toFixed(lev % 1 ? 1 : 0)}×</div>
        <div className="tile-sub">{eligibility ?? `intraday (MIS) equity · ${marginPct}% margin per position`}</div>
      </div>
      <div className="tile">
        <div className="tile-label">Buying power</div>
        <div className="tile-value">₹{rupees(m.buying_power)}</div>
        <div className="tile-sub">{lev}× capital · ₹{rupees(m.available_buying_power)} available now</div>
      </div>
      <div className="tile">
        <div className="tile-label">Margin used</div>
        <div className="tile-value">₹{rupees(used)}</div>
        <div className="tile-sub">blocked by {m.open_positions ?? 0} open position{(m.open_positions ?? 0) === 1 ? "" : "s"}</div>
      </div>
      <div className="tile">
        <div className="tile-label">Available margin</div>
        <div className={`tile-value ${(m.available_margin ?? 0) < 0 ? "loss" : ""}`}>₹{rupees(m.available_margin)}</div>
        <div className="tile-sub">capital + realised P&amp;L − margin used</div>
      </div>
      <div className="tile">
        <div className="tile-label">Exposure</div>
        <div className="tile-value">₹{rupees(m.exposure)}</div>
        <div className="tile-sub">value of open positions · {exposurePct.toFixed(0)}% of buying power</div>
      </div>
    </div>
  );
}
