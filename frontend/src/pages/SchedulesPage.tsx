/**
 * Графики ТО и ТР и план-графики ППР в формах заказчика: сформировать по реестру зоны и регламенту,
 * загрузить файл заказчика, сверить генератор с его графиком, утвердить, выгрузить XLSX.
 * Регламент ТО по видам оборудования (сколько ТО в год, из них с ТР, нужен ли ППР) правится здесь же.
 */
import { BarChart } from '@mantine/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  FileButton,
  Grid,
  Group,
  Loader,
  NumberInput,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  UnstyledButton,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconFileTypeXls, IconScale, IconTable, IconTrash, IconUpload } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, download, upload, type Page } from '../api/client'
import type { MaintenanceNorm, MaintenanceScheduleItem, ScheduleLineItem, ScheduleValidation } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
const MONTH_NAMES = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]
const fmt = (d: string | null) => (d ? dayjs(d).format('DD.MM') : '—')
const pct = (v?: number) => (v == null ? '—' : `${Math.round(v * 100)} %`)

type Detail = MaintenanceScheduleItem & { lines: ScheduleLineItem[] }

function LoadChart({ load, compare }: { load?: number[]; compare?: ScheduleValidation }) {
  if (compare) {
    const data = MONTHS.map((m, i) => ({ m, customer: compare.load_customer[i], generated: compare.load_generated[i] }))
    return (
      <BarChart
        h={160}
        data={data}
        dataKey="m"
        series={[
          { name: 'customer', label: 'заказчик', color: 'gray.5' },
          { name: 'generated', label: 'генератор системы', color: 'teal.6' },
        ]}
        withLegend
      />
    )
  }
  if (!load) return null
  return (
    <BarChart
      h={140}
      data={MONTHS.map((m, i) => ({ m, v: load[i] }))}
      dataKey="m"
      series={[{ name: 'v', label: 'работ', color: 'teal.6' }]}
    />
  )
}

function Validation({ schedule, v }: { schedule: Detail; v: ScheduleValidation }) {
  const toTr = schedule.kind === 'to_tr'
  return (
    <Card withBorder padding="sm" radius="md">
      <Group gap={6} mb={4}>
        <IconScale size={16} />
        <Text fw={600} size="sm">
          Сверка: генератор системы на составе этого графика
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="xs">
        {toTr ? (
          <>
            <Metric label="Периодичность совпала" value={pct(v.periodicity_match)} />
            <Metric label="ТО+ТР совпало" value={pct(v.repairs_match)} />
          </>
        ) : (
          <>
            <Metric label="Партий: заказчик / система" value={`${v.batches_customer} / ${v.batches_generated}`} />
            <Metric
              label="Последняя приёмка"
              value={`${fmt(v.last_acceptance_customer ?? null)} / ${fmt(v.last_acceptance_generated ?? null)}`}
            />
          </>
        )}
        <Metric label="Неравномерность, заказчик" value={v.cv_customer.toFixed(2)} />
        <Metric label="Неравномерность, система" value={v.cv_generated.toFixed(2)} />
      </SimpleGrid>
      <LoadChart compare={v} />
      <Text size="xs" c="dimmed" mt={4}>
        {toTr
          ? 'Регламент по видам оборудования применён к тем же объектам и количествам. Неравномерность — коэффициент вариации числа работ по месяцам: меньше — ровнее нагрузка на бригады.'
          : 'Те же объекты и количество датчиков метана; система собирает партии и распределяет их по рабочим дням года. Нагрузка — датчиков в месяц.'}
      </Text>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={700}>{value}</Text>
    </div>
  )
}

