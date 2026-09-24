import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Pagination,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconClipboardPlus, IconRefresh } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type Page } from '../api/client'
import type { RiskLevel } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge } from '../components/badges'

interface Recommendation {
  id: number
  node: number
  node_name: string
  channel_name: string | null
  equipment_name: string | null
  work_type: string
  work_type_display: string
  priority: RiskLevel
  due_date: string
  rationale: string
  status: 'new' | 'accepted' | 'rejected' | 'done'
  workorders: { id: number; number: string; status: string }[]
  created_at: string
}

interface WorkOrder {
  id: number
  number: string
  status: WorkOrderStatus
  node_name: string
  incident: number | null
  recommendation: number | null
  work_type: string
  priority: RiskLevel
  title: string
  description: string
  due_at: string
  assignee_name: string | null
  created_at: string
}

type WorkOrderStatus = 'draft' | 'approved' | 'submitted' | 'in_progress' | 'done' | 'cancelled'

const WO_STATUS: Record<WorkOrderStatus, { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'gray' },
  approved: { label: 'Утверждена', color: 'blue' },
  submitted: { label: 'Передана в систему заявок', color: 'indigo' },
  in_progress: { label: 'В работе', color: 'orange' },
  done: { label: 'Выполнена', color: 'teal' },
  cancelled: { label: 'Отменена', color: 'gray' },
}
// Следующий шаг жизненного цикла и право, которое для него нужно
const NEXT: Partial<Record<WorkOrderStatus, { status: WorkOrderStatus; label: string; perm: string }>> = {
  draft: { status: 'approved', label: 'Утвердить', perm: 'workorders.approve_workorder' },
  approved: { status: 'submitted', label: 'Передать в систему заявок', perm: 'workorders.change_workorder' },
  submitted: { status: 'in_progress', label: 'Взять в работу', perm: 'workorders.execute_workorder' },
  in_progress: { status: 'done', label: 'Выполнена', perm: 'workorders.execute_workorder' },
}
const REC_STATUS = {
  new: { label: 'Новая', color: 'blue' },
  accepted: { label: 'Принята', color: 'teal' },
  rejected: { label: 'Отклонена', color: 'gray' },
  done: { label: 'Выполнена', color: 'teal' },
} as const
const PAGE = 25

