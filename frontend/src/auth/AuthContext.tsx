import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'

import { ApiError, api, tokens } from '../api/client'
import type { Me } from '../api/types'

interface AuthState {
  user: Me | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  can: (perm: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => api<Me>('/auth/me/'),
    enabled: Boolean(tokens.access),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 5 * 60_000,
  })

  const login = useCallback(
    async (username: string, password: string) => {
      const data = await api<{ access: string; refresh: string }>('/auth/token/', {
        method: 'POST',
        body: { username, password },
      })
      tokens.save(data.access, data.refresh)
      await queryClient.fetchQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me/') })
    },
    [queryClient],
  )

  const logout = useCallback(() => {
    // отозвать refresh на сервере: украденной копией токена после выхода не воспользоваться
    const refresh = tokens.refresh
    const pending = [
      refresh ? api('/auth/logout/', { method: 'POST', body: { refresh } }) : Promise.resolve(),
      // и закрыть сеанс Grafana / Prometheus (cookie, по которой их пускает Caddy)
      api('/observability/session/', { method: 'DELETE', contour: 'combat' }),
      // и закрыть сеансы админки обеих подсистем, открытые без второго пароля
      api('/auth/admin-session/', { method: 'DELETE', contour: 'combat' }),
      api('/auth/admin-session/', { method: 'DELETE', contour: 'training' }),
    ]
    tokens.clear()
    queryClient.clear()
    // переход — после ответов (не дольше 2 с): иначе браузер оборвёт запросы
    const timeout = new Promise((resolve) => setTimeout(resolve, 2000))
    void Promise.race([Promise.allSettled(pending), timeout]).then(() => window.location.assign('/login'))
  }, [queryClient])

  const value = useMemo<AuthState>(() => {
    const user = tokens.access ? (me.data ?? null) : null
    const perms = new Set(user?.permissions ?? [])
    return {
      user,
      loading: Boolean(tokens.access) && me.isLoading,
      login,
      logout,
      // Интерфейс лишь прячет недоступное; права проверяет бэкенд
      can: (perm) => Boolean(user?.is_superuser || perms.has(perm)),
    }
  }, [me.data, me.isLoading, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}
