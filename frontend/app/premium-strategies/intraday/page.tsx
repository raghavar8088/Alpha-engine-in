"use client";

// Premium Strategies -> Premium Intraday Strategies (2026-11-22). An independent research and paper desk for Indian
// cash equities: its own container (premium-intraday-service), scheduler, database, paper books, risk limits and
// switch; the backend only adds read-only routes (/api/premium-intraday). This route is its own code split: nothing
// here is imported by /premium-strategies, and that page links here with prefetch off, so opening Premium Strategies
// never loads this page, its research data, or calls the desk.
//
// The shared PageHeader is NOT used: its Main Control switch matches pages by URL prefix and would show (and could
// flip) the Premium Strategies desk's switch here. This page shows the desk's own switch instead.
import Link from "next/link";
import { useState } from "react";
import DeskSwitch from "./DeskSwitch";
import ImportedView from "./ImportedView";
import JournalView from "./JournalView";
import PlanView from "./PlanView";
import PositionsView from "./PositionsView";
import ResearchView from "./ResearchView";
import ResultsView from "./ResultsView";
import SectorsView from "./SectorsView";
import { API, useDesk } from "./desk";

type Tab = "plan" | "sectors" | "imported" | "research" | "results" | "positions" | "journal";
const TABS: { id: Tab; label: string }[] = [
  { id: "plan", label: "Today's Trade Plan" },
  { id: "sectors", label: "Sector Strength and Weakness" },
  { id: "imported", label: "Imported Top 25" },
  { id: "research", label: "New Strategy Research" },
  { id: "results", label: "Backtest and Forward Results" },
  { id: "positions", label: "Paper Positions" },
  { id: "journal", label: "Trade Journal" },
];

