import { BarChart } from '@mantine/charts'
import {
  Anchor,
  Badge,
  Card,
  Group,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { IconArrowRight, IconBolt, IconLayersIntersect, IconUserExclamation } from '@tabler/icons-react'
import dayjs from 'dayjs'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { INCIDENT_TYPE, RISK, TASK } from '../api/labels'
import type { Live, LiveIncident, RiskLevel } from '../api/types'
import { PriorityBadge } from './badges'

const WINDOWS = [
  { value: '10', label: '10 мин' },
  { value: '60', label: '1 ч' },
  { value: '1440', label: '24 ч' },
]

function ago(ts: string | null) {
  if (!ts) return 'сигналов ещё не было'
  const minutes = dayjs().diff(dayjs(ts), 'minute')
  if (minutes < 1) return 'последний сигнал только что'
  if (minutes < 60) return `последний сигнал ${minutes} мин назад`
  if (minutes < 60 * 24) return `последний сигнал ${Math.floor(minutes / 60)} ч назад`
  return `последний сигнал ${dayjs(ts).format('DD.MM.YYYY HH:mm')}`
}

function Stage({
  icon,
  color,
  title,
  value,
  hint,
  children,
}: {
  icon: ReactNode
  color: string
  title: string
  value: number
  hint: string
  children?: ReactNode
}) {
  return (
    <Card withBorder radius="md" h="100%">
      <Group gap="xs" mb={4} wrap="nowrap">
        <ThemeIcon variant="light" color={color} size="md">
          {icon}
        </ThemeIcon>
        <Text fw={600} size="sm">
          {title}
        </Text>
      </Group>
      <Text fz={34} fw={700} lh={1.1} c={value > 0 ? color : 'dimmed'}>
        {value.toLocaleString('ru-RU')}
      </Text>
      <Text size="xs" c="dimmed" mb="xs">
        {hint}
      </Text>
      {children}
    </Card>
  )
}

function IncidentLine({ incident }: { incident: LiveIncident }) {
  const navigate = useNavigate()
  return (
    <UnstyledButton onClick={() => navigate(`/incidents/${incident.id}`)} w="100%">
      <Group gap="xs" wrap="nowrap" py={3}>
        <PriorityBadge value={incident.priority} />
        <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
          <Text size="sm" fw={500} truncate>
            {INCIDENT_TYPE[incident.type]} · {incident.node_name}
          </Text>
          <Text size="xs" c="dimmed" truncate>
            {incident.contour === 'physical' ? 'физ.' : 'техн.'} контур · {incident.signals_count} сигн.
            {incident.channels_count ? ` · ${incident.channels_count} кан.` : ''}
            {incident.assigned_to_name ? ` · ${incident.assigned_to_name}` : ' · не взят'}
          </Text>
        </Stack>
        {incident.overdue && (
          <Tooltip label={`Реакция до ${dayjs(incident.ack_deadline).format('HH:mm')} — срок вышел`}>
            <Badge color="red" size="xs">
              просрочен
            </Badge>
          </Tooltip>
        )}
        {incident.escalation_level > 0 && (
          <Badge color="grape" size="xs">
            ×{incident.escalation_level}
          </Badge>
        )}
      </Group>
    </UnstyledButton>
  )
}

export function PipelinePanel({
  data,
  minutes,
  onMinutes,
}: {
  data: Live
  minutes: string
  onMinutes: (v: string) => void
}) {
  const { signals, episodes, action } = data
  const series = signals.series.map((s) => ({ ...s, t: dayjs(s.t).format(minutes === '1440' ? 'HH:00' : 'HH:mm') }))
  const reduction = episodes.touched ? signals.total / episodes.touched : null
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="xs">
          <Text fw={600}>Поток: сигналы → эпизоды → требуют действия</Text>
          <Text size="xs" c="dimmed">
            {ago(data.last_signal_at)}
          </Text>
        </Group>
        <SegmentedControl size="xs" value={minutes} onChange={onMinutes} data={WINDOWS} />
      </Group>
      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="xs">
        <Stage
          icon={<IconBolt size={16} />}
          color="blue"
          title="Сырые сигналы"
          value={signals.total}
          hint={`переходы в тревогу и сбой за ${WINDOWS.find((w) => w.value === minutes)?.label}: физ. ${
            signals.by_contour.physical ?? 0
          }, техн. ${signals.by_contour.technical ?? 0}`}
        >
          {series.length > 0 ? (
            <BarChart
              h={110}
              data={series}
              dataKey="t"
              type="stacked"
              withXAxis
              withYAxis={false}
              gridAxis="none"
              series={[
                { name: 'technical', label: 'Технический', color: 'blue.6' },
                { name: 'physical', label: 'Физический', color: 'red.6' },
              ]}
            />
          ) : (
            <Text size="xs" c="dimmed">
              В окне сигналов нет. Поток идёт из СМВУ через Kafka; на стенде его можно воспроизвести из архива
              (replay_journal).
            </Text>
          )}
        </Stage>
        <Stage
          icon={<IconLayersIntersect size={16} />}
          color="teal"
          title="Эпизоды"
          value={episodes.touched}
          hint={`карточек с сигналами в окне, из них новых ${episodes.new}${
            reduction && reduction > 1 ? ` · сжатие ×${reduction.toFixed(1)}` : ''
          }`}
        >
          <Stack gap={0}>
            {episodes.items.map((i) => (
              <IncidentLine key={i.id} incident={i} />
            ))}
          </Stack>
        </Stage>
        <Stage
          icon={<IconUserExclamation size={16} />}
          color="red"
          title="Требуют действия"
          value={action.unassigned}
          hint={`не приняты или никем не взяты · просрочено ${action.overdue} · эскалировано ${action.escalated} · всего открыто ${action.open}`}
        >
          <Stack gap={0}>
            {action.items.map((i) => (
              <IncidentLine key={i.id} incident={i} />
            ))}
          </Stack>
          {action.unassigned > action.items.length && (
            <Anchor component={Link} to="/incidents?status=new" size="xs" mt={4}>
              Вся очередь <IconArrowRight size={12} />
            </Anchor>
          )}
        </Stage>
      </SimpleGrid>
    </Stack>
  )
}

