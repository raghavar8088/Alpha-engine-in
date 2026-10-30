"use client";

// Commodity Auto Positions (2026-10-30): 220 paper accounts - 4 MCX minis x 11 strike distances x 5
// account sizes - each selling one call + put pair at 22:00 IST and buying it back at 22:00 on the
// next MCX trading day. Backend: app/services/commodity_auto.py, /api/commodity-auto.
import AutoSellingDesk from "../../components/AutoSellingDesk";

export default function CommodityAutoPositionsPage() {
  return (
    <AutoSellingDesk
      api="/api/commodity-auto"
      crumb="Commodity Auto Positions"
      title="Commodity Auto Positions"
      subtitle="Four MCX minis, eleven strike distances, five account sizes: 220 paper accounts, each selling one call and one put every evening and buying them back the next evening. Nothing here reaches a broker."
      rules={
        <>
          <p>
            <b>The rules.</b> At 22:00 IST on every MCX trading day each account sells a call and a put: ATM, or the
            call k strikes above and the put k strikes below the at-the-money strike (k = 1–10), set from the
            underlying future. At 22:00 on the next MCX trading day the pair is bought back and a fresh one sold.
            Entries are taken only 22:00–22:30.
          </p>
          <p>
            <b>Expiry.</b> The nearest listed expiry with more than two MCX trading days left (expiry day counts as
            one), checked for each commodity at every entry, so no trade is held into expiry day.
          </p>
          <p>
            <b>Size and stop.</b> The whole account is allocated. Lots = equity ÷ the broker’s margin for one call +
            put pair, rounded down. The stop is 20% of that allocation on the pair’s combined loss. It is checked
            every 30 seconds while MCX is open, against the cost of buying both legs back at the ask. After a stop
            the account waits for the next 22:00 entry.
          </p>
          <p className="dim">
            Fills: sold at the bid, bought back at the ask, from Angel One’s live quote. A leg with no fresh
            two-sided quote at 22:00 skips that strategy for the day. Every order pays Angel’s MCX option charges.
            The touch is assumed for any size, which the biggest accounts would not get in a thin book. Nothing
            trades between sessions, so an overnight gap can carry a loss past 20% before the stop can act.
          </p>
        </>
      }
    />
  );
}
