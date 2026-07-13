"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import PageHeader from "../../components/PageHeader";
import {
  AIResult,
  AIStatus,
  ResearchSignal,
  StrategyInfo,
  VectorHit,
  compareStrategies,
  detectUnusualActivity,
  explainTrade,
  fetchAIStatus,
  fetchResearchIdeas,
  fetchStrategies,
  fetchStrategyRanking,
  fetchTradeIdeas,
  fetchVectorStatus,
  indexResearchIntoVectorStore,
  ingestResearch,
  vectorSearch,
} from "../../lib/api";

const TABS = ["research", "explainer", "intelligence", "vector"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  research: "Research Feed",
  explainer: "Trade Explainer",
  intelligence: "Strategy Intelligence",
  vector: "Vector Search",
};

const SAMPLE_TRADE = JSON.stringify(
  { symbol: "RELIANCE", direction: "LONG", entry_price: 2500, exit_price: 2550, stop_loss: 2470, target: 2580, pnl: 5000, exit_reason: "target" },
  null,
  2
);

function AIResultView({ result }: { result: AIResult | null }) {
  if (!result) return null;
  if (result.status === "not_configured") {
    return <div className="notice">{result.message} — set ANTHROPIC_API_KEY on ai-service to activate this.</div>;
  }
  if (result.status === "no_data") {
    return <div className="notice">{result.message}</div>;
  }
  const { status, ...rest } = result;
  return <pre className="result-json">{JSON.stringify(rest, null, 2)}</pre>;
}

