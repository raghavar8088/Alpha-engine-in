"use client";

/** Indian Index Intraday Trading — cash-market intraday on Indian indexes, researched, backtested and
 * paper traded. No options, futures or leverage.
 *
 * The research (backend/research/index_intraday_2026_10, INDEX_INTRADAY_RESEARCH_2026_10.md) tested
 * 1,208 variants of 14 strategy families on 8 indexes over 2016–23 one-minute data, with Angel One's
 * intraday charges and each ETF's measured spread. None reached Validated, so none is Paper Trading
 * Approved; the 2024–26 holdout was never opened. Every strategy can still be run in paper as an
 * OBSERVATION, labelled with its research status, on one of two execution models:
 *   ETF    the tracking ETF at its live bid / ask, whole units, Angel's charges, a liquidity cap
 *   index  the index level itself, simulated, charged what its ETF would cost
 *
 * Paper only: nothing on this page can reach a broker.
 */

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import { fetchIIResearch, type IIResearch } from "../../lib/indexIntradayApi";
import MarketOverview from "./MarketOverview";
import StrategyDashboard from "./StrategyDashboard";
import TradingTerminal from "./TradingTerminal";
import BacktestLab from "./BacktestLab";
import TradeJournal from "./TradeJournal";
import RiskPanel from "./RiskPanel";

type Tab = "overview" | "strategies" | "terminal" | "lab" | "journal" | "risk";
const TABS: [Tab, string][] = [
  ["overview", "Market Overview"],
  ["strategies", "Strategy Dashboard"],
  ["terminal", "Paper Trading Terminal"],
  ["lab", "Backtesting Lab"],
  ["journal", "Trade Journal"],
  ["risk", "Risk Management"],
];

