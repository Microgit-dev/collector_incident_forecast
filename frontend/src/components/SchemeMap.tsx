import { Badge, Card, Group, Loader, Stack, Table, Text, Tooltip } from '@mantine/core'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'

import { CHANNEL_STATE, RISK, TASK, WO_STATUS } from '../api/labels'
import type { IncidentType, RiskLevel, WorkOrderStatus } from '../api/types'
import { RiskBadge } from './badges'
import { useScheme } from './useScheme'

type Coord = [number, number]

export interface SegmentProps {
  kind: 'segment'
  complex: number
  from: number
  to: number
  channels: number
  states: Record<string, number>
  silent: number
  health_min: number | null
  health_avg: number | null
  risk_level: RiskLevel
  risk_by_task: Record<string, number>
  top: {
    channel: number
    name: string
    picket: number
    task: string
    probability: number
    risk_level: RiskLevel
    state: string | null
  }[]
}

export interface RouteProps {
  kind: 'route'
  complex: number
  name: string
  row: number
  picket_from: number
  picket_to: number
  bin: number
  channels: number
  risk_level: RiskLevel
  criticality: number
}

interface ObjectProps {
  kind: 'object'
  complex: number
  node: number
  name: string
  node_kind: string
  channels: number
  coords?: Coord[]
}

interface IncidentProps {
  kind: 'incident'
  id: number
  title: string
  type: IncidentType
  severity: RiskLevel
  status: string
  is_forecast: boolean
  priority: number
  picket_from: number
  picket_to: number
}

export interface WorkOrderProps {
  kind: 'workorder'
  id: number
  number: string
  title: string
  status: WorkOrderStatus
  priority: RiskLevel
  work_type: string
  due_at: string
  overdue: boolean
  node: string
  assignee: string | null
  mine: boolean
}

type Feature<P> = { type: 'Feature'; geometry: { type: string; coordinates: Coord | Coord[] }; properties: P }
type AnyProps = SegmentProps | RouteProps | ObjectProps | IncidentProps | WorkOrderProps

export interface Scheme {
  type: 'FeatureCollection'
  properties: { rows: number }
  features: Feature<AnyProps>[]
}

export interface Layers {
  objects: boolean
  incidents: boolean
  states: boolean
  workorders: boolean
}

// Чем окрашен участок: риском прогноза (диспетчер, руководитель), качеством данных (аналитик)
// или текущим состоянием каналов (бригада — прогнозы ей не показываются)
export type ColorBy = 'risk' | 'health' | 'state'

const W = 1000
const H = 84
const LINE_Y = 30
const FILL: Record<RiskLevel, string> = {
  low: 'var(--mantine-color-gray-4)',
  medium: 'var(--mantine-color-yellow-5)',
  high: 'var(--mantine-color-orange-6)',
  critical: 'var(--mantine-color-red-7)',
}

function segmentFill(s: SegmentProps, colorBy: ColorBy): { fill: string; dim: boolean } {
  if (colorBy === 'health') {
    if (s.silent > 0 || (s.health_min !== null && s.health_min < 40)) return { fill: FILL.critical, dim: false }
    if (s.health_min !== null && s.health_min < 70) return { fill: FILL.high, dim: false }
    if (s.health_min !== null && s.health_min < 85) return { fill: FILL.medium, dim: false }
    return { fill: FILL.low, dim: true }
  }
  if (colorBy === 'state') {
    if (s.states.alarm) return { fill: FILL.critical, dim: false }
    if (s.states.fault || s.states.power_loss) return { fill: FILL.high, dim: false }
    if (s.states.unknown) return { fill: FILL.medium, dim: false }
    return { fill: FILL.low, dim: true }
  }
  return { fill: FILL[s.risk_level], dim: s.risk_level === 'low' }
}

