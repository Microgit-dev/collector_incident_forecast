import { BarChart, DonutChart, LineChart } from '@mantine/charts'
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { notifications } from '@mantine/notifications'
import { IconDownload, IconFileTypePdf, IconFileTypeXls } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { StaffTab } from '../components/StaffTab'
import { api, download, type Page } from '../api/client'
import { CAUSE, RISK, TASK } from '../api/labels'
import type { DecisionCause, RiskLevel } from '../api/types'
import { useAuth } from '../auth/AuthContext'

type Span = { from: string; to: string; count: number } | null
interface Ranges {
  live: Span
  emulated: Span
  journal: Span
  backtest: Span
}

interface Stats {
  n: number
  median: number | null
  p90: number | null
}

interface Efficiency {
  emulated: number
  summary: {
    cards: number
    cards_per_shift: number
    signals: number
    reduction: number | null
    view: Stats
    take: Stats
    decision: Stats
    escalated_share: number | null
    decided_share: number | null
    closed: number
    closed_with_result_share: number | null
    forecast_useful: Record<string, number>
  }
  by_severity: Record<RiskLevel, { cards: number; view: Stats; decision: Stats; escalated_share: number | null }>
  causes: { cause: string; title: string; count: number }[]
  daily: { day: string; cards: number; escalated: number; decision_median: number | null }[]
  staff: {
    user: number
    name: string
    position: string
    team: string | null
    decisions: number
    view: number | null
    decision: number | null
    escalated_share: number | null
    with_cause_share: number | null
    false_alarm_share: number | null
    emulated: number
  }[]
}

interface TaskQuality {
  total: number
  per_day: number
  by_outcome: Record<string, number>
  precision: number | null
  false_share: number | null
  prevented: number
  recall: { onsets: number; warned: number; recall: number | null } | null
  model: {
    version: string
    test_precision_high: number | null
    test_recall_high: number | null
    lead_time_median_h: number | null
  } | null
}

interface Quality {
  tasks: Record<string, TaskQuality>
  forecast_cards: { decided: number; useful: Record<string, number> }
}

interface Report {
  id: number
  format: 'pdf' | 'xlsx'
  params: { from: string; to: string; include_emulated: boolean; backtest: boolean; scope: string }
  created_at: string
  size: number | null
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)} %`)
const mins = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)} мин`)
const day = (v: string) => dayjs(v).format('YYYY-MM-DD')
const CAUSE_COLOR: Record<string, string> = {
  sensor_fault: 'orange.6',
  communication: 'blue.6',
  power: 'grape.6',
  false_alarm: 'gray.5',
  external: 'cyan.6',
  works: 'indigo.4',
  real_event: 'red.6',
  insufficient_data: 'yellow.5',
  none: 'gray.3',
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card withBorder radius="md" padding="sm">
      <Tooltip label={hint} disabled={!hint} multiline w={280}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
      </Tooltip>
      <Text fz={24} fw={700}>
        {value}
      </Text>
    </Card>
  )
}

