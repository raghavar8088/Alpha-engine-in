'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Trade } from '@/lib/types'

export function useTrades() {
  return useQuery<Trade[], Error>({
    queryKey: ['trades'],
    queryFn: api.trades,
    refetchInterval: 10000,
    retry: 3,
  })
}
