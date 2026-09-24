import type { DecisionOutcome, IncidentStatus, IncidentType, PredictionOutcome, RiskLevel } from './types'

export const RISK: Record<RiskLevel, { label: string; color: string }> = {
  low: { label: 'Низкий', color: 'gray' },
  medium: { label: 'Средний', color: 'yellow' },
  high: { label: 'Высокий', color: 'orange' },
  critical: { label: 'Критический', color: 'red' },
}

export const INCIDENT_TYPE: Record<IncidentType, string> = {
  sensor_failure: 'Отказ датчика',
  fire: 'Пожар / задымление',
  gas: 'Загазованность',
  flood: 'Подтопление',
  intrusion: 'Несанкционированный доступ',
  power: 'Потеря питания',
  equipment: 'Отказ оборудования',
  communication: 'Потеря связи',
}

export const INCIDENT_STATUS: Record<IncidentStatus, { label: string; color: string }> = {
  new: { label: 'Новый', color: 'red' },
  acknowledged: { label: 'Принят', color: 'blue' },
  in_progress: { label: 'В работе', color: 'indigo' },
  resolved: { label: 'Решён', color: 'teal' },
  closed: { label: 'Закрыт', color: 'gray' },
}

export const OUTCOME: Record<DecisionOutcome, string> = {
  brigade_dispatched: 'Выезд бригады',
  check_requested: 'Направлена проверка',
  monitoring: 'Мониторинг ситуации',
  false_alarm: 'Ложное срабатывание',
  confirmed: 'Инцидент подтверждён',
  resolved: 'Устранено',
}

export const CHANNEL_STATE: Record<string, { label: string; color: string }> = {
  normal: { label: 'Норма', color: 'teal' },
  warning: { label: 'Предупреждение', color: 'yellow' },
  alarm: { label: 'Тревога', color: 'red' },
  fault: { label: 'Неисправность', color: 'orange' },
  power_loss: { label: 'Нет питания', color: 'grape' },
  unknown: { label: 'Не определено', color: 'gray' },
  event: { label: 'Событие', color: 'blue' },
}

export const ROLE: Record<string, string> = {
  admin: 'Администратор',
  head: 'Руководитель подразделения',
  ods_dispatcher: 'Диспетчер ОДС',
  unit_dispatcher: 'Диспетчер подразделения',
  analyst: 'Аналитик',
  technician: 'Ремонтная бригада',
  observer: 'Наблюдатель',
}

export const PREDICTION_OUTCOME: Record<PredictionOutcome, { label: string; color: string }> = {
  pending: { label: 'Ожидает', color: 'gray' },
  confirmed: { label: 'Подтвердился', color: 'red' },
  not_confirmed: { label: 'Не подтвердился', color: 'teal' },
  prevented: { label: 'Предотвращён', color: 'blue' },
}

export const CONTOUR: Record<string, { label: string; color: string }> = {
  physical: { label: 'Физический', color: 'red' },
  technical: { label: 'Технический', color: 'blue' },
}

export const PRIORITY_FACTOR: Record<string, string> = {
  severity: 'Тяжесть',
  contour: 'Контур',
  criticality: 'Критичность объекта',
  confidence: 'Уверенность данных',
  urgency: 'Срочность',
  probability: 'Вероятность',
}

export const HEALTH_COMPONENT: Record<string, string> = {
  completeness: 'Полнота',
  freshness: 'Свежесть',
  technical: 'Время в исправном состоянии',
  stability: 'Стабильность частоты',
  consistency: 'Согласованность с соседями',
}
