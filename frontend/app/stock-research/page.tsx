"use client";

import { useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import {
  CAP_BUCKETS,
  CapBucket,
  HOLDER_TYPES,
  HolderType,
  STOCK_RESEARCH_DATA,
} from "../../lib/stockResearchData";

const crCr = (v: number) => `₹${v.toLocaleString("en-IN")} Cr`;

export default function StockResearchPage() {
  const [search, setSearch] = useState("");
  const [holderType, setHolderType] = useState<HolderType | "all">("all");
  const [capFilter, setCapFilter] = useState<CapBucket | "all">("all");

  const visible = useMemo(() => {
    const q = search.trim().toUpperCase();
    return STOCK_RESEARCH_DATA.filter((row) => {
      if (holderType !== "all" && row.holderType !== holderType) return false;
      if (capFilter !== "all" && row.capBucket !== capFilter) return false;
      if (
        q &&
        !row.symbol.toUpperCase().includes(q) &&
        !row.company.toUpperCase().includes(q) &&
        !row.holder.toUpperCase().includes(q) &&
        !row.sector.toUpperCase().includes(q)
      )
        return false;
      return true;
    });
  }, [search, holderType, capFilter]);

  return (
    <div className="page">
      <PageHeader
        crumb="Stock Research"
        title="Stock Research"
        subtitle="Curated snapshot of stocks held by well-known marquee investors and promoter/business families, sourced from public BSE/NSE shareholding disclosures. Manually maintained, not a live feed — verify against the latest shareholding pattern before acting. Not investment advice."
      />

      <div className="tabs-row">
        <div className="toolbar">
          <input
            placeholder="Search symbol, holder, sector…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={holderType} onChange={(e) => setHolderType(e.target.value as HolderType | "all")}>
            <option value="all">All holder types</option>
            {HOLDER_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select value={capFilter} onChange={(e) => setCapFilter(e.target.value as CapBucket | "all")}>
            <option value="all">All market caps</option>
            {CAP_BUCKETS.map((c) => (
              <option key={c} value={c}>
                {c} cap
              </option>
            ))}
          </select>
        </div>
      </div>

      <GlassPanel title={`Holdings (${visible.length})`}>
        {visible.length === 0 ? (
          <div className="empty">No holdings match this filter.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol / Company</th>
                  <th style={{ textAlign: "left" }}>Holder</th>
                  <th>Stake</th>
                  <th>Market cap</th>
                  <th>Cap bucket</th>
                  <th style={{ textAlign: "left" }}>Sector</th>
                  <th style={{ textAlign: "left" }}>Core business</th>
                  <th>Monopoly</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={`${row.symbol}-${row.holder}`}>
                    <td style={{ textAlign: "left" }}>
                      <div className="name-cell">
                        <span className="name">{row.symbol}</span>
                        <span className="sub">{row.company}</span>
                      </div>
                    </td>
                    <td style={{ textAlign: "left" }}>
                      <div className="name-cell">
                        <span className="holder">{row.holder}</span>
                        <span className={`chip type-${row.holderType === "Marquee Investor" ? "investor" : "promoter"}`}>
                          {row.holderType}
                        </span>
                      </div>
                    </td>
                    <td>{row.stakePct === null ? "-" : `${row.stakePct.toFixed(1)}%`}</td>
                    <td>{crCr(row.marketCapCr)}</td>
                    <td>
                      <span className={`chip cap-${row.capBucket.toLowerCase()}`}>{row.capBucket}</span>
                    </td>
                    <td style={{ textAlign: "left" }}>{row.sector}</td>
                    <td style={{ textAlign: "left" }} title={row.monopolyNote}>
                      {row.coreBusiness}
                    </td>
                    <td>
                      <span className={row.monopoly ? "gain pct" : "loss pct"}>{row.monopoly ? "Yes" : "No"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="footnote">
          Stake %, market cap and sector figures are approximate and periodically refreshed manually from public
          shareholding filings — treat as directional, not a live quote. "Monopoly" reflects a qualitative call on
          competitive intensity in the company's core segment, hover a row for the rationale.
        </div>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tabs-row { display: flex; justify-content: flex-end; align-items: center; gap: 12px; flex-wrap: wrap; }
        .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        input, select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13px; min-width: 120px; }
        input { min-width: 220px; }
        .empty { padding: 28px 20px; font-size: 13px; color: var(--text-muted); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); background: var(--panel); position: sticky; top: 0; }
        .data-table td { padding: 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); vertical-align: top; }
        .name-cell { display: flex; flex-direction: column; gap: 4px; }
        .name { font-weight: 700; font-size: 13px; }
        .sub { font-size: 11px; color: var(--text-muted); }
        .holder { font-size: 12.5px; font-weight: 600; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; color: var(--text-muted); display: inline-block; width: fit-content; }
        .chip.type-investor { color: var(--purple); }
        .chip.type-promoter { color: var(--accent); }
        .chip.cap-mega { color: var(--gain); }
        .chip.cap-large { color: var(--purple); }
        .chip.cap-mid { color: var(--accent); }
        .chip.cap-small, .chip.cap-micro { color: var(--loss); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .pct { font-weight: 700; font-size: 11px; }
        .footnote { padding: 12px 20px; font-size: 11px; color: var(--text-faint); border-top: 1px solid var(--panel-border); }
      `}</style>
    </div>
  );
}
