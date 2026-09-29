import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Drawer,
  Group,
  Loader,
  Pagination,
  Paper,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Tabs,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconInfoCircle, IconList, IconSatellite, IconSearch, IconSettings } from '@tabler/icons-react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { lazy, Suspense, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { CHANNEL_STATE as STATE, WO_STATUS } from '../api/labels'
import type {
  MonitoringMap as MapData,
  MonitoringMode,
  MonitoringObject,
  MonitoringObjectDetail,
  MonitoringOthers,
  WorkOrderStatus,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge } from '../components/badges'
import { useCompleteOrder } from '../components/CompleteOrder'
import { usePlanUrl } from '../map/plans'
import { LEGEND, MODE_HINT, MODE_LABEL, SENSOR_COLOR, objectColor, objectWeight } from '../map/status'

// движок карты тяжёлый — грузится только на этой странице
const MonitoringMap = lazy(() => import('../map/MonitoringMap').then((m) => ({ default: m.MonitoringMap })))

const TECH_NEXT: Partial<Record<WorkOrderStatus, { status: WorkOrderStatus; label: string }>> = {
  submitted: { status: 'in_progress', label: 'Взять в работу' },
  in_progress: { status: 'done', label: 'Выполнена' },
}
// без системы заявок заказчика утверждённую заявку бригада берёт сразу
const TAKE = { status: 'in_progress' as WorkOrderStatus, label: 'Взять в работу' }

function Dot({ color }: { color: string }) {
  return <Box w={10} h={10} style={{ borderRadius: 5, background: color, flexShrink: 0 }} />
}

/** Короткая строка цифр объекта для текущего режима. */
function figures(o: MonitoringObject, mode: MonitoringMode): string {
  switch (mode) {
    case 'situation':
      return o.incidents ? `карточек ${o.incidents}${o.escalated ? `, эскалировано ${o.escalated}` : ''}` : 'карточек нет'
    case 'risk':
      return o.risk_level && o.risk_level !== 'low' ? 'повышенный риск' : 'риск низкий'
    case 'state':
      return `не в норме ${o.abnormal ?? 0} из ${o.channels ?? 0}`
    case 'health':
      return `слабых ${o.health_low ?? 0}, молчат ${o.silent ?? 0}`
    case 'orders':
      return o.orders ? `заявок ${o.orders}${o.overdue ? `, просрочено ${o.overdue}` : ''}` : 'заявок нет'
  }
}

function Summary({ data }: { data: MapData }) {
  const s = data.summary
  const chips: { label: string; value: number; color?: string; show: boolean }[] = [
    { label: 'Объекты', value: s.objects, show: true },
    { label: 'Карточки', value: s.incidents, color: s.incidents ? 'orange' : undefined, show: data.modes.includes('situation') },
    { label: 'Эскалированы', value: s.escalated, color: 'grape', show: data.modes.includes('situation') && s.escalated > 0 },
    { label: 'Датчики не в норме', value: s.abnormal, color: s.abnormal ? 'yellow' : undefined, show: true },
    { label: 'Молчат', value: s.silent, show: data.modes.includes('health') },
    { label: 'Заявки', value: s.orders, color: s.overdue ? 'red' : 'blue', show: data.modes.includes('orders') },
    { label: 'На утверждении', value: s.approvals, color: 'violet', show: data.modes.includes('orders') && s.approvals > 0 },
  ]
  return (
    <Group gap={6} wrap="wrap">
      {chips
        .filter((c) => c.show)
        .map((c) => (
          <Badge key={c.label} variant="light" color={c.color ?? 'gray'} size="lg" radius="sm" tt="none" fw={500}>
            {c.label}: <b>{c.value}</b>
          </Badge>
        ))}
    </Group>
  )
}

function ObjectRow({ o, mode, onPick }: { o: MonitoringObject; mode: MonitoringMode; onPick: () => void }) {
  return (
    <UnstyledButton onClick={onPick} py={6} px={4} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
      <Group gap="xs" wrap="nowrap">
        <Dot color={objectColor(o, mode)} />
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text size="sm" fw={500} truncate>
            {o.name}
          </Text>
          <Text size="xs" c="dimmed" truncate>
            {figures(o, mode)}
            {!o.placed && ' · не на карте'}
          </Text>
        </Box>
      </Group>
    </UnstyledButton>
  )
}

