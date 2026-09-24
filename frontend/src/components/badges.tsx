import { Badge, Tooltip } from '@mantine/core'

import { CONTOUR, INCIDENT_STATUS, RISK } from '../api/labels'
import type { IncidentStatus, RiskLevel } from '../api/types'

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <Badge color={RISK[level].color} variant={level === 'critical' ? 'filled' : 'light'}>
      {RISK[level].label}
    </Badge>
  )
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <Badge color={INCIDENT_STATUS[status].color} variant="dot">
      {INCIDENT_STATUS[status].label}
    </Badge>
  )
}

export function ContourBadge({ contour }: { contour: string }) {
  const c = CONTOUR[contour] ?? CONTOUR.technical
  return (
    <Badge size="xs" variant="outline" color={c.color}>
      {c.label}
    </Badge>
  )
}

export function PriorityBadge({ value }: { value: number }) {
  const color = value >= 60 ? 'red' : value >= 35 ? 'orange' : value >= 15 ? 'yellow' : 'gray'
  return (
    <Tooltip label="Операционный приоритет 0–100: тяжесть × контур × критичность объекта × уверенность данных × срочность">
      <Badge color={color} variant="filled" size="lg" radius="sm" w={52}>
        {Math.round(value)}
      </Badge>
    </Tooltip>
  )
}
