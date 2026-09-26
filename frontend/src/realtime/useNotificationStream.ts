import { notifications } from '@mantine/notifications'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api, tokens } from '../api/client'
import { RISK } from '../api/labels'
import type { AppNotification } from '../api/types'

/**
 * Персональный WebSocket-поток уведомлений. На каждое уведомление — всплывающее сообщение
 * и инвалидация связанных запросов, чтобы списки обновлялись без перезагрузки страницы.
 */
export function useNotificationStream(enabled: boolean) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!enabled) return
    let socket: WebSocket | null = null
    let retry: number | undefined
    let attempt = 0
    let closed = false

    const connect = async () => {
      // access живёт 30 минут: перед (пере)подключением обновить его, иначе сокет откроется с просроченным
      await api('/auth/me/').catch(() => undefined)
      if (closed) return
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // токен — в заголовке Sec-WebSocket-Protocol, не в адресе: адреса попадают в журналы серверов
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/notifications/`, ['jwt', tokens.access ?? ''])
      socket.onopen = () => {
        attempt = 0
      }
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as { type: string; data: AppNotification }
        if (message.type === 'incident') {
          // карточку взяли или перехватили — очередь, схема и открытая карточка обновляются сразу
          for (const key of ['incidents', 'live', 'workspace', 'scheme', 'training-current']) {
            void queryClient.invalidateQueries({ queryKey: [key] })
          }
          return
        }
        if (message.type !== 'notification') return
        const n = message.data
        notifications.show({
          title: n.title,
          message: n.body,
          color: RISK[n.level]?.color ?? 'blue',
          autoClose: n.level === 'critical' ? false : 8000,
        })
        void queryClient.invalidateQueries({ queryKey: ['incidents'] })
        void queryClient.invalidateQueries({ queryKey: ['overview'] })
        void queryClient.invalidateQueries({ queryKey: ['notifications'] })
        void queryClient.invalidateQueries({ queryKey: ['exercises'] })
      }
      socket.onclose = () => {
        if (closed) return
        // Экспоненциальная пауза переподключения, не чаще раза в 30 с
        retry = window.setTimeout(() => void connect(), Math.min(30_000, 1000 * 2 ** attempt++))
      }
    }
    void connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      socket?.close()
    }
  }, [enabled, queryClient])
}
