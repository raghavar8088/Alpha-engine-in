"use client";

/*
 * Angel One Commodity Live Trading Data — the owner's REAL Angel One MCX account, read-only.
 * Trades, orders and positions come from Angel's API (today's session; the backend keeps each
 * day), P&L is Angel's own, charges follow Angel's published commodity rate card, and the
 * capital each day is the peak of what Angel reported in use (margin + premium). The tabs add
 * what the raw book cannot show on its own: completed trades and their statistics, Greeks and
 * margin per open position with what-if moves, drawdown and risk-adjusted returns, a calendar,
 * charges by component, order quality and data coverage. Nothing on this page can place an order.
 */

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  type AcAnalytics,
  type AcRisk,
  type AcSummary,
  fetchAngelCommodity,
  fetchAngelCommodityAnalytics,
  fetchAngelCommodityRisk,
  refreshing,
  syncAngelCommodity,
} from "../../lib/api";
import ChargesTab from "./ChargesTab";
import DailyTab from "./DailyTab";
import DataTab from "./DataTab";
import OrdersTab from "./OrdersTab";
import OverviewTab from "./OverviewTab";
import RiskTab from "./RiskTab";
import TradesTab from "./TradesTab";

const TABS = [
  ["overview", "Overview"],
  ["risk", "Positions & risk"],
  ["trades", "Trades"],
  ["daily", "Daily & calendar"],
  ["charges", "Charges"],
  ["orders", "Orders"],
  ["data", "Data"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function AngelCommodityPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<AcSummary | null>(null);
  const [analytics, setAnalytics] = useState<AcAnalytics | null>(null);
  const [risk, setRisk] = useState<AcRisk | null>(null);
  const [riskBusy, setRiskBusy] = useState(false);
  const [riskErr, setRiskErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t && TABS.some(([k]) => k === t)) setTab(t as Tab);
  }, []);
  const choose = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", t === "overview" ? window.location.pathname : `?tab=${t}`);
  };

  const loadSummary = useCallback(async () => {
    try {
      setData(await fetchAngelCommodity());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the Angel One commodity data");
    }
  }, []);
  const loadAnalytics = useCallback(async () => {
    try {
      setAnalytics(await fetchAngelCommodityAnalytics());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the analytics");
    }
  }, []);
  const loadRisk = useCallback(async () => {
    setRiskBusy(true);
    try {
      setRisk(await fetchAngelCommodityRisk());
      setRiskErr(null);
    } catch (e) {
      setRiskErr(e instanceof Error ? e.message : "failed");
    } finally {
      setRiskBusy(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
    loadAnalytics();
    const a = setInterval(loadSummary, 60000);
    const b = setInterval(loadAnalytics, 120000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [loadSummary, loadAnalytics]);

  useEffect(() => {
    if (tab !== "risk") return;
    loadRisk();
    const id = setInterval(loadRisk, 60000);
    return () => clearInterval(id);
  }, [tab, loadRisk]);

  const handleRefresh = useCallback(async () => {
    setBusy(true);
    try {
      await refreshing(() => Promise.all([loadSummary(), loadAnalytics(), tab === "risk" ? loadRisk() : Promise.resolve()]));
    } finally {
      setBusy(false);
    }
  }, [loadSummary, loadAnalytics, loadRisk, tab]);

  const syncNow = async () => {
    setSyncMsg("Asking Angel One…");
    try {
      const r = await syncAngelCommodity();
      setSyncMsg(r.skipped ? String(r.skipped) : `Synced: ${r.fills ?? 0} trades, ${r.positions ?? 0} positions today`);
      await refreshing(() => Promise.all([loadSummary(), loadAnalytics()]));
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    }
  };

  const st = data?.status;
  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={busy}
        crumb="Angel One Commodity Live Trading Data"
        title="Angel One Commodity Live Trading Data"
        subtitle="Your REAL Angel One MCX account: every trade, Angel's own P&L, the return on the capital you had in use each day — and the analysis behind it: completed trades, Greeks and margin on open positions, drawdowns, charges and orders. Read-only: this page can never place an order."
      />

      {error && <ErrorBanner message={error} />}

      <div className="strip">
        <span className="pill real">REAL ACCOUNT · READ-ONLY</span>
        <span className={`pill ${st?.angel_ok === false ? "bad" : st?.angel_ok ? "ok" : ""}`}>
          {st?.angel_ok === false ? `Angel One error: ${st.last_error ?? ""}` : st?.angel_ok ? "Angel One connected" : "Angel One — not polled yet"}
        </span>
        <span className="pill">{st?.window_open ? "MCX window open — polled every minute" : "MCX window closed (Mon–Fri 08:45–23:59)"}</span>
        {st && !st.switch_on && <span className="pill bad">switched off in Main Control</span>}
        <span className="muted small">{st?.last_sync ? `last sync ${new Date(st.last_sync).toLocaleTimeString()}` : ""}</span>
        <button type="button" className="btn" onClick={syncNow} disabled={!st?.window_open}>Sync now</button>
        {syncMsg && <span className="muted small">{syncMsg}</span>}
      </div>

      <div className="tabs" role="tablist" aria-label="Sections">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => choose(k)}>{label}</button>
        ))}
      </div>

      {!data ? (
        <div className="empty">Loading your Angel One commodity account…</div>
      ) : tab === "overview" ? (
        <OverviewTab data={data} analytics={analytics} />
      ) : tab === "risk" ? (
        <RiskTab risk={risk} loading={riskBusy} error={riskErr} onRefresh={() => refreshing(() => loadRisk())} />
      ) : tab === "trades" ? (
        <TradesTab data={data} analytics={analytics} />
      ) : tab === "daily" ? (
        <DailyTab data={data} analytics={analytics} />
      ) : tab === "charges" ? (
        <ChargesTab analytics={analytics} />
      ) : tab === "orders" ? (
        <OrdersTab data={data} analytics={analytics} />
      ) : (
        <DataTab data={data} analytics={analytics} onImported={() => refreshing(() => Promise.all([loadSummary(), loadAnalytics()])).then(() => undefined)} />
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .strip { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .pill { font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .pill.real { background: var(--loss-dim); color: var(--loss); }
        .pill.ok { background: var(--gain-dim); color: var(--gain); }
        .pill.bad { background: var(--loss-dim); color: var(--loss); }
        .btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .muted { color: var(--text-muted); }
        .small { font-size: 11px; }
        .tabs { display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--panel-border); padding-bottom: 8px; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.on { background: var(--panel); color: var(--text); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12); border-color: var(--text-faint); }
        .empty { padding: 30px; text-align: center; color: var(--text-faint); font-size: 13px; }
      `}</style>
    </div>
  );
}
