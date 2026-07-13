"""Indian transaction-cost model (NSE, 2024-25 rate card, post-Oct-2024 STT revision).

Every rate is a config field, not a constant, so brokers/rate changes are a config edit.
Defaults follow Dhan's pricing (zero delivery brokerage; Rs 20 or 0.03% — whichever is
lower — for intraday/F&O) plus statutory charges: STT, NSE transaction charges, SEBI
turnover fee, stamp duty (buy side), and 18% GST on brokerage + exchange + SEBI.

Slippage/impact are modelled at the engine level as a price adjustment on fills;
partial fills as a volume-participation cap (see engine.py)."""

from pydantic import BaseModel

from tradingai_shared.domain import AssetClass

# Engine-side product buckets: delivery vs intraday equity, futures, options.
DELIVERY, INTRADAY, FUTURES, OPTIONS = "delivery", "intraday", "futures", "options"


class CostModel(BaseModel):
    # Brokerage: flat per order, or pct of turnover, whichever is LOWER (0 flat = free)
    delivery_brokerage_flat: float = 0.0
    delivery_brokerage_pct: float = 0.0
    intraday_brokerage_flat: float = 20.0
    intraday_brokerage_pct: float = 0.0003  # 0.03%
    fno_brokerage_flat: float = 20.0
    fno_brokerage_pct: float = 0.0003

    # STT (Securities Transaction Tax)
    stt_delivery_pct: float = 0.001  # 0.1% both sides
    stt_intraday_sell_pct: float = 0.00025  # 0.025% sell only
    stt_futures_sell_pct: float = 0.0002  # 0.02% sell only
    stt_options_sell_pct: float = 0.001  # 0.1% of premium, sell only

    # NSE transaction charges
    exch_equity_pct: float = 0.0000297
    exch_futures_pct: float = 0.0000173
    exch_options_pct: float = 0.0003503  # on premium

    # SEBI turnover fee (both sides)
    sebi_pct: float = 0.000001  # Rs 10/crore

    # Stamp duty (buy side only)
    stamp_delivery_pct: float = 0.00015
    stamp_intraday_pct: float = 0.00003
    stamp_futures_pct: float = 0.00002
    stamp_options_pct: float = 0.00003

    gst_pct: float = 0.18  # on brokerage + exchange + SEBI

    def product_for(self, asset_class: AssetClass, is_intraday_timeframe: bool) -> str:
        """Cash instruments are delivery on daily/weekly bars, intraday on minute bars
        (an index backtest is an approximation — indices aren't directly tradeable, so
        cash-equity rates stand in for the proxy instrument)."""
        if asset_class in (AssetClass.EQUITY_FUTURE, AssetClass.INDEX_FUTURE):
            return FUTURES
        if asset_class in (AssetClass.EQUITY_OPTION, AssetClass.INDEX_OPTION):
            return OPTIONS
        return INTRADAY if is_intraday_timeframe else DELIVERY

    def order_charges(self, product: str, price: float, quantity: int, is_buy: bool) -> float:
        """Total charges for one executed order (one side of a trade)."""
        turnover = price * quantity

        if product == DELIVERY:
            brokerage = _brokerage(turnover, self.delivery_brokerage_flat, self.delivery_brokerage_pct)
            stt = turnover * self.stt_delivery_pct
            exch = turnover * self.exch_equity_pct
            stamp = turnover * self.stamp_delivery_pct if is_buy else 0.0
        elif product == INTRADAY:
            brokerage = _brokerage(turnover, self.intraday_brokerage_flat, self.intraday_brokerage_pct)
            stt = 0.0 if is_buy else turnover * self.stt_intraday_sell_pct
            exch = turnover * self.exch_equity_pct
            stamp = turnover * self.stamp_intraday_pct if is_buy else 0.0
        elif product == FUTURES:
            brokerage = _brokerage(turnover, self.fno_brokerage_flat, self.fno_brokerage_pct)
            stt = 0.0 if is_buy else turnover * self.stt_futures_sell_pct
            exch = turnover * self.exch_futures_pct
            stamp = turnover * self.stamp_futures_pct if is_buy else 0.0
        elif product == OPTIONS:
            brokerage = _brokerage(turnover, self.fno_brokerage_flat, self.fno_brokerage_pct)
            stt = 0.0 if is_buy else turnover * self.stt_options_sell_pct
            exch = turnover * self.exch_options_pct
            stamp = turnover * self.stamp_options_pct if is_buy else 0.0
        else:
            raise ValueError(f"unknown product {product!r}")

        sebi = turnover * self.sebi_pct
        gst = (brokerage + exch + sebi) * self.gst_pct
        return brokerage + stt + exch + sebi + stamp + gst


def _brokerage(turnover: float, flat: float, pct: float) -> float:
    """Flat or pct-of-turnover, whichever is lower; either being 0 means free."""
    pct_amount = turnover * pct
    candidates = [c for c in (flat, pct_amount) if c > 0]
    return min(candidates) if candidates else 0.0
