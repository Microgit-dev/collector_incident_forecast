import { Card, Checkbox, Group, Progress, SimpleGrid, Stack, Text, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'

import { api } from '../api/client'
import { PRIORITY_FACTOR } from '../api/labels'
import type { IncidentDetail } from '../api/types'
import { ContourBadge, PriorityBadge } from './badges'

function duration(from: string | null, to: string | null) {
  if (!from || !to) return '—'
  const minutes = Math.max(0, dayjs(to).diff(dayjs(from), 'minute'))
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  return hours < 48 ? `${hours} ч ${minutes % 60} мин` : `${Math.round(hours / 24)} сут`
}

export function EpisodeCard({ incident }: { incident: IncidentDetail }) {
  const factors = Object.entries(incident.priority_factors ?? {})
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>Эпизод</Text>
          <ContourBadge contour={incident.contour} />
        </Group>
        <Tooltip
          label={
            <Stack gap={2}>
              {factors.map(([k, v]) => (
                <Text key={k} size="xs">
                  {PRIORITY_FACTOR[k] ?? k}: ×{v}
                </Text>
              ))}
            </Stack>
          }
        >
          <Group gap={6}>
            <Text size="sm" c="dimmed">
              приоритет
            </Text>
            <PriorityBadge value={incident.priority} />
          </Group>
        </Tooltip>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <div>
          <Text size="xs" c="dimmed">
            Сигналов
          </Text>
          <Text fw={700} fz="lg">
            {incident.signals_count}
          </Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Каналов
          </Text>
          <Text fw={700} fz="lg">
            {incident.channels_count}
          </Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Первый — последний сигнал
          </Text>
          <Text size="sm">
            {incident.first_signal_at ? dayjs(incident.first_signal_at).format('DD.MM HH:mm:ss') : '—'} —{' '}
            {incident.last_signal_at ? dayjs(incident.last_signal_at).format('HH:mm:ss') : '—'}
          </Text>
        </div>
        <div>
          <Text size="xs" c="dimmed">
            Длительность
          </Text>
          <Text size="sm">{duration(incident.first_signal_at, incident.last_signal_at)}</Text>
        </div>
      </SimpleGrid>
      {incident.data_confidence !== null && (
        <Text size="xs" c="dimmed" mt="xs">
          Средний балл качества данных каналов эпизода: {Math.round(incident.data_confidence)}
        </Text>
      )}
    </Card>
  )
}

export function HypothesesCard({ incident }: { incident: IncidentDetail }) {
  if (!incident.hypotheses?.length) return null
  return (
    <Card withBorder radius="md">
      <Text fw={600} mb="xs">
        Вероятные причины
      </Text>
      <Stack gap="sm">
        {incident.hypotheses.map((h, i) => (
          <div key={h.code}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" fw={i === 0 ? 600 : 400}>
                {h.title}
              </Text>
              <Text size="sm" c="dimmed">
                {Math.round(h.weight * 100)} %
              </Text>
            </Group>
            <Progress value={h.weight * 100} size="sm" color={i === 0 ? 'blue' : 'gray'} mt={2} />
            {h.evidence.map((e) => (
              <Text key={e} size="xs" c="dimmed">
                • {e}
              </Text>
            ))}
          </div>
        ))}
      </Stack>
      <Text size="xs" c="dimmed" mt="xs">
        Гипотезы строятся правилами по составу сигналов, истории каналов, работам на объекте и времени суток. Решение
        остаётся за диспетчером.
      </Text>
    </Card>
  )
}

export function ActionsCard({ incident, canEdit }: { incident: IncidentDetail; canEdit: boolean }) {
  const queryClient = useQueryClient()
  const mark = useMutation({
    mutationFn: ({ code, done }: { code: string; done: boolean }) =>
      api<IncidentDetail>(`/incidents/items/${incident.id}/checklist/`, { method: 'POST', body: { code, done } }),
    onSuccess: (data) => queryClient.setQueryData(['incidents', incident.id], data),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  if (!incident.actions?.length) return null
  const done = incident.actions.filter((a) => a.done).length
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Что делать</Text>
        <Text size="sm" c="dimmed">
          {done} из {incident.actions.length}
        </Text>
      </Group>
      <Stack gap={6}>
        {incident.actions.map((a) => (
          <Checkbox
            key={a.code}
            checked={a.done}
            disabled={!canEdit || mark.isPending}
            onChange={(e) => mark.mutate({ code: a.code, done: e.currentTarget.checked })}
            label={
              <Text size="sm" td={a.done ? 'line-through' : undefined} c={a.done ? 'dimmed' : undefined}>
                {a.title}
              </Text>
            }
            description={a.done && a.done_by ? `${a.done_by}, ${dayjs(a.done_at).format('DD.MM HH:mm')}` : undefined}
          />
        ))}
      </Stack>
    </Card>
  )
}
