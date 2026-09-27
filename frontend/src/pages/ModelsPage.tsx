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
import type { IndicatorCalibration, Metrics, MLModel, TrainingRun } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const STATUS: Record<MLModel['status'], { label: string; color: string }> = {
  training: { label: 'Обучается', color: 'blue' },
  ready: { label: 'Готова', color: 'gray' },
  active: { label: 'Активна', color: 'teal' },
  archived: { label: 'В архиве', color: 'gray' },
  failed: { label: 'Ошибка', color: 'red' },
}
const LEVEL_LABEL = { critical: 'Критический', high: 'Высокий', medium: 'Средний' } as const
const TASK_TITLE: Record<string, string> = {
  sensor_failure: 'Отказ датчика',
  gas: 'Превышение 1 % метана',
  flood: 'Подтопление',
}
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
          <Text fw={600}>
            {TASK_TITLE[model.task] ?? model.task} · горизонт {horizon(model.horizon_hours)}
          </Text>
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
  const [task, setTask] = useState('sensor_failure')
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
        body: { task, params: { horizon_hours: Number(hours) } },
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
            value={task}
            onChange={setTask}
            data={Object.entries(TASK_TITLE).map(([value, label]) => ({ value, label }))}
          />
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

const INDICATOR_TITLE: Record<string, string> = { fire: 'Пожар', intrusion: 'Несанкционированный доступ' }

function CalibrationPanel() {
  const { can } = useAuth()
  const client = useQueryClient()
  const list = useQuery({
    queryKey: ['calibrations'],
    queryFn: () => api<Page<IndicatorCalibration>>('/forecasting/calibrations/', { query: { page_size: 20 } }),
  })
  const run = useMutation({
    mutationFn: () => api<{ detail: string }>('/forecasting/calibrations/recalibrate/', { method: 'POST' }),
    onSuccess: (r) => {
      notifications.show({ color: 'teal', message: r.detail })
      setTimeout(() => void client.invalidateQueries({ queryKey: ['calibrations'] }), 60_000)
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  // действующая калибровка — последняя по задаче
  const latest = new Map<string, IndicatorCalibration>()
  for (const c of list.data?.results ?? []) if (!latest.has(c.task)) latest.set(c.task, c)
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Индикаторы пожара и НСД: вероятность по истории</Text>
        {can('forecasting.add_indicatorcalibration') && (
          <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />} loading={run.isPending} onClick={() => run.mutate()}>
            Пересчитать по архиву
          </Button>
        )}
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Индекс правил считается по Parquet-архиву теми же правилами, что в работе, каждый час; исход — угроза проявилась
        (тревоги того же рода на объекте через 1–24 ч). Доля проявившихся среди случаев с похожим индексом, сглаженная
        и выровненная по возрастанию, — вероятность в карточке. Пересчёт — раз в неделю. Brier: меньше — лучше;
        сравнение с «частотой» показывает, что даёт индекс сверх средней доли.
      </Text>
      {list.isLoading ? (
        <Loader size="sm" />
      ) : latest.size === 0 ? (
        <Text size="sm" c="dimmed">
          Калибровки ещё нет: нужен загруженный архив журналов.
        </Text>
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          {[...latest.values()].map((c) => (
            <Stack key={c.id} gap={6}>
              <Group justify="space-between">
                <Text fw={500}>{INDICATOR_TITLE[c.task] ?? c.task}</Text>
                <Text size="xs" c="dimmed">
                  архив {c.period} · {dayjs(c.created_at).format('DD.MM.YYYY')}
                </Text>
              </Group>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Индекс</Table.Th>
                    <Table.Th>Случаев</Table.Th>
                    <Table.Th>Вероятность</Table.Th>
                    <Table.Th>
                      Проверка {c.test_period}: прогноз → факт
                    </Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {c.calibration.bins.map((b, i) => {
                    const check = c.test.reliability?.[i]
                    return (
                      <Table.Tr key={b.lo}>
                        <Table.Td>
                          {b.lo.toFixed(2)}–{b.hi.toFixed(2)}
                        </Table.Td>
                        <Table.Td>{b.n.toLocaleString('ru-RU')}</Table.Td>
                        <Table.Td fw={600}>{pct(b.p)}</Table.Td>
                        <Table.Td>
                          {check?.observed != null
                            ? `${pct(check.p)} → ${pct(check.observed)} (${check.n.toLocaleString('ru-RU')})`
                            : '—'}
                        </Table.Td>
                      </Table.Tr>
                    )
                  })}
                </Table.Tbody>
              </Table>
              <Text size="xs" c="dimmed">
                Всего случаев {c.calibration.n.toLocaleString('ru-RU')}, угроза проявилась в {pct(c.calibration.base_rate)}.
                {c.test.brier != null &&
                  ` Проверка — версия, обученная на ${c.test.train_period}, на ${c.test_period}: Brier ${c.test.brier} против ${c.test.brier_base} для постоянной частоты и ${c.test.brier_index} для «индекс как вероятность».`}
              </Text>
            </Stack>
          ))}
        </SimpleGrid>
      )}
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
  // Сначала активные версии каждой задачи, затем последние обученные
  const shown = [...list.filter((m) => m.status === 'active'), ...list.filter((m) => m.status !== 'active')].slice(0, 6)

  return (
    <Stack>
      <Title order={3}>Модели прогнозирования</Title>
      <Alert color="gray" variant="light">
        Три модели на LightGBM: отказ датчика, превышение 1 % метана, подтопление. Пожар и проникновение — правила-индикаторы
        с вероятностью по истории (внизу страницы). Цели ТЗ по точности и полноте (P &gt; 0,7, R &gt; 0,5) одновременно на этих данных
        недостижимы: события редки (доли процента каналов в сутки), журналов ремонтов нет, метки слабые. Поэтому уровни риска настроены по
        точности: «критический» — самые надёжные прогнозы, «средний» — список наблюдения для планового ТО. Модель
        сравнивается с простым правилом, чтобы было видно, что она даёт сверх него.
      </Alert>
      {canTrain && <TrainingPanel />}
      {shown.length === 0 ? (
        <Text c="dimmed">Моделей ещё нет — обучите первую на загруженной истории.</Text>
      ) : (
        shown.map((m) => <ModelCard key={m.id} model={m} canTrain={canTrain} />)
      )}
      <CalibrationPanel />
    </Stack>
  )
}
