"use client";

/*
 * Pre-Live Paper Desk — rebuilt 2026-10-02 after the audit that found:
 *   - no strategy in the 167-strategy library predicts NIFTY's direction (two-year replay:
 *     47.8-48.4% of trades went the bought option's way), so a leaderboard of them ranks luck;
 *   - the leaderboard's top rows were ANTI-<name>: sign flips of the WORST records, never traded;
 *   - "weekly ATM" buys were often monthlies (the instrument master had gone stale), the lot was
 *     75 not 65, fills were at the last traded price, and STT was not charged before 2 Oct.
 * The tournament keeps running as a source of REAL option-premium data; its table is a set of
 * research records, not a ranking. What may ever trade real money now enters through the
 * pre-registered hypotheses on the second tab, and the real-money path stays locked until one
 * of them earns a CONFIRMED forward verdict.
 */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LivePaperBuying from "../../components/LivePaperBuying";
import {
  refreshing,
  type ChainRecorder,
  type LabRun,
  type OptionHypothesis,
  type PreLiveDay,
  type PreLiveRecords,
  type PreLiveStatus,
  type PreLiveTrade,
  type RealMoneyReadiness,
  type VolDeskSummary,
  armRealMoney,
  disarmRealMoney,
  fetchBuyingLab,
  fetchChainRecorder,
  fetchOptionHypotheses,
  fetchPreLiveDaily,
  fetchPreLiveRecords,
  fetchPreLiveStatus,
  fetchPreLiveTrades,
  fetchRealMoney,
  fetchVolDesk,
  killRealMoney,
} from "../../lib/api";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null | undefined, dp = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(dp)}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v >= 0 ? "gain" : "loss");
type Tab = "tournament" | "research" | "livepaper" | "livepaper2L";
const STATUS_TONE: Record<string, string> = {
  CONFIRMED: "ok", INCUBATING: "wait", FAILED: "bad", REJECTED_ON_HISTORY: "bad",
};

