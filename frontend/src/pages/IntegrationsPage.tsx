/**
 * Интеграции с системами заказчика (администратор): режим — эмуляция стенда или боевое подключение,
 * адрес, последний успешный обмен и ошибка, проверка связи и ручная синхронизация. Подключения
 * настраиваются в .env (docs/integrations.md), здесь — контроль.
 */
import { Alert, Badge, Button, Card, Code, Group, Loader, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconPlugConnected, IconRefresh } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'

import { api } from '../api/client'
import { openObservability } from '../api/observability'
import { useAuth } from '../auth/AuthContext'
import { RegistryImport } from '../components/RegistryImport'

interface Integration {
  code: string
  title: string
  purpose: string
  mode: string
  mode_label: string
  emulated: boolean
  endpoint: string
  can_sync: boolean
  sync_label: string
  last_ok_at: string | null
  last_error_at: string | null
  last_error: string
  last_result: Record<string, unknown>
}

interface ActionResult {
  ok: boolean
  result?: Record<string, unknown>
  error?: string
}

function summary(result: Record<string, unknown>): string {
  return Object.entries(result)
    .filter(([, v]) => v !== null && typeof v !== 'object')
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(' · ')
}

function IntegrationCard({ item }: { item: Integration }) {
  const client = useQueryClient()
  const act = useMutation({
    mutationFn: (action: 'check' | 'sync') =>
      api<ActionResult>(`/integrations/${item.code}/${action}/`, { method: 'POST' }),
    onSuccess: (r, action) => {
      notifications.show({
        color: r.ok ? 'teal' : 'red',
        title: `${item.title}: ${action === 'check' ? 'проверка связи' : item.sync_label.toLowerCase()}`,
        message: r.ok ? summary(r.result ?? {}) || 'успешно' : r.error,
      })
      void client.invalidateQueries({ queryKey: ['integrations'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  const failing = item.last_error_at && (!item.last_ok_at || dayjs(item.last_error_at).isAfter(item.last_ok_at))
  const status = item.mode === 'off' ? 'gray' : failing ? 'red' : item.last_ok_at ? 'teal' : 'yellow'
  return (
    <Card withBorder radius="md">
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div>
            <Text fw={600}>{item.title}</Text>
            <Text size="xs" c="dimmed">
              {item.purpose}
            </Text>
          </div>
          <Badge color={status} variant="dot" style={{ flexShrink: 0 }}>
            {item.mode === 'off' ? 'выключено' : failing ? 'ошибка' : item.last_ok_at ? 'на связи' : 'не проверялось'}
          </Badge>
        </Group>
        <Group gap="xs">
          <Badge variant="light" color={item.emulated ? 'gray' : 'blue'}>
            {item.emulated ? 'эмуляция' : 'боевой режим'}
          </Badge>
          <Text size="xs">{item.mode_label}</Text>
        </Group>
        <Code block style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {item.endpoint || '—'}
        </Code>
        <Text size="xs" c="dimmed">
          Последний обмен: {item.last_ok_at ? dayjs(item.last_ok_at).format('DD.MM.YYYY HH:mm:ss') : '—'}
          {Object.keys(item.last_result ?? {}).length > 0 && ` · ${summary(item.last_result)}`}
        </Text>
        {failing && (
          <Alert color="red" variant="light" p="xs">
            <Text size="xs">
              {dayjs(item.last_error_at!).format('DD.MM HH:mm')} — {item.last_error}
            </Text>
          </Alert>
        )}
        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlugConnected size={14} />}
            loading={act.isPending && act.variables === 'check'}
            onClick={() => act.mutate('check')}
          >
            Проверить связь
          </Button>
          {item.can_sync && (
            <Button
              size="xs"
              variant="default"
              leftSection={<IconRefresh size={14} />}
              loading={act.isPending && act.variables === 'sync'}
              onClick={() => act.mutate('sync')}
            >
              {item.sync_label}
            </Button>
          )}
          {item.code === 'observability' && (
            <>
              <Button size="xs" variant="subtle" onClick={() => void openObservability('system')}>
                Grafana
              </Button>
              <Button size="xs" variant="subtle" onClick={() => void openObservability('prometheus')}>
                Prometheus
              </Button>
            </>
          )}
        </Group>
        {item.code === 'registry' && <RegistryImport />}
      </Stack>
    </Card>
  )
}

export function IntegrationsPage() {
  const { can } = useAuth()
  const list = useQuery({
    queryKey: ['integrations'],
    queryFn: () => api<Integration[]>('/integrations/'),
    enabled: can('integrations.manage_integrations'),
    refetchInterval: 60_000,
  })
  return (
    <Stack>
      <div>
        <Title order={3}>Интеграции</Title>
        <Text size="sm" c="dimmed">
          Системы заказчика подключаются без правки кода — адреса, доступы и соответствие статусов задаются в .env
          (инструкция по развёртыванию, раздел «Интеграции»). С системами заказчика обмен только на чтение, кроме
          передачи утверждённых заявок.
        </Text>
      </div>
      {list.isLoading ? (
        <Loader />
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          {list.data?.map((item) => (
            <IntegrationCard key={item.code} item={item} />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  )
}
