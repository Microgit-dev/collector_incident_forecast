import { BarChart, LineChart } from '@mantine/charts'
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Select, Stack, Table, Text, Title, Tooltip } from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { CHANNEL_STATE, INCIDENT_STATUS, INCIDENT_TYPE } from '../api/labels'
import type { ChannelHistory, HistoryCoverage, HistoryIncident, NodeHistory } from '../api/types'
import { RiskBadge } from '../components/badges'
import { TimeTracks } from '../components/TimeTracks'

interface NodeItem {
  id: number
  name: string
  depth: number
}

interface ChannelItem {
  id: number
  name: string
  sensor_type_name?: string
  node_name?: string
}

const PRESETS = [
  { label: 'Сутки', days: 1 },
  { label: 'Неделя', days: 7 },
  { label: 'Месяц', days: 30 },
  { label: 'Квартал', days: 91 },
  { label: 'Год', days: 365 },
]
const DAY_STATES = ['alarm', 'fault', 'power_loss', 'unknown']
const RESOLUTION = {
  raw: 'сырые показания',
  bucket: 'интервалы: минимум, среднее, максимум',
  daily: 'по суткам',
}

function bucketLabel(seconds: number | null) {
  if (!seconds) return ''
  return seconds >= 3600 ? `${seconds / 3600} ч` : `${seconds / 60} мин`
}

