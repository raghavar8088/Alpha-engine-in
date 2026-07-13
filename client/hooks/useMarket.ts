'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { MarketData } from '@/lib/types'

export function useMarket() {
  return useQuery<MarketData, Error>({
    queryKey: ['market'],
    queryFn: api.market,
    refetchInterval: 3000,
    retry: 3,
  })
}