function ToTrTable({ lines }: { lines: ScheduleLineItem[] }) {
  let current = ''
  return (
    <ScrollArea>
      <Table withTableBorder withColumnBorders fz="xs" miw={1000}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Вид оборудования</Table.Th>
            <Table.Th>Кол-во</Table.Th>
            {MONTHS.map((m) => (
              <Table.Th key={m} ta="center">
                {m}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lines.flatMap((ln) => {
            const rows = []
            if (ln.object_label !== current) {
              current = ln.object_label
              rows.push(
                <Table.Tr key={`o-${ln.id}`} bg="var(--mantine-color-default-hover)">
                  <Table.Td colSpan={14} fw={700}>
                    {ln.object_label}
                  </Table.Td>
                </Table.Tr>,
              )
            }
            rows.push(
              <Table.Tr key={ln.id}>
                <Table.Td>{ln.type_name}</Table.Td>
                <Table.Td>
                  {Number.isInteger(ln.quantity) ? ln.quantity : ln.quantity.toFixed(1)} {ln.unit}
                </Table.Td>
                {MONTHS.map((_, i) => {
                  const mark = ln.months[String(i + 1)]
                  return (
                    <Table.Td key={i} ta="center" p={2}>
                      {mark && (
                        <Badge
                          size="xs"
                          variant={mark === 'ТО+ТР' ? 'filled' : 'light'}
                          color={mark === 'ТО+ТР' ? 'grape' : 'teal'}
                        >
                          {mark}
                        </Badge>
                      )}
                    </Table.Td>
                  )
                })}
              </Table.Tr>,
            )
            return rows
          })}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  )
}

function PprTable({ lines }: { lines: ScheduleLineItem[] }) {
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table striped withTableBorder fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Партия</Table.Th>
            <Table.Th>Месяц</Table.Th>
            <Table.Th>Объект</Table.Th>
            <Table.Th>Датчиков</Table.Th>
            <Table.Th>Демонтаж</Table.Th>
            <Table.Th>В ОМ (до 9:00)</Table.Th>
            <Table.Th>Вывоз из ОМ</Table.Th>
            <Table.Th>Комиссия</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lines.map((ln) => (
            <Table.Tr key={ln.id}>
              <Table.Td>{ln.batch ?? '—'}</Table.Td>
              <Table.Td>{ln.month ? MONTH_NAMES[ln.month - 1] : '—'}</Table.Td>
              <Table.Td>{ln.object_label}</Table.Td>
              <Table.Td>{ln.quantity}</Table.Td>
              <Table.Td>{fmt(ln.dismantle_on)}</Table.Td>
              <Table.Td>{fmt(ln.delivery_on)}</Table.Td>
              <Table.Td>{fmt(ln.pickup_on)}</Table.Td>
              <Table.Td>{fmt(ln.acceptance_on)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

function ScheduleDetail({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { can } = useAuth()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['schedules', id], queryFn: () => api<Detail>(`/workorders/schedules/${id}/`) })
  const refresh = () => void client.invalidateQueries({ queryKey: ['schedules'] })
  const act = useMutation({
    mutationFn: (action: 'approve' | 'validate' | 'derive-norms' | 'discard') =>
      api<Record<string, number>>(`/workorders/schedules/${id}/${action}/`, { method: 'POST' }),
    onSuccess: (r, action) => {
      const text = {
        approve: 'График утверждён: работы месяца появятся в плане ТО',
        validate: 'Сверка выполнена',
        'derive-norms': `Регламент обновлён по графику заказчика: видов ${r ? (r.created ?? 0) + (r.updated ?? 0) : 0}`,
        discard: 'Черновик удалён',
      }[action]
      notifications.show({ color: 'teal', message: text })
      if (action === 'discard') onDeleted()
      refresh()
      void client.invalidateQueries({ queryKey: ['norms'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const s = detail.data
  if (detail.isLoading || !s) return <Loader />
  return (
    <Stack>
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Text fw={700} size="lg">
            {s.title}
          </Text>
          <Group gap={6} mt={4}>
            <Badge variant="light">{s.kind_display}</Badge>
            <Badge variant="outline" color={s.source === 'customer' ? 'gray' : 'blue'}>
              {s.source_display}
            </Badge>
            <Badge color={s.status === 'approved' ? 'teal' : 'yellow'}>{s.status_display}</Badge>
            <Text size="xs" c="dimmed">
              {s.kind === 'to_tr'
                ? `объектов ${s.stats.objects} · строк ${s.stats.lines}`
                : `объектов ${s.stats.objects} · партий ${s.stats.batches} · датчиков ${s.stats.sensors}`}
              {s.approved_by_name && ` · утвердил ${s.approved_by_name}`}
            </Text>
          </Group>
        </div>
        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            leftSection={<IconFileTypeXls size={14} />}
            onClick={() => void download(`/workorders/schedules/${id}/xlsx/`, `${s.title}.xlsx`)}
          >
            XLSX в форме заказчика
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<IconScale size={14} />}
            loading={act.isPending && act.variables === 'validate'}
            onClick={() => act.mutate('validate')}
          >
            Сверить с генератором
          </Button>
          {s.source === 'customer' && s.kind === 'to_tr' && (
            <Button size="xs" variant="default" onClick={() => act.mutate('derive-norms')}>
              Регламент из этого графика
            </Button>
          )}
          {s.status === 'draft' && can('workorders.approve_workorder') && (
            <Button size="xs" color="teal" leftSection={<IconCheck size={14} />} onClick={() => act.mutate('approve')}>
              Утвердить
            </Button>
          )}
          {s.status === 'draft' && (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection={<IconTrash size={14} />}
              onClick={() => act.mutate('discard')}
            >
              Удалить
            </Button>
          )}
        </Group>
      </Group>
      {s.stats.validation ? (
        <Validation schedule={s} v={s.stats.validation} />
      ) : (
        <Card withBorder padding="sm" radius="md">
          <Text size="sm" fw={600} mb={4}>
            {s.kind === 'to_tr' ? 'Работ по месяцам' : 'Датчиков метана по месяцам'}
          </Text>
          <LoadChart load={s.stats.load} />
        </Card>
      )}
      {s.kind === 'to_tr' ? <ToTrTable lines={s.lines} /> : <PprTable lines={s.lines} />}
    </Stack>
  )
}

function Norms() {
  const { can } = useAuth()
  const client = useQueryClient()
  const norms = useQuery({ queryKey: ['norms'], queryFn: () => api<MaintenanceNorm[]>('/workorders/norms/') })
  const save = useMutation({
    mutationFn: ({ id, ...body }: Partial<MaintenanceNorm> & { id: number }) =>
      api(`/workorders/norms/${id}/`, { method: 'PATCH', body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['norms'] }),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const edit = can('workorders.plan_maintenance')
  if (norms.isLoading) return <Loader />
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Сколько раз в год обслуживается каждый вид оборудования и сколько из этих ТО — с текущим ремонтом. Нормы систем
        АКМ и ДУ выведены из графика ТО и ТР заказчика на 2026 год: у каждого вида одна периодичность на всех объектах.
        По регламенту строятся графики и сроки ТО в реестре.
      </Text>
      <Table.ScrollContainer minWidth={800}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Вид оборудования</Table.Th>
              <Table.Th>Система</Table.Th>
              <Table.Th>ТО в год</Table.Th>
              <Table.Th>из них ТО+ТР</Table.Th>
              <Table.Th>ППР и поверка</Table.Th>
              <Table.Th>Источник</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {norms.data?.map((n) => (
              <Table.Tr key={n.id}>
                <Table.Td>
                  {n.type_name}{' '}
                  <Text span size="xs" c="dimmed">
                    ({n.unit})
                  </Text>
                </Table.Td>
                <Table.Td>{n.system}</Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    w={80}
                    min={0}
                    max={12}
                    disabled={!edit}
                    defaultValue={n.visits_per_year}
                    onBlur={(e) => {
                      const v = Number(e.currentTarget.value)
                      if (v !== n.visits_per_year) save.mutate({ id: n.id, visits_per_year: v })
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    w={80}
                    min={0}
                    max={12}
                    disabled={!edit}
                    defaultValue={n.repairs_per_year}
                    onBlur={(e) => {
                      const v = Number(e.currentTarget.value)
                      if (v !== n.repairs_per_year) save.mutate({ id: n.id, repairs_per_year: v })
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Checkbox
                    disabled={!edit}
                    checked={n.ppr}
                    onChange={(e) => save.mutate({ id: n.id, ppr: e.currentTarget.checked })}
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {n.source}
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

export function SchedulesPage() {
  const client = useQueryClient()
  const thisYear = dayjs().year()
  const [year, setYear] = useState(String(thisYear))
  const [selected, setSelected] = useState<number | null>(null)
  const list = useQuery({
    queryKey: ['schedules', 'list', year],
    queryFn: () => api<Page<MaintenanceScheduleItem>>('/workorders/schedules/', { query: { year, page_size: 50 } }),
  })
  const refresh = () => void client.invalidateQueries({ queryKey: ['schedules'] })
  const generate = useMutation({
    mutationFn: (kind: 'to_tr' | 'ppr') =>
      api<MaintenanceScheduleItem>('/workorders/schedules/generate/', {
        method: 'POST',
        body: { kind, year: Number(year) },
      }),
    onSuccess: (s) => {
      notifications.show({ color: 'teal', message: `Сформирован черновик: ${s.title}` })
      setSelected(s.id)
      refresh()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const importFile = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return upload<MaintenanceScheduleItem>('/workorders/schedules/import/', form)
    },
    onSuccess: (s) => {
      notifications.show({ color: 'teal', message: `Загружен ${s.title}` })
      setYear(String(s.year))
      setSelected(s.id)
      refresh()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const items = list.data?.results ?? []
  const current = selected ?? items[0]?.id ?? null
  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <div>
          <Title order={3}>Графики ТО и ППР</Title>
          <Text size="sm" c="dimmed">
            Годовой график ТО и ТР и план-график ППР аппаратуры контроля метана в формах заказчика: по реестру и
            регламенту или из файла. Утверждённый график превращается в заявки по месяцам в плане ТО.
          </Text>
        </div>
        <Group gap="xs">
          <Select
            size="xs"
            w={100}
            data={[thisYear - 1, thisYear, thisYear + 1].map(String)}
            value={year}
            onChange={(v) => {
              setYear(v ?? String(thisYear))
              setSelected(null)
            }}
          />
          <Button
            size="xs"
            leftSection={<IconTable size={14} />}
            loading={generate.isPending && generate.variables === 'to_tr'}
            onClick={() => generate.mutate('to_tr')}
          >
            Сформировать график ТО и ТР
          </Button>
          <Button
            size="xs"
            variant="light"
            loading={generate.isPending && generate.variables === 'ppr'}
            onClick={() => generate.mutate('ppr')}
          >
            Сформировать план-график ППР
          </Button>
          <FileButton onChange={(f) => f && importFile.mutate(f)} accept=".xlsx">
            {(props) => (
              <Button
                {...props}
                size="xs"
                variant="default"
                leftSection={<IconUpload size={14} />}
                loading={importFile.isPending}
              >
                Загрузить график заказчика
              </Button>
            )}
          </FileButton>
        </Group>
      </Group>
      <Tabs defaultValue="schedules" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="schedules">Графики</Tabs.Tab>
          <Tabs.Tab value="norms">Регламент ТО</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="schedules" pt="md">
          {list.isLoading ? (
            <Loader />
          ) : items.length === 0 ? (
            <Alert variant="light">
              Графиков на {year} год нет. Сформируйте их по реестру зоны или загрузите файл заказчика (XLSX).
            </Alert>
          ) : (
            <Grid>
              <Grid.Col span={{ base: 12, lg: 3 }}>
                <Stack gap="xs">
                  {items.map((s) => (
                    <UnstyledButton key={s.id} onClick={() => setSelected(s.id)}>
                      <Card
                        withBorder
                        padding="xs"
                        radius="md"
                        bg={s.id === current ? 'var(--mantine-color-blue-light)' : undefined}
                      >
                        <Text size="sm" fw={600} lineClamp={2}>
                          {s.title}
                        </Text>
                        <Group gap={4} mt={4}>
                          <Badge size="xs" variant="outline" color={s.source === 'customer' ? 'gray' : 'blue'}>
                            {s.source === 'customer' ? 'заказчик' : 'система'}
                          </Badge>
                          <Badge size="xs" color={s.status === 'approved' ? 'teal' : 'yellow'}>
                            {s.status_display}
                          </Badge>
                          <Text size="xs" c="dimmed">
                            {dayjs(s.created_at).format('DD.MM HH:mm')}
                          </Text>
                        </Group>
                      </Card>
                    </UnstyledButton>
                  ))}
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 9 }}>
                {current && (
                  <Card withBorder radius="md">
                    <ScheduleDetail key={current} id={current} onDeleted={() => setSelected(null)} />
                  </Card>
                )}
              </Grid.Col>
            </Grid>
          )}
        </Tabs.Panel>
        <Tabs.Panel value="norms" pt="md">
          <Card withBorder radius="md">
            <Norms />
          </Card>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
