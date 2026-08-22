"""Paper Broker — a broker terminal that trades real Angel One prices with fake money.

TWO MODULES SIT ON THIS ONE ENGINE: Stock Paper Trading (NSE cash) and F&O Paper Trading
(NFO futures and options). They are the same broker with two segments, not two codebases,
because everything that makes a broker a broker — the order lifecycle, the funds ledger,
margin blocking, rejections, day-order expiry, auto square-off — is identical on both sides.
Forking it would guarantee the two drift.

WHAT THIS IS NOT. The app already has `manual_positions` (equity) and `fno_positions`
(F&O), which are paper POSITION books: you place an order and it fills, or it rests as a
limit and fills later. That is most of a portfolio tracker and about a third of a broker.
What a real terminal adds, and what this module is for:

  * SL and SL-M orders — a trigger price that arms the order, then a limit or market fill.
    Without these you cannot paper-trade any strategy that uses a stop, which is all of them.
  * ORDER MODIFY, not just cancel.
  * VALIDITY. A DAY order dies at the close. The existing desks leave a pending order
    resting forever, which quietly fills trades days after you meant them.
  * REJECTIONS AS RECORDS. Insufficient margin produces a REJECTED row in the order book
    with a reason, the way a broker does — not an exception that loses the attempt.
  * PRODUCT SEMANTICS. CNC cannot short and settles to HOLDINGS; MIS is squared off by the
    exchange cutoff whether you like it or not; NRML carries overnight in F&O.
  * A FUNDS LEDGER — every debit and credit, so the cash balance can be explained rather
    than just displayed.

MODELLING LIMITS, stated because they decide what this can honestly be used for:
  * Fills happen at the last traded price. Angel's FULL quote as parsed here carries no
    bid/ask depth, so there is no spread and no queue position. A real limit order at the
    touch may not fill; here it does. Paper P&L is therefore optimistic by roughly half a
    spread per side, which matters most on illiquid strikes.
  * F&O margin is the SPAN-lite model in `fno_margin`, the same one the F&O Positions desk
    uses — a defensible approximation of the exchange's scenario array, not the exchange's
    own number.
  * No orders ever reach Angel One. The client's `place_order` is deliberately never called
    from this package.
"""
