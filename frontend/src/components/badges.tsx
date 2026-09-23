import { Badge } from '@mantine/core'

import { INCIDENT_STATUS, RISK } from '../api/labels'
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
