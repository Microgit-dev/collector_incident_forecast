import { BarChart } from '@mantine/charts'
import {
  Anchor,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  List,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconClipboardPlus } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import { CHANNEL_STATE, HEALTH_COMPONENT, INCIDENT_TYPE, isIndicator, PREDICTION_OUTCOME, TASK } from '../api/labels'
import type { PredictionCard } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge, StatusBadge } from '../components/badges'
import { CameraPanel } from '../components/CameraPanel'

const pct = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
const scoreColor = (v: number) => (v >= 80 ? 'teal' : v >= 50 ? 'yellow' : 'red')

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Tooltip label={hint} disabled={!hint} multiline w={260}>
      <div>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Text fw={700} fz="lg">
          {value}
        </Text>
      </div>
    </Tooltip>
  )
}

function TrustCard({ card }: { card: PredictionCard }) {
  const m = card.model_info
  const live = card.realized.live
  const back = card.realized.backtest
  if (m.method === 'rules') {
    const test = m.test
    return (
      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Насколько доверять
        </Text>
        <Text size="sm">{m.note}</Text>
        {m.calibrated && m.bin ? (
          <>
            <SimpleGrid cols={{ base: 2, sm: 4 }} mt="sm">
              <Metric
                label="Похожих случаев в истории"
                value={m.bin.n.toLocaleString('ru-RU')}
                hint={`Моменты ${m.period} с индексом ${m.bin.lo.toFixed(2)}–${m.bin.hi.toFixed(2)}`}
              />
              <Metric label="Угроза проявилась" value={pct(m.bin.p)} hint={`${m.bin.k} из ${m.bin.n}, со сглаживанием`} />
              <Metric
                label="Обычная частота"
                value={pct(test?.n ? test.k! / test.n : undefined)}
                hint="Доля проявившихся среди всех случаев с индексом от 0,15 на отложенном периоде"
              />
              <Metric
                label="Проверка (Brier)"
                value={test?.brier != null ? test.brier.toFixed(3) : '—'}
                hint={`Отложенный ${m.test_period}: ${test?.brier ?? '—'} против ${test?.brier_base ?? '—'} для постоянной частоты. Меньше — лучше`}
              />
            </SimpleGrid>
            <Text size="xs" c="dimmed" mt="xs">
              Калибровка по архиву {m.period}; проверка — версия, обученная на {test?.train_period ?? '—'}, на
              {' '}{m.test_period}. Вероятность по интервалам индекса:{' '}
              {m.bins?.map((b) => `${b.lo.toFixed(2)}–${b.hi.toFixed(2)}: ${pct(b.p)}`).join(' · ')}
            </Text>
          </>
        ) : (
          <Text size="sm" mt="xs" c="orange.8">
            Калибровки ещё нет (архив журналов не загружен) — показан индекс правил.
          </Text>
        )}
        <Text size="sm" mt="xs">
          Итог журнала на этом уровне: угроза проявилась в {back.confirmed} из {back.resolved} записей бэктеста (
          {pct(back.precision)}), в работе — {live.confirmed} из {live.resolved}.
        </Text>
      </Card>
    )
  }
  const level = m.level_test ?? {}
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Насколько доверять</Text>
        <Text size="xs" c="dimmed">
          модель {m.version} · {m.algorithm}
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Metric
          label="Точность уровня на тесте"
          value={pct(level.precision)}
          hint="Доля сбывшихся среди прогнозов этого уровня на отложенном 2026 годе"
        />
        <Metric label="Полнота уровня" value={pct(level.recall)} hint="Какую долю событий ловит этот уровень и выше" />
        <Metric
          label="Упреждение (медиана)"
          value={level.lead_time_median_h != null ? `${level.lead_time_median_h} ч` : '—'}
          hint="За сколько часов до события модель поднимала этот уровень"
        />
        <Metric
          label="Сбылось в журнале"
          value={pct(live.resolved ? live.precision : back.precision)}
          hint={`Работа: ${live.confirmed} из ${live.resolved}; бэктест: ${back.confirmed} из ${back.resolved}`}
        />
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="xs">
        Без модели событие случается у {pct(m.base_rate, 1)} каналов в сутки — прогноз этого уровня в{' '}
        {m.base_rate && level.precision ? Math.round(level.precision / m.base_rate) : '—'} раз точнее случайного.
        {m.baseline && ` Простое правило «${m.baseline.rule}»: точность ${pct(m.baseline.precision)}.`}
      </Text>
    </Card>
  )
}

