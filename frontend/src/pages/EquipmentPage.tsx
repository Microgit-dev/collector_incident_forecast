/**
 * Реестр оборудования зоны (ТЗ §6 «анализ реестров», §1 «фактическое состояние»): регламент ТО,
 * фактическое состояние по осмотрам и история осмотров. Инженер ТО записывает осмотр, заводит единицы
 * и загружает выгрузку реестра заказчика.
 */
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Drawer,
  Group,
  Loader,
  Modal,
  NumberInput,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Timeline,
  Title,
} from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { useDebouncedValue } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconClipboardCheck, IconPlus } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, type Page } from '../api/client'
import { CONDITION, EQUIPMENT_SOURCE } from '../api/labels'
import type { Equipment, Inspection } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RegistryImport } from '../components/RegistryImport'
import { ConditionBadge } from './MaintenancePage'

const PAGE = 50
const KINDS = [
  { value: 'hatch', label: 'Люк' },
  { value: 'door', label: 'Дверь / аварийный выход' },
  { value: 'vent_shaft', label: 'Вентшахта' },
  { value: 'chamber', label: 'Камера' },
  { value: 'pump', label: 'Насос' },
  { value: 'fan', label: 'Вентилятор' },
  { value: 'ups', label: 'ИБП' },
  { value: 'cabinet', label: 'Шкаф автоматики' },
  { value: 'sensor', label: 'Датчик' },
]

