"use client";

// Stock Momentum Trading (its own module from 21 Nov 2026; before that a Stock Screener tab). The 09:30 scan ranks
// each universe's stocks on the first 15 minutes - opening move, strength against Nifty and the stock's sector,
// session VWAP, turnover and volume against the same interval of earlier sessions - and keeps the ten strongest a
// side. A paper book (Rs 1 lakh a universe) can trade the rules the owner approves on those candidates, five
// positions at most, entries until 14:30 and square-off at 15:10 IST. The backend is
// app/services/screener/morning*.py behind /api/screener/morning/{index}; Main Control's "Stock Momentum Trading"
// switch gates it (OFF: open positions are still managed to their exits, nothing new opens).
import StockMomentumDesk from "./StockMomentumDesk";

export default function StockMomentumPage() {
  return <StockMomentumDesk />;
}
