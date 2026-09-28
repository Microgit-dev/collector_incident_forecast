/**
 * Конструктор источников и датчиков: новый датчик или шлюз с любым форматом подключается без программиста.
 * Шаблон формата говорит, где в сообщении канал, время, значение и тревога; профиль датчика — как понимать
 * значение (пороги, служебные коды, правила «текст → состояние»). Песочница показывает результат на примере.
 */
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Grid,
  Group,
  JsonInput,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconBooks, IconDeviceFloppy, IconPlayerPlay, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, type Page } from '../api/client'
import { CHANNEL_STATE } from '../api/labels'
import { useAuth } from '../auth/AuthContext'

type Fmt = 'json' | 'csv' | 'regex'

interface TemplateConfig {
  items?: string
  delimiter?: string
  header?: boolean
  columns?: string[]
  pattern?: string
  fields?: Record<string, unknown>
  measurements?: Record<string, unknown>[]
}

interface Source {
  id?: number
  code: string
  name: string
  description: string
  format: Fmt
  config: TemplateConfig
  sample: string
  is_active: boolean
  token?: string
  ingest_url?: string
}

interface LibraryItem {
  code: string
  name: string
  description: string
  format: Fmt
  config: TemplateConfig
  sample: string
}

interface PreviewRow {
  channel: number
  channel_name: string | null
  object: string | null
  known: boolean
  profile: string
  ts: string
  raw_value: string
  raw_alarm: boolean | null
  state: string
  numeric: number | null
  facet: string
  quality: string
}

interface Profile {
  id: number
  code: string
  name: string
  value_kind: string
  unit: string
  valid_min: number | null
  valid_max: number | null
  drift_tolerance: number | null
  warn_threshold: number | null
  alarm_threshold: number | null
  direction: 'above' | 'below'
  sentinels: string[]
  expected_interval_s: number
  silence_factor: number
  description: string
}

interface Rule {
  id: number
  profile: number | null
  pattern: string
  is_regex: boolean
  state: string
  facet: string
  guarded: boolean
  priority: number
}

const EMPTY: Source = {
  code: '',
  name: '',
  description: '',
  format: 'json',
  config: { fields: { channel: '', ts: '', ts_format: 'iso', value: '' } },
  sample: '',
  is_active: true,
}

const FIELD_HELP: Record<string, string> = {
  channel: 'путь к ид канала или «=80000001»',
  ts: 'путь к времени; дата и время отдельно — через запятую',
  ts_format: 'iso, epoch_s, epoch_ms или %d.%m.%Y %H:%M:%S',
  value: 'путь к значению',
  alarm: 'путь к признаку тревоги (необязательно)',
  event_id: 'путь к ид события (необязательно)',
}

function FieldsEditor({ config, onChange }: { config: TemplateConfig; onChange: (c: TemplateConfig) => void }) {
  const fields = (config.fields ?? {}) as Record<string, unknown>
  const set = (key: string, value: unknown) => {
    const next = { ...fields, [key]: value }
    if (value === '' || value === undefined) delete next[key]
    onChange({ ...config, fields: next })
  }
  return (
    <Stack gap={6}>
      {Object.keys(FIELD_HELP).map((key) => (
        <TextInput
          key={key}
          size="xs"
          label={key}
          description={FIELD_HELP[key]}
          value={Array.isArray(fields[key]) ? (fields[key] as string[]).join(', ') : ((fields[key] as string) ?? '')}
          onChange={(e) => {
            const v = e.currentTarget.value
            set(key, key === 'ts' && v.includes(',') ? v.split(',').map((x) => x.trim()) : v)
          }}
        />
      ))}
      <JsonInput
        size="xs"
        label="channel_map"
        description='ключ из сообщения → ид канала, например {"temp": 80000001}'
        autosize
        minRows={1}
        validationError="Некорректный JSON"
        value={fields.channel_map ? JSON.stringify(fields.channel_map) : ''}
        onChange={(v) => {
          try {
            set('channel_map', v ? JSON.parse(v) : undefined)
          } catch {
            /* ждём корректный JSON */
          }
        }}
      />
    </Stack>
  )
}

