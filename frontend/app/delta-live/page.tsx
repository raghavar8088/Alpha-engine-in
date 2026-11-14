"use client";

// Delta Exchange Live Trading (14 Nov 2026): REAL money on Delta Exchange India for the bitcoin Premium strategies the
// owner picked from the Crypto tab - TH-05, TL-04 and TH-01 - at $5 risked a trade and a $20 daily loss stop. The desk
// is premium_live's "crypto" desk: it copies the paper desk's trades of the three (their signals come from Delta's live
// BTCUSD candles) into real Delta orders, each with its stop and target held on Delta. It starts off; going live needs
// the owner's PIN and the words REAL MONEY; stopping never does. The gold desk stays on Premium Strategies.
import Link from "next/link";
import PageHeader from "../../components/PageHeader";
import LiveDelta from "../premium-strategies/LiveDelta";

export default function DeltaLiveTradingPage() {
  return (
    <div className="dl-page">
      <PageHeader
        crumb="Delta Exchange Live Trading"
        title="Delta Exchange Live Trading"
        subtitle="Real money on Delta Exchange India for the bitcoin Premium strategies you picked: TH-05, TL-04 and TH-01, traded on Delta's live BTCUSD data."
      />
      <div className="dl-box">
        <p>
          Each of the three runs on the Premium paper desk on Delta&apos;s live one-minute BTCUSD candles. When one of them
          enters, this desk sends the same trade to your Delta account as a real order: a market entry sized so its stop
          loses $5, with that strategy&apos;s own stop and target placed on Delta as a bracket. When the strategy exits, the
          real position is closed. The desk never adds trades of its own, and Delta holds one bitcoin position at a time, so
          a second signal is skipped while one is open.
        </p>
        <p>
          It starts <b>off</b>. Use <b>Shadow</b> first: every decision is made and logged with simulated fills, and nothing is
          sent. <b>Go live</b> needs your Delta API keys and PIN on the server (the deploy script sets them; they never go in
          the repository) and the words REAL MONEY. The gold strategies stay on{" "}
          <Link href="/premium-strategies">Premium Strategies › Real money · Delta gold</Link>, with their own switch and daily stop.
        </p>
      </div>
      <LiveDelta
        desk="crypto"
        intro={<>These three were picked on 14 Nov from the Crypto tab after 9 to 15 paper trades each, and TL-04&apos;s own 2-year bitcoin backtest loses −0.31R a trade over 2,134 trades.</>}
      />
      <style jsx>{`
        .dl-page { padding: 0 0 40px; }
        .dl-box { border: 1px solid var(--panel-border); background: var(--panel); border-radius: 14px; padding: 14px 18px;
          margin: 0 0 16px; }
        .dl-box p { margin: 0 0 8px; font-size: 13.5px; line-height: 1.6; color: var(--text-secondary); }
        .dl-box p:last-child { margin-bottom: 0; }
        .dl-box :global(a) { color: var(--accent); }
      `}</style>
    </div>
  );
}
