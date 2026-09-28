/**
 * План ТО — рабочий раздел инженера ТО (ТЗ §3 «поддержка планирования профилактических работ», §8):
 * что подходит по регламенту, что рекомендует система по состоянию, что уже запланировано.
 * «В план» создаёт черновик заявки на выбранную дату; дальше — утверждение руководителем и бригада.
 */
import { BarChart } from '@mantine/charts'
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Pagination,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { notifications } from '@mantine/notifications'
import { IconCalendarPlus, IconFileTypeXls } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, download } from '../api/client'
import { CONDITION, RISK, WO_STATUS, WORK_TYPE } from '../api/labels'
import type { MaintenanceDue, MaintenancePlan, MaintenanceRec, RiskLevel, ScheduleDue } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge } from '../components/badges'

type Target =
  | { kind: 'equipment'; row: MaintenanceDue }
  | { kind: 'recommendation'; row: MaintenanceRec }
  | { kind: 'line'; row: ScheduleDue }

function Kpi({ label, value, color, hint }: { label: string; value: number; color?: string; hint?: string }) {
  return (
    <Card withBorder padding="sm" radius="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={28} fw={700} lh={1.2} c={value > 0 ? color : undefined}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
}

export function ConditionBadge({ condition }: { condition: string }) {
  if (!condition)
    return (
      <Text size="xs" c="dimmed">
        не оценивалось
      </Text>
    )
  const c = CONDITION[condition]
  return (
    <Badge variant="light" color={c?.color ?? 'gray'} size="sm">
      {c?.label ?? condition}
    </Badge>
  )
}

function ScheduleModal({ target, onClose }: { target: Target | null; onClose: () => void }) {
  const client = useQueryClient()
  // предлагаемая дата — срок по регламенту или рекомендации, но не раньше завтрашнего дня
  const tomorrow = dayjs().add(1, 'day')
  const due =
    target?.kind === 'equipment'
      ? target.row.due
      : target?.kind === 'recommendation'
        ? target.row.due_date
        : target?.kind === 'line'
          ? (target.row.date ??
            dayjs()
              .month(target.row.month - 1)
              .date(15)
              .format('YYYY-MM-DD'))
          : null
  const suggested = target ? (due && dayjs(due).isAfter(tomorrow) ? dayjs(due) : tomorrow).format('YYYY-MM-DD') : null
  const [date, setDate] = useState<string | null>(null)
  const [work, setWork] = useState<string | null>(null)
  const [priority, setPriority] = useState<string>('medium')
  const save = useMutation({
    mutationFn: () =>
      api<{ number: string }>('/workorders/maintenance/schedule/', {
        method: 'POST',
        body:
          target?.kind === 'equipment'
            ? { equipment: target.row.id, date: date ?? suggested, work_type: work ?? target.row.work_type, priority }
            : target?.kind === 'line'
              ? { schedule_line: target.row.id, date: date ?? suggested }
              : { recommendation: target?.row.id, date: date ?? suggested },
      }),
    onSuccess: (o) => {
      notifications.show({
        color: 'teal',
        message: `В плане: черновик заявки ${o.number} — ждёт утверждения руководителем`,
      })
      void client.invalidateQueries({ queryKey: ['maintenance-plan'] })
      void client.invalidateQueries({ queryKey: ['workorders'] })
      setDate(null)
      setWork(null)
      onClose()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  if (!target) return null
  const title =
    target.kind === 'equipment'
      ? target.row.name
      : target.kind === 'line'
        ? `${target.row.work}: ${target.row.type_name} — ${target.row.object}`
        : `${target.row.work_type_display} — ${target.row.node_name}`
  return (
    <Modal opened onClose={onClose} title="Поставить в план">
      <Stack>
        <Text size="sm" fw={500}>
          {title}
        </Text>
        <DatePickerInput
          label="Дата работ"
          value={date ?? suggested}
          onChange={(v) => setDate(v as string | null)}
          valueFormat="DD.MM.YYYY"
          minDate={dayjs().format('YYYY-MM-DD')}
        />
        {target.kind === 'equipment' && (
          <>
            <Select
              label="Вид работ"
              data={Object.entries(WORK_TYPE).map(([value, label]) => ({ value, label }))}
              value={work ?? target.row.work_type}
              onChange={setWork}
            />
            <Select
              label="Приоритет"
              data={(['low', 'medium', 'high', 'critical'] as RiskLevel[]).map((v) => ({
                value: v,
                label: RISK[v].label,
              }))}
              value={priority}
              onChange={(v) => setPriority(v ?? 'medium')}
            />
          </>
        )}
        <Text size="xs" c="dimmed">
          Создаётся черновик заявки на эту дату. Руководитель утверждает его, исполнитель — бригада зоны объекта.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button leftSection={<IconCalendarPlus size={16} />} loading={save.isPending} onClick={() => save.mutate()}>
            В план
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

const PAGE = 25

function DueTable({
  rows: all,
  onPlan,
  canPlan,
}: {
  rows: MaintenanceDue[]
  onPlan: (r: MaintenanceDue) => void
  canPlan: boolean
}) {
  const [page, setPage] = useState(1)
  if (!all.length)
    return (
      <Text size="sm" c="dimmed">
        Нет единиц в этом горизонте.
      </Text>
    )
  const rows = all.slice((page - 1) * PAGE, page * PAGE)
  return (
    <Stack gap="xs">
      <Table.ScrollContainer minWidth={900}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Срок ТО</Table.Th>
              <Table.Th>Оборудование</Table.Th>
              <Table.Th>Объект</Table.Th>
              <Table.Th>Последнее ТО</Table.Th>
              <Table.Th>Состояние</Table.Th>
              <Table.Th>План</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>
                  <Text size="sm" c={r.overdue_days ? 'red' : undefined} fw={r.overdue_days ? 600 : undefined}>
                    {r.due ? dayjs(r.due).format('DD.MM.YYYY') : '—'}
                  </Text>
                  {r.overdue_days > 0 && (
                    <Text size="xs" c="red">
                      просрочено на {r.overdue_days} сут
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{r.name}</Text>
                  <Text size="xs" c="dimmed">
                    {r.kind_display}
                    {r.inventory_number && ` · ${r.inventory_number}`}
                    {r.interval_days && ` · раз в ${r.interval_days} сут`}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{r.node_name}</Text>
                  {r.picket != null && (
                    <Text size="xs" c="dimmed">
                      ПК {r.picket}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>{r.last_maintenance_at ? dayjs(r.last_maintenance_at).format('DD.MM.YYYY') : '—'}</Table.Td>
                <Table.Td>
                  <ConditionBadge condition={r.condition} />
                </Table.Td>
                <Table.Td>
                  {r.planned ? (
                    <Stack gap={0}>
                      <Badge variant="light" color={WO_STATUS[r.planned.status].color} size="sm">
                        {r.planned.number}
                      </Badge>
                      <Text size="xs" c="dimmed">
                        на {dayjs(r.planned.due_at).format('DD.MM.YYYY')}
                      </Text>
                    </Stack>
                  ) : (
                    canPlan && (
                      <Button size="compact-xs" leftSection={<IconCalendarPlus size={12} />} onClick={() => onPlan(r)}>
                        В план
                      </Button>
                    )
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {all.length > PAGE && (
        <Group justify="center">
          <Pagination size="sm" total={Math.ceil(all.length / PAGE)} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  )
}

export function MaintenancePage() {
  const { can } = useAuth()
  const canPlan = can('workorders.add_workorder')
  const [horizon, setHorizon] = useState('90')
  const [target, setTarget] = useState<Target | null>(null)
  const plan = useQuery({
    queryKey: ['maintenance-plan', horizon],
    queryFn: () => api<MaintenancePlan>('/workorders/maintenance/plan/', { query: { horizon } }),
  })
  const data = plan.data
  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <div>
          <Title order={3}>План технического обслуживания</Title>
          <Text size="sm" c="dimmed">
            Регламентные сроки по реестру оборудования, рекомендации системы по прогнозам и фактическому состоянию,
            запланированные работы зоны.
          </Text>
        </div>
        <Group gap="xs">
          <SegmentedControl
            size="xs"
            value={horizon}
            onChange={setHorizon}
            data={[
              { value: '30', label: '30 дней' },
              { value: '90', label: '90 дней' },
              { value: '180', label: '180 дней' },
            ]}
          />
          <Button
            size="xs"
            variant="light"
            leftSection={<IconFileTypeXls size={14} />}
            onClick={() =>
              void download(`/workorders/maintenance/plan/?export=xlsx&horizon=${horizon}`, 'plan_to.xlsx').catch((e) =>
                notifications.show({ color: 'red', message: (e as Error).message }),
              )
            }
          >
            План в XLSX
          </Button>
        </Group>
      </Group>

      {plan.isLoading || !data ? (
        <Loader />
      ) : (
        <>
          <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
            <Kpi
              label="ТО просрочено"
              value={data.kpis.overdue}
              color="red"
              hint={`не в плане: ${data.kpis.unplanned_overdue}`}
            />
            <Kpi label="ТО в ближайшие 30 дней" value={data.kpis.due_30} color="orange" />
            <Kpi label="Рекомендации по состоянию" value={data.kpis.recommendations} color="blue" />
            <Kpi label="Требует ремонта" value={data.kpis.bad_condition} color="grape" hint="по последнему осмотру" />
            <Kpi label="Работ в плане" value={data.kpis.planned} color="teal" />
            <Card withBorder padding="sm" radius="md">
              <Text size="sm" c="dimmed">
                Нагрузка по неделям
              </Text>
              {data.weeks.length ? (
                <BarChart
                  h={60}
                  data={data.weeks.map((w) => ({ week: dayjs(w.week).format('DD.MM'), orders: w.orders }))}
                  dataKey="week"
                  series={[{ name: 'orders', label: 'работ', color: 'teal.6' }]}
                  withYAxis={false}
                  gridAxis="none"
                  withXAxis={false}
                />
              ) : (
                <Text size="xs" c="dimmed">
                  нет запланированных работ
                </Text>
              )}
            </Card>
          </SimpleGrid>

          <Card withBorder radius="md">
            <Tabs defaultValue="due" keepMounted={false}>
              <Tabs.List>
                <Tabs.Tab value="due">По регламенту · {data.due.length}</Tabs.Tab>
                <Tabs.Tab value="condition">
                  По состоянию · {data.recommendations.length + data.bad_condition.length}
                </Tabs.Tab>
                <Tabs.Tab value="schedule">По графику · {data.schedule_due.length}</Tabs.Tab>
                <Tabs.Tab value="planned">Запланировано · {data.planned.length}</Tabs.Tab>
              </Tabs.List>

              <Tabs.Panel value="due" pt="md">
                <Text size="xs" c="dimmed" mb="xs">
                  Срок = последнее ТО + регламентный интервал из реестра. Сначала — самые давние.
                </Text>
                <DueTable rows={data.due} canPlan={canPlan} onPlan={(row) => setTarget({ kind: 'equipment', row })} />
              </Tabs.Panel>

              <Tabs.Panel value="condition" pt="md">
                <Stack>
                  <Text size="sm" fw={600}>
                    Рекомендации системы
                  </Text>
                  <Text size="xs" c="dimmed">
                    Из прогнозов отказа датчиков, газа и подтопления, Data Health каналов и осмотров. Раз в сутки;
                    исправное состояние после осмотра снимает рекомендацию.
                  </Text>
                  {data.recommendations.length ? (
                    <Table.ScrollContainer minWidth={800}>
                      <Table striped>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th>Срок</Table.Th>
                            <Table.Th>Приоритет</Table.Th>
                            <Table.Th>Работы</Table.Th>
                            <Table.Th>Обоснование</Table.Th>
                            <Table.Th />
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {data.recommendations.map((r) => (
                            <Table.Tr key={r.id}>
                              <Table.Td>{dayjs(r.due_date).format('DD.MM.YYYY')}</Table.Td>
                              <Table.Td>
                                <RiskBadge level={r.priority} />
                              </Table.Td>
                              <Table.Td>
                                <Text size="sm">{r.work_type_display}</Text>
                                <Text size="xs" c="dimmed">
                                  {r.node_name}
                                  {(r.equipment_name ?? r.channel_name) && ` · ${r.equipment_name ?? r.channel_name}`}
                                </Text>
                              </Table.Td>
                              <Table.Td maw={380}>
                                <Text size="xs">{r.rationale}</Text>
                              </Table.Td>
                              <Table.Td>
                                {canPlan && (
                                  <Button
                                    size="compact-xs"
                                    leftSection={<IconCalendarPlus size={12} />}
                                    onClick={() => setTarget({ kind: 'recommendation', row: r })}
                                  >
                                    В план
                                  </Button>
                                )}
                              </Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </Table.ScrollContainer>
                  ) : (
                    <Text size="sm" c="dimmed">
                      Новых рекомендаций нет.
                    </Text>
                  )}
                  <Text size="sm" fw={600} mt="sm">
                    Оборудование в неудовлетворительном состоянии
                  </Text>
                  <DueTable
                    rows={data.bad_condition}
                    canPlan={canPlan}
                    onPlan={(row) => setTarget({ kind: 'equipment', row })}
                  />
                </Stack>
              </Tabs.Panel>

              <Tabs.Panel value="schedule" pt="md">
                <Text size="xs" c="dimmed" mb="xs">
                  Работы утверждённых графиков ТО и ТР и ППР на текущий и следующий месяц (раздел «Графики ТО и ППР»).
                </Text>
                {data.schedule_due.length ? (
                  <Table.ScrollContainer minWidth={800}>
                    <Table striped>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Месяц</Table.Th>
                          <Table.Th>Работа</Table.Th>
                          <Table.Th>Объект</Table.Th>
                          <Table.Th>Вид оборудования</Table.Th>
                          <Table.Th>План</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {data.schedule_due.map((r) => (
                          <Table.Tr key={r.id}>
                            <Table.Td>
                              {dayjs()
                                .month(r.month - 1)
                                .format('MMMM')}
                            </Table.Td>
                            <Table.Td>
                              <Badge
                                size="sm"
                                variant="light"
                                color={r.work.includes('ТР') ? 'grape' : r.kind === 'ppr' ? 'orange' : 'teal'}
                              >
                                {r.work}
                              </Badge>
                            </Table.Td>
                            <Table.Td>{r.object}</Table.Td>
                            <Table.Td>
                              <Text size="sm">{r.type_name}</Text>
                              <Text size="xs" c="dimmed">
                                {r.quantity} {r.unit}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              {r.planned ? (
                                <Badge variant="light" color={WO_STATUS[r.planned.status].color} size="sm">
                                  {r.planned.number}
                                </Badge>
                              ) : (
                                canPlan && (
                                  <Button
                                    size="compact-xs"
                                    leftSection={<IconCalendarPlus size={12} />}
                                    onClick={() => setTarget({ kind: 'line', row: r })}
                                  >
                                    В план
                                  </Button>
                                )
                              )}
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                ) : (
                  <Text size="sm" c="dimmed">
                    Утверждённых графиков с работами на ближайшие месяцы нет.{' '}
                    <Anchor component={Link} to="/schedules" size="sm">
                      Графики ТО и ППР →
                    </Anchor>
                  </Text>
                )}
              </Tabs.Panel>

              <Tabs.Panel value="planned" pt="md">
                {data.planned.length ? (
                  <Table.ScrollContainer minWidth={800}>
                    <Table striped>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Дата</Table.Th>
                          <Table.Th>Заявка</Table.Th>
                          <Table.Th>Объект</Table.Th>
                          <Table.Th>Статус</Table.Th>
                          <Table.Th>Исполнитель</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {data.planned.map((o) => (
                          <Table.Tr key={o.id}>
                            <Table.Td>
                              <Text size="sm" c={dayjs(o.due_at).isBefore(dayjs()) ? 'red' : undefined}>
                                {dayjs(o.due_at).format('DD.MM.YYYY')}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Text size="sm">{o.title}</Text>
                              <Text size="xs" c="dimmed">
                                {o.number}
                              </Text>
                            </Table.Td>
                            <Table.Td>{o.node_name}</Table.Td>
                            <Table.Td>
                              <Badge variant="light" color={WO_STATUS[o.status].color} size="sm">
                                {WO_STATUS[o.status].label}
                              </Badge>
                            </Table.Td>
                            <Table.Td>{o.assignee_name ?? '—'}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                ) : (
                  <Text size="sm" c="dimmed">
                    Запланированных работ нет.
                  </Text>
                )}
                <Anchor component={Link} to="/workorders" size="xs" mt="xs" display="block">
                  Все заявки →
                </Anchor>
              </Tabs.Panel>
            </Tabs>
          </Card>
        </>
      )}
      <ScheduleModal target={target} onClose={() => setTarget(null)} />
    </Stack>
  )
}
