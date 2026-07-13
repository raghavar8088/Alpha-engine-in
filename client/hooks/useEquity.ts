'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { EquityResponse } from '@/lib/types'

export function useEquity() {
  return useQuery<EquityResponse, Error>({
    queryKey: ['equity'],
    queryFn: api.equity,
    refetchInterval: 5000,
    retry: 3,
  })
}
