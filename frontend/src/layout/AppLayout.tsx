import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  Indicator,
  Menu,
  NavLink,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconActivityHeartbeat,
  IconAlertTriangle,
  IconBrain,
  IconCalendarDue,
  IconCalendarStats,
  IconCertificate,
  IconSchool,
  IconHeartRateMonitor,
  IconHistory,
  IconLayoutDashboard,
  IconMapPin,
  IconPolygon,
  IconBell,
  IconBook,
  IconChartBar,
  IconClipboardList,
  IconDatabase,
  IconPuzzle,
  IconDatabaseImport,
  IconFlag,
  IconGauge,
  IconLogout,
  IconMap2,
  IconMoon,
  IconPlugConnected,
  IconPresentationAnalytics,
  IconRoute,
  IconSettings,
  IconShieldCheck,
  IconSun,
  IconTimeline,
  IconTable,
  IconTool,
  IconUser,
  IconUsersGroup,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import type { ComponentType } from 'react'
import { NavLink as RouterLink, Outlet, useLocation } from 'react-router-dom'

import { api } from '../api/client'
import { GRAFANA_PERM, openObservability, SYSTEM_PERM } from '../api/observability'
import type { Me } from '../api/types'
import { ROLE } from '../api/labels'
import { useAuth } from '../auth/AuthContext'
import { CONTOUR, contourHref, type ContourCode } from '../contour'
import { useNotificationStream } from '../realtime/useNotificationStream'
import { ExerciseBanner } from '../components/ExerciseBanner'
import { TrainingDock } from '../training/TrainingDock'
import { NotificationsDrawer } from './NotificationsDrawer'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ size?: number; stroke?: number }>
  perm?: string
  /** страница живёт в другой подсистеме (учения — в учебном контуре): переход без повторного входа */
  contour?: ContourCode
  show?: (ctx: { user: Me; can: (perm: string) => boolean }) => boolean
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const STRUCTURE_PERMS = [
  'topology.add_node',
  'topology.change_node',
  'topology.manage_zones',
  'assets.change_channel',
  'accounts.assign_staff',
]

// Меню по разделам; каждый пункт виден только ролям с соответствующим правом
const NAV: NavGroup[] = [
  {
    label: 'Оперативная работа',
    items: [
      // мониторинг — главный экран каждой роли, открывается после входа
      { to: '/', label: 'Мониторинг', icon: IconMapPin },
      { to: '/workspace', label: 'Рабочее место', icon: IconLayoutDashboard },
      { to: '/overview', label: 'Оперативная обстановка', icon: IconGauge, perm: 'incidents.view_incident' },
      { to: '/incidents', label: 'Инциденты', icon: IconAlertTriangle, perm: 'incidents.view_incident' },
      { to: '/map', label: 'Схема объектов', icon: IconMap2, perm: 'topology.view_node' },
      { to: '/workorders', label: 'Заявки и ТО', icon: IconClipboardList, perm: 'workorders.view_workorder' },
      { to: '/maintenance', label: 'План ТО', icon: IconCalendarDue, perm: 'workorders.plan_maintenance' },
      { to: '/equipment', label: 'Реестр оборудования', icon: IconTool, perm: 'workorders.plan_maintenance' },
      { to: '/schedules', label: 'Графики ТО и ППР', icon: IconTable, perm: 'workorders.plan_maintenance' },
    ],
  },
  {
    label: 'Прогнозы и данные',
    items: [
      { to: '/forecasts', label: 'Журнал прогнозов', icon: IconTimeline, perm: 'forecasting.view_prediction' },
      { to: '/data-health', label: 'Здоровье каналов', icon: IconHeartRateMonitor, perm: 'forecasting.view_channelhealth' },
      { to: '/models', label: 'Модели', icon: IconBrain, perm: 'forecasting.view_mlmodel' },
      { to: '/learning', label: 'Обучение и обратная связь', icon: IconSchool, perm: 'forecasting.review_feedback' },
      { to: '/history', label: 'История', icon: IconCalendarStats, perm: 'telemetry.view_channeldaily' },
      { to: '/replay', label: 'Разбор эпизода', icon: IconHistory, perm: 'incidents.view_incident' },
      { to: '/analytics', label: 'Аналитика', icon: IconChartBar, perm: 'analytics.view_reportexport' },
      { to: '/data-import', label: 'Загрузка данных', icon: IconDatabaseImport, perm: 'ingestion.add_importjob' },
      { to: '/data-quality', label: 'Качество данных', icon: IconDatabase, perm: 'ingestion.view_importjob' },
      { to: '/constructor', label: 'Конструктор датчиков', icon: IconPuzzle, perm: 'ingestion.view_datasource' },
    ],
  },
  {
    label: 'Обучение',
    items: [
      { to: '/training', label: 'Учебные задания', icon: IconCertificate },
      { to: '/exercises', label: 'Учения', icon: IconFlag, contour: 'training' },
    ],
  },
  {
    label: 'Справка',
    items: [
      { to: '/teams', label: 'Команды', icon: IconUsersGroup },
      { to: '/wiki', label: 'Вики', icon: IconBook },
    ],
  },
  {
    label: 'Администрирование',
    items: [
      // задачи роли из матрицы ответственности; админка открывается отсюда без второго входа
      {
        to: '/administration',
        label: 'Мои задачи',
        icon: IconSettings,
        show: ({ user }) => user.admin || user.operations.length > 0,
      },
      { to: '/structure', label: 'Зоны и объекты', icon: IconPolygon, show: ({ can }) => STRUCTURE_PERMS.some(can) },
      { to: '/integrations', label: 'Интеграции', icon: IconPlugConnected, perm: 'integrations.manage_integrations' },
    ],
  },
]

