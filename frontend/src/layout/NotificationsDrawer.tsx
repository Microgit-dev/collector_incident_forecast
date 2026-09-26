import { Badge, Button, Drawer, Group, Loader, Stack, Text, UnstyledButton } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { RISK } from '../api/labels'
import type { AppNotification } from '../api/types'

/** Сообщения пользователя: карточки, эскалации, заявки, учения. Щелчок — перейти и отметить прочитанным. */
export function NotificationsDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const list = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => api<Page<AppNotification>>('/notifications/', { query: { page_size: 50 } }),
    enabled: opened,
  })
  const refresh = () => client.invalidateQueries({ queryKey: ['notifications'] })
  const read = useMutation({
    mutationFn: (id: number) => api(`/notifications/${id}/read/`, { method: 'POST' }),
    onSuccess: refresh,
  })
  const readAll = useMutation({
    mutationFn: () => api('/notifications/read_all/', { method: 'POST' }),
    onSuccess: refresh,
  })
  const items = list.data?.results ?? []

  return (
    <Drawer opened={opened} onClose={onClose} position="right" title="Сообщения" size="md">
      <Group justify="flex-end" mb="xs">
        <Button size="compact-sm" variant="subtle" onClick={() => readAll.mutate()} disabled={!items.some((n) => !n.read_at)}>
          Прочитать все
        </Button>
      </Group>
      {list.isLoading && <Loader size="sm" />}
      <Stack gap={6}>
        {items.map((n) => (
          <UnstyledButton
            key={n.id}
            onClick={() => {
              if (!n.read_at) read.mutate(n.id)
              if (n.link) {
                navigate(n.link)
                onClose()
              }
            }}
            p="xs"
            style={{
              borderRadius: 8,
              border: '1px solid var(--mantine-color-default-border)',
              background: n.read_at ? undefined : 'var(--mantine-color-blue-light)',
            }}
          >
            <Group justify="space-between" wrap="nowrap" align="flex-start" gap="xs">
              <Text size="sm" fw={n.read_at ? 400 : 600}>
                {n.title}
              </Text>
              <Badge size="xs" variant="light" color={RISK[n.level]?.color ?? 'blue'} style={{ flexShrink: 0 }}>
                {dayjs(n.created_at).format('DD.MM HH:mm')}
              </Badge>
            </Group>
            {n.body && (
              <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-line' }} lineClamp={4}>
                {n.body}
              </Text>
            )}
          </UnstyledButton>
        ))}
        {!list.isLoading && !items.length && (
          <Text size="sm" c="dimmed">
            Сообщений нет.
          </Text>
        )}
      </Stack>
    </Drawer>
  )
}
