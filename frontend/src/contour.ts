/**
 * Подсистемы единой платформы на одном адресе: основная система — в корне, учебный контур — под /training/.
 * Интерфейс один и тот же; от префикса адреса зависят маршруты, API и WebSocket. Вход общий: токен
 * выдаёт основная система (/api/v1/auth/token/), и он действует в обеих подсистемах.
 */

export const TRAINING_PREFIX = '/training'

export type ContourCode = 'combat' | 'training'

/** Подсистема, в которой открыта страница. */
export const CONTOUR: ContourCode =
  window.location.pathname === TRAINING_PREFIX || window.location.pathname.startsWith(`${TRAINING_PREFIX}/`)
    ? 'training'
    : 'combat'

/** Префикс маршрутов и API подсистемы: '' — основная система, '/training' — учебный контур. */
export const BASE = CONTOUR === 'training' ? TRAINING_PREFIX : ''

export const prefixOf = (contour: ContourCode) => (contour === 'training' ? TRAINING_PREFIX : '')

/** Полный путь страницы в подсистеме: переход между подсистемами — обычная загрузка страницы, без входа. */
export const contourHref = (contour: ContourCode, path = '/') => `${prefixOf(contour)}${path}`

/** Страница входа платформы (одна на все подсистемы) с возвратом туда, откуда пришли. */
export function loginHref(next?: string): string {
  const back = next ?? window.location.pathname + window.location.search
  return back && back !== '/' && back !== '/login' ? `/login?next=${encodeURIComponent(back)}` : '/login'
}

/** Куда можно вернуть после входа: только свои пути, не чужие сайты. */
export function safeNext(raw: string | null): string | null {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/login')) return null
  return raw
}
