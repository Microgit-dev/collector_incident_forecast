import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconMap2, IconTrophy, IconX } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { INCIDENT_TYPE, WO_STATUS } from '../api/labels'
import type { Live, MyMetrics, Workspace, WorkspaceKpi, WorkspaceOrder, WorkOrderStatus } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge } from '../components/badges'
import { useCompleteOrder } from '../components/CompleteOrder'
import { IncidentLine, RisksPanel } from '../components/LivePanels'
import { SchemeLegend, SchemeMap, SegmentDetails, type SegmentProps } from '../components/SchemeMap'
import { useRoutes } from '../components/useScheme'

const DISPATCHER = ['unit_dispatcher', 'ods_dispatcher']
// Следующий шаг заявки для бригады прямо с рабочего места
const TECH_NEXT: Partial<Record<WorkOrderStatus, { status: WorkOrderStatus; label: string }>> = {
  submitted: { status: 'in_progress', label: 'Взять в работу' },
  in_progress: { status: 'done', label: 'Выполнена' },
}
// без системы заявок заказчика утверждённую заявку бригада берёт сразу
const TAKE = { status: 'in_progress' as WorkOrderStatus, label: 'Взять в работу' }

function Kpi({ kpi }: { kpi: WorkspaceKpi }) {
  const body = (
    <Card withBorder padding="sm" radius="md" h="100%">
      <Text size="sm" c="dimmed">
        {kpi.label}
      </Text>
      <Text fz={30} fw={700} lh={1.2} c={kpi.value > 0 && kpi.color ? kpi.color : undefined}>
        {kpi.value.toLocaleString('ru-RU')}
      </Text>
      {kpi.hint && (
        <Text size="xs" c="dimmed">
          {kpi.hint}
        </Text>
      )}
    </Card>
  )
  return kpi.to ? (
    <Link to={kpi.to} style={{ textDecoration: 'none', color: 'inherit' }}>
      {body}
    </Link>
  ) : (
    body
  )
}

function Panel({ title, to, tour, children }: { title: string; to?: string; tour?: string; children: React.ReactNode }) {
  return (
    <Card withBorder radius="md" h="100%" data-tour={tour}>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>{title}</Text>
        {to && (
          <Anchor component={Link} to={to} size="xs">
            Все
          </Anchor>
        )}
      </Group>
      {children}
    </Card>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <Text size="sm" c="dimmed">
      {children}
    </Text>
  )
}

function OrderLine({ order, action }: { order: WorkspaceOrder; action?: React.ReactNode }) {
  return (
    <Stack gap={4} py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
      <Text size="sm" fw={500} lineClamp={2}>
        {order.title}
      </Text>
      <Text size="xs" c={order.overdue ? 'red' : 'dimmed'}>
        {order.number} · {order.node} · срок {dayjs(order.due_at).format('DD.MM HH:mm')}
        {order.overdue ? ' · просрочена' : ''}
        {order.created_by ? ` · автор ${order.created_by}` : ''}
      </Text>
      <Group gap="xs" justify="space-between">
        <Group gap={6}>
          <RiskBadge level={order.priority} />
          <Badge variant="light" color={WO_STATUS[order.status].color} size="sm">
            {WO_STATUS[order.status].label}
          </Badge>
        </Group>
        {action}
      </Group>
    </Stack>
  )
}

function EngineerPanel({ data }: { data: Workspace }) {
  const due = data.lists.maintenance_due ?? []
  const recs = data.lists.maintenance_recommendations ?? []
  return (
    <Panel title="Просрочено и не в плане" to="/maintenance">
      {due.length ? (
        <Stack gap={0}>
          {due.map((r) => (
            <Stack key={r.id} gap={2} py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
              <Text size="sm" fw={500} lineClamp={1}>
                {r.name}
              </Text>
              <Text size="xs" c="red">
                {r.node_name} · ТО просрочено на {r.overdue_days} сут
                {r.condition_display ? ` · ${r.condition_display.toLowerCase()}` : ''}
              </Text>
            </Stack>
          ))}
        </Stack>
      ) : (
        <Empty>Просроченного ТО вне плана нет.</Empty>
      )}
      {recs.length > 0 && (
        <>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase" mt="md" mb={4}>
            Рекомендации по состоянию
          </Text>
          {recs.map((r) => (
            <Group key={r.id} gap={6} wrap="nowrap" py={4}>
              <RiskBadge level={r.priority} />
              <Text size="sm" lineClamp={1} style={{ flex: 1 }}>
                {r.work_type_display} · {r.equipment_name ?? r.channel_name ?? r.node_name}
              </Text>
            </Group>
          ))}
        </>
      )}
    </Panel>
  )
}

