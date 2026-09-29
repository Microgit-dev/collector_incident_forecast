export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type IncidentStatus = 'new' | 'acknowledged' | 'in_progress' | 'resolved' | 'closed'
export type IncidentType =
  | 'sensor_failure'
  | 'fire'
  | 'gas'
  | 'flood'
  | 'intrusion'
  | 'temperature'
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
  /** административные операции, доступные пользователю (матрица accounts/operations.py) */
  operations: Operation[]
  /** админка открывается без второго входа */
  admin: boolean
}

export interface Operation {
  code: string
  title: string
  description: string
  page: string | null
  admin: string | null
  contour: 'combat' | 'training'
  scope: string
  responsible: boolean
}

export interface OperationsMatrix {
  roles: Record<string, string>
  matrix: (Omit<Operation, 'page' | 'admin' | 'responsible'> & { responsible: string[] })[]
  mine: Operation[]
}

export interface Contour {
  code: 'combat' | 'training'
  urls: { combat: string; training: string }
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
  /** маршрут нарушителя по сработкам охраны — только у карточек НСД */
  route: IntrusionRoute | null
}

export interface RouteStep {
  n: number
  channel: number
  name: string
  at: string
  until: string
  count: number
  position: LonLat | null
  placed: boolean
  picket: number | null
  floor: number | null
  floor_title: string | null
}

export interface IntrusionRoute {
  object: number
  object_name: string
  geometry: Polygon | null
  line: { type: 'LineString'; coordinates: LonLat[] } | null
  steps: RouteStep[]
  distance_m: number
  duration_s: number
  last: { name: string; at: string; floor_title: string | null }
  heading: string
  floors: Floor[]
  map: MapConfig
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
  // пожар и НСД: индекс правил, из которого получена вероятность
  index: number | null
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

export interface CalibrationBin {
  lo: number
  hi: number
  n: number
  k: number
  p: number
}

export interface CalibrationTest {
  train_period?: string
  n?: number
  k?: number
  brier?: number
  brier_base?: number
  brier_index?: number
  reliability?: { lo: number; hi: number; p: number; n: number; observed: number | null }[]
}

export interface IndicatorCalibration {
  id: number
  task: string
  horizon_hours: number
  period: string
  test_period: string
  calibration: { edges: number[]; base_rate: number; bins: CalibrationBin[]; n: number; k: number }
  test: CalibrationTest
  created_at: string
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
    // индикаторы пожара и НСД: индекс и калибровка индекса в вероятность по архиву
    index?: number
    calibrated?: boolean
    period?: string
    test_period?: string
    bin?: CalibrationBin
    bins?: CalibrationBin[]
    test?: CalibrationTest
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
    maintenance_due?: MaintenanceDue[]
    maintenance_recommendations?: MaintenanceRec[]
  }
  map: { color_by: 'risk' | 'health' | 'state'; incidents: boolean; workorders: boolean }
}

// План ТО (инженер ТО): регламент, рекомендации по состоянию, запланированные работы
export interface MaintenanceDue {
  id: number
  name: string
  kind: string
  kind_display: string
  inventory_number: string
  node: number
  node_name: string
  picket: number | null
  last_maintenance_at: string | null
  interval_days: number | null
  due: string | null
  overdue_days: number
  condition: string
  condition_display: string
  condition_at: string | null
  source: string
  work_type: string
  planned: { id: number; number: string; status: WorkOrderStatus; due_at: string } | null
}

export interface MaintenanceRec {
  id: number
  node_name: string
  equipment: number | null
  equipment_name: string | null
  channel_name: string | null
  work_type: string
  work_type_display: string
  priority: RiskLevel
  due_date: string
  rationale: string
}

export interface PlannedOrder {
  id: number
  number: string
  title: string
  status: WorkOrderStatus
  work_type: string
  priority: RiskLevel
  due_at: string
  node_name: string
  equipment_name: string | null
  assignee_name: string | null
}