const LEVELS: ('critical' | 'high' | 'medium')[] = ['critical', 'high', 'medium']

export function RisksPanel({ data }: { data: Live }) {
  const navigate = useNavigate()
  const order = ['sensor_failure', 'gas', 'flood', 'fire', 'intrusion']
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text fw={600}>Активные риски</Text>
        {data.data_clock && (
          <Text size="xs" c="dimmed">
            время данных {dayjs(data.data_clock).format('DD.MM.YYYY HH:mm')}
          </Text>
        )}
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 5 }} spacing="xs">
        {order
          .filter((t) => data.risks.tasks[t])
          .map((task) => {
            const r = data.risks.tasks[task]
            return (
              <Card key={task} withBorder radius="md" padding="sm">
                <Text size="sm" fw={600}>
                  {TASK[task]}
                </Text>
                <Group gap={6} my={6}>
                  {LEVELS.map((lvl) => (
                    <Tooltip key={lvl} label={RISK[lvl].label}>
                      <Badge
                        color={RISK[lvl].color}
                        variant={lvl === 'critical' ? 'filled' : 'light'}
                        size="lg"
                        radius="sm"
                        style={{ opacity: r.levels[lvl] ? 1 : 0.35 }}
                      >
                        {r.levels[lvl]}
                      </Badge>
                    </Tooltip>
                  ))}
                </Group>
                <Stack gap={2}>
                  {r.top.slice(0, 3).map((item, i) => (
                    <UnstyledButton
                      key={i}
                      disabled={!item.prediction}
                      onClick={() => item.prediction && navigate(`/forecasts/${item.prediction}`)}
                    >
                      <Group gap={4} wrap="nowrap">
                        <Text size="xs" fw={600} w={34} c={RISK[item.risk_level as RiskLevel].color}>
                          {task === 'fire' || task === 'intrusion'
                            ? item.probability.toFixed(2)
                            : `${Math.round(item.probability * 100)}%`}
                        </Text>
                        <Text size="xs" truncate>
                          {item.channel_name ?? item.node_name}
                        </Text>
                      </Group>
                    </UnstyledButton>
                  ))}
                  {r.top.length === 0 && (
                    <Text size="xs" c="dimmed">
                      высокого риска нет
                    </Text>
                  )}
                </Stack>
              </Card>
            )
          })}
      </SimpleGrid>
      {data.risks.nodes.length > 0 && (
        <Group gap={6}>
          <Text size="xs" c="dimmed">
            Объекты с высоким риском:
          </Text>
          {data.risks.nodes.map((n) => (
            <Badge
              key={`${n.node}-${n.task}`}
              variant="light"
              color={RISK[n.risk_level].color}
              component={Link}
              to={`/map?node=${n.node}`}
              style={{ cursor: 'pointer' }}
            >
              {n.node_name} · {TASK[n.task]?.toLowerCase()}
            </Badge>
          ))}
        </Group>
      )}
      <Text size="xs" c="dimmed">
        Числа — каналы (для пожара и НСД — объекты) по уровням: критический, высокий, средний. Щелчок по строке открывает
        карточку прогноза.
      </Text>
    </Stack>
  )
}

