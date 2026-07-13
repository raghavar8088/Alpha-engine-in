import type {
  HealthResponse,
  EquityRaw,
  EquityResponse,
  TradeRaw,
  Trade,
  StrategyStatsRaw,
  StrategyStats,
  MarketDataRaw,
  MarketData,
  MockTradingStatus,
  MockTradingPortfolio,
  MockTradingAnalytics,
  LeaderboardEntry,
  StrategyValidationStatus,
} from './types'
import { STRATEGIES } from './constants'

const BASE = '/api/proxy'

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`)
  }
  return res.json() as Promise<T>
}

// ── Normalisation helpers ─────────────────────────────────────────────────────

function normaliseTrade(r: TradeRaw): Trade {
  const nullExit =
    !r.ExitAt ||
    r.ExitAt === '0001-01-01T00:00:00Z' ||
    r.ExitAt.startsWith('0001')
      ? null
      : r.ExitAt

  return {
    id: r.ID,
    strategy: r.Strategy,
    underlying: r.Underlying,
    instrument: r.Instrument,
    direction: r.Direction,
    strike: r.Strike,
    lots: r.Lots,
    quantity: r.Quantity,
    entryPrice: r.EntryPrice,
    stopLoss: r.StopLoss,
    takeProfit: r.TakeProfit,
    exitPrice: r.ExitPrice,
    exitReason: r.ExitReason,
    entryAt: r.EntryAt,
    exitAt: nullExit,
    status: r.Status,
    grossPnl: r.GrossPnL,
    entryCostINR: r.EntryCostINR,
    exitCostINR: r.ExitCostINR,
    netPnl: r.NetPnL,
    marginBlockedINR: r.MarginBlockedINR,
  }
}

/** Map engine strategy ID (e.g. "S8_EMA_Ribbon_Trend_Rider") → short form "S8" */
function shortId(raw: string): string {
  const m = /^(S\d+)/.exec(raw)
  return m ? m[1] : raw
}

function normaliseStrategy(r: StrategyStatsRaw): StrategyStats {
  const id = shortId(r.strategy)
  const def = STRATEGIES.find((s) => s.id === id)

  // Map engine status strings
  const statusMap: Record<string, StrategyStats['status']> = {
    ACTIVE: 'ACTIVE',
    PROBATION: 'INSUFFICIENT_DATA',
    BLOCKED: 'BLOCKED',
    DEMOTED: 'DEMOTED',
    INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
  }
  const status = statusMap[r.status] ?? 'INSUFFICIENT_DATA'

  return {
    id,
    name: def?.name ?? r.strategy,
    timeframe: def?.timeframe ?? 'intraday',
    regime: def?.allowedRegimes.join(', ') ?? '',
    totalTrades: 0,
    winRate: r.last_window_winrate,
    netPnl: 0,
    sharpe: r.last_window_sharpe,
    maxDrawdown: 0,
    status,
    promotionWindow: r.status === 'ACTIVE' ? 2 : r.status === 'PROBATION' ? 1 : 0,
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

export const api = {
  health: () => fetchJSON<HealthResponse>('/health'),

  equity: async (): Promise<EquityResponse> => {
    const r = await fetchJSON<EquityRaw>('/api/equity')
    return {
      capital: r.capital_inr,
      equity: r.equity_inr,
      margin_used: r.margin_used_inr,
      margin_available: r.margin_available_inr,
      margin_utilization_pct: r.margin_utilization_pct,
      pnl: r.realized_pnl_inr,
    }
  },

  positions: async (): Promise<Trade[]> => {
    const raw = await fetchJSON<TradeRaw[] | null>('/api/positions')
    if (!raw) return []
    return raw.map(normaliseTrade)
  },

  trades: async (): Promise<Trade[]> => {
    const raw = await fetchJSON<TradeRaw[] | null>('/api/trades')
    if (!raw) return []
    return raw.map(normaliseTrade)
  },

  strategies: async (): Promise<StrategyStats[]> => {
    const raw = await fetchJSON<StrategyStatsRaw[] | null>('/api/strategies')
    if (!raw) return []
    return raw.map(normaliseStrategy)
  },

  // ── Mock Trading ───────────────────────────────────────────────────────────

  mockTradingStatus: () =>
    fetchJSON<MockTradingStatus>('/api/mock-trading/status'),

  mockTradingPortfolio: () =>
    fetchJSON<MockTradingPortfolio>('/api/mock-trading/portfolio'),

  mockTradingAnalytics: () =>
    fetchJSON<MockTradingAnalytics>('/api/mock-trading/analytics'),

  mockTradingLeaderboard: () =>
    fetchJSON<LeaderboardEntry[]>('/api/mock-trading/leaderboard'),

  strategiesValidation: () =>
    fetchJSON<StrategyValidationStatus[]>('/api/strategies/validation'),

  // ── Market ────────────────────────────────────────────────────────────────

  market: async (): Promise<MarketData> => {
    const r = await fetchJSON<MarketDataRaw>('/api/market')

    // Derive regime from VIX when engine doesn't send it
    let regime = r.regime ?? ''
    let regime_code = r.regime_code ?? 1
    if (!regime) {
      if (r.india_vix > 22) {
        regime = 'HighVol'; regime_code = 4
      } else if (r.india_vix > 17) {
        regime = 'Ranging'; regime_code = 3
      } else {
        regime = 'TrendingBull'; regime_code = 1
      }
    }

    return {
      spot: r.nifty_spot,
      banknifty_spot: r.banknifty_spot,
      vix: r.india_vix,
      pcr: r.nifty_pcr,
      max_pain: r.nifty_max_pain,
      regime,
      regime_code,
    }
  },
}
