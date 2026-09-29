/**
 * Grafana и Prometheus открываются в новой вкладке под учётной записью системы: бэкенд ставит cookie
 * сеанса, по которой Caddy пускает к панелям после проверки роли (apps/accounts/observability.py).
 * Тем же сеансом руководитель учений открывает веб-интерфейс симулятора датчиков.
 */
import { notifications } from '@mantine/notifications'

import { api } from './client'

export const GRAFANA_PERM = 'accounts.view_grafana'
export const SYSTEM_PERM = 'accounts.view_system_monitoring'

type Target = 'grafana' | 'business' | 'system' | 'prometheus' | 'simulator'

export async function openObservability(target: Target): Promise<void> {
  // Вкладку открываем сразу, по клику: после await браузер счёл бы её всплывающим окном
  const tab = window.open('about:blank', '_blank')
  try {
    const links = await api<Record<Target, string | null>>('/observability/session/', { method: 'POST', contour: 'combat' })
    const url = links[target]
    if (!url) throw new Error('Панель недоступна вашей роли')
    if (tab) tab.location.href = url
    else window.location.assign(url)
  } catch (error) {
    tab?.close()
    notifications.show({ color: 'red', title: 'Не удалось открыть панель', message: (error as Error).message })
  }
}
