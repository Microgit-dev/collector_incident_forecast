import { BarChart } from '@mantine/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconCheck, IconPlayerPlay } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, type Page } from '../api/client'
import { INCIDENT_TYPE } from '../api/labels'
import type { Hypothesis, IncidentType, RiskLevel } from '../api/types'
import { ContourBadge, RiskBadge } from '../components/badges'

interface Episode {
  node: string
  type: IncidentType
  contour: string
  severity: RiskLevel
  signals: number
  channels: number
  first: string
  last: string
  states: Record<string, number>
  hypotheses: Hypothesis[]
  actions: string[]
}

interface ForecastTop {
  channel: string
  probability: number
  level: RiskLevel | null
  factors: string[]
  happened: boolean
}

interface Replay {
  node: { id: number; name: string }
  period: { from: string; to: string }
  source: string
  channels: number
  readings: number
  signals_total: number
  bucket_minutes: number
  series: { t: string; physical: number; technical: number }[]
  episodes: Episode[]
  reduction: number | null
  decisions: {
    id: number
    title: string
    status: string
    decisions: { outcome: string; reason: string; by: string; at: string }[]
  }[]
  forecast?: Record<string, { model: string; channels: number; top: ForecastTop[] }>
}

interface NodeItem {
  id: number
  name: string
  depth: number
}

const TASK_TITLE: Record<string, string> = {
  sensor_failure: 'Отказ датчика',
  gas: 'Превышение 1 % метана',
  flood: 'Подтопление',
}

// Эпизоды из данных заказчика, на которых удобно показать работу системы
const PRESETS = [
  {
    label: 'Потеря связи, «Кси», 24.06.2026',
    node: 'объект Кси ПК0-ПК202',
    from: '2026-06-24T12:25',
    to: '2026-06-24T12:45',
  },
  {
    label: 'Пожарные тревоги, «Каппа ПС», 17.06.2024',
    node: 'объект Каппа ПС',
    from: '2024-06-17T00:00',
    to: '2024-06-17T23:59',
  },
  {
    label: 'Каскад, «Дзета ПС», 30.06.2026',
    node: 'объект Дзета ПС',
    from: '2026-06-30T16:20',
    to: '2026-06-30T17:20',
  },
]

const STATE_LABEL: Record<string, string> = {
  alarm: 'тревога',
  fault: 'неисправен',
  power_loss: 'обесточен',
  unknown: 'не определено',
}

function EpisodeCard({ episode }: { episode: Episode }) {
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb={4}>
        <Group gap="xs">
          <RiskBadge level={episode.severity} />
          <Text fw={600}>{INCIDENT_TYPE[episode.type] ?? episode.type}</Text>
          <ContourBadge contour={episode.contour} />
        </Group>
        <Text size="sm" c="dimmed">
          {dayjs(episode.first).format('DD.MM HH:mm:ss')} — {dayjs(episode.last).format('HH:mm:ss')}
        </Text>
      </Group>
      <Text size="sm">
        {episode.node}: {episode.signals} сигналов по {episode.channels} каналам (
        {Object.entries(episode.states)
          .map(([k, v]) => `${STATE_LABEL[k] ?? k} ${v}`)
          .join(', ')}
        ) → одна карточка
      </Text>
      <SimpleGrid cols={{ base: 1, md: 2 }} mt="xs">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Гипотезы
          </Text>
          {episode.hypotheses.map((h, i) => (
            <div key={h.code}>
              <Group justify="space-between" gap="xs" wrap="nowrap">
                <Text size="xs" fw={i === 0 ? 600 : 400}>
                  {h.title}
                </Text>
                <Text size="xs" c="dimmed">
                  {Math.round(h.weight * 100)} %
                </Text>
              </Group>
              <Progress value={h.weight * 100} size="xs" color={i === 0 ? 'blue' : 'gray'} />
            </div>
          ))}
        </Stack>
        <Stack gap={2}>
          <Text size="sm" fw={500}>
            Что предложила бы система
          </Text>
          {episode.actions.map((a, i) => (
            <Text key={a} size="xs">
              {i + 1}. {a}
            </Text>
          ))}
        </Stack>
      </SimpleGrid>
    </Card>
  )
}

