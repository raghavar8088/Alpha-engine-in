'use client'
import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { currentIST, formatPrice, formatPct } from '@/lib/formatters'
import { useMarket } from '@/hooks/useMarket'
import { useHealth } from '@/hooks/useHealth'
import { MarketStatusBadge } from '@/components/dashboard/MarketStatusBadge'

function PriceTicker({
  label,
  value,
  change,
}: {
  label: string
  value: number
  change?: number
}) {
  const prevRef = useRef<number>(value)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)

  useEffect(() => {
    if (value !== prevRef.current) {
      setFlash(value > prevRef.current ? 'up' : 'down')
      prevRef.current = value
      const t = setTimeout(() => setFlash(null), 300)
      return () => clearTimeout(t)
    }
  }, [value])

  const isPos = (change ?? 0) >= 0

  return (
    <div
      className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition-colors duration-300 ${
        flash === 'up'
          ? 'bg-profit-green/20'
          : flash === 'down'
          ? 'bg-loss-red/20'
          : ''
      }`}
    >
      <span className="text-text-muted text-xs font-medium">{label}</span>
      <span className="text-text-primary text-sm font-mono font-medium">
        {formatPrice(value)}
      </span>
      {change !== undefined && (
        <span
          className={`text-xs font-medium ${isPos ? 'text-profit-green' : 'text-loss-red'}`}
        >
          {formatPct(change / 100, 2, true)}
        </span>
      )}
    </div>
  )
}

interface HeaderProps {
  title: string
}

export function Header({ title }: HeaderProps) {
  const { data: market } = useMarket()
  const { data: health } = useHealth()
  const [time, setTime] = useState(currentIST())

  useEffect(() => {
    const interval = setInterval(() => setTime(currentIST()), 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="h-14 border-b border-border bg-surface/80 backdrop-blur-sm flex items-center justify-between px-6 sticky top-0 z-30">
      {/* Page title */}
      <h1 className="text-text-primary font-semibold text-lg hidden md:block">{title}</h1>

      {/* Ticker strip */}
      <div className="flex items-center gap-1 overflow-x-auto">
        {market ? (
          <>
            <PriceTicker label="NIFTY" value={market.spot} />
            <span className="text-border">|</span>
            <PriceTicker label="BANKNIFTY" value={market.banknifty_spot} />
            <span className="text-border">|</span>
            <div className="flex items-center gap-1.5 px-3 py-1">
              <span className="text-text-muted text-xs font-medium">VIX</span>
              <span className="text-neutral-yellow text-sm font-mono font-medium">
                {market.vix.toFixed(1)}
              </span>
            </div>
            <div className="flex items-center gap-1 ml-1">
              <span className="inline-block w-2 h-2 rounded-full bg-neutral-yellow animate-pulse" />
              <span className="text-neutral-yellow text-xs font-medium">SYNTHETIC DATA</span>
            </div>
          </>
        ) : (
          <div className="h-4 w-60 animate-skeleton rounded bg-surface-elevated" />
        )}
      </div>

      {/* Right: status + clock */}
      <div className="flex items-center gap-4">
        <AnimatePresence mode="wait">
          <motion.span
            key={health?.status ?? 'loading'}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.2 }}
          >
            {health && <MarketStatusBadge status={health.status} />}
          </motion.span>
        </AnimatePresence>
        <span className="text-text-muted text-xs font-mono hidden sm:block">{time}</span>
      </div>
    </header>
  )
}