const LEGEND: Record<ColorBy, { fill: string; label: string; dim?: boolean }[]> = {
  risk: (['low', 'medium', 'high', 'critical'] as RiskLevel[]).map((l) => ({
    fill: FILL[l],
    label: RISK[l].label,
    dim: l === 'low',
  })),
  health: [
    { fill: FILL.low, label: 'Data Health от 85', dim: true },
    { fill: FILL.medium, label: '70–84' },
    { fill: FILL.high, label: '40–69' },
    { fill: FILL.critical, label: 'ниже 40 или молчит' },
  ],
  state: [
    { fill: FILL.low, label: 'норма', dim: true },
    { fill: FILL.medium, label: 'не определено' },
    { fill: FILL.high, label: 'неисправность, обесточен' },
    { fill: FILL.critical, label: 'тревога' },
  ],
}

function ticks(from: number, to: number) {
  const span = to - from
  const step = [10, 20, 50, 100, 200, 500].find((s) => span / s <= 8) ?? 1000
  const out = []
  for (let v = Math.ceil(from / step) * step; v <= to; v += step) out.push(v)
  return out
}

function Row({
  route,
  segments,
  objects,
  incidents,
  workorders,
  layers,
  colorBy,
  selected,
  onSelect,
  labelWidth,
}: {
  route: RouteProps
  segments: SegmentProps[]
  objects: ObjectProps[]
  incidents: { props: IncidentProps; x: number }[]
  workorders: { props: WorkOrderProps; x: number }[]
  layers: Layers
  colorBy: ColorBy
  selected: SegmentProps | null
  onSelect: (s: SegmentProps) => void
  labelWidth: number
}) {
  const navigate = useNavigate()
  const span = Math.max(route.picket_to - route.picket_from, 1)
  const x = (pk: number) => ((pk - route.picket_from) / span) * W
  return (
    <Group wrap="nowrap" align="center" gap="sm">
      <Stack gap={0} w={labelWidth} style={{ flexShrink: 0 }}>
        <Text size="sm" fw={600} truncate>
          {route.name}
        </Text>
        <Group gap={4}>
          {colorBy === 'risk' && <RiskBadge level={route.risk_level} />}
          <Text size="xs" c="dimmed">
            {route.channels} кан.
          </Text>
        </Group>
      </Stack>
      {/* flex: 1 + minWidth: 0 — трасса занимает остаток строки, а не 100% рядом с подписью */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg viewBox={`-8 0 ${W + 16} ${H}`} style={{ width: '100%', height: H, overflow: 'visible', display: 'block' }}>
          <line x1={0} x2={W} y1={LINE_Y} y2={LINE_Y} stroke="var(--mantine-color-gray-5)" strokeWidth={2} />
          {segments.map((s) => {
            const a = x(s.from)
            const b = Math.min(x(s.to), W)
            const abnormal = Object.values(s.states).reduce((acc, n) => acc + n, 0)
            const isSelected = selected?.complex === s.complex && selected?.from === s.from
            const { fill, dim } = segmentFill(s, colorBy)
            return (
              <g key={s.from} style={{ cursor: 'pointer' }} onClick={() => onSelect(s)}>
                <title>
                  {`ПК ${s.from}–${s.to}: ${s.channels} кан.` +
                    (colorBy === 'risk' ? `, риск ${RISK[s.risk_level].label.toLowerCase()}` : '') +
                    (colorBy === 'health' && s.health_min !== null ? `, Data Health мин ${s.health_min}` : '') +
                    (abnormal ? `, не в норме ${abnormal}` : '') +
                    (s.silent ? `, молчат ${s.silent}` : '')}
                </title>
                <rect
                  x={a + 0.5}
                  y={LINE_Y - 7}
                  width={Math.max(b - a - 1, 1.5)}
                  height={14}
                  rx={2}
                  fill={fill}
                  opacity={dim ? 0.45 : 0.95}
                  stroke={isSelected ? 'var(--mantine-color-blue-7)' : 'none'}
                  strokeWidth={2}
                />
                {layers.states && abnormal > 0 && (
                  <circle
                    cx={(a + b) / 2}
                    cy={LINE_Y + 13}
                    r={Math.min(2 + Math.sqrt(abnormal), 6)}
                    fill="var(--mantine-color-grape-6)"
                  />
                )}
                {layers.states && s.silent > 0 && (
                  <circle
                    cx={(a + b) / 2 + 7}
                    cy={LINE_Y + 13}
                    r={3}
                    fill="none"
                    stroke="var(--mantine-color-dark-3)"
                    strokeWidth={1.5}
                  />
                )}
              </g>
            )
          })}
          {layers.objects &&
            objects.map((o, i) => {
              if (!o.coords) return null
              const a = x(o.coords[0][0])
              const b = x(o.coords[1][0])
              return (
                <g key={o.node}>
                  <title>{`${o.name}: ${o.channels} кан.`}</title>
                  <rect
                    x={a}
                    y={LINE_Y + 32 + (i % 2) * 6}
                    width={Math.max(b - a, 2)}
                    height={4}
                    rx={2}
                    fill={i % 2 ? 'var(--mantine-color-cyan-5)' : 'var(--mantine-color-indigo-4)'}
                    opacity={0.7}
                  />
                </g>
              )
            })}
          {layers.workorders &&
            workorders.map(({ props, x: pk }) => {
              const cx = x(pk)
              const cy = LINE_Y + 23
              return (
                <g key={`wo-${props.id}`} style={{ cursor: 'pointer' }} onClick={() => navigate('/workorders')}>
                  <title>
                    {`${props.number} ${props.title} · ${WO_STATUS[props.status].label.toLowerCase()} · срок ` +
                      dayjs(props.due_at).format('DD.MM HH:mm') +
                      (props.overdue ? ' (просрочена)' : '') +
                      (props.assignee ? ` · ${props.assignee}` : '')}
                  </title>
                  <path
                    d={`M ${cx} ${cy - 7} l 7 7 l -7 7 l -7 -7 z`}
                    fill={FILL[props.priority]}
                    stroke={
                      props.overdue
                        ? 'var(--mantine-color-red-8)'
                        : props.mine
                          ? 'var(--mantine-color-blue-7)'
                          : 'var(--mantine-color-dark-4)'
                    }
                    strokeWidth={props.mine || props.overdue ? 2.2 : 1}
                  />
                </g>
              )
            })}
          {layers.incidents &&
            incidents.map(({ props, x: pk }) => {
              const cx = x(pk)
              return (
                <g key={props.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/incidents/${props.id}`)}>
                  <title>{`#${props.id} ${props.title} (приоритет ${props.priority})`}</title>
                  <path
                    d={`M ${cx} ${LINE_Y - 9} l -7 -14 l 14 0 z`}
                    fill={FILL[props.severity]}
                    stroke={props.is_forecast ? 'var(--mantine-color-blue-7)' : 'var(--mantine-color-dark-6)'}
                    strokeDasharray={props.is_forecast ? '2 2' : undefined}
                    strokeWidth={1.2}
                  />
                </g>
              )
            })}
          {ticks(route.picket_from, route.picket_to).map((t) => (
            <text key={t} x={x(t)} y={H - 2} fontSize={9} textAnchor="middle" fill="var(--mantine-color-dimmed)">
              ПК{t}
            </text>
          ))}
        </svg>
      </div>
    </Group>
  )
}

export function SchemeLegend({ colorBy, layers }: { colorBy: ColorBy; layers: Layers }) {
  const marks = [
    layers.states && '● каналы не в норме · ○ молчат',
    layers.incidents && '▼ карточка (пунктир — прогноз)',
    layers.workorders && '◆ заявка (синяя рамка — моя, красная — просрочена)',
  ].filter(Boolean)
  return (
    <Group gap="md">
      {LEGEND[colorBy].map((item) => (
        <Group key={item.label} gap={4}>
          <div style={{ width: 14, height: 10, borderRadius: 2, background: item.fill, opacity: item.dim ? 0.45 : 1 }} />
          <Text size="xs">{item.label}</Text>
        </Group>
      ))}
      {marks.length > 0 && (
        <Text size="xs" c="dimmed">
          {marks.join(' · ')}
        </Text>
      )}
    </Group>
  )
}

export function SchemeMap({
  complex,
  task = 'all',
  layers,
  colorBy = 'risk',
  selected,
  onSelect,
  labelWidth = 200,
}: {
  complex?: string | null
  task?: string
  layers: Layers
  colorBy?: ColorBy
  selected: SegmentProps | null
  onSelect: (s: SegmentProps) => void
  labelWidth?: number
}) {
  const scheme = useScheme(complex, task, layers.workorders)
  if (scheme.isLoading) return <Loader />

  const features = scheme.data?.features ?? []
  const routes = features.filter((f) => f.properties.kind === 'route').map((f) => f.properties as RouteProps)
  const byComplex = (c: number, kind: AnyProps['kind']) =>
    features.filter((f) => f.properties.kind === kind && (f.properties as SegmentProps).complex === c)
  const points = <P,>(kind: 'incident' | 'workorder') => {
    const byRow = new Map<number, { props: P; x: number }[]>()
    for (const f of features) {
      if (f.properties.kind !== kind) continue
      const [xv, row] = f.geometry.coordinates as Coord
      byRow.set(row, [...(byRow.get(row) ?? []), { props: f.properties as P, x: xv }])
    }
    return byRow
  }
  const incidents = points<IncidentProps>('incident')
  const workorders = points<WorkOrderProps>('workorder')

  return (
    <Stack gap={4}>
      {routes.length === 0 && <Text c="dimmed">Нет каналов с пикетами в зоне ответственности.</Text>}
      {routes.map((r) => (
        <Row
          key={r.complex}
          route={r}
          segments={byComplex(r.complex, 'segment').map((f) => f.properties as SegmentProps)}
          objects={byComplex(r.complex, 'object').map((f) => ({
            ...(f.properties as ObjectProps),
            coords: f.geometry.coordinates as Coord[],
          }))}
          incidents={incidents.get(r.row) ?? []}
          workorders={workorders.get(r.row) ?? []}
          layers={layers}
          colorBy={colorBy}
          selected={selected}
          onSelect={onSelect}
          labelWidth={labelWidth}
        />
      ))}
      {routes.length > 0 && (
        <Text size="xs" c="dimmed" mt="xs">
          {routes.length === 1
            ? `Участок — ${routes[0].bin} пикетов.`
            : 'Ширина участка подбирается по длине трассы (около 60 участков на строку). Для подробной схемы выберите объект.'}
        </Text>
      )}
    </Stack>
  )
}

export function SegmentDetails({ segment, route }: { segment: SegmentProps; route?: RouteProps }) {
  const abnormal = Object.entries(segment.states)
  return (
    <Card withBorder radius="md">
      <Text fw={600}>
        {route?.name} · ПК {segment.from}–{segment.to}
      </Text>
      <Group gap="xs" my="xs">
        <RiskBadge level={segment.risk_level} />
        <Text size="sm">{segment.channels} каналов</Text>
        {segment.health_avg !== null && (
          <Tooltip label="Data Health: средний / минимальный балл каналов участка">
            <Badge variant="light" color={segment.health_min !== null && segment.health_min < 40 ? 'red' : 'teal'}>
              Data Health {segment.health_avg} / мин {segment.health_min}
            </Badge>
          </Tooltip>
        )}
        {segment.silent > 0 && <Badge color="dark">молчат {segment.silent}</Badge>}
      </Group>
      {abnormal.length > 0 && (
        <Group gap={6} mb="xs">
          {abnormal.map(([state, n]) => (
            <Badge key={state} variant="light" color={CHANNEL_STATE[state]?.color ?? 'gray'}>
              {CHANNEL_STATE[state]?.label ?? state}: {n}
            </Badge>
          ))}
        </Group>
      )}
      {Object.keys(segment.risk_by_task).length > 0 && (
        <Text size="xs" c="dimmed" mb={4}>
          Максимальный риск по задачам:{' '}
          {Object.entries(segment.risk_by_task)
            .map(([t, p]) => `${TASK[t] ?? t} ${Math.round(p * 100)}%`)
            .join(' · ')}
        </Text>
      )}
      {segment.top.length > 0 ? (
        <Table>
          <Table.Tbody>
            {segment.top.map((c) => (
              <Table.Tr key={`${c.channel}-${c.task}`}>
                <Table.Td>
                  <Text size="xs">{c.name}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{TASK[c.task] ?? c.task}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{Math.round(c.probability * 100)}%</Text>
                </Table.Td>
                <Table.Td>
                  <RiskBadge level={c.risk_level} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : (
        <Text size="xs" c="dimmed">
          Каналов с риском от среднего нет.
        </Text>
      )}
    </Card>
  )
}