export default function AIPage() {
  const [tab, setTab] = useState<Tab>("research");
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [vectorMode, setVectorMode] = useState<string | null>(null);

  useEffect(() => {
    fetchAIStatus().then(setStatus).catch(() => setStatus(null));
    fetchVectorStatus().then((d) => setVectorMode(d.mode)).catch(() => setVectorMode(null));
  }, []);

  // Research feed
  const [signals, setSignals] = useState<ResearchSignal[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);

  const loadSignals = useCallback(() => {
    setSignalsLoading(true);
    fetchResearchIdeas(40)
      .then(setSignals)
      .finally(() => setSignalsLoading(false));
  }, []);

  useEffect(() => {
    loadSignals();
  }, [loadSignals]);

  const runIngest = useCallback(async () => {
    setIngesting(true);
    try {
      await ingestResearch();
      loadSignals();
    } finally {
      setIngesting(false);
    }
  }, [loadSignals]);

  // Trade explainer
  const [tradeJson, setTradeJson] = useState(SAMPLE_TRADE);
  const [explainResult, setExplainResult] = useState<AIResult | null>(null);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);

  const runExplain = useCallback(async () => {
    setExplainError(null);
    setExplaining(true);
    try {
      const trade = JSON.parse(tradeJson);
      setExplainResult(await explainTrade(trade));
    } catch (e) {
      setExplainError(e instanceof Error ? e.message : "Invalid trade JSON");
    } finally {
      setExplaining(false);
    }
  }, [tradeJson]);

  // Strategy intelligence
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [rankResult, setRankResult] = useState<AIResult | null>(null);
  const [ranking, setRanking] = useState(false);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [compareResult, setCompareResult] = useState<AIResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [ideasResult, setIdeasResult] = useState<AIResult | null>(null);
  const [ideasLoading, setIdeasLoading] = useState(false);

  useEffect(() => {
    fetchStrategies()
      .then((all) => {
        const passing = all.filter((s) => s.validation?.passed);
        setStrategies(passing);
        if (passing.length >= 2) {
          setCompareA(passing[0].strategy_id);
          setCompareB(passing[1].strategy_id);
        }
      })
      .catch(() => setStrategies([]));
  }, []);

  const runRank = useCallback(async () => {
    setRanking(true);
    try {
      setRankResult(await fetchStrategyRanking());
    } finally {
      setRanking(false);
    }
  }, []);

  const runCompare = useCallback(async () => {
    if (!compareA || !compareB) return;
    setComparing(true);
    try {
      setCompareResult(await compareStrategies(compareA, compareB));
    } finally {
      setComparing(false);
    }
  }, [compareA, compareB]);

  const runIdeas = useCallback(async () => {
    setIdeasLoading(true);
    try {
      setIdeasResult(await fetchTradeIdeas());
    } finally {
      setIdeasLoading(false);
    }
  }, []);

  // Vector search
  const [query, setQuery] = useState("Reliance Industries earnings");
  const [hits, setHits] = useState<VectorHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [indexNote, setIndexNote] = useState<string | null>(null);

  const runSearch = useCallback(async () => {
    setSearching(true);
    try {
      const res = await vectorSearch(query);
      setHits(res.hits);
      setVectorMode(res.mode);
    } finally {
      setSearching(false);
    }
  }, [query]);

  const runIndex = useCallback(async () => {
    setIndexing(true);
    setIndexNote(null);
    try {
      const res = await indexResearchIntoVectorStore(200);
      setIndexNote(res.status === "no_data" ? res.message ?? "no data" : `indexed ${JSON.stringify(res.indexed)}`);
    } finally {
      setIndexing(false);
    }
  }, []);

  return (
    <div className="page">
      <PageHeader
        crumb="AI Research"
        title="AI Research & Trade Intelligence"
        subtitle="Claude-powered trade explanations, strategy ranking, and news summarization, plus a Qdrant-backed research search. Every AI call reports its real status honestly rather than fabricating a response when unconfigured."
      />

      <div className="banner">
        <StatusPill
          label={status ? `AI: ${status.configured ? "configured" : "not configured"} (${status.model})` : "AI: loading..."}
          tone={status?.configured ? "accent" : "warn"}
          pulse={status?.configured}
        />
        <StatusPill
          label={vectorMode ? `Vector search: ${vectorMode}` : "Vector: loading..."}
          tone={vectorMode === "semantic" ? "accent" : "muted"}
        />
        {status && !status.configured && <span className="banner-note">{status.note}</span>}
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {tab === "research" && (
        <GlassPanel title="Research Feed" note={`${signals.length} signals`}>
          <div className="form">
            <button onClick={loadSignals} disabled={signalsLoading}>{signalsLoading ? "Loading..." : "Refresh"}</button>
            <button className="secondary" onClick={runIngest} disabled={ingesting}>
              {ingesting ? "Ingesting..." : "Ingest new RSS"}
            </button>
          </div>
          <div className="footnote">
            Mechanically normalized from real RSS feeds (Economic Times, Moneycontrol, LiveMint) — symbol detection is
            keyword-based, signal is a neutral HOLD placeholder (no fabricated directional call) until an AI module enriches it.
          </div>
          <div className="feed">
            {signals.map((s) => (
              <div className="feed-item" key={s.id}>
                <div className="feed-meta">
                  <span className="feed-symbol">{s.symbol}</span>
                  <span className="feed-source">{s.source}</span>
                  <span className="feed-time">{new Date(s.timestamp).toLocaleString("en-IN")}</span>
                </div>
                <div className="feed-text">
                  {s.link ? <a href={s.link} target="_blank" rel="noreferrer">{s.reasoning}</a> : s.reasoning}
                </div>
              </div>
            ))}
            {!signalsLoading && signals.length === 0 && <div className="notice">No research signals yet — click Ingest.</div>}
          </div>
        </GlassPanel>
      )}

      {tab === "explainer" && (
        <GlassPanel title="Trade Explainer">
          <div className="form-col">
            <label>
              Trade JSON
              <textarea rows={9} value={tradeJson} onChange={(e) => setTradeJson(e.target.value)} />
            </label>
            {explainError && <div className="error">{explainError}</div>}
            <button onClick={runExplain} disabled={explaining}>{explaining ? "Explaining..." : "Explain trade"}</button>
          </div>
          <AIResultView result={explainResult} />
        </GlassPanel>
      )}

      {tab === "intelligence" && (
        <>
          <GlassPanel title="Strategy Ranking" note={`${strategies.length} passing strategies`}>
            <div className="form">
              <button onClick={runRank} disabled={ranking}>{ranking ? "Ranking..." : "Rank strategies"}</button>
            </div>
            <AIResultView result={rankResult} />
          </GlassPanel>

          <GlassPanel title="Compare Two Strategies">
            <div className="form">
              <label>
                Strategy A
                <select value={compareA} onChange={(e) => setCompareA(e.target.value)}>
                  {strategies.map((s) => (
                    <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Strategy B
                <select value={compareB} onChange={(e) => setCompareB(e.target.value)}>
                  {strategies.map((s) => (
                    <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>
                  ))}
                </select>
              </label>
              <button onClick={runCompare} disabled={comparing || !compareA || !compareB}>
                {comparing ? "Comparing..." : "Compare"}
              </button>
            </div>
            <AIResultView result={compareResult} />
          </GlassPanel>

          <GlassPanel title="Trade Ideas from Research Signals">
            <div className="form">
              <button onClick={runIdeas} disabled={ideasLoading}>{ideasLoading ? "Generating..." : "Generate ideas"}</button>
            </div>
            <AIResultView result={ideasResult} />
          </GlassPanel>
        </>
      )}

      {tab === "vector" && (
        <GlassPanel title="Research Vector Search" note={vectorMode ?? undefined}>
          <div className="footnote">
            {vectorMode === "placeholder"
              ? "Placeholder mode: a deterministic bag-of-words hash embedder — matches by shared vocabulary, not meaning. Proves the Qdrant plumbing works; not semantic search."
              : "Semantic embedder active."}
          </div>
          <div className="form">
            <button className="secondary" onClick={runIndex} disabled={indexing}>
              {indexing ? "Indexing..." : "Index research signals"}
            </button>
            {indexNote && <span className="banner-note">{indexNote}</span>}
          </div>
          <div className="form">
            <label style={{ flex: 1 }}>
              Query
              <input value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <button onClick={runSearch} disabled={searching}>{searching ? "Searching..." : "Search"}</button>
          </div>
          {hits && (
            <div className="feed">
              {hits.map((h) => (
                <div className="feed-item" key={h.id}>
                  <div className="feed-meta">
                    <span className="feed-symbol">{String(h.payload.symbol ?? "")}</span>
                    <span className="feed-source">{String(h.payload.source ?? "")}</span>
                    <span className="feed-time">score {h.score.toFixed(3)}</span>
                  </div>
                  <div className="feed-text">{String(h.payload.reasoning ?? "")}</div>
                </div>
              ))}
              {hits.length === 0 && <div className="notice">No hits — index research signals first.</div>}
            </div>
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .banner { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .banner-note { font-size: 12px; color: var(--text-faint); }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab {
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
          padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .form { display: flex; flex-wrap: wrap; gap: 14px; padding: 18px 20px; align-items: center; }
        .form-col { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px; }
        label { display: flex; flex-direction: column; gap: 6px; font-size: 11.5px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.04em; text-transform: uppercase; }
        input, select, textarea { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13.5px; color: var(--text); font-family: var(--font-data); }
        textarea { font-family: ui-monospace, monospace; resize: vertical; }
        button { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 11px 20px; cursor: pointer; }
        button.secondary { background: var(--canvas-soft); color: var(--text); border: 1px solid var(--panel-border); }
        button:disabled { opacity: 0.55; cursor: default; }
        .error { padding: 10px 14px; border-radius: 9px; background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3); color: var(--loss); font-size: 13px; }
        .notice { margin: 0 20px 18px; padding: 12px 16px; border-radius: 9px; background: rgba(245,166,35,0.08); border: 1px solid rgba(245,166,35,0.25); color: var(--warn); font-size: 13px; }
        .result-json { margin: 0 20px 20px; padding: 14px 16px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; overflow-x: auto; white-space: pre-wrap; }
        .footnote { padding: 0 20px 16px; font-size: 11px; color: var(--text-faint); line-height: 1.5; }
        .feed { display: flex; flex-direction: column; gap: 2px; padding: 0 20px 20px; max-height: 520px; overflow-y: auto; }
        .feed-item { padding: 12px 0; border-bottom: 1px solid var(--canvas-soft); }
        .feed-meta { display: flex; gap: 10px; align-items: center; margin-bottom: 4px; }
        .feed-symbol { font-weight: 700; font-size: 12.5px; color: var(--accent); }
        .feed-source { font-size: 11px; color: var(--text-muted); }
        .feed-time { font-size: 11px; color: var(--text-faint); margin-left: auto; }
        .feed-text { font-size: 13px; line-height: 1.5; color: var(--text); }
        .feed-text a { color: inherit; text-decoration: none; }
        .feed-text a:hover { text-decoration: underline; }
      `}</style>
    </div>
  );
}
