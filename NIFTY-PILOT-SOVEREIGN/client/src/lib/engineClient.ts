import type {
  EquitySnapshot,
  HealthSnapshot,
  MarketSnapshot,
  StrategyStatus,
  Trade,
  MockTradingStatus,
  MockTradingPortfolio,
  MockTradingAnalytics,
  StrategyValidationStatus,
  LeaderboardEntry,
} from "./types";

// All calls go through the /api/engine/* rewrite (next.config.ts),
// which proxies to the Go engine at INTERNAL_API_URL.
const BASE = "/api/engine";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`engine request failed: ${path} -> ${res.status}`);
  return res.json();
}

export const engine = {
  // Core endpoints
  health: () => getJSON<HealthSnapshot>("/health"),
  equity: () => getJSON<EquitySnapshot>("/api/equity"),
  positions: () => getJSON<Trade[]>("/api/positions"),
  trades: () => getJSON<Trade[]>("/api/trades"),
  strategies: () => getJSON<StrategyStatus[]>("/api/strategies"),
  market: () => getJSON<MarketSnapshot>("/api/market"),

  // Mock Trading endpoints
  mockTradingStatus: () => getJSON<MockTradingStatus>("/api/mock-trading/status"),
  mockTradingPortfolio: () => getJSON<MockTradingPortfolio>("/api/mock-trading/portfolio"),
  mockTradingAnalytics: () => getJSON<MockTradingAnalytics>("/api/mock-trading/analytics"),
  mockTradingLeaderboard: () => getJSON<LeaderboardEntry[]>("/api/mock-trading/leaderboard"),

  // Strategy validation
  strategiesValidation: () => getJSON<StrategyValidationStatus[]>("/api/strategies/validation"),
};
