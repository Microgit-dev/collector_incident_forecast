import {
  Badge,
  Card,
  Group,
  Loader,
  MultiSelect,
  Pagination,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core'
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { INCIDENT_STATUS, INCIDENT_TYPE, RISK } from '../api/labels'
import type { Incident } from '../api/types'
import { ContourBadge, PriorityBadge, RiskBadge, StatusBadge } from '../components/badges'

const PAGE_SIZE = 25
const OPEN = ['new', 'acknowledged', 'in_progress']

export function IncidentsPage() {
  const navigate = useNavigate()
  const phone = useMediaQuery('(max-width: 48em)')
  const [status, setStatus] = useState<string[]>(OPEN)
  const [severity, setSeverity] = useState<string[]>([])
  const [type, setType] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [debounced] = useDebouncedValue(search, 300)
  const [page, setPage] = useState(1)

  const query = useQuery({
    queryKey: ['incidents', { status, severity, type, debounced, page }],
    queryFn: () =>
      api<Page<Incident>>('/incidents/items/', {
        query: {
          status__in: status,
          severity__in: severity,
          type__in: type,
          search: debounced,
          page,
          page_size: PAGE_SIZE,
          ordering: '-priority,-last_signal_at',
        },
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  })

  const options = (dict: Record<string, string | { label: string }>) =>
    Object.entries(dict).map(([value, v]) => ({ value, label: typeof v === 'string' ? v : v.label }))

  return (
    <Stack>
      <Title order={3}>Инциденты</Title>
      <Group align="flex-end" wrap="wrap">
        <TextInput
          placeholder="Объект или описание"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            setSearch(e.currentTarget.value)
            setPage(1)
          }}
          w={{ base: '100%', sm: 240 }}
        />
        <MultiSelect label="Статус" data={options(INCIDENT_STATUS)} value={status} onChange={setStatus} clearable w={{ base: '100%', sm: 260 }} />
        <MultiSelect label="Уровень" data={options(RISK)} value={severity} onChange={setSeverity} clearable w={{ base: '100%', sm: 220 }} />
        <MultiSelect label="Тип" data={options(INCIDENT_TYPE)} value={type} onChange={setType} clearable w={{ base: '100%', sm: 260 }} />
      </Group>

      <Card withBorder radius="md" p={0}>
        {query.isLoading ? (
          <Loader m="md" />
        ) : phone ? (
          // на телефоне — карточки: всё главное без прокрутки таблицы вбок
          <Stack gap={0}>
            {query.data?.results.map((incident) => (
              <UnstyledButton
                key={incident.id}
                onClick={() => navigate(`/incidents/${incident.id}`)}
                p="sm"
                style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
              >
                <Group justify="space-between" wrap="nowrap" gap="xs" mb={4}>
                  <Group gap={6} wrap="nowrap">
                    <PriorityBadge value={incident.priority} />
                    <RiskBadge level={incident.severity} />
                  </Group>
                  <StatusBadge status={incident.status} />
                </Group>
                <Text size="sm" fw={500}>
                  {incident.title}
                </Text>
                <Text size="xs" c="dimmed">
                  {incident.node_name} · {dayjs(incident.opened_at).format('DD.MM HH:mm')}
                  {incident.assigned_to_name && ` · ${incident.assigned_to_name}`}
                </Text>
                {incident.escalation_level > 0 && (
                  <Text size="xs" c="grape">
                    эскалация → {incident.responsible_node_name}
                  </Text>
                )}
              </UnstyledButton>
            ))}
          </Stack>
        ) : (
          <Table.ScrollContainer minWidth={900}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Приоритет</Table.Th>
                  <Table.Th>Открыт</Table.Th>
                  <Table.Th>Уровень</Table.Th>
                  <Table.Th>Инцидент</Table.Th>
                  <Table.Th>Объект</Table.Th>
                  <Table.Th>Статус</Table.Th>
                  <Table.Th>Ответственный</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {query.data?.results.map((incident) => (
                  <Table.Tr key={incident.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/incidents/${incident.id}`)}>
                    <Table.Td>
                      <PriorityBadge value={incident.priority} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{dayjs(incident.opened_at).format('DD.MM HH:mm')}</Text>
                    </Table.Td>
                    <Table.Td>
                      <RiskBadge level={incident.severity} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {incident.title}
                      </Text>
                      <Group gap={4}>
                        <Text size="xs" c="dimmed">
                          {INCIDENT_TYPE[incident.type]}
                          {incident.signals_count > 1 &&
                            ` · сигналов: ${incident.signals_count}, каналов: ${incident.channels_count}`}
                        </Text>
                        <ContourBadge contour={incident.contour} />
                        {incident.is_forecast && (
                          <Badge size="xs" variant="outline">
                            прогноз
                          </Badge>
                        )}
                        {incident.is_emulated && (
                          <Badge size="xs" color="orange" variant="light">
                            эмуляция
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{incident.node_name}</Text>
                    </Table.Td>
                    <Table.Td>
                      <StatusBadge status={incident.status} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{incident.assigned_to_name || '—'}</Text>
                      {incident.escalation_level > 0 && (
                        <Text size="xs" c="grape">
                          эскалация → {incident.responsible_node_name}
                        </Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {query.data && query.data.count === 0 && (
          <Text c="dimmed" p="md">
            Инцидентов по заданным условиям нет
          </Text>
        )}
      </Card>
      {query.data && query.data.count > PAGE_SIZE && (
        <Pagination total={Math.ceil(query.data.count / PAGE_SIZE)} value={page} onChange={setPage} size={phone ? 'sm' : 'md'} siblings={phone ? 0 : 1} />
      )}
    </Stack>
  )
}
