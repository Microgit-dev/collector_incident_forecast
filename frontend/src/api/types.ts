export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type IncidentStatus = 'new' | 'acknowledged' | 'in_progress' | 'resolved' | 'closed'
export type IncidentType =
  | 'sensor_failure'
  | 'fire'
  | 'gas'
  | 'flood'
  | 'intrusion'
  | 'power'
  | 'equipment'
  | 'communication'
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
  team: TeamRef | null
  command_chain: TeamRef[]
  roles: string[]
  permissions: string[]
  is_superuser: boolean
  contour: Contour
}

export interface Contour {
  code: 'combat' | 'training'
  urls: { combat: string; training: string; simulator: string }
}

export type TeamKind = 'management' | 'ods' | 'unit' | 'brigade' | 'analytics' | 'support'

export interface TeamRef {
  id: number
  code: string
  name: string
  kind: TeamKind
}

export interface TeamMember {
  id: number
  username: string
  last_name: string
  first_name: string
  position: string
  phone: string
  roles: { code: string; title: string }[]
}

export interface Team extends TeamRef {
  kind_display: string
  scope_node: number | null
  scope_node_name: string | null
  parent: number | null
  lead: number | null
  members: TeamMember[]
}

export interface Viewer {
  user: number
  username: string
  name: string
  position: string
  first_viewed_at: string
  last_viewed_at: string
  times: number
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
  is_emulated: boolean
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
  contour: 'physical' | 'technical'
  signals_count: number
  channels_count: number
  first_signal_at: string | null
  last_signal_at: string | null
  priority: number
  data_confidence: number | null
}

export interface Hypothesis {
  code: string
  title: string
  weight: number
  evidence: string[]
}

