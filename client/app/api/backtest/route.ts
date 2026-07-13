import { NextResponse } from 'next/server'
import path from 'path'
import fs from 'fs'

const BACKTEST_DIR = path.join(
  process.cwd(),
  '..',
  'NIFTY-PILOT-SOVEREIGN',
  'engine',
  'backtest_results'
)

function findLatestRun(): string | null {
  if (!fs.existsSync(BACKTEST_DIR)) return null
  const dirs = fs
    .readdirSync(BACKTEST_DIR)
    .filter((d) => fs.statSync(path.join(BACKTEST_DIR, d)).isDirectory())
    .sort()
    .reverse()
  return dirs[0] ?? null
}

function readCSV(filePath: string): Record<string, string>[] {
  if (!fs.existsSync(filePath)) return []
  const lines = fs.readFileSync(filePath, 'utf-8').split('\n').filter(Boolean)
  if (lines.length < 2) return []
  const headers = lines[0].split(',')
  return lines.slice(1).map((line) => {
    const vals = line.split(',')
    return Object.fromEntries(headers.map((h, i) => [h.trim(), (vals[i] ?? '').trim()]))
  })
}

export async function GET() {
  const run = findLatestRun()
  if (!run) {
    return NextResponse.json({ available: false, run: null })
  }

  const runDir = path.join(BACKTEST_DIR, run)

  const readJSON = <T>(name: string): T | null => {
    const p = path.join(runDir, name)
    if (!fs.existsSync(p)) return null
    try {
      return JSON.parse(fs.readFileSync(p, 'utf-8')) as T
    } catch {
      return null
    }
  }

  const summary = readJSON<Record<string, unknown>>('summary.json')
  const leaderboardRaw = readJSON<{ value: unknown[]; Count: number } | unknown[]>('leaderboard.json')
  const walkforward = readJSON<unknown[]>('walkforward_details.json')
  const equityCurve = readCSV(path.join(runDir, 'equity_curve.csv'))
  const dailyPnl = readCSV(path.join(runDir, 'daily_pnl.csv'))
  const regimeAnalysis = readCSV(path.join(runDir, 'regime_analysis.csv'))

  return NextResponse.json({
    available: true,
    run,
    summary,
    leaderboard: Array.isArray(leaderboardRaw)
      ? leaderboardRaw
      : (leaderboardRaw as { value: unknown[] } | null)?.value ?? [],
    walkforward: walkforward ?? [],
    equityCurve,
    dailyPnl,
    regimeAnalysis,
  })
}
