'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Trade } from '@/lib/types'

export function usePositions() {
  return useQuery<Trade[], Error>({
    queryKey: ['positions'],
    queryFn: api.positions,
    refetchInterval: 5000,
    retry: 3,
  })
}
