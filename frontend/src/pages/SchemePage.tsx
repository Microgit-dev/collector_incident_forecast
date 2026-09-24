import {
  Badge,
  Card,
  Grid,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { CHANNEL_STATE, RISK, TASK } from '../api/labels'
import type { IncidentType, RiskLevel } from '../api/types'
import { RiskBadge } from '../components/badges'

type Coord = [number, number]

interface SegmentProps {
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

interface RouteProps {
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

type Feature<P> = { type: 'Feature'; geometry: { type: string; coordinates: Coord | Coord[] }; properties: P }
type AnyProps = SegmentProps | RouteProps | ObjectProps | IncidentProps

interface Scheme {
  type: 'FeatureCollection'
  properties: { rows: number }
  features: Feature<AnyProps>[]
}

interface NodeItem {
  id: number
  name: string
  depth: number
}

const W = 1000
const H = 76
const LINE_Y = 30
const FILL: Record<RiskLevel, string> = {
  low: 'var(--mantine-color-gray-4)',
  medium: 'var(--mantine-color-yellow-5)',
  high: 'var(--mantine-color-orange-6)',
  critical: 'var(--mantine-color-red-7)',
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
  layers,
  selected,
  onSelect,
}: {
  route: RouteProps
  segments: SegmentProps[]
  objects: ObjectProps[]
  incidents: { props: IncidentProps; x: number }[]
  layers: { objects: boolean; incidents: boolean; states: boolean }
  selected: SegmentProps | null
  onSelect: (s: SegmentProps) => void
}) {
  const navigate = useNavigate()
  const span = Math.max(route.picket_to - route.picket_from, 1)
  const x = (pk: number) => ((pk - route.picket_from) / span) * W
  return (
    <Group wrap="nowrap" align="center" gap="sm">
      <Stack gap={0} w={200} style={{ flexShrink: 0 }}>
        <Text size="sm" fw={600} truncate>
          {route.name}
        </Text>
        <Group gap={4}>
          <RiskBadge level={route.risk_level} />
          <Text size="xs" c="dimmed">
            {route.channels} кан.
          </Text>
        </Group>
      </Stack>
      <svg viewBox={`-8 0 ${W + 16} ${H}`} style={{ width: '100%', height: H, overflow: 'visible' }}>
        <line x1={0} x2={W} y1={LINE_Y} y2={LINE_Y} stroke="var(--mantine-color-gray-5)" strokeWidth={2} />
        {segments.map((s) => {
          const a = x(s.from)
          const b = Math.min(x(s.to), W)
          const abnormal = Object.values(s.states).reduce((acc, n) => acc + n, 0)
          const isSelected = selected?.complex === s.complex && selected?.from === s.from
          return (
            <g key={s.from} style={{ cursor: 'pointer' }} onClick={() => onSelect(s)}>
              <title>
                {`ПК ${s.from}–${s.to}: ${s.channels} кан., риск ${RISK[s.risk_level].label.toLowerCase()}` +
                  (abnormal ? `, не в норме ${abnormal}` : '') +
                  (s.silent ? `, молчат ${s.silent}` : '')}
              </title>
              <rect
                x={a + 0.5}
                y={LINE_Y - 7}
                width={Math.max(b - a - 1, 1.5)}
                height={14}
                rx={2}
                fill={FILL[s.risk_level]}
                opacity={s.risk_level === 'low' ? 0.45 : 0.95}
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
                  y={LINE_Y + 20 + (i % 2) * 6}
                  width={Math.max(b - a, 2)}
                  height={4}
                  rx={2}
                  fill={i % 2 ? 'var(--mantine-color-cyan-5)' : 'var(--mantine-color-indigo-4)'}
                  opacity={0.7}
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
    </Group>
  )
}

function SegmentDetails({ segment, route }: { segment: SegmentProps; route?: RouteProps }) {
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

export function SchemePage() {
  const [params, setParams] = useSearchParams()
  const node = params.get('node')
  const [task, setTask] = useState('all')
  const [layers, setLayers] = useState({ objects: true, incidents: true, states: true })
  const [selected, setSelected] = useState<SegmentProps | null>(null)

  const nodes = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () => api<Page<NodeItem>>('/topology/nodes/', { query: { page_size: 500, is_active: true } }),
    staleTime: 10 * 60_000,
  })
  const scheme = useQuery({
    queryKey: ['scheme', node, task],
    queryFn: () =>
      api<Scheme>('/analytics/scheme/', {
        query: { ...(node ? { complex: node } : {}), ...(task !== 'all' ? { task } : {}) },
      }),
    refetchInterval: 60_000,
  })

  const options = (nodes.data?.results ?? [])
    .filter((n) => n.depth >= 2)
    .map((n) => ({ value: String(n.id), label: `${n.depth > 2 ? '   ' : ''}${n.name}` }))

  const features = scheme.data?.features ?? []
  const routes = features.filter((f) => f.properties.kind === 'route').map((f) => f.properties as RouteProps)
  const byComplex = (complex: number, kind: AnyProps['kind']) =>
    features.filter((f) => f.properties.kind === kind && (f.properties as SegmentProps).complex === complex)
  const incidentsByRow = new Map<number, { props: IncidentProps; x: number }[]>()
  for (const f of features) {
    if (f.properties.kind !== 'incident') continue
    const [xv, row] = f.geometry.coordinates as Coord
    incidentsByRow.set(row, [...(incidentsByRow.get(row) ?? []), { props: f.properties as IncidentProps, x: xv }])
  }
  const selectedRoute = selected ? routes.find((r) => r.complex === selected.complex) : undefined
  const openIncidents = [...incidentsByRow.values()].flat().length

  return (
    <Stack>
      <Title order={3}>Схема объектов</Title>
      <Text size="sm" c="dimmed">
        Линейная схема по пикетам: координат у заказчика нет, трасса каждого объекта строится по пикетам его каналов.
        Цвет участка — максимальный риск по каналам, точки — каналы не в норме и молчащие, треугольники — открытые
        карточки (пунктир — прогнозные). Щелчок по участку — подробности, по карточке — переход к ней.
      </Text>
      <Card withBorder radius="md">
        <Group wrap="wrap" align="flex-end">
          <Select
            label="Объект"
            placeholder="Все объекты"
            data={options}
            value={node}
            onChange={(v) => {
              setSelected(null)
              setParams(v ? { node: v } : {})
            }}
            searchable
            clearable
            w={300}
          />
          <SegmentedControl
            value={task}
            onChange={(v) => {
              setTask(v)
              setSelected(null)
            }}
            data={[
              { value: 'all', label: 'Все риски' },
              { value: 'sensor_failure', label: 'Отказ датчика' },
              { value: 'gas', label: 'Газ' },
              { value: 'flood', label: 'Подтопление' },
            ]}
          />
          <Switch
            label="Объекты и шкафы"
            checked={layers.objects}
            onChange={(e) => setLayers({ ...layers, objects: e.currentTarget.checked })}
          />
          <Switch
            label="Карточки"
            checked={layers.incidents}
            onChange={(e) => setLayers({ ...layers, incidents: e.currentTarget.checked })}
          />
          <Switch
            label="Состояния каналов"
            checked={layers.states}
            onChange={(e) => setLayers({ ...layers, states: e.currentTarget.checked })}
          />
        </Group>
        <Group gap="md" mt="sm">
          {(['low', 'medium', 'high', 'critical'] as RiskLevel[]).map((l) => (
            <Group key={l} gap={4}>
              <div
                style={{ width: 14, height: 10, borderRadius: 2, background: FILL[l], opacity: l === 'low' ? 0.45 : 1 }}
              />
              <Text size="xs">{RISK[l].label}</Text>
            </Group>
          ))}
          <Text size="xs" c="dimmed">
            ● каналы не в норме · ○ молчат · ▼ карточка
          </Text>
          <Text size="xs" c="dimmed">
            Открытых карточек на схеме: {openIncidents}
          </Text>
        </Group>
      </Card>

      {scheme.isLoading ? (
        <Loader />
      ) : (
        <Grid>
          <Grid.Col span={{ base: 12, lg: selected ? 8 : 12 }}>
            <Card withBorder radius="md">
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
                    incidents={incidentsByRow.get(r.row) ?? []}
                    layers={layers}
                    selected={selected}
                    onSelect={setSelected}
                  />
                ))}
              </Stack>
              {routes.length > 0 && (
                <Text size="xs" c="dimmed" mt="xs">
                  {routes.length === 1
                    ? `Участок — ${routes[0].bin} пикетов.`
                    : 'Ширина участка подбирается по длине трассы (около 60 участков на строку). Для подробной схемы выберите объект.'}
                </Text>
              )}
            </Card>
          </Grid.Col>
          {selected && (
            <Grid.Col span={{ base: 12, lg: 4 }}>
              <SegmentDetails segment={selected} route={selectedRoute} />
            </Grid.Col>
          )}
        </Grid>
      )}
    </Stack>
  )
}
