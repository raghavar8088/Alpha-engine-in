"use client";

// Premium Strategies (2026-11-06), directly below Gold Desk as asked. The VWAP study: the two setups from
// a "Booming Bulls" VWAP video made exact (NSE-VWAP-01: Original A and B) plus four upgrades (NSE-VWAP-02:
// U1-U4), each pre-registered and tested once on Yahoo 5-minute NSE data with full costs. All numbers come
// from ./data.ts, generated from the saved research results (D:\NSE-Intraday-Research\vwap\export_app_data.py).
// Research only: none of these passed its test, and nothing on this page places or simulates live orders.
import { useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import { PREMIUM, type Version } from "./data";

type Tab = "strategies" | "results" | "november" | "daily" | "method";
const TABS: { id: Tab; label: string }[] = [
  { id: "strategies", label: "Strategies" },
  { id: "results", label: "Results" },
  { id: "november", label: "November 2026" },
  { id: "daily", label: "Day by day" },
  { id: "method", label: "How it was tested" },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${parseInt(iso.slice(8, 10), 10)} ${MONTHS[parseInt(iso.slice(5, 7), 10) - 1]}`;
const sign = (x: number) => (x > 0 ? "+" : x < 0 ? "−" : "");
const pct = (x: number | null | undefined, d = 2) => (x == null ? "—" : `${sign(x)}${Math.abs(x).toFixed(d)}%`);
const num = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${sign(x)}${Math.abs(x).toFixed(d)}`);
const tone = (x: number | null | undefined) => (x == null || x === 0 ? "" : x > 0 ? "ps-pos" : "ps-neg");

function inr(n: number): string {
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

const REASON: Record<string, string> = {
  stop: "Stop",
  stop_gap: "Stop (gap)",
  target: "Target",
  time: "15:10 close",
  vwap_trail: "VWAP trail",
};

const ALL = PREMIUM.versions;
const CARDS = ALL.filter((v) => v.id !== "AB");
const SHORT: Record<string, string> = { A: "Orig A", B: "Orig B", AB: "Orig A+B", U1: "U1", U2: "U2", U3: "U3", U4: "U4" };
const byNov = [...ALL].sort((a, b) => (b.nov.totalPct ?? 0) - (a.nov.totalPct ?? 0));
const byOct = [...ALL].sort((a, b) => (b.oct.totalPct ?? 0) - (a.oct.totalPct ?? 0));
const last = (v: Version) => {
  const c = v.curve.filter((x): x is number => x != null);
  return c.length ? c[c.length - 1] : 0;
};

function Curve({ v }: { v: Version }) {
  const S = PREMIUM.sessions;
  const [hover, setHover] = useState<number | null>(null);
  const W = 320, H = 116, L = 40, R = 8, T = 10, B = 20;
  const vals = v.curve.filter((x): x is number => x != null);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const X = (i: number) => L + (i / (S.length - 1)) * (W - L - R);
  const Y = (y: number) => T + (1 - (y - lo) / span) * (H - T - B);
  let path = "";
  v.curve.forEach((y, i) => {
    if (y != null) path += `${path ? "L" : "M"}${X(i).toFixed(1)},${Y(y).toFixed(1)}`;
  });
  const end = last(v);
  const pick = (clientX: number, el: SVGSVGElement) => {
    const r = el.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(S.length - 1, Math.round(((px - L) / (W - L - R)) * (S.length - 1))));
    setHover(v.curve[i] == null ? null : i);
  };
  const h = hover;
  return (
    <div className="ps-curve">
      <div className="ps-curve-head">
        <span className="ps-curve-name">{v.name}</span>
        <span className={`ps-curve-end ${tone(end)}`}>{pct(end)}</span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="ps-curve-svg"
        role="img"
        aria-label={`${v.name}: cumulative net return ${pct(end)} from ${day(v.firstSession)} to ${day(S[S.length - 1])}`}
        onMouseMove={(e) => pick(e.clientX, e.currentTarget)}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} className="ps-zero" />
        <text x={L - 5} y={Y(hi) + 3} textAnchor="end" className="ps-tick">{pct(hi, 1)}</text>
        {lo < 0 && <text x={L - 5} y={Y(lo) + 3} textAnchor="end" className="ps-tick">{pct(lo, 1)}</text>}
        {hi > 0 && lo < 0 && <text x={L - 5} y={Y(0) + 3} textAnchor="end" className="ps-tick">0%</text>}
        <path d={path} className="ps-line" />
        {h != null && v.curve[h] != null && (
          <>
            <line x1={X(h)} x2={X(h)} y1={T} y2={H - B} className="ps-cross" />
            <circle cx={X(h)} cy={Y(v.curve[h] as number)} r={4} className="ps-dot" />
          </>
        )}
        <text x={L} y={H - 5} className="ps-tick">{day(v.firstSession)}</text>
        <text x={W - R} y={H - 5} textAnchor="end" className="ps-tick">{day(S[S.length - 1])}</text>
      </svg>
      <div className="ps-curve-tip">
        {h != null && v.curve[h] != null ? (
          <>
            <b>{day(S[h])}</b>: {pct(v.curve[h])} so far, {pct(v.daily[h])} that day
          </>
        ) : (
          <span className="ps-faint">Hover the line for any day</span>
        )}
      </div>
    </div>
  );
}

