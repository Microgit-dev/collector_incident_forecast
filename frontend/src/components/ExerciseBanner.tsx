import { Alert, Anchor, Button, Group, Text } from '@mantine/core'
import { IconFlag } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Exercise } from '../api/types'
import { CONTOUR, contourHref } from '../contour'

/**
 * Плашка участнику: назначенные и идущие учения, «ознакомлен», роль «молчащего».
 * Учения живут в учебном контуре, но плашка видна и в основной системе: участник узнаёт о них
 * на своём рабочем месте, а «Подробнее» ведёт в учебный контур без повторного входа.
 */
export function ExerciseBanner() {
  const client = useQueryClient()
  const mine = useQuery({
    queryKey: ['exercises', 'mine'],
    // учебный контур не запущен — просто нет плашки
    queryFn: () => api<Exercise[]>('/exercises/mine/', { contour: 'training' }).catch(() => [] as Exercise[]),
    refetchInterval: 30_000,
  })
  const confirm = useMutation({
    mutationFn: (id: number) => api<Exercise>(`/exercises/${id}/confirm/`, { method: 'POST', contour: 'training' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['exercises'] }),
  })
  if (!mine.data?.length) return null
  return (
    <>
      {mine.data.map((e) => {
        const running = e.status === 'running'
        return (
          <Alert
            key={e.id}
            mb="sm"
            color={running ? 'red' : 'blue'}
            variant={running ? 'filled' : 'light'}
            icon={<IconFlag size={18} />}
            py={8}
          >
            <Group justify="space-between" gap="xs" wrap="wrap">
              <Text size="sm">
                <b>{running ? 'Идут учения' : 'Вы участник учений'}</b>: {e.title} ·{' '}
                {running
                  ? `объект ${e.object}`
                  : e.scheduled_at
                    ? `начало ${dayjs(e.scheduled_at).format('DD.MM в HH:mm')}`
                    : 'начало по сигналу руководителя'}
                {e.me?.silent && ' · ваша роль — «молчащий»: не реагируйте на карточки'}
              </Text>
              <Group gap="xs">
                {!running && !e.me?.confirmed_at && (
                  <Button size="compact-sm" variant="white" onClick={() => confirm.mutate(e.id)} loading={confirm.isPending}>
                    Ознакомлен(а)
                  </Button>
                )}
                {CONTOUR === 'training' ? (
                  <Anchor component={Link} to={`/exercises/${e.id}`} size="sm" c={running ? 'white' : undefined}>
                    Подробнее
                  </Anchor>
                ) : (
                  <Anchor href={contourHref('training', `/exercises/${e.id}`)} size="sm" c={running ? 'white' : undefined}>
                    Подробнее в учебном контуре
                  </Anchor>
                )}
              </Group>
            </Group>
          </Alert>
        )
      })}
    </>
  )
}
