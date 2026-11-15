"use client";

// Delta Exchange Live Trading (14 Nov 2026): REAL money on Delta Exchange India for the bitcoin Premium strategies the
// owner picked from the Crypto tab - TH-05, TL-04 and TH-01 on 14 Nov, TD-02 on 15 Nov - at one contract a trade (the
// smallest order; or $1 to $5 of risk the owner picks on the page) and a $20 daily loss stop. The desk
// is premium_live's "crypto" desk: it copies the paper desk's trades of the four (their signals come from Delta's live
// BTCUSD candles) into real Delta orders, each with its stop and target held on Delta. One ON/OFF switch runs it: ON
// needs one confirmation (the page sends the words REAL MONEY the server asks for); since 15 Nov no PIN (the owner's
// choice). The gold desk stays on Premium Strategies.
import Link from "next/link";
import PageHeader from "../../components/PageHeader";
import LiveDelta from "../premium-strategies/LiveDelta";

export default function DeltaLiveTradingPage() {
  return (
    <div className="dl-page">
      <PageHeader
        crumb="Delta Exchange Live Trading"
        title="Delta Exchange Live Trading"
        subtitle="Real money on Delta Exchange India for the bitcoin Premium strategies you picked: TH-05, TL-04, TH-01 and TD-02, traded on Delta's live BTCUSD data."
      />
      <div className="dl-box">
        <p>
          Each of the four runs on the Premium paper desk on Delta&apos;s live one-minute BTCUSD candles. When one of them
          enters, this desk sends the same trade to your Delta account as a real order: a market entry of 1 contract, the
          smallest order Delta allows (or sized to a risk of $1 to $5 if you pick one below), with that strategy&apos;s own
          stop and target placed on Delta. When the strategy exits, its
          real trade is closed. The desk never adds trades of its own. All four can be in a trade at the same time: each is
          its own order with its own stop and target, and Delta shows their sum as one bitcoin position.
        </p>
        <p>
          Use the <b>Live trading</b> switch below. <b>ON</b> starts real orders after one confirmation. <b>OFF</b> stops new
          trades at once; a position already open still closes at its stop, its target or its strategy&apos;s exit. To watch
          the decisions without sending anything, use <b>Test without orders</b>. The gold strategies stay on{" "}
          <Link href="/premium-strategies">Premium Strategies › Real money · Delta gold</Link>, with their own switch and daily stop.
        </p>
      </div>
      <LiveDelta
        desk="crypto"
        intro={<>TH-05, TL-04 and TH-01 were picked on 14 Nov and TD-02 on 15 Nov, each after 7 to 15 paper trades; TL-04&apos;s and TD-02&apos;s own 2-year bitcoin backtests lose (−0.31R and −0.37R a trade).</>}
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
