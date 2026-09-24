import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconPlayerPlay, IconRefresh } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'

import { api, type Page } from '../api/client'
import type { Metrics, MLModel, TrainingRun } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const STATUS: Record<MLModel['status'], { label: string; color: string }> = {
  training: { label: 'Обучается', color: 'blue' },
  ready: { label: 'Готова', color: 'gray' },
  active: { label: 'Активна', color: 'teal' },
  archived: { label: 'В архиве', color: 'gray' },
  failed: { label: 'Ошибка', color: 'red' },
}
const LEVEL_LABEL = { critical: 'Критический', high: 'Высокий', medium: 'Средний' } as const
const pct = (v?: number | null) => (v == null ? '—' : `${Math.round(v * 1000) / 10} %`)
const horizon = (h: number) => (h % 24 === 0 && h > 24 ? `${h / 24} сут` : `${h} ч`)

function MetricCell({ m }: { m?: Metrics }) {
  if (!m) return <Text size="sm">—</Text>
  return (
    <Text size="sm">
      P {pct(m.precision)} · R {pct(m.recall)}
    </Text>
  )
}

function ModelCard({ model, canTrain }: { model: MLModel; canTrain: boolean }) {
  const queryClient = useQueryClient()
  const m = model.metrics
  const activate = useMutation({
    mutationFn: () => api<MLModel>(`/forecasting/models/${model.id}/activate/`, { method: 'POST', body: {} }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['models'] })
      notifications.show({ color: 'teal', message: `Активна версия ${model.version}` })
    },
  })
  const importance = Object.entries(m.feature_importance ?? {}).slice(0, 6)
  const maxGain = importance.length ? importance[0][1] : 1

  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>Отказ датчика · горизонт {horizon(model.horizon_hours)}</Text>
          <Badge color={STATUS[model.status].color} variant={model.status === 'active' ? 'filled' : 'light'}>
            {STATUS[model.status].label}
          </Badge>
          <Text size="xs" c="dimmed">
            v{model.version} · {model.algorithm}
          </Text>
        </Group>
        {canTrain && model.status !== 'active' && (
          <Button size="xs" variant="light" loading={activate.isPending} onClick={() => activate.mutate()}>
            Сделать активной
          </Button>
        )}
      </Group>

      <SimpleGrid cols={{ base: 2, md: 5 }} mb="sm">
        <div>
          <Text size="xs" c="dimmed">
            PR-AUC (тест 2026)
          </Text>
          <Text fw={700}>{m.test?.pr_auc ?? '—'}</Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            ROC-AUC (тест 2026)
          </Text>
          <Text fw={700}>{m.test?.roc_auc ?? '—'}</Text>
        </div>
        <div>
          <Tooltip label="Доля каналов, у которых в горизонте начинается неисправность">
            <Text size="xs" c="dimmed">
              Базовая частота отказа
            </Text>
          </Tooltip>
          <Text fw={700}>{pct(m.test?.base_rate)}</Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Упреждение (медиана)
          </Text>
          <Text fw={700}>{m.test?.lead_time_hours ? `${m.test.lead_time_hours.median} ч` : '—'}</Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Обучение
          </Text>
          <Text fw={700}>{m.train_seconds != null ? `${m.train_seconds} с` : '—'}</Text>
        </div>
      </SimpleGrid>

      <Table withTableBorder mb="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Уровень риска</Table.Th>
            <Table.Th>Порог вероятности</Table.Th>
            <Table.Th>Точность и полнота на 2026 годе</Table.Th>
            <Table.Th>Сигналов в сутки</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(['critical', 'high', 'medium'] as const).map((level) => (
            <Table.Tr key={level}>
              <Table.Td>{LEVEL_LABEL[level]}</Table.Td>
              <Table.Td>{m.levels ? pct(m.levels[level]) : '—'}</Table.Td>
              <Table.Td>
                <MetricCell m={m.levels_test?.[level]} />
              </Table.Td>
              <Table.Td>{m.levels_test?.[level]?.alerts_per_day ?? '—'}</Table.Td>
            </Table.Tr>
          ))}
          {m.baseline_test && (
            <Table.Tr>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  Для сравнения: правило «{m.baseline_test.rule}»
                </Text>
              </Table.Td>
              <Table.Td>—</Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  P {pct(m.baseline_test.precision)} · R {pct(m.baseline_test.recall)}
                </Text>
              </Table.Td>
              <Table.Td>—</Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>

      {importance.length > 0 && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Главные признаки
          </Text>
          {importance.map(([name, gain]) => (
            <Group key={name} gap="xs" wrap="nowrap">
              <Text size="xs" w={140}>
                {name}
              </Text>
              <Progress value={(gain / maxGain) * 100} style={{ flex: 1 }} size="sm" />
            </Group>
          ))}
        </Stack>
      )}
      <Text size="xs" c="dimmed" mt="sm">
        {model.notes}
      </Text>
    </Card>
  )
}

