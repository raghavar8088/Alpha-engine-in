import { STRATEGY_MAP, LOT_SIZES, REGIMES } from './constants'

/**
 * Format a number in the Indian rupee number system.
 * Examples: 10000000 → ₹1,00,00,000  |  150000 → ₹1,50,000  |  -45600 → ₹-45,600
 */
export function formatINR(value: number, compact = false): string {
  const isNegative = value < 0
  const abs = Math.abs(value)
  const sign = isNegative ? '-' : ''

  if (compact) {
    if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)}Cr`
    if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(1)}L`
    if (abs >= 1000) return `${sign}₹${(abs / 1000).toFixed(1)}K`
    return `${sign}₹${abs.toFixed(0)}`
  }

  // Indian grouping: rightmost 3, then groups of 2 going left
  const showDecimals = abs < 1_00_000
  const fixed = abs.toFixed(showDecimals ? 2 : 0)
  const [intStr, decStr] = fixed.split('.')

  let formatted = ''
  if (intStr.length <= 3) {
    formatted = intStr
  } else {
    const last3 = intStr.slice(-3)
    const rest = intStr.slice(0, -3)
    const groups: string[] = []
    for (let i = rest.length; i > 0; i -= 2) {
      groups.unshift(rest.slice(Math.max(0, i - 2), i))
    }
    formatted = groups.join(',') + ',' + last3
  }

  const result = decStr ? `${formatted}.${decStr}` : formatted
  return `${sign}₹${result}`
}

/**
 * Format a number with explicit + sign for positive values, color-class-ready.
 */
export function formatINRSigned(value: number, compact = false): string {
  const formatted = formatINR(Math.abs(value), compact)
  if (value > 0) return `+${formatted}`
  if (value < 0) return `-${formatted.replace('₹', '').replace('-', '')}`.replace(/^-/, '-₹')
  return formatted
}

/** Return CSS class for profit/loss coloring */
export function pnlClass(value: number): string {
  if (value > 0) return 'text-profit-green'
  if (value < 0) return 'text-loss-red'
  return 'text-text-primary'
}

/**
 * Convert UTC ISO string to IST and format.
 * mode: 'datetime' = "25 Jun 09:30:00 IST"
 *       'date'     = "25 Jun 2024"
 *       'time'     = "09:30:00 IST"
 *       'relative' = "2 min ago", "3h ago"
 */
export function formatIST(
  utcString: string | null | undefined,
  mode: 'datetime' | 'date' | 'time' | 'relative' = 'datetime'
): string {
  if (!utcString) return '—'

  let date: Date
  try {
    date = new Date(utcString)
    if (isNaN(date.getTime())) return '—'
  } catch {
    return '—'
  }

  // IST = UTC + 5:30
  const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000
  const istDate = new Date(date.getTime() + IST_OFFSET_MS)

  if (mode === 'relative') {
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffSec = Math.floor(diffMs / 1000)
    if (diffSec < 60) return `${diffSec}s ago`
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin} min ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDay = Math.floor(diffHr / 24)
    return `${diffDay}d ago`
  }

  const day = istDate.getUTCDate().toString().padStart(2, '0')
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const month = monthNames[istDate.getUTCMonth()]
  const year = istDate.getUTCFullYear()
  const hh = istDate.getUTCHours().toString().padStart(2, '0')
  const mm = istDate.getUTCMinutes().toString().padStart(2, '0')
  const ss = istDate.getUTCSeconds().toString().padStart(2, '0')

  if (mode === 'date') return `${day} ${month} ${year}`
  if (mode === 'time') return `${hh}:${mm}:${ss} IST`
  return `${day} ${month} ${hh}:${mm}:${ss} IST`
}

/** Format current time in IST */
export function currentIST(): string {
  return formatIST(new Date().toISOString(), 'time')
}

/**
 * Format a percentage value.
 * showPlus = true → "+0.32%"
 */
export function formatPct(value: number, decimals = 1, showPlus = false): string {
  const fixed = (value * 100).toFixed(decimals)
  const prefix = showPlus && value > 0 ? '+' : ''
  return `${prefix}${fixed}%`
}

/**
 * Format raw ratio (e.g. 0.543 → "54.3%")
 */
export function formatWinRate(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

/**
 * Format lot size with underlying context.
 */
export function formatLots(lots: number, underlying: string): string {
  const ul = underlying.toUpperCase()
  const unitSize = LOT_SIZES[ul] ?? LOT_SIZES['NIFTY']
  const units = lots * unitSize
  return `${lots}L (${units.toLocaleString()}u)`
}

/** Format holding duration between two UTC timestamps */
export function formatHolding(entryAt: string, exitAt: string | null): string {
  if (!exitAt) {
    const diffMs = Date.now() - new Date(entryAt).getTime()
    return formatDuration(diffMs)
  }
  const diffMs = new Date(exitAt).getTime() - new Date(entryAt).getTime()
  return formatDuration(diffMs)
}

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const days = Math.floor(totalSec / 86400)
  const hours = Math.floor((totalSec % 86400) / 3600)
  const mins = Math.floor((totalSec % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}

/** Look up strategy name by ID */
export function getStrategyName(id: string): string {
  return STRATEGY_MAP[id] ?? id
}

/** Get regime display metadata */
export function getRegimeDisplay(regime: string): { label: string; color: string; description: string } {
  const r = REGIMES.find((x) => x.code === regime)
  if (r) return { label: r.label, color: r.color, description: r.description }
  return { label: regime, color: '#8B949E', description: '' }
}

/** Format Sharpe ratio */
export function formatSharpe(sharpe: number): string {
  return sharpe.toFixed(2)
}

/** Sharpe color */
export function sharpeClass(sharpe: number): string {
  if (sharpe >= 0.6) return 'text-profit-green'
  if (sharpe >= 0.2) return 'text-neutral-yellow'
  return 'text-loss-red'
}

/** Format price with 2 decimal places */
export function formatPrice(price: number): string {
  return price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
