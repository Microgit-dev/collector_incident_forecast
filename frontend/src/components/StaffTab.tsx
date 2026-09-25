import { Badge, Card, Group, Loader, Progress, SimpleGrid, Table, Text, Tooltip } from '@mantine/core'
import { IconTrophy } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { StaffMetrics } from '../api/types'

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)} %`)
const min = (v: number | null) => (v === null ? '—' : `${v} мин`)

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card withBorder padding="sm" radius="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={26} fw={700}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
}

/** «Кто первый»: отклики первым, гонки, качество решений, нагрузка на смену, обучение — по людям и командам. */
export function StaffTab({ query, emulated }: { query: { from: string; to: string }; emulated: boolean }) {
  const staff = useQuery({
    queryKey: ['staff', query, emulated],
    queryFn: () => api<StaffMetrics>('/analytics/staff/', { query: { ...query, include_emulated: emulated } }),
    enabled: Boolean(query.from && query.to),
  })
  if (staff.isLoading || !staff.data) return <Loader />
  const { summary, people, teams } = staff.data
  const active = people.filter((p) => p.active)
  const best = Math.max(...active.map((p) => p.responded), 1)

  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 5 }} mb="md">
        <Stat label="Карточек" value={String(summary.cards)} hint={`с откликом ${pct(summary.responded_share)}`} />
        <Stat
          label="До отклика, медиана"
          value={min(summary.response.median)}
          hint={`90 % — за ${min(summary.response.p90)}`}
        />
        <Stat
          label="Гонок"
          value={String(summary.contested)}
          hint={`${pct(summary.contested_share)} карточек открыли двое и больше до отклика`}
        />
        <Stat label="Эскалаций без отклика" value={String(summary.escalated_unanswered)} hint="никто не успел в срок" />
        <Stat label="Перехватов" value={String(summary.takeovers)} hint="руководитель забрал карточку" />
      </SimpleGrid>

      <Card withBorder radius="md" mb="md">
        <Group justify="space-between" mb={4}>
          <Text fw={600}>Кто первый: рейтинг смены</Text>
          <Text size="xs" c="dimmed">
            Правило смены — карточку забирает откликнувшийся первым
          </Text>
        </Group>
        <Text size="xs" c="dimmed" mb="sm">
          Доля зоны — на сколько карточек своей зоны сотрудник откликнулся первым. Гонки — карточки, которые до отклика
          открыли несколько диспетчеров. Качество — доля карточек пожара, газа, воды и проникновения, закрытых как
          ложные, после которых угроза не повторилась на объекте в течение 6 часов.
        </Text>
        <Table.ScrollContainer minWidth={1100}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>№</Table.Th>
                <Table.Th>Сотрудник</Table.Th>
                <Table.Th>Первым откликнулся</Table.Th>
                <Table.Th>Доля зоны</Table.Th>
                <Table.Th>Заметил первым</Table.Th>
                <Table.Th>До отклика</Table.Th>
                <Table.Th>Гонки</Table.Th>
                <Table.Th>До решения</Table.Th>
                <Table.Th>Качество</Table.Th>
                <Table.Th>На смену</Table.Th>
                <Table.Th>Перехвачено</Table.Th>
                <Table.Th>Обучение</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {active.map((p) => (
                <Table.Tr key={p.user}>
                  <Table.Td>
                    {p.rank === 1 ? <IconTrophy size={18} color="var(--mantine-color-yellow-6)" /> : (p.rank ?? '—')}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {p.name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {p.team ?? p.zone}
                    </Text>
                  </Table.Td>
                  <Table.Td miw={150}>
                    <Group gap="xs" wrap="nowrap">
                      <Progress value={(100 * p.responded) / best} w={70} size="sm" />
                      <Text size="sm">{p.responded}</Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Tooltip label={`из ${p.zone_cards} карточек зоны «${p.zone}»`}>
                      <Text size="sm">{pct(p.responded_share)}</Text>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>{p.first_seen}</Table.Td>
                  <Table.Td>{min(p.response_median)}</Table.Td>
                  <Table.Td>
                    {p.races ? (
                      <Tooltip label="выиграно из гонок, в которых участвовал">
                        <Text size="sm">
                          {p.races_won} из {p.races}
                        </Text>
                      </Tooltip>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                  <Table.Td>{min(p.decision_median)}</Table.Td>
                  <Table.Td>
                    {p.closed ? (
                      <Tooltip label={`закрыто как ложные ${p.closed}, повторилось ${p.repeated}; метки: принято ${p.labels_accepted}, отклонено ${p.labels_rejected}`}>
                        <Badge variant="light" color={p.quality !== null && p.quality < 0.8 ? 'orange' : 'teal'}>
                          {pct(p.quality)}
                        </Badge>
                      </Tooltip>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Tooltip label={`смен в периоде: ${p.shifts}`}>
                      <Text size="sm">{p.per_shift ?? '—'}</Text>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>{p.takeovers_lost || '—'}</Table.Td>
                  <Table.Td>
                    {p.training_done ? `${p.training_done} (ошибок ${p.training_mistakes})` : '—'}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {active.length === 0 && (
          <Text size="sm" c="dimmed">
            За период нет откликов и решений.
          </Text>
        )}
      </Card>

      {teams.length > 0 && (
        <Card withBorder radius="md">
          <Text fw={600} mb="xs">
            Команды
          </Text>
          <Table.ScrollContainer minWidth={760}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Команда</Table.Th>
                  <Table.Th>Сотрудников</Table.Th>
                  <Table.Th>Карточек зоны</Table.Th>
                  <Table.Th>Откликнулись первыми</Table.Th>
                  <Table.Th>До отклика</Table.Th>
                  <Table.Th>Эскалаций без отклика</Table.Th>
                  <Table.Th>Качество</Table.Th>
                  <Table.Th>Учебных заданий</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {teams.map((t) => (
                  <Table.Tr key={t.team}>
                    <Table.Td>{t.team}</Table.Td>
                    <Table.Td>{t.members}</Table.Td>
                    <Table.Td>{t.zone_cards}</Table.Td>
                    <Table.Td>
                      {t.responded} ({pct(t.responded_share)})
                    </Table.Td>
                    <Table.Td>{min(t.response_median)}</Table.Td>
                    <Table.Td>{t.escalated_unanswered}</Table.Td>
                    <Table.Td>{pct(t.quality)}</Table.Td>
                    <Table.Td>{t.training_done}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Card>
      )}
    </>
  )
}
