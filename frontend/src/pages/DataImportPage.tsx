import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  FileInput,
  Grid,
  Group,
  Loader,
  NumberInput,
  Progress,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconDatabaseImport, IconFileUpload, IconFolder, IconUpload } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'

import { api, upload, type Page } from '../api/client'

interface Journal {
  year: number
  file: string
  size_mb: number
  excluded: boolean
  exclude_reason: string
  last_status: JobStatus | null
  last_rows: number | null
  last_finished_at: string | null
}

interface HistoryState {
  data_dir: string
  journals_dir: string
  journals: Journal[]
  reference: { objects_file: boolean; channels_file: boolean; objects: number; channels: number }
  active_batch: string | null
}

type JobStatus = 'pending' | 'running' | 'done' | 'failed'

interface Job {
  id: number
  kind: 'history' | 'window' | 'file'
  batch: string | null
  file_name: string
  params: { year?: number; raw_days?: number; since?: string }
  status: JobStatus
  progress: number
  stage: string
  rows_ok: number
  error: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

const STATUS: Record<JobStatus, { label: string; color: string }> = {
  pending: { label: 'В очереди', color: 'gray' },
  running: { label: 'Выполняется', color: 'blue' },
  done: { label: 'Готово', color: 'teal' },
  failed: { label: 'Ошибка', color: 'red' },
}

const fmt = new Intl.NumberFormat('ru-RU')
const isActive = (j: Job) => j.status === 'pending' || j.status === 'running'

function jobTitle(job: Job): string {
  if (job.kind === 'history') return `Журнал ${job.params.year}`
  if (job.kind === 'window') return `Оперативное окно (${job.params.raw_days ?? 30} дн.)`
  return job.file_name
}

function elapsed(job: Job): string {
  if (!job.started_at) return ''
  const seconds = dayjs(job.finished_at ?? undefined).diff(dayjs(job.started_at), 'second')
  return seconds >= 60 ? `${Math.floor(seconds / 60)} мин ${seconds % 60} с` : `${seconds} с`
}

function JobRow({ job }: { job: Job }) {
  return (
    <Stack gap={4}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={500}>
            {jobTitle(job)}
          </Text>
          <Badge size="sm" variant="light" color={STATUS[job.status].color}>
            {STATUS[job.status].label}
          </Badge>
        </Group>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {job.status === 'done' ? `${fmt.format(job.rows_ok)} строк · ${elapsed(job)}` : elapsed(job)}
        </Text>
      </Group>
      <Progress
        value={job.status === 'done' ? 100 : job.progress}
        color={job.status === 'failed' ? 'red' : job.status === 'done' ? 'teal' : 'blue'}
        animated={job.status === 'running'}
        striped={job.status === 'running'}
      />
      <Text size="xs" c={job.status === 'failed' ? 'red' : 'dimmed'}>
        {job.status === 'failed' ? job.error || job.stage : `${job.stage}${job.status === 'running' ? ` · ${job.progress.toFixed(0)}%` : ''}`}
      </Text>
    </Stack>
  )
}

function ReferenceCard({ state }: { state: HistoryState }) {
  const queryClient = useQueryClient()
  const [objects, setObjects] = useState<File | null>(null)
  const [channels, setChannels] = useState<File | null>(null)

  const load = useMutation({
    mutationFn: (fromDataDir: boolean) => {
      const form = new FormData()
      if (fromDataDir) form.append('from_data_dir', '1')
      if (objects) form.append('objects', objects)
      if (channels) form.append('channels', channels)
      return upload<{ objects?: { created: number }; channels?: { created: number; updated: number } }>(
        '/ingestion/reference/',
        form,
      )
    },
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Справочники загружены' })
      setObjects(null)
      setChannels(null)
      void queryClient.invalidateQueries({ queryKey: ['ingestion-history'] })
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })
  const ref = state.reference

  return (
    <Card withBorder radius="md" h="100%">
      <Text fw={600} mb="xs">
        Справочники
      </Text>
      <Text size="sm">
        Объектов: <b>{fmt.format(ref.objects)}</b> · каналов: <b>{fmt.format(ref.channels)}</b>
      </Text>
      <Text size="xs" c="dimmed" mb="sm">
        Загружаются первыми: журналы привязываются к каналам и объектам. Повторная загрузка обновляет данные без дублей.
      </Text>
      <Stack gap="xs">
        <Button
          variant="light"
          leftSection={<IconFolder size={16} />}
          disabled={!(ref.objects_file && ref.channels_file)}
          loading={load.isPending}
          onClick={() => load.mutate(true)}
        >
          Загрузить из каталога данных
        </Button>
        <FileInput size="sm" label="Справочник объектов (CSV)" accept=".csv" value={objects} onChange={setObjects} clearable />
        <FileInput size="sm" label="Справочник каналов (CSV)" accept=".csv" value={channels} onChange={setChannels} clearable />
        <Button leftSection={<IconUpload size={16} />} disabled={!objects && !channels} loading={load.isPending} onClick={() => load.mutate(false)}>
          Загрузить файлы
        </Button>
      </Stack>
    </Card>
  )
}

function UploadJournalCard() {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [sent, setSent] = useState<number | null>(null)

  const send = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('file', file as File)
      return upload<Job>('/ingestion/jobs/', form, setSent)
    },
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Файл принят, обработка запущена' })
      setFile(null)
      setSent(null)
      void queryClient.invalidateQueries({ queryKey: ['import-jobs'] })
    },
    onError: (error) => {
      setSent(null)
      notifications.show({ color: 'red', message: error.message })
    },
  })

  return (
    <Card withBorder radius="md" h="100%">
      <Text fw={600} mb="xs">
        Журнал файлом
      </Text>
      <Text size="xs" c="dimmed" mb="sm">
        CSV или XLSX с колонками ид_события, ид_канала_данных, дата, время, тревожное, значение_датчика. Данные сразу попадают
        в оперативный контур и витрины.
      </Text>
      <Stack gap="xs">
        <FileInput label="Файл журнала" accept=".csv,.xlsx,.xlsm" value={file} onChange={setFile} clearable />
        {sent !== null && (
          <Stack gap={2}>
            <Progress value={sent * 100} animated striped />
            <Text size="xs" c="dimmed">
              Передача файла: {(sent * 100).toFixed(0)}%{file ? ` из ${(file.size / 2 ** 20).toFixed(0)} МБ` : ''}
            </Text>
          </Stack>
        )}
        <Button leftSection={<IconFileUpload size={16} />} disabled={!file} loading={send.isPending} onClick={() => send.mutate()}>
          Загрузить и обработать
        </Button>
      </Stack>
    </Card>
  )
}