/** Переключатель подсистем платформы: основная система и учебный контур — один вход, одна вкладка. */
function ContourSwitch() {
  return (
    <SegmentedControl
      size="xs"
      visibleFrom="sm"
      value={CONTOUR}
      color={CONTOUR === 'training' ? 'violet' : 'blue'}
      data={[
        { value: 'combat', label: 'Рабочий контур' },
        { value: 'training', label: 'Учебный контур' },
      ]}
      onChange={(value) => {
        if (value !== CONTOUR) window.location.assign(contourHref(value as ContourCode))
      }}
      aria-label="Подсистема"
    />
  )
}

function ColorSchemeToggle({ visibleFrom }: { visibleFrom?: string }) {
  const { setColorScheme } = useMantineColorScheme()
  const scheme = useComputedColorScheme('light')
  return (
    <Tooltip label={scheme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
      <ActionIcon
        variant="default"
        size="lg"
        visibleFrom={visibleFrom}
        aria-label="Тема"
        onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}
      >
        {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  )
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const [inbox, { open: openInbox, close: closeInbox }] = useDisclosure()
  const { user, can, logout } = useAuth()
  const { setColorScheme } = useMantineColorScheme()
  const scheme = useComputedColorScheme('light')
  const location = useLocation()
  useNotificationStream(Boolean(user))

  const unread = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => api<{ count: number }>('/notifications/unread_count/'),
    refetchInterval: 60_000,
  })

  const training = CONTOUR === 'training'
  // Симулятор полигона — тем, кто отвечает за учебный контур (матрица ответственности, accounts/operations.py)
  const instructor = Boolean(user?.operations.some((op) => op.code === 'training.manage'))

  return (
    <AppShell header={{ height: training ? 88 : 56 }} navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        {training && (
          <Group h={32} px="md" gap="xs" justify="center" wrap="nowrap" bg="violet.7" c="white">
            <IconRoute size={16} />
            <Text size="sm" fw={600} truncate>
              Учебный контур — полигон и учебные данные, на работу района не влияет
            </Text>
          </Group>
        )}
        <Group h={56} px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Меню" />
            <Title order={4} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              Прогноз инцидентов
            </Title>
            <Badge variant="light" visibleFrom="lg">
              {user?.scope_node_name ?? 'Все объекты'}
            </Badge>
            {training && (
              <Badge color="violet" variant="filled" hiddenFrom="sm">
                Учебный
              </Badge>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            <ContourSwitch />
            <Indicator label={unread.data?.count} size={16} disabled={!unread.data?.count} color="red">
              <ActionIcon variant="default" size="lg" aria-label="Сообщения" data-tour="notifications" onClick={openInbox}>
                <IconBell size={18} />
              </ActionIcon>
            </Indicator>
            <ColorSchemeToggle visibleFrom="xs" />
            <Menu position="bottom-end" withArrow>
              <Menu.Target>
                <ActionIcon variant="default" size="lg" aria-label="Профиль">
                  <IconUser size={18} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>
                  <Text size="sm" fw={600}>
                    {[user?.last_name, user?.first_name].filter(Boolean).join(' ') || user?.username}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {user?.roles.map((r) => ROLE[r] ?? r).join(', ') || 'Без роли'}
                  </Text>
                  {user?.team && (
                    <Text size="xs" c="dimmed">
                      {user.team.name}
                    </Text>
                  )}
                </Menu.Label>
                <Menu.Divider />
                <Menu.Item
                  hiddenFrom="xs"
                  leftSection={scheme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
                  onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}
                >
                  {scheme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
                </Menu.Item>
                <Menu.Item leftSection={<IconLogout size={16} />} onClick={logout}>
                  Выйти
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <ScrollArea style={{ flex: 1 }} type="scroll">
          <Stack gap={2} data-tour="nav">
            {NAV.map((group) => {
              const items = group.items.filter(
                (item) => (!item.perm || can(item.perm)) && (!item.show || (user && item.show({ user, can }))),
              )
              if (!items.length) return null
              return (
                <Stack gap={2} key={group.label} mb={6}>
                  <Text size="xs" c="dimmed" fw={600} tt="uppercase" px="sm" pt={4}>
                    {group.label}
                  </Text>
                  {items.map((item) =>
                    item.contour && item.contour !== CONTOUR ? (
                      <NavLink
                        key={item.to}
                        href={contourHref(item.contour, item.to)}
                        label={item.label}
                        description={item.contour === 'training' ? 'в учебном контуре' : 'в рабочем контуре'}
                        leftSection={<item.icon size={18} stroke={1.6} />}
                      />
                    ) : (
                      <NavLink
                        key={item.to}
                        component={RouterLink}
                        to={item.to}
                        label={item.label}
                        leftSection={<item.icon size={18} stroke={1.6} />}
                        active={item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)}
                        onClick={close}
                      />
                    ),
                  )}
                </Stack>
              )
            })}
          </Stack>
        </ScrollArea>
        <Stack gap={2} pt={4} style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}>
          {training && instructor && (
            <NavLink
              href={user?.contour.urls.simulator}
              target="_blank"
              label="Симулятор датчиков"
              leftSection={<IconRoute size={18} stroke={1.6} />}
            />
          )}
          <NavLink
            href={contourHref(training ? 'combat' : 'training')}
            label={training ? 'Рабочий контур' : 'Учебный контур'}
            description={training ? 'вернуться к работе района' : 'полигон для заданий и учений'}
            leftSection={training ? <IconShieldCheck size={18} stroke={1.6} /> : <IconRoute size={18} stroke={1.6} />}
          />
          {/* панели наблюдаемости подключены к основной системе */}
          {!training && (can(GRAFANA_PERM) || can(SYSTEM_PERM)) && (
            <NavLink
              label="Панели Grafana"
              description="Бизнес-показатели"
              leftSection={<IconPresentationAnalytics size={18} stroke={1.6} />}
              onClick={() => openObservability('business')}
            />
          )}
          {!training && can(SYSTEM_PERM) && (
            <>
              <NavLink
                label="Мониторинг системы"
                description="Сервисы и очереди в Grafana"
                leftSection={<IconChartBar size={18} stroke={1.6} />}
                onClick={() => openObservability('system')}
              />
              <NavLink
                label="Prometheus"
                description="Метрики и цели сбора"
                leftSection={<IconActivityHeartbeat size={18} stroke={1.6} />}
                onClick={() => openObservability('prometheus')}
              />
            </>
          )}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <ExerciseBanner />
        <Outlet />
        <NotificationsDrawer opened={inbox} onClose={closeInbox} />
        <TrainingDock />
      </AppShell.Main>
    </AppShell>
  )
}
