"use client";

// Crypto Application (2026-10-31): the owner's crypto app - ICC, the Institutional Command Center
// (repo raghavar8088/antigravity, deployed on Vercel) - reached from this app's sidebar, with every
// module it has. That app has its own login and sends X-Frame-Options: DENY / frame-ancestors 'none',
// so it cannot be shown inside this one; each module opens in a new tab, through its login.
// The module list mirrors its sidebar (client/src/components/AppShell.tsx PRIMARY_NAV, and the
// Command Center pages in client/src/lib/utils/navRoutes.ts) as of origin/main d57399ba.
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";

const BASE = (process.env.NEXT_PUBLIC_CRYPTO_APP_URL || "https://antigravity-five-pink.vercel.app").replace(/\/$/, "");

type Mod = { href: string; label: string; about: string };

// In the order that app's own sidebar lists them.
const MODULES: Mod[] = [
  { href: "/terminal", label: "Command Center", about: "The monitoring surface: engines, the strategy pipeline, portfolio, risk and health in one place." },
  { href: "/crypto-positions", label: "Crypto Positions", about: "Put a position on by hand: Delta option chains and perpetuals at real quoted premiums, paper money." },
  { href: "/live-engine", label: "Live Engine", about: "The real-money Delta desk: what live capital is doing, strategy by strategy." },
  { href: "/delta-paper-trading", label: "Delta Paper Trading", about: "A manual terminal on Delta: real quotes, contract specs, funding and order-book fills, paper money." },
  { href: "/forex-paper-trading", label: "Forex Paper Trading", about: "The same terminal on forex: lots, pips and swap; an account stopped out on margin level." },
  { href: "/crypto-screener", label: "Crypto Screener", about: "Which of ~220 Delta perpetuals is moving, why, on whose positioning, and which can hold a stop." },
  { href: "/live-demo-engine", label: "Live Demo Engine", about: "The Live Engine against Delta's demo venue: same desk, separate credentials." },
  { href: "/live-engine-paper", label: "Live Engine Paper Desk", about: "The live roster's strategies with paper money: same prices, taker fees and margin rules." },
  { href: "/high-volume-crypto", label: "High Volume Crypto Trading", about: "The scalp strategies on the highest-volume currencies only, a candidate feeder for the live desk." },
  { href: "/top-crypto-trading", label: "Top Crypto Trading", about: "The widest strategy catalogue the app runs, where a strategy earns its way toward the live roster." },
  { href: "/gold-desk", label: "Gold Desk", about: "Gold on the same venue and engine, kept apart from the crypto leaderboard." },
  { href: "/crypto-fno", label: "Crypto F&O", about: "Crypto futures and options." },
  { href: "/btc-pre-live", label: "BTC Pre-Live Engine", about: "A qualified whitelist of strategies on BTC, paper money, before any of them goes live." },
  { href: "/scalp-desk", label: "Crypto Scalp Desk", about: "The scalping strategies across Delta's perpetuals: the control arm." },
  { href: "/options-selling-desk", label: "Crypto Options Selling", about: "Option-selling strategies on Delta's crypto options." },
  { href: "/options-buying-desk", label: "Crypto Options Buying", about: "Option-buying strategies on Delta's crypto options." },
  { href: "/mock-trading", label: "Mock Trading", about: "The mock-trading execution surface and its validation gate." },
  { href: "/mobile", label: "Mobile Emergency", about: "The phone-sized emergency controls." },
];

