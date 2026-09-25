import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Progress,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconChevronDown, IconChevronUp, IconCertificate, IconPointer } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { TrainingSession } from '../api/types'
import { mmss, spotlight } from './spotlight'

function useTicker(active: boolean, startedAt?: string) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return startedAt ? Math.max(0, Math.round((now - new Date(startedAt).getTime()) / 1000)) : 0
}

/** Учебное задание поверх любых экранов: шаги, подсказка текущего, «показать где», итог. */
export function TrainingDock() {
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const current = useQuery({
    queryKey: ['training-current'],
    queryFn: () => api<TrainingSession | null>('/training/sessions/current/'),
    refetchInterval: (q) => (q.state.data?.status === 'active' ? 3000 : 30_000),
  })
  const session = current.data
  const elapsed = useTicker(session?.status === 'active', session?.started_at)

  // сообщить о каждом засчитанном шаге
  const done = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!session) {
      done.current = null
      return
    }
    const now = new Set(session.steps.filter((s) => s.status === 'done').map((s) => s.code))
    if (done.current) {
      for (const s of session.steps) {
        if (now.has(s.code) && !done.current.has(s.code)) {
          notifications.show({ color: 'violet', icon: <IconCheck size={16} />, message: `Шаг выполнен: ${s.title}` })
        }
      }
    }
    done.current = now
  }, [session])

  const act = useMutation({
    mutationFn: ({ action, step }: { action: string; step?: string }) =>
      api<TrainingSession>(`/training/sessions/${session!.id}/${action}/`, { method: 'POST', body: { step } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['training-current'] }),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })

  if (!session) return null
  const steps = session.steps
  const finished = steps.filter((s) => s.status === 'done').length
  const step = steps.find((s) => s.status === 'current')
  const isDone = session.status === 'done'

  const show = () => {
    if (!step) return
    act.mutate({ action: 'hint' })
    if (step.route && step.route !== location.pathname) navigate(step.route)
    if (step.target) window.setTimeout(() => spotlight(step.target!), step.route !== location.pathname ? 500 : 0)
  }

  return (
    <Paper
      shadow="lg"
      radius="md"
      withBorder
      p="sm"
      w={360}
      style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 300, maxWidth: 'calc(100vw - 32px)' }}
    >
      <Group justify="space-between" wrap="nowrap" mb={collapsed ? 0 : 'xs'}>
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <ThemeIcon color={isDone ? 'teal' : 'violet'} variant="light">
            {isDone ? <IconCheck size={18} /> : <IconCertificate size={18} />}
          </ThemeIcon>
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed">
              {isDone ? 'Задание выполнено' : `Учебное задание · ${finished} из ${steps.length} · ${mmss(elapsed)}`}
            </Text>
            <Text size="sm" fw={600} truncate>
              {session.title}
            </Text>
          </Stack>
        </Group>
        <ActionIcon variant="subtle" onClick={() => setCollapsed(!collapsed)} aria-label="Свернуть">
          {collapsed ? <IconChevronUp size={16} /> : <IconChevronDown size={16} />}
        </ActionIcon>
      </Group>

      {!collapsed && (
        <Stack gap="xs">
          <Progress value={(100 * finished) / Math.max(steps.length, 1)} color={isDone ? 'teal' : 'violet'} size="sm" />
          {session.object && (
            <Text size="xs" c="dimmed">
              Полигон: {session.object}
            </Text>
          )}
          {session.note && (
            <Alert color="orange" p="xs">
              <Text size="xs">{session.note}</Text>
            </Alert>
          )}
          {isDone ? (
            <>
              <Text size="sm">
                Время {mmss(session.elapsed_s)} · ошибок {session.mistakes} · подсказок {session.hints}
              </Text>
              <Group gap="xs">
                <Button size="xs" component={Link} to="/training" variant="light">
                  Другие задания
                </Button>
                <Button size="xs" variant="subtle" color="gray" onClick={() => act.mutate({ action: 'dismiss' })}>
                  Закрыть
                </Button>
              </Group>
            </>
          ) : (
            <>
              <Stack gap={6}>
                {steps.map((s, i) => (
                  <Group key={s.code} gap={8} wrap="nowrap" align="flex-start">
                    <ThemeIcon
                      size={20}
                      radius="xl"
                      variant={s.status === 'done' ? 'filled' : 'light'}
                      color={s.status === 'pending' ? 'gray' : s.status === 'done' ? 'teal' : 'violet'}
                    >
                      {s.status === 'done' ? <IconCheck size={12} /> : <Text size="xs">{i + 1}</Text>}
                    </ThemeIcon>
                    <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                      <Text size="sm" fw={s.status === 'current' ? 600 : 400} c={s.status === 'current' ? undefined : 'dimmed'}>
                        {s.title}
                      </Text>
                      {s.status === 'current' && (
                        <>
                          <Text size="xs" c="dimmed">
                            {s.hint}
                          </Text>
                          <Group gap="xs">
                            {(s.target || s.route) && (
                              <Button size="compact-xs" variant="light" leftSection={<IconPointer size={12} />} onClick={show}>
                                Показать где
                              </Button>
                            )}
                            {s.manual ? (
                              <Button size="compact-xs" onClick={() => act.mutate({ action: 'confirm', step: s.code })}>
                                Готово
                              </Button>
                            ) : (
                              <Tooltip label="Шаг засчитается сам, как только действие появится в системе">
                                <Badge variant="dot" color="violet" size="sm">
                                  ждём действия
                                </Badge>
                              </Tooltip>
                            )}
                          </Group>
                        </>
                      )}
                    </Stack>
                  </Group>
                ))}
              </Stack>
              <UnstyledButton
                onClick={() => window.confirm('Прервать задание? Полигон вернётся в норму.') && act.mutate({ action: 'abandon' })}
              >
                <Text size="xs" c="dimmed" td="underline">
                  Прервать задание
                </Text>
              </UnstyledButton>
            </>
          )}
        </Stack>
      )}
    </Paper>
  )
}
