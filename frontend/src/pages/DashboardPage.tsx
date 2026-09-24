import { BarChart, DonutChart } from '@mantine/charts'
import { Alert, Button, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { CHANNEL_STATE, INCIDENT_TYPE, RISK } from '../api/labels'
import type { FloodStats, IncidentType, Live, NodeRisk, Overview, RiskLevel } from '../api/types'
import { RiskBadge } from '../components/badges'
import { PipelinePanel, RisksPanel } from '../components/LivePanels'

function Kpi({ label, value, hint, color, to }: { label: string; value: number; hint?: string; color?: string; to?: string }) {
  const body = (
    <Card withBorder padding="md" radius="md" h="100%">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={32} fw={700} c={value > 0 ? color : undefined} lh={1.2}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
  return to ? (
    <Link to={to} style={{ textDecoration: 'none', color: 'inherit' }}>
      {body}
    </Link>
  ) : (
    body
  )
}

const LEVELS: RiskLevel[] = ['critical', 'high', 'medium', 'low']

function FloodCard() {
  const { data } = useQuery({
    queryKey: ['flood'],
    queryFn: () => api<FloodStats>('/analytics/flood/', { query: { days: 30 } }),
    staleTime: 10 * 60_000,
  })
  if (!data?.signals || !data.period) return null
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Снижение нагрузки на диспетчера</Text>
        <Text size="xs" c="dimmed">
          {dayjs(data.period.from).format('DD.MM')} — {dayjs(data.period.to).format('DD.MM.YYYY')}
        </Text>
      </Group>
      <Group align="flex-end" gap="xl" wrap="wrap">
        <div>
          <Text size="xs" c="dimmed">
            Сигналов потока
          </Text>
          <Text fz={28} fw={700}>
            {data.signals.toLocaleString('ru-RU')}
          </Text>
          <Text size="xs" c="dimmed">
            ≈ {data.per_day?.signals.toLocaleString('ru-RU')} в сутки
          </Text>
        </div>
        <Text fz={28} c="dimmed">
          →
        </Text>
        <div>
          <Text size="xs" c="dimmed">
            Карточек-эпизодов
          </Text>
          <Text fz={28} fw={700} c="teal">
            {data.episodes.toLocaleString('ru-RU')}
          </Text>
          <Text size="xs" c="dimmed">
            ≈ {data.per_day?.episodes} в сутки
          </Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Сокращение
          </Text>
          <Text fz={28} fw={700}>
            ×{data.factor}
          </Text>
        </div>
      </Group>
      <Text size="xs" c="dimmed" mt="xs">
        Переходы каналов в тревогу, неисправность, обесточивание и «не определено» склеиваются в эпизоды по объекту и
        контуру риска, пока пауза между сигналами не больше 30 минут.
      </Text>
    </Card>
  )
}

function NodeRiskCard() {
  const { data } = useQuery({
    queryKey: ['node-risk'],
    queryFn: () => api<NodeRisk[]>('/forecasting/node-risk/'),
    refetchInterval: 60_000,
  })
  if (!data?.length) return null
  const top = [...data].sort((a, b) => b.expected_failures - a.expected_failures).slice(0, 8)
  const max = Math.max(...top.map((n) => n.expected_failures), 1)
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Риск отказа датчиков по объектам</Text>
        <Text size="xs" c="dimmed">
          прогноз на {dayjs(data[0].as_of).format('DD.MM.YYYY HH:mm')}
        </Text>
      </Group>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Объект</Table.Th>
            <Table.Th>Ожидаемых отказов за горизонт</Table.Th>
            <Table.Th>Каналов под риском</Table.Th>
            <Table.Th>Максимальный риск</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {top.map((n) => (
            <Table.Tr key={n.node}>
              <Table.Td>{n.node_name}</Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Progress value={(n.expected_failures / max) * 100} w={120} size="sm" />
                  <Text size="sm">{n.expected_failures.toFixed(1)}</Text>
                </Group>
              </Table.Td>
              <Table.Td>
                {n.channels_at_risk} из {n.channels_total}
              </Table.Td>
              <Table.Td>
                <RiskBadge level={n.risk_level} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  )
}

export function DashboardPage() {
  const { can } = useAuth()
  const [minutes, setMinutes] = useState('10')
  const live = useQuery({
    queryKey: ['live', minutes],
    queryFn: () => api<Live>('/analytics/live/', { query: { minutes } }),
    refetchInterval: 15_000,
  })
  const { data, isLoading } = useQuery({
    queryKey: ['overview'],
    queryFn: () => api<Overview>('/analytics/overview/'),
    refetchInterval: 30_000,
  })

  if (isLoading || !data) return <Loader />

  const severity = LEVELS.map((level) => ({
    name: RISK[level].label,
    value: data.incidents_by_severity[level] ?? 0,
    color: `${RISK[level].color}.6`,
  })).filter((s) => s.value > 0)

  const byType = (Object.entries(data.incidents_by_type) as [IncidentType, number][]).map(([type, count]) => ({
    type: INCIDENT_TYPE[type],
    count,
  }))

  const states = Object.entries(data.channels_by_state).map(([state, count]) => ({
    name: CHANNEL_STATE[state]?.label ?? state,
    value: count,
    color: `${CHANNEL_STATE[state]?.color ?? 'gray'}.6`,
  }))

  return (
    <Stack>
      <Title order={3}>Оперативная обстановка</Title>
      {Object.keys(data.channels_by_state).length === 0 && (
        <Alert color="blue" title="Данные ещё не загружены">
          <Group justify="space-between">
            <Text size="sm">Загрузите справочники и журналы СМВУ, чтобы увидеть состояние датчиков и прогнозы.</Text>
            {can('ingestion.add_importjob') && (
              <Button component={Link} to="/data-import" size="xs">
                Загрузить данные
              </Button>
            )}
          </Group>
        </Alert>
      )}
      {live.data && (
        <>
          <PipelinePanel data={live.data} minutes={minutes} onMinutes={setMinutes} />
          <RisksPanel data={live.data} />
        </>
      )}
      <Title order={4} mt="sm">
        Сводка
      </Title>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Kpi label="Открытые инциденты" value={data.incidents_open} color="red" to="/incidents" />
        <Kpi label="Не взяты в работу" value={data.incidents_unassigned} color="orange" hint="ожидают диспетчера" />
        <Kpi label="Эскалированы" value={data.incidents_escalated} color="grape" hint="нет реакции в срок" />
        <Kpi
          label="Прогнозы высокого риска"
          value={(data.predictions_by_risk.high ?? 0) + (data.predictions_by_risk.critical ?? 0)}
          color="orange"
          hint="на ближайшие 24 ч"
          to="/forecasts"
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Card withBorder radius="md">
          <Text fw={600} mb="sm">
            Инциденты по уровню
          </Text>
          {severity.length ? (
            <Group justify="center">
              <DonutChart data={severity} withLabels withLabelsLine={false} chartLabel={data.incidents_open} />
            </Group>
          ) : (
            <Text c="dimmed">Открытых инцидентов нет</Text>
          )}
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="sm">
            Инциденты по типу
          </Text>
          {byType.length ? (
            <BarChart h={220} data={byType} dataKey="type" orientation="vertical" yAxisProps={{ width: 150 }} series={[{ name: 'count', label: 'Инцидентов', color: 'blue.6' }]} />
          ) : (
            <Text c="dimmed">Нет данных</Text>
          )}
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="sm">
            Состояние датчиков
          </Text>
          {states.length ? (
            <Group justify="center">
              <DonutChart data={states} withLabels withLabelsLine={false} />
            </Group>
          ) : (
            <Text c="dimmed">Телеметрия ещё не поступала</Text>
          )}
        </Card>
      </SimpleGrid>
      <FloodCard />
      <NodeRiskCard />
    </Stack>
  )
}
