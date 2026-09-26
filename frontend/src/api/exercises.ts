import dayjs from 'dayjs'

import type { Exercise, ExerciseStatus } from './types'

export const EXERCISE_STATUS: Record<ExerciseStatus, { label: string; color: string }> = {
  scheduled: { label: 'Назначены', color: 'blue' },
  running: { label: 'Идут', color: 'red' },
  finished: { label: 'Завершены', color: 'teal' },
  stopped: { label: 'Прекращены досрочно', color: 'orange' },
  cancelled: { label: 'Отменены', color: 'gray' },
}

export function when(e: Exercise): string {
  if (e.started_at) return dayjs(e.started_at).format('DD.MM HH:mm')
  return e.scheduled_at ? `${dayjs(e.scheduled_at).format('DD.MM HH:mm')} (таймер)` : 'по кнопке'
}
