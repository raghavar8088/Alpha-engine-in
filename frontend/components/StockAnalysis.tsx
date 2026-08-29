"use client";

/**
 * Stock Analysis — paste names, get a verdict per stock with the argument behind it.
 *
 * TWO COLUMNS, NOT ONE. `bias` is where the chart points; `action` is whether to buy
 * today. Collapsing them into a single "good to buy?" is the most misleading thing this
 * screen could do — IOLCP scores 83 on the chart and is still Avoid, because it is under
 * ASM and the margin rules can change under the position. The table shows both, side by
 * side, so a bullish-but-untouchable stock reads as exactly that.
 *
 * Every score expands into the five pillars that produced it, each with a written note.
 * A reader has to be able to disagree with one step rather than the whole verdict.
 */

import { useCallback, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import { copySymbols } from "../lib/copySymbols";
import { Th, Select, SearchBox, FilterBar, cmp, SortState } from "./TableControls";
import { analyseStocks, AnalysisResult, AnalysisRow } from "../lib/api";

const BIAS_TONE: Record<string, string> = {
  Bullish: "ok", Neutral: "mid", Bearish: "bad",
};
const ACTION_TONE: Record<string, string> = {
  Buy: "ok", Watch: "mid", Avoid: "bad",
};
const PILLAR_LABEL: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", volume: "Volume & delivery",
  structure: "Position in range", tradability: "Can you trade it",
};

type SortKey = "symbol" | "score" | "bias" | "action" | "ltp" | "r1w" | "r1m" | "r6m";

const BIAS_OPTS: [string, string][] = [
  ["any", "any"], ["Bullish", "Bullish"], ["Neutral", "Neutral"], ["Bearish", "Bearish"],
];
const ACTION_OPTS: [string, string][] = [
  ["any", "any"], ["Buy", "Buy"], ["Watch", "Watch"], ["Avoid", "Avoid"],
];
const SCORE_OPTS: [string, string][] = [
  ["0", "any"], ["60", "60+"], ["70", "70+"], ["80", "80+"], ["90", "90+"],
];

const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const cls = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "gain" : v < 0 ? "loss" : "";