function TemplatesTab() {
  const { can } = useAuth()
  const edit = can('ingestion.change_datasource')
  const client = useQueryClient()
  const [draft, setDraft] = useState<Source>(EMPTY)
  const [profile, setProfile] = useState<string | null>(null)
  const [raw, setRaw] = useState(false)
  const sources = useQuery({ queryKey: ['templates'], queryFn: () => api<Page<Source>>('/ingestion/templates/') })
  const library = useQuery({
    queryKey: ['templates', 'library'],
    queryFn: () => api<LibraryItem[]>('/ingestion/templates/library/'),
  })
  const profiles = useQuery({
    queryKey: ['profiles'],
    queryFn: () => api<Page<Profile>>('/normalization/profiles/', { query: { page_size: 200 } }),
  })
  const preview = useMutation({
    mutationFn: () =>
      api<{ events: PreviewRow[]; total: number; errors: { item: number | null; error: string }[] }>(
        '/ingestion/templates/preview/',
        { method: 'POST', body: { format: draft.format, config: draft.config, sample: draft.sample, profile } },
      ),
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const save = useMutation({
    mutationFn: () =>
      draft.id
        ? api<Source>(`/ingestion/templates/${draft.id}/`, { method: 'PATCH', body: draft })
        : api<Source>('/ingestion/templates/', { method: 'POST', body: draft }),
    onSuccess: (s) => {
      notifications.show({ color: 'teal', message: `Шаблон «${s.name}» сохранён` })
      setDraft(s)
      void client.invalidateQueries({ queryKey: ['templates'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const remove = useMutation({
    mutationFn: () => api(`/ingestion/templates/${draft.id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      setDraft(EMPTY)
      void client.invalidateQueries({ queryKey: ['templates'] })
    },
  })
  const rotate = useMutation({
    mutationFn: () => api<Source>(`/ingestion/templates/${draft.id}/rotate-token/`, { method: 'POST' }),
    onSuccess: (s) => setDraft(s),
  })
  useEffect(() => preview.reset(), [draft.format]) // eslint-disable-line react-hooks/exhaustive-deps

  const fromLibrary = (code: string | null) => {
    const item = library.data?.find((l) => l.code === code)
    if (item) setDraft({ ...EMPTY, ...item, code: `${item.code}-${Math.floor(Math.random() * 900 + 100)}` })
  }
  const origin = window.location.origin
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 3 }}>
        <Stack gap="xs">
          {edit && (
            <Button size="xs" leftSection={<IconPlus size={14} />} variant="light" onClick={() => setDraft(EMPTY)}>
              Новый шаблон
            </Button>
          )}
          <Select
            size="xs"
            leftSection={<IconBooks size={14} />}
            placeholder="Из библиотеки…"
            data={(library.data ?? []).map((l) => ({ value: l.code, label: l.name }))}
            onChange={fromLibrary}
            value={null}
          />
          {sources.isLoading ? (
            <Loader size="sm" />
          ) : (
            sources.data?.results.map((s) => (
              <UnstyledButton key={s.id} onClick={() => setDraft(s)}>
                <Card withBorder padding="xs" bg={s.id === draft.id ? 'var(--mantine-color-blue-light)' : undefined}>
                  <Text size="sm" fw={600}>
                    {s.name}
                  </Text>
                  <Group gap={4}>
                    <Badge size="xs" variant="light">
                      {s.format}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {s.code}
                    </Text>
                    {!s.is_active && (
                      <Badge size="xs" color="gray">
                        выключен
                      </Badge>
                    )}
                  </Group>
                </Card>
              </UnstyledButton>
            ))
          )}
          {sources.data?.results.length === 0 && (
            <Text size="xs" c="dimmed">
              Шаблонов пока нет — начните с библиотеки.
            </Text>
          )}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 9 }}>
        <Stack>
          <Card withBorder radius="md">
            <Grid>
              <Grid.Col span={{ base: 12, md: 5 }}>
                <Stack gap={6}>
                  <TextInput
                    size="xs"
                    label="Название"
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
                  />
                  <TextInput
                    size="xs"
                    label="Код"
                    description="латиница; используется в адресе приёма и обёртке Kafka"
                    value={draft.code}
                    disabled={Boolean(draft.id)}
                    onChange={(e) => setDraft({ ...draft, code: e.currentTarget.value })}
                  />
                  <Textarea
                    size="xs"
                    label="Описание"
                    autosize
                    minRows={1}
                    value={draft.description}
                    onChange={(e) => setDraft({ ...draft, description: e.currentTarget.value })}
                  />
                  <Text size="xs" fw={500}>
                    Формат сообщения
                  </Text>
                  <SegmentedControl
                    size="xs"
                    value={draft.format}
                    onChange={(v) => setDraft({ ...draft, format: v as Fmt })}
                    data={[
                      { value: 'json', label: 'JSON' },
                      { value: 'csv', label: 'CSV' },
                      { value: 'regex', label: 'Строка (regex)' },
                    ]}
                  />
                  {draft.format === 'json' && (
                    <TextInput
                      size="xs"
                      label="items"
                      description="путь к массиву измерений; поля пакета — через «^.поле»"
                      value={draft.config.items ?? ''}
                      onChange={(e) =>
                        setDraft({ ...draft, config: { ...draft.config, items: e.currentTarget.value || undefined } })
                      }
                    />
                  )}
                  {draft.format === 'csv' && (
                    <Group grow>
                      <TextInput
                        size="xs"
                        label="Разделитель"
                        value={draft.config.delimiter ?? ','}
                        onChange={(e) =>
                          setDraft({ ...draft, config: { ...draft.config, delimiter: e.currentTarget.value } })
                        }
                      />
                      <Switch
                        size="xs"
                        mt="lg"
                        label="Первая строка — заголовок"
                        checked={draft.config.header ?? true}
                        onChange={(e) =>
                          setDraft({ ...draft, config: { ...draft.config, header: e.currentTarget.checked } })
                        }
                      />
                    </Group>
                  )}
                  {draft.format === 'regex' && (
                    <TextInput
                      size="xs"
                      label="Регулярное выражение"
                      description="именованные группы (?P<channel>…), (?P<value>…)"
                      ff="monospace"
                      value={draft.config.pattern ?? ''}
                      onChange={(e) =>
                        setDraft({ ...draft, config: { ...draft.config, pattern: e.currentTarget.value } })
                      }
                    />
                  )}
                  <Switch
                    size="xs"
                    label="Активен (принимает события)"
                    checked={draft.is_active}
                    onChange={(e) => setDraft({ ...draft, is_active: e.currentTarget.checked })}
                  />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 7 }}>
                <Group justify="space-between" mb={4}>
                  <Text size="xs" fw={500}>
                    Поля события
                  </Text>
                  <Switch
                    size="xs"
                    label="JSON целиком"
                    checked={raw}
                    onChange={(e) => setRaw(e.currentTarget.checked)}
                  />
                </Group>
                {raw ? (
                  <JsonInput
                    size="xs"
                    autosize
                    minRows={10}
                    formatOnBlur
                    validationError="Некорректный JSON"
                    defaultValue={JSON.stringify(draft.config, null, 2)}
                    key={`${draft.id}-${draft.code}`}
                    onBlur={(e) => {
                      try {
                        setDraft({ ...draft, config: JSON.parse(e.currentTarget.value) })
                      } catch {
                        /* noop */
                      }
                    }}
                  />
                ) : (
                  <FieldsEditor config={draft.config} onChange={(c) => setDraft({ ...draft, config: c })} />
                )}
              </Grid.Col>
            </Grid>
          </Card>

          <Card withBorder radius="md">
            <Text fw={600} mb={4}>
              Песочница
            </Text>
            <Textarea
              size="xs"
              ff="monospace"
              autosize
              minRows={3}
              placeholder="Вставьте пример сообщения от датчика или шлюза"
              value={draft.sample}
              onChange={(e) => setDraft({ ...draft, sample: e.currentTarget.value })}
            />
            <Group mt="xs" gap="xs">
              <Select
                size="xs"
                w={280}
                clearable
                placeholder="Профиль для незаведённых каналов"
                data={(profiles.data?.results ?? []).map((p) => ({ value: p.code, label: p.name }))}
                value={profile}
                onChange={setProfile}
              />
              <Button
                size="xs"
                leftSection={<IconPlayerPlay size={14} />}
                loading={preview.isPending}
                onClick={() => preview.mutate()}
              >
                Проверить
              </Button>
              {edit && (
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<IconDeviceFloppy size={14} />}
                  loading={save.isPending}
                  disabled={!draft.code || !draft.name}
                  onClick={() => save.mutate()}
                >
                  Сохранить шаблон
                </Button>
              )}
              {edit && draft.id && (
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  leftSection={<IconTrash size={14} />}
                  onClick={() => remove.mutate()}
                >
                  Удалить
                </Button>
              )}
            </Group>
            {preview.data && (
              <Stack mt="sm" gap="xs">
                <Text size="sm">
                  Событий: {preview.data.total}
                  {preview.data.errors.length > 0 && `, ошибок: ${preview.data.errors.length}`}
                </Text>
                {preview.data.errors.map((e, i) => (
                  <Alert key={i} color="red" variant="light" p="xs">
                    <Text size="xs">
                      {e.item ? `Сообщение ${e.item}: ` : ''}
                      {e.error}
                    </Text>
                  </Alert>
                ))}
                {preview.data.events.length > 0 && (
                  <Table.ScrollContainer minWidth={900}>
                    <Table striped fz="xs">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Канал</Table.Th>
                          <Table.Th>Время</Table.Th>
                          <Table.Th>Значение</Table.Th>
                          <Table.Th>Тревога</Table.Th>
                          <Table.Th>Состояние</Table.Th>
                          <Table.Th>Число</Table.Th>
                          <Table.Th>Качество</Table.Th>
                          <Table.Th>Профиль</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {preview.data.events.map((r, i) => (
                          <Table.Tr key={i}>
                            <Table.Td>
                              <Text size="xs" fw={500}>
                                {r.channel}
                              </Text>
                              <Text size="xs" c={r.known ? 'dimmed' : 'orange'}>
                                {r.known ? `${r.channel_name} · ${r.object}` : 'канал не заведён'}
                              </Text>
                            </Table.Td>
                            <Table.Td>{new Date(r.ts).toLocaleString('ru-RU')}</Table.Td>
                            <Table.Td ff="monospace">{r.raw_value}</Table.Td>
                            <Table.Td>{r.raw_alarm == null ? '—' : r.raw_alarm ? 'да' : 'нет'}</Table.Td>
                            <Table.Td>
                              <Badge size="xs" color={CHANNEL_STATE[r.state]?.color ?? 'gray'}>
                                {CHANNEL_STATE[r.state]?.label ?? r.state}
                              </Badge>
                              {r.facet !== 'primary' && (
                                <Text size="xs" c="dimmed">
                                  {r.facet}
                                </Text>
                              )}
                            </Table.Td>
                            <Table.Td>{r.numeric ?? '—'}</Table.Td>
                            <Table.Td>{r.quality}</Table.Td>
                            <Table.Td>{r.profile}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                )}
              </Stack>
            )}
          </Card>

          {draft.id && draft.token && (
            <Card withBorder radius="md">
              <Group justify="space-between" mb={4}>
                <Text fw={600}>Как подключить источник</Text>
                {edit && (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    leftSection={<IconRefresh size={12} />}
                    onClick={() => rotate.mutate()}
                  >
                    Новый ключ
                  </Button>
                )}
              </Group>
              <Text size="xs" c="dimmed" mb={4}>
                Шлюз отправляет сообщения по HTTP с ключом источника — события попадают в тот же поток, что у СМВУ:
              </Text>
              <Code block fz="xs">
                {`curl -X POST ${origin}${draft.ingest_url} \\\n  -H "Authorization: Token ${draft.token}" \\\n  --data-binary @message.txt`}
              </Code>
              <Text size="xs" c="dimmed" mt="xs" mb={4}>
                Или пишет в Kafka (тема событий СМВУ) обёртку:
              </Text>
              <Code block fz="xs">{`{"template": "${draft.code}", "payload": "<сообщение в формате шаблона>"}`}</Code>
              <Text size="xs" c="dimmed" mt="xs">
                Каналы с ид из сообщений заводятся в «Зоны и объекты» (новый датчик, тип датчика задаёт профиль).
              </Text>
            </Card>
          )}
        </Stack>
      </Grid.Col>
    </Grid>
  )
}

const STATES = ['normal', 'warning', 'alarm', 'fault', 'power_loss', 'unknown', 'event']

function ProfilesTab() {
  const { can } = useAuth()
  const edit = can('normalization.change_sensorprofile')
  const client = useQueryClient()
  const [selected, setSelected] = useState<Profile | null>(null)
  const [test, setTest] = useState('')
  const [newRule, setNewRule] = useState({ pattern: '', state: 'alarm', facet: 'primary', is_regex: false })
  const profiles = useQuery({
    queryKey: ['profiles'],
    queryFn: () => api<Page<Profile>>('/normalization/profiles/', { query: { page_size: 200 } }),
  })
  const rules = useQuery({
    queryKey: ['rules', selected?.id],
    queryFn: () => api<Page<Rule>>('/normalization/rules/', { query: { profile: selected!.id, page_size: 200 } }),
    enabled: Boolean(selected?.id),
  })
  const save = useMutation({
    mutationFn: (p: Profile) =>
      p.id
        ? api<Profile>(`/normalization/profiles/${p.id}/`, { method: 'PATCH', body: p })
        : api<Profile>('/normalization/profiles/', { method: 'POST', body: p }),
    onSuccess: (p) => {
      notifications.show({ color: 'teal', message: `Профиль «${p.name}» сохранён — консьюмер подхватит его за минуту` })
      setSelected(p)
      void client.invalidateQueries({ queryKey: ['profiles'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const addRule = useMutation({
    mutationFn: () =>
      api('/normalization/rules/', { method: 'POST', body: { ...newRule, profile: selected!.id, priority: 100 } }),
    onSuccess: () => {
      setNewRule({ ...newRule, pattern: '' })
      void client.invalidateQueries({ queryKey: ['rules', selected?.id] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const delRule = useMutation({
    mutationFn: (id: number) => api(`/normalization/rules/${id}/`, { method: 'DELETE' }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['rules', selected?.id] }),
  })
  const check = useMutation({
    mutationFn: () =>
      api<{ state: string; numeric: number | null; quality: string; facet: string }>(
        '/normalization/profiles/preview/',
        {
          method: 'POST',
          body: { profile: selected?.code ?? '', value: test },
        },
      ),
  })
  const num = (key: keyof Profile) => (
    <NumberInput
      size="xs"
      label={
        {
          valid_min: 'мин.',
          valid_max: 'макс.',
          drift_tolerance: 'дрейф нуля',
          warn_threshold: 'предупреждение',
          alarm_threshold: 'тревога',
          expected_interval_s: 'интервал, с',
          silence_factor: 'молчание, интервалов',
        }[key as string]
      }
      value={(selected?.[key] as number | null) ?? ''}
      onChange={(v) => selected && setSelected({ ...selected, [key]: v === '' ? null : Number(v) })}
      disabled={!edit}
    />
  )
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 3 }}>
        <Stack gap={4}>
          {edit && (
            <Button
              size="xs"
              variant="light"
              leftSection={<IconPlus size={14} />}
              onClick={() =>
                setSelected({
                  id: 0,
                  code: '',
                  name: '',
                  value_kind: 'numeric',
                  unit: '',
                  valid_min: null,
                  valid_max: null,
                  drift_tolerance: null,
                  warn_threshold: null,
                  alarm_threshold: null,
                  direction: 'above',
                  sentinels: [],
                  expected_interval_s: 3600,
                  silence_factor: 24,
                  description: '',
                })
              }
            >
              Новый профиль
            </Button>
          )}
          {profiles.data?.results.map((p) => (
            <UnstyledButton key={p.id} onClick={() => setSelected(p)}>
              <Card withBorder padding={6} bg={p.id === selected?.id ? 'var(--mantine-color-blue-light)' : undefined}>
                <Text size="sm">{p.name}</Text>
                <Text size="xs" c="dimmed">
                  {p.code} · {p.value_kind}
                  {p.unit && ` · ${p.unit}`}
                </Text>
              </Card>
            </UnstyledButton>
          ))}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 9 }}>
        {!selected ? (
          <Text c="dimmed" size="sm">
            Профиль описывает, как понимать значения класса датчиков: диапазон, пороги, служебные коды и правила «текст
            → состояние». Тип датчика ссылается на профиль; каналу можно задать свой.
          </Text>
        ) : (
          <Stack>
            <Card withBorder radius="md">
              <Grid>
                <Grid.Col span={{ base: 12, md: 6 }}>
                  <Stack gap={6}>
                    <TextInput
                      size="xs"
                      label="Название"
                      value={selected.name}
                      disabled={!edit}
                      onChange={(e) => setSelected({ ...selected, name: e.currentTarget.value })}
                    />
                    <TextInput
                      size="xs"
                      label="Код"
                      value={selected.code}
                      disabled={!edit || Boolean(selected.id)}
                      onChange={(e) => setSelected({ ...selected, code: e.currentTarget.value })}
                    />
                    <Group grow>
                      <Select
                        size="xs"
                        label="Тип значений"
                        data={['numeric', 'discrete', 'text', 'mixed']}
                        value={selected.value_kind}
                        disabled={!edit}
                        onChange={(v) => setSelected({ ...selected, value_kind: v ?? 'numeric' })}
                      />
                      <TextInput
                        size="xs"
                        label="Единица"
                        value={selected.unit}
                        disabled={!edit}
                        onChange={(e) => setSelected({ ...selected, unit: e.currentTarget.value })}
                      />
                    </Group>
                    <TextInput
                      size="xs"
                      label="Служебные коды (= неисправность)"
                      description="через запятую: -1, 9999, 01.01.1970…"
                      value={selected.sentinels.join(', ')}
                      disabled={!edit}
                      onChange={(e) =>
                        setSelected({
                          ...selected,
                          sentinels: e.currentTarget.value
                            .split(',')
                            .map((x) => x.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                  </Stack>
                </Grid.Col>
                <Grid.Col span={{ base: 12, md: 6 }}>
                  <Group grow>
                    {num('valid_min')}
                    {num('valid_max')}
                    {num('drift_tolerance')}
                  </Group>
                  <Group grow mt={6}>
                    {num('warn_threshold')}
                    {num('alarm_threshold')}
                    <Select
                      size="xs"
                      label="направление"
                      data={[
                        { value: 'above', label: 'рост' },
                        { value: 'below', label: 'падение' },
                      ]}
                      value={selected.direction}
                      disabled={!edit}
                      onChange={(v) => setSelected({ ...selected, direction: (v as 'above' | 'below') ?? 'above' })}
                    />
                  </Group>
                  <Group grow mt={6}>
                    {num('expected_interval_s')}
                    {num('silence_factor')}
                  </Group>
                  {edit && (
                    <Button
                      mt="sm"
                      size="xs"
                      leftSection={<IconDeviceFloppy size={14} />}
                      loading={save.isPending}
                      onClick={() => save.mutate(selected)}
                    >
                      Сохранить профиль
                    </Button>
                  )}
                </Grid.Col>
              </Grid>
            </Card>
            {selected.id > 0 && (
              <Card withBorder radius="md">
                <Text fw={600} mb={4}>
                  Правила «текст → состояние»
                </Text>
                <Table fz="xs">
                  <Table.Tbody>
                    {rules.data?.results.map((r) => (
                      <Table.Tr key={r.id}>
                        <Table.Td ff="monospace">{r.pattern}</Table.Td>
                        <Table.Td>{r.is_regex ? 'регулярное' : 'текст'}</Table.Td>
                        <Table.Td>
                          <Badge size="xs" color={CHANNEL_STATE[r.state]?.color}>
                            {CHANNEL_STATE[r.state]?.label ?? r.state}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{r.facet}</Table.Td>
                        <Table.Td>
                          {edit && (
                            <Button size="compact-xs" variant="subtle" color="red" onClick={() => delRule.mutate(r.id)}>
                              удалить
                            </Button>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
                {edit && (
                  <Group mt="xs" gap="xs" align="flex-end">
                    <TextInput
                      size="xs"
                      label="Значение"
                      value={newRule.pattern}
                      onChange={(e) => setNewRule({ ...newRule, pattern: e.currentTarget.value })}
                    />
                    <Switch
                      size="xs"
                      label="регулярное"
                      checked={newRule.is_regex}
                      onChange={(e) => setNewRule({ ...newRule, is_regex: e.currentTarget.checked })}
                    />
                    <Select
                      size="xs"
                      label="Состояние"
                      w={150}
                      data={STATES.map((s) => ({ value: s, label: CHANNEL_STATE[s]?.label ?? s }))}
                      value={newRule.state}
                      onChange={(v) => setNewRule({ ...newRule, state: v ?? 'alarm' })}
                    />
                    <TextInput
                      size="xs"
                      label="Аспект"
                      w={110}
                      value={newRule.facet}
                      onChange={(e) => setNewRule({ ...newRule, facet: e.currentTarget.value })}
                    />
                    <Button size="xs" disabled={!newRule.pattern} onClick={() => addRule.mutate()}>
                      Добавить правило
                    </Button>
                  </Group>
                )}
              </Card>
            )}
            <Card withBorder radius="md">
              <Text fw={600} mb={4}>
                Проверить значение
              </Text>
              <Group gap="xs">
                <TextInput
                  size="xs"
                  placeholder="например 1,35 или «Затоплен»"
                  value={test}
                  onChange={(e) => setTest(e.currentTarget.value)}
                />
                <Button size="xs" variant="light" onClick={() => check.mutate()}>
                  Проверить
                </Button>
                {check.data && (
                  <Group gap={6}>
                    <Badge color={CHANNEL_STATE[check.data.state]?.color}>
                      {CHANNEL_STATE[check.data.state]?.label ?? check.data.state}
                    </Badge>
                    <Text size="xs">
                      число: {check.data.numeric ?? '—'} · качество: {check.data.quality} · аспект: {check.data.facet}
                    </Text>
                  </Group>
                )}
              </Group>
            </Card>
          </Stack>
        )}
      </Grid.Col>
    </Grid>
  )
}

export function ConstructorPage() {
  return (
    <Stack>
      <div>
        <Title order={3}>Конструктор источников и датчиков</Title>
        <Text size="sm" c="dimmed">
          Новый датчик или шлюз подключается без программиста: шаблон формата разбирает сообщение в единое событие,
          профиль датчика задаёт, как понимать значение. Дальше — тот же конвейер: нормализация, прогнозы, карточки.
        </Text>
      </div>
      <Tabs defaultValue="templates" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="templates">Шаблоны формата</Tabs.Tab>
          <Tabs.Tab value="profiles">Профили датчиков</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="templates" pt="md">
          <TemplatesTab />
        </Tabs.Panel>
        <Tabs.Panel value="profiles" pt="md">
          <ProfilesTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