function Recommendations() {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<string | null>('new')
  const [priority, setPriority] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const filters = { ...(status ? { status } : {}), ...(priority ? { priority } : {}) }
  const recs = useQuery({
    queryKey: ['recommendations', filters, page],
    queryFn: () =>
      api<Page<Recommendation>>('/workorders/recommendations/', {
        query: { ...filters, page, page_size: PAGE, ordering: 'due_date' },
      }),
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
    void queryClient.invalidateQueries({ queryKey: ['workorders'] })
  }
  const draft = useMutation({
    mutationFn: (id: number) =>
      api<WorkOrder>(`/workorders/recommendations/${id}/draft/`, { method: 'POST', body: {} }),
    onSuccess: (o) => {
      notifications.show({ color: 'teal', message: `Создан черновик заявки ${o.number}` })
      refresh()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const reject = useMutation({
    mutationFn: (id: number) =>
      api(`/workorders/recommendations/${id}/`, { method: 'PATCH', body: { status: 'rejected' } }),
    onSuccess: refresh,
  })
  const generate = useMutation({
    mutationFn: () =>
      api<{ created: number; updated: number }>('/workorders/recommendations/generate/', { method: 'POST', body: {} }),
    onSuccess: (r) => {
      notifications.show({ color: 'teal', message: `Новых рекомендаций: ${r.created}, обновлено: ${r.updated}` })
      refresh()
    },
  })

  return (
    <Stack>
      <Group justify="space-between" wrap="wrap">
        <Group gap="xs">
          <Select
            size="xs"
            placeholder="Статус"
            data={Object.entries(REC_STATUS).map(([value, v]) => ({ value, label: v.label }))}
            value={status}
            onChange={(v) => {
              setStatus(v)
              setPage(1)
            }}
            clearable
            w={150}
          />
          <Select
            size="xs"
            placeholder="Приоритет"
            data={[
              { value: 'critical', label: 'Критический' },
              { value: 'high', label: 'Высокий' },
              { value: 'medium', label: 'Средний' },
              { value: 'low', label: 'Низкий' },
            ]}
            value={priority}
            onChange={(v) => {
              setPriority(v)
              setPage(1)
            }}
            clearable
            w={150}
          />
        </Group>
        {can('workorders.add_workorder') && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconRefresh size={14} />}
            loading={generate.isPending}
            onClick={() => generate.mutate()}
          >
            Обновить рекомендации
          </Button>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Рекомендации строятся раз в сутки из прогнозов (отказ датчика, газ, подтопление), качества данных каналов и
        просрочек ТО по реестру оборудования. Черновик заявки создаётся одной кнопкой и дальше проходит утверждение.
      </Text>
      {recs.isLoading ? (
        <Loader />
      ) : (
        <Table.ScrollContainer minWidth={960}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Срок</Table.Th>
                <Table.Th>Приоритет</Table.Th>
                <Table.Th>Работы</Table.Th>
                <Table.Th>Объект</Table.Th>
                <Table.Th>Обоснование</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {recs.data?.results.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Text size="sm" c={dayjs(r.due_date).isBefore(dayjs(), 'day') ? 'red' : undefined}>
                      {dayjs(r.due_date).format('DD.MM.YYYY')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <RiskBadge level={r.priority} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{r.work_type_display}</Text>
                    <Text size="xs" c="dimmed">
                      {r.channel_name ?? r.equipment_name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{r.node_name}</Text>
                  </Table.Td>
                  <Table.Td maw={380}>
                    <Text size="xs">{r.rationale}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color={REC_STATUS[r.status].color}>
                      {REC_STATUS[r.status].label}
                    </Badge>
                    {r.workorders.map((w) => (
                      <Text key={w.id} size="xs" c="dimmed">
                        заявка {w.number}
                      </Text>
                    ))}
                  </Table.Td>
                  <Table.Td>
                    {r.status === 'new' && can('workorders.add_workorder') && (
                      <Group gap={4} wrap="nowrap">
                        <Button
                          size="compact-xs"
                          leftSection={<IconClipboardPlus size={12} />}
                          onClick={() => draft.mutate(r.id)}
                        >
                          Черновик заявки
                        </Button>
                        <Button size="compact-xs" variant="subtle" color="gray" onClick={() => reject.mutate(r.id)}>
                          Отклонить
                        </Button>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {(recs.data?.count ?? 0) > PAGE && (
        <Group justify="center">
          <Pagination total={Math.ceil((recs.data?.count ?? 0) / PAGE)} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  )
}

function Orders() {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const orders = useQuery({
    queryKey: ['workorders', status, page],
    queryFn: () =>
      api<Page<WorkOrder>>('/workorders/items/', {
        query: { ...(status ? { status } : {}), page, page_size: PAGE, ordering: '-created_at' },
      }),
  })
  const move = useMutation({
    mutationFn: ({ id, next }: { id: number; next: WorkOrderStatus }) =>
      api<WorkOrder>(`/workorders/items/${id}/transition/`, { method: 'POST', body: { status: next } }),
    onSuccess: (o) => {
      notifications.show({ color: 'teal', message: `Заявка ${o.number}: ${WO_STATUS[o.status].label}` })
      void queryClient.invalidateQueries({ queryKey: ['workorders'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  return (
    <Stack>
      <Select
        size="xs"
        placeholder="Статус"
        data={Object.entries(WO_STATUS).map(([value, v]) => ({ value, label: v.label }))}
        value={status}
        onChange={(v) => {
          setStatus(v)
          setPage(1)
        }}
        clearable
        w={220}
      />
      {orders.isLoading ? (
        <Loader />
      ) : orders.data?.results.length === 0 ? (
        <Text c="dimmed" size="sm">
          Заявок нет. Черновик создаётся из карточки инцидента или из рекомендации по ТО.
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Номер</Table.Th>
                <Table.Th>Заявка</Table.Th>
                <Table.Th>Приоритет</Table.Th>
                <Table.Th>Срок</Table.Th>
                <Table.Th>Основание</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {orders.data?.results.map((o) => {
                const next = NEXT[o.status]
                return (
                  <Table.Tr key={o.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {o.number}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{o.title}</Text>
                      <Text size="xs" c="dimmed">
                        {o.node_name}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <RiskBadge level={o.priority} />
                    </Table.Td>
                    <Table.Td>{dayjs(o.due_at).format('DD.MM HH:mm')}</Table.Td>
                    <Table.Td>
                      {o.incident ? (
                        <Anchor component={Link} to={`/incidents/${o.incident}`} size="sm">
                          инцидент #{o.incident}
                        </Anchor>
                      ) : o.recommendation ? (
                        <Text size="sm">рекомендация по ТО</Text>
                      ) : (
                        '—'
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={WO_STATUS[o.status].color}>
                        {WO_STATUS[o.status].label}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {next && can(next.perm) && (
                          <Button size="compact-xs" onClick={() => move.mutate({ id: o.id, next: next.status })}>
                            {next.label}
                          </Button>
                        )}
                        {o.status !== 'done' && o.status !== 'cancelled' && can('workorders.change_workorder') && (
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            color="gray"
                            onClick={() => move.mutate({ id: o.id, next: 'cancelled' })}
                          >
                            Отменить
                          </Button>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {(orders.data?.count ?? 0) > PAGE && (
        <Group justify="center">
          <Pagination total={Math.ceil((orders.data?.count ?? 0) / PAGE)} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  )
}

export function WorkOrdersPage() {
  const { can } = useAuth()
  const showRecs = can('workorders.view_maintenancerecommendation')
  return (
    <Stack>
      <Title order={3}>Заявки и рекомендации по ТО</Title>
      <Card withBorder radius="md">
        <Tabs defaultValue={showRecs ? 'recommendations' : 'orders'} keepMounted={false}>
          <Tabs.List>
            {showRecs && <Tabs.Tab value="recommendations">Рекомендации по ТО</Tabs.Tab>}
            <Tabs.Tab value="orders">Заявки</Tabs.Tab>
          </Tabs.List>
          {showRecs && (
            <Tabs.Panel value="recommendations" pt="md">
              <Recommendations />
            </Tabs.Panel>
          )}
          <Tabs.Panel value="orders" pt="md">
            <Orders />
          </Tabs.Panel>
        </Tabs>
      </Card>
    </Stack>
  )
}
