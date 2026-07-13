'use client'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { HealthResponse } from '@/lib/types'

export function useHealth() {
  return useQuery<HealthResponse, Error>({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 5000,
    retry: 3,
    retryDelay: 1000,
  })
}
