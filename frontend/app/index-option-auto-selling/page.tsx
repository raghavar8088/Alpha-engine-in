"use client";

// Indian Market Option Auto Selling (2026-10-30): Commodity Auto Positions on Indian index options -
// per index, 11 strike distances x 5 account sizes, each account selling one call + put pair at 15:15
// IST and buying it back at 15:15 on the next trading day. Backend: app/services/index_auto.py,
// /api/index-auto.
import AutoSellingDesk from "../../components/AutoSellingDesk";

export default function IndexOptionAutoSellingPage() {
  return (
    <AutoSellingDesk
      api="/api/index-auto"
      crumb="Indian Market Option Auto Selling"
      title="Indian Market Option Auto Selling"
      subtitle="NIFTY 50, BANK NIFTY, SENSEX and BANKEX options, eleven strike distances, five account sizes: 220 paper accounts, each selling one call and one put a day and buying them back the next. Nothing here reaches a broker."
      rules={
        <>
          <p>
            <b>The rules.</b> At 15:15 IST on every trading day each account sells a call and a put: ATM, or the
            call k strikes above and the put k strikes below the at-the-money strike (k = 1–10), set from the
            index’s own price and counted on the listed strike ladder. At 15:15 on the next trading day the pair is
            bought back and a fresh one sold. Entries are taken only 15:15–15:30.
          </p>
          <p>
            <b>Expiry.</b> The nearest listed expiry with more than two trading days left (expiry day counts as
            one), checked for each index at every entry, so no trade is held into expiry day. NIFTY and SENSEX have
            weekly expiries; BANK NIFTY and BANKEX monthly ones.
          </p>
          <p>
            <b>Size and stop.</b> The whole account is allocated. Lots = equity ÷ Angel One’s margin for one call +
            put lot pair, rounded down. The stop is 20% of that allocation on the pair’s combined loss. It is checked
            every 30 seconds in the session, against the cost of buying both legs back at the ask. After a stop the
            account waits for the next 15:15 entry.
          </p>
          <p className="dim">
            Fills: sold at the bid, bought back at the ask, from Angel One’s live quote. A leg with no fresh
            two-sided quote at 15:15 skips that strategy for the day; BANKEX options trade thinly, so its strategies
            often skip. Every order pays Angel’s option charges, BSE contracts at BSE’s own exchange rate. SENSEX and
            BANKEX contracts are loaded from Angel’s contract file each day. The touch is assumed for any size, and
            nothing trades overnight, so a gap can carry a loss past 20% before the stop can act.
          </p>
        </>
      }
    />
  );
}