function TrainingPanel() {
  const queryClient = useQueryClient()
  const [hours, setHours] = useState('24')
  const runs = useQuery({
    queryKey: ['training-runs'],
    queryFn: () => api<Page<TrainingRun>>('/forecasting/training-runs/', { query: { page_size: 5 } }),
    refetchInterval: (q) =>
      q.state.data?.results.some((r) => r.status === 'running' || r.status === 'pending') ? 2000 : 30_000,
  })
  const current = runs.data?.results.find((r) => r.status === 'running' || r.status === 'pending')
  const start = useMutation({
    mutationFn: () =>
      api<TrainingRun>('/forecasting/training-runs/', {
        method: 'POST',
        body: { task: 'sensor_failure', params: { horizon_hours: Number(hours) } },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['training-runs'] }),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const cycle = useMutation({
    mutationFn: () => api<{ detail: string }>('/forecasting/cycle/', { method: 'POST', body: {} }),
    onSuccess: (r) => notifications.show({ color: 'teal', message: r.detail }),
  })
  const backtest = useMutation({
    mutationFn: () => api<{ detail: string }>('/forecasting/cycle/backtest/', { method: 'POST', body: { days: 30 } }),
    onSuccess: (r) => notifications.show({ color: 'teal', message: r.detail }),
  })
  const last = runs.data?.results[0]
  // Обучение завершилось — обновить список моделей
  useEffect(() => {
    if (last?.status === 'done') void queryClient.invalidateQueries({ queryKey: ['models'] })
  }, [last?.id, last?.status, queryClient])

  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>Обучение и запуск прогноза</Text>
        <Group gap="xs">
          <SegmentedControl
            size="xs"
            value={hours}
            onChange={setHours}
            data={[
              { value: '24', label: '24 ч' },
              { value: '168', label: '7 суток' },
            ]}
          />
          <Button
            size="xs"
            leftSection={<IconRefresh size={14} />}
            onClick={() => start.mutate()}
            loading={start.isPending}
            disabled={Boolean(current)}
          >
            Обучить на всей истории
          </Button>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlayerPlay size={14} />}
            onClick={() => cycle.mutate()}
          >
            Прогноз сейчас
          </Button>
          <Tooltip label="Прогон активной модели по последним 30 суткам истории с разметкой исходов">
            <Button size="xs" variant="light" onClick={() => backtest.mutate()} loading={backtest.isPending}>
              Бэктест 30 суток
            </Button>
          </Tooltip>
        </Group>
      </Group>
      {current ? (
        <Stack gap={4}>
          <Group justify="space-between">
            <Text size="sm">{current.stage || 'В очереди'}</Text>
            <Text size="sm" c="dimmed">
              {Math.round(current.progress)} %
            </Text>
          </Group>
          <Progress value={current.progress} animated striped />
        </Stack>
      ) : (
        last && (
          <Text size="sm" c={last.status === 'failed' ? 'red' : 'dimmed'}>
            Последнее обучение {dayjs(last.finished_at ?? last.created_at).format('DD.MM.YYYY HH:mm')}:{' '}
            {last.status === 'failed' ? last.log : last.stage}
          </Text>
        )
      )}
      <Text size="xs" c="dimmed" mt="xs">
        Валидация строго по времени: обучение на 2019–2024 годах (без 2021), подбор порогов на 2025, проверка на 2026.
        Новая версия становится активной, если на валидации она не хуже текущей того же горизонта.
      </Text>
    </Card>
  )
}

export function ModelsPage() {
  const { can } = useAuth()
  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => api<Page<MLModel>>('/forecasting/models/', { query: { page_size: 20 } }),
  })
  const canTrain = can('forecasting.retrain_model')
  if (models.isLoading) return <Loader />
  const list = (models.data?.results ?? []).filter((m) => m.status !== 'archived' || m.metrics.test)
  const shown = [...list.filter((m) => m.status === 'active'), ...list.filter((m) => m.status !== 'active')].slice(0, 4)

  return (
    <Stack>
      <Title order={3}>Модели прогнозирования</Title>
      <Alert color="gray" variant="light">
        Цели ТЗ по точности и полноте (P &gt; 0,7, R &gt; 0,5) одновременно на этих данных недостижимы: отказ начинается
        в среднем у 0,4 % каналов в сутки, журналов ремонтов нет, метки слабые. Поэтому уровни риска настроены по
        точности: «критический» — самые надёжные прогнозы, «средний» — список наблюдения для планового ТО. Модель
        сравнивается с простым правилом, чтобы было видно, что она даёт сверх него.
      </Alert>
      {canTrain && <TrainingPanel />}
      {shown.length === 0 ? (
        <Text c="dimmed">Моделей ещё нет — обучите первую на загруженной истории.</Text>
      ) : (
        shown.map((m) => <ModelCard key={m.id} model={m} canTrain={canTrain} />)
      )}
    </Stack>
  )
}