export default function IndexIntradayPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [research, setResearch] = useState<IIResearch | null>(null);
  const [labSid, setLabSid] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0); // remounts the open tab on Refresh

  const loadResearch = useCallback(async () => {
    try {
      setResearch(await fetchIIResearch());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not reach the Index Intraday service.");
    }
  }, []);

  useEffect(() => {
    loadResearch();
    const fromHash = window.location.hash.replace("#", "") as Tab;
    if (TABS.some(([k]) => k === fromHash)) setTab(fromHash);
  }, [loadResearch]);

  const go = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", `#${t}`);
  };

  const backtest = (sid: string) => {
    setLabSid(sid);
    go("lab");
  };

  return (
    <div className="iid">
      <PageHeader
        crumb="Index Intraday"
        title="Indian Index Intraday Trading"
        onRefresh={async () => {
          await loadResearch();
          setNonce((n) => n + 1);
        }}
        subtitle={
          <>
            Intraday trading of Indian indexes in the cash market — no options, futures or leverage.{" "}
            <strong>{research?.trials?.toLocaleString("en-IN") ?? "1,208"} strategy variants</strong> were tested on
            2016–23 one-minute data with Angel One&rsquo;s charges and measured spreads:{" "}
            <strong>none reached Validated</strong>, so none is approved for paper trading, and the 2024–26 holdout was
            never opened. Any of them can still be run in paper as an observation, labelled with its research status.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper only" tone="accent" />
            <StatusPill label={`${research?.validated ?? 0} approved`} tone="muted" />
          </>
        }
      />

      {err && <ErrorBanner message={err} onRetry={loadResearch} />}

      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => go(k)}>
            {label}
          </button>
        ))}
      </div>

      <div key={`${tab}-${nonce}`}>
        {tab === "overview" && <MarketOverview research={research} />}
        {tab === "strategies" && <StrategyDashboard research={research} onBacktest={backtest} />}
        {tab === "terminal" && <TradingTerminal onOpenStrategies={() => go("strategies")} />}
        {tab === "lab" && <BacktestLab initialSid={labSid} />}
        {tab === "journal" && <TradeJournal />}
        {tab === "risk" && <RiskPanel />}
      </div>

      <style jsx global>{`
        .iid { padding: 28px 32px 56px; display: flex; flex-direction: column; gap: 18px; }
        .iid .stack { display: flex; flex-direction: column; gap: 16px; }
        .iid .pad { padding: 24px 4px; }

        .iid .tabs { display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--panel-border); }
        .iid .tab { background: none; border: none; border-bottom: 2px solid transparent; margin-bottom: -1px;
                    color: var(--text-muted); padding: 9px 14px; font-size: 13px; font-weight: 700; cursor: pointer; }
        .iid .tab:hover { color: var(--text); }
        .iid .tab.on { color: var(--purple); border-bottom-color: var(--purple); }

        .iid .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
        .iid .stat { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px;
                     padding: 13px 15px; display: flex; flex-direction: column; gap: 4px; }
        .iid .stat .k { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                        color: var(--text-faint); }
        .iid .stat .v { font-family: var(--font-data); font-size: 19px; font-weight: 700;
                        font-variant-numeric: tabular-nums; }
        .iid .stat .v.sm { font-size: 14px; }
        .iid .stat .s { font-size: 11.5px; color: var(--text-muted); line-height: 1.45; }

        .iid .tscroll { overflow-x: auto; }
        .iid .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums;
                    white-space: nowrap; }
        .iid .tbl th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em;
                       text-transform: uppercase; color: var(--text-faint); border-bottom: 1px solid var(--panel-border); }
        .iid .tbl td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .iid .tbl th.l, .iid .tbl td.l { text-align: left; }
        .iid .tbl tr.click { cursor: pointer; }
        .iid .tbl tr.click:hover td { background: var(--canvas-soft); }
        .iid .tbl.small { font-size: 12px; margin-top: 8px; }
        .iid .tbl.small td { padding: 6px 8px; }
        .iid .wrap { white-space: normal; min-width: 220px; }
        .iid .strong { font-weight: 700; }
        .iid .muted { color: var(--text-muted); }
        .iid .faint { color: var(--text-faint); font-size: 11px; }
        .iid .gain { color: var(--gain); }
        .iid .loss { color: var(--loss); }
        .iid .warn { color: var(--warn); }
        .iid .empty { color: var(--text-muted); white-space: normal; padding: 16px 10px; }
        .iid .empty-block { color: var(--text-muted); font-size: 12.5px; padding: 6px 2px; }
        .iid .foot { margin: 12px 2px 0; font-size: 12px; line-height: 1.6; color: var(--text-muted); }

        .iid .chip { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 100px;
                     background: var(--canvas-soft); color: var(--text-muted); margin-right: 4px; }
        .iid .chip.good { color: var(--gain); background: var(--gain-dim); }
        .iid .chip.bad { color: var(--loss); background: var(--loss-dim); }
        .iid .chip.run { color: var(--purple); background: var(--purple-dim); margin-left: 6px; }
        .iid .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
        .iid .stag { display: inline-block; font-size: 10.5px; font-weight: 800; letter-spacing: 0.03em; padding: 2px 8px;
                     border-radius: 100px; border: 1px solid var(--panel-border); color: var(--text-muted); }
        .iid .stag.st-bt { color: var(--warn); background: var(--warn-dim); border-color: transparent; }
        .iid .stag.st-val { color: var(--purple); background: var(--purple-dim); border-color: transparent; }
        .iid .stag.st-ok { color: var(--gain); background: var(--gain-dim); border-color: transparent; }
        .iid .side { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 100px; }
        .iid .side.buy { color: var(--gain); background: var(--gain-dim); }
        .iid .side.sell { color: var(--loss); background: var(--loss-dim); }

        .iid .btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
                    border-radius: 9px; padding: 7px 13px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .iid .btn:hover:not(:disabled) { color: var(--purple); border-color: var(--purple); }
        .iid .btn:disabled { opacity: 0.5; cursor: default; }
        .iid .btn.sm { padding: 4px 10px; font-size: 11.5px; }
        .iid .btn.primary { background: var(--purple-dim); color: var(--purple); border-color: var(--purple); }
        .iid .btn.danger:hover:not(:disabled) { color: var(--loss); border-color: var(--loss); }
        .iid .btn.strongbtn { color: var(--loss); border-color: var(--loss); background: var(--loss-dim); font-weight: 800; }
        .iid .btn.more { margin-top: 10px; }
        .iid .linkish { background: none; border: none; padding: 0; color: var(--purple); cursor: pointer;
                        font-size: inherit; text-align: left; }
        .iid .linkish:hover { text-decoration: underline; }

        .iid .filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
        .iid .filters label, .iid .deploy label { display: flex; flex-direction: column; gap: 4px; font-size: 10px;
                     font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-faint); }
        .iid .filters label.wide { min-width: 260px; flex: 1; }
        .iid .filters label.check { flex-direction: row; align-items: center; gap: 6px; text-transform: none;
                                    font-size: 12.5px; font-weight: 600; color: var(--text-muted); padding-bottom: 7px; }
        .iid select, .iid input { background: var(--panel); border: 1px solid var(--panel-border); color: var(--text);
                                  border-radius: 8px; padding: 6px 9px; font-size: 12.5px; font-family: inherit; }
        .iid input[type="checkbox"] { padding: 0; }
        .iid .quick { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
        .iid .row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .iid .row.spread { justify-content: space-between; }

        .iid .note { font-size: 12.5px; color: var(--text-muted); background: var(--canvas-soft);
                     border: 1px solid var(--panel-border); border-radius: 10px; padding: 9px 13px; }
        .iid .warnbox { font-size: 12.5px; color: var(--warn); background: var(--warn-dim); border-radius: 10px;
                        padding: 9px 13px; line-height: 1.5; margin-top: 8px; }
        .iid .verdict, .iid .observe { font-size: 12.5px; line-height: 1.6; color: var(--text-muted);
                     background: var(--canvas-soft); border: 1px solid var(--panel-border); border-left: 3px solid var(--warn);
                     border-radius: 10px; padding: 11px 15px; }
        .iid .observe { border-left-color: var(--purple); }
        .iid .sel-sum { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12.5px; margin-top: 4px; }

        .iid .notes, .iid .events { margin: 10px 0 0; padding-left: 0; list-style: none; display: flex;
                                    flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--text-muted); }
        .iid .events li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }

        .iid .drawer-wrap { position: fixed; inset: 0; background: var(--scrim); z-index: 60; display: flex;
                            justify-content: flex-end; }
        .iid .drawer { width: min(760px, 100%); height: 100%; overflow-y: auto; background: var(--panel);
                       box-shadow: var(--shadow-lg); padding: 22px 24px 40px; display: flex; flex-direction: column; gap: 10px; }
        .iid .drawer-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .iid .dtitle { font-family: var(--font-display); font-size: 18px; font-weight: 800; margin: 2px 0; }
        .iid .dstatus { display: flex; gap: 10px; align-items: baseline; font-size: 12.5px; color: var(--text-muted);
                        background: var(--canvas-soft); border-radius: 10px; padding: 9px 12px; }
        .iid .dsec { margin-top: 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                     color: var(--text-faint); }
        .iid .deploy p { font-size: 12.5px; color: var(--text-muted); margin: 4px 0 10px; line-height: 1.55; }

        .iid .estop { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
                      border: 1px solid var(--panel-border); background: var(--canvas-soft); border-radius: 14px;
                      padding: 16px 20px; }
        .iid .estop.on { border-color: var(--loss); background: var(--loss-dim); }
        .iid .etitle { font-family: var(--font-display); font-weight: 800; font-size: 14px; letter-spacing: 0.03em; }
        .iid .estop.on .etitle { color: var(--loss); }
        .iid .esub { margin-top: 4px; font-size: 12.5px; color: var(--text-muted); max-width: 760px; }

        .iid .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 14px 18px;
                     margin-bottom: 14px; }
        .iid .field { display: flex; flex-direction: column; gap: 5px; }
        .iid .fl { font-size: 12.5px; font-weight: 700; color: var(--text); }
        .iid .fh { font-size: 11.5px; color: var(--text-muted); line-height: 1.45; }

        @media (max-width: 640px) {
          .iid { padding: 18px 16px 40px; }
          .iid .drawer { padding: 18px 16px 32px; }
        }
      `}</style>
    </div>
  );
}
