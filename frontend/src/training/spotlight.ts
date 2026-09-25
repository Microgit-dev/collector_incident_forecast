// Подсветить элемент с data-tour; страница могла ещё не отрисоваться после перехода — ждём до 3 с
export function spotlight(target: string, attempts = 10) {
  const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`)
  if (!el) {
    if (attempts > 0) window.setTimeout(() => spotlight(target, attempts - 1), 300)
    return
  }
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('tour-spotlight')
  window.setTimeout(() => el.classList.remove('tour-spotlight'), 3600)
}

export function mmss(seconds: number) {
  const m = Math.floor(seconds / 60)
  return `${m}:${String(seconds % 60).padStart(2, '0')}`
}
