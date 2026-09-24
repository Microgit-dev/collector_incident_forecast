import { Badge, Card, Group, Loader, Progress, SegmentedControl, SimpleGrid, Stack, Table, Text, Title, Tooltip } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, type Page } from '../api/client'
import { HEALTH_COMPONENT } from '../api/labels'
import type { ChannelHealth, HealthSummary } from '../api/types'

const scoreColor = (s: number) => (s >= 80 ? 'teal' : s >= 50 ? 'yellow' : 'red')

function Components({ c }: { c: ChannelHealth['components'] }) {
  return (
    <Stack gap={2} miw={180}>
      {Object.entries(c)
        .filter(([, v]) => v != null)
        .map(([k, v]) => (
          <Tooltip key={k} label={`${HEALTH_COMPONENT[k]}: ${Math.round((v as number) * 100)} %`}>
            <Group gap={4} wrap="nowrap">
              <Text size="xs" w={90} truncate>
                {HEALTH_COMPONENT[k]}
              </Text>
              <Progress value={(v as number) * 100} color={scoreColor((v as number) * 100)} size="sm" style={{ flex: 1 }} />
            </Group>
          </Tooltip>
        ))}
    </Stack>
  )
}

function interval(seconds: number | null) {
  if (!seconds) return '—'
  return seconds >= 3600 ? `${Math.round(seconds / 3600)} ч` : `${Math.round(seconds / 60)} мин`
}

export function DataHealthPage() {
  const [view, setView] = useState<'poor' | 'silent'>('poor')
  const summary = useQuery({
    queryKey: ['health', 'summary'],
    queryFn: () => api<HealthSummary>('/forecasting/health/summary/'),
    refetchInterval: 60_000,
  })
  const list = useQuery({
    queryKey: ['health', view],
    queryFn: () =>
      api<Page<ChannelHealth>>('/forecasting/health/', {
        query: view === 'silent' ? { silent: true, page_size: 50, ordering: 'last_seen_at' } : { score__lt: 80, page_size: 50 },
      }),
  })
  const s = summary.data
  if (summary.isLoading) return <Loader />

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Здоровье каналов</Title>
        {s?.computed_at && (
          <Text size="sm" c="dimmed">
            на {dayjs(s.computed_at).format('DD.MM.YYYY HH:mm')}
          </Text>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        Data Health Score (0–100) показывает, насколько можно доверять данным канала: полнота и свежесть (для каналов с
        регулярными измерениями), время в исправном состоянии, стабильность частоты, согласованность с соседними
        датчиками. Низкий балл снижает доверие к прогнозу и сам по себе — повод проверить канал.
      </Text>
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        {[
          { label: 'Каналов оценено', value: s?.total, color: undefined },
          { label: 'Хорошо (80+)', value: s?.good, color: 'teal' },
          { label: 'Снижено (50–79)', value: s?.degraded, color: 'yellow' },
          { label: 'Плохо (<50)', value: s?.poor, color: 'red' },
          { label: 'Молчат', value: s?.silent, color: 'grape', hint: `из ${s?.periodic ?? 0} с регулярной передачей` },
        ].map((k) => (
          <Card key={k.label} withBorder radius="md">
            <Text size="sm" c="dimmed">
              {k.label}
            </Text>
            <Text fz={28} fw={700} c={k.color}>
              {k.value ?? '—'}
            </Text>
            {k.hint && (
              <Text size="xs" c="dimmed">
                {k.hint}
              </Text>
            )}
          </Card>
        ))}
      </SimpleGrid>

      <Card withBorder radius="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>{view === 'silent' ? 'Молчащие каналы (риск потери связи)' : 'Каналы с проблемами качества'}</Text>
          <SegmentedControl
            size="xs"
            value={view}
            onChange={(v) => setView(v as 'poor' | 'silent')}
            data={[
              { value: 'poor', label: 'Худшие по баллу' },
              { value: 'silent', label: 'Молчат' },
            ]}
          />
        </Group>
        {list.isLoading ? (
          <Loader />
        ) : (
          <Table.ScrollContainer minWidth={760}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Канал</Table.Th>
                  <Table.Th>Объект</Table.Th>
                  <Table.Th>Балл</Table.Th>
                  <Table.Th>Составляющие</Table.Th>
                  <Table.Th>Последнее сообщение</Table.Th>
                  <Table.Th>Обычный интервал</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.results.map((h) => (
                  <Table.Tr key={h.channel}>
                    <Table.Td>
                      <Text size="sm">{h.channel_name}</Text>
                      <Text size="xs" c="dimmed">
                        {h.sensor_type}
                      </Text>
                    </Table.Td>
                    <Table.Td>{h.node_name}</Table.Td>
                    <Table.Td>
                      <Badge color={scoreColor(h.score)} variant="light" size="lg">
                        {h.score}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Components c={h.components} />
                    </Table.Td>
                    <Table.Td>
                      {h.last_seen_at ? dayjs(h.last_seen_at).format('DD.MM.YYYY HH:mm') : '—'}
                      {h.silent && (
                        <Badge ml={6} color="grape" variant="light" size="xs">
                          молчит
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td>{h.periodic ? interval(h.expected_interval_s) : 'по событию'}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>
    </Stack>
  )
}