function ChannelHistory({ card }: { card: PredictionCard }) {
  const ch = card.channel_info
  if (!ch || ch.daily.length === 0) return null
  const issued = dayjs(card.issued_at).format('DD.MM')
  return (
    <Card withBorder radius="md">
      <Text fw={600} mb="xs">
        История канала за 30 суток{' '}
        <Text span size="xs" c="dimmed" fw={400}>
          · синяя линия — сутки прогноза
        </Text>
      </Text>
      <BarChart
        h={160}
        data={ch.daily.map((d) => ({
          day: dayjs(d.day).format('DD.MM'),
          faults: d.faults,
          alarms: d.alarms,
          other: d.power_losses + d.unknowns,
        }))}
        dataKey="day"
        type="stacked"
        referenceLines={[{ x: issued, color: 'blue.6' }]}
        series={[
          { name: 'faults', label: 'Неисправность', color: 'orange.6' },
          { name: 'alarms', label: 'Тревога', color: 'red.6' },
          { name: 'other', label: 'Нет питания / не определено', color: 'gray.5' },
        ]}
        withLegend
      />
    </Card>
  )
}

function DataQuality({ card }: { card: PredictionCard }) {
  const ch = card.channel_info
  if (!ch) return null
  const h = ch.health
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Качество данных канала</Text>
        {h && (
          <Badge size="lg" color={scoreColor(h.score)}>
            Data Health {h.score}
          </Badge>
        )}
      </Group>
      <Text size="sm">
        {ch.sensor_type ?? 'тип не определён'}
        {ch.picket != null && ` · ПК${ch.picket}`}
        {ch.location_hint && ` · ${ch.location_hint}`}
      </Text>
      {ch.state && (
        <Text size="sm" mt={4}>
          Сейчас:{' '}
          <Badge variant="light" color={CHANNEL_STATE[ch.state.state]?.color ?? 'gray'}>
            {CHANNEL_STATE[ch.state.state]?.label ?? ch.state.state}
          </Badge>{' '}
          <Text span size="xs" c="dimmed">
            с {dayjs(ch.state.since).format('DD.MM.YYYY HH:mm')}
          </Text>
        </Text>
      )}
      {h?.silent && (
        <Text size="sm" c="red" mt={4}>
          Канал молчит с {dayjs(h.silent_since).format('DD.MM HH:mm')} — выводы по нему ненадёжны
        </Text>
      )}
      {h && (
        <Stack gap={4} mt="xs">
          {Object.entries(h.components)
            .filter(([, v]) => v != null)
            .map(([k, v]) => (
              <div key={k}>
                <Group justify="space-between">
                  <Text size="xs">{HEALTH_COMPONENT[k] ?? k}</Text>
                  <Text size="xs" c="dimmed">
                    {Math.round((v ?? 0) * 100)} %
                  </Text>
                </Group>
                <Progress value={(v ?? 0) * 100} size="xs" color={scoreColor((v ?? 0) * 100)} />
              </div>
            ))}
        </Stack>
      )}
      {ch.risks.filter((r) => r.task !== card.task).length > 0 && (
        <Text size="xs" c="dimmed" mt="xs">
          Другие риски канала:{' '}
          {ch.risks
            .filter((r) => r.task !== card.task)
            .map((r) => `${TASK[r.task] ?? r.task} ${pct(r.probability)}`)
            .join(' · ')}
        </Text>
      )}
    </Card>
  )
}