export interface ActionStep {
  code: string
  title: string
  done: boolean
  done_by: string | null
  done_at: string | null
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

export type DecisionCause =
  | 'sensor_fault'
  | 'communication'
  | 'power'
  | 'false_alarm'
  | 'external'
  | 'works'
  | 'real_event'
  | 'insufficient_data'

export interface Decision {
  id: number
  outcome: DecisionOutcome
  reason: number | null
  comment: string
  cause: DecisionCause | ''
  forecast_useful: boolean | null
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
  viewed_by: Viewer[]
  hypotheses: Hypothesis[]
  actions: ActionStep[]
  priority_factors: Record<string, number>
}

export interface FloodStats {
  period?: { from: string; to: string; days: number }
  signals: number
  episodes: number
  factor: number | null
  per_day?: { signals: number; episodes: number }
  by_contour?: Record<string, { signals: number; episodes: number; largest_episode: number }>
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

export interface Factor {
  feature: string
  title: string
  value: number | string | null
  contribution: number
}

export type PredictionOutcome = 'pending' | 'confirmed' | 'not_confirmed' | 'prevented'

export interface Prediction {
  id: number
  task: string
  model: number | null
  node: number
  node_name: string
  channel: number | null
  channel_name: string | null
  issued_at: string
  horizon_hours: number
  valid_until: string
  probability: number
  risk_level: RiskLevel
  factors: Factor[]
  summary: string
  outcome: PredictionOutcome
  outcome_at: string | null
  is_backtest: boolean
}

export interface Metrics {
  precision: number
  recall: number
  f1: number
  pr_auc: number
  roc_auc: number
  base_rate: number
  alerts_per_day: number | null
  onsets: number
  lead_time_hours?: { median: number; p25: number; p75: number }
}

export interface MLModel {
  id: number
  task: string
  version: string
  algorithm: string
  horizon_hours: number
  status: 'training' | 'ready' | 'active' | 'archived' | 'failed'
  features: string[]
  metrics: {
    levels?: Record<'medium' | 'high' | 'critical', number>
    levels_test?: Record<'medium' | 'high' | 'critical', Metrics>
    valid?: Metrics
    test?: Metrics
    baseline_test?: { rule: string; precision: number; recall: number }
    by_sensor_type_test?: Record<string, { precision: number; recall: number; onsets: number }>
    feature_importance?: Record<string, number>
    rows?: Record<string, number>
    train_seconds?: number
  }
  train_period: Record<string, string[] | string>
  notes: string
  created_at: string
}

export interface TrainingRun {
  id: number
  task: string
  status: 'pending' | 'running' | 'done' | 'failed'
  params: Record<string, unknown>
  result_model: number | null
  log: string
  progress: number
  stage: string
  started_by_name: string | null
  created_at: string
  finished_at: string | null
}

export interface ChannelHealth {
  channel: number
  channel_name: string
  node: number
  node_name: string
  sensor_type: string | null
  computed_at: string
  score: number
  components: Record<'completeness' | 'freshness' | 'technical' | 'stability' | 'consistency', number | null>
  periodic: boolean
  expected_interval_s: number | null
  last_seen_at: string | null
  silent: boolean
  silent_since: string | null
}

export interface HealthSummary {
  total: number
  good: number
  degraded: number
  poor: number
  silent: number
  periodic: number
  average: number | null
  computed_at: string | null
}

export interface NodeRisk {
  node: number
  node_name: string
  task: string
  as_of: string
  max_probability: number
  expected_failures: number
  channels_total: number
  channels_at_risk: number
  risk_level: RiskLevel
}

export interface ChannelRisk {
  id: number
  channel: number
  channel_name: string
  node: number
  node_name: string
  sensor_type: string | null
  picket: string | null
  as_of: string
  probability: number
  risk_level: RiskLevel
  factors: Factor[]
}

export interface LiveIncident {
  id: number
  title: string
  type: IncidentType
  severity: RiskLevel
  status: IncidentStatus
  priority: number
  contour: string
  is_forecast: boolean
  node_name: string
  signals_count: number
  channels_count: number
  last_signal_at: string | null
  ack_deadline: string | null
  overdue: boolean
  assigned_to_name: string | null
  escalation_level: number
}

export interface TaskRisk {
  as_of: string | null
  levels: Record<'critical' | 'high' | 'medium', number>
  top: {
    channel?: number
    channel_name?: string
    prediction?: number | null
    node_name: string
    probability: number
    risk_level: RiskLevel
    factor: string
  }[]
}

export interface Live {
  now: string
  minutes: number
  data_clock: string | null
  last_signal_at: string | null
  signals: {
    total: number
    by_contour: Record<string, number>
    by_type: Record<string, number>
    bucket_minutes: number
    series: { t: string; physical: number; technical: number }[]
  }
  episodes: { touched: number; new: number; items: LiveIncident[] }
  action: { open: number; unassigned: number; overdue: number; escalated: number; items: LiveIncident[] }
  risks: {
    tasks: Record<string, TaskRisk>
    nodes: {
      node: number
      node_name: string
      task: string
      risk_level: RiskLevel
      max_probability: number
      channels_at_risk: number
    }[]
  }
}

export interface PredictionCard extends Prediction {
  viewed_by: Viewer[]
  model_info: {
    method: 'model' | 'rules'
    note?: string
    version?: string
    algorithm?: string
    status?: string
    roc_auc?: number
    pr_auc?: number
    base_rate?: number
    level_test?: { precision?: number; recall?: number; alerts_per_day?: number; lead_time_median_h?: number }
    baseline?: { rule: string; precision: number; recall: number }
  }
  realized: Record<'live' | 'backtest', { confirmed: number; resolved: number; precision: number | null }>
  channel_info: {
    id: number
    name: string
    sensor_type: string | null
    picket: number | null
    location_hint: string
    state: { state: string; since: string; last_seen_at: string } | null
    health: {
      score: number
      components: Record<string, number | null>
      silent: boolean
      silent_since: string | null
      last_seen_at: string | null
      periodic: boolean
    } | null
    daily: {
      day: string
      readings: number
      alarms: number
      faults: number
      power_losses: number
      unknowns: number
      numeric_max: number | null
      last_state: string
    }[]
    risks: { task: string; probability: number; risk_level: RiskLevel; as_of: string }[]
  } | null
  history: { id: number; issued_at: string; probability: number; risk_level: RiskLevel; outcome: PredictionOutcome }[]
  incidents: {
    id: number
    title: string
    type: IncidentType
    severity: RiskLevel
    status: IncidentStatus
    is_forecast: boolean
    opened_at: string
    hypothesis: string | null
    decision: string | null
  }[]
  recommendations: {
    id: number
    work_type: string
    priority: RiskLevel
    due_date: string
    status: string
    rationale: string
    work_order: { id: number; number: string; status: string } | null
  }[]
  actions: { code: string; title: string }[]
}

export type WorkOrderStatus = 'draft' | 'approved' | 'submitted' | 'in_progress' | 'done' | 'cancelled'

export interface WorkspaceKpi {
  key: string
  label: string
  value: number
  hint: string
  color: string | null
  to: string | null
}

export interface WorkspaceIncident {
  id: number
  title: string
  type: IncidentType
  severity: RiskLevel
  status: IncidentStatus
  priority: number
  escalation_level: number
  opened_at: string
  node: string
}

export interface WorkspaceOrder {
  id: number
  number: string
  title: string
  status: WorkOrderStatus
  priority: RiskLevel
  work_type: string
  due_at: string
  overdue: boolean
  node: string
  created_by: string | null
  external_status: string
}

export interface Workspace {
  role: string
  title: string
  description: string
  roles: { code: string; title: string }[]
  kpis: WorkspaceKpi[]
  lists: {
    escalated?: WorkspaceIncident[]
    approvals?: WorkspaceOrder[]
    my_orders?: WorkspaceOrder[]
    weak_channels?: {
      channel: number
      name: string
      node: string
      score: number
      silent: boolean
      last_seen_at: string | null
    }[]
  }
  map: { color_by: 'risk' | 'health' | 'state'; incidents: boolean; workorders: boolean }
}
