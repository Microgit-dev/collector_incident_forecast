import {
  Badge,
  Card,
  Group,
  Loader,
  Pagination,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { isIndicator, PREDICTION_OUTCOME } from '../api/labels'
import type { ChannelRisk, Prediction, PredictionOutcome } from '../api/types'
import { RiskBadge } from '../components/badges'

const PAGE = 25
const TASK_LABEL: Record<string, string> = {
  sensor_failure: 'Отказ датчика',
  gas: 'Газ',
  flood: 'Подтопление',
  fire: 'Пожар (индикатор)',
  intrusion: 'НСД (индикатор)',
}
const pct = (p: number) => `${Math.round(p * 100)} %`

interface JournalSummary {
  by_outcome: Partial<Record<PredictionOutcome, number>>
  total: number
  precision: number | null
}

function Factors({ factors }: { factors: { title: string; contribution: number }[] }) {
  if (!factors.length) return <Text size="xs">—</Text>
  return (
    <Stack gap={2}>
      {factors.map((f) => (
        <Text key={f.title} size="xs">
          • {f.title}
        </Text>
      ))}
    </Stack>
  )
}

function Watchlist() {
  const risks = useQuery({
    queryKey: ['channel-risk', 'medium+'],
    queryFn: () =>
      api<Page<ChannelRisk>>('/forecasting/channel-risk/', {
        query: { risk_level__in: 'medium,high,critical', page_size: 10 },
      }),
  })
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Список наблюдения: каналы с повышенным риском сейчас</Text>
        <Text size="sm" c="dimmed">
          всего {risks.data?.count ?? 0}
        </Text>
      </Group>
      <Table.ScrollContainer minWidth={640}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Канал</Table.Th>
              <Table.Th>Объект</Table.Th>
              <Table.Th>Вероятность</Table.Th>
              <Table.Th>Уровень</Table.Th>
              <Table.Th>Почему</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {risks.data?.results.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>
                  <Text size="sm">{r.channel_name}</Text>
                  <Text size="xs" c="dimmed">
                    {r.sensor_type}
                  </Text>
                </Table.Td>
                <Table.Td>{r.node_name}</Table.Td>
                <Table.Td>{pct(r.probability)}</Table.Td>
                <Table.Td>
                  <RiskBadge level={r.risk_level} />
                </Table.Td>
                <Table.Td>
                  <Factors factors={r.factors} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  )
}

export function ForecastsPage() {
  const [mode, setMode] = useState<'live' | 'backtest'>('live')
  const [task, setTask] = useState<string>('all')
  const [outcome, setOutcome] = useState<string>('all')
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const filters = {
    is_backtest: mode === 'backtest',
    ...(task !== 'all' ? { task } : {}),
    ...(outcome !== 'all' ? { outcome } : {}),
  }

  const journal = useQuery({
    queryKey: ['predictions', filters, page],
    queryFn: () =>
      api<Page<Prediction>>('/forecasting/predictions/', {
        query: { ...filters, page, page_size: PAGE, ordering: '-issued_at' },
      }),
    refetchInterval: 60_000,
  })
  const summary = useQuery({
    queryKey: ['predictions', 'summary', mode, task],
    queryFn: () =>
      api<JournalSummary>('/forecasting/predictions/summary/', {
        query: { is_backtest: mode === 'backtest', ...(task !== 'all' ? { task } : {}) },
      }),
  })

  const s = summary.data
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Журнал прогнозов</Title>
        <SegmentedControl
          value={mode}
          onChange={(v) => {
            setMode(v as 'live' | 'backtest')
            setPage(1)
          }}
          data={[
            { value: 'live', label: 'Оперативные' },
            { value: 'backtest', label: 'Бэктест по истории' },
          ]}
        />
      </Group>
      <SegmentedControl
        value={task}
        onChange={(v) => {
          setTask(v)
          setPage(1)
        }}
        data={[
          { value: 'all', label: 'Все' },
          { value: 'sensor_failure', label: 'Отказ датчика' },
          { value: 'gas', label: 'Газ' },
          { value: 'flood', label: 'Подтопление' },
          { value: 'fire', label: 'Пожар' },
          { value: 'intrusion', label: 'НСД' },
        ]}
      />
      {mode === 'backtest' && (
        <Text size="sm" c="dimmed">
          Прогнозы, выпущенные задним числом на исторических данных: так модель отработала бы на реальном периоде. Исход
          размечен по факту неисправности в горизонте прогноза, инциденты по ним не создавались.
        </Text>
      )}

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Прогнозов
          </Text>
          <Text fz={28} fw={700}>
            {s?.total ?? '—'}
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Подтвердились
          </Text>
          <Text fz={28} fw={700} c="red">
            {s?.by_outcome.confirmed ?? 0}
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Ожидают исхода
          </Text>
          <Text fz={28} fw={700}>
            {s?.by_outcome.pending ?? 0}
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Tooltip label="Доля подтвердившихся среди прогнозов с известным исходом">
            <Text size="sm" c="dimmed">
              Реализованная точность
            </Text>
          </Tooltip>
          <Text fz={28} fw={700}>
            {s?.precision != null ? pct(s.precision) : '—'}
          </Text>
        </Card>
      </SimpleGrid>

      {mode === 'live' && <Watchlist />}

      <Card withBorder radius="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Прогнозы и индикаторы риска</Text>
          <SegmentedControl
            size="xs"
            value={outcome}
            onChange={(v) => {
              setOutcome(v)
              setPage(1)
            }}
            data={[
              { value: 'all', label: 'Все' },
              { value: 'pending', label: 'Ожидают' },
              { value: 'confirmed', label: 'Подтвердились' },
              { value: 'not_confirmed', label: 'Не подтвердились' },
            ]}
          />
        </Group>
        {journal.isLoading ? (
          <Loader />
        ) : (
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Сформирован</Table.Th>
                  <Table.Th>Задача</Table.Th>
                  <Table.Th>Канал</Table.Th>
                  <Table.Th>Объект</Table.Th>
                  <Table.Th>Вероятность / индекс</Table.Th>
                  <Table.Th>Уровень</Table.Th>
                  <Table.Th>Горизонт</Table.Th>
                  <Table.Th>Исход</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {journal.data?.results.map((p) => (
                    <Table.Tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/forecasts/${p.id}`)}>
                      <Table.Td>{dayjs(p.issued_at).format('DD.MM.YYYY HH:mm')}</Table.Td>
                      <Table.Td>
                        <Text size="xs">{TASK_LABEL[p.task] ?? p.task}</Text>
                      </Table.Td>
                      <Table.Td>{p.channel_name ?? '—'}</Table.Td>
                      <Table.Td>{p.node_name}</Table.Td>
                      <Table.Td>
                        {isIndicator(p.task) && p.index == null ? (
                          <Text size="sm" title="Индикатор по правилам без калибровки: индекс риска 0–1">
                            индекс {p.probability.toFixed(2)}
                          </Text>
                        ) : (
                          pct(p.probability)
                        )}
                      </Table.Td>
                      <Table.Td>
                        <RiskBadge level={p.risk_level} />
                      </Table.Td>
                      <Table.Td>до {dayjs(p.valid_until).format('DD.MM HH:mm')}</Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={PREDICTION_OUTCOME[p.outcome].color}>
                          {PREDICTION_OUTCOME[p.outcome].label}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {journal.data?.results.length === 0 && (
          <Text c="dimmed" size="sm">
            {mode === 'live'
              ? 'Оперативных прогнозов высокого риска нет. Средний риск — в списке наблюдения выше.'
              : 'Бэктест ещё не запускался (раздел «Модели»).'}
          </Text>
        )}
        {(journal.data?.count ?? 0) > PAGE && (
          <Group justify="center" mt="sm">
            <Pagination total={Math.ceil((journal.data?.count ?? 0) / PAGE)} value={page} onChange={setPage} />
          </Group>
        )}
      </Card>
    </Stack>
  )
}