function InspectForm({ equipment, onDone }: { equipment: Equipment; onDone: () => void }) {
  const client = useQueryClient()
  const [condition, setCondition] = useState('')
  const [notes, setNotes] = useState('')
  const [maintenance, setMaintenance] = useState(false)
  const save = useMutation({
    mutationFn: () =>
      api('/workorders/inspections/', {
        method: 'POST',
        body: { equipment: equipment.id, condition, notes, maintenance },
      }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Осмотр записан, состояние обновлено в реестре' })
      void client.invalidateQueries({ queryKey: ['equipment'] })
      void client.invalidateQueries({ queryKey: ['inspections', equipment.id] })
      void client.invalidateQueries({ queryKey: ['maintenance-plan'] })
      setCondition('')
      setNotes('')
      setMaintenance(false)
      onDone()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  return (
    <Stack gap="xs">
      <SegmentedControl
        size="xs"
        fullWidth
        value={condition}
        onChange={setCondition}
        data={Object.entries(CONDITION).map(([value, c]) => ({ value, label: c.label }))}
      />
      <Textarea
        placeholder="Замечания"
        autosize
        minRows={1}
        value={notes}
        onChange={(e) => setNotes(e.currentTarget.value)}
      />
      <Checkbox
        size="xs"
        label="Выполнено ТО — начать новый межрегламентный интервал"
        checked={maintenance}
        onChange={(e) => setMaintenance(e.currentTarget.checked)}
      />
      <Button
        size="xs"
        leftSection={<IconClipboardCheck size={14} />}
        disabled={!condition}
        loading={save.isPending}
        onClick={() => save.mutate()}
      >
        Записать осмотр
      </Button>
    </Stack>
  )
}

function EquipmentDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { can } = useAuth()
  const client = useQueryClient()
  // карточка читается заново: после осмотра состояние и дата ТО меняются
  const one = useQuery({
    queryKey: ['equipment', 'one', id],
    queryFn: () => api<Equipment>(`/assets/equipment/${id}/`),
    enabled: id !== null,
  })
  const history = useQuery({
    queryKey: ['inspections', id],
    queryFn: () => api<Page<Inspection>>('/workorders/inspections/', { query: { equipment: id!, page_size: 50 } }),
    enabled: id !== null,
  })
  const [intervalDays, setIntervalDays] = useState<number | string>('')
  const saveInterval = useMutation({
    mutationFn: () =>
      api(`/assets/equipment/${id}/`, { method: 'PATCH', body: { maintenance_interval_days: Number(intervalDays) } }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Регламентный интервал сохранён' })
      void client.invalidateQueries({ queryKey: ['equipment'] })
      void client.invalidateQueries({ queryKey: ['maintenance-plan'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  if (id === null) return null
  const equipment = one.data
  if (!equipment)
    return (
      <Drawer opened onClose={onClose} position="right" size="md" title="Оборудование">
        <Loader size="sm" />
      </Drawer>
    )
  const source = EQUIPMENT_SOURCE[equipment.source]
  return (
    <Drawer opened onClose={onClose} position="right" size="md" title={equipment.name}>
      <Stack>
        <Text size="sm" c="dimmed">
          {equipment.kind_display} · {equipment.node_name}
          {equipment.picket && ` · ПК ${equipment.picket}`}
          {equipment.inventory_number && ` · инв. ${equipment.inventory_number}`}
        </Text>
        <Group gap="xs">
          <ConditionBadge condition={equipment.condition} />
          <Badge variant="outline" color={source.color} size="sm">
            {source.label}
          </Badge>
          {!equipment.is_active && (
            <Badge color="gray" size="sm">
              выведено
            </Badge>
          )}
        </Group>
        <Table>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>Ввод в эксплуатацию</Table.Td>
              <Table.Td>
                {equipment.commissioned_at ? dayjs(equipment.commissioned_at).format('DD.MM.YYYY') : '—'}
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>Последнее ТО</Table.Td>
              <Table.Td>
                {equipment.last_maintenance_at ? dayjs(equipment.last_maintenance_at).format('DD.MM.YYYY') : '—'}
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>Следующее ТО по регламенту</Table.Td>
              <Table.Td
                c={
                  equipment.next_maintenance_at && dayjs(equipment.next_maintenance_at).isBefore(dayjs())
                    ? 'red'
                    : undefined
                }
              >
                {equipment.next_maintenance_at ? dayjs(equipment.next_maintenance_at).format('DD.MM.YYYY') : '—'}
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>Наработка на отказ</Table.Td>
              <Table.Td>{equipment.mtbf_hours ? `${equipment.mtbf_hours.toLocaleString('ru-RU')} ч` : '—'}</Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
        {can('assets.change_equipment') && (
          <Group align="flex-end" gap="xs">
            <NumberInput
              size="xs"
              label="Регламентный интервал ТО, сут"
              min={1}
              max={3650}
              value={intervalDays === '' ? (equipment.maintenance_interval_days ?? '') : intervalDays}
              onChange={setIntervalDays}
              w={220}
            />
            <Button
              size="xs"
              variant="light"
              disabled={intervalDays === ''}
              loading={saveInterval.isPending}
              onClick={() => saveInterval.mutate()}
            >
              Сохранить
            </Button>
          </Group>
        )}
        {can('workorders.add_equipmentinspection') && (
          <Card withBorder padding="sm">
            <Text fw={600} size="sm" mb="xs">
              Осмотр: фактическое состояние
            </Text>
            <InspectForm equipment={equipment} onDone={() => undefined} />
          </Card>
        )}
        <Text fw={600} size="sm">
          История осмотров и ТО
        </Text>
        {history.isLoading ? (
          <Loader size="sm" />
        ) : history.data?.results.length ? (
          <Timeline bulletSize={12} lineWidth={2}>
            {history.data.results.map((i) => (
              <Timeline.Item
                key={i.id}
                color={CONDITION[i.condition]?.color}
                title={`${i.condition_display}${i.maintenance ? ' · ТО' : ''}`}
              >
                <Text size="xs" c="dimmed">
                  {dayjs(i.inspected_at).format('DD.MM.YYYY HH:mm')}
                  {i.inspector_name && ` · ${i.inspector_name}`}
                  {i.workorder_number && ` · заявка ${i.workorder_number}`}
                </Text>
                {i.notes && <Text size="sm">{i.notes}</Text>}
              </Timeline.Item>
            ))}
          </Timeline>
        ) : (
          <Text size="sm" c="dimmed">
            Осмотров ещё не было.
          </Text>
        )}
      </Stack>
    </Drawer>
  )
}

function AddEquipment({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const client = useQueryClient()
  const [form, setForm] = useState({
    name: '',
    kind: 'pump',
    node: '',
    inventory_number: '',
    picket: '',
    interval: '',
    last: null as string | null,
  })
  const nodes = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () =>
      api<Page<{ id: number; name: string; depth: number }>>('/topology/nodes/', {
        query: { page_size: 500, is_active: true },
      }),
    staleTime: 10 * 60_000,
    enabled: opened,
  })
  const save = useMutation({
    mutationFn: () =>
      api('/assets/equipment/', {
        method: 'POST',
        body: {
          name: form.name,
          kind: form.kind,
          node: Number(form.node),
          inventory_number: form.inventory_number,
          picket: form.picket || null,
          maintenance_interval_days: form.interval ? Number(form.interval) : null,
          last_maintenance_at: form.last,
        },
      }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Единица добавлена в реестр' })
      void client.invalidateQueries({ queryKey: ['equipment'] })
      onClose()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const set = (key: keyof typeof form) => (value: string | null) => setForm((f) => ({ ...f, [key]: value ?? '' }))
  return (
    <Modal opened={opened} onClose={onClose} title="Новая единица оборудования">
      <Stack gap="xs">
        <TextInput
          label="Наименование"
          required
          value={form.name}
          onChange={(e) => set('name')(e.currentTarget.value)}
        />
        <Select label="Вид" data={KINDS} value={form.kind} onChange={set('kind')} />
        <Select
          label="Объект"
          searchable
          required
          data={(nodes.data?.results ?? []).map((n) => ({
            value: String(n.id),
            label: `${'  '.repeat(Math.max(0, n.depth - 1))}${n.name}`,
          }))}
          value={form.node}
          onChange={set('node')}
        />
        <Group grow>
          <TextInput
            label="Инв. номер"
            value={form.inventory_number}
            onChange={(e) => set('inventory_number')(e.currentTarget.value)}
          />
          <TextInput label="Пикет" value={form.picket} onChange={(e) => set('picket')(e.currentTarget.value)} />
        </Group>
        <Group grow>
          <TextInput
            label="Интервал ТО, сут"
            value={form.interval}
            onChange={(e) => set('interval')(e.currentTarget.value)}
          />
          <DatePickerInput
            label="Последнее ТО"
            value={form.last}
            onChange={(v) => set('last')(v as string | null)}
            valueFormat="DD.MM.YYYY"
            clearable
          />
        </Group>
        <Text size="xs" c="dimmed">
          Заведённая вручную единица не перезаписывается при синхронизации с реестром заказчика.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={!form.name || !form.node} loading={save.isPending} onClick={() => save.mutate()}>
            Добавить
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

export function EquipmentPage() {
  const { can } = useAuth()
  const [search, setSearch] = useState('')
  const [debounced] = useDebouncedValue(search, 300)
  const [kind, setKind] = useState<string | null>(null)
  const [condition, setCondition] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const list = useQuery({
    queryKey: ['equipment', debounced, kind, condition, page],
    queryFn: () =>
      api<Page<Equipment>>('/assets/equipment/', {
        query: { search: debounced, kind, condition, is_active: true, page, page_size: PAGE },
      }),
  })
  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <div>
          <Title order={3}>Реестр оборудования</Title>
          <Text size="sm" c="dimmed">
            Регламент ТО, фактическое состояние по осмотрам и история работ по каждой единице.
          </Text>
        </div>
        {can('assets.add_equipment') && (
          <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setAdding(true)}>
            Добавить единицу
          </Button>
        )}
      </Group>
      {can('assets.add_equipment') && (
        <Card withBorder radius="md">
          <RegistryImport />
        </Card>
      )}
      <Card withBorder radius="md">
        <Group gap="xs" mb="sm" wrap="wrap">
          <TextInput
            size="xs"
            placeholder="Наименование или инв. номер"
            value={search}
            onChange={(e) => {
              setSearch(e.currentTarget.value)
              setPage(1)
            }}
            w={260}
          />
          <Select
            size="xs"
            placeholder="Вид"
            data={KINDS}
            value={kind}
            onChange={(v) => {
              setKind(v)
              setPage(1)
            }}
            clearable
            w={200}
          />
          <Select
            size="xs"
            placeholder="Состояние"
            data={Object.entries(CONDITION).map(([value, c]) => ({ value, label: c.label }))}
            value={condition}
            onChange={(v) => {
              setCondition(v)
              setPage(1)
            }}
            clearable
            w={200}
          />
          <Text size="xs" c="dimmed">
            {list.data ? `единиц: ${list.data.count}` : ''}
          </Text>
        </Group>
        {list.isLoading ? (
          <Loader />
        ) : (
          <Table.ScrollContainer minWidth={900}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Оборудование</Table.Th>
                  <Table.Th>Объект</Table.Th>
                  <Table.Th>Последнее ТО</Table.Th>
                  <Table.Th>Следующее ТО</Table.Th>
                  <Table.Th>Состояние</Table.Th>
                  <Table.Th>Источник</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.results.map((e) => {
                  const overdue = e.next_maintenance_at && dayjs(e.next_maintenance_at).isBefore(dayjs(), 'day')
                  return (
                    <Table.Tr key={e.id} style={{ cursor: 'pointer' }} onClick={() => setSelected(e.id)}>
                      <Table.Td>
                        <Text size="sm">{e.name}</Text>
                        <Text size="xs" c="dimmed">
                          {e.kind_display}
                          {e.inventory_number && ` · ${e.inventory_number}`}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{e.node_name}</Text>
                      </Table.Td>
                      <Table.Td>
                        {e.last_maintenance_at ? dayjs(e.last_maintenance_at).format('DD.MM.YYYY') : '—'}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" c={overdue ? 'red' : undefined} fw={overdue ? 600 : undefined}>
                          {e.next_maintenance_at ? dayjs(e.next_maintenance_at).format('DD.MM.YYYY') : '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <ConditionBadge condition={e.condition} />
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {EQUIPMENT_SOURCE[e.source]?.label}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {(list.data?.count ?? 0) > PAGE && (
          <Group justify="center" mt="sm">
            <Pagination total={Math.ceil((list.data?.count ?? 0) / PAGE)} value={page} onChange={setPage} />
          </Group>
        )}
      </Card>
      <EquipmentDrawer key={selected ?? 0} id={selected} onClose={() => setSelected(null)} />
      <AddEquipment opened={adding} onClose={() => setAdding(false)} />
    </Stack>
  )
}
