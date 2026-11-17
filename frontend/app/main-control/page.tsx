"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import {
  refreshing,
  ModuleSwitch,
  ModuleSwitches,
  fetchMainControl,
  setMainControlAll,
  setMainControlModule,
  setMainControlOnly,
  resetMainControlCounts,
  PerfSummary,
  fetchServerPerf,
} from "../../lib/api";
import { publishSnapshot } from "../../lib/moduleStatus";

const REFRESH_MS = 30000;

export default function MainControlPage() {
  const [data, setData] = useState<ModuleSwitches | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const [perf, setPerf] = useState<PerfSummary | null>(null);
  const drainServer = data?.semantics === "drain";

  const load = useCallback(async () => {
    try {
      const snap = await fetchMainControl();
      setData(snap);
      publishSnapshot(snap); // every page header shows the same states
      setError(null);
      // Server load is a nice-to-have: an older server has no /perf, and that is fine.
      fetchServerPerf(12)
        .then(setPerf)
        .catch(() => setPerf(null));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Main Control");
    }
  }, []);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const run = async (
    label: string,
    fn: () => Promise<ModuleSwitches>,
    msg: string,
  ) => {
    if (busy) return;
    setBusy(label);
    setNotice(null);
    try {
      const snap = await fn();
      setData(snap);
      publishSnapshot(snap);
      setNotice(msg);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change the switch");
    } finally {
      setBusy(null);
    }
  };

  const toggle = (m: ModuleSwitch) =>
    run(
      m.module,
      () => setMainControlModule(m.module, !m.enabled),
      m.enabled
        ? drainServer && m.drains
          ? `${m.label} switched OFF. No new entries from now. Open positions keep being managed to their exits (shown as Stopping); once it is flat it pauses completely.`
          : `${m.label} switched OFF. It pauses at once: its loop stops and its API refuses new work. Open positions are left as they are and are not managed.`
        : `${m.label} switched ON. Its API answers again and the loop resumes on its next tick.`,
    );

  const confirmOff = (m: ModuleSwitch) =>
    !m.enabled ||
    window.confirm(
      `Switch OFF "${m.label}"?\n\n` +
        (m.module === "live_trading" ? "This is the REAL-MONEY desk.\n\n" : "") +
        (m.off_behaviour ||
          "It pauses at once; open positions are left as they are and are not managed while off."),
    );

  const only = (m: ModuleSwitch) => {
    const n = (data?.total ?? 1) - 1;
    if (
      !window.confirm(
        `Leave ONLY "${m.label}" running and switch OFF the other ${n} modules?\n\n` +
          `Every other desk stops taking new trades, and their APIs stop doing work. ` +
          (drainServer
            ? `Desks still holding positions keep managing them to their exits, then pause.`
            : `Open positions everywhere are left unmanaged.`),
      )
    )
      return;
    run(
      "only",
      () => setMainControlOnly(m.module),
      `Only ${m.label} is running now. The other ${n} modules are OFF.`,
    );
  };

  const toggleAll = (enabled: boolean) => {
    const n = data?.total ?? 0;
    if (
      !enabled &&
      !window.confirm(
        `Switch OFF all ${n} modules?\n\nEvery desk stops taking new trades, and every ` +
          `module API stops fetching and writing (exits still work). ` +
          (drainServer
            ? `Desks still holding positions keep managing them to their exits, then pause. `
            : `Open positions are left unmanaged. `) +
          `Main Control itself stays reachable.`,
      )
    )
      return;
    run(
      "all",
      () => setMainControlAll(enabled),
      enabled ? `All ${n} modules switched ON.` : `All ${n} modules switched OFF.`,
    );
  };

  const rows = data?.modules ?? [];
  const groups = data?.groups ?? [];

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (m) =>
        m.label.toLowerCase().includes(q) ||
        m.module.toLowerCase().includes(q) ||
        (m.api_prefixes ?? []).some((p) => p.toLowerCase().includes(q)),
    );
  }, [rows, filter]);

  const byGroup = useMemo(() => {
    const out: { group: string; items: ModuleSwitch[] }[] = [];
    for (const g of groups) {
      const items = visible.filter((m) => m.group === g);
      if (items.length) out.push({ group: g, items });
    }
    const rest = visible.filter((m) => !groups.includes(m.group ?? ""));
    if (rest.length) out.push({ group: "Other", items: rest });
    return out;
  }, [visible, groups]);

  const blockedTotal = data?.blocked_total ?? 0;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Main Control"
        title="Main Control"
        subtitle={
          <>
            One switch per module, for the whole application — the same switch sits in the
            header of each module&apos;s own page. <strong>ON</strong> is exactly how the module
            behaves today. <strong>OFF</strong> stops its new trades, its background loop{" "}
            <em>and</em> any API request that would call the broker or write a document, so a
            module you do not use stops costing CPU.
          </>
        }
        actions={
          <>
            <StatusPill label={`${data?.on ?? 0} active`} tone="gain" />
            {(data?.stopping ?? 0) > 0 && (
              <StatusPill label={`${data?.stopping} stopping`} tone="warn" pulse />
            )}
            <StatusPill
              label={`${drainServer ? (data?.paused ?? 0) : (data?.off ?? 0)} paused`}
              tone={(data?.off ?? 0) > 0 ? "loss" : "muted"}
            />
            {blockedTotal > 0 && (
              <StatusPill label={`${blockedTotal} requests blocked`} tone="warn" />
            )}
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      {drainServer ? (
        <div className="warn">
          <strong>What OFF does.</strong> New entries stop at once. A module still holding
          positions shows <strong>Stopping</strong>: it keeps marking them and exiting them on
          their own stops, targets and the mandatory square-off, and its exit buttons keep
          working. Once it is flat it shows <strong>Paused</strong>: no polling, no broker
          calls, no background CPU. Its page still shows its history — those numbers are frozen,
          not live. Switching it back <strong>ON</strong> resumes on the next tick. A few
          modules cannot manage a book without doing the very work OFF stops; their card says
          so, and they pause at once.
        </div>
      ) : (
        <div className="warn">
          <strong>Two things OFF does not do.</strong> It does not close anything — whatever a
          module already holds stays exactly as it is, frozen at its last mark and{" "}
          <em>not</em> managed, so an open position will not hit its own stop while the module is
          off. Square off first if that matters. And it does not blank the page: plain reads of
          rows already stored still answer, so an OFF module still shows its last known numbers.{" "}
          <strong>Those numbers are frozen, not live.</strong> Blocking reads too would only cost
          you the ability to look at history you already have.
        </div>
      )}

      {perf && (
        <GlassPanel
          title="Server load"
          note={`since the backend started ${Math.round(perf.uptime_s / 60)} min ago`}
        >
          <div className="perf">
            <div className="lag">
              {(["last_1m", "last_10m", "last_60m"] as const).map((w) => {
                const lag = perf.event_loop_lag[w];
                const tone = lag.blocked_pct >= 25 ? "bad" : lag.blocked_pct >= 8 ? "mid" : "ok";
                return (
                  <div className="lag-cell" key={w}>
                    <div className="lag-k">{w.replace("last_", "last ")}</div>
                    <div className={`lag-v ${tone}`}>{lag.blocked_pct}% blocked</div>
                    <div className="lag-s">
                      lag p95 {lag.p95_ms} ms · max {lag.max_ms} ms
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="tb-note">
              <strong>Blocked</strong> is the share of time the server could not answer any page
              at all because it was busy — mostly the background desks. Switching off modules you
              do not use lowers it; this is how to check the switches are paying off.
            </div>
            {perf.endpoints.length > 0 && (
              <table className="slow">
                <thead>
                  <tr>
                    <th>Slowest requests</th>
                    <th>calls</th>
                    <th>p50</th>
                    <th>p95</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.endpoints.slice(0, 8).map((e) => (
                    <tr key={e.endpoint}>
                      <td className="ep">{e.endpoint}</td>
                      <td>{e.count}</td>
                      <td>{e.p50_s.toFixed(2)}s</td>
                      <td>{e.p95_s.toFixed(2)}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </GlassPanel>
      )}

      <GlassPanel
        title="Modules"
        note={`${rows.length} modules · ${data?.api_prefixes_controlled ?? 0} API prefixes`}
      >
        <div className="toolbar">
          <button className="btn sm" onClick={() => toggleAll(true)} disabled={!!busy}>
            All on
          </button>
          <button className="btn sm danger" onClick={() => toggleAll(false)} disabled={!!busy}>
            All off
          </button>
          {blockedTotal > 0 && (
            <button
              className="btn sm"
              onClick={() =>
                run("counts", resetMainControlCounts, "Blocked-request counters cleared.")
              }
              disabled={!!busy}
            >
              Clear counters
            </button>
          )}
          <input
            className="find"
            placeholder="Filter by name, key or /api prefix"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        <div className="tb-note">{data?.note}</div>

        {byGroup.map(({ group, items }) => (
          <div className="group" key={group}>
            <div className="g-head">
              <span className="g-name">{group}</span>
              <span className="g-count">
                {items.filter((m) => m.enabled).length}/{items.length} on
              </span>
            </div>
            <div className="grid">
              {items.map((m) => (
                <div
                  key={m.module}
                  className={`mod ${m.enabled ? "on" : m.state === "stopping" ? "stopping" : "off"}`}
                >
                  <div className="m-head">
                    <div className="m-text">
                      <div className="m-label">
                        {m.label}
                        {m.module === "live_trading" && <span className="tag real">REAL MONEY</span>}
                        {m.shared && <span className="tag shared">SHARED</span>}
                        {!m.has_api && <span className="tag loop">LOOP ONLY</span>}
                      </div>
                      <Link href={m.href} className="m-href">
                        {m.href}
                      </Link>
                      {(m.api_prefixes ?? []).length > 0 && (
                        <div className="m-api">{(m.api_prefixes ?? []).join("  ")}</div>
                      )}
                    </div>
                    <div className="m-ctl">
                      <button
                        className={`switch ${m.enabled ? "on" : "off"}`}
                        onClick={() => {
                          if (confirmOff(m)) toggle(m);
                        }}
                        disabled={!!busy}
                        role="switch"
                        aria-checked={m.enabled}
                        aria-label={`Toggle ${m.label}`}
                      >
                        <span className="knob" />
                        <span className="s-label">{m.enabled ? "ON" : "OFF"}</span>
                      </button>
                      <button
                        className="only"
                        onClick={() => only(m)}
                        disabled={!!busy}
                        title={`Run ONLY ${m.label} and switch off everything else`}
                      >
                        only this
                      </button>
                    </div>
                  </div>

                  {m.shared && m.note && <div className="m-note">{m.note}</div>}

                  {m.state && (
                    <div className={`m-state ${m.state}`}>
                      <span className="sd" />
                      {m.state === "stopping" && (m.open_positions ?? 0) > 0
                        ? `Stopping — managing ${m.open_positions} open position${m.open_positions === 1 ? "" : "s"}`
                        : (m.state_label ?? m.state)}
                    </div>
                  )}
                  {m.enabled && m.off_behaviour && (
                    <div className="m-behave">{m.off_behaviour}</div>
                  )}

                  {!m.enabled && (
                    <div className={`m-off ${m.state === "stopping" ? "draining" : ""}`}>
                      {m.state === "stopping"
                        ? "No new entries. Managing what it holds to the exits, then it pauses."
                        : "Not polling, not trading, API not fetching or writing."}
                      {(m.blocked_requests ?? 0) > 0 && (
                        <>
                          {" "}
                          <strong>{m.blocked_requests} request(s) blocked</strong>
                          {m.last_blocked ? ` — last: ${m.last_blocked}` : ""}.
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}

        {!visible.length && <div className="empty">No module matches “{filter}”.</div>}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn.sm { padding: 5px 11px; font-size: 11.5px; }
        .btn.danger { color: var(--loss); border-color: rgba(217,45,63,.3); }
        .btn:disabled { opacity: .55; cursor: default; }
        .notice { border-radius: 12px; padding: 11px 16px; font-size: 12.5px; cursor: pointer; line-height: 1.5;
                  background: var(--purple-dim); border: 1px solid rgba(var(--brand-rgb), .24); color: var(--purple); }
        .warn { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.55;
                background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 14px 20px 0; }
        .find { flex: 1 1 220px; min-width: 160px; padding: 6px 11px; border-radius: 9px; font-size: 12px;
                border: 1px solid var(--panel-border); background: var(--canvas-soft); color: var(--text); }
        .tb-note { padding: 10px 20px 0; font-size: 11.5px; color: var(--text-faint); line-height: 1.5; }
        .group { padding: 4px 20px 0; }
        .g-head { display: flex; align-items: baseline; gap: 10px; padding: 16px 0 8px; }
        .g-name { font-size: 11px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase;
                  color: var(--text-muted); }
        .g-count { font-size: 10.5px; color: var(--text-faint); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
        .mod { border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px;
               background: var(--canvas-soft); }
        .mod.on { border-color: rgba(14,159,110,.32); background: rgba(14,159,110,.05); }
        .mod.off { border-color: rgba(217,45,63,.24); }
        .m-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
        .m-text { min-width: 0; }
        .m-label { font-size: 12.5px; font-weight: 700; line-height: 1.4; }
        .tag { margin-left: 6px; font-size: 8.5px; font-weight: 800; letter-spacing: .05em;
               padding: 2px 5px; border-radius: 5px; vertical-align: middle; white-space: nowrap; }
        .tag.real { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217,45,63,.3); }
        .tag.shared { background: var(--canvas); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .tag.loop { background: var(--canvas); color: var(--text-faint); border: 1px solid var(--panel-border); }
        .m-href { display: inline-block; margin-top: 3px; font-size: 10.5px; color: var(--text-faint);
                  text-decoration: none; }
        .m-href:hover { color: var(--purple); text-decoration: underline; }
        .m-api { margin-top: 4px; font-family: var(--font-mono, ui-monospace), monospace;
                 font-size: 9.5px; color: var(--text-faint); word-break: break-all; }
        .m-ctl { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
        .switch { position: relative; width: 74px; height: 30px; border-radius: 16px; border: none;
                  cursor: pointer; display: flex; align-items: center; padding: 0 4px;
                  transition: background .15s; }
        .switch.on { background: var(--gain); justify-content: flex-end; }
        .switch.off { background: var(--loss); justify-content: flex-start; }
        .switch:disabled { opacity: .6; cursor: default; }
        .knob { width: 22px; height: 22px; border-radius: 50%; background: #fff; }
        .s-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff;
                   font-weight: 800; font-size: 10px; letter-spacing: .05em; }
        .switch.on .s-label { left: 11px; }
        .switch.off .s-label { right: 9px; }
        .only { padding: 2px 7px; border-radius: 6px; font-size: 9.5px; font-weight: 700; cursor: pointer;
                border: 1px solid var(--panel-border); background: transparent; color: var(--text-faint); }
        .only:hover:not(:disabled) { color: var(--purple); border-color: rgba(var(--brand-rgb), .34); }
        .only:disabled { opacity: .5; cursor: default; }
        .m-note { margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--panel-border);
                  font-size: 10.5px; color: var(--text-muted); line-height: 1.45; }
        .m-off { margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--panel-border);
                 font-size: 11px; color: var(--loss); line-height: 1.45; }
        .empty { padding: 26px 20px; text-align: center; font-size: 12.5px; color: var(--text-faint); }
        .mod.stopping { border-color: rgba(var(--warn-rgb), .4); background: var(--warn-dim); }
        .m-off.draining { color: var(--warn); }
        .m-state { display: inline-flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 11px;
                   font-weight: 700; color: var(--text-muted); }
        .m-state .sd { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
        .m-state.active { color: var(--gain); }
        .m-state.stopping { color: var(--warn); }
        .m-state.paused { color: var(--loss); }
        .m-behave { margin-top: 5px; font-size: 10.5px; line-height: 1.45; color: var(--text-faint); }
        .perf { padding: 14px 20px 18px; display: flex; flex-direction: column; gap: 12px; }
        .lag { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .lag-cell { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px;
                    background: var(--canvas-soft); }
        .lag-k { font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
                 color: var(--text-faint); }
        .lag-v { margin-top: 4px; font-size: 17px; font-weight: 800; }
        .lag-v.ok { color: var(--gain); }
        .lag-v.mid { color: var(--warn); }
        .lag-v.bad { color: var(--loss); }
        .lag-s { margin-top: 2px; font-size: 11px; color: var(--text-muted); }
        .slow { width: 100%; border-collapse: collapse; font-size: 11.5px; }
        .slow th { text-align: left; font-size: 10px; font-weight: 800; letter-spacing: .05em;
                   text-transform: uppercase; color: var(--text-faint); padding: 4px 6px; }
        .slow td { padding: 5px 6px; border-top: 1px solid var(--panel-border); color: var(--text-muted); }
        .slow td.ep { font-family: var(--font-mono, ui-monospace), monospace; font-size: 10.5px;
                      color: var(--text); word-break: break-all; }
      `}</style>
    </div>
  );
}
