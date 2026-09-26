import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core'
import { DateTimePicker } from '@mantine/dates'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconFlag, IconPlus, IconRoute } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { ROLE } from '../api/labels'
import { EXERCISE_STATUS, when } from '../api/exercises'
import type { Exercise, ExerciseOptions } from '../api/types'
import { useAuth } from '../auth/AuthContext'

/** Настройка учений: сценарий, объект полигона, темп, осложнение, участники, старт по кнопке или таймеру. */
function SetupForm({ onDone }: { onDone: () => void }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [node, setNode] = useState<string | null>(null)
  const options = useQuery({
    queryKey: ['exercise-options', node],
    queryFn: () => api<ExerciseOptions>('/exercises/options/', { query: { node } }),
  })
  const [title, setTitle] = useState('')
  const [scenario, setScenario] = useState<string | null>('fire')
  const [speed, setSpeed] = useState('2')
  const [complication, setComplication] = useState<string | null>(null)
  const [after, setAfter] = useState<number | string>(3)
  const [duration, setDuration] = useState<number | string>(30)
  const [briefing, setBriefing] = useState('')
  const [mode, setMode] = useState('button')
  const [at, setAt] = useState<string | null>(null)
  const [chosen, setChosen] = useState<number[]>([])
  const [silent, setSilent] = useState<number[]>([])

  const create = useMutation({
    mutationFn: () =>
      api<Exercise>('/exercises/', {
        method: 'POST',
        body: {
          title,
          scenario,
          node: node ?? options.data?.node,
          speed: Number(speed),
          complication: complication ?? '',
          complication_after_min: Number(after),
          duration_min: Number(duration),
          briefing,
          scheduled_at: mode === 'timer' && at ? dayjs(at).toISOString() : null,
          participants: chosen,
          silent: silent.filter((id) => chosen.includes(id)),
        },
      }),
    onSuccess: (e) => {
      notifications.show({ color: 'teal', message: `Учения назначены, участники оповещены: ${e.participants.length}` })
      void client.invalidateQueries({ queryKey: ['exercises'] })
      onDone()
      navigate(`/exercises/${e.id}`)
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })

  const data = options.data
  const current = data?.scenarios.find((s) => s.code === scenario)
  const toggle = (id: number) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))

  return (
    <Card withBorder radius="md">
      <Text fw={600} mb="sm">
        Новые учения
      </Text>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Stack gap="sm">
          <TextInput
            label="Название"
            placeholder="по умолчанию — сценарий и объект"
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
          />
          <Select
            label="Сценарий"
            data={(data?.scenarios ?? []).map((s) => ({ value: s.code, label: s.title }))}
            value={scenario}
            onChange={setScenario}
            description={current?.description}
            allowDeselect={false}
          />
          <Select
            label="Объект полигона"
            data={(data?.objects ?? []).map((o) => ({ value: String(o.id), label: o.name }))}
            value={node ?? (data?.node ? String(data.node) : null)}
            onChange={(v) => {
              setNode(v)
              setChosen([])
            }}
            allowDeselect={false}
          />
          <div>
            <Text size="sm" fw={500} mb={4}>
              Темп нарастания
            </Text>
            <SegmentedControl
              fullWidth
              value={speed}
              onChange={setSpeed}
              data={[
                { value: '1', label: 'как в жизни' },
                { value: '2', label: '×2' },
                { value: '5', label: '×5' },
              ]}
            />
          </div>
          <Group grow align="flex-start">
            <Select
              label="Осложнение"
              placeholder="без осложнения"
              clearable
              data={(data?.complications ?? []).map((c) => ({ value: c.code, label: c.title }))}
              value={complication}
              onChange={setComplication}
            />
            <NumberInput
              label="через, мин"
              min={1}
              max={60}
              value={after}
              onChange={setAfter}
              disabled={!complication}
            />
          </Group>
          <NumberInput
            label="Длительность, мин"
            description="по истечении учения завершаются сами и строится разбор"
            min={5}
            max={240}
            value={duration}
            onChange={setDuration}
          />
          <Textarea
            label="Вводная для участников"
            description="придёт в уведомлении; сценарий участникам не раскрывается"
            autosize
            minRows={2}
            value={briefing}
            onChange={(e) => setBriefing(e.currentTarget.value)}
          />
          <div>
            <Text size="sm" fw={500} mb={4}>
              Начало
            </Text>
            <SegmentedControl
              fullWidth
              value={mode}
              onChange={setMode}
              data={[
                { value: 'button', label: 'По кнопке' },
                { value: 'timer', label: 'По таймеру' },
              ]}
            />
            {mode === 'timer' && (
              <DateTimePicker
                mt="xs"
                placeholder="дата и время начала"
                minDate={new Date()}
                value={at}
                onChange={setAt}
                valueFormat="DD.MM.YYYY HH:mm"
              />
            )}
          </div>
        </Stack>

        <Stack gap="xs">
          <Group justify="space-between">
            <Text size="sm" fw={500}>
              Участники · выбрано {chosen.length}
            </Text>
            <Tooltip label="«Молчащий» получает скрытую вводную не реагировать — проверяется эскалация и взаимозаменяемость">
              <Text size="xs" c="dimmed" td="underline" style={{ cursor: 'help' }}>
                кто такой «молчащий»?
              </Text>
            </Tooltip>
          </Group>
          <Stack gap={4} mah={520} style={{ overflowY: 'auto' }}>
            {(data?.candidates ?? []).map((c) => (
              <Card key={c.id} withBorder padding="xs" radius="sm">
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <Checkbox
                    checked={chosen.includes(c.id)}
                    onChange={() => toggle(c.id)}
                    label={c.name}
                    description={
                      <>
                        {c.roles.map((r) => ROLE[r] ?? r).join(', ')} · {c.team ?? c.zone}
                        {!c.sees && (
                          <Text span size="xs" c="orange" display="block">
                            не видит карточек этого объекта
                          </Text>
                        )}
                      </>
                    }
                  />
                  {chosen.includes(c.id) && (
                    <Switch
                      size="xs"
                      label="молчащий"
                      checked={silent.includes(c.id)}
                      onChange={(e) => {
                        const on = e.currentTarget.checked
                        setSilent((s) => (on ? [...s, c.id] : s.filter((x) => x !== c.id)))
                      }}
                    />
                  )}
                </Group>
              </Card>
            ))}
          </Stack>
        </Stack>
      </SimpleGrid>
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={onDone}>
          Отмена
        </Button>
        <Button
          leftSection={<IconFlag size={16} />}
          loading={create.isPending}
          disabled={!chosen.length || (mode === 'timer' && !at)}
          onClick={() => create.mutate()}
        >
          Назначить и оповестить участников
        </Button>
      </Group>
    </Card>
  )
}