function IncidentsTable({ items, empty }: { items: HistoryIncident[]; empty: string }) {
  if (!items.length) {
    return (
      <Text size="sm" c="dimmed">
        {empty}
      </Text>
    )
  }
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Открыта</Table.Th>
            <Table.Th>Карточка</Table.Th>
            <Table.Th>Уровень</Table.Th>
            <Table.Th w={130}>Статус</Table.Th>
            <Table.Th>Решение того времени</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((i) => (
            <Table.Tr key={i.id}>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>{dayjs(i.opened_at).format('DD.MM.YYYY HH:mm')}</Table.Td>
              <Table.Td>
                <Anchor component={Link} to={`/incidents/${i.id}`} size="sm">
                  {i.title}
                </Anchor>
                <Text size="xs" c="dimmed">
                  {INCIDENT_TYPE[i.type]} · {i.node}
                  {i.is_emulated ? ' · эмуляция смены' : ''}
                  {i.is_forecast ? ' · прогноз' : ''}
                </Text>
              </Table.Td>
              <Table.Td>
                <RiskBadge level={i.severity} />
              </Table.Td>
              <Table.Td>
                <Badge variant="light" color={INCIDENT_STATUS[i.status].color}>
                  {INCIDENT_STATUS[i.status].label}
                </Badge>
              </Table.Td>
              <Table.Td>
                {i.decision ? (
                  <>
                    <Text size="sm">
                      {i.decision.outcome}
                      {i.decision.cause ? ` · ${i.decision.cause}` : ''}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {i.decision.by} · {dayjs(i.decision.at).format('DD.MM HH:mm')}
                    </Text>
                  </>
                ) : (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

function DailyCharts({ data, unit }: { data: ChannelHistory['daily']; unit: string }) {
  if (!data.length) {
    return (
      <Text size="sm" c="dimmed">
        В суточной витрине за период нет данных по каналу.
      </Text>
    )
  }
  const rows = data.map((d) => ({
    day: dayjs(d.day).format('DD.MM.YY'),
    alarms: d.alarms,
    faults: d.faults,
    power: d.power_losses,
    unknown: d.unknowns,
    invalid: d.invalid,
    avg: d.numeric_avg,
    min: d.numeric_min,
    max: d.numeric_max,
  }))
  const numeric = data.some((d) => d.numeric_avg !== null)
  return (
    <Stack>
      <div>
        <Text size="sm" fw={500} mb={4}>
          Нештатные сообщения по суткам
        </Text>
        <BarChart
          h={180}
          data={rows}
          dataKey="day"
          type="stacked"
          series={[
            { name: 'alarms', label: 'Тревоги', color: 'red.6' },
            { name: 'faults', label: 'Неисправности', color: 'orange.6' },
            { name: 'power', label: 'Нет питания', color: 'grape.6' },
            { name: 'unknown', label: 'Не определено', color: 'gray.5' },
            { name: 'invalid', label: 'Невалидные значения', color: 'pink.4' },
          ]}
          withLegend
        />
      </div>
      {numeric && (
        <div>
          <Text size="sm" fw={500} mb={4}>
            Показания по суткам{unit ? `, ${unit}` : ''}
          </Text>
          <LineChart
            h={180}
            data={rows}
            dataKey="day"
            series={[
              { name: 'max', label: 'Максимум', color: 'red.4' },
              { name: 'avg', label: 'Среднее', color: 'blue.6' },
              { name: 'min', label: 'Минимум', color: 'teal.4' },
            ]}
            withLegend
            connectNulls
            dotProps={{ r: rows.length < 3 ? 4 : 0 }}
          />
        </div>
      )}
    </Stack>
  )
}

function ChannelView({ channel, from, to }: { channel: string; from: string; to: string }) {
  const q = useQuery({
    queryKey: ['history-channel', channel, from, to],
    queryFn: () => api<ChannelHistory>('/history/channel/', { query: { channel, from, to } }),
  })
  if (q.isLoading) return <Loader />
  if (q.error) return <Alert color="red">{q.error.message}</Alert>
  const h = q.data!
  const invalidTotal = h.invalid_total ?? h.daily.reduce((acc, d) => acc + d.invalid, 0)
  return (
    <Stack>
      <Card withBorder radius="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <div>
            <Text fw={600}>{h.channel.name}</Text>
            <Text size="sm" c="dimmed">
              {h.channel.sensor_type} · {h.channel.node}
              {h.channel.picket !== null ? ` · ПК${h.channel.picket}` : ''} · канал {h.channel.external_id}
            </Text>
          </div>
          <Group gap={6}>
            <Badge variant="light">
              {RESOLUTION[h.resolution]}
              {h.bucket_s ? ` по ${bucketLabel(h.bucket_s)}` : ''}
            </Badge>
            <Badge variant="default">сообщений {h.readings.toLocaleString('ru-RU')}</Badge>
            {h.sources.map((s) => (
              <Badge key={s} variant="outline" color="gray">
                {s}
              </Badge>
            ))}
          </Group>
        </Group>
        {h.resolution !== 'daily' ? (
          <Stack mt="md" gap="xs">
            <TimeTracks
              from={h.period.from}
              to={h.period.to}
              numeric={h.numeric}
              unit={h.channel.unit}
              warn={h.channel.warn}
              alarm={h.channel.alarm}
              states={h.states}
              incidents={h.incidents}
              predictions={h.predictions}
              invalid={h.invalid}
            />
            <Group gap="md">
              {Object.entries(CHANNEL_STATE)
                .filter(([s]) => s !== 'event')
                .map(([s, v]) => (
                  <Group key={s} gap={4}>
                    <div style={{ width: 12, height: 10, borderRadius: 2, background: `var(--mantine-color-${v.color}-5)` }} />
                    <Text size="xs">{v.label}</Text>
                  </Group>
                ))}
              <Text size="xs" c="dimmed">
                ◆ карточка (полоса — пока открыта) · ● прогноз (размер — вероятность) · красные штрихи — невалидные значения
              </Text>
            </Group>
          </Stack>
        ) : (
          <Text size="sm" c="dimmed" mt="xs">
            Период длиннее {31} суток — показания по суточной витрине. Для сырых показаний выберите период до месяца.
          </Text>
        )}
        {invalidTotal > 0 && (
          <Text size="xs" c="dimmed" mt="xs">
            Невалидных значений за период: {invalidTotal.toLocaleString('ru-RU')} (служебные коды, артефакты даты, вне
            диапазона) — они не рисуются как показания.
          </Text>
        )}
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          По суткам
        </Text>
        <DailyCharts data={h.daily} unit={h.channel.unit} />
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Карточки по каналу и решения того времени
        </Text>
        <IncidentsTable items={h.incidents} empty="Карточек по этому каналу за период не было." />
        {h.node_incidents.length > 0 && (
          <>
            <Text fw={600} mt="md" mb="xs" size="sm">
              На объекте в то же время
            </Text>
            <IncidentsTable items={h.node_incidents} empty="" />
          </>
        )}
      </Card>
    </Stack>
  )
}

function NodeView({ node, from, to, onChannel }: { node: string; from: string; to: string; onChannel: (id: number) => void }) {
  const q = useQuery({
    queryKey: ['history-node', node, from, to],
    queryFn: () => api<NodeHistory>('/history/node/', { query: { node, from, to } }),
  })
  if (q.isLoading) return <Loader />
  if (q.error) return <Alert color="red">{q.error.message}</Alert>
  const h = q.data!
  const cell = Math.max(3, Math.min(18, Math.floor(900 / Math.max(h.days.length, 1))))
  const labelEvery = Math.ceil(h.days.length / 12)
  const totals = h.totals.map((t) => ({
    day: dayjs(t.day).format('DD.MM'),
    alarm: Number(t.alarm ?? 0),
    fault: Number(t.fault ?? 0),
    power_loss: Number(t.power_loss ?? 0),
    unknown: Number(t.unknown ?? 0),
  }))
  return (
    <Stack>
      <Card withBorder radius="md">
        <Group justify="space-between" wrap="wrap" mb="xs">
          <Text fw={600}>{h.node.name}: каналы по суткам</Text>
          <Group gap={6}>
            <Badge variant="default">каналов {h.node.channels}</Badge>
            <Badge variant="default">передавали {h.reporting}</Badge>
            {h.silent > 0 && (
              <Tooltip label="Ни одного сообщения за период: канал молчал или ещё не был установлен (справочник — текущий состав оборудования)">
                <Badge color="gray" variant="light">
                  без данных {h.silent}
                </Badge>
              </Tooltip>
            )}
          </Group>
        </Group>
        <Text size="xs" c="dimmed" mb="sm">
          Клетка — худшее состояние канала за сутки. Сначала каналы с наибольшим числом нештатных суток
          {h.shown < h.reporting ? ` (показаны ${h.shown} из ${h.reporting})` : ''}. Щелчок по строке — история канала.
        </Text>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th />
                {h.days.map((d, i) => (
                  <th key={d} style={{ width: cell, padding: 0, fontWeight: 400 }}>
                    {i % labelEvery === 0 && (
                      <Text size="xs" c="dimmed" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', lineHeight: 1 }}>
                        {dayjs(d).format('DD.MM')}
                      </Text>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {h.rows.map((r) => (
                <tr key={r.channel} style={{ cursor: 'pointer' }} onClick={() => onChannel(r.channel)}>
                  <td style={{ paddingRight: 8, whiteSpace: 'nowrap', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <Text size="xs" span title={`${r.sensor_type} · ${r.object}`}>
                      {r.name}
                    </Text>
                  </td>
                  {h.days.map((d) => {
                    const state = r.cells[d]
                    return (
                      <td key={d} style={{ padding: 1 }}>
                        <div
                          title={`${r.name} · ${dayjs(d).format('DD.MM.YYYY')}: ${state ? CHANNEL_STATE[state]?.label : 'нет сообщений'}`}
                          style={{
                            width: cell,
                            height: 12,
                            borderRadius: 2,
                            background: state ? `var(--mantine-color-${CHANNEL_STATE[state]?.color ?? 'gray'}-5)` : 'transparent',
                            opacity: state === 'normal' ? 0.35 : 1,
                            border: state ? 'none' : '1px dashed var(--mantine-color-default-border)',
                          }}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Сколько каналов объекта было не в норме
        </Text>
        <BarChart
          h={180}
          data={totals}
          dataKey="day"
          type="stacked"
          series={DAY_STATES.map((s) => ({
            name: s,
            label: CHANNEL_STATE[s].label,
            color: `${CHANNEL_STATE[s].color}.6`,
          }))}
          withLegend
        />
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Карточки на объекте за период ({h.incidents.length})
        </Text>
        <IncidentsTable items={h.incidents} empty="Карточек за период не было." />
      </Card>
    </Stack>
  )
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams()
  const node = params.get('node')
  const channel = params.get('channel')
  const coverage = useQuery({
    queryKey: ['history-coverage'],
    queryFn: () => api<HistoryCoverage>('/history/coverage/'),
    staleTime: 10 * 60_000,
  })
  const lastDay = coverage.data?.daily?.to ?? dayjs().format('YYYY-MM-DD')
  const from = params.get('from') ?? dayjs(lastDay).subtract(6, 'day').format('YYYY-MM-DD')
  const to = params.get('to') ?? lastDay
  const [range, setRange] = useState<[string | null, string | null]>([from, to])
  const [search, setSearch] = useState('')

  const nodes = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () => api<Page<NodeItem>>('/topology/nodes/', { query: { page_size: 500, is_active: true } }),
    staleTime: 10 * 60_000,
  })
  const channels = useQuery({
    queryKey: ['history-channels', node, search],
    queryFn: () =>
      api<Page<ChannelItem>>('/assets/channels/', {
        query: { within: node!, page_size: 200, ordering: 'name', ...(search ? { search } : {}) },
      }),
    enabled: Boolean(node),
  })

  const update = (next: Record<string, string | null>) => {
    const merged = { node, channel, from, to, ...next }
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v)) as Record<string, string>)
  }
  const applyRange = (a: string | null, b: string | null) => {
    setRange([a, b])
    if (a && b) update({ from: dayjs(a).format('YYYY-MM-DD'), to: dayjs(b).format('YYYY-MM-DD') })
  }
  const cov = coverage.data
  const years = cov?.archive_years ?? []

  return (
    <Stack>
      <Title order={3}>История</Title>
      <Text size="sm" c="dimmed">
        Показания и состояния за любой период: объект целиком (каналы по суткам) или один канал — график значений,
        смены состояний по аспектам, качество данных, карточки и решения того времени, прогнозы. До месяца —
        сырые показания, длиннее — суточная витрина.
      </Text>
      <Card withBorder radius="md">
        <Group align="flex-end" wrap="wrap">
          <Select
            label="Объект"
            placeholder="Выберите объект"
            data={(nodes.data?.results ?? []).map((n) => ({ value: String(n.id), label: `${'  '.repeat(Math.max(n.depth - 1, 0))}${n.name}` }))}
            value={node}
            onChange={(v) => update({ node: v, channel: null })}
            searchable
            w={280}
          />
          <Select
            label="Канал"
            placeholder={node ? 'Весь объект' : 'Сначала объект'}
            data={(channels.data?.results ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
            value={channel}
            onChange={(v) => update({ channel: v })}
            searchable
            clearable
            onSearchChange={setSearch}
            nothingFoundMessage="Нет каналов"
            disabled={!node}
            w={300}
          />
          <DatePickerInput
            type="range"
            label="Период"
            value={range}
            onChange={(v) => applyRange(...(v as [string | null, string | null]))}
            valueFormat="DD.MM.YYYY"
            w={250}
          />
          <Group gap={6}>
            {PRESETS.map((p) => (
              <Button
                key={p.label}
                size="compact-sm"
                variant="light"
                onClick={() => applyRange(dayjs(to).subtract(p.days - 1, 'day').format('YYYY-MM-DD'), to)}
              >
                {p.label}
              </Button>
            ))}
          </Group>
        </Group>
        {cov && (
          <Text size="xs" c="dimmed" mt="sm">
            Есть данные: архив журналов {years.length ? `${years[0]}–${years[years.length - 1]}` : 'не загружен'}
            {years.length && years.length < years[years.length - 1] - years[0] + 1
              ? ` (нет ${Array.from({ length: years[years.length - 1] - years[0] + 1 }, (_, i) => years[0] + i)
                  .filter((y) => !years.includes(y))
                  .join(', ')})`
              : ''}
            {cov.daily ? `, суточная витрина ${dayjs(cov.daily.from).format('DD.MM.YYYY')} — ${dayjs(cov.daily.to).format('DD.MM.YYYY')}` : ''}
            {cov.operational_from ? `, оперативный контур с ${dayjs(cov.operational_from).format('DD.MM.YYYY')}` : ''}.
          </Text>
        )}
      </Card>

      {channel ? (
        <ChannelView channel={channel} from={from} to={to} />
      ) : node ? (
        <NodeView node={node} from={from} to={to} onChannel={(id) => update({ channel: String(id) })} />
      ) : (
        <Text c="dimmed">Выберите объект — покажем его каналы по суткам; выберите канал — его показания и состояния.</Text>
      )}
    </Stack>
  )
}
