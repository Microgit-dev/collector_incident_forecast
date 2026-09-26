import type { MonitoringMode, MonitoringObject, RiskLevel } from '../api/types'

/** Цвета уровней — те же, что у значков риска в интерфейсе. */
export const LEVEL_COLOR: Record<RiskLevel, string> = {
  low: '#74c0fc',
  medium: '#fab005',
  high: '#fd7e14',
  critical: '#fa5252',
}
export const OK = '#40c057'
export const QUIET = '#adb5bd'
export const WARN = '#fd7e14'
export const BAD = '#fa5252'
export const ORDER = '#228be6'
export const APPROVAL = '#7950f2'

export const MODE_LABEL: Record<MonitoringMode, string> = {
  situation: 'Обстановка',
  risk: 'Прогноз',
  state: 'Датчики',
  health: 'Данные',
  orders: 'Заявки',
}

export const MODE_HINT: Record<MonitoringMode, string> = {
  situation: 'Цвет — самая серьёзная открытая карточка объекта; зелёный — карточек нет',
  risk: 'Цвет — наибольший уровень прогноза риска по каналам объекта',
  state: 'Цвет — доля датчиков не в норме: тревога, неисправность, обесточен, неизвестно',
  health: 'Цвет — каналы с низким Data Health (ниже 40) и молчащие',
  orders: 'Цвет — открытые заявки: просроченные, на утверждении, в работе',
}

/** Легенда режима: что означают цвета. */
export const LEGEND: Record<MonitoringMode, { color: string; label: string }[]> = {
  situation: [
    { color: OK, label: 'нет карточек' },
    { color: LEVEL_COLOR.medium, label: 'средний' },
    { color: LEVEL_COLOR.high, label: 'высокий' },
    { color: LEVEL_COLOR.critical, label: 'критический' },
  ],
  risk: [
    { color: OK, label: 'низкий' },
    { color: LEVEL_COLOR.medium, label: 'средний' },
    { color: LEVEL_COLOR.high, label: 'высокий' },
    { color: LEVEL_COLOR.critical, label: 'критический' },
  ],
  state: [
    { color: OK, label: 'все в норме' },
    { color: WARN, label: 'есть не в норме' },
    { color: BAD, label: 'больше 10 %' },
  ],
  health: [
    { color: OK, label: 'данным можно доверять' },
    { color: WARN, label: 'есть слабые каналы' },
    { color: BAD, label: 'больше 10 %' },
  ],
  orders: [
    { color: QUIET, label: 'заявок нет' },
    { color: ORDER, label: 'в работе' },
    { color: APPROVAL, label: 'на утверждении' },
    { color: BAD, label: 'просрочены' },
  ],
}

function share(part = 0, total = 0) {
  return total ? part / total : 0
}

export function objectColor(o: MonitoringObject, mode: MonitoringMode): string {
  if (!o.mine) return QUIET
  switch (mode) {
    case 'situation':
      return o.incident_level ? LEVEL_COLOR[o.incident_level] : OK
    case 'risk':
      return o.risk_level && o.risk_level !== 'low' ? LEVEL_COLOR[o.risk_level] : OK
    case 'state':
      return !o.abnormal ? OK : share(o.abnormal, o.channels) > 0.1 ? BAD : WARN
    case 'health': {
      const weak = (o.health_low ?? 0) + (o.silent ?? 0)
      return !weak ? OK : share(weak, o.channels) > 0.1 ? BAD : WARN
    }
    case 'orders':
      return o.overdue ? BAD : o.approvals ? APPROVAL : o.orders ? ORDER : QUIET
  }
}

/** Насколько объект «горит» в режиме — для сортировки списка «Моя зона». */
export function objectWeight(o: MonitoringObject, mode: MonitoringMode): number {
  const lvl = (l?: RiskLevel | null) => (l ? ['low', 'medium', 'high', 'critical'].indexOf(l) + 1 : 0)
  switch (mode) {
    case 'situation':
      return lvl(o.incident_level) * 1000 + (o.escalated ?? 0) * 100 + (o.incidents ?? 0)
    case 'risk':
      return lvl(o.risk_level) * 1000 + (o.abnormal ?? 0)
    case 'state':
      return o.abnormal ?? 0
    case 'health':
      return (o.health_low ?? 0) + (o.silent ?? 0)
    case 'orders':
      return (o.overdue ?? 0) * 1000 + (o.approvals ?? 0) * 100 + (o.orders ?? 0)
  }
}

export const SENSOR_COLOR: Record<string, string> = {
  normal: OK,
  warning: '#fab005',
  alarm: BAD,
  fault: WARN,
  power_loss: '#e64980',
  unknown: QUIET,
}
