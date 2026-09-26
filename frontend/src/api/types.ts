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
  first_seen_by: number | null
  first_seen_by_name: string | null
  first_seen_at: string | null
  responder: number | null
  responder_name: string | null
  responded_at: string | null
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
  kind_display?: string
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

export interface TrainingStep {
  code: string
  title: string
  hint: string
  route: string | null
  target: string | null
  manual: boolean
  status: 'done' | 'current' | 'pending'
  done_at: string | null
}

export interface TrainingSession {
  id: number
  lesson: string
  title: string
  summary: string
  role: string
  status: 'active' | 'done' | 'abandoned'
  object: string | null
  started_at: string
  finished_at: string | null
  elapsed_s: number
  hints: number
  mistakes: number
  note: string | null
  steps: TrainingStep[]
  user?: string
}

export interface TrainingLesson {
  code: string
  title: string
  summary: string
  minutes: number
  steps: number
  polygon: boolean
  available: boolean
  best: { finished_at: string; elapsed_s: number; mistakes: number } | null
}

export interface HistoryPoint {
  t: string
  v: number
  min?: number
  max?: number
}

export interface HistoryInterval {
  from: string
  to: string
  state: string
  raw: string
}

export interface HistoryIncident {
  id: number
  title: string
  type: IncidentType
  severity: RiskLevel
  status: IncidentStatus
  is_forecast: boolean
  is_emulated: boolean
  opened_at: string
  resolved_at: string | null
  node: string
  assigned_to: string | null
  decision: { outcome: string; cause: string | null; by: string | null; at: string } | null
}

export interface HistoryPrediction {
  t: string
  task: string
  p: number
  level: RiskLevel
  outcome: string
}

export interface HistoryDaily {
  day: string
  readings: number
  normal: number
  warnings: number
  alarms: number
  faults: number
  power_losses: number
  unknowns: number
  events: number
  invalid: number
  numeric_avg: number | null
  numeric_min: number | null
  numeric_max: number | null
  last_state: string
}

export interface ChannelHistory {
  channel: {
    id: number
    external_id: number
    name: string
    node: string
    node_id: number
    sensor_type: string
    picket: number | null
    unit: string
    warn: number | null
    alarm: number | null
  }
  period: { from: string; to: string }
  resolution: 'raw' | 'bucket' | 'daily'
  bucket_s: number | null
  sources: string[]
  readings: number
  numeric: HistoryPoint[]
  states: Record<string, HistoryInterval[]>
  invalid: { t: string; quality: string; raw: string }[]
  invalid_total?: number
  daily: HistoryDaily[]
  incidents: HistoryIncident[]
  node_incidents: HistoryIncident[]
  predictions: HistoryPrediction[]
}

export interface NodeHistory {
  node: { id: number; name: string; channels: number }
  period: { from: string; to: string }
  days: string[]
  totals: ({ day: string } & Record<string, number | string>)[]
  rows: {
    channel: number
    name: string
    sensor_type: string
    object: string
    abnormal_days: number
    cells: Record<string, string>
  }[]
  shown: number
  reporting: number
  silent: number
  incidents: HistoryIncident[]
}

export interface HistoryCoverage {
  archive_years: number[]
  daily: { from: string; to: string } | null
  operational_from: string | null
  max_raw_days: number
}

export interface StaffPerson {
  user: number
  name: string
  position: string
  team: string | null
  zone: string
  active: boolean
  rank: number | null
  zone_cards: number
  first_seen: number
  responded: number
  responded_share: number | null
  view_median: number | null
  response_median: number | null
  decision_median: number | null
  races: number
  races_won: number
  races_won_share: number | null
  decisions: number
  closed: number
  repeated: number
  quality: number | null
  labels_accepted: number
  labels_rejected: number
  takeovers_lost: number
  releases: number
  shifts: number
  per_shift: number | null
  training_done: number
  training_mistakes: number | null
}

export interface StaffTeam {
  team: string
  members: number
  zone_cards: number
  responded: number
  responded_share: number | null
  response_median: number | null
  escalated_unanswered: number
  quality: number | null
  training_done: number
}

export interface StaffMetrics {
  period: { from: string; to: string }
  summary: {
    cards: number
    responded_share: number | null
    response: { median: number | null; p90: number | null }
    contested: number
    contested_share: number | null
    escalated_unanswered: number
    takeovers: number
    emulated: number
  }
  people: StaffPerson[]
  teams: StaffTeam[]
}

export interface MyMetrics {
  period: { from: string; to: string }
  me: StaffPerson | null
  rank_of: number
  colleagues: {
    count: number
    responded: number | null
    response_median: number | null
    responded_share: number | null
    quality: number | null
  }
}

// ---------- учения ----------

export type ExerciseStatus = 'scheduled' | 'running' | 'finished' | 'stopped' | 'cancelled'

export interface ExerciseCheck {
  code: string
  title: string
  ok: boolean | null
  detail: string
}

export interface ExerciseEvent {
  t: number | null
  kind: string
  text: string
  who: string | null
  incident?: number
}

export interface ExercisePerson {
  user: number
  name: string
  role: string
  silent: boolean
  confirmed: boolean
  first_view: number | null
  responded: number
  first_response: number | null
  decisions: number
  actions: number
  workorders: number
  verdict: string
}

export interface ExerciseReport {
  scenario: string
  complication: string | null
  duration_s: number | null
  incidents: {
    id: number
    type: string
    type_display: string
    title: string
    status: string
    opened: number | null
    responder: string | null
    responded: number | null
    escalation_level: number
  }[]
  checks: ExerciseCheck[]
  score: { passed: number; total: number }
  people: ExercisePerson[]
  timeline: ExerciseEvent[]
}

export interface Exercise {
  id: number
  title: string
  status: ExerciseStatus
  status_display: string
  object: string
  node: number
  scenario: string | null
  scenario_display: string | null
  complication: string | null
  complication_display: string | null
  complication_after_min: number | null
  speed: number | null
  duration_min: number
  briefing: string
  scheduled_at: string | null
  started_at: string | null
  finished_at: string | null
  ends_at: string | null
  created_by: string
  stopped_by: string | null
  stop_reason: string
  manager: boolean
  me: { silent: boolean; confirmed_at: string | null } | null
  participants: { user: number; name: string; role: string; silent: boolean; confirmed_at: string | null }[]
  report?: ExerciseReport
}

export interface ExerciseCandidate {
  id: number
  name: string
  username: string
  roles: string[]
  team: string | null
  zone: string
  sees: boolean
}

export interface ExerciseOptions {
  scenarios: { code: string; title: string; description: string }[]
  complications: { code: string; title: string }[]
  objects: { id: number; name: string }[]
  node: number | null
  candidates: ExerciseCandidate[]
}

// ---------- вики ----------

export interface WikiBrief {
  slug: string
  title: string
  summary: string
  roles: string[]
  is_published: boolean
}

export interface WikiIndex {
  sections: { slug: string; title: string; pages: WikiBrief[] }[]
  can_edit: boolean
}

export interface WikiArticle extends WikiBrief {
  id: number
  section: string
  body: string
  updated_at: string
  updated_by: string | null
}