export interface MaintenancePlan {
  today: string
  horizon_days: number
  kpis: Record<
    'overdue' | 'due_30' | 'unplanned_overdue' | 'recommendations' | 'bad_condition' | 'planned' | 'schedule_unplanned',
    number
  >
  due: MaintenanceDue[]
  bad_condition: MaintenanceDue[]
  recommendations: MaintenanceRec[]
  planned: PlannedOrder[]
  weeks: { week: string; orders: number }[]
  schedule_due: ScheduleDue[]
}

// Работа утверждённого графика ТО и ТР / ППР на ближайшие месяцы
export interface ScheduleDue {
  id: number
  schedule: string
  kind: 'to_tr' | 'ppr'
  object: string
  type_name: string
  quantity: number
  unit: string
  month: number
  work: string
  date: string | null
  planned: { id: number; number: string; status: WorkOrderStatus } | null
}

export interface MaintenanceNorm {
  id: number
  type_name: string
  system: string
  unit: string
  visits_per_year: number
  repairs_per_year: number
  ppr: boolean
  source: string
}

export interface ScheduleValidation {
  rows: number
  periodicity_match?: number
  repairs_match?: number
  batches_customer?: number
  batches_generated?: number
  load_customer: number[]
  load_generated: number[]
  cv_customer: number
  cv_generated: number
  max_customer?: number
  max_generated?: number
  last_acceptance_customer?: string | null
  last_acceptance_generated?: string | null
}

export interface MaintenanceScheduleItem {
  id: number
  kind: 'to_tr' | 'ppr'
  kind_display: string
  year: number
  title: string
  source: 'generated' | 'customer'
  source_display: string
  status: 'draft' | 'approved'
  status_display: string
  zone_name: string | null
  created_by_name: string | null
  approved_by_name: string | null
  file_name: string
  stats: {
    objects?: number
    lines?: number
    batches?: number
    sensors?: number
    load?: number[]
    repairs?: number[]
    validation?: ScheduleValidation
  }
  created_at: string
}

export interface ScheduleLineItem {
  id: number
  order: number
  node: number | null
  object_label: string
  type_name: string
  quantity: number
  unit: string
  months: Record<string, string>
  month: number | null
  batch: number | null
  dismantle_on: string | null
  delivery_on: string | null
  pickup_on: string | null
  acceptance_on: string | null
  note: string
}

export interface Equipment {
  id: number
  kind: string
  kind_display: string
  node: number
  node_name: string
  name: string
  inventory_number: string
  picket: string | null
  channels: number[]
  commissioned_at: string | null
  last_maintenance_at: string | null
  maintenance_interval_days: number | null
  next_maintenance_at: string | null
  mtbf_hours: number | null
  source: 'emulated' | 'imported' | 'manual'
  condition: string
  condition_display: string
  condition_at: string | null
  is_active: boolean
  synced_at: string | null
}

