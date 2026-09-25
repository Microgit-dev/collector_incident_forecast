import { Alert, Badge, Button, Card, Group, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCertificate, IconRoute } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'

import { api } from '../api/client'
import type { TrainingLesson, TrainingSession } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { mmss } from '../training/spotlight'

const STATUS = {
  done: { label: 'Пройдено', color: 'teal' },
  abandoned: { label: 'Прервано', color: 'gray' },
  active: { label: 'Идёт', color: 'violet' },
}

export function TrainingPage() {
  const { user, can } = useAuth()
  const client = useQueryClient()
  const lessons = useQuery({
    queryKey: ['training-lessons'],
    queryFn: () => api<{ contour: string; lessons: TrainingLesson[] }>('/training/lessons/'),
  })
  const results = useQuery({
    queryKey: ['training-results'],
    queryFn: () => api<TrainingSession[]>('/training/sessions/'),
  })
  const current = useQuery({
    queryKey: ['training-current'],
    queryFn: () => api<TrainingSession | null>('/training/sessions/current/'),
  })
  const start = useMutation({
    mutationFn: (lesson: string) => api<TrainingSession>('/training/sessions/', { method: 'POST', body: { lesson } }),
    onSuccess: (s) => {
      notifications.show({
        color: 'violet',
        message: s.object ? `Задание началось на полигоне: ${s.object}` : 'Задание началось',
      })
      client.invalidateQueries({ queryKey: ['training-current'] })
      client.invalidateQueries({ queryKey: ['training-results'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })

  const training = lessons.data?.contour === 'training'
  const team = can('audit.view_actionlog')
  const active = current.data?.status === 'active' ? current.data : null

  return (
    <Stack>
      <Title order={3}>Учебные задания</Title>
      <Text size="sm" c="dimmed">
        Задания для вашей роли. На полигоне события запускает симулятор датчиков, а шаг засчитывается по вашему
        действию в системе: карточка принята, выбрана причина, заявка утверждена. Панель задания видна поверх любых
        экранов, кнопка «Показать где» подсвечивает нужный элемент.
      </Text>
      {!training && lessons.data && (
        <Alert color="violet" icon={<IconRoute size={18} />} title="Вы в рабочем контуре">
          <Group justify="space-between" wrap="wrap">
            <Text size="sm">
              Здесь доступна экскурсия по интерфейсу. Задания со сценариями проходят в учебном контуре: полигон и учебные
              данные, на работу района они не влияют.
            </Text>
            <Button component="a" href={user?.contour.urls.training} target="_blank" color="violet" size="xs">
              Открыть учебный контур
            </Button>
          </Group>
        </Alert>
      )}
      {active && (
        <Alert color="violet" icon={<IconCertificate size={18} />}>
          Сейчас идёт «{active.title}». Новое задание прервёт текущее.
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {(lessons.data?.lessons ?? []).map((l) => (
          <Card key={l.code} withBorder radius="md">
            <Stack gap="xs" h="100%" justify="space-between">
              <Stack gap={6}>
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <Text fw={600}>{l.title}</Text>
                  {l.best && (
                    <Badge color="teal" variant="light">
                      пройдено
                    </Badge>
                  )}
                </Group>
                <Text size="sm" c="dimmed">
                  {l.summary}
                </Text>
                <Group gap={6}>
                  <Badge variant="default">≈ {l.minutes} мин</Badge>
                  <Badge variant="default">шагов {l.steps}</Badge>
                  {l.polygon ? (
                    <Badge color="violet" variant="light">
                      полигон
                    </Badge>
                  ) : (
                    <Badge variant="light">экскурсия</Badge>
                  )}
                </Group>
                {l.best && (
                  <Text size="xs" c="dimmed">
                    Лучший результат: {mmss(l.best.elapsed_s)}, ошибок {l.best.mistakes} ·{' '}
                    {dayjs(l.best.finished_at).format('DD.MM HH:mm')}
                  </Text>
                )}
              </Stack>
              {l.available ? (
                <Button
                  variant={l.best ? 'light' : 'filled'}
                  color="violet"
                  loading={start.isPending && start.variables === l.code}
                  onClick={() => start.mutate(l.code)}
                >
                  {l.best ? 'Пройти ещё раз' : 'Начать'}
                </Button>
              ) : (
                <Button component="a" href={user?.contour.urls.training} target="_blank" variant="default">
                  В учебном контуре
                </Button>
              )}
            </Stack>
          </Card>
        ))}
      </SimpleGrid>

      <Card withBorder radius="md">
        <Text fw={600} mb="xs">
          {team ? 'Результаты сотрудников зоны' : 'Мои результаты'}
        </Text>
        {results.data?.length ? (
          <Table.ScrollContainer minWidth={720}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Когда</Table.Th>
                  {team && <Table.Th>Сотрудник</Table.Th>}
                  <Table.Th>Задание</Table.Th>
                  <Table.Th>Полигон</Table.Th>
                  <Table.Th>Итог</Table.Th>
                  <Table.Th>Время</Table.Th>
                  <Table.Th>Ошибок</Table.Th>
                  <Table.Th>Подсказок</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {results.data.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td>{dayjs(r.started_at).format('DD.MM HH:mm')}</Table.Td>
                    {team && <Table.Td>{r.user}</Table.Td>}
                    <Table.Td>{r.title}</Table.Td>
                    <Table.Td>{r.object ?? '—'}</Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={STATUS[r.status].color}>
                        {STATUS[r.status].label}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{mmss(r.elapsed_s)}</Table.Td>
                    <Table.Td>{r.mistakes}</Table.Td>
                    <Table.Td>{r.hints}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        ) : (
          <Text size="sm" c="dimmed">
            Пройденных заданий пока нет.
          </Text>
        )}
      </Card>
    </Stack>
  )
}
