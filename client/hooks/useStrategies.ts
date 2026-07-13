'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { StrategyStats } from '@/lib/types'

export function useStrategies() {
  return useQuery<StrategyStats[], Error>({
    queryKey: ['strategies'],
    queryFn: api.strategies,
    refetchInterval: 10000,
    retry: 3,
  })
}
