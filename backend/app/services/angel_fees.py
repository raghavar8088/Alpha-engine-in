"""Angel One cash-equity cost model.

Paper P&L that ignores costs is not a forecast of anything. On a small desk the gap is
not a rounding error: a Rs10,000 position that moves 1% earns Rs100, while a single
round trip costs roughly Rs40-60 in brokerage, statutory charges and GST. So the same
strategy can look profitable per-trade and still bleed, and the cheaper the book, the
harder costs bite. Everything here is charged against realised P&L so the desks compare
honestly against each other and against a real Angel One account.

RATES (Angel One flat plan, NSE cash segment):

  brokerage      INTRADAY  min(Rs20, 0.25% x turnover) per executed order
                 DELIVERY  min(Rs20, 0.10% x turnover) per executed order
  STT            INTRADAY  0.025% on the SELL leg only
                 DELIVERY  0.100% on BOTH legs
  exchange txn   0.00297% both legs (NSE cash)
  SEBI turnover  0.0001%  both legs (Rs10 per crore)
  NSE IPFT       0.0001%  both legs
  stamp duty     INTRADAY  0.003%  on the BUY leg only
                 DELIVERY  0.015%  on the BUY leg only
  GST            18% on (brokerage + exchange txn + SEBI + IPFT)
  DP charge      DELIVERY sell only: Rs20 + GST per scrip, per day

PRODUCT follows how the position is actually held, not how it is labelled: a strategy
that squares off the same session is INTRADAY, one that carries overnight is DELIVERY
and pays the heavier STT plus a DP charge on exit. Getting that split wrong understates
swing costs by roughly 4x on the sell side, so it is chosen from the real holding.

Rates are class attributes rather than literals so a rate change is one edit, and so
tests can assert against a known schedule.
"""

from dataclasses import dataclass, field

GST_RATE = 0.18

BROKERAGE_CAP = 20.0
BROKERAGE_PCT = {"INTRADAY": 0.0025, "DELIVERY": 0.0010}
STT_SELL = {"INTRADAY": 0.00025, "DELIVERY": 0.001}
STT_BUY = {"INTRADAY": 0.0, "DELIVERY": 0.001}
STAMP_DUTY_BUY = {"INTRADAY": 0.00003, "DELIVERY": 0.00015}
EXCHANGE_TXN = 0.0000297
SEBI_TURNOVER = 0.000001
NSE_IPFT = 0.000001
DP_CHARGE = 20.0

# ── F&O options (NSE) ─────────────────────────────────────────────────────────
# A different schedule entirely, and the difference is not cosmetic. Options brokerage is
# a FLAT Rs20 per order with no percentage cap, so a cheap option pays the same Rs20 as an
# expensive one — on a Rs3,000 premium that is 1.3% before anything else. All statutory
# charges are on PREMIUM turnover, never on notional.
OPT_BROKERAGE = 20.0          # per executed order, flat
OPT_STT_SELL = 0.001          # 0.10% of premium, sell side only
OPT_EXCHANGE_TXN = 0.0005     # 0.05% of premium, both sides (NSE)
OPT_STAMP_BUY = 0.00003       # 0.003% of premium, buy side only
OPT_SEBI = 0.000001           # Rs10 per crore