export function ExercisesPage() {
  const { user, can } = useAuth()
  const [setup, setSetup] = useState(false)
  const list = useQuery({
    queryKey: ['exercises'],
    queryFn: () => api<Exercise[]>('/exercises/'),
    refetchInterval: 15_000,
  })
  const manager = can('training.add_exercise')
  const training = user?.contour.code === 'training'

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Учения</Title>
        {manager && training && !setup && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setSetup(true)}>
            Настроить учения
          </Button>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        Отработка всей цепочки на полигоне: руководитель задаёт сценарий, темп и осложнение, назначает участников и
        запускает учения по кнопке или по таймеру. Карточки, эскалации и заявки во время учений — настоящие, по итогам —
        разбор с хронологией и проверками.
      </Text>
      {!training && (
        <Alert color="violet" icon={<IconRoute size={18} />} title="Учения проходят в учебном контуре">
          <Group justify="space-between" wrap="wrap">
            <Text size="sm">Там полигон и учебные данные, на работу района учения не влияют.</Text>
            <Button component="a" href={user?.contour.urls.training} target="_blank" color="violet" size="xs">
              Открыть учебный контур
            </Button>
          </Group>
        </Alert>
      )}
      {setup && <SetupForm onDone={() => setSetup(false)} />}

      <Card withBorder radius="md">
        {list.data?.length ? (
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Учения</Table.Th>
                  <Table.Th>Статус</Table.Th>
                  <Table.Th>Объект</Table.Th>
                  <Table.Th>Начало</Table.Th>
                  <Table.Th>Участников</Table.Th>
                  <Table.Th>Итог</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data.map((e) => (
                  <Table.Tr key={e.id}>
                    <Table.Td>
                      <Text component={Link} to={`/exercises/${e.id}`} size="sm" fw={500} c="blue">
                        {e.title}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {e.scenario_display ?? 'сценарий скрыт до конца учений'}
                        {e.me?.silent && ' · вы «молчащий»'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={EXERCISE_STATUS[e.status].color}>
                        {EXERCISE_STATUS[e.status].label}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{e.object}</Table.Td>
                    <Table.Td>{when(e)}</Table.Td>
                    <Table.Td>{e.participants.length}</Table.Td>
                    <Table.Td>
                      {e.report?.score ? `${e.report.score.passed} из ${e.report.score.total}` : '—'}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        ) : (
          <Group gap="xs">
            <IconAlertTriangle size={16} color="var(--mantine-color-dimmed)" />
            <Text size="sm" c="dimmed">
              {manager ? 'Учений пока не было.' : 'Вас пока не назначали на учения.'}
            </Text>
          </Group>
        )}
      </Card>
    </Stack>
  )
}