export function ReplayPage() {
  const [node, setNode] = useState<string | null>(null)
  const [from, setFrom] = useState('2026-06-24T12:25')
  const [to, setTo] = useState('2026-06-24T12:45')
  const [params, setParams] = useState<{ node: string; from: string; to: string } | null>(null)

  const nodes = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () => api<Page<NodeItem>>('/topology/nodes/', { query: { page_size: 500, is_active: true } }),
    staleTime: 10 * 60_000,
  })
  const options = (nodes.data?.results ?? []).map((n) => ({
    value: String(n.id),
    label: `${'  '.repeat(Math.max(0, n.depth - 1))}${n.name}`,
  }))
  const replay = useQuery({
    queryKey: ['replay', params],
    queryFn: () =>
      api<Replay>('/analytics/replay/', {
        query: {
          node: params!.node,
          from: dayjs(params!.from).format('YYYY-MM-DDTHH:mm:ssZ'),
          to: dayjs(params!.to).format('YYYY-MM-DDTHH:mm:ssZ'),
        },
      }),
    enabled: params !== null,
    retry: false,
  })
  const preset = (p: (typeof PRESETS)[number]) => {
    const found = nodes.data?.results.find((n) => n.name === p.node)
    if (!found) return
    setNode(String(found.id))
    setFrom(p.from)
    setTo(p.to)
    setParams({ node: String(found.id), from: p.from, to: p.to })
  }
  const r = replay.data

  return (
    <Stack>
      <Title order={3}>Разбор эпизода</Title>
      <Text size="sm" c="dimmed">
        Сценарный анализ на исторических данных: как система отработала бы выбранный интервал на объекте — сырые
        сигналы, склейка в эпизоды, гипотезы, предложенные действия и что прогнозные модели говорили к началу интервала.
        Используются те же правила и модели, что в работе.
      </Text>
      <Card withBorder radius="md">
        <Group align="flex-end" wrap="wrap">
          <Select
            label="Объект"
            data={options}
            value={node}
            onChange={setNode}
            searchable
            w={320}
            placeholder={nodes.isLoading ? 'Загрузка…' : 'Выберите объект'}
          />
          <TextInput label="С" type="datetime-local" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
          <TextInput label="По" type="datetime-local" value={to} onChange={(e) => setTo(e.currentTarget.value)} />
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            disabled={!node}
            onClick={() => node && setParams({ node, from, to })}
          >
            Разобрать
          </Button>
        </Group>
        <Group gap="xs" mt="sm">
          <Text size="xs" c="dimmed">
            Примеры:
          </Text>
          {PRESETS.map((p) => (
            <Button key={p.label} size="compact-xs" variant="light" onClick={() => preset(p)}>
              {p.label}
            </Button>
          ))}
        </Group>
      </Card>

      {replay.isFetching && <Loader />}
      {replay.error && <Alert color="red">{(replay.error as Error).message}</Alert>}
      {r && !replay.isFetching && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }}>
            <Card withBorder radius="md">
              <Text size="sm" c="dimmed">
                Показаний за интервал
              </Text>
              <Text fz={26} fw={700}>
                {r.readings.toLocaleString('ru-RU')}
              </Text>
              <Text size="xs" c="dimmed">
                {r.channels} каналов · {r.source}
              </Text>
            </Card>
            <Card withBorder radius="md">
              <Text size="sm" c="dimmed">
                Сигналов (переходов в тревогу и сбой)
              </Text>
              <Text fz={26} fw={700}>
                {r.signals_total.toLocaleString('ru-RU')}
              </Text>
            </Card>
            <Card withBorder radius="md">
              <Text size="sm" c="dimmed">
                Карточек-эпизодов
              </Text>
              <Text fz={26} fw={700} c="teal">
                {r.episodes.length}
              </Text>
            </Card>
            <Card withBorder radius="md">
              <Text size="sm" c="dimmed">
                Сокращение нагрузки
              </Text>
              <Text fz={26} fw={700}>
                {r.reduction ? `×${r.reduction}` : '—'}
              </Text>
            </Card>
          </SimpleGrid>

          {r.series.length > 0 && (
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Поток сигналов (по {r.bucket_minutes} мин)
              </Text>
              <BarChart
                h={220}
                data={r.series.map((s) => ({ ...s, t: dayjs(s.t).format('DD.MM HH:mm') }))}
                dataKey="t"
                type="stacked"
                series={[
                  { name: 'technical', label: 'Технический контур', color: 'blue.6' },
                  { name: 'physical', label: 'Физический контур', color: 'red.6' },
                ]}
                withLegend
              />
            </Card>
          )}

          {r.forecast && Object.keys(r.forecast).length > 0 && (
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Прогноз на начало интервала ({dayjs(r.period.from).format('DD.MM.YYYY HH:mm')}) — и что сбылось
              </Text>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                {Object.entries(r.forecast)
                  .filter(([, v]) => v.top.length)
                  .map(([task, v]) => (
                    <Stack key={task} gap={4}>
                      <Text size="sm" fw={500}>
                        {TASK_TITLE[task] ?? task}{' '}
                        <Text span size="xs" c="dimmed">
                          · сбылось {v.top.filter((t) => t.happened).length} из {v.top.length} в топе
                        </Text>
                      </Text>
                      <Table>
                        <Table.Tbody>
                          {v.top.map((t) => (
                            <Table.Tr key={t.channel}>
                              <Table.Td>
                                <Text size="xs">{t.channel}</Text>
                              </Table.Td>
                              <Table.Td>
                                <Text size="xs">{Math.round(t.probability * 100)} %</Text>
                              </Table.Td>
                              <Table.Td>{t.level && <RiskBadge level={t.level} />}</Table.Td>
                              <Table.Td>
                                {t.happened ? (
                                  <Badge size="xs" color="red" leftSection={<IconCheck size={10} />}>
                                    сбылось
                                  </Badge>
                                ) : (
                                  <Text size="xs" c="dimmed">
                                    —
                                  </Text>
                                )}
                              </Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </Stack>
                  ))}
              </SimpleGrid>
            </Card>
          )}

          <Title order={4}>Эпизоды</Title>
          {r.episodes.length === 0 ? (
            <Text c="dimmed">В интервале не было переходов в тревогу или сбой.</Text>
          ) : (
            r.episodes.map((e, i) => <EpisodeCard key={i} episode={e} />)
          )}

          {r.decisions.length > 0 && (
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Решения диспетчеров в интервале
              </Text>
              {r.decisions.map((d) => (
                <Text key={d.id} size="sm">
                  #{d.id} {d.title}:{' '}
                  {d.decisions.map((x) => `${x.outcome}${x.reason ? ` (${x.reason})` : ''} — ${x.by}`).join('; ') ||
                    'решения нет'}
                </Text>
              ))}
            </Card>
          )}
        </>
      )}
    </Stack>
  )
}