function DispatcherPanel({ live }: { live?: Live }) {
  const items = live?.action.items ?? []
  return (
    <Panel title="Требуют действия" to="/incidents">
      {live && (
        <Text size="xs" c="dimmed" mb="xs">
          За {live.minutes} мин: сигналов {live.signals.total} → эпизодов {live.episodes.touched} → ждут диспетчера{' '}
          {live.action.unassigned}
          {live.action.overdue ? `, просрочено ${live.action.overdue}` : ''}. Поток по минутам — в оперативной
          обстановке.
        </Text>
      )}
      {items.length ? (
        <Stack gap={0}>
          {items.slice(0, 8).map((i) => (
            <IncidentLine key={i.id} incident={i} />
          ))}
        </Stack>
      ) : (
        <Empty>Все карточки приняты — очередь пуста.</Empty>
      )}
    </Panel>
  )
}

function MyMetricsCard() {
  const q = useQuery({ queryKey: ['staff-me'], queryFn: () => api<MyMetrics>('/analytics/staff/me/'), staleTime: 60_000 })
  const me = q.data?.me
  if (!q.data || !me) return null
  const c = q.data.colleagues
  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)} %`)
  const item = (label: string, value: string, peer: string | null, hint?: string) => (
    <Tooltip label={hint ?? label} disabled={!hint}>
      <Stack gap={0}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Text fw={700} fz="lg">
          {value}
        </Text>
        {peer !== null && (
          <Text size="xs" c="dimmed">
            коллеги: {peer}
          </Text>
        )}
      </Stack>
    </Tooltip>
  )
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <IconTrophy size={18} color={me.rank === 1 ? 'var(--mantine-color-yellow-6)' : 'var(--mantine-color-dimmed)'} />
          <Text fw={600}>Мои показатели</Text>
          <Text size="xs" c="dimmed">
            {dayjs(q.data.period.from).format('DD.MM')} — {dayjs(q.data.period.to).subtract(1, 'day').format('DD.MM.YYYY')}
          </Text>
        </Group>
        <Anchor component={Link} to="/analytics" size="xs">
          Рейтинг смены
        </Anchor>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 5 }}>
        {item('Место', me.rank ? `${me.rank} из ${q.data.rank_of}` : '—', null, 'Рейтинг «кто первый» среди диспетчеров зоны')}
        {item('Первым откликнулся', String(me.responded), c.responded === null ? null : String(c.responded))}
        {item('Доля карточек зоны', pct(me.responded_share), c.responded_share === null ? null : pct(c.responded_share))}
        {item(
          'До отклика, медиана',
          me.response_median === null ? '—' : `${me.response_median} мин`,
          c.response_median === null ? null : `${c.response_median} мин`,
        )}
        {item(
          'Качество решений',
          pct(me.quality),
          c.quality === null ? null : pct(c.quality),
          'Доля физических угроз, закрытых как ложные, после которых угроза не повторилась в течение 6 часов',
        )}
      </SimpleGrid>
      {me.races > 0 && (
        <Text size="xs" c="dimmed" mt="xs">
          Гонки за карточку: выиграно {me.races_won} из {me.races}
          {me.takeovers_lost ? ` · перехвачено руководителем ${me.takeovers_lost}` : ''}
        </Text>
      )}
    </Card>
  )
}

function HeadPanel({ data }: { data: Workspace }) {
  const navigate = useNavigate()
  const escalated = data.lists.escalated ?? []
  return (
    <Panel title="Эскалированы" to="/incidents">
      {escalated.length ? (
        <Stack gap={0}>
          {escalated.map((i) => (
            <UnstyledButton key={i.id} onClick={() => navigate(`/incidents/${i.id}`)} py={4}>
              <Group gap="xs" wrap="nowrap">
                <RiskBadge level={i.severity} />
                <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
                  <Text size="sm" fw={500} truncate>
                    {INCIDENT_TYPE[i.type]} · {i.node}
                  </Text>
                  <Text size="xs" c="dimmed" truncate>
                    открыта {dayjs(i.opened_at).format('DD.MM HH:mm')} · приоритет {i.priority}
                  </Text>
                </Stack>
                <Badge color="grape" size="sm">
                  ×{i.escalation_level}
                </Badge>
              </Group>
            </UnstyledButton>
          ))}
        </Stack>
      ) : (
        <Empty>Эскалаций нет: смены реагируют в срок.</Empty>
      )}
    </Panel>
  )
}

function ApprovalsPanel({ data }: { data: Workspace }) {
  const approvals = data.lists.approvals ?? []
  return (
    <Panel title="Заявки на утверждение" to="/workorders" tour="approvals">
      {approvals.length ? (
        <Stack gap={0}>
          {approvals.map((o) => (
            <OrderLine key={o.id} order={o} />
          ))}
        </Stack>
      ) : (
        <Empty>Черновиков от диспетчеров нет.</Empty>
      )}
    </Panel>
  )
}

function AnalystPanel({ data }: { data: Workspace }) {
  const weak = data.lists.weak_channels ?? []
  return (
    <Panel title="Проблемные каналы" to="/data-health">
      {weak.length ? (
        <Table>
          <Table.Tbody>
            {weak.map((c) => (
              <Table.Tr key={c.channel}>
                <Table.Td>
                  <Text size="sm" truncate>
                    {c.name}
                  </Text>
                  <Text size="xs" c="dimmed" truncate>
                    {c.node}
                  </Text>
                </Table.Td>
                <Table.Td w={90}>
                  {c.silent ? (
                    <Tooltip
                      label={
                        c.last_seen_at ? `Последнее сообщение ${dayjs(c.last_seen_at).format('DD.MM HH:mm')}` : 'Не выходил на связь'
                      }
                    >
                      <Badge color="dark">молчит</Badge>
                    </Tooltip>
                  ) : (
                    <Badge color={c.score < 40 ? 'red' : 'orange'} variant="light">
                      {c.score}
                    </Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : (
        <Empty>Все каналы зоны с Data Health от 40 и на связи.</Empty>
      )}
    </Panel>
  )
}

function TechnicianPanel({ data }: { data: Workspace }) {
  const client = useQueryClient()
  const phone = useMediaQuery('(max-width: 36em)')
  const orders = data.lists.my_orders ?? []
  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: WorkOrderStatus }) =>
      api(`/workorders/items/${id}/transition/`, { method: 'POST', body: { status } }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['workspace'] })
      client.invalidateQueries({ queryKey: ['scheme'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const complete = useCompleteOrder(() => {
    client.invalidateQueries({ queryKey: ['workspace'] })
    client.invalidateQueries({ queryKey: ['scheme'] })
  })
  return (
    <Panel title="Мои заявки" to="/workorders">
      {complete.modal}
      {orders.length ? (
        <Stack gap={0}>
          {orders.map((o) => {
            const next = o.status === 'approved' && o.direct ? TAKE : TECH_NEXT[o.status]
            return (
              <OrderLine
                key={o.id}
                order={o}
                action={
                  next && (
                    // бригада жмёт с телефона на объекте — кнопка под палец (не меньше 36 px)
                    <Button
                      size="sm"
                      fullWidth={phone}
                      loading={move.isPending && move.variables?.id === o.id}
                      onClick={() =>
                        next.status === 'done' ? complete.open(o.id) : move.mutate({ id: o.id, status: next.status })
                      }
                    >
                      {next.label}
                    </Button>
                  )
                }
              />
            )
          })}
        </Stack>
      ) : (
        <Empty>Назначенных заявок нет.</Empty>
      )}
    </Panel>
  )
}

export function WorkspacePage() {
  const { user } = useAuth()
  const [role, setRole] = useState<string | null>(null)
  const [selected, setSelected] = useState<SegmentProps | null>(null)
  const workspace = useQuery({
    queryKey: ['workspace', role],
    queryFn: () => api<Workspace>('/analytics/workspace/', { query: role ? { role } : {} }),
    refetchInterval: 30_000,
  })
  const current = workspace.data?.role
  const withLive = Boolean(current && (DISPATCHER.includes(current) || ['head', 'observer', 'analyst'].includes(current)))
  const live = useQuery({
    queryKey: ['live', '10'],
    queryFn: () => api<Live>('/analytics/live/', { query: { minutes: 10 } }),
    refetchInterval: 15_000,
    enabled: withLive,
  })
  const data = workspace.data
  const layers = {
    objects: true,
    states: true,
    incidents: Boolean(data?.map.incidents),
    workorders: Boolean(data?.map.workorders),
  }
  const { routes } = useRoutes(null, 'all', layers.workorders)

  if (!data) return <Loader />
  const selectedRoute = selected ? routes.find((r) => r.complex === selected.complex) : undefined
  const dispatcher = DISPATCHER.includes(data.role)

  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <div>
          <Title order={3}>Рабочее место · {data.title}</Title>
          <Text size="sm" c="dimmed">
            {user?.scope_node_name ?? 'Все объекты'} — {data.description.charAt(0).toLowerCase() + data.description.slice(1)}
          </Text>
        </div>
        {data.roles.length > 1 && (
          <SegmentedControl
            value={data.role}
            onChange={(v) => {
              setSelected(null)
              setRole(v)
            }}
            data={data.roles.map((r) => ({ value: r.code, label: r.title }))}
          />
        )}
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 3, lg: data.kpis.length }} data-tour="kpis">
        {data.kpis.map((k) => (
          <Kpi key={k.key} kpi={k} />
        ))}
      </SimpleGrid>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <Card withBorder radius="md" data-tour="scheme">
            <Group justify="space-between" mb={4}>
              <Text fw={600}>Схема зоны ответственности</Text>
              <Tooltip label="Схема со всеми слоями и фильтрами">
                <ActionIcon component={Link} to="/map" variant="default" aria-label="Открыть схему">
                  <IconMap2 size={16} />
                </ActionIcon>
              </Tooltip>
            </Group>
            <div style={{ marginBottom: 8 }}>
              <SchemeLegend colorBy={data.map.color_by} layers={layers} />
            </div>
            <SchemeMap
              layers={layers}
              colorBy={data.map.color_by}
              selected={selected}
              onSelect={setSelected}
              labelWidth={150}
            />
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 4 }} data-tour="side">
          {selected ? (
            <Stack gap={4}>
              <Group justify="flex-end">
                <ActionIcon variant="subtle" onClick={() => setSelected(null)} aria-label="Закрыть">
                  <IconX size={16} />
                </ActionIcon>
              </Group>
              <SegmentDetails segment={selected} route={selectedRoute} />
            </Stack>
          ) : dispatcher ? (
            <DispatcherPanel live={live.data} />
          ) : data.role === 'head' ? (
            <HeadPanel data={data} />
          ) : data.role === 'analyst' ? (
            <AnalystPanel data={data} />
          ) : data.role === 'technician' ? (
            <TechnicianPanel data={data} />
          ) : data.role === 'maintenance_engineer' ? (
            <EngineerPanel data={data} />
          ) : (
            <Panel title="Участок схемы">
              <Empty>Щелчок по участку схемы покажет каналы, их состояние и риск.</Empty>
            </Panel>
          )}
        </Grid.Col>
      </Grid>

      {dispatcher && <MyMetricsCard />}
      {data.role === 'head' && <ApprovalsPanel data={data} />}
      {withLive && live.data && <RisksPanel data={live.data} />}
    </Stack>
  )
}
