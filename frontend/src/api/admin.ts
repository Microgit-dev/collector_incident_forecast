import { CONTOUR, prefixOf, TRAINING_PREFIX, type ContourCode } from '../contour'
import { api } from './client'

/**
 * Открыть раздел админки без второго входа: бэкенд по нашему токену открывает сеанс Django
 * (POST /auth/admin-session/), затем переходим в раздел. Вкладка открывается сразу по щелчку,
 * иначе браузер сочтёт её всплывающим окном и заблокирует.
 */
export async function openAdmin(path = '', contour: ContourCode = CONTOUR): Promise<void> {
  const tab = window.open('about:blank', '_blank')
  try {
    const { url } = await api<{ url: string }>('/auth/admin-session/', { method: 'POST', contour })
    const target = `${url}${path.replace(/^\//, '')}`
    if (tab) tab.location.href = target
    else window.location.assign(target)
  } catch (error) {
    tab?.close()
    throw error
  }
}

/** Вход в платформу с возвратом в админку (её страница входа ведёт сюда): сеанс Django и переход. */
export async function returnTo(next: string): Promise<void> {
  const contour: ContourCode = next.startsWith(`${TRAINING_PREFIX}/`) ? 'training' : 'combat'
  const admin = next.startsWith(`${prefixOf(contour)}/admin/`)
  if (admin) await api('/auth/admin-session/', { method: 'POST', contour })
  window.location.assign(next)
}
