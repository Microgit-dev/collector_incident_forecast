import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { RouteProps, Scheme } from './SchemeMap'

export function useScheme(complex: string | null | undefined, task: string, workorders: boolean) {
  return useQuery({
    queryKey: ['scheme', complex ?? null, task, workorders],
    queryFn: () =>
      api<Scheme>('/analytics/scheme/', {
        query: {
          ...(complex ? { complex } : {}),
          ...(task !== 'all' ? { task } : {}),
          ...(workorders ? { workorders: 1 } : {}),
        },
      }),
    refetchInterval: 60_000,
  })
}

export function useRoutes(complex: string | null | undefined, task: string, workorders: boolean) {
  const scheme = useScheme(complex, task, workorders)
  const features = scheme.data?.features ?? []
  return {
    routes: features.filter((f) => f.properties.kind === 'route').map((f) => f.properties as RouteProps),
    incidents: features.filter((f) => f.properties.kind === 'incident').length,
    workorders: features.filter((f) => f.properties.kind === 'workorder').length,
  }
}