function MyZone({ data, mode, onPick }: { data: MapData; mode: MonitoringMode; onPick: (id: number) => void }) {
  const [q, setQ] = useState('')
  const rows = useMemo(
    () =>
      data.objects
        .filter((o) => o.mine && (!q || o.name.toLowerCase().includes(q.toLowerCase())))
        .sort((a, b) => objectWeight(b, mode) - objectWeight(a, mode) || a.name.localeCompare(b.name)),
    [data, mode, q],
  )
  return (
    <Stack gap={6}>
      <TextInput size="xs" placeholder="Найти объект" leftSection={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      {data.summary.unplaced > 0 && (
        <Text size="xs" c="dimmed">
          Не на карте: {data.summary.unplaced} — контур задаётся в «Зоны и объекты».
        </Text>
      )}
      <Stack gap={0}>
        {rows.map((o) => (
          <ObjectRow key={o.id} o={o} mode={mode} onPick={() => onPick(o.id)} />
        ))}
        {!rows.length && (
          <Text size="sm" c="dimmed">
            Объектов нет.
          </Text>
        )}
      </Stack>
    </Stack>
  )
}

/** Объекты вне зоны ответственности — второстепенные, постранично. */
function Others({ onPick }: { onPick: (id: number) => void }) {
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [query] = useDebouncedValue(q.trim(), 300)
  const others = useQuery({
    queryKey: ['monitoring-others', page, query],
    queryFn: () => api<MonitoringOthers>('/analytics/monitoring/others/', { query: { page, q: query } }),
    placeholderData: keepPreviousData,
  })
  return (
    <Stack gap={6}>
      <TextInput
        size="xs"
        placeholder="Найти объект вне зоны"
        leftSection={<IconSearch size={14} />}
        value={q}
        onChange={(e) => {
          setQ(e.currentTarget.value)
          setPage(1)
        }}
      />
      <Text size="xs" c="dimmed">
        Второстепенные направления: на карте — серым, подробности видит их зона. Смежные зоны — первыми.
      </Text>
      <Stack gap={0}>
        {others.data?.results.map((r) => (
          <UnstyledButton key={r.id} onClick={() => onPick(r.id)} py={6} px={4} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
            <Group gap="xs" wrap="nowrap" justify="space-between">
              <Box style={{ minWidth: 0 }}>
                <Text size="sm" truncate>
                  {r.name}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {r.zone_name}
                  {!r.center && ' · не на карте'}
                </Text>
              </Box>
              {r.adjacent && (
                <Badge size="xs" variant="light">
                  смежная
                </Badge>
              )}
            </Group>
          </UnstyledButton>
        ))}
        {others.data && !others.data.count && (
          <Text size="sm" c="dimmed">
            Все объекты — в вашей зоне.
          </Text>
        )}
      </Stack>
      {others.data && others.data.pages > 1 && (
        <Group justify="space-between" gap="xs">
          <Text size="xs" c="dimmed">
            {others.data.count} объектов
          </Text>
          <Pagination size="sm" siblings={0} total={others.data.pages} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={4}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">
        {title}
      </Text>
      {children}
    </Stack>
  )
}

function ObjectPanel({ id, detail, loading, onBack }: { id: number; detail?: MonitoringObjectDetail; loading: boolean; onBack: () => void }) {
  const client = useQueryClient()
  const [allSensors, setAllSensors] = useState(false)
  const move = useMutation({
    mutationFn: ({ order, status }: { order: number; status: WorkOrderStatus }) =>
      api(`/workorders/items/${order}/transition/`, { method: 'POST', body: { status } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['monitoring'] })
      void client.invalidateQueries({ queryKey: ['monitoring-object', id] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const complete = useCompleteOrder(() => {
    void client.invalidateQueries({ queryKey: ['monitoring'] })
    void client.invalidateQueries({ queryKey: ['monitoring-object', id] })
  })
  if (loading || !detail) return <Loader size="sm" />
  const sensors = detail.sensors ?? []
  const bad = sensors.filter((s) => s.state !== 'normal' || s.silent)
  const shown = allSensors ? sensors : bad
  return (
    <Stack gap="sm">
      {complete.modal}
      <Group gap={4} wrap="nowrap">
        <ActionIcon variant="subtle" onClick={onBack} aria-label="К списку">
          <IconArrowLeft size={16} />
        </ActionIcon>
        <Box style={{ minWidth: 0 }}>
          <Text fw={600} truncate>
            {detail.name}
          </Text>
          <Text size="xs" c="dimmed">
            {detail.zone_name ?? 'без зоны'}
            {detail.criticality ? ` · критичность ${detail.criticality}` : ''}
          </Text>
        </Box>
      </Group>
      {!detail.mine ? (
        <Card withBorder padding="sm">
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <IconInfoCircle size={18} />
            <Text size="sm">{detail.note}</Text>
          </Group>
        </Card>
      ) : (
        <>
          <Group gap={6}>
            {Object.entries(detail.states ?? {}).map(([state, n]) => (
              <Badge key={state} variant="light" color="gray" leftSection={<Dot color={SENSOR_COLOR[state] ?? '#adb5bd'} />} tt="none">
                {STATE[state]?.label ?? state}: {n}
              </Badge>
            ))}
          </Group>
          {detail.incidents && detail.modes?.includes('situation') && (
            <Section title={`Карточки · ${detail.incidents.length}`}>
              {detail.incidents.length ? (
                detail.incidents.map((i) => (
                  <Anchor key={i.id} component={Link} to={`/incidents/${i.id}`} underline="never">
                    <Group gap={6} wrap="nowrap">
                      <Box style={{ flexShrink: 0 }}>
                        <RiskBadge level={i.severity} />
                      </Box>
                      <Box style={{ minWidth: 0 }}>
                        <Text size="sm" truncate>
                          {i.title}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {i.status_display}
                          {i.assigned_to ? ` · ${i.assigned_to}` : ''}
                          {i.escalation_level ? ' · эскалация' : ''} · {dayjs(i.opened_at).format('DD.MM HH:mm')}
                        </Text>
                      </Box>
                    </Group>
                  </Anchor>
                ))
              ) : (
                <Text size="sm" c="dimmed">
                  Открытых карточек нет.
                </Text>
              )}
            </Section>
          )}
          {detail.orders && detail.modes?.includes('orders') && (
            <Section title={`Заявки · ${detail.orders.length}`}>
              {detail.orders.length ? (
                detail.orders.map((o) => {
                  const next = o.mine ? (o.status === 'approved' && o.direct ? TAKE : TECH_NEXT[o.status]) : undefined
                  return (
                    <Stack key={o.id} gap={4} pb={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                      <Text size="sm" lineClamp={2}>
                        {o.title}
                      </Text>
                      <Group gap={6}>
                        <Badge size="xs" variant="light" color={WO_STATUS[o.status].color}>
                          {o.status_display}
                        </Badge>
                        <Text size="xs" c={o.overdue ? 'red' : 'dimmed'}>
                          {o.number} · срок {dayjs(o.due_at).format('DD.MM HH:mm')}
                          {o.assignee ? ` · ${o.assignee}` : ''}
                        </Text>
                      </Group>
                      {next ? (
                        <Button size="sm" fullWidth loading={move.isPending} onClick={() =>
                            next.status === 'done' ? complete.open(o.id) : move.mutate({ order: o.id, status: next.status })
                          }
                        >
                          {next.label}
                        </Button>
                      ) : o.status === 'draft' ? (
                        <Anchor component={Link} to="/workorders" size="xs">
                          Утвердить в «Заявки и ТО»
                        </Anchor>
                      ) : null}
                    </Stack>
                  )
                })
              ) : (
                <Text size="sm" c="dimmed">
                  Открытых заявок нет.
                </Text>
              )}
            </Section>
          )}
          <Section title={allSensors ? `Датчики · ${sensors.length}` : `Датчики не в норме · ${bad.length} из ${sensors.length}`}>
            {shown.slice(0, 60).map((s) => (
              <Group key={s.id} gap={6} wrap="nowrap">
                <Dot color={SENSOR_COLOR[s.state] ?? '#adb5bd'} />
                <Text size="sm" truncate style={{ flex: 1 }}>
                  {s.name}
                </Text>
                <Text size="xs" c="dimmed">
                  {s.silent ? 'молчит' : (STATE[s.state]?.label ?? s.state)}
                  {s.health != null && s.health < 40 ? ` · DH ${Math.round(s.health)}` : ''}
                </Text>
              </Group>
            ))}
            {shown.length > 60 && (
              <Text size="xs" c="dimmed">
                … и ещё {shown.length - 60}
              </Text>
            )}
            {sensors.length > 0 && (
              <Anchor size="xs" component="button" onClick={() => setAllSensors((v) => !v)}>
                {allSensors ? 'Только не в норме' : 'Показать все датчики'}
              </Anchor>
            )}
            {sensors.some((s) => !s.placed) && (
              <Text size="xs" c="dimmed">
                Датчики без своих координат разложены по контуру здания по пикету.
              </Text>
            )}
          </Section>
          <Group gap="xs">
            <Button size="xs" variant="light" component={Link} to={`/history?node=${detail.id}`}>
              История объекта
            </Button>
            <Button size="xs" variant="default" component={Link} to="/map">
              Схема по пикетам
            </Button>
          </Group>
        </>
      )}
    </Stack>
  )
}

/** Мониторинг — главный экран каждой роли: карта зоны ответственности и всё, что на ней требует внимания. */
export function MonitoringPage() {
  const { can } = useAuth()
  const phone = useMediaQuery('(max-width: 48em)')
  const [mode, setMode] = useState<MonitoringMode | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [focus, setFocus] = useState<{ id: number; at: number } | null>(null)
  const [tab, setTab] = useState<string | null>('mine')
  const [sheet, setSheet] = useState(false)
  const [satellite, setSatellite] = useState(false)
  // этаж выбранного объекта: план на карте и его датчики; 'all' — все датчики, план контрольного этажа
  const [floorSel, setFloorSel] = useState<{ object: number; floor: number | 'all' } | null>(null)
  // непрозрачность плана на карте у этого пользователя; null — как задано при привязке
  const [planOpacity, setPlanOpacity] = useState<number | null>(null)
  const map = useQuery({
    queryKey: ['monitoring'],
    queryFn: () => api<MapData>('/analytics/monitoring/'),
    refetchInterval: 30_000,
  })
  const detail = useQuery({
    queryKey: ['monitoring-object', selected],
    queryFn: () => api<MonitoringObjectDetail>(`/analytics/monitoring/objects/${selected}/`),
    enabled: selected != null,
    refetchInterval: 30_000,
  })
  const data = map.data
  const floors = detail.data?.id === selected ? (detail.data?.floors ?? []).filter((f) => f.corners) : []
  const chosen = floorSel?.object === selected ? floorSel.floor : 'all'
  const floor = chosen === 'all' ? floors.find((f) => f.is_base) : floors.find((f) => f.id === chosen)
  const floorUrl = usePlanUrl(floor?.plan)
  const plan = floor
    ? { floor: chosen === 'all' ? null : floor.id, url: floorUrl, corners: floor.corners, opacity: planOpacity ?? floor.opacity }
    : null
  const current: MonitoringMode | null = data ? (mode && data.modes.includes(mode) ? mode : data.mode) : null
  const manage = can('topology.add_node') || can('topology.manage_zones') || can('accounts.assign_staff')

  const pick = (id: number | null) => {
    setSelected(id)
    if (id != null) {
      setFocus({ id, at: Date.now() })
      if (phone) setSheet(true)
    }
  }

  const panel = data && current && (
    <>
      {selected != null ? (
        <ObjectPanel id={selected} detail={detail.data} loading={detail.isLoading} onBack={() => setSelected(null)} />
      ) : (
        <Tabs value={tab} onChange={setTab} keepMounted={false}>
          <Tabs.List grow mb="xs">
            <Tabs.Tab value="mine">Моя зона · {data.summary.objects}</Tabs.Tab>
            <Tabs.Tab value="others" disabled={!data.summary.others}>
              Вне зоны · {data.summary.others}
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="mine">
            <MyZone data={data} mode={current} onPick={pick} />
          </Tabs.Panel>
          <Tabs.Panel value="others">
            <Others onPick={pick} />
          </Tabs.Panel>
        </Tabs>
      )}
    </>
  )

  return (
    <Box
      pos="relative"
      style={{
        // во весь экран под шапкой: отступы AppShell компенсируются
        height: 'calc(100dvh - var(--app-shell-header-height, 56px) - 2 * var(--mantine-spacing-md))',
        minHeight: 420,
        display: 'flex',
        gap: 'var(--mantine-spacing-md)',
      }}
    >
      <Paper withBorder radius="md" pos="relative" style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
        {data && current ? (
          <Suspense fallback={<Loader m="md" />}>
            <MonitoringMap
              data={data}
              mode={current}
              selected={selected}
              detail={detail.data}
              onSelect={pick}
              focus={focus}
              satellite={satellite}
              plan={plan}
            />
          </Suspense>
        ) : (
          <Loader m="md" />
        )}
        {data && current && (
          <>
            <Paper shadow="sm" radius="md" p={6} withBorder pos="absolute" top={8} left={8} maw="calc(100% - 64px)" style={{ zIndex: 2 }}>
              <Stack gap={6}>
                <Group gap={6} wrap="nowrap">
                  <SegmentedControl
                    size="xs"
                    data-tour="monitoring-mode"
                    value={current}
                    onChange={(v) => setMode(v as MonitoringMode)}
                    data={data.modes.map((m) => ({ value: m, label: MODE_LABEL[m] }))}
                    style={{ overflowX: 'auto' }}
                  />
                  <Tooltip label={MODE_HINT[current]} multiline w={260}>
                    <IconInfoCircle size={16} style={{ flexShrink: 0 }} />
                  </Tooltip>
                </Group>
                {!phone && <Summary data={data} />}
              </Stack>
            </Paper>
            {data.map.satellite && (
              <Tooltip label={satellite ? 'Векторная карта' : 'Спутниковый снимок'} position="left">
                <ActionIcon
                  pos="absolute"
                  top={90}
                  right={10}
                  size="lg"
                  variant={satellite ? 'filled' : 'default'}
                  style={{ zIndex: 2 }}
                  onClick={() => setSatellite((v) => !v)}
                  aria-label="Спутниковый снимок"
                >
                  <IconSatellite size={18} />
                </ActionIcon>
              </Tooltip>
            )}
            {selected != null && floors.length > 0 && (
              <Paper shadow="sm" radius="md" p={4} withBorder pos="absolute" top={132} right={8} style={{ zIndex: 2 }}>
                <Text size="xs" ta="center" c="dimmed" mb={2}>
                  Этаж
                </Text>
                <SegmentedControl
                  size="xs"
                  orientation="vertical"
                  value={String(chosen)}
                  onChange={(v) => setFloorSel({ object: selected, floor: v === 'all' ? 'all' : Number(v) })}
                  data={[
                    ...[...floors].reverse().map((f) => ({ value: String(f.id), label: f.level === 0 ? 'Ц' : String(f.level) })),
                    { value: 'all', label: 'Все' },
                  ]}
                />
                <Tooltip label="Прозрачность плана" position="left" withArrow>
                  <Slider
                    size="xs"
                    w={52}
                    mx="auto"
                    mt={8}
                    mb={4}
                    min={0.1}
                    max={1}
                    step={0.05}
                    label={null}
                    value={planOpacity ?? floor?.opacity ?? 0.85}
                    onChange={setPlanOpacity}
                    aria-label="Прозрачность плана"
                  />
                </Tooltip>
              </Paper>
            )}
            <Paper shadow="sm" radius="md" p={6} withBorder pos="absolute" bottom={30} left={8} style={{ zIndex: 2 }}>
              <Group gap={8}>
                {LEGEND[current].map((l) => (
                  <Group key={l.label} gap={4} wrap="nowrap">
                    <Dot color={l.color} />
                    <Text size="xs">{l.label}</Text>
                  </Group>
                ))}
              </Group>
            </Paper>
            {phone && (
              <Button
                pos="absolute"
                bottom={80}
                right={8}
                style={{ zIndex: 2 }}
                leftSection={<IconList size={16} />}
                onClick={() => setSheet(true)}
              >
                {selected != null ? 'Объект' : 'Список'}
              </Button>
            )}
          </>
        )}
      </Paper>

      {!phone && (
        <Paper withBorder radius="md" w={380} p="sm" style={{ display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <Group justify="space-between" mb="xs" wrap="nowrap">
            <Box style={{ minWidth: 0 }}>
              <Text fw={700}>Мониторинг</Text>
              <Text size="xs" c="dimmed" truncate>
                Зона: {data?.scope ?? '…'}
              </Text>
            </Box>
            {manage && (
              <Tooltip label="Зоны, объекты, датчики и сотрудники">
                <ActionIcon component={Link} to="/structure" variant="default" aria-label="Зоны и объекты">
                  <IconSettings size={16} />
                </ActionIcon>
              </Tooltip>
            )}
          </Group>
          <ScrollArea style={{ flex: 1 }} offsetScrollbars>
            {panel}
          </ScrollArea>
        </Paper>
      )}

      {phone && (
        <Drawer
          opened={sheet}
          onClose={() => setSheet(false)}
          position="bottom"
          size="70%"
          title={
            <Box>
              <Text fw={700}>Мониторинг</Text>
              {data && <Summary data={data} />}
            </Box>
          }
        >
          {panel}
        </Drawer>
      )}
    </Box>
  )
}