function DispatchersTab({ data }: { data: Efficiency }) {
  const s = data.summary
  const useful = s.forecast_useful
  const usefulTotal = (useful.yes ?? 0) + (useful.no ?? 0) + (useful.unknown ?? 0)
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, sm: 4, lg: 8 }} spacing="xs">
        <Kpi label="Карточек" value={s.cards.toLocaleString('ru-RU')} />
        <Kpi label="На 12-часовую смену" value={String(s.cards_per_shift)} />
        <Kpi
          label="Сжатие потока"
          value={s.reduction ? `×${s.reduction}` : '—'}
          hint={`${s.signals.toLocaleString('ru-RU')} сигналов → карточки-факты`}
        />
        <Kpi label="До просмотра" value={mins(s.view.median)} hint={`Медиана; 90 % — ${mins(s.view.p90)}`} />
        <Kpi label="До взятия" value={mins(s.take.median)} hint="Медиана" />
        <Kpi label="До решения" value={mins(s.decision.median)} hint={`Медиана; 90 % — ${mins(s.decision.p90)}`} />
        <Kpi label="Эскалаций по таймауту" value={pct(s.escalated_share)} />
        <Kpi
          label="Закрыто с результатом"
          value={pct(s.closed_with_result_share)}
          hint="Доля закрытых карточек, где указано «что произошло» или причина решения"
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Карточки и эскалации по суткам
          </Text>
          <BarChart
            h={220}
            data={data.daily.map((d) => ({ ...d, day: dayjs(d.day).format('DD.MM') }))}
            dataKey="day"
            series={[
              { name: 'cards', label: 'Карточек', color: 'blue.6' },
              { name: 'escalated', label: 'Эскалаций', color: 'grape.6' },
            ]}
            withLegend
          />
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Время до решения, медиана по суткам
          </Text>
          <LineChart
            h={220}
            data={data.daily.map((d) => ({ day: dayjs(d.day).format('DD.MM'), decision: d.decision_median }))}
            dataKey="day"
            unit=" мин"
            series={[{ name: 'decision', label: 'До решения', color: 'teal.6' }]}
            connectNulls
          />
        </Card>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 3 }}>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Скорость реакции по уровню
          </Text>
          <Table horizontalSpacing={6} fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Уровень</Table.Th>
                <Table.Th>Карточек</Table.Th>
                <Table.Th>Просмотр</Table.Th>
                <Table.Th>Решение</Table.Th>
                <Table.Th>Эскал.</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(Object.entries(data.by_severity) as [RiskLevel, Efficiency['by_severity'][RiskLevel]][]).map(
                ([level, v]) => (
                  <Table.Tr key={level}>
                    <Table.Td>
                      <Text size="sm" fw={600} c={`${RISK[level].color}.7`}>
                        {RISK[level].label}
                      </Text>
                    </Table.Td>
                    <Table.Td>{v.cards}</Table.Td>
                    <Table.Td>{mins(v.view.median)}</Table.Td>
                    <Table.Td>{mins(v.decision.median)}</Table.Td>
                    <Table.Td>{pct(v.escalated_share)}</Table.Td>
                  </Table.Tr>
                ),
              )}
            </Table.Tbody>
          </Table>
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Что происходило на самом деле
          </Text>
          {data.causes.length ? (
            <Group justify="center">
              <DonutChart
                size={150}
                thickness={24}
                withTooltip
                tooltipDataSource="segment"
                data={data.causes.map((c) => ({
                  name: CAUSE[c.cause as DecisionCause]?.label ?? 'не указано',
                  value: c.count,
                  color: CAUSE_COLOR[c.cause] ?? 'gray.4',
                }))}
              />
              <Stack gap={2}>
                {data.causes.map((c) => (
                  <Text key={c.cause} size="xs">
                    {CAUSE[c.cause as DecisionCause]?.label ?? 'не указано'} — {c.count}
                  </Text>
                ))}
              </Stack>
            </Group>
          ) : (
            <Text size="sm" c="dimmed">
              Решений за период нет
            </Text>
          )}
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Помог ли прогноз
          </Text>
          {usefulTotal ? (
            <Stack gap={6}>
              <Text size="sm">Прогнозных карточек с ответом: {usefulTotal}</Text>
              {[
                ['yes', 'Да, успели среагировать', 'teal'],
                ['no', 'Нет, бесполезен', 'red'],
                ['unknown', 'Не ясно', 'gray'],
              ].map(([k, label, color]) => (
                <Group key={k} justify="space-between">
                  <Badge variant="light" color={color}>
                    {label}
                  </Badge>
                  <Text size="sm">
                    {useful[k] ?? 0} · {pct((useful[k] ?? 0) / usefulTotal)}
                  </Text>
                </Group>
              ))}
              <Text size="xs" c="dimmed">
                Ответы диспетчеров в форме решения по прогнозным карточкам.
              </Text>
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Ответов по прогнозным карточкам нет
            </Text>
          )}
        </Card>
      </SimpleGrid>

      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Сотрудники
        </Text>
        <Table.ScrollContainer minWidth={760}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Сотрудник</Table.Th>
                <Table.Th>Команда</Table.Th>
                <Table.Th>Решений</Table.Th>
                <Table.Th>До просмотра</Table.Th>
                <Table.Th>До решения</Table.Th>
                <Table.Th>Эскалаций</Table.Th>
                <Table.Th>С причиной</Table.Th>
                <Table.Th>Ложных</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.staff.map((p) => (
                <Table.Tr key={p.user}>
                  <Table.Td>
                    <Text size="sm">{p.name}</Text>
                    <Text size="xs" c="dimmed">
                      {p.position}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{p.team ?? '—'}</Text>
                  </Table.Td>
                  <Table.Td>{p.decisions}</Table.Td>
                  <Table.Td>{mins(p.view)}</Table.Td>
                  <Table.Td>{mins(p.decision)}</Table.Td>
                  <Table.Td>{pct(p.escalated_share)}</Table.Td>
                  <Table.Td>{pct(p.with_cause_share)}</Table.Td>
                  <Table.Td>{pct(p.false_alarm_share)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {data.staff.length === 0 && (
          <Text size="sm" c="dimmed">
            Решений за период нет.
          </Text>
        )}
        <Text size="xs" c="dimmed" mt="xs">
          Время считается от открытия карточки: до первого просмотра (журнал просмотров), до взятия в работу и до первого
          решения. Эскалация — только по таймауту реакции. Метрики описывают поток карточек, а не качество работы человека:
          доля ложных зависит от объектов в зоне ответственности.
        </Text>
      </Card>
    </Stack>
  )
}

function ForecastsTab({ data, backtest }: { data: Quality; backtest: boolean }) {
  return (
    <Stack>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Качество прогнозов за период ({backtest ? 'бэктест' : 'оперативный журнал'})
        </Text>
        <Table.ScrollContainer minWidth={900}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Задача</Table.Th>
                <Table.Th>Записей</Table.Th>
                <Table.Th>В сутки</Table.Th>
                <Table.Th>Точность</Table.Th>
                <Table.Th>Доля ложных</Table.Th>
                <Table.Th>Предотвращено</Table.Th>
                <Table.Th>Предупреждено событий</Table.Th>
                <Table.Th>Полнота</Table.Th>
                <Table.Th>На тесте: точность / полнота</Table.Th>
                <Table.Th>Упреждение</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(data.tasks).map(([task, q]) => (
                <Table.Tr key={task}>
                  <Table.Td>{TASK[task] ?? task}</Table.Td>
                  <Table.Td>{q.total}</Table.Td>
                  <Table.Td>{q.per_day}</Table.Td>
                  <Table.Td fw={600}>{pct(q.precision)}</Table.Td>
                  <Table.Td>{pct(q.false_share)}</Table.Td>
                  <Table.Td>{q.prevented || '—'}</Table.Td>
                  <Table.Td>{q.recall ? `${q.recall.warned} из ${q.recall.onsets}` : '—'}</Table.Td>
                  <Table.Td fw={600}>{pct(q.recall?.recall)}</Table.Td>
                  <Table.Td>
                    {q.model ? `${pct(q.model.test_precision_high)} / ${pct(q.model.test_recall_high)}` : 'правила'}
                  </Table.Td>
                  <Table.Td>{q.model?.lead_time_median_h ? `${q.model.lead_time_median_h} ч` : '—'}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Stack gap={4} mt="sm">
          <Text size="xs" c="dimmed">
            <b>Точность</b> — доля подтвердившихся среди записей журнала (уровень «высокий» и выше) с известным исходом;{' '}
            <b>доля ложных</b> — остальные. «Предотвращено» — диспетчер устранил причину по прогнозу, это не ошибка
            модели.
          </Text>
          <Text size="xs" c="dimmed">
            <b>Полнота</b> — сколько событий, начавшихся за период (по суточной витрине, как при обучении), было
            заранее предупреждено прогнозом уровня «высокий» и выше. Для пожара и НСД — индекс по правилам, исход —
            «угроза проявилась», полнота не считается: подтверждённых событий нет.
          </Text>
          <Text size="xs" c="dimmed">
            Колонки «на тесте» — метрики активной модели на отложенном 2026 годе (уровень «высокий»). Цели ТЗ (P &gt; 0,7,
            R &gt; 0,5) на этих данных одновременно недостижимы — см. раздел «Модели».
          </Text>
        </Stack>
      </Card>
    </Stack>
  )
}

function ReportsTab({ params }: { params: Record<string, string | boolean> }) {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const reports = useQuery({
    queryKey: ['reports'],
    queryFn: () => api<Page<Report>>('/analytics/reports/', { query: { page_size: 20 } }),
  })
  const create = useMutation({
    mutationFn: (format: 'pdf' | 'xlsx') =>
      api<Report>('/analytics/reports/', { method: 'POST', body: { ...params, format } }),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      void download(`/analytics/reports/${r.id}/download/`, `report.${r.format}`)
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  return (
    <Stack>
      <Card withBorder radius="md">
        <Text fw={600} mb={4}>
          Отчёт за выбранный период
        </Text>
        <Text size="sm" c="dimmed" mb="sm">
          PDF — сводка для руководства: нагрузка, скорость реакции, сотрудники, качество прогнозов, что происходило.
          XLSX — та же сводка и журналы инцидентов и прогнозов за период для самостоятельного анализа. Цифры совпадают с
          этой страницей.
        </Text>
        {can('analytics.export_report') ? (
          <Group>
            <Button
              leftSection={<IconFileTypePdf size={16} />}
              loading={create.isPending && create.variables === 'pdf'}
              onClick={() => create.mutate('pdf')}
            >
              Сформировать PDF
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileTypeXls size={16} />}
              loading={create.isPending && create.variables === 'xlsx'}
              onClick={() => create.mutate('xlsx')}
            >
              Сформировать XLSX
            </Button>
          </Group>
        ) : (
          <Text size="sm" c="orange">
            Выгрузка отчётов доступна руководителю и аналитику.
          </Text>
        )}
      </Card>
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Мои отчёты
        </Text>
        {reports.data?.results.length ? (
          <Table>
            <Table.Tbody>
              {reports.data.results.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Badge variant="light" color={r.format === 'pdf' ? 'red' : 'teal'}>
                      {r.format.toUpperCase()}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {dayjs(r.params.from).format('DD.MM.YYYY')} — {dayjs(r.params.to).format('DD.MM.YYYY')}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {r.params.scope}
                      {r.params.include_emulated && ' · с эмуляцией'}
                      {r.params.backtest && ' · бэктест'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {dayjs(r.created_at).format('DD.MM HH:mm')}
                      {r.size ? ` · ${Math.max(1, Math.round(r.size / 1024))} КБ` : ''}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Anchor
                      size="sm"
                      onClick={() => void download(`/analytics/reports/${r.id}/download/`, `report.${r.format}`)}
                    >
                      <IconDownload size={14} /> скачать
                    </Anchor>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text size="sm" c="dimmed">
            Отчётов пока нет.
          </Text>
        )}
      </Card>
    </Stack>
  )
}

function defaultPeriod(r: Ranges | undefined): [string | null, string | null] {
  if (!r) return [null, null]
  const span = r.emulated ?? r.live
  const end = dayjs(span?.to)
  const start = end.subtract(29, 'day')
  return [day(span && start.isBefore(span.from) ? span.from : start.format()), day(end.format())]
}

export function AnalyticsPage() {
  const [picked, setPeriod] = useState<[string | null, string | null] | null>(null)
  const [emulated, setEmulated] = useState(true)
  const [pickedBacktest, setBacktest] = useState<boolean | null>(null)
  const [tab, setTab] = useState<string | null>('staff')

  const ranges = useQuery({ queryKey: ['analytics-ranges'], queryFn: () => api<Ranges>('/analytics/ranges/') })
  const r = ranges.data
  // По умолчанию — где есть данные: эмуляция смен на стенде или последние 30 суток работы
  const period = picked ?? defaultPeriod(r)
  const backtest = pickedBacktest ?? Boolean(r && !r.journal && r.backtest)

  const ready = Boolean(period[0] && period[1])
  const query = { from: period[0] ?? '', to: period[1] ?? '' }
  const efficiency = useQuery({
    queryKey: ['efficiency', query, emulated],
    queryFn: () => api<Efficiency>('/analytics/efficiency/', { query: { ...query, include_emulated: emulated } }),
    enabled: ready,
  })
  const quality = useQuery({
    queryKey: ['quality', query, backtest],
    queryFn: () => api<Quality>('/analytics/quality/', { query: { ...query, backtest } }),
    enabled: ready,
  })

  const presets = [
    r?.emulated && { label: 'Эмуляция смен', span: r.emulated },
    r?.live && { label: 'Реальная работа', span: r.live },
    r?.backtest && { label: 'Бэктест прогнозов', span: r.backtest },
  ].filter(Boolean) as { label: string; span: NonNullable<Span> }[]

  return (
    <Stack>
      <Title order={3}>Аналитика</Title>
      <Card withBorder radius="md">
        <Group align="flex-end" wrap="wrap">
          <DatePickerInput
            type="range"
            label="Период"
            value={period}
            onChange={(v) => setPeriod(v as [string | null, string | null])}
            valueFormat="DD.MM.YYYY"
            w={260}
            maxDate={new Date()}
          />
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              Где есть данные
            </Text>
            <Group gap={6}>
              {presets.map((p) => (
                <Button
                  key={p.label}
                  size="compact-sm"
                  variant="light"
                  onClick={() => {
                    setPeriod([day(p.span.from), day(p.span.to)])
                    if (p.label === 'Бэктест прогнозов') {
                      setBacktest(true)
                      setTab('forecasts')
                    }
                  }}
                >
                  {p.label}: {dayjs(p.span.from).format('DD.MM')}–{dayjs(p.span.to).format('DD.MM.YYYY')}
                </Button>
              ))}
            </Group>
          </Stack>
          <Switch
            label="Учитывать эмуляцию смен"
            checked={emulated}
            onChange={(e) => setEmulated(e.currentTarget.checked)}
          />
          <SegmentedControl
            size="xs"
            value={backtest ? 'backtest' : 'live'}
            onChange={(v) => setBacktest(v === 'backtest')}
            data={[
              { value: 'live', label: 'Оперативный журнал' },
              { value: 'backtest', label: 'Бэктест' },
            ]}
          />
        </Group>
      </Card>

      {efficiency.data && efficiency.data.emulated > 0 && (
        <Alert color="orange" variant="light">
          В периоде {efficiency.data.emulated} карточек из <b>эмуляции смен</b>: реальные эпизоды из данных заказчика,
          отработанные демо-диспетчерами со случайными задержками (команда emulate_shifts). Они показывают, как будут
          выглядеть отчёты; в обучение моделей не попадают. Выключите «Учитывать эмуляцию», чтобы видеть только реальную
          работу.
        </Alert>
      )}

      <Tabs value={tab} onChange={setTab}>
        <Tabs.List>
          <Tabs.Tab value="staff">Эффективность диспетчеров</Tabs.Tab>
          <Tabs.Tab value="people">Сотрудники и команды</Tabs.Tab>
          <Tabs.Tab value="forecasts">Качество прогнозов</Tabs.Tab>
          <Tabs.Tab value="reports">Отчёты</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="staff" pt="md">
          {efficiency.isLoading || !efficiency.data ? <Loader /> : <DispatchersTab data={efficiency.data} />}
        </Tabs.Panel>
        <Tabs.Panel value="people" pt="md">
          <StaffTab query={query} emulated={emulated} />
        </Tabs.Panel>
        <Tabs.Panel value="forecasts" pt="md">
          {quality.isLoading || !quality.data ? <Loader /> : <ForecastsTab data={quality.data} backtest={backtest} />}
        </Tabs.Panel>
        <Tabs.Panel value="reports" pt="md">
          <ReportsTab params={{ ...query, include_emulated: emulated, backtest }} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
