'use client'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { useHealth } from '@/hooks/useHealth'
import { useAppStore } from '@/store/useAppStore'
import { useEffect } from 'react'

export function KillSwitchBanner() {
  const { data: health } = useHealth()
  const { killSwitchActive, setKillSwitchActive } = useAppStore()

  useEffect(() => {
    if (health?.status === 'KILL_SWITCH_ACTIVE') {
      setKillSwitchActive(true)
    }
  }, [health, setKillSwitchActive])

  const isActive = killSwitchActive || health?.status === 'KILL_SWITCH_ACTIVE'

  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <motion.div
            animate={{ opacity: [0.8, 1, 0.8] }}
            transition={{ repeat: Infinity, duration: 1.5 }}
            className="bg-loss-red/90 text-white px-6 py-2.5 flex items-center justify-center gap-3 kill-switch-banner"
          >
            <AlertTriangle size={18} className="shrink-0" />
            <span className="text-sm font-semibold">
              ⚠ KILL SWITCH ACTIVE — All trading halted. Go to Settings to deactivate.
            </span>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