@dataclass
class FeeBreakdown:
    """Every component kept separately: a single total invites the suspicion that the
    number was guessed, and the breakdown is what makes it checkable against a real
    Angel One contract note."""

    brokerage: float = 0.0
    stt: float = 0.0
    exchange_txn: float = 0.0
    sebi: float = 0.0
    ipft: float = 0.0
    stamp_duty: float = 0.0
    gst: float = 0.0
    dp_charge: float = 0.0
    product: str = "INTRADAY"
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(
            self.brokerage + self.stt + self.exchange_txn + self.sebi
            + self.ipft + self.stamp_duty + self.gst + self.dp_charge, 2)

    def as_dict(self) -> dict:
        return {
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "sebi": round(self.sebi, 2),
            "ipft": round(self.ipft, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "gst": round(self.gst, 2),
            "dp_charge": round(self.dp_charge, 2),
            "total": self.total,
            "product": self.product,
        }


def _brokerage(turnover: float, product: str) -> float:
    return min(BROKERAGE_CAP, turnover * BROKERAGE_PCT[product])


def round_trip(
    entry_price: float,
    exit_price: float,
    qty: int,
    side: str = "BUY",
    product: str = "INTRADAY",
) -> FeeBreakdown:
    """Total cost of opening AND closing one equity position.

    `side` is the direction of the OPEN, so a short (side="SELL") pays STT on its entry
    rather than its exit. That asymmetry is real money on the sell-side STT and is the
    reason this takes a side at all instead of just two prices."""
    product = product if product in BROKERAGE_PCT else "INTRADAY"
    fb = FeeBreakdown(product=product)
    if qty <= 0 or entry_price <= 0 or exit_price <= 0:
        return fb

    buy_turnover = (entry_price if side == "BUY" else exit_price) * qty
    sell_turnover = (exit_price if side == "BUY" else entry_price) * qty
    turnover = buy_turnover + sell_turnover

    fb.brokerage = _brokerage(buy_turnover, product) + _brokerage(sell_turnover, product)
    fb.stt = sell_turnover * STT_SELL[product] + buy_turnover * STT_BUY[product]
    fb.exchange_txn = turnover * EXCHANGE_TXN
    fb.sebi = turnover * SEBI_TURNOVER
    fb.ipft = turnover * NSE_IPFT
    fb.stamp_duty = buy_turnover * STAMP_DUTY_BUY[product]
    # GST rides on the broker/exchange/regulator services, never on STT or stamp duty.
    fb.gst = GST_RATE * (fb.brokerage + fb.exchange_txn + fb.sebi + fb.ipft)
    if product == "DELIVERY" and side == "BUY":
        # Debiting shares out of the demat on exit; a delivery short is not possible.
        fb.dp_charge = DP_CHARGE * (1 + GST_RATE)
    return fb


def option_round_trip(entry_premium: float, exit_premium: float, lots: int, lot_size: int) -> FeeBreakdown:
    """Cost of buying and then selling one NSE options position.

    Option buying is charged on the PREMIUM paid, not the contract's notional value, so a
    Rs150 ATM NIFTY option on a 75-lot is Rs11,250 of turnover per leg — not Rs17 lakh.
    Sizing off notional here would overstate costs by roughly 150x."""
    fb = FeeBreakdown(product="OPTION")
    qty = max(lots, 0) * max(lot_size, 0)
    if qty <= 0 or entry_premium <= 0 or exit_premium < 0:
        return fb
    buy_turnover = entry_premium * qty
    sell_turnover = exit_premium * qty
    turnover = buy_turnover + sell_turnover

    fb.brokerage = OPT_BROKERAGE * 2          # one order in, one out
    fb.stt = sell_turnover * OPT_STT_SELL
    fb.exchange_txn = turnover * OPT_EXCHANGE_TXN
    fb.sebi = turnover * OPT_SEBI
    fb.stamp_duty = buy_turnover * OPT_STAMP_BUY
    fb.gst = GST_RATE * (fb.brokerage + fb.exchange_txn + fb.sebi)
    return fb


def product_for(category: str | None, days_held: int | None = None) -> str:
    """DELIVERY only when the position actually slept overnight.

    A swing strategy that happens to hit its target within the session is charged as
    intraday, because that is what the broker would have charged."""
    if days_held is not None:
        return "DELIVERY" if days_held >= 1 else "INTRADAY"
    return "DELIVERY" if (category or "") == "swing" else "INTRADAY"


def position_fees(pos: dict, exit_price: float | None = None) -> FeeBreakdown:
    """Fee breakdown for a stored position document."""
    exit_px = exit_price if exit_price is not None else pos.get("exit_price")
    days = None
    opened_on, closed_on = pos.get("opened_on"), pos.get("closed_on")
    if opened_on and closed_on:
        try:
            from datetime import date
            days = (date.fromisoformat(closed_on) - date.fromisoformat(opened_on)).days
        except ValueError:
            days = None
    return round_trip(
        entry_price=float(pos.get("entry_price") or 0),
        exit_price=float(exit_px or 0),
        qty=int(pos.get("qty") or 0),
        side=pos.get("side") or "BUY",
        product=product_for(pos.get("category"), days),
    )
