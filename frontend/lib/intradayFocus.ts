const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface FocusStrategy {
  strategy_id: string; name: string; timeframe: string; description: string;
  initial_capital: number; equity: number; available_cash: number; deployed_capital: number;
  realized_pnl: number; unrealized_pnl: number; total_pnl: number; return_pct: number;
  trades: number; win_rate: number; open_positions: number; status: string; last_skip: string | null;
}
export interface FocusPosition {
  position_id: string; strategy_id: string; strategy_name: string; symbol: string;
  side: "BUY" | "SELL"; qty: number; entry_price: number; ltp: number; stoploss: number;
  target: number; capital_deployed: number; unrealized_pnl: number; return_pct: number;
  opened_at: string; price_status: string;
}
export interface FocusTrade extends FocusPosition {
  exit_price: number; gross_pnl: number; fees: number; realized_pnl: number;
  closed_at: string; exit_reason: string;
}
export interface FocusSnapshot {
  mode: "PAPER"; real_orders_enabled: false; initial_capital: number;
  per_strategy_capital: number; slot_notional: number; slots_per_strategy: number;
  started_at: string | null; updated_at: string; realized_pnl: number; unrealized_pnl: number;
  total_pnl: number; return_pct: number; equity: number; available_cash: number;
  deployed_capital: number; fee_reserve: number; open_positions: number; closed_trades: number;
  feed: { source: string; status: string; last_quote_at: string | null; reason: string | null };
  engine: { enabled: boolean; entries_enabled: boolean; last_tick: string | null;
    last_evaluation: string | null; note: string | null };
  strategies: FocusStrategy[]; positions: FocusPosition[]; trades: FocusTrade[];
  daily: { date: string; trades: number; gross_pnl: number; fees: number;
    realized_pnl: number; return_pct: number }[];
  cost_note: string; validation_note: string;
}

export async function fetchFocusSnapshot(signal: AbortSignal): Promise<FocusSnapshot> {
  const response = await fetch(`${API_URL}/api/intraday-focus/snapshot`, {
    signal, cache: "no-store", credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`Could not load the five-strategy desk (HTTP ${response.status}).`);
  const data = await response.json();
  if (data.mode !== "PAPER" || data.real_orders_enabled !== false || !Array.isArray(data.strategies)) {
    throw new Error("The server returned an unexpected desk response. Results have not been replaced.");
  }
  return data as FocusSnapshot;
}
