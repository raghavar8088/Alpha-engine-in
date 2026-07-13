'use client'
import { motion } from 'framer-motion'
import type { MarketStatus } from '@/lib/types'

const CONFIG: Record<MarketStatus, { label: string; bg: string; dot: string; pulse: boolean }> = {
  OPEN: { label: 'OPEN', bg: 'bg-profit-green/15 text-profit-green border-profit-green/30', dot: 'bg-profit-green', pulse: true },
  PRE_OPEN: { label: 'PRE-OPEN', bg: 'bg-neutral-yellow/15 text-neutral-yellow border-neutral-yellow/30', dot: 'bg-neutral-yellow', pulse: false },
  CLOSED: { label: 'CLOSED', bg: 'bg-text-muted/15 text-text-secondary border-text-muted/30', dot: 'bg-text-muted', pulse: false },
  KILL_SWITCH_ACTIVE: { label: 'KILL SWITCH', bg: 'bg-loss-red/15 text-loss-red border-loss-red/30', dot: 'bg-loss-red', pulse: true },
}

export function MarketStatusBadge({ status }: { status: MarketStatus }) {
  const cfg = CONFIG[status]
  return (
    <span className={`inline-flex items-center gap-1.5 border px-2.5 py-0.5 rounded-full text-xs font-semibold ${cfg.bg}`}>
      <motion.span
        className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}
        animate={cfg.pulse ? { opacity: [1, 0.3, 1] } : {}}
        transition={{ repeat: Infinity, duration: 1.5 }}
      />
      {cfg.label}
    </span>
  )
}