export interface Inspection {
  id: number
  equipment: number
  inspected_at: string
  inspector_name: string | null
  condition: string
  condition_display: string
  maintenance: boolean
  notes: string
  workorder: number | null
  workorder_number: string | null
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

// ---------- карта мониторинга и структура ----------

export type MonitoringMode = 'situation' | 'risk' | 'state' | 'health' | 'orders'
export type Polygon = { type: 'Polygon'; coordinates: number[][][] }
export type LonLat = [number, number]

export interface MonitoringZone {
  id: number
  name: string
  color: string
  geometry: Polygon | null
  mine: boolean
  home: boolean
  adjacent: boolean
  seconded: boolean
}

export interface MonitoringObject {
  id: number
  name: string
  zone: number | null
  zone_name: string | null
  mine: boolean
  geometry: Polygon | null
  center: LonLat | null
  placed: boolean
  busy?: boolean
  criticality?: number
  channels?: number
  abnormal?: number
  silent?: number
  health_low?: number
  risk_level?: RiskLevel | null
  incidents?: number
  incident_level?: RiskLevel | null
  escalated?: number
  new?: number
  orders?: number
  approvals?: number
  overdue?: number
}

export interface MonitoringMap {
  role: string
  modes: MonitoringMode[]
  mode: MonitoringMode
  scope: string
  global: boolean
  home_zone: number | null
  bbox: [number, number, number, number] | null
  zones: MonitoringZone[]
  objects: MonitoringObject[]
  incidents: { object: number; count: number; level: RiskLevel | null }[]
  orders: { object: number; count: number; approvals: number; overdue: number }[]
  summary: Record<string, number>
  map: MapConfig
}

/** Подложки карт: векторные светлая и тёмная, спутниковые растровые тайлы (пусто — без спутника). */
export interface MapConfig {
  light: string
  dark: string
  satellite?: string
  satellite_attribution?: string
}

/** Контрольная точка плана: пиксель плана ↔ точка на местности. */
export interface ControlPoint {
  px: number
  py: number
  lon: number
  lat: number
  on: boolean
}

/** Этаж объекта с планом помещений; corners — углы плана nw, ne, se, sw на местности. */
export interface Floor {
  id: number
  node: number
  level: number
  name: string
  title: string
  is_base: boolean
  plan: string | null
  width: number | null
  height: number | null
  points: ControlPoint[]
  corners: LonLat[] | null
  rmse_m: number | null
  opacity: number
  sensors: number
}

export interface MonitoringSensor {
  id: number
  external_id: number
  name: string
  type: string
  system: string
  part: string | null
  state: string
  silent: boolean
  health: number | null
  risk_level: RiskLevel | null
  position: LonLat | null
  placed: boolean
  floor: number | null
}

export interface MonitoringObjectDetail {
  id: number
  name: string
  zone: number | null
  zone_name: string | null
  geometry: Polygon | null
  center: LonLat | null
  mine: boolean
  note?: string
  criticality?: number
  parts?: { id: number; name: string; kind: string }[]
  sensors?: MonitoringSensor[]
  states?: Record<string, number>
  incidents?: {
    id: number
    title: string
    type: string
    severity: RiskLevel
    status: string
    status_display: string
    assigned_to: string | null
    escalation_level: number
    opened_at: string
  }[]
  orders?: {
    id: number
    number: string
    title: string
    status: WorkOrderStatus
    status_display: string
    priority: RiskLevel
    due_at: string
    overdue: boolean
    assignee: string | null
    mine: boolean
  }[]
  modes?: MonitoringMode[]
  floors?: Floor[]
  routes?: { incident: number; line: { type: 'LineString'; coordinates: LonLat[] }; steps: RouteStep[] }[]
}

export interface MonitoringOthers {
  count: number
  pages: number
  page: number
  results: { id: number; name: string; zone: number | null; zone_name: string; adjacent: boolean; center: LonLat | null }[]
}

export interface StructureZone {
  id: number
  name: string
  color: string
  geometry: Polygon | null
  center: LonLat | null
  adjacent: number[]
  objects: number
  staff: number
}

export interface StructureObject {
  id: number
  name: string
  zone: number | null
  criticality: number
  geometry: Polygon | null
  source: string
  center: LonLat | null
  channels: number
  floors: number
}

export interface StructurePerson {
  id: number
  name: string
  roles: string[]
  scope: number | null
  scope_name: string
  zone: number | null
  team: string | null
}

export interface StructureSecondment {
  id: number
  user: number
  user_name: string
  zone: number
  zone_name: string
  ends_at: string
  reason: string
  emergency: boolean
  by: string | null
}

export interface Structure {
  can: { zones: boolean; objects: boolean; add_objects: boolean; sensors: boolean; add_sensors: boolean; staff: boolean }
  district: { id: number; name: string }
  zones: StructureZone[]
  objects: StructureObject[]
  sensor_types: { id: number; name: string; system_type: string }[]
  staff: StructurePerson[]
  secondments: StructureSecondment[]
  overpass: boolean
  map: MapConfig
}

export interface DetectedBuilding {
  geometry: Polygon
  source: string
  name: string
  address: string
  levels: string | null
  area_m2: number
  center: LonLat
  exact: boolean
  /** выделение по снимку: оценка ИИ, варианты контура, почему взят запасной путь */
  score?: number | null
  candidates?: { geometry: Polygon; score: number | null }[]
  note?: string
}

export interface StructureSensor {
  id: number
  external_id: number
  name: string
  type: string
  node: number
  node_name: string
  picket: number | null
  location: LonLat | null
  floor: number | null
  manual: boolean
}