function ActionCard({ card }: { card: PredictionCard }) {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const draft = useMutation({
    mutationFn: (id: number) =>
      api<{ number: string }>(`/workorders/recommendations/${id}/draft/`, { method: 'POST', body: {} }),
    onSuccess: (order) => {
      notifications.show({ color: 'teal', message: `Создан черновик заявки ${order.number}` })
      void queryClient.invalidateQueries({ queryKey: ['prediction', card.id] })
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })
  return (
    <Card withBorder radius="md">
      <Text fw={600} mb="xs">
        Что делать
      </Text>
      <List size="sm" type="ordered" spacing={4}>
        {card.actions.map((a) => (
          <List.Item key={a.code}>{a.title}</List.Item>
        ))}
      </List>
      {card.recommendations.length > 0 && (
        <Stack gap="xs" mt="sm">
          <Text size="sm" fw={500}>
            Рекомендации по ТО
          </Text>
          {card.recommendations.map((r) => (
            <Stack key={r.id} gap={4}>
              <Stack gap={0}>
                <Group gap={6}>
                  <RiskBadge level={r.priority} />
                  <Text size="sm">{r.work_type}</Text>
                  <Text size="xs" c="dimmed">
                    до {dayjs(r.due_date).format('DD.MM.YYYY')}
                  </Text>
                </Group>
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {r.rationale}
                </Text>
              </Stack>
              {r.work_order ? (
                <Anchor component={Link} to="/workorders" size="xs">
                  заявка {r.work_order.number}
                </Anchor>
              ) : (
                can('workorders.add_workorder') && (
                  <Button
                    size="compact-xs"
                    variant="light"
                    w="fit-content"
                    leftSection={<IconClipboardPlus size={14} />}
                    loading={draft.isPending && draft.variables === r.id}
                    onClick={() => draft.mutate(r.id)}
                  >
                    Черновик заявки
                  </Button>
                )
              )}
            </Stack>
          ))}
        </Stack>
      )}
    </Card>
  )
}

export function ForecastCardPage() {
  const { id } = useParams()
  const { data: card, isLoading } = useQuery({
    queryKey: ['prediction', Number(id)],
    queryFn: () => api<PredictionCard>(`/forecasting/predictions/${id}/`),
  })
  if (isLoading || !card) return <Loader />

  const maxContribution = Math.max(...card.factors.map((f) => Math.abs(f.contribution ?? 0)), 0.01)
  const indicator = isIndicator(card.task)
  const outcome = PREDICTION_OUTCOME[card.outcome]

  return (
    <Stack>
      <Anchor component={Link} to="/forecasts" size="sm">
        ← К журналу прогнозов
      </Anchor>
      <Stack gap={4}>
        <Group gap="xs">
          <RiskBadge level={card.risk_level} />
          <Badge variant="light" color={outcome.color}>
            {outcome.label}
          </Badge>
          {card.is_backtest && <Badge variant="outline">бэктест</Badge>}
        </Group>
        <Title order={3}>
          {TASK[card.task] ?? card.task}: {card.channel_name ?? card.node_name}
        </Title>
        <Text size="sm" c="dimmed">
          {card.node_name} · сформирован {dayjs(card.issued_at).format('DD.MM.YYYY HH:mm')} · действует до{' '}
          {dayjs(card.valid_until).format('DD.MM.YYYY HH:mm')}
          {card.channel && (
            <>
              {' · '}
              <Anchor
                component={Link}
                to={`/history?node=${card.node}&channel=${card.channel}&from=${dayjs(card.issued_at).subtract(6, 'day').format('YYYY-MM-DD')}&to=${dayjs(card.valid_until).format('YYYY-MM-DD')}`}
                size="sm"
              >
                история канала
              </Anchor>
            </>
          )}
        </Text>
      </Stack>

      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack>
            <Card withBorder radius="md">
              <Group align="flex-end" gap="xl" mb="xs">
                <div>
                  <Text size="xs" c="dimmed">
                    {indicator && !card.model_info.calibrated
                      ? 'Индекс риска'
                      : indicator
                        ? `Вероятность проявления за ${card.horizon_hours} ч`
                        : `Вероятность за ${card.horizon_hours} ч`}
                  </Text>
                  <Text fz={40} fw={700} lh={1}>
                    {indicator && !card.model_info.calibrated ? card.probability.toFixed(2) : pct(card.probability)}
                  </Text>
                  {indicator && card.index != null && card.model_info.calibrated && (
                    <Text size="xs" c="dimmed" mt={4}>
                      индекс правил {card.index.toFixed(2)}
                    </Text>
                  )}
                </div>
                <Text size="sm" style={{ flex: 1 }}>
                  {card.summary}
                </Text>
              </Group>
              <Text size="sm" fw={500} mb={4}>
                Почему так: факторы
              </Text>
              <Stack gap={6}>
                {card.factors.map((f, i) => (
                  <div key={i}>
                    <Group justify="space-between" gap="xs" wrap="nowrap">
                      <Text size="sm">{f.title}</Text>
                      <Text size="xs" c="dimmed">
                        {f.contribution != null && (f.contribution > 0 ? '+' : '') + f.contribution.toFixed(2)}
                      </Text>
                    </Group>
                    <Progress
                      value={(Math.abs(f.contribution ?? 0) / maxContribution) * 100}
                      size="sm"
                      color={(f.contribution ?? 0) >= 0 ? 'orange' : 'teal'}
                    />
                  </div>
                ))}
              </Stack>
              <Text size="xs" c="dimmed" mt="xs">
                {indicator
                  ? 'Вклад — слагаемое индекса по правилу.'
                  : 'Вклад — SHAP-оценка: насколько фактор сдвинул прогноз для этого канала (в логарифме шансов).'}
              </Text>
            </Card>
            <TrustCard card={card} />
            <ChannelHistory card={card} />
            {card.history.length > 0 && (
              <Card withBorder radius="md">
                <Text fw={600} mb="xs">
                  Прошлые прогнозы {card.channel ? 'по каналу' : 'по объекту'}
                </Text>
                <Table>
                  <Table.Tbody>
                    {card.history.map((h) => (
                      <Table.Tr key={h.id}>
                        <Table.Td>
                          <Anchor component={Link} to={`/forecasts/${h.id}`} size="sm">
                            {dayjs(h.issued_at).format('DD.MM.YYYY HH:mm')}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>{pct(h.probability)}</Table.Td>
                        <Table.Td>
                          <RiskBadge level={h.risk_level} />
                        </Table.Td>
                        <Table.Td>
                          <Badge variant="light" color={PREDICTION_OUTCOME[h.outcome].color}>
                            {PREDICTION_OUTCOME[h.outcome].label}
                          </Badge>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Card>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <ActionCard card={card} />
            {indicator && <CameraPanel prediction={card.id} />}
            <DataQuality card={card} />
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Карточки инцидентов
              </Text>
              {card.incidents.length === 0 ? (
                <Text size="sm" c="dimmed">
                  В горизонте прогноза карточек по каналу не было.
                </Text>
              ) : (
                <Stack gap="xs">
                  {card.incidents.map((i) => (
                    <div key={i.id}>
                      <Group gap={6}>
                        <RiskBadge level={i.severity} />
                        <StatusBadge status={i.status} />
                        <Anchor component={Link} to={`/incidents/${i.id}`} size="sm">
                          #{i.id} {INCIDENT_TYPE[i.type]}
                        </Anchor>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {dayjs(i.opened_at).format('DD.MM HH:mm')}
                        {i.hypothesis && ` · гипотеза: ${i.hypothesis}`}
                        {i.decision && ` · решение: ${i.decision}`}
                      </Text>
                    </div>
                  ))}
                </Stack>
              )}
            </Card>
            {card.viewed_by.length > 0 && (
              <Card withBorder radius="md">
                <Text fw={600} mb="xs">
                  Просмотрели
                </Text>
                {card.viewed_by.map((v) => (
                  <Text key={v.user} size="sm">
                    {v.name}{' '}
                    <Text span size="xs" c="dimmed">
                      {dayjs(v.first_viewed_at).format('DD.MM HH:mm')}
                    </Text>
                  </Text>
                ))}
              </Card>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
