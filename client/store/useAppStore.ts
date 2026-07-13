import { create } from 'zustand'

interface AppState {
  killSwitchActive: boolean
  setKillSwitchActive: (v: boolean) => void
  selectedStrategy: string | null
  setSelectedStrategy: (id: string | null) => void
  engineUrl: string
  setEngineUrl: (url: string) => void
  pollingInterval: number
  setPollingInterval: (ms: number) => void
  compactMode: boolean
  setCompactMode: (v: boolean) => void
  defaultChartRange: '1W' | '1M' | '3M' | 'ALL'
  setDefaultChartRange: (r: '1W' | '1M' | '3M' | 'ALL') => void
}

export const useAppStore = create<AppState>((set) => ({
  killSwitchActive: false,
  setKillSwitchActive: (v) => set({ killSwitchActive: v }),
  selectedStrategy: null,
  setSelectedStrategy: (id) => set({ selectedStrategy: id }),
  engineUrl: 'http://localhost:8090',
  setEngineUrl: (url) => set({ engineUrl: url }),
  pollingInterval: 5000,
  setPollingInterval: (ms) => set({ pollingInterval: ms }),
  compactMode: false,
  setCompactMode: (v) => set({ compactMode: v }),
  defaultChartRange: '1M',
  setDefaultChartRange: (r) => set({ defaultChartRange: r }),
}))
