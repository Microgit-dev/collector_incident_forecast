import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  Indicator,
  Menu,
  NavLink,
  Stack,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconAlertTriangle,
  IconBrain,
  IconSchool,
  IconHeartRateMonitor,
  IconHistory,
  IconLayoutDashboard,
  IconBell,
  IconChartBar,
  IconClipboardList,
  IconDatabase,
  IconDatabaseImport,
  IconGauge,
  IconLogout,
  IconMap2,
  IconMoon,
  IconRoute,
  IconSettings,
  IconShieldCheck,
  IconSun,
  IconTimeline,
  IconUser,
  IconUsersGroup,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import type { ComponentType } from 'react'
import { NavLink as RouterLink, Outlet, useLocation } from 'react-router-dom'

import { api } from '../api/client'
import { ROLE } from '../api/labels'
import { useAuth } from '../auth/AuthContext'
import { useNotificationStream } from '../realtime/useNotificationStream'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ size?: number; stroke?: number }>
  perm?: string
}

// Каждый пункт виден только ролям, у которых есть соответствующее право
const NAV: NavItem[] = [
  { to: '/', label: 'Рабочее место', icon: IconLayoutDashboard },
  { to: '/overview', label: 'Оперативная обстановка', icon: IconGauge, perm: 'incidents.view_incident' },
  { to: '/incidents', label: 'Инциденты', icon: IconAlertTriangle, perm: 'incidents.view_incident' },
  { to: '/map', label: 'Схема объектов', icon: IconMap2, perm: 'topology.view_node' },
  { to: '/forecasts', label: 'Журнал прогнозов', icon: IconTimeline, perm: 'forecasting.view_prediction' },
  { to: '/data-health', label: 'Здоровье каналов', icon: IconHeartRateMonitor, perm: 'forecasting.view_channelhealth' },
  { to: '/models', label: 'Модели', icon: IconBrain, perm: 'forecasting.view_mlmodel' },
  { to: '/learning', label: 'Обучение и обратная связь', icon: IconSchool, perm: 'forecasting.review_feedback' },
  { to: '/workorders', label: 'Заявки и ТО', icon: IconClipboardList, perm: 'workorders.view_workorder' },
  { to: '/replay', label: 'Разбор эпизода', icon: IconHistory, perm: 'incidents.view_incident' },
  { to: '/teams', label: 'Команды', icon: IconUsersGroup },
  { to: '/analytics', label: 'Аналитика', icon: IconChartBar, perm: 'analytics.view_reportexport' },
  { to: '/data-import', label: 'Загрузка данных', icon: IconDatabaseImport, perm: 'ingestion.add_importjob' },
  { to: '/data-quality', label: 'Качество данных', icon: IconDatabase, perm: 'ingestion.view_importjob' },
]

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme()
  const scheme = useComputedColorScheme('light')
  return (
    <Tooltip label={scheme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
      <ActionIcon variant="default" size="lg" onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
        {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  )
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const { user, can, logout } = useAuth()
  const location = useLocation()
  useNotificationStream(Boolean(user))

  const unread = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => api<{ count: number }>('/notifications/unread_count/'),
    refetchInterval: 60_000,
  })

  const isStaff = can('normalization.change_sensorprofile') || user?.is_superuser
  const training = user?.contour.code === 'training'
  // Сценарии на полигоне запускают инструкторы: руководитель, аналитик, администратор
  const instructor = Boolean(user?.is_superuser || user?.roles.some((r) => ['head', 'analyst', 'admin'].includes(r)))

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
            <Title order={4} style={{ whiteSpace: 'nowrap' }}>
              Прогноз инцидентов
            </Title>
            <Badge variant="light" visibleFrom="md">
              {user?.scope_node_name ?? 'Все объекты'}
            </Badge>
            {training && (
              <Badge color="violet" variant="filled">
                Учебный
              </Badge>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Indicator label={unread.data?.count} size={16} disabled={!unread.data?.count} color="red">
              <ActionIcon variant="default" size="lg" aria-label="Уведомления">
                <IconBell size={18} />
              </ActionIcon>
            </Indicator>
            <ColorSchemeToggle />
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
                <Menu.Item leftSection={<IconLogout size={16} />} onClick={logout}>
                  Выйти
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <Stack gap={2} style={{ flex: 1 }}>
          {NAV.filter((item) => !item.perm || can(item.perm)).map((item) => (
            <NavLink
              key={item.to}
              component={RouterLink}
              to={item.to}
              label={item.label}
              leftSection={<item.icon size={18} stroke={1.6} />}
              active={item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)}
              onClick={close}
            />
          ))}
        </Stack>
        <Stack gap={2} mb={isStaff ? 2 : 0}>
          {training ? (
            <>
              {instructor && (
                <NavLink
                  href={user?.contour.urls.simulator}
                  target="_blank"
                  label="Симулятор датчиков"
                  leftSection={<IconRoute size={18} stroke={1.6} />}
                />
              )}
              <NavLink
                href={user?.contour.urls.combat}
                label="Перейти в рабочий контур"
                leftSection={<IconShieldCheck size={18} stroke={1.6} />}
              />
            </>
          ) : (
            <NavLink
              href={user?.contour.urls.training}
              target="_blank"
              label="Учебный контур"
              description="Полигон для обучения"
              leftSection={<IconRoute size={18} stroke={1.6} />}
            />
          )}
        </Stack>
        {isStaff && (
          <Stack gap={2}>
            <NavLink href="/admin/" label="Администрирование" leftSection={<IconSettings size={18} stroke={1.6} />} />
            <NavLink href="/grafana/" label="Мониторинг системы" leftSection={<IconChartBar size={18} stroke={1.6} />} />
          </Stack>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