export default function PreLivePage() {
  const [tab, setTab] = useState<Tab>("tournament");
  const [status, setStatus] = useState<PreLiveStatus | null>(null);
  const [records, setRecords] = useState<PreLiveRecords | null>(null);
  const [trades, setTrades] = useState<PreLiveTrade[]>([]);
  const [days, setDays] = useState<PreLiveDay[]>([]);
  const [totals, setTotals] = useState<{ sessions?: number; net?: number; real?: number }>({});
  const [hyps, setHyps] = useState<OptionHypothesis[]>([]);
  const [vol, setVol] = useState<VolDeskSummary | null>(null);
  const [lab, setLab] = useState<LabRun | null>(null);
  const [rec, setRec] = useState<ChainRecorder | null>(null);
  const [money, setMoney] = useState<RealMoneyReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [armHyp, setArmHyp] = useState("H1");
  const [phrase, setPhrase] = useState("");
  const [moneyMsg, setMoneyMsg] = useState<string | null>(null);

  const loadTournament = useCallback(async () => {
    const [s, r, t, d] = await Promise.all([fetchPreLiveStatus(), fetchPreLiveRecords(), fetchPreLiveTrades(80), fetchPreLiveDaily(400)]);
    setStatus(s); setRecords(r); setTrades(t.trades); setDays(d.days);
    setTotals({ sessions: d.sessions_total, net: d.total_net, real: d.total_real_net });
  }, []);
  const loadResearch = useCallback(async () => {
    const [h, v, l, c, m] = await Promise.all([
      fetchOptionHypotheses(), fetchVolDesk(), fetchBuyingLab(), fetchChainRecorder(), fetchRealMoney(),
    ]);
    setHyps(h.hypotheses); setVol(v); setLab(l.run); setRec(c); setMoney(m);
  }, []);
  const load = useCallback(async () => {
    try {
      await (tab === "research" ? loadResearch() : loadTournament());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the Pre-Live desk");
    }
  }, [tab, loadResearch, loadTournament]);

  useEffect(() => {
    if (tab === "livepaper" || tab === "livepaper2L") return;
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [tab, load]);

  const handleRefresh = useCallback(async () => {
    setBusy(true);
    try { await refreshing(() => load()); } finally { setBusy(false); }
  }, [load]);

  const doMoney = async (fn: () => Promise<unknown>) => {
    try {
      const r = await fn();
      setMoneyMsg(JSON.stringify(r).slice(0, 300));
      setMoney(await fetchRealMoney());
    } catch (e) {
      setMoneyMsg(e instanceof Error ? e.message : "failed");
    }
  };

  const eng = status?.engine;
  const running = eng?.status === "running";
  const desk = records?.desk;
  const luck = records?.luck;
  const greenDays = days.filter((d) => (d.net_pnl || 0) > 0).length;
  const anyArmable = money?.hypotheses.some((h) => h.can_arm) ?? false;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={busy}
        crumb="Pre-Live Desk"
        title="Pre-Live Paper Desk"
        subtitle="NIFTY option buying on live data and REAL option premiums — paper only. The 167-strategy tournament now runs as a source of real-premium research data; what may ever trade real money enters through the pre-registered hypotheses, judged on real-money (order-book) P&L."
      />

      <div className="desk-tabs">
        <button className={tab === "tournament" ? "dt active" : "dt"} onClick={() => setTab("tournament")}>Tournament · research records</button>
        <button className={tab === "research" ? "dt active" : "dt"} onClick={() => setTab("research")}>Hypotheses &amp; real money</button>
        <button className={tab === "livepaper" ? "dt active" : "dt"} onClick={() => setTab("livepaper")}>Live Paper Buying · ₹50k</button>
        <button className={tab === "livepaper2L" ? "dt active" : "dt"} onClick={() => setTab("livepaper2L")}>Live Paper Trade · ₹2 lakh</button>
      </div>

      {error && <ErrorBanner message={error} />}

      {tab === "livepaper" || tab === "livepaper2L" ? (
        <LivePaperBuying key={tab} book={tab === "livepaper2L" ? "2L" : "50k"} />
      ) : tab === "tournament" ? (
        <>
          <div className="audit">
            <b>Read this first (audit of 2 Oct 2026).</b> Over two years of replay and 45 live sessions, no strategy here
            predicted NIFTY&apos;s direction: the market moved the bought option&apos;s way on{" "}
            {desk ? pct(desk.direction_hit) : "~49%"} of trades — a coin flip. The table below is therefore a set of{" "}
            <b>records, not a ranking</b>: the &ldquo;ANTI-&rdquo; rows that used to top it were sign flips of the worst
            strategies and never traded, and are gone. From 5 Oct every trade also records the order book (bought at the ask,
            sold at the bid) at NIFTY&apos;s real lot of 65, and refuses any contract that is not this week&apos;s expiry.
          </div>

          <div className="tiles">
            <div className="tile">
              <div className="tile-label">Engine</div>
              <div className={`tile-value ${running ? "gain" : ""}`}><span className={`dot ${running ? "live" : "off"}`} /> {eng?.status ?? "offline"}</div>
              <div className="tile-sub">{eng?.heartbeat ? `beat ${new Date(eng.heartbeat).toLocaleTimeString()}` : "no heartbeat"}
                {eng?.weekly_expiry ? ` · trading the ${eng.weekly_expiry} weekly` : ""}</div>
            </div>
            <div className="tile">
              <div className="tile-label">Equity</div>
              <div className={`tile-value ${tone((eng?.equity ?? 0) - (eng?.initial_capital ?? 0))}`}>₹{inr(eng?.equity ?? eng?.balance)}</div>
              <div className="tile-sub">
                {eng?.capital_mode === "tournament"
                  ? `${eng.accounts} accounts × ₹${inr(eng.per_strategy_capital)} = ₹${inr(eng.initial_capital)}`
                  : `from ₹${inr(eng?.initial_capital)}`}
              </div>
            </div>
            <div className="tile">
              <div className="tile-label">Track record</div>
              <div className={`tile-value ${tone(totals.net)}`}>{signed(totals.net)}</div>
              <div className="tile-sub">paper, {totals.sessions ?? days.length} sessions · {greenDays} green</div>
            </div>
            <div className="tile">
              <div className="tile-label">Real-money estimate</div>
              <div className={`tile-value ${tone(desk?.real_net_estimate)}`}>{signed(desk?.real_net_estimate)}</div>
              <div className="tile-sub">same trades at lot 65, ask/bid fills, Angel rate card</div>
            </div>
            <div className="tile">
              <div className="tile-label">Direction hit</div>
              <div className="tile-value">{pct(desk?.direction_hit)}</div>
              <div className="tile-sub">NIFTY moved the option&apos;s way · 50% = coin flip</div>
            </div>
            <div className="tile">
              <div className="tile-label">Luck line</div>
              <div className="tile-value">{luck ? `${luck.observed_t_above_2} vs ${luck.expected_t_above_2_by_chance}` : "–"}</div>
              <div className="tile-sub">strategies with t &gt; 2, observed vs expected by pure chance ({luck?.strategies_with_20_trades ?? 0} with 20+ trades; {luck?.observed_t_below_minus_2 ?? 0} below −2)</div>
            </div>
          </div>

          {desk && (
            <div className="dte">
              <span>Real-money estimate per trade by days to expiry (the instrument master was stale, so many &ldquo;weekly&rdquo; buys were monthlies):</span>
              {Object.entries(desk.by_days_to_expiry).map(([k, v]) => (
                <span key={k} className="chip">{k === "0" ? "expiry day" : `${k} days`}: <b className={tone(v.real_per_trade)}>{signed(v.real_per_trade)}</b> ({v.trades})</span>
              ))}
            </div>
          )}

          {status?.open_positions && status.open_positions.length > 0 && (
            <GlassPanel title="Open paper positions (live-marked)">
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Strategy</th><th>TF</th><th>Leg</th><th>Strike</th><th>Qty</th><th>Entry ₹</th><th>Mark ₹</th><th>Unrealized</th></tr></thead>
                  <tbody>
                    {status.open_positions.map((p) => (
                      <tr key={p.key}>
                        <td className="l">{p.strategy_id}</td><td>{p.timeframe}</td>
                        <td className={p.option_type === "CE" ? "gain" : "loss"}>{p.option_type}</td>
                        <td>{p.strike}</td><td>{p.qty}</td><td>{p.entry_premium}</td><td>{p.mark}</td>
                        <td className={tone(p.unrealized)}>{signed(p.unrealized)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassPanel>
          )}

          <GlassPanel title="Strategy records — research data, not a ranking" note={records ? `${records.strategies.filter((s) => s.trades).length} traded · A–Z` : undefined}>
            <div className="note">{luck?.reading} {records?.real_money_basis ? `Real money: ${records.real_money_basis}.` : ""}</div>
            <div className="table-scroll tall">
              <table className="data-table">
                <thead><tr><th className="l">Strategy</th><th>TF</th><th>Trades</th><th>Paper net</th><th>Per trade</th><th>t</th>
                  <th>Direction hit</th><th>Real / trade</th><th className="l">Days to expiry traded</th></tr></thead>
                <tbody>
                  {(records?.strategies ?? []).filter((s) => s.trades > 0).map((s) => (
                    <tr key={s.key}>
                      <td className="l">{s.strategy_id}</td><td>{s.timeframe}</td><td>{s.trades}</td>
                      <td className={tone(s.net_pnl)}>{signed(s.net_pnl)}</td>
                      <td className={tone(s.per_trade)}>{signed(s.per_trade)}</td>
                      <td className={Math.abs(s.t_stat ?? 0) >= 2 ? "strong" : ""}>{s.t_stat ?? "–"}</td>
                      <td>{s.direction_hit !== null && s.direction_hit !== undefined ? `${pct(s.direction_hit, 0)} (${s.direction_n})` : "–"}</td>
                      <td className={tone(s.real_per_trade)}>{signed(s.real_per_trade)}</td>
                      <td className="l small">{Object.entries(s.dte_mix ?? {}).map(([k, v]) => `${k}:${v}`).join(" · ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassPanel>

          <div className="grid-2">
            <GlassPanel title="Daily P&L history (from the trades)">
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Session</th><th>Trades</th><th>Paper net</th><th>Real est.</th><th>Cumulative paper</th><th>Cumulative real</th></tr></thead>
                  <tbody>
                    {[...days].reverse().map((d) => (
                      <tr key={d.session}>
                        <td>{d.session}{d.daily_doc === false ? " *" : ""}</td><td>{d.trades}</td>
                        <td className={tone(d.net_pnl)}>{signed(d.net_pnl)}</td>
                        <td className={tone(d.real_net)}>{signed(d.real_net)}</td>
                        <td className={tone(d.cumulative_pnl)}>{signed(d.cumulative_pnl)}</td>
                        <td className={tone(d.cumulative_real)}>{signed(d.cumulative_real)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="note">* the daemon had not written a daily record for this session; it was rebuilt from the trades.</div>
            </GlassPanel>

            <GlassPanel title="Recent trades">
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Exit</th><th className="l">Strategy</th><th>Leg</th><th>Expiry</th><th>Entry → exit (LTP)</th><th>Paper</th><th>Real</th></tr></thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.id}>
                        <td className="small">{new Date(t.exit_ts).toLocaleString()}</td>
                        <td className="l">{t.strategy_id}@{t.timeframe}</td>
                        <td className={t.option_type === "CE" ? "gain" : "loss"}>{t.option_type} {t.strike}</td>
                        <td className="small">{t.expiry ?? "–"}</td>
                        <td>{t.entry_premium} → {t.exit_premium}</td>
                        <td className={tone(t.pnl)}>{signed(t.pnl)}</td>
                        <td className={tone(t.real_pnl)}>{t.real_pnl !== undefined ? signed(t.real_pnl) : "–"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassPanel>
          </div>
        </>
      ) : (
        <>
          <GlassPanel title="Pre-registered hypotheses" note="rules and expectations frozen 2 Oct 2026 — judged on forward real-money P&L">
            <div className="hyps">
              {hyps.map((h) => (
                <div key={h.id} className="hyp">
                  <div className="hyp-head"><b>{h.id}</b> {h.name} <span className={`pill ${STATUS_TONE[h.status] ?? ""}`}>{h.status.replace(/_/g, " ")}</span></div>
                  <div className="small">{h.rule}</div>
                  <div className="small muted">Prior: {String((h.expected as Record<string, unknown>).note ?? "")}
                    {typeof (h.expected as Record<string, number>).per_trade_net_mean === "number"
                      ? ` expected ${signed((h.expected as Record<string, number>).per_trade_net_mean)} a trade (research model)` : ""}
                  </div>
                  <div className="small">Forward: {h.forward && Object.keys(h.forward).length
                    ? JSON.stringify(Object.fromEntries(Object.entries(h.forward).filter(([k]) => k !== "evaluated_at")))
                    : "no forward trades yet"}</div>
                </div>
              ))}
            </div>
          </GlassPanel>

          <div className="grid-2">
            <GlassPanel title="Volatility desk — H1 / H1b paper incubation">
              {vol ? (
                <>
                  <div className="kv"><span>Today&apos;s 09:45 signal</span><b>{vol.status.last_decision
                    ? `${vol.status.last_decision.prediction} vs threshold ${vol.status.last_decision.threshold} → ${vol.status.last_decision.flagged ? "TRADE" : "no trade"}`
                    : "not computed yet today"}</b></div>
                  <div className="kv"><span>H1 (intraday)</span><b>{vol.H1.trades} trades · real {signed(vol.H1.real_net)} · paper {signed(vol.H1.paper_net)}</b></div>
                  <div className="kv"><span>H1b (overnight)</span><b>{vol.H1b.trades} trades · real {signed(vol.H1b.real_net)} · paper {signed(vol.H1b.paper_net)}</b></div>
                  {vol.status.last_action && <div className="note">Last action: {vol.status.last_action}</div>}
                  {vol.status.last_error && <div className="note loss">Last error: {vol.status.last_error}</div>}
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead><tr><th>Date</th><th>Prediction</th><th>Flagged</th><th>Next-week expiry</th></tr></thead>
                      <tbody>{vol.decisions.map((d) => (
                        <tr key={d.date}><td>{d.date}</td><td>{d.prediction}</td><td className={d.flagged ? "gain" : ""}>{d.flagged ? "yes" : "no"}</td><td>{d.next_week_expiry ?? "–"}</td></tr>
                      ))}</tbody>
                    </table>
                  </div>
                  {vol.trades.length > 0 && (
                    <div className="table-scroll">
                      <table className="data-table">
                        <thead><tr><th>Closed</th><th>Hyp.</th><th>Expiry</th><th>Paper</th><th>Real</th><th>Basis</th></tr></thead>
                        <tbody>{vol.trades.map((t, i) => (
                          <tr key={i}><td className="small">{new Date(t.closed_at).toLocaleString()}</td><td>{t.hypothesis}</td><td>{t.expiry}</td>
                            <td className={tone(t.paper_pnl)}>{signed(t.paper_pnl)}</td><td className={tone(t.real_pnl)}>{signed(t.real_pnl)}</td><td>{t.real_basis}</td></tr>
                        ))}</tbody>
                      </table>
                    </div>
                  )}
                </>
              ) : <div className="empty">Loading…</div>}
            </GlassPanel>

            <GlassPanel title="Option-chain recorder (real NIFTY prices, every minute)">
              {rec ? (
                <>
                  <div className="kv"><span>Today</span><b>{rec.status.today_rows} minutes recorded · {rec.status.contracts} contracts{rec.status.last_t ? ` · last ${new Date(rec.status.last_t).toLocaleTimeString()}` : ""}</b></div>
                  <div className="kv"><span>Kept so far</span><b>{rec.coverage.days} days{rec.coverage.first ? ` (${rec.coverage.first} → ${rec.coverage.last})` : ""}{rec.coverage.bytes ? ` · ${(rec.coverage.bytes / 1e6).toFixed(1)} MB` : ""}</b></div>
                  <div className="kv"><span>Errors</span><b className={rec.status.errors ? "loss" : ""}>{rec.status.errors}{rec.status.last_error ? ` — ${rec.status.last_error}` : ""}</b></div>
                  <div className="kv"><span>Instrument master</span><b>{rec.instrument_master.last_sync ? `synced ${new Date(rec.instrument_master.last_sync).toLocaleString()}` : "sync pending"} · NIFTY expiries {rec.instrument_master.nifty_expiries.slice(0, 4).join(", ")}</b></div>
                  <div className="note">ATM ±10 strikes of the current and next weekly expiry, calls and puts: best bid and ask with quantities, last price, open interest and volume. Dhan deletes expired contracts, so this is the only real-premium history the Buying Lab will ever have — after about three months it replaces the model.</div>
                </>
              ) : <div className="empty">Loading…</div>}
            </GlassPanel>
          </div>

          <GlassPanel title="Buying Lab v2 — the gate every buying strategy must pass" note={lab ? `run ${lab.run_id} · ${lab.data.from} → ${lab.data.to}` : undefined}>
            {lab ? (
              <>
                <div className="kv"><span>Result</span><b>{lab.passed.length} of {lab.pairs} passed · overfitting probability (PBO) {lab.pbo !== null ? lab.pbo.toFixed(2) : "–"} · direction t &gt; 2: {lab.luck.direction_t_above_2_observed} observed vs {lab.luck.direction_t_above_2_expected_by_chance} by chance</b></div>
                <div className="note">A strategy passes only if NIFTY moves its way significantly before 2026 (t ≥ 2) AND after (t ≥ 1), its deflated Sharpe over all {lab.trials} strategies is ≥ 0.95, PBO ≤ 0.5, it nets money in both periods after spread and fees, with enough trades. Passing makes it a candidate for pre-registration, never a live strategy.</div>
                <div className="table-scroll tall">
                  <table className="data-table">
                    <thead><tr><th className="l">Strategy</th><th>Trades (early / late)</th><th>Direction t (early / late)</th><th>Net / trade (early / late)</th><th>Deflated Sharpe</th><th>Gate</th></tr></thead>
                    <tbody>{lab.rows.map((r) => (
                      <tr key={r.key}>
                        <td className="l">{r.key}</td><td>{r.explore.trades} / {r.holdout.trades}</td>
                        <td>{r.explore.direction_t ?? "–"} / {r.holdout.direction_t ?? "–"}</td>
                        <td><span className={tone(r.explore.net_per_trade)}>{signed(r.explore.net_per_trade)}</span> / <span className={tone(r.holdout.net_per_trade)}>{signed(r.holdout.net_per_trade)}</span></td>
                        <td>{r.dsr ?? "–"}</td>
                        <td className="small">{r.passed ? "PASS" : Object.entries(r.gate).filter(([, v]) => !v).map(([k]) => k.replace(/_/g, " ")).join(", ")}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </>
            ) : <div className="empty">No Buying Lab v2 run stored yet — it runs as a job on the server (python -m app.services.buying_lab_job).</div>}
          </GlassPanel>

          <GlassPanel title="Real money — locked until a hypothesis is CONFIRMED">
            {money ? (
              <>
                <div className="kv"><span>State</span><b className={money.state.armed ? "loss" : ""}>{money.state.armed ? `ARMED for ${money.state.armed_hypothesis}` : "disarmed"} · kill switch {money.state.kill_switch ? "ON" : "off"} · {money.state.dry_run ? "dry run (orders are recorded, never sent)" : "LIVE orders"} · server switch {money.state.env_enabled ? "on" : "off"}</b></div>
                {money.hypotheses.map((h) => (
                  <div key={h.hypothesis} className="kv"><span>{h.hypothesis} · {h.status}</span><b className={h.can_arm ? "gain" : "muted"}>{h.can_arm ? "can be armed" : h.why_not.join("; ")}</b></div>
                ))}
                <div className="note">Every opening order checks: {money.checks.join(" · ")}. Closing orders are always allowed.</div>
                <div className="arm">
                  <select value={armHyp} onChange={(e) => setArmHyp(e.target.value)} disabled={!anyArmable}>
                    {money.hypotheses.map((h) => <option key={h.hypothesis} value={h.hypothesis}>{h.hypothesis}</option>)}
                  </select>
                  <input placeholder={`type "${money.confirm_phrase}"`} value={phrase} onChange={(e) => setPhrase(e.target.value)} disabled={!anyArmable} />
                  <button disabled={!anyArmable} onClick={() => doMoney(() => armRealMoney(armHyp, phrase))}>Arm</button>
                  <button onClick={() => doMoney(() => disarmRealMoney())}>Disarm</button>
                  <button className="danger" onClick={() => doMoney(() => killRealMoney(false))}>Kill switch</button>
                  <button className="danger" onClick={() => { if (window.confirm("Square off every real option position and trip the kill switch?")) doMoney(() => killRealMoney(true)); }}>Panic close all</button>
                </div>
                {moneyMsg && <div className="note">{moneyMsg}</div>}
                <div className="kv"><span>Paper-vs-real slippage</span><b>{money.slippage.fills ? `${money.slippage.mean_slippage_pct}% mean over ${money.slippage.fills} fills (alarm at ${money.slippage.alarm_at_pct}%)` : "no real fills yet"}</b></div>
              </>
            ) : <div className="empty">Loading…</div>}
          </GlassPanel>
        </>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .audit { font-size: 12.5px; line-height: 1.6; color: var(--text-muted); padding: 12px 16px; border-radius: 12px; background: var(--warn-dim); border: 1px solid rgba(185, 119, 14, 0.25); }
        .audit b { color: var(--text); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 6px; font-family: var(--font-data); font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .tile-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); line-height: 1.4; }
        .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .dot.live { background: var(--gain); box-shadow: 0 0 8px var(--gain); }
        .dot.off { background: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .muted { color: var(--text-muted); font-weight: 500; }
        .strong { font-weight: 700; }
        .dte { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; color: var(--text-muted); }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 3px 8px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .table-scroll { overflow-x: auto; max-height: 420px; overflow-y: auto; }
        .table-scroll.tall { max-height: 560px; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table .l { text-align: left; }
        .small { font-size: 11px; }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 6px 2px 10px; line-height: 1.5; }
        .empty { padding: 28px 20px; text-align: center; color: var(--text-faint); font-size: 13px; }
        .desk-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .dt { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .dt.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .hyps { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
        .hyp { border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
        .hyp-head { font-size: 13px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .pill { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: var(--canvas-edge); color: var(--text-muted); }
        .pill.ok { background: var(--gain-dim); color: var(--gain); }
        .pill.wait { background: var(--accent-dim); color: var(--accent-hover); }
        .pill.bad { background: var(--loss-dim); color: var(--loss); }
        .kv { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; padding: 6px 0; border-bottom: 1px solid var(--canvas-soft); }
        .kv span { color: var(--text-muted); white-space: nowrap; }
        .kv b { text-align: right; }
        .arm { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
        .arm select, .arm input { font-size: 12px; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .arm button { font-size: 12px; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .arm button:disabled, .arm select:disabled, .arm input:disabled { opacity: 0.5; cursor: not-allowed; }
        .arm .danger { color: var(--loss); border-color: rgba(217, 45, 63, 0.35); }
      `}</style>
    </div>
  );
}
