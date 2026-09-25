import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  NumberInput,
  Pagination,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type Page } from '../api/client'
import type { MLModel, TrainingRun } from '../api/types'

type Effect = 'positive' | 'negative' | 'exclude' | 'ignore'
type LabelStatus = 'pending' | 'accepted' | 'rejected'

const EFFECT: Record<Effect, { label: string; color: string }> = {
  positive: { label: 'Подтверждает отказ', color: 'red' },
  negative: { label: 'Не отказ датчика', color: 'teal' },
  exclude: { label: 'Исключить из обучения', color: 'gray' },
  ignore: { label: 'Не влияет', color: 'gray' },
}
const STATUS: Record<LabelStatus, { label: string; color: string }> = {
  pending: { label: 'На проверке', color: 'yellow' },
  accepted: { label: 'Принята', color: 'teal' },
  rejected: { label: 'Отклонена', color: 'gray' },
}

interface Rule {
  id: number
  code: string
  title: string
  effect: Effect
  weight: number
  auto_accept: boolean
  enabled: boolean
  description: string
  labels_total: number
  labels_accepted: number
}

interface Label {
  id: number
  source: 'decision' | 'emulated'
  channel_name: string
  node_name: string
  label_date: string
  effect: Effect
  weight: number
  status: LabelStatus
  rule_title: string | null
  decision: number | null
  incident: number | null
  incident_title: string | null
  decided_by: number | null
  decided_by_name: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  review_comment: string
  rows_affected: number
  model_version: string | null
}

interface Summary {
  by_status: Partial<Record<LabelStatus, number>>
  accepted_by_effect: Partial<Record<Effect, number>>
  by_dispatcher: { user: number; name: string; total: number; accepted: number; rejected: number }[]
  accepted_not_in_model: number
  emulated_active: number
}

interface Settings {
  use_feedback: boolean
  retrain_weekly: boolean
  auto_activate: boolean
  retrain_on_degradation: boolean
  degradation_ratio: number
  degradation_window_days: number
  degradation_min_resolved: number
  horizon_hours: number
  last_check: Record<string, unknown>
}

type FeedbackMetrics = {
  enabled?: boolean
  labels?: number
  labels_matched?: number
  effects?: Record<string, { rows: number; flipped: number; positives_removed: number }>
  ablation?: Record<'valid' | 'test', { with_feedback: number; without_feedback: number }> | null
}

function useReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ changed: number }>('/forecasting/feedback-labels/review/', { method: 'POST', body }),
    onSuccess: (r) => {
      notifications.show({ color: 'teal', message: `Изменено меток: ${r.changed}` })
      void queryClient.invalidateQueries({ queryKey: ['feedback'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
}

// ---------- влияние на модели ----------

function Delta({ a, b }: { a?: number; b?: number }) {
  if (a == null || b == null) return <Text size="sm">—</Text>
  const d = a - b
  return (
    <Text size="sm" c={d > 0.0005 ? 'teal' : d < -0.0005 ? 'red' : 'dimmed'}>
      {a.toFixed(3)} против {b.toFixed(3)} ({d >= 0 ? '+' : ''}
      {d.toFixed(3)})
    </Text>
  )
}

function TrainButtons() {
  const queryClient = useQueryClient()
  const runs = useQuery({
    queryKey: ['training-runs'],
    queryFn: () => api<Page<TrainingRun>>('/forecasting/training-runs/', { query: { page_size: 3 } }),
    refetchInterval: (q) =>
      q.state.data?.results.some((r) => r.status === 'running' || r.status === 'pending') ? 2000 : 30_000,
  })
  const current = runs.data?.results.find((r) => r.status === 'running' || r.status === 'pending')
  const last = runs.data?.results[0]
  useEffect(() => {
    if (last?.status === 'done') void queryClient.invalidateQueries({ queryKey: ['models'] })
  }, [last?.id, last?.status, queryClient])
  const start = useMutation({
    mutationFn: (useFeedback: boolean) =>
      api<TrainingRun>('/forecasting/training-runs/', {
        method: 'POST',
        body: { task: 'sensor_failure', params: { horizon_hours: 24, use_feedback: useFeedback } },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['training-runs'] }),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  return (
    <Card withBorder radius="md">
      <Group justify="space-between">
        <Text fw={600}>Переобучение (горизонт 24 ч)</Text>
        <Group gap="xs">
          <Button size="xs" onClick={() => start.mutate(true)} disabled={Boolean(current)}>
            С учётом разметки
          </Button>
          <Button size="xs" variant="light" onClick={() => start.mutate(false)} disabled={Boolean(current)}>
            Без разметки
          </Button>
        </Group>
      </Group>
      {current ? (
        <Stack gap={4} mt="sm">
          <Text size="sm">{current.stage || 'В очереди'}</Text>
          <Progress value={current.progress} animated striped />
        </Stack>
      ) : (
        last && (
          <Text size="sm" c={last.status === 'failed' ? 'red' : 'dimmed'} mt="xs">
            Последнее обучение {dayjs(last.finished_at ?? last.created_at).format('DD.MM HH:mm')}:{' '}
            {last.status === 'failed' ? last.log : last.stage}
          </Text>
        )
      )}
    </Card>
  )
}

function ImpactTab() {
  const queryClient = useQueryClient()
  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => api<Page<MLModel>>('/forecasting/models/', { query: { page_size: 20 } }),
  })
  const activate = useMutation({
    mutationFn: (id: number) => api<MLModel>(`/forecasting/models/${id}/activate/`, { method: 'POST', body: {} }),
    onSuccess: (m) => {
      notifications.show({ color: 'teal', message: `Активна версия ${m.version}` })
      void queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
  if (models.isLoading) return <Loader />
  const list = (models.data?.results ?? []).filter((m) => m.metrics.valid)

  return (
    <Stack>
      <TrainButtons />
      <Text size="sm" c="dimmed">
        При каждом обучении с разметкой параллельно обучается контрольная модель на тех же строках, но с исходными
        (слабыми) метками. Обе оцениваются на выборке с учётом разметки — разница показывает, что дали решения
        диспетчеров. Новая версия сравнивается с действующей на одной и той же валидации; откат — кнопкой «Сделать
        активной» у прежней версии.
      </Text>
      <Table.ScrollContainer minWidth={980}>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Версия</Table.Th>
              <Table.Th>Разметка</Table.Th>
              <Table.Th>Изменено строк выборки</Table.Th>
              <Table.Th>PR-AUC валидация: с разметкой / без</Table.Th>
              <Table.Th>PR-AUC тест 2026: с разметкой / без</Table.Th>
              <Table.Th>Решение по версии</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.map((m) => {
              const fb = (m.metrics as { feedback?: FeedbackMetrics }).feedback
              const cmp = (m.metrics as { comparison?: { verdict?: string } }).comparison
              const effects = fb?.effects ?? {}
              return (
                <Table.Tr key={m.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {m.version}
                    </Text>
                    <Group gap={4}>
                      <Badge
                        size="xs"
                        color={m.status === 'active' ? 'teal' : 'gray'}
                        variant={m.status === 'active' ? 'filled' : 'light'}
                      >
                        {m.status === 'active' ? 'активна' : m.status === 'archived' ? 'архив' : 'готова'}
                      </Badge>
                      <Text size="xs" c="dimmed">
                        {m.horizon_hours} ч ·{' '}
                        {String((m as unknown as { params: Record<string, unknown> }).params?.trigger ?? 'manual')}
                      </Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {fb?.enabled === false ? (
                      <Text size="sm" c="dimmed">
                        выключена
                      </Text>
                    ) : fb?.labels ? (
                      <Text size="sm">
                        {fb.labels} меток, сработали {fb.labels_matched}
                      </Text>
                    ) : (
                      <Text size="sm" c="dimmed">
                        нет принятых меток
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {Object.keys(effects).length === 0 ? (
                      <Text size="sm">—</Text>
                    ) : (
                      <Stack gap={0}>
                        {Object.entries(effects)
                          .filter(([, v]) => v.rows > 0)
                          .map(([k, v]) => (
                            <Text key={k} size="xs">
                              {EFFECT[k as Effect]?.label}: {v.rows}
                              {v.flipped ? `, метка изменена у ${v.flipped}` : ''}
                              {v.positives_removed ? `, убрано отказов ${v.positives_removed}` : ''}
                            </Text>
                          ))}
                      </Stack>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Delta a={fb?.ablation?.valid.with_feedback} b={fb?.ablation?.valid.without_feedback} />
                  </Table.Td>
                  <Table.Td>
                    <Delta a={fb?.ablation?.test.with_feedback} b={fb?.ablation?.test.without_feedback} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{cmp?.verdict ?? '—'}</Text>
                  </Table.Td>
                  <Table.Td>
                    {m.status !== 'active' && (
                      <Button
                        size="xs"
                        variant="light"
                        onClick={() => activate.mutate(m.id)}
                        loading={activate.isPending}
                      >
                        Сделать активной
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}

// ---------- разметка ----------

const PAGE = 25

function LabelsTab() {
  const review = useReview()
  const [status, setStatus] = useState<string | null>('pending')
  const [effect, setEffect] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number[]>([])
  const [comment, setComment] = useState('')
  const filters = { ...(status ? { status } : {}), ...(effect ? { effect } : {}) }
  const labels = useQuery({
    queryKey: ['feedback', 'labels', filters, page],
    queryFn: () => api<Page<Label>>('/forecasting/feedback-labels/', { query: { ...filters, page, page_size: PAGE } }),
  })
  const summary = useQuery({
    queryKey: ['feedback', 'summary'],
    queryFn: () => api<Summary>('/forecasting/feedback-labels/summary/'),
  })
  const s = summary.data
  const act = (body: Record<string, unknown>) => {
    review.mutate({ ...body, comment })
    setSelected([])
  }
  const rows = labels.data?.results ?? []

  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        {(['pending', 'accepted', 'rejected'] as LabelStatus[]).map((k) => (
          <Card key={k} withBorder radius="md">
            <Text size="sm" c="dimmed">
              {STATUS[k].label}
            </Text>
            <Text fz={26} fw={700} c={STATUS[k].color === 'gray' ? undefined : STATUS[k].color}>
              {s?.by_status[k] ?? 0}
            </Text>
          </Card>
        ))}
        <Card withBorder radius="md">
          <Tooltip label="Принятые метки, которые ещё не участвовали в обучении — войдут в следующую версию">
            <Text size="sm" c="dimmed">
              Ждут обучения
            </Text>
          </Tooltip>
          <Text fz={26} fw={700}>
            {s?.accepted_not_in_model ?? 0}
          </Text>
        </Card>
      </SimpleGrid>

      {Boolean(s?.emulated_active) && (
        <Alert color="violet" variant="light">
          <Group justify="space-between">
            <Text size="sm">
              {s?.emulated_active} меток создано эмуляцией на исторических событиях — для демонстрации влияния разметки
              на стенде без живых решений за исторический период.
            </Text>
            <Button size="xs" color="violet" variant="light" onClick={() => act({ source: 'emulated', status: 'rejected' })}>
              Отклонить всю эмуляцию
            </Button>
          </Group>
        </Alert>
      )}
      {Boolean(s?.by_dispatcher.length) && (
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Разметка по диспетчерам
          </Text>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Диспетчер</Table.Th>
                <Table.Th>Меток</Table.Th>
                <Table.Th>Принято</Table.Th>
                <Table.Th>Отклонено</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {s?.by_dispatcher.map((d) => (
                <Table.Tr key={d.user}>
                  <Table.Td>{d.name}</Table.Td>
                  <Table.Td>{d.total}</Table.Td>
                  <Table.Td>{d.accepted}</Table.Td>
                  <Table.Td>{d.rejected}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Button
                        size="compact-xs"
                        variant="light"
                        onClick={() => act({ decided_by: d.user, status: 'accepted', only_status: 'pending' })}
                      >
                        Принять ожидающие
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="light"
                        color="red"
                        onClick={() => act({ decided_by: d.user, status: 'rejected' })}
                      >
                        Отклонить все
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <Card withBorder radius="md">
        <Group justify="space-between" mb="sm" wrap="wrap">
          <Group gap="xs">
            <Select
              size="xs"
              placeholder="Статус"
              data={Object.entries(STATUS).map(([value, v]) => ({ value, label: v.label }))}
              value={status}
              onChange={(v) => {
                setStatus(v)
                setPage(1)
              }}
              clearable
              w={160}
            />
            <Select
              size="xs"
              placeholder="Эффект"
              data={Object.entries(EFFECT)
                .filter(([k]) => k !== 'ignore')
                .map(([value, v]) => ({ value, label: v.label }))}
              value={effect}
              onChange={(v) => {
                setEffect(v)
                setPage(1)
              }}
              clearable
              w={200}
            />
          </Group>
          <Group gap="xs">
            <TextInput
              size="xs"
              placeholder="Комментарий к решению"
              value={comment}
              onChange={(e) => setComment(e.currentTarget.value)}
              w={220}
            />
            <Button size="xs" disabled={!selected.length} onClick={() => act({ ids: selected, status: 'accepted' })}>
              Принять ({selected.length})
            </Button>
            <Button
              size="xs"
              color="red"
              variant="light"
              disabled={!selected.length}
              onClick={() => act({ ids: selected, status: 'rejected' })}
            >
              Отклонить ({selected.length})
            </Button>
          </Group>
        </Group>
        {labels.isLoading ? (
          <Loader />
        ) : rows.length === 0 ? (
          <Text size="sm" c="dimmed">
            Меток нет. Они появляются, когда диспетчеры закрывают инциденты с причиной решения.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={1000}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>
                    <Checkbox
                      checked={selected.length === rows.length}
                      indeterminate={selected.length > 0 && selected.length < rows.length}
                      onChange={(e) => setSelected(e.currentTarget.checked ? rows.map((r) => r.id) : [])}
                    />
                  </Table.Th>
                  <Table.Th>Канал</Table.Th>
                  <Table.Th>Дата события</Table.Th>
                  <Table.Th>Эффект</Table.Th>
                  <Table.Th>Решение</Table.Th>
                  <Table.Th>Статус</Table.Th>
                  <Table.Th>В модели</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((l) => (
                  <Table.Tr key={l.id}>
                    <Table.Td>
                      <Checkbox
                        checked={selected.includes(l.id)}
                        onChange={(e) =>
                          setSelected((prev) =>
                            e.currentTarget.checked ? [...prev, l.id] : prev.filter((x) => x !== l.id),
                          )
                        }
                      />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{l.channel_name}</Text>
                      <Text size="xs" c="dimmed">
                        {l.node_name}
                      </Text>
                    </Table.Td>
                    <Table.Td>{dayjs(l.label_date).format('DD.MM.YYYY')}</Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={EFFECT[l.effect].color}>
                        {EFFECT[l.effect].label}
                      </Badge>
                      <Text size="xs" c="dimmed">
                        вес ×{l.weight}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Text size="sm">{l.rule_title}</Text>
                        {l.source === 'emulated' && (
                          <Tooltip label="Метка создана эмуляцией на исторических событиях для демонстрационного стенда">
                            <Badge size="xs" color="violet" variant="light">
                              эмуляция
                            </Badge>
                          </Tooltip>
                        )}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {l.decided_by_name}
                        {l.incident && (
                          <>
                            {' · '}
                            <Anchor component={Link} to={`/incidents/${l.incident}`} size="xs">
                              инцидент #{l.incident}
                            </Anchor>
                          </>
                        )}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="dot" color={STATUS[l.status].color}>
                        {STATUS[l.status].label}
                      </Badge>
                      {l.reviewed_by_name && (
                        <Text size="xs" c="dimmed">
                          {l.reviewed_by_name}
                          {l.review_comment && `: ${l.review_comment}`}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {l.model_version ? (
                        <Text size="xs">
                          v{l.model_version}
                          <br />
                          строк изменено: {l.rows_affected}
                        </Text>
                      ) : (
                        <Text size="xs" c="dimmed">
                          ещё нет
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {l.status !== 'accepted' && (
                          <Button
                            size="compact-xs"
                            variant="light"
                            onClick={() => act({ ids: [l.id], status: 'accepted' })}
                          >
                            Принять
                          </Button>
                        )}
                        {l.status !== 'rejected' && (
                          <Button
                            size="compact-xs"
                            variant="light"
                            color="red"
                            onClick={() => act({ ids: [l.id], status: 'rejected' })}
                          >
                            {l.status === 'accepted' ? 'Отменить' : 'Отклонить'}
                          </Button>
                        )}
                        {l.decision && (
                          <Tooltip label="Отклонить все метки этого решения диспетчера">
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              color="red"
                              onClick={() => act({ decision: l.decision, status: 'rejected' })}
                            >
                              Всё решение
                            </Button>
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {(labels.data?.count ?? 0) > PAGE && (
          <Group justify="center" mt="sm">
            <Pagination total={Math.ceil((labels.data?.count ?? 0) / PAGE)} value={page} onChange={setPage} />
          </Group>
        )}
        <Text size="xs" c="dimmed" mt="xs">
          Отклонённая метка не участвует в следующем обучении. Чтобы убрать её влияние из уже действующей модели,
          переобучите модель или верните прежнюю версию на вкладке «Влияние на модели».
        </Text>
      </Card>
    </Stack>
  )
}

// ---------- правила ----------

function RulesTab() {
  const queryClient = useQueryClient()
  const rules = useQuery({
    queryKey: ['feedback', 'rules'],
    queryFn: () => api<Rule[]>('/forecasting/feedback-rules/'),
  })
  const save = useMutation({
    mutationFn: ({ id, ...body }: Partial<Rule> & { id: number }) =>
      api<Rule>(`/forecasting/feedback-rules/${id}/`, { method: 'PATCH', body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['feedback', 'rules'] }),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  if (rules.isLoading) return <Loader />
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Правило определяет, как причина решения диспетчера превращается в метку для обучения. Изменение правила
        действует на новые метки; уже созданные можно принять или отклонить на вкладке «Разметка».
      </Text>
      <Table.ScrollContainer minWidth={980}>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Причина решения</Table.Th>
              <Table.Th>Эффект для обучения</Table.Th>
              <Table.Th>Вес</Table.Th>
              <Table.Th>Без проверки</Table.Th>
              <Table.Th>Включено</Table.Th>
              <Table.Th>Меток</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rules.data?.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td maw={320}>
                  <Text size="sm" fw={500}>
                    {r.title}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {r.description}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Select
                    size="xs"
                    w={210}
                    data={Object.entries(EFFECT).map(([value, v]) => ({ value, label: v.label }))}
                    value={r.effect}
                    onChange={(v) => v && save.mutate({ id: r.id, effect: v as Effect })}
                    allowDeselect={false}
                  />
                </Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    w={80}
                    min={0.1}
                    max={10}
                    step={0.5}
                    decimalScale={1}
                    defaultValue={r.weight}
                    onBlur={(e) => {
                      const value = Number(e.currentTarget.value.replace(',', '.'))
                      if (value && value !== r.weight) save.mutate({ id: r.id, weight: value })
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Switch
                    checked={r.auto_accept}
                    onChange={(e) => save.mutate({ id: r.id, auto_accept: e.currentTarget.checked })}
                  />
                </Table.Td>
                <Table.Td>
                  <Switch
                    checked={r.enabled}
                    onChange={(e) => save.mutate({ id: r.id, enabled: e.currentTarget.checked })}
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {r.labels_accepted} / {r.labels_total}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}

// ---------- настройки ----------

function SettingsTab() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ['feedback', 'settings'],
    queryFn: () => api<Settings>('/forecasting/learning-settings/'),
  })
  const save = useMutation({
    mutationFn: (body: Partial<Settings>) =>
      api<Settings>('/forecasting/learning-settings/', { method: 'PATCH', body }),
    onSuccess: (data) => queryClient.setQueryData(['feedback', 'settings'], data),
  })
  const check = useMutation({
    mutationFn: () => api<Record<string, unknown>>('/forecasting/learning-settings/', { method: 'POST', body: {} }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['feedback', 'settings'] }),
  })
  const s = settings.data
  if (!s) return <Loader />
  const last = s.last_check as {
    status?: string
    checked_at?: string
    realized_precision?: number | null
    expected_precision?: number | null
    resolved?: number
  }
  const statusText: Record<string, string> = {
    ok: 'в норме',
    degraded: 'деградация',
    not_enough_data: 'мало прогнозов с исходом',
    no_model: 'нет активной модели',
  }
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }}>
      <Card withBorder radius="md">
        <Text fw={600} mb="sm">
          Дообучение
        </Text>
        <Stack>
          <Switch
            label="Учитывать разметку диспетчеров при обучении"
            checked={s.use_feedback}
            onChange={(e) => save.mutate({ use_feedback: e.currentTarget.checked })}
          />
          <Switch
            label="Переобучать раз в неделю"
            checked={s.retrain_weekly}
            onChange={(e) => save.mutate({ retrain_weekly: e.currentTarget.checked })}
          />
          <Switch
            label="Автоматически активировать версию, если она не хуже действующей"
            description="Иначе новая версия ждёт решения аналитика"
            checked={s.auto_activate}
            onChange={(e) => save.mutate({ auto_activate: e.currentTarget.checked })}
          />
          <Switch
            label="Переобучать при деградации"
            checked={s.retrain_on_degradation}
            onChange={(e) => save.mutate({ retrain_on_degradation: e.currentTarget.checked })}
          />
        </Stack>
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="sm">
          Контроль деградации
        </Text>
        <Stack gap="xs">
          <NumberInput
            label="Порог: доля от ожидаемой точности"
            min={0.1}
            max={1}
            step={0.05}
            decimalScale={2}
            defaultValue={s.degradation_ratio}
            onBlur={(e) => save.mutate({ degradation_ratio: Number(e.currentTarget.value.replace(',', '.')) })}
          />
          <NumberInput
            label="Окно, суток"
            min={3}
            max={90}
            defaultValue={s.degradation_window_days}
            onBlur={(e) => save.mutate({ degradation_window_days: Number(e.currentTarget.value) })}
          />
          <NumberInput
            label="Минимум прогнозов с исходом"
            min={5}
            max={1000}
            defaultValue={s.degradation_min_resolved}
            onBlur={(e) => save.mutate({ degradation_min_resolved: Number(e.currentTarget.value) })}
          />
          <Alert color={last.status === 'degraded' ? 'red' : 'gray'} variant="light">
            {last.status ? (
              <Text size="sm">
                Последняя проверка {last.checked_at ? dayjs(last.checked_at).format('DD.MM HH:mm') : ''}:{' '}
                {statusText[last.status] ?? last.status}
                {last.realized_precision != null &&
                  ` — точность журнала ${Math.round(last.realized_precision * 100)} % при ожидаемой ${Math.round((last.expected_precision ?? 0) * 100)} % (прогнозов с исходом: ${last.resolved})`}
              </Text>
            ) : (
              <Text size="sm">Проверка ещё не выполнялась</Text>
            )}
          </Alert>
          <Button size="xs" variant="light" onClick={() => check.mutate()} loading={check.isPending}>
            Проверить сейчас
          </Button>
        </Stack>
      </Card>
    </SimpleGrid>
  )
}

export function LearningPage() {
  return (
    <Stack>
      <Title order={3}>Обучение и обратная связь</Title>
      <Tabs defaultValue="impact" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="impact">Влияние на модели</Tabs.Tab>
          <Tabs.Tab value="labels" data-tour="labels">
            Разметка диспетчеров
          </Tabs.Tab>
          <Tabs.Tab value="rules">Правила разметки</Tabs.Tab>
          <Tabs.Tab value="settings">Настройки</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="impact" pt="md">
          <ImpactTab />
        </Tabs.Panel>
        <Tabs.Panel value="labels" pt="md">
          <LabelsTab />
        </Tabs.Panel>
        <Tabs.Panel value="rules" pt="md">
          <RulesTab />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <SettingsTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