export default function PremiumIntradayPage() {
  const [tab, setTab] = useState<Tab>("plan");
  const { data: status, error: statusError, reload } = useDesk<any>(`${API}/status`, 30_000);
  return (
    <div className="pis">
      <div className="pis-header">
        <div className="pis-crumbs">
          <Link href="/dashboard">Home</Link><span>›</span>
          <Link href="/premium-strategies">Premium Strategies</Link><span>›</span>
          <span className="pis-current">Premium Intraday Strategies</span>
        </div>
        <div className="pis-header-row">
          <div>
            <h1>Premium Intraday Strategies</h1>
            <p className="pis-sub">
              Each morning: strong and weak sectors, a shortlist of stocks, a strategy that fits the conditions, and a paper
              trade only when its trigger fires. Six new research strategies and the 25 best existing ones, all judged after costs.
            </p>
          </div>
          <DeskSwitch status={status} error={statusError} onChange={reload} />
        </div>
      </div>

      <div className="pis-banner">
        <span className="pis-pill pis-pill-warn">Paper only</span>
        <span>
          <b>No strategy has earned Portfolio Eligible status: 0 of 12 new strategy sides and 0 of the imported 25.</b> The
          shared Rs 10 lakh portfolio therefore places no trade; every strategy keeps collecting forward evidence in its own
          observation book. Nothing on this page can place a real order.
        </span>
      </div>

      <div className="pis-tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`pis-tab${tab === t.id ? " on" : ""}`}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>

      {tab === "plan" && <PlanView />}
      {tab === "sectors" && <SectorsView />}
      {tab === "imported" && <ImportedView />}
      {tab === "research" && <ResearchView />}
      {tab === "results" && <ResultsView />}
      {tab === "positions" && <PositionsView status={status} />}
      {tab === "journal" && <JournalView />}

      <style jsx global>{`
        .pis { display: flex; flex-direction: column; gap: 16px; }
        .pis-header { margin-bottom: 4px; }
        .pis-crumbs { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--text-faint); margin-bottom: 10px; flex-wrap: wrap; }
        .pis-crumbs a { color: var(--text-faint); text-decoration: none; }
        .pis-crumbs a:hover { color: var(--brand); }
        .pis-current { color: var(--text-muted); font-weight: 600; }
        .pis-header-row { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
        .pis-header h1 { margin: 0; font-size: 26px; font-weight: 800; color: var(--text); letter-spacing: -0.01em; }
        .pis-sub { margin: 6px 0 0; font-size: 13.5px; color: var(--text-muted); max-width: 760px; line-height: 1.55; }
        .pis-switch { display: flex; gap: 12px; align-items: center; padding: 10px 14px; border-radius: 12px; background: var(--panel);
                      border: 1px solid var(--panel-border); min-width: 280px; }
        .pis-switch-state { font-weight: 800; color: var(--text); display: flex; gap: 8px; align-items: center; font-size: 13px; }
        .pis-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .pis-dot.on { background: var(--gain); } .pis-dot.off { background: var(--loss); }
        .pis-btn { margin-left: auto; padding: 7px 14px; border-radius: 999px; border: 1px solid var(--panel-border); background: var(--canvas-soft);
                   color: var(--text); font-weight: 700; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
        .pis-btn:hover { border-color: var(--brand); color: var(--brand); }
        .pis-banner { display: flex; gap: 12px; align-items: flex-start; padding: 12px 16px; border-radius: 10px; background: var(--warn-dim);
                      border: 1px solid var(--panel-border); font-size: 13px; line-height: 1.6; color: var(--text-muted); }
        .pis-banner b { color: var(--text); }
        .pis-alert { padding: 12px 16px; border-radius: 10px; background: var(--loss-dim); border: 1px solid var(--loss); color: var(--text); font-size: 13px; }
        .pis-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
        .pis-tab { padding: 8px 14px; border-radius: 999px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted);
                   font-weight: 700; font-size: 12.5px; cursor: pointer; }
        .pis-tab.on { background: var(--brand); color: var(--on-brand, #fff); border-color: var(--brand); }
        .pis-col { display: flex; flex-direction: column; gap: 16px; }
        .pis .panel { padding-bottom: 14px; }
        .pis .panel > :not(.panel-head) { margin-left: 18px; margin-right: 18px; }
        .pis .panel > .panel-head + * { margin-top: 12px; }
        .pis-pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; white-space: nowrap; margin-left: 6px; }
        .pis-banner .pis-pill { margin-left: 0; }
        .pis-pill-good { background: var(--gain-dim); color: var(--gain); }
        .pis-pill-bad { background: var(--loss-dim); color: var(--loss); }
        .pis-pill-warn { background: var(--warn); color: #fff; }
        .pis-pill-info { background: var(--brand-dim); color: var(--brand); }
        .pis-pill-neutral { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .pis-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .pis-table th { text-align: left; font-size: 11px; font-weight: 800; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.03em;
                        padding: 8px 10px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .pis-table td { padding: 8px 10px; border-bottom: 1px solid var(--panel-border); color: var(--text); vertical-align: top; white-space: nowrap; }
        .pis-table .r { text-align: right; }
        .pis-compact td, .pis-compact th { padding: 5px 8px; }
        .pis-wrap { white-space: normal !important; min-width: 220px; max-width: 460px; }
        .pis-scroll { overflow-x: auto; }
        .pis-strong { font-weight: 700; }
        .pis-muted { color: var(--text-faint); }
        .pis-small { font-size: 11.5px; }
        .pis-up { color: var(--gain) !important; }
        .pis-down { color: var(--loss) !important; }
        .pis-err { color: var(--loss); }
        .pis-note { font-size: 12px; color: var(--text-muted); line-height: 1.55; margin: 10px 0 0; }
        .pis-warnline { font-size: 12.5px; color: var(--text); background: var(--warn-dim); padding: 8px 12px; border-radius: 8px; }
        .pis-empty { padding: 14px 16px; border-radius: 10px; background: var(--canvas-soft); color: var(--text-muted); font-size: 13px; line-height: 1.55; }
        .pis-h4, .pis-detail h4, .pis-detail-grid h4 { margin: 14px 0 6px; font-size: 13px; font-weight: 800; color: var(--text); }
        .pis-list { margin: 6px 0; padding-left: 18px; font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .pis-list b { color: var(--text); }
        .pis-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 12px; }
        .pis-tile { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; background: var(--canvas-soft);
                    border: 1px solid var(--panel-border); }
        .pis-tile-label { font-size: 11px; font-weight: 800; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.03em; }
        .pis-tile-val { font-size: 20px; font-weight: 800; color: var(--text); text-transform: capitalize; }
        .pis-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
        .pis-chip { padding: 6px 12px; border-radius: 999px; border: 1px solid var(--panel-border); background: var(--panel); font-size: 12px;
                    font-weight: 700; color: var(--text-muted); cursor: pointer; }
        .pis-chip.on { border-color: var(--brand); color: var(--brand); background: var(--brand-dim); }
        .pis-timeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; margin: 12px 0; }
        .pis-stage { text-align: left; display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border-radius: 10px;
                     border: 1px solid var(--panel-border); background: var(--panel); cursor: pointer; font: inherit; color: var(--text-muted); }
        .pis-stage.done { background: var(--canvas-soft); }
        .pis-stage.on { border-color: var(--brand); }
        .pis-stage-at { font-weight: 800; color: var(--text); font-size: 13px; }
        .pis-stage-what { font-size: 11.5px; color: var(--text-faint); }
        .pis-stage-sum { font-size: 12px; line-height: 1.5; }
        .pis-detail { margin-top: 8px; }
        .pis-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }
        .pis-side { display: flex; flex-direction: column; gap: 6px; }
        .pis-side-head { display: flex; gap: 8px; align-items: center; font-size: 13px; flex-wrap: wrap; }
        .pis-dl { display: grid; grid-template-columns: minmax(120px, 190px) 1fr; gap: 6px 14px; font-size: 12.5px; margin: 6px 0; }
        .pis-dl dt { font-weight: 800; color: var(--text); }
        .pis-dl dd { margin: 0; color: var(--text-muted); line-height: 1.55; }
        .pis-rules { margin: 8px 0; font-size: 13px; }
        .pis-rules summary { cursor: pointer; color: var(--text); }
        .pis-checks { list-style: none; padding: 0; margin: 6px 0; font-size: 12.5px; line-height: 1.6; }
        .pis-checks li.ok b { color: var(--gain); }
        .pis-checks li.bad b { color: var(--loss); }
        .pis-click { cursor: pointer; }
        .pis-click:hover td { background: var(--canvas-soft); }
        .pis-sel td { background: var(--brand-dim) !important; }
        .pis-selbox { margin-top: 12px; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--brand); background: var(--canvas-soft); }
        .pis-selbox-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; font-size: 13px; color: var(--text); margin-bottom: 6px; }
        .pis-row-strong td { background: var(--gain-dim); }
        .pis-row-weak td { background: var(--loss-dim); }
        .pis-link { color: var(--brand); font-weight: 700; }
        .pis-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
        .pis-filters select, .pis-filters input { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel);
                                                  color: var(--text); font: inherit; font-size: 12.5px; }
        @media (max-width: 640px) {
          .pis-header h1 { font-size: 21px; }
          .pis-switch { min-width: 0; width: 100%; }
          .pis-dl { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  );
}