// The Command Center's own pages, as its sidebar groups them.
const COMMAND_CENTER: { title: string; items: { href: string; label: string }[] }[] = [
  {
    title: "Trading",
    items: [
      { href: "/terminal/live-engine", label: "Live Engine" },
      { href: "/terminal/pre-live-engine", label: "Pre-Live Engine" },
      { href: "/terminal/pre-live-strategies", label: "Pre-Live Strategies" },
      { href: "/terminal/trade-engine", label: "Trade Engine" },
      { href: "/terminal/backtest", label: "Backtest Lab" },
      { href: "/terminal/strategies", label: "Strategies" },
      { href: "/terminal/strategies/threshold-config", label: "Trade Thresholds" },
    ],
  },
  {
    title: "Monitor",
    items: [
      { href: "/terminal", label: "Command Center" },
      { href: "/terminal/portfolio", label: "Portfolio" },
      { href: "/terminal/risk", label: "Risk" },
      { href: "/terminal/analytics", label: "Analytics" },
      { href: "/terminal/execution", label: "Execution" },
      { href: "/terminal/events", label: "Events" },
      { href: "/terminal/health", label: "Health" },
      { href: "/terminal/diagnostics", label: "Diagnostics" },
      { href: "/terminal/settings", label: "Settings" },
    ],
  },
];

const ext = { target: "_blank", rel: "noopener noreferrer" } as const;

export default function CryptoApplicationPage() {
  return (
    <div className="page">
      <PageHeader
        crumb="Crypto Application"
        title="Crypto Application"
        subtitle="ICC — the Institutional Command Center: your crypto app, with every module it has. It runs on its own login and its own engines, and opens in a new tab."
        actions={
          <a className="open-btn" href={`${BASE}/terminal`} {...ext}>
            Open the Crypto Application ↗
          </a>
        }
      />

      <div className="note">
        <p>
          <b>One click, the whole app.</b> Every card below opens that module in the crypto app. The first time, it
          asks for the crypto app’s own login, then lands on the module you picked.
        </p>
        <p className="dim">
          The crypto app does not allow itself to be shown inside another site (a standard guard for a logged-in
          trading app), so it opens beside this one rather than within it. Its desks run on their own engines; a
          desk whose engine is stopped opens without live data.
        </p>
      </div>

      <GlassPanel title={`Modules — ${MODULES.length}`}>
        <div className="grid">
          {MODULES.map((m) => (
            <a key={m.href} className="card" href={`${BASE}${m.href}`} {...ext}>
              <span className="card-name">{m.label}</span>
              <span className="card-about">{m.about}</span>
              <span className="card-path">{m.href} ↗</span>
            </a>
          ))}
        </div>
      </GlassPanel>

      <GlassPanel title="Inside the Command Center">
        <div className="cc">
          {COMMAND_CENTER.map((g) => (
            <div key={g.title} className="cc-group">
              <div className="cc-title">{g.title}</div>
              <div className="cc-links">
                {g.items.map((it) => (
                  <a key={`${g.title}${it.href}`} className="chip" href={`${BASE}${it.href}`} {...ext}>
                    {it.label} ↗
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .open-btn { display: inline-flex; align-items: center; padding: 10px 16px; border-radius: 10px; font-weight: 700;
                    font-size: 13px; text-decoration: none; background: var(--brand); color: #fff; white-space: nowrap; }
        .note { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .note p { margin: 0 0 8px; }
        .note p:last-child { margin-bottom: 0; }
        .note b { color: var(--text); }
        .dim { color: var(--text-faint); }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
        .card { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; border-radius: 12px; text-decoration: none;
                background: var(--panel); border: 1px solid var(--panel-border); color: var(--text); }
        .card:hover { border-color: rgba(var(--brand-rgb), 0.45); background: var(--brand-dim); }
        .card-name { font-weight: 800; font-size: 14px; }
        .card-about { font-size: 12px; line-height: 1.5; color: var(--text-muted); flex: 1; }
        .card-path { font-size: 11px; color: var(--brand); font-family: var(--font-mono, monospace); }
        .cc { display: flex; flex-direction: column; gap: 14px; }
        .cc-title { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px; }
        .cc-links { display: flex; flex-wrap: wrap; gap: 8px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 6px 11px;
                border-radius: 8px; font-size: 12px; font-weight: 700; text-decoration: none; }
        .chip:hover { color: var(--brand); border-color: rgba(var(--brand-rgb), 0.35); }
      `}</style>
    </div>
  );
}
