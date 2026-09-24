import {
  Anchor,
  Badge,
  Button,
  Card,
  Chip,
  Grid,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  Timeline,
  Title,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconArrowUp, IconClipboardPlus, IconHandGrab, IconHandOff, IconChecklist } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { CAUSE, INCIDENT_TYPE, OUTCOME } from '../api/labels'
import type { DecisionCause, DecisionOutcome, DecisionReason, IncidentDetail } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RiskBadge, StatusBadge } from '../components/badges'
import { ActionsCard, EpisodeCard, HypothesesCard } from '../components/EpisodePanels'

function DecisionModal({ incident, opened, onClose }: { incident: IncidentDetail; opened: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [cause, setCause] = useState<DecisionCause | ''>('')
  const [useful, setUseful] = useState<'yes' | 'no' | 'unknown'>('unknown')

  const reasons = useQuery({
    queryKey: ['decision-reasons'],
    queryFn: () => api<Page<DecisionReason>>('/incidents/reasons/', { query: { is_active: true, page_size: 200 } }),
    staleTime: 10 * 60_000,
  })

  const decide = useMutation({
    mutationFn: () =>
      api<IncidentDetail>(`/incidents/items/${incident.id}/decide/`, {
        method: 'POST',
        body: {
          outcome,
          reason: reason ? Number(reason) : null,
          comment,
          cause,
          forecast_useful: incident.is_forecast && useful !== 'unknown' ? useful === 'yes' : null,
        },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['incidents', incident.id], data)
      void queryClient.invalidateQueries({ queryKey: ['incidents'] })
      notifications.show({ color: 'teal', message: 'Решение зафиксировано' })
      onClose()
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })

  const reasonOptions = (reasons.data?.results ?? [])
    .filter((r) => r.outcome === outcome)
    .map((r) => ({ value: String(r.id), label: r.name }))

  return (
    <Modal opened={opened} onClose={onClose} title="Решение по инциденту" size="lg">
      <Stack>
        <div>
          <Text size="sm" fw={500} mb={6}>
            Что произошло на самом деле
          </Text>
          <Chip.Group multiple={false} value={cause} onChange={(v) => setCause(v as DecisionCause)}>
            <Group gap={6}>
              {(Object.keys(CAUSE) as DecisionCause[]).map((c) => (
                <Chip key={c} value={c} size="sm" variant="light">
                  {CAUSE[c].label}
                </Chip>
              ))}
            </Group>
          </Chip.Group>
          <Text size="xs" c="dimmed" mt={6}>
            {cause
              ? `Для модели отказа датчиков: ${CAUSE[cause].hint}.`
              : 'Ответ попадает в обратную связь: аналитик видит, как решения диспетчеров влияют на обучение моделей.'}
          </Text>
        </div>
        {incident.is_forecast && (
          <div>
            <Text size="sm" fw={500} mb={6}>
              Прогноз помог?
            </Text>
            <SegmentedControl
              value={useful}
              onChange={(v) => setUseful(v as typeof useful)}
              data={[
                { value: 'yes', label: 'Да, успели среагировать' },
                { value: 'no', label: 'Нет, бесполезен' },
                { value: 'unknown', label: 'Не ясно' },
              ]}
            />
          </div>
        )}
        <Select
          label="Решение"
          data={Object.entries(OUTCOME).map(([value, label]) => ({ value, label }))}
          value={outcome}
          onChange={(v) => {
            setOutcome(v as DecisionOutcome)
            setReason(null)
          }}
          required
        />
        <Select label="Причина" data={reasonOptions} value={reason} onChange={setReason} disabled={!outcome} clearable />
        <Textarea label="Комментарий" value={comment} onChange={(e) => setComment(e.currentTarget.value)} autosize minRows={2} />
        <Button onClick={() => decide.mutate()} loading={decide.isPending} disabled={!outcome}>
          Зафиксировать
        </Button>
      </Stack>
    </Modal>
  )
}

export function IncidentDetailPage() {
  const { id } = useParams()
  const { user, can } = useAuth()
  const queryClient = useQueryClient()
  const [decisionOpened, decisionModal] = useDisclosure()

  const { data: incident, isLoading } = useQuery({
    queryKey: ['incidents', Number(id)],
    queryFn: () => api<IncidentDetail>(`/incidents/items/${id}/`),
    refetchInterval: 20_000,
  })

  const action = useMutation({
    mutationFn: (name: 'take' | 'release' | 'escalate' | 'acknowledge') =>
      api<IncidentDetail>(`/incidents/items/${id}/${name}/`, { method: 'POST', body: {} }),
    onSuccess: (data) => {
      queryClient.setQueryData(['incidents', Number(id)], data)
      void queryClient.invalidateQueries({ queryKey: ['incidents'] })
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })

  const draft = useMutation({
    mutationFn: () => api<{ number: string }>(`/workorders/items/from-incident/${id}/`, { method: 'POST', body: {} }),
    onSuccess: (order) => {
      notifications.show({ color: 'teal', message: `Создан черновик заявки ${order.number}` })
      void queryClient.invalidateQueries({ queryKey: ['incidents', Number(id)] })
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })

  if (isLoading || !incident) return <Loader />

  const open = ['new', 'acknowledged', 'in_progress'].includes(incident.status)
  const mine = incident.assigned_to === user?.id
  const lockedByOther = incident.assigned_to !== null && !mine

  return (
    <Stack>
      <Anchor component={Link} to="/incidents" size="sm">
        ← К списку инцидентов
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Group gap="xs">
            <RiskBadge level={incident.severity} />
            <StatusBadge status={incident.status} />
            {incident.is_forecast && <Badge variant="outline">прогноз</Badge>}
            {incident.is_emulated && (
              <Badge color="orange" variant="light">
                эмуляция смены
              </Badge>
            )}
            {incident.escalation_level > 0 && <Badge color="grape">эскалация ×{incident.escalation_level}</Badge>}
          </Group>
          <Title order={3}>{incident.title}</Title>
          <Text c="dimmed" size="sm">
            {INCIDENT_TYPE[incident.type]} · {incident.node_name} · открыт {dayjs(incident.opened_at).format('DD.MM.YYYY HH:mm')}
          </Text>
        </Stack>

        {open && (
          <Group gap="xs">
            {!mine && can('incidents.change_incident') && (
              <Button leftSection={<IconHandGrab size={16} />} onClick={() => action.mutate('take')} disabled={lockedByOther} loading={action.isPending}>
                Взять в работу
              </Button>
            )}
            {mine && (
              <Button variant="default" leftSection={<IconHandOff size={16} />} onClick={() => action.mutate('release')}>
                Освободить
              </Button>
            )}
            {can('incidents.decide_incident') && (
              <Button color="teal" leftSection={<IconChecklist size={16} />} onClick={decisionModal.open} disabled={lockedByOther}>
                Решение
              </Button>
            )}
            {can('workorders.add_workorder') && (
              <Button variant="light" leftSection={<IconClipboardPlus size={16} />} onClick={() => draft.mutate()} loading={draft.isPending}>
                Черновик заявки
              </Button>
            )}
            {can('incidents.escalate_incident') && (
              <Button variant="light" color="grape" leftSection={<IconArrowUp size={16} />} onClick={() => action.mutate('escalate')}>
                Эскалировать
              </Button>
            )}
          </Group>
        )}
      </Group>

      {lockedByOther && (
        <Text c="orange" size="sm">
          Карточка в работе у {incident.assigned_to_name}. Действия доступны только ему.
        </Text>
      )}

      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack>
            <EpisodeCard incident={incident} />
            <HypothesesCard incident={incident} />
            <ActionsCard incident={incident} canEdit={open && !lockedByOther && can('incidents.change_incident')} />
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Ответственность
              </Text>
              <Text size="sm">Уровень: {incident.responsible_node_name}</Text>
              <Text size="sm">В работе у: {incident.assigned_to_name || 'не назначен'}</Text>
              {incident.ack_deadline && incident.status === 'new' && (
                <Text size="sm" c="red">
                  Реакция до {dayjs(incident.ack_deadline).format('DD.MM HH:mm')} — затем эскалация
                </Text>
              )}
              {incident.probability !== null && (
                <Text size="sm">
                  Вероятность: {(incident.probability * 100).toFixed(0)}% на {incident.horizon_hours} ч
                </Text>
              )}
            </Card>
            <Card withBorder radius="md">
              <Text fw={600} mb="xs">
                Сигналы ({incident.signals_count > incident.alerts.length
                  ? `последние ${incident.alerts.length} из ${incident.signals_count}`
                  : incident.alerts.length})
              </Text>
              <Stack gap="xs">
                {incident.alerts.map((alert) => (
                  <Group key={alert.id} justify="space-between" wrap="nowrap">
                    <Text size="sm">{alert.title}</Text>
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                      {dayjs(alert.raised_at).format('DD.MM HH:mm:ss')}
                    </Text>
                  </Group>
                ))}
              </Stack>
            </Card>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <Card withBorder radius="md">
              <Text fw={600} mb="sm">
                Просмотрели карточку
              </Text>
              {incident.viewed_by.length === 0 ? (
                <Text size="sm" c="dimmed">
                  Пока никто
                </Text>
              ) : (
                <Stack gap={4}>
                  {incident.viewed_by.map((v) => (
                    <Group key={v.user} justify="space-between" gap="xs" wrap="nowrap">
                      <Text size="sm">
                        {v.name}
                        {v.position && (
                          <Text span size="xs" c="dimmed">
                            {' '}
                            · {v.position}
                          </Text>
                        )}
                      </Text>
                      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                        {dayjs(v.first_viewed_at).format('DD.MM HH:mm')}
                        {v.times > 1 && ` · ${v.times} раза`}
                      </Text>
                    </Group>
                  ))}
                </Stack>
              )}
            </Card>
            <Card withBorder radius="md">
              <Text fw={600} mb="sm">
                Хронология
              </Text>
              <Timeline bulletSize={14} lineWidth={2}>
                {incident.events.map((event) => (
                  <Timeline.Item key={event.id} title={event.text || event.kind}>
                    <Text size="xs" c="dimmed">
                      {dayjs(event.ts).format('DD.MM HH:mm:ss')}
                      {event.actor_name && ` · ${event.actor_name}`}
                    </Text>
                  </Timeline.Item>
                ))}
              </Timeline>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

      <DecisionModal incident={incident} opened={decisionOpened} onClose={decisionModal.close} />
    </Stack>
  )
}
