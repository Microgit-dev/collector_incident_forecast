import type {
  DecisionCause,
  DecisionOutcome,
  IncidentStatus,
  IncidentType,
  PredictionOutcome,
  RiskLevel,
  WorkOrderStatus,
} from './types'

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
  temperature: 'Аномальная температура',
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
  maintenance_engineer: 'Инженер ТО',
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

export const TASK: Record<string, string> = {
  sensor_failure: 'Отказ датчика',
  gas: 'Загазованность',
  flood: 'Подтопление',
  fire: 'Пожар (индикатор)',
  intrusion: 'НСД (индикатор)',
}

// Что произошло — обратная связь диспетчера (ТЗ §12), подсказка — как это учтёт модель отказа датчика
export const CAUSE: Record<DecisionCause, { label: string; hint: string }> = {
  sensor_fault: { label: 'Неисправность датчика', hint: 'подтверждённый отказ канала — пример для обучения' },
  communication: { label: 'Потеря связи', hint: 'канал исправен, «неисправен» в журнале — от связи' },
  power: { label: 'Обесточивание', hint: 'канал исправен, пропадало питание' },
  false_alarm: { label: 'Ложное срабатывание', hint: 'угрозы не было' },
  external: { label: 'Внешнее воздействие', hint: 'нагрев, конденсат, пыль, вибрация' },
  works: { label: 'Работы на объекте', hint: 'эти сутки исключаются из обучения' },
  real_event: { label: 'Реальное событие', hint: 'угроза подтвердилась' },
  insufficient_data: { label: 'Недостаточно данных', hint: 'вывод сделать нельзя — метка не ставится' },
}

export const WO_STATUS: Record<WorkOrderStatus, { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'gray' },
  approved: { label: 'Утверждена', color: 'blue' },
  submitted: { label: 'Передана в систему заявок', color: 'indigo' },
  in_progress: { label: 'В работе', color: 'orange' },
  done: { label: 'Выполнена', color: 'teal' },
  cancelled: { label: 'Отменена', color: 'gray' },
}

// Пожар и НСД — индикаторы по правилам (подтверждённых событий в данных нет): индекс 0–1 складывает признаки,
// вероятность проявления угрозы за 24 ч получается из индекса калибровкой по архиву
export const isIndicator = (task: string) => task === 'fire' || task === 'intrusion'

// Фактическое состояние оборудования по последнему осмотру или ТО
export const CONDITION: Record<string, { label: string; color: string }> = {
  good: { label: 'Исправно', color: 'teal' },
  remarks: { label: 'Есть замечания', color: 'yellow' },
  needs_repair: { label: 'Требует ремонта', color: 'orange' },
  faulty: { label: 'Неисправно', color: 'red' },
}

export const WORK_TYPE: Record<string, string> = {
  inspection: 'Осмотр / проверка',
  sensor_replacement: 'Замена датчика',
  calibration: 'Калибровка / поверка',
  power_check: 'Проверка электропитания',
  pump_service: 'Обслуживание насосов',
  ventilation: 'Обслуживание вентиляции',
  cleaning: 'Очистка / откачка',
  security: 'Проверка охраны периметра',
}

export const EQUIPMENT_SOURCE: Record<string, { label: string; color: string }> = {
  imported: { label: 'реестр заказчика', color: 'teal' },
  manual: { label: 'вручную', color: 'blue' },
  emulated: { label: 'эмуляция', color: 'gray' },
}
