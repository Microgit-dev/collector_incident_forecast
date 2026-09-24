import { Badge, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, type Page } from '../api/client'

interface SummaryItem {
  key: string
  label: string
  value: number
}

interface ImportJob {
  id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  params: { year?: number }
  file_path: string
  rows_total: number
  rows_ok: number
  started_at: string | null
  finished_at: string | null
  error: string
  quality: {
    summary?: SummaryItem[]
    by_quality?: Record<string, number>
    channels?: number
    unknown_channels?: number
    period?: { from: string | null; to: string | null }
    unmapped_top?: { value: string; rows: number }[]
  }
}

const STATUS = {
  pending: { label: 'В очереди', color: 'gray' },
  running: { label: 'Выполняется', color: 'blue' },
  done: { label: 'Завершён', color: 'teal' },
  failed: { label: 'Ошибка', color: 'red' },
} as const

// Цвет категории: зелёный — полезные данные, оранжевый — технические, красный — брак
const CATEGORY_COLOR: Record<string, string> = {
  valid: 'teal',
  technical: 'orange',
  invalid: 'red',
  time: 'grape',
  duplicates: 'gray',
  bad_ids: 'red',
  unknown: 'yellow',
}

const fmt = new Intl.NumberFormat('ru-RU')

function QualityReport({ job }: { job: ImportJob }) {
  const summary = job.quality.summary ?? []
  const total = summary.find((s) => s.key === 'rows_total')?.value ?? job.rows_total
  const parts = summary.filter((s) => s.key !== 'rows_total' && s.value > 0)

  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>
          Отчёт о качестве{job.params.year ? ` · ${job.params.year}` : ''}
        </Text>
        <Text size="sm" c="dimmed">
          {job.quality.period?.from && `${dayjs(job.quality.period.from).format('DD.MM.YYYY')} — ${dayjs(job.quality.period.to).format('DD.MM.YYYY')}`}
        </Text>
      </Group>
      <Progress.Root size={20} mb="md">
        {parts.map((p) => (
          <Progress.Section key={p.key} value={(p.value / Math.max(total, 1)) * 100} color={CATEGORY_COLOR[p.key] ?? 'blue'} />
        ))}
      </Progress.Root>
      <Table>
        <Table.Tbody>
          {summary.map((s) => (
            <Table.Tr key={s.key}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  {s.key !== 'rows_total' && <Badge size="xs" circle color={CATEGORY_COLOR[s.key] ?? 'blue'} />}
                  <Text size="sm" fw={s.key === 'rows_total' ? 600 : 400}>
                    {s.label}
                  </Text>
                </Group>
              </Table.Td>
              <Table.Td ta="right">
                <Text size="sm" ff="monospace">
                  {fmt.format(s.value)}
                </Text>
              </Table.Td>
              <Table.Td ta="right" w={80}>
                <Text size="xs" c="dimmed">
                  {s.key !== 'rows_total' && total ? `${((s.value / total) * 100).toFixed(2)}%` : ''}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Text size="sm" c="dimmed" mt="sm">
        Каналов в журнале: {fmt.format(job.quality.channels ?? 0)}, из них вне справочника: {fmt.format(job.quality.unknown_channels ?? 0)}
      </Text>
      {!!job.quality.unmapped_top?.length && (
        <Text size="sm" c="dimmed" mt={4}>
          Нераспознанные значения: {job.quality.unmapped_top.slice(0, 5).map((u) => `«${u.value}» (${u.rows})`).join(', ')}
        </Text>
      )}
    </Card>
  )
}

export function DataQualityPage() {
  const [selected, setSelected] = useState<number | null>(null)
  const jobs = useQuery({
    queryKey: ['import-jobs'],
    queryFn: () => api<Page<ImportJob>>('/ingestion/jobs/', { query: { page_size: 100, ordering: '-created_at' } }),
    refetchInterval: (query) => (query.state.data?.results.some((j) => j.status === 'running') ? 5000 : false),
  })

  if (jobs.isLoading) return <Loader />
  const list = jobs.data?.results ?? []
  const done = list.filter((j) => j.status === 'done' && j.quality.summary)
  const current = list.find((j) => j.id === selected) ?? done[0]
  const totalRows = done.reduce((sum, j) => sum + j.rows_total, 0)
  const loadedRows = done.reduce((sum, j) => sum + j.rows_ok, 0)

  return (
    <Stack>
      <Title order={3}>Качество данных</Title>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Загружено строк
          </Text>
          <Text fz={28} fw={700}>
            {fmt.format(loadedRows)}
          </Text>
          <Text size="xs" c="dimmed">
            из {fmt.format(totalRows)} прочитанных
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Периодов загружено
          </Text>
          <Text fz={28} fw={700}>
            {done.length}
          </Text>
          <Text size="xs" c="dimmed">
            2021 год исключён: миграция системы мониторинга
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Text size="sm" c="dimmed">
            Отброшено при загрузке
          </Text>
          <Text fz={28} fw={700}>
            {totalRows ? (((totalRows - loadedRows) / totalRows) * 100).toFixed(3) : 0}%
          </Text>
          <Text size="xs" c="dimmed">
            дубли, ошибки времени, строки без идентификаторов
          </Text>
        </Card>
      </SimpleGrid>

      <Card withBorder radius="md" p={0}>
        <Table.ScrollContainer minWidth={700}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Период / файл</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th ta="right">Прочитано</Table.Th>
                <Table.Th ta="right">Загружено</Table.Th>
                <Table.Th>Длительность</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.map((job) => (
                <Table.Tr
                  key={job.id}
                  onClick={() => setSelected(job.id)}
                  style={{ cursor: 'pointer' }}
                  bg={current?.id === job.id ? 'var(--mantine-color-blue-light)' : undefined}
                >
                  <Table.Td>
                    <Text size="sm">{job.params.year ?? job.file_path.split('/').pop()}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={STATUS[job.status].color} variant="light">
                      {STATUS[job.status].label}
                    </Badge>
                  </Table.Td>
                  <Table.Td ta="right" ff="monospace">
                    {fmt.format(job.rows_total)}
                  </Table.Td>
                  <Table.Td ta="right" ff="monospace">
                    {fmt.format(job.rows_ok)}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {job.started_at && job.finished_at
                        ? `${dayjs(job.finished_at).diff(dayjs(job.started_at), 'second')} с`
                        : '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {!list.length && (
          <Text c="dimmed" p="md">
            Импортов ещё не было. Запустите: docker compose run --rm backend python manage.py import_history
          </Text>
        )}
      </Card>

      {current?.quality.summary && <QualityReport job={current} />}
    </Stack>
  )
}