export default function PremiumStrategiesPage() {
  const [tab, setTab] = useState<Tab>("strategies");
  const [tradeFilter, setTradeFilter] = useState<string>("ALL");
  const S = PREMIUM.sessions;
  const NOV = PREMIUM.novSessions;
  const trades = PREMIUM.novTrades.filter((t) => tradeFilter === "ALL" || t.v === tradeFilter);
  const u4 = ALL.find((v) => v.id === "U4");

  return (
    <div className="ps-page">
      <PageHeader
        crumb="Premium Strategies"
        title="Premium Strategies"
        subtitle="Intraday VWAP strategies on NSE stocks: the original two setups from the video and four upgrades, with exact rules and results after all costs."
      />

      <div className="ps-banner" role="note">
        <span className="ps-pill ps-pill-warn">Research only</span>
        <span>
          <b>None of these strategies passed its test, so none is approved for real money.</b> Each was written down
          exactly and tested once on {S.length} sessions ({day(S[0])} – {day(S[S.length - 1])} 2026) on a ₹1 crore
          paper book, with every cost included. U4 comes closest: about break-even over 55 sessions
          ({pct(u4?.main.totalPct ?? null)}). A good week, like November so far, is not evidence on its own.
        </span>
      </div>

      <div className="ps-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`ps-tab${tab === t.id ? " on" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "strategies" && (
        <>
          <div className="ps-cards">
            {CARDS.map((v) => (
              <div key={v.id} className="ps-card">
                <div className="ps-card-top">
                  <span className={`ps-fam ${v.family === "Original" ? "orig" : "up"}`}>{v.family}</span>
                  <span className="ps-pill ps-pill-loss">{v.verdict}</span>
                </div>
                <div className="ps-card-name">{v.name}</div>
                <div className="ps-card-idea">{v.idea}</div>
                <div className="ps-stats">
                  <div>
                    <span className="ps-stat-label">55-session test</span>
                    <span className={`ps-stat-val ${tone(v.main.totalPct)}`}>{pct(v.main.totalPct)}</span>
                  </div>
                  <div>
                    <span className="ps-stat-label">November so far</span>
                    <span className={`ps-stat-val ${tone(v.nov.totalPct)}`}>{pct(v.nov.totalPct)}</span>
                  </div>
                  <div>
                    <span className="ps-stat-label">Trades a day</span>
                    <span className="ps-stat-val">{v.main.perDay ?? "—"}</span>
                  </div>
                </div>
                <div className="ps-card-note">{v.note}</div>
                <details className="ps-rules">
                  <summary>Exact rules</summary>
                  <dl>
                    {v.rules.map((r) => (
                      <div key={r.label} className="ps-rule">
                        <dt>{r.label}</dt>
                        <dd>{r.text}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </div>
            ))}
          </div>
          <GlassPanel title="Rules every strategy shares">
            <dl className="ps-common">
              {PREMIUM.common.map((r) => (
                <div key={r.label} className="ps-rule">
                  <dt>{r.label}</dt>
                  <dd>{r.text}</dd>
                </div>
              ))}
            </dl>
          </GlassPanel>
        </>
      )}

      {tab === "results" && (
        <>
          <GlassPanel title="Main test — 55 sessions, 18 Aug – 5 Nov 2026" note="₹1 crore book · after all costs">
            <div className="ps-scroll">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Per day</th>
                    <th>Win rate</th>
                    <th title="Average result per trade before costs, in basis points (1 bp = 0.01%)">Before costs</th>
                    <th title="Average result per trade after all costs, in basis points">After costs</th>
                    <th>Total</th>
                    <th>1st half</th>
                    <th>2nd half</th>
                    <th>2× slippage</th>
                    <th>Max drawdown</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {ALL.map((v) => (
                    <tr key={v.id}>
                      <td className="ps-name">{v.name}</td>
                      <td>{v.main.trades.toLocaleString("en-US")}</td>
                      <td>{v.main.perDay ?? "—"}</td>
                      <td>{v.main.winRate == null ? "—" : `${v.main.winRate.toFixed(1)}%`}</td>
                      <td className={tone(v.main.grossBp)}>{num(v.main.grossBp)} bp</td>
                      <td className={tone(v.main.netBp)}>{num(v.main.netBp)} bp</td>
                      <td className={`ps-strong ${tone(v.main.totalPct)}`}>{pct(v.main.totalPct)}</td>
                      <td className={tone(v.main.half1)}>{pct(v.main.half1)}</td>
                      <td className={tone(v.main.half2)}>{pct(v.main.half2)}</td>
                      <td className={tone(v.main.slip2xPct)}>{pct(v.main.slip2xPct)}</td>
                      <td>{v.main.maxDdPct == null ? "—" : `${v.main.maxDdPct.toFixed(1)}%`}</td>
                      <td><span className="ps-pill ps-pill-loss">{v.verdict}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ps-foot">
              The original&apos;s own pre-registered test ran on 60 sessions (11 Aug – 5 Nov): A {pct(PREMIUM.original60.A)}, B{" "}
              {pct(PREMIUM.original60.B)}, A+B {pct(PREMIUM.original60.AB)}. It is shown here on the same 55 sessions as the
              upgrades, whose first 5 sessions were a volume warm-up. A strategy needed all of: a profit after costs, a
              significant result, both halves positive, and a profit at 2× slippage. None met them.
            </p>
          </GlassPanel>

          <GlassPanel title="Cumulative return, after costs" note={`${day(S[0])} – ${day(S[S.length - 1])} · % of ₹1 crore`}>
            <div className="ps-curves">
              {ALL.map((v) => (
                <Curve key={v.id} v={v} />
              ))}
            </div>
            <p className="ps-foot">Each chart has its own scale; read the labels before comparing shapes.</p>
          </GlassPanel>

          <GlassPanel title="October 2026 — 20 sessions" note="every strategy lost">
            <div className="ps-scroll">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Win rate</th>
                    <th>Net P&amp;L</th>
                    <th>Return</th>
                    <th>Up / down days</th>
                  </tr>
                </thead>
                <tbody>
                  {byOct.map((v) => (
                    <tr key={v.id}>
                      <td className="ps-name">{v.name}</td>
                      <td>{v.oct.trades}</td>
                      <td>{v.oct.winRate == null ? "—" : `${v.oct.winRate.toFixed(1)}%`}</td>
                      <td className={tone(v.oct.netRs)}>{inr(v.oct.netRs)}</td>
                      <td className={`ps-strong ${tone(v.oct.totalPct)}`}>{pct(v.oct.totalPct)}</td>
                      <td>{v.oct.upDays} / {v.oct.downDays}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        </>
      )}

      {tab === "november" && (
        <>
          <GlassPanel title={`November 2026 so far — ${NOV.length} sessions, ${day(NOV[0])} – ${day(NOV[NOV.length - 1])}`} note="ranked by return">
            <div className="ps-scroll">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Win rate</th>
                    <th>Net P&amp;L</th>
                    <th>Return</th>
                    <th>Up / down days</th>
                    <th>Best day</th>
                    <th>Worst day</th>
                  </tr>
                </thead>
                <tbody>
                  {byNov.map((v) => (
                    <tr key={v.id}>
                      <td className="ps-name">{v.name}</td>
                      <td>{v.nov.trades}</td>
                      <td>{v.nov.winRate == null ? "—" : `${v.nov.winRate.toFixed(1)}%`}</td>
                      <td className={tone(v.nov.netRs)}>{inr(v.nov.netRs)}</td>
                      <td className={`ps-strong ${tone(v.nov.totalPct)}`}>{pct(v.nov.totalPct)}</td>
                      <td>{v.nov.upDays} / {v.nov.downDays}</td>
                      <td className={tone(v.nov.bestDay)}>{pct(v.nov.bestDay)}</td>
                      <td className={tone(v.nov.worstDay)}>{pct(v.nov.worstDay)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ps-foot">
              One week is far too short to judge. Original A made {pct(ALL.find((v) => v.id === "A")?.nov.totalPct)} this week but{" "}
              {pct(ALL.find((v) => v.id === "A")?.oct.totalPct)} in October. Only 6 Nov is new data; the other days were already
              part of the main test.
            </p>
          </GlassPanel>

          <GlassPanel title="Day by day" note="% of ₹1 crore">
            <div className="ps-scroll">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    {NOV.map((d) => (
                      <th key={d}>{day(d)}</th>
                    ))}
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {byNov.map((v) => (
                    <tr key={v.id}>
                      <td className="ps-name">{v.name}</td>
                      {v.nov.daily.map((x, i) => (
                        <td key={NOV[i]} className={tone(x)}>{pct(x)}</td>
                      ))}
                      <td className={`ps-strong ${tone(v.nov.totalPct)}`}>{pct(v.nov.totalPct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ps-foot">Original A+B is not A plus B: both setups compete for the same 4 position slots.</p>
          </GlassPanel>

          <GlassPanel title={`Every November trade — ${trades.length}`} note="paper book, after costs">
            <div className="ps-chips">
              {["ALL", ...CARDS.map((v) => v.id)].map((id) => (
                <button key={id} className={`ps-chip${tradeFilter === id ? " on" : ""}`} onClick={() => setTradeFilter(id)}>
                  {id === "ALL" ? "All" : SHORT[id]}
                </button>
              ))}
            </div>
            <div className="ps-scroll ps-tall">
              <table className="ps-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Strategy</th>
                    <th>Stock</th>
                    <th>Side</th>
                    <th>In</th>
                    <th>Out</th>
                    <th>Entry ₹</th>
                    <th>Exit ₹</th>
                    <th>Net P&amp;L</th>
                    <th>Exit</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t, i) => (
                    <tr key={`${t.v}-${t.date}-${t.sym}-${t.inAt}-${i}`}>
                      <td>{day(t.date)}</td>
                      <td>{SHORT[t.v] ?? t.v}</td>
                      <td className="ps-name">{t.sym}</td>
                      <td>{t.side > 0 ? "Long" : "Short"}</td>
                      <td>{t.inAt}</td>
                      <td>{t.outAt}</td>
                      <td>{t.inPx == null ? "—" : t.inPx.toFixed(2)}</td>
                      <td>{t.outPx == null ? "—" : t.outPx.toFixed(2)}</td>
                      <td className={tone(t.netRs)}>{inr(t.netRs)}</td>
                      <td>{REASON[t.why] ?? t.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ps-foot">Times are 5-minute candles: entry at that candle&apos;s open; a stop or target fills inside its exit candle.</p>
          </GlassPanel>
        </>
      )}

      {tab === "daily" && (
        <GlassPanel title={`Every session — ${S.length}`} note="daily return, % of ₹1 crore, newest first">
          <div className="ps-scroll ps-tall">
            <table className="ps-table">
              <thead>
                <tr>
                  <th>Date</th>
                  {ALL.map((v) => (
                    <th key={v.id}>{SHORT[v.id]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="ps-total">
                  <td>Total</td>
                  {ALL.map((v) => (
                    <td key={v.id} className={tone(last(v))}>{pct(last(v))}</td>
                  ))}
                </tr>
                {S.map((_, k) => S.length - 1 - k).map((i) => (
                  <tr key={S[i]}>
                    <td>{day(S[i])}</td>
                    {ALL.map((v) => (
                      <td key={v.id} className={tone(v.daily[i])}>{v.daily[i] == null ? "—" : pct(v.daily[i])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ps-foot">U1–U4 start on {day("2026-08-18")}: their first 5 sessions were the volume warm-up.</p>
        </GlassPanel>
      )}

      {tab === "method" && (
        <GlassPanel title="How these were tested">
          <ul className="ps-list">
            <li>
              <b>Rules first, results second.</b> Each set of rules was written down and fingerprinted (SHA-256) before its
              test ran: the original <code>{PREMIUM.hashes.original}…</code>, the upgrades <code>{PREMIUM.hashes.upgrades}…</code>.
              Each test ran once, and no rule was changed after seeing results.
            </li>
            <li>
              <b>Data.</b> Yahoo 5-minute candles for about 500 NSE stocks, 11 Aug – 6 Nov 2026, converted to official
              rupee prices and checked against NSE&apos;s own daily high and low. Liquidity ranks come from NSE bhavcopies.
            </li>
            <li>
              <b>Book.</b> ₹1 crore of paper capital, ₹25,000 risk per trade, at most 4 positions open. Returns are not
              compounded; 1% = ₹1 lakh.
            </li>
            <li>
              <b>Costs.</b> STT, stamp duty, exchange and SEBI fees, GST and ₹20 brokerage per order, plus 3–5 bp of
              slippage per side. Fills are conservative: a candle touching both stop and target counts as the stop.
            </li>
            <li>
              <b>The upgrades are in-sample.</b> U1–U4 were designed after seeing the original fail on the same sessions,
              so even a pass would only have earned a paper test on new days.
            </li>
            <li>
              <b>Limits.</b> 61 sessions is short. Yahoo reports no volume for the 09:15 candle, so it is estimated. Only
              stocks were tested, not index options. Nothing on this page trades: it is a record of the research.
            </li>
          </ul>
          <p className="ps-foot">Data generated {PREMIUM.generated}.</p>
        </GlassPanel>
      )}

      <style jsx global>{`
        .ps-page { display: flex; flex-direction: column; gap: 16px; }
        .ps-banner { display: flex; gap: 12px; align-items: flex-start; padding: 12px 16px; border-radius: 10px;
                     background: var(--warn-dim); border: 1px solid var(--panel-border); font-size: 13px; line-height: 1.6;
                     color: var(--text-muted); }
        .ps-banner b { color: var(--text); }
        .ps-pill { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 800;
                   white-space: nowrap; letter-spacing: 0.01em; }
        .ps-pill-warn { background: var(--warn); color: #fff; }
        .ps-pill-loss { background: var(--loss-dim); color: var(--loss); }
        .ps-tabs { display: flex; flex-wrap: wrap; gap: 6px; border-bottom: 1px solid var(--panel-border); }
        .ps-tab { background: none; border: none; border-bottom: 2px solid transparent; padding: 9px 14px; font-size: 13px;
                  font-weight: 700; color: var(--text-muted); cursor: pointer; margin-bottom: -1px; }
        .ps-tab:hover { color: var(--text); }
        .ps-tab.on { color: var(--purple); border-bottom-color: var(--purple); }
        .ps-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
        .ps-card { display: flex; flex-direction: column; gap: 10px; padding: 16px; border-radius: 14px; background: var(--panel);
                   border: 1px solid var(--panel-border); }
        .ps-card-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .ps-fam { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 8px;
                  border-radius: 6px; }
        .ps-fam.orig { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .ps-fam.up { background: var(--purple-dim); color: var(--purple); }
        .ps-card-name { font-size: 16px; font-weight: 800; color: var(--text); }
        .ps-card-idea { font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        .ps-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 10px 0;
                    border-top: 1px solid var(--panel-border); border-bottom: 1px solid var(--panel-border); }
        .ps-stats > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
        .ps-stat-label { font-size: 10.5px; color: var(--text-faint); font-weight: 700; }
        .ps-stat-val { font-size: 16px; font-weight: 800; color: var(--text); }
        .ps-card-note { font-size: 12px; line-height: 1.5; color: var(--text-muted); }
        .ps-rules summary { cursor: pointer; font-size: 12.5px; font-weight: 800; color: var(--purple); }
        .ps-rules dl, .ps-common { margin: 10px 0 0; display: flex; flex-direction: column; gap: 8px; }
        .ps-rule { display: grid; grid-template-columns: 96px 1fr; gap: 10px; font-size: 12.5px; line-height: 1.55; }
        .ps-rule dt { font-weight: 800; color: var(--text); }
        .ps-rule dd { margin: 0; color: var(--text-muted); }
        .ps-scroll { overflow-x: auto; }
        .ps-tall { max-height: 520px; overflow-y: auto; }
        .ps-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .ps-table th { text-align: right; font-size: 10.5px; font-weight: 800; color: var(--text-muted); text-transform: uppercase;
                       letter-spacing: 0.04em; padding: 8px 10px; border-bottom: 1px solid var(--panel-border); white-space: nowrap;
                       position: sticky; top: 0; background: var(--panel); }
        .ps-table td { text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--panel-border); white-space: nowrap;
                       color: var(--text); }
        .ps-table th:first-child, .ps-table td:first-child { text-align: left; }
        .ps-table tbody tr:hover td { background: var(--canvas-soft); }
        .ps-name { font-weight: 700; }
        .ps-strong { font-weight: 800; }
        .ps-total td { font-weight: 800; background: var(--canvas-soft); }
        .ps-pos { color: var(--gain) !important; }
        .ps-neg { color: var(--loss) !important; }
        .ps-faint { color: var(--text-faint); }
        .ps-foot { margin: 12px 0 0; font-size: 12px; line-height: 1.55; color: var(--text-muted); }
        .ps-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
        .ps-chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 6px 12px;
                   border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .ps-chip.on { color: var(--purple); border-color: var(--purple); background: var(--purple-dim); }
        .ps-curves { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
        .ps-curve { padding: 12px; border-radius: 12px; border: 1px solid var(--panel-border); background: var(--panel); }
        .ps-curve-head { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
        .ps-curve-name { font-size: 12.5px; font-weight: 800; color: var(--text); }
        .ps-curve-end { font-size: 14px; font-weight: 800; }
        .ps-curve-svg { width: 100%; height: auto; display: block; margin-top: 6px; cursor: crosshair; }
        .ps-zero { stroke: var(--panel-border-hover); stroke-width: 1; }
        .ps-line { fill: none; stroke: var(--purple); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
        .ps-cross { stroke: var(--text-faint); stroke-width: 1; }
        .ps-dot { fill: var(--purple); stroke: var(--panel); stroke-width: 2; }
        .ps-tick { font-size: 9.5px; fill: var(--text-faint); font-variant-numeric: tabular-nums; }
        .ps-curve-tip { min-height: 18px; margin-top: 4px; font-size: 11.5px; color: var(--text-muted); }
        .ps-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 10px; font-size: 13px; line-height: 1.6;
                   color: var(--text-muted); }
        .ps-list b { color: var(--text); }
        .ps-list code { font-size: 12px; background: var(--canvas-soft); padding: 1px 5px; border-radius: 4px; }
        @media (max-width: 640px) {
          .ps-banner { flex-direction: column; }
          .ps-rule { grid-template-columns: 1fr; gap: 2px; }
        }
      `}</style>
    </div>
  );
}