function HistoryCard({ state, busy }: { state: HistoryState; busy: boolean }) {
  const queryClient = useQueryClient()
  // По умолчанию отмечены все годы, кроме исключённых (2021)
  const [selected, setSelected] = useState<number[]>(() => state.journals.filter((j) => !j.excluded).map((j) => j.year))
  const [rawDays, setRawDays] = useState<number>(30)

  const start = useMutation({
    mutationFn: () =>
      api<{ batch: string }>('/ingestion/history/', { method: 'POST', body: { years: selected, raw_days: rawDays } }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Импорт запущен' })
      void queryClient.invalidateQueries({ queryKey: ['ingestion-history'] })
      void queryClient.invalidateQueries({ queryKey: ['import-jobs'] })
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  })

  const toggle = (year: number) =>
    setSelected((current) => (current.includes(year) ? current.filter((y) => y !== year) : [...current, year]))
  const totalMb = state.journals.filter((j) => selected.includes(j.year)).reduce((sum, j) => sum + j.size_mb, 0)

  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Журналы СМВУ в каталоге данных</Text>
        <Text size="xs" c="dimmed" ff="monospace">
          {state.journals_dir}
        </Text>
      </Group>
      {state.journals.length === 0 ? (
        <Alert color="yellow">
          Файлы не найдены. Положите журналы ext-journal-ГГГГ.csv в каталог data/dataset/journals и обновите страницу — или
          загрузите файл через браузер.
        </Alert>
      ) : (
        <>
          <Table.ScrollContainer minWidth={560}>
            <Table verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={40} />
                  <Table.Th>Год</Table.Th>
                  <Table.Th ta="right">Размер</Table.Th>
                  <Table.Th>Последний импорт</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {state.journals.map((j) => (
                  <Table.Tr key={j.year}>
                    <Table.Td>
                      <Checkbox checked={selected.includes(j.year)} onChange={() => toggle(j.year)} disabled={busy} aria-label={`Год ${j.year}`} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{j.year}</Text>
                      {j.excluded && (
                        <Text size="xs" c="orange">
                          не рекомендуется: {j.exclude_reason}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text size="sm">{fmt.format(j.size_mb)} МБ</Text>
                    </Table.Td>
                    <Table.Td>
                      {j.last_status ? (
                        <Group gap="xs">
                          <Badge size="sm" variant="light" color={STATUS[j.last_status].color}>
                            {STATUS[j.last_status].label}
                          </Badge>
                          {j.last_rows ? <Text size="xs" c="dimmed">{fmt.format(j.last_rows)} строк</Text> : null}
                        </Group>
                      ) : (
                        <Text size="xs" c="dimmed">
                          не загружался
                        </Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group mt="md" align="flex-end">
            <NumberInput
              label="Оперативное окно, дней"
              description="сырые показания в БД; вся история — в архиве и витринах"
              min={1}
              max={365}
              value={rawDays}
              onChange={(v) => setRawDays(Number(v) || 30)}
              w={260}
              disabled={busy}
            />
            <Button
              leftSection={<IconDatabaseImport size={16} />}
              disabled={busy || selected.length === 0}
              loading={start.isPending}
              onClick={() => start.mutate()}
            >
              Импортировать ({selected.length} · {(totalMb / 1024).toFixed(1)} ГБ)
            </Button>
          </Group>
          <Text size="xs" c="dimmed" mt={6}>
            Ориентир: около 1–2 минут на год журнала. Импорт идёт в фоне — страницу можно закрыть.
          </Text>
        </>
      )}
    </Card>
  )
}

export function DataImportPage() {
  const history = useQuery({
    queryKey: ['ingestion-history'],
    queryFn: () => api<HistoryState>('/ingestion/history/'),
    refetchInterval: (q) => (q.state.data?.active_batch ? 3000 : false),
  })
  const jobs = useQuery({
    queryKey: ['import-jobs', 'recent'],
    queryFn: () => api<Page<Job>>('/ingestion/jobs/', { query: { page_size: 30, ordering: '-created_at' } }),
    refetchInterval: (q) => (q.state.data?.results.some(isActive) ? 2000 : false),
  })

  if (history.isLoading || !history.data) return <Loader />
  const state = history.data
  const list = jobs.data?.results ?? []
  const busy = Boolean(state.active_batch)
  const batch = state.active_batch ?? list.find((j) => j.batch)?.batch ?? null
  const batchJobs = list
    .filter((j) => j.batch && j.batch === batch)
    .sort((a, b) => (a.kind === b.kind ? (a.params.year ?? 0) - (b.params.year ?? 0) : a.kind === 'window' ? 1 : -1))
  const overall = batchJobs.length ? batchJobs.reduce((sum, j) => sum + (j.status === 'done' ? 100 : j.progress), 0) / batchJobs.length : 0
  const uploads = list.filter((j) => j.kind === 'file').slice(0, 5)

  return (
    <Stack>
      <div>
        <Title order={3}>Загрузка данных</Title>
        <Text size="sm" c="dimmed">
          Стенд поставляется без данных заказчика: загрузите справочники, затем журналы — из каталога {state.data_dir} на
          сервере или файлом через браузер.
        </Text>
      </div>

      {batchJobs.length > 0 && (
        <Card withBorder radius="md">
          <Group justify="space-between" mb="xs">
            <Text fw={600}>{busy ? 'Идёт импорт истории' : 'Последний импорт истории'}</Text>
            <Text fw={600}>{overall.toFixed(0)}%</Text>
          </Group>
          <Progress size="lg" value={overall} animated={busy} striped={busy} color={batchJobs.some((j) => j.status === 'failed') ? 'orange' : 'blue'} mb="md" />
          <Grid>
            {batchJobs.map((job) => (
              <Grid.Col key={job.id} span={{ base: 12, md: 6 }}>
                <JobRow job={job} />
              </Grid.Col>
            ))}
          </Grid>
        </Card>
      )}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <ReferenceCard state={state} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <UploadJournalCard />
        </Grid.Col>
      </Grid>

      <HistoryCard state={state} busy={busy} />

      {uploads.length > 0 && (
        <Card withBorder radius="md">
          <Text fw={600} mb="sm">
            Загруженные файлы
          </Text>
          <Stack>
            {uploads.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
