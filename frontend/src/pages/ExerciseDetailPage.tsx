import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Modal,
  RingProgress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Timeline,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconCheck,
  IconEyeOff,
  IconFlag,
  IconHandStop,
  IconPlayerPlay,
  IconPlayerStop,
  IconQuestionMark,
  IconX,
} from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import { EXERCISE_STATUS, when } from '../api/exercises'
import { ROLE } from '../api/labels'
import type { Exercise, ExerciseReport } from '../api/types'
import { mmss } from '../training/spotlight'

const t = (s: number | null) => (s === null ? '—' : `+${mmss(s)}`)

const KIND_COLOR: Record<string, string> = {
  start: 'violet',
  complication: 'orange',
  opened: 'red',
  seen: 'gray',
  acknowledged: 'blue',
  assigned: 'blue',
  escalated: 'orange',
  decision: 'teal',
  workorder: 'cyan',
  stop: 'orange',
  end: 'violet',
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

function Report({ report, live }: { report: ExerciseReport; live: boolean }) {
  const { passed, total } = report.score
  const share = total ? passed / total : 0
  return (
    <>
      <Grid>
        <Grid.Col span={{ base: 12, md: 4 }}>
        <Card withBorder radius="md" h="100%">
          <Group wrap="nowrap">
            <RingProgress
              size={96}
              thickness={10}
              roundCaps
              sections={[{ value: share * 100, color: share >= 0.8 ? 'teal' : share >= 0.5 ? 'yellow' : 'red' }]}
              label={
                <Text ta="center" fw={700}>
                  {passed}/{total}
                </Text>
              }
            />
            <div>
              <Text fw={600}>{live ? 'Ход учений' : 'Итог учений'}</Text>
              <Text size="sm" c="dimmed">
                проверок пройдено; сценарий «{report.scenario}»
                {report.complication && `, осложнение — ${report.complication.toLowerCase()}`}
              </Text>
              <Text size="sm" c="dimmed">
                длительность {mmss(report.duration_s ?? 0)}, карточек {report.incidents.length}
              </Text>
            </div>
          </Group>
        </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
        <Card withBorder radius="md" h="100%">
          <Text fw={600} mb="xs">
            Проверки
          </Text>
          <Stack gap={6}>
            {report.checks.map((c) => (
              <Group key={c.code} gap="xs" wrap="nowrap" align="flex-start">
                <ThemeIcon size="sm" radius="xl" color={c.ok ? 'teal' : c.ok === false ? 'red' : 'gray'}>
                  {c.ok ? <IconCheck size={12} /> : c.ok === false ? <IconX size={12} /> : <IconQuestionMark size={12} />}
                </ThemeIcon>
                <div>
                  <Text size="sm">{c.title}</Text>
                  {c.detail && (
                    <Text size="xs" c="dimmed">
                      {c.detail}
                    </Text>
                  )}
                </div>
              </Group>
            ))}
          </Stack>
        </Card>
        </Grid.Col>
      </Grid>

      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          Участники
        </Text>
        <Table.ScrollContainer minWidth={760}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Сотрудник</Table.Th>
                <Table.Th>Открыл карточку</Table.Th>
                <Table.Th>Откликнулся первым</Table.Th>
                <Table.Th>Решений</Table.Th>
                <Table.Th>Заявок</Table.Th>
                <Table.Th>Действий</Table.Th>
                <Table.Th>Оценка</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.people.map((p) => (
                <Table.Tr key={p.user}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {p.name} {p.silent && <IconEyeOff size={14} style={{ verticalAlign: 'middle' }} />}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {ROLE[p.role] ?? p.role}
                      {p.silent && ' · молчащий'}
                    </Text>
                  </Table.Td>
                  <Table.Td>{t(p.first_view)}</Table.Td>
                  <Table.Td>{p.responded ? `${p.responded} · ${t(p.first_response)}` : '—'}</Table.Td>
                  <Table.Td>{p.decisions || '—'}</Table.Td>
                  <Table.Td>{p.workorders || '—'}</Table.Td>
                  <Table.Td>{p.actions || '—'}</Table.Td>
                  <Table.Td>
                    <Badge
                      variant="light"
                      color={
                        p.verdict.startsWith('выполнил') || p.verdict === 'участвовал'
                          ? 'teal'
                          : p.verdict.startsWith('вмешался')
                            ? 'orange'
                            : 'gray'
                      }
                    >
                      {p.verdict}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>

      <Card withBorder radius="md">
        <Text fw={600} mb="sm">
          Хронология
        </Text>
        <Timeline bulletSize={14} lineWidth={2}>
          {report.timeline.map((r, i) => (
            <Timeline.Item key={i} color={KIND_COLOR[r.kind] ?? 'gray'}>
              <Group gap="xs" wrap="wrap">
                <Text size="xs" c="dimmed" ff="monospace" w={56}>
                  {t(r.t)}
                </Text>
                <Text size="sm">
                  {r.incident ? (
                    <Anchor component={Link} to={`/incidents/${r.incident}`} size="sm">
                      {r.text}
                    </Anchor>
                  ) : (
                    r.text
                  )}
                </Text>
                {r.who && (
                  <Badge variant="default" size="sm">
                    {r.who}
                  </Badge>
                )}
              </Group>
            </Timeline.Item>
          ))}
        </Timeline>
      </Card>
    </>
  )
}

export function ExerciseDetailPage() {
  const { id } = useParams()
  const client = useQueryClient()
  const [stopOpen, setStopOpen] = useState(false)
  const [reason, setReason] = useState('')
  const q = useQuery({
    queryKey: ['exercises', id],
    queryFn: () => api<Exercise>(`/exercises/${id}/`),
    refetchInterval: (query) => (['running', 'scheduled'].includes(query.state.data?.status ?? '') ? 5000 : false),
  })
  const e = q.data
  const now = useNow(e?.status === 'running' || e?.status === 'scheduled')
  const act = useMutation({
    mutationFn: (action: string) =>
      api<Exercise>(`/exercises/${id}/${action}/`, { method: 'POST', body: action === 'stop' ? { reason } : {} }),
    onSuccess: (data) => {
      client.setQueryData(['exercises', id], data)
      void client.invalidateQueries({ queryKey: ['exercises'] })
      setStopOpen(false)
    },
    onError: (err) => notifications.show({ color: 'red', message: err.message }),
  })
  if (!e) return null

  const status = EXERCISE_STATUS[e.status]
  const running = e.status === 'running'
  const left = e.ends_at ? Math.max(0, Math.round((new Date(e.ends_at).getTime() - now) / 1000)) : null
  const toStart = e.scheduled_at ? Math.round((new Date(e.scheduled_at).getTime() - now) / 1000) : null

  return (
    <Stack>
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Anchor component={Link} to="/exercises" size="sm">
            ← Все учения
          </Anchor>
          <Title order={3}>{e.title}</Title>
          <Group gap="xs" mt={4}>
            <Badge color={status.color}>{status.label}</Badge>
            <Text size="sm" c="dimmed">
              {e.object} · начало {when(e)} · руководитель {e.created_by}
            </Text>
          </Group>
        </div>
        {e.manager && (
          <Group gap="xs">
            {e.status === 'scheduled' && (
              <Button leftSection={<IconPlayerPlay size={16} />} color="red" loading={act.isPending} onClick={() => act.mutate('start')}>
                Начать сейчас
              </Button>
            )}
            {running && (
              <Button leftSection={<IconFlag size={16} />} variant="light" loading={act.isPending} onClick={() => act.mutate('finish')}>
                Завершить
              </Button>
            )}
            {(running || e.status === 'scheduled') && (
              <Button leftSection={<IconPlayerStop size={16} />} color="orange" variant="outline" onClick={() => setStopOpen(true)}>
                {running ? 'Прекратить досрочно' : 'Отменить'}
              </Button>
            )}
          </Group>
        )}
      </Group>

      {e.status === 'scheduled' && (
        <Alert color="blue" icon={<IconFlag size={18} />}>
          {toStart !== null && toStart > 0
            ? `Старт по таймеру через ${mmss(toStart)}`
            : toStart !== null
              ? 'Старт по таймеру — вот-вот'
              : 'Старт — по кнопке руководителя'}
          . Участники оповещены{e.participants.filter((p) => p.confirmed_at).length ? `, ознакомлены ${e.participants.filter((p) => p.confirmed_at).length} из ${e.participants.length}` : ''}.
        </Alert>
      )}
      {running && (
        <Alert color="red" icon={<IconPlayerPlay size={18} />} title="Учения идут">
          Прошло {mmss(Math.round((now - new Date(e.started_at!).getTime()) / 1000))}
          {left !== null && `, до конца ${mmss(left)}`}. Карточки на объекте «{e.object}» — часть учений.
        </Alert>
      )}
      {e.status === 'stopped' && (
        <Alert color="orange" icon={<IconHandStop size={18} />}>
          Прекращены досрочно{e.stopped_by && ` (${e.stopped_by})`}
          {e.stop_reason && `: ${e.stop_reason}`}. Объект возвращён в норму.
        </Alert>
      )}
      {e.me?.silent && e.status !== 'finished' && e.status !== 'stopped' && (
        <Alert color="grape" icon={<IconEyeOff size={18} />} title="Ваша роль — «молчащий»">
          Не реагируйте на карточки учений: проверяется, сработает ли эскалация и подхватят ли карточку коллеги.
        </Alert>
      )}
      {e.me && !e.me.confirmed_at && e.status === 'scheduled' && (
        <Group>
          <Button variant="light" leftSection={<IconCheck size={16} />} onClick={() => act.mutate('confirm')}>
            Ознакомлен(а)
          </Button>
        </Group>
      )}

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Настройки
          </Text>
          <Stack gap={4}>
            <Text size="sm">Сценарий: {e.scenario_display ?? 'сообщается после учений'}</Text>
            {e.speed !== null && <Text size="sm">Темп: ×{e.speed}</Text>}
            {e.complication_display && (
              <Text size="sm">
                Осложнение: {e.complication_display} через {e.complication_after_min} мин
              </Text>
            )}
            <Text size="sm">Длительность: {e.duration_min} мин</Text>
            {e.briefing && (
              <Text size="sm" c="dimmed">
                Вводная: {e.briefing}
              </Text>
            )}
          </Stack>
        </Card>
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Участники · {e.participants.length}
          </Text>
          <Stack gap={4}>
            {e.participants.map((p) => (
              <Group key={p.user} justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {p.name}{' '}
                  <Text span size="xs" c="dimmed">
                    {ROLE[p.role] ?? p.role}
                  </Text>
                </Text>
                <Group gap={4} wrap="nowrap">
                  {p.silent && (
                    <Badge size="xs" color="grape" variant="light">
                      молчащий
                    </Badge>
                  )}
                  <Badge size="xs" variant="light" color={p.confirmed_at ? 'teal' : 'gray'}>
                    {p.confirmed_at ? 'ознакомлен' : 'оповещён'}
                  </Badge>
                </Group>
              </Group>
            ))}
          </Stack>
        </Card>
      </SimpleGrid>

      {e.report && Object.keys(e.report).length > 0 && <Report report={e.report} live={running} />}

      <Modal opened={stopOpen} onClose={() => setStopOpen(false)} title={running ? 'Прекратить учения досрочно' : 'Отменить учения'}>
        <Stack>
          <Text size="sm">
            {running
              ? 'Сценарий остановится, объект полигона вернётся в норму, участники получат уведомление. Разбор сохранится за прошедшее время.'
              : 'Участники получат уведомление об отмене.'}
          </Text>
          <TextInput label="Причина" placeholder="например, реальная тревога в районе" value={reason} onChange={(ev) => setReason(ev.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setStopOpen(false)}>
              Назад
            </Button>
            <Button color="orange" loading={act.isPending} onClick={() => act.mutate('stop')}>
              {running ? 'Прекратить' : 'Отменить учения'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
