export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type IncidentStatus = 'new' | 'acknowledged' | 'in_progress' | 'resolved' | 'closed'
export type IncidentType = 'sensor_failure' | 'fire' | 'gas' | 'flood' | 'intrusion' | 'power' | 'equipment'
export type DecisionOutcome =
  | 'brigade_dispatched'
  | 'check_requested'
  | 'monitoring'
  | 'false_alarm'
  | 'confirmed'
  | 'resolved'

export interface Me {
  id: number
  username: string
  first_name: string
  last_name: string
  email: string
  position: string
  scope_node: number | null
  scope_node_name: string | null
  roles: string[]
  permissions: string[]
  is_superuser: boolean
}

export interface Overview {
  incidents_open: number
  incidents_by_severity: Partial<Record<RiskLevel, number>>
  incidents_by_type: Partial<Record<IncidentType, number>>
  incidents_unassigned: number
  incidents_escalated: number
  channels_by_state: Record<string, number>
  predictions_by_risk: Partial<Record<RiskLevel, number>>
}

export interface Incident {
  id: number
  type: IncidentType
  severity: RiskLevel
  status: IncidentStatus
  is_forecast: boolean
  node: number
  node_name: string
  responsible_node: number
  responsible_node_name: string
  title: string
  description: string
  probability: number | null
  horizon_hours: number | null
  opened_at: string
  ack_deadline: string | null
  acknowledged_at: string | null
  resolved_at: string | null
  assigned_to: number | null
  assigned_to_name: string | null
  escalation_level: number
  alerts_count: number
}

export interface Alert {
  id: number
  source: string
  type: IncidentType
  severity: RiskLevel
  channel: number | null
  channel_name: string | null
  raised_at: string
  title: string
  details: Record<string, unknown>
}

export interface Decision {
  id: number
  outcome: DecisionOutcome
  reason: number | null
  comment: string
  decided_by_name: string
  decided_at: string
}

export interface IncidentEvent {
  id: number
  ts: string
  kind: string
  actor_name: string | null
  text: string
}

export interface IncidentDetail extends Incident {
  alerts: Alert[]
  decisions: Decision[]
  events: IncidentEvent[]
}

export interface DecisionReason {
  id: number
  code: string
  name: string
  outcome: DecisionOutcome
}

export interface AppNotification {
  id: number
  title: string
  body: string
  level: RiskLevel
  link: string
  created_at: string
  read_at?: string | null
}
