'use client'
import { getRegimeDisplay } from '@/lib/formatters'
import { REGIMES } from '@/lib/constants'

export function RegimeChip({ regime }: { regime: string }) {
  const display = getRegimeDisplay(regime)
  const def = REGIMES.find((r) => r.code === regime)

  return (
    <div className="space-y-2">
      <span
        className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold border"
        style={{
          backgroundColor: `${display.color}20`,
          color: display.color,
          borderColor: `${display.color}40`,
        }}
      >
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: display.color }}
        />
        {display.label}
      </span>
      {def && (
        <p className="text-text-muted text-xs">{display.description}</p>
      )}
      {def && (
        <p className="text-text-secondary text-xs">
          Position multiplier:{' '}
          <span className="font-mono font-medium text-text-primary">
            {def.sizeMult === 0 ? 'BLOCKED' : `${def.sizeMult}×`}
          </span>
        </p>
      )}
    </div>
  )
}