export default function StockAnalysis() {
  const [raw, setRaw] = useState("");
  const [res, setRes] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [bias, setBias] = useState("any");
  const [action, setAction] = useState("any");
  const [minScore, setMinScore] = useState("0");
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "score", dir: -1 });
  const [copied, setCopied] = useState<"tv" | "plain" | null>(null);

  const run = useCallback(async (fresh = false) => {
    if (!raw.trim()) return;
    setBusy(true); setErr(null);
    try { setRes(await analyseStocks(raw, fresh)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }, [raw]);

  const activeFilters = [q.trim(), bias, action, minScore]
    .filter((v, i) => (i === 0 ? !!v : v !== "any" && v !== "0")).length;
  const clearFilters = () => {
    setQ(""); setBias("any"); setAction("any"); setMinScore("0");
  };

  const rows = (res?.rows ?? [])
    .filter((r) => {
      const needle = q.trim().toUpperCase();
      if (needle && !r.symbol.includes(needle)
          && !(r.name ?? "").toUpperCase().includes(needle)) return false;
      if (bias !== "any" && r.verdict?.bias !== bias) return false;
      if (action !== "any" && r.verdict?.action !== action) return false;
      if (Number(minScore) && (r.verdict?.score ?? 0) < Number(minScore)) return false;
      return true;
    })
    .sort((a, b) => {
      const { key, dir } = sort;
      const pick = (r: AnalysisRow) =>
        key === "symbol" ? r.symbol
        : key === "score" ? r.verdict?.score
        : key === "bias" ? r.verdict?.bias
        : key === "action" ? r.verdict?.action
        : key === "ltp" ? r.ltp
        : key === "r1w" ? r.returns?.["1w"]
        : key === "r1m" ? r.returns?.["1m"]
        : r.returns?.["6m"];
      return cmp(pick(a), pick(b), dir);
    });

  // Copies the filtered view, so "Buy only" then copy hands you exactly the shortlist.
  const copy = async (fmt: "tv" | "plain") => {
    await copySymbols(rows.map((r) => r.symbol), fmt);
    setCopied(fmt);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div className="sa">
      <GlassPanel title="Analyse stocks">
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={4}
          spellCheck={false}
          placeholder={"One symbol or a whole list — commas, spaces or newlines.\n\nTITAN\nBHEL, IOLCP, PVP\nNSE:PRECWIRE, NSE:GLENMARK"}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run(); }}
        />
        <div className="bar">
          <button className="go" disabled={busy || !raw.trim()} onClick={() => run()}>
            {busy ? "Analysing…" : "Submit"}
          </button>
          {res && (
            <button className="re" disabled={busy} onClick={() => run(true)}>
              Re-run fresh
            </button>
          )}
          <span className="hint">
            ⌘/Ctrl + ⏎. Up to 40 at a time. A name with no stored history is fetched from
            Angel on the spot, so the first run on an unusual stock takes a little longer.
          </span>
        </div>
      </GlassPanel>

      {err && <div className="err">{err}</div>}

      {busy && !res && (
        <GlassPanel title="Working">
          <div className="sk">{Array.from({ length: 6 }).map((_, i) =>
            <Skeleton key={i} height={28} />)}</div>
        </GlassPanel>
      )}

      {res && (
        <GlassPanel
          title="Verdicts"
          note={activeFilters
            ? `${rows.length} of ${res.analysed} shown`
            : `${res.analysed} of ${res.count} analysed`}
        >
          {res.fetch_note && <div className="warn">{res.fetch_note}</div>}

          <div className="legend">
            <b>Bias</b> is where the chart points. <b>Action</b> is whether to put money in
            today. They are deliberately separate — a stock can be in a clean uptrend and
            still be a poor buy because it is extended past its breakout, or sits in a
            circuit band where a stop cannot fill. Action is never better than tradability
            allows.
          </div>

          <FilterBar active={activeFilters} onClear={clearFilters}>
            <SearchBox value={q} onChange={setQ} placeholder="Find a stock…" />
            <Select label="Bias" value={bias} onChange={setBias} options={BIAS_OPTS} />
            <Select label="Action" value={action} onChange={setAction} options={ACTION_OPTS} />
            <Select label="Score" value={minScore} onChange={setMinScore} options={SCORE_OPTS} />
          </FilterBar>

          <div className="filters">
            <button className="preset"
              onClick={() => { clearFilters(); setAction("Buy"); }}>
              Buyable only
            </button>
            <button className="preset"
              onClick={() => { clearFilters(); setAction("Buy"); setMinScore("80"); }}>
              Best scoring buys
            </button>
            <div className="copies">
              <button className="cp primary" disabled={!rows.length}
                onClick={() => copy("tv")}
                title="NSE:SYM,NSE:SYM — paste into a TradingView watchlist, or into the All Time High watchlist">
                {copied === "tv" ? `copied ${rows.length} ✓` : "copy for TradingView"}
              </button>
              <button className="cp" disabled={!rows.length}
                onClick={() => copy("plain")} title="Bare tickers, comma separated">
                {copied === "plain" ? "copied ✓" : "plain"}
              </button>
            </div>
          </div>

          {!rows.length ? (
            <EmptyState title="Nothing matches those filters"
              note={activeFilters ? "Loosen a filter to see the rest." : undefined} />
          ) : (
            <div className="tw">
              <table>
                <thead><tr>
                  <Th k="symbol" sort={sort} setSort={setSort} align="l">Stock</Th>
                  <Th k="score" sort={sort} setSort={setSort} numeric>Score</Th>
                  <Th k="bias" sort={sort} setSort={setSort} align="l">Bias</Th>
                  <Th k="action" sort={sort} setSort={setSort} align="l">Action</Th>
                  <Th k="ltp" sort={sort} setSort={setSort} numeric>LTP</Th>
                  <Th k="r1w" sort={sort} setSort={setSort} numeric>1w</Th>
                  <Th k="r1m" sort={sort} setSort={setSort} numeric>1m</Th>
                  <Th k="r6m" sort={sort} setSort={setSort} numeric>6m</Th>
                  <th className="l">Why</th><th></th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <RowView key={r.symbol} r={r}
                      open={open === r.symbol}
                      toggle={() => setOpen(open === r.symbol ? null : r.symbol)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .sa { display: flex; flex-direction: column; gap: 16px; }
        textarea {
          width: 100%; padding: 10px 12px; border-radius: 9px; resize: vertical;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-primary); font-size: 13px; line-height: 1.6;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        textarea:focus { outline: none; border-color: var(--accent); }
        .bar { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .go {
          padding: 8px 24px; border-radius: 8px; font-size: 13px; font-weight: 600;
          border: 1px solid var(--accent); background: var(--accent); color: #fff;
          cursor: pointer;
        }
        .go:disabled { opacity: 0.45; cursor: default; }
        .re {
          padding: 8px 14px; border-radius: 8px; font-size: 12.5px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary);
        }
        .hint { font-size: 11.5px; color: var(--text-muted); flex: 1 1 300px; line-height: 1.5; }
        .err {
          border: 1px solid var(--loss); background: rgba(220,38,38,0.08);
          color: var(--loss); border-radius: 10px; padding: 10px 14px; font-size: 12.5px;
        }
        .warn {
          border: 1px solid rgba(217,119,6,0.35); background: rgba(217,119,6,0.08);
          color: #b45309; border-radius: 9px; padding: 9px 12px; font-size: 12px;
          margin-bottom: 10px;
        }
        .legend {
          font-size: 12px; line-height: 1.6; color: var(--text-muted);
          border: 1px solid var(--border); border-radius: 10px; padding: 10px 13px;
          margin-bottom: 12px; max-width: 94ch; background: var(--canvas-soft);
        }
        .legend b { color: var(--text-primary); }
        .filters { display: flex; gap: 7px; margin-bottom: 12px; }
        .filters button {
          padding: 5px 13px; border-radius: 999px; font-size: 12px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary);
        }
        .filters .preset {
          border-color: var(--accent); color: var(--accent); font-weight: 600;
        }
        .copies { margin-left: auto; display: flex; gap: 6px; }
        .cp {
          padding: 5px 13px; border-radius: 8px; font-size: 11.5px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary); white-space: nowrap;
        }
        .cp.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
        .cp:hover:not(:disabled) { border-color: var(--accent); color: var(--text-primary); }
        .cp:disabled { opacity: 0.4; cursor: default; }
        .sk { display: flex; flex-direction: column; gap: 8px; }
        .tw { overflow-x: auto; }
        .tw table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        /* :global because the sortable headers are rendered by the shared Th component,
           and styled-jsx scopes plain selectors to this file's own JSX only. */
        .tw :global(th) {
          text-align: right; padding: 8px 10px; font-weight: 600; font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted);
          border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        .tw :global(th.l) { text-align: left; }
      `}</style>
    </div>
  );
}

function RowView({ r, open, toggle }: { r: AnalysisRow; open: boolean; toggle: () => void }) {
  const v = r.verdict;
  return (
    <>
      <tr className={!r.analysed ? "dead" : ""}>
        <td className="l sym">
          <b>{r.symbol}</b>
          {r.market_cap_cr ? <div className="sub">₹{r.market_cap_cr.toLocaleString("en-IN")}cr</div> : null}
        </td>
        <td>{v ? <span className={`sc ${v.score >= 72 ? "ok" : v.score >= 50 ? "mid" : "bad"}`}>{v.score}</span> : "—"}</td>
        <td className="l">{v ? <span className={`tag ${BIAS_TONE[v.bias]}`}>{v.bias}</span> : "—"}</td>
        <td className="l">{v ? <span className={`tag ${ACTION_TONE[v.action]}`}>{v.action}</span> : "—"}</td>
        <td>{num(r.ltp)}</td>
        <td className={cls(r.returns?.["1w"])}>{pct(r.returns?.["1w"])}</td>
        <td className={cls(r.returns?.["1m"])}>{pct(r.returns?.["1m"])}</td>
        <td className={cls(r.returns?.["6m"])}>{pct(r.returns?.["6m"])}</td>
        <td className="l why">{v ? v.action_why : r.note}</td>
        <td>{r.analysed && <button className="exp" onClick={toggle}>{open ? "hide" : "detail"}</button>}</td>
      </tr>
      {open && r.analysed && <DetailRow r={r} />}

      <style jsx>{`
        td {
          text-align: right; padding: 9px 10px; vertical-align: top;
          border-bottom: 1px solid var(--border-soft, var(--border));
          color: var(--text-secondary);
        }
        td.l { text-align: left; }
        td.sym { white-space: nowrap; }
        td.sym b { color: var(--text-primary); font-weight: 650; }
        .sub { font-size: 10px; color: var(--text-faint); font-weight: 400; }
        td.why { color: var(--text-muted); font-size: 11.5px; line-height: 1.5; min-width: 250px; max-width: 480px; }
        tr.dead td { opacity: 0.65; }
        .sc {
          display: inline-block; min-width: 32px; padding: 2px 8px; border-radius: 6px;
          font-weight: 700; font-size: 12px;
        }
        .sc.ok { background: rgba(22,163,74,0.14); color: var(--gain); }
        .sc.mid { background: rgba(217,119,6,0.13); color: #b45309; }
        .sc.bad { background: rgba(220,38,38,0.13); color: var(--loss); }
        .tag {
          display: inline-block; padding: 2px 10px; border-radius: 999px;
          font-size: 11.5px; font-weight: 600; white-space: nowrap;
        }
        .tag.ok { background: rgba(22,163,74,0.14); color: var(--gain); }
        .tag.mid { background: rgba(217,119,6,0.13); color: #b45309; }
        .tag.bad { background: rgba(220,38,38,0.13); color: var(--loss); }
        .exp {
          padding: 3px 10px; border-radius: 6px; font-size: 11px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas);
          color: var(--text-secondary);
        }
        .gain { color: var(--gain); font-weight: 600; }
        .loss { color: var(--loss); font-weight: 600; }
      `}</style>
    </>
  );
}

function DetailRow({ r }: { r: AnalysisRow }) {
  const lv = r.levels ?? {};
  const t = r.next_target;
  return (
    <tr className="detail">
      <td colSpan={10}>
        <div className="grid">
          {/* pillars */}
          <div className="card wide">
            <h4>What the verdict rests on</h4>
            {Object.entries(r.pillars ?? {}).map(([k, p]) => (
              <div key={k} className={`pill ${p.verdict}`}>
                <div className="ph">
                  <span className="dot" />
                  <b>{PILLAR_LABEL[k] ?? k}</b>
                  <span className="ps">{p.score}</span>
                </div>
                <div className="pn">{p.note}</div>
              </div>
            ))}
          </div>

          {/* levels */}
          <div className="card">
            <h4>Levels</h4>
            <Kv k="20 / 50 / 200 DMA" v={`${num(lv.sma20)} · ${num(lv.sma50)} · ${num(lv.sma200)}`} />
            <Kv k="RSI(14)" v={num(lv.rsi14, 1)} />
            <Kv k="ATR" v={`${num(lv.atr14)} (${num(lv.atr_pct, 1)}%)`} />
            <Kv k="52-week range" v={`${num(lv.week52_low)} – ${num(lv.week52_high)}`} />
            <Kv k="From 52w high" v={pct(lv.pct_from_52w_high)} />
            <Kv k="All-time high" v={num(lv.all_time_high)} />
            <Kv k="20-day breakout level" v={num(lv.breakout_level_20d)} />
            <Kv k="Extension past it" v={pct(lv.extension_pct)} />
            <Kv k="Swing low / resistance" v={`${num(lv.swing_low)} / ${num(lv.resistance)}`} />
          </div>

          {/* target + plan */}
          <div className="card">
            <h4>Next target</h4>
            {t?.target ? (
              <>
                <div className="big">{num(t.target)} <i>{pct(t.upside_pct)}</i></div>
                <div className="meth">{t.method} · <span className={`str ${t.strength}`}>{t.strength}</span></div>
                {t.note && <div className="meth">{t.note}</div>}
              </>
            ) : <div className="none">No level worth naming above here.</div>}

            <h4 style={{ marginTop: 14 }}>Swing plan</h4>
            {r.plan ? (
              <>
                <Kv k="Entry" v={num(r.plan.entry)} />
                <Kv k="Stop" v={`${num(r.plan.stop)} (${pct(r.plan.stop_pct)})`} />
                <Kv k="Target" v={`${num(r.plan.target)} (${pct(r.plan.target_pct)})`} />
                {r.plan.quantity ? <Kv k="Qty @ ₹50k" v={String(r.plan.quantity)} /> : null}
                <div className="meth">{r.plan.horizon} · costed on the delivery schedule</div>
              </>
            ) : <div className="none">No plan — not enough volatility data.</div>}
          </div>

          {/* cross-checks */}
          <div className="card">
            <h4>Cross-checks</h4>
            <div className="sub2">Chartink screens listing it now</div>
            {r.screens.length ? (
              <div className="chips">{r.screens.map((s) => <span key={s}>{s}</span>)}</div>
            ) : <div className="none">None of the screens we check.</div>}

            <div className="sub2" style={{ marginTop: 12 }}>Chart patterns</div>
            {r.patterns?.length ? (
              <div className="chips">
                {r.patterns.map((p, i) => (
                  <span key={i} className={p.direction === "bullish" ? "up" : "dn"}>
                    {p.label}<i>{p.timeframe} · {p.state}</i>
                  </span>
                ))}
              </div>
            ) : <div className="none">No pattern formed or forming.</div>}

            {r.reasons?.length ? (
              <>
                <div className="sub2" style={{ marginTop: 12 }}>Notes</div>
                <ul>{r.reasons.map((x, i) => <li key={i}>{x.text}</li>)}</ul>
              </>
            ) : null}
          </div>
        </div>
      </td>

      <style jsx>{`
        .detail td { background: var(--canvas-soft); padding: 14px; text-align: left; }
        .grid {
          display: grid; gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
          align-items: start;
        }
        .card {
          border: 1px solid var(--border); border-radius: 11px;
          padding: 12px 14px; background: var(--canvas);
        }
        .card.wide { grid-column: span 1; }
        h4 {
          margin: 0 0 9px; font-size: 11px; text-transform: uppercase;
          letter-spacing: 0.05em; color: var(--text-muted); font-weight: 700;
        }
        .pill { padding: 7px 0; border-bottom: 1px solid var(--border-soft, var(--border)); }
        .pill:last-child { border-bottom: none; }
        .ph { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-primary); }
        .ph .ps { margin-left: auto; font-weight: 700; font-size: 12px; }
        .pn { font-size: 11.5px; line-height: 1.5; color: var(--text-muted); margin-top: 3px; }
        .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
        .pill.strong .dot { background: var(--gain); } .pill.strong .ps { color: var(--gain); }
        .pill.ok .dot { background: var(--gain); opacity: 0.55; }
        .pill.weak .dot { background: #d97706; } .pill.weak .ps { color: #b45309; }
        .pill.bad .dot { background: var(--loss); } .pill.bad .ps { color: var(--loss); }
        /* unknown stays neutral and dashed: an absence of evidence, not a middling result */
        .pill.unknown .dot { background: var(--text-faint); }
        .pill.unknown .pn { font-style: italic; }
        .big { font-size: 20px; font-weight: 700; color: var(--text-primary); }
        .big i { font-size: 13px; font-style: normal; color: var(--gain); margin-left: 6px; }
        .meth { font-size: 11px; color: var(--text-muted); line-height: 1.5; margin-top: 4px; }
        .str { font-weight: 700; }
        .str.strong { color: var(--gain); }
        .str.moderate { color: #b45309; }
        .none { font-size: 11.5px; color: var(--text-faint); }
        .sub2 { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-faint); margin-bottom: 6px; }
        .chips { display: flex; flex-wrap: wrap; gap: 5px; }
        .chips span {
          display: inline-flex; align-items: baseline; gap: 5px;
          padding: 3px 9px; border-radius: 6px; font-size: 11px;
          border: 1px solid var(--border); background: var(--canvas-soft);
          color: var(--text-secondary);
        }
        .chips span.up { border-color: rgba(22,163,74,0.35); color: var(--gain); }
        .chips span.dn { border-color: rgba(220,38,38,0.32); color: var(--loss); }
        .chips i { font-size: 9.5px; font-style: normal; color: var(--text-faint); }
        ul { margin: 0; padding-left: 16px; }
        li { font-size: 11.5px; line-height: 1.55; color: var(--text-muted); margin-bottom: 3px; }
      `}</style>
    </tr>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div className="kv">
      <span>{k}</span><b>{v}</b>
      <style jsx>{`
        .kv {
          display: flex; justify-content: space-between; gap: 10px;
          font-size: 11.5px; padding: 3px 0; color: var(--text-muted);
        }
        .kv b { color: var(--text-secondary); font-weight: 600; white-space: nowrap; }
      `}</style>
    </div>
  );
}
