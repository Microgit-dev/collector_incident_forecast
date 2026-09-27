/**
 * Проверка по камерам (ТЗ §12, шаг «Верификация»): ближайшие к месту тревоги камеры, кадр из архива
 * системы видеонаблюдения на момент тревоги и текущий кадр. Просмотр из карточки инцидента пишется
 * в её хронологию — видно, что проверка была.
 */
import { Anchor, Badge, Button, Card, Group, Image, Loader, SegmentedControl, Stack, Text } from '@mantine/core'
import { IconExternalLink, IconRefresh, IconVideo } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'

import { api, apiBlob } from '../api/client'

interface CameraRef {
  id: number
  name: string
  node: string
  picket: number | null
  distance: number | null
  live_url: string | null
}

interface CameraList {
  enabled: boolean
  mode: string
  alarm_at: string | null
  picket: number | null
  cameras: CameraRef[]
}

function Snapshot({ camera, at, incident }: { camera: CameraRef; at: string | null; incident?: number }) {
  const client = useQueryClient()
  const [url, setUrl] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const frame = useQuery({
    queryKey: ['camera-frame', camera.id, at, tick],
    queryFn: () =>
      apiBlob(`/integrations/cameras/${camera.id}/snapshot/`, { at: at ?? undefined, incident: incident ?? undefined }),
    staleTime: Infinity,
    retry: false,
  })
  useEffect(() => {
    if (!frame.data) return
    const next = URL.createObjectURL(frame.data)
    setUrl(next)
    // просмотр записан в хронологию карточки — обновить её
    if (incident) void client.invalidateQueries({ queryKey: ['incidents', incident] })
    return () => URL.revokeObjectURL(next)
  }, [frame.data, incident, client])
  return (
    <Stack gap={6}>
      {frame.isLoading ? (
        <Loader size="sm" />
      ) : frame.isError ? (
        <Text size="sm" c="red">
          {(frame.error as Error).message}
        </Text>
      ) : (
        url && <Image src={url} alt={`Кадр: ${camera.name}`} radius="sm" />
      )}
      <Group gap="xs">
        <Button
          size="compact-xs"
          variant="light"
          leftSection={<IconRefresh size={12} />}
          onClick={() => setTick((t) => t + 1)}
        >
          Обновить кадр
        </Button>
        {camera.live_url && (
          <Anchor href={camera.live_url} target="_blank" rel="noopener" size="xs">
            <Group gap={4}>
              Открыть в системе видеонаблюдения <IconExternalLink size={12} />
            </Group>
          </Anchor>
        )}
      </Group>
    </Stack>
  )
}

export function CameraPanel({ incident, prediction }: { incident?: number; prediction?: number }) {
  const [selected, setSelected] = useState<number | null>(null)
  const [moment, setMoment] = useState<'alarm' | 'now'>('alarm')
  const list = useQuery({
    queryKey: ['cameras', incident, prediction],
    queryFn: () => api<CameraList>('/integrations/cameras/', { query: { incident, prediction } }),
  })
  if (list.isLoading) return null
  const data = list.data
  if (!data?.enabled) return null
  const camera = data.cameras.find((c) => c.id === selected) ?? data.cameras[0]
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap={6}>
          <IconVideo size={18} />
          <Text fw={600}>Проверка по камерам</Text>
        </Group>
        {data.mode === 'mock' && (
          <Badge variant="light" color="gray" size="sm">
            эмуляция VMS
          </Badge>
        )}
      </Group>
      {!camera ? (
        <Text size="sm" c="dimmed">
          У объекта нет камер в реестре. Проверьте по обходу или добавьте камеры в «Администрировании».
        </Text>
      ) : (
        <Stack gap="sm">
          <Group gap={6}>
            {data.cameras.map((c) => (
              <Button
                key={c.id}
                size="compact-xs"
                variant={c.id === camera.id ? 'filled' : 'default'}
                onClick={() => setSelected(c.id)}
              >
                {c.name}
                {c.distance != null && ` · ${c.distance} пк`}
              </Button>
            ))}
          </Group>
          {data.alarm_at && (
            <SegmentedControl
              size="xs"
              value={moment}
              onChange={(v) => setMoment(v as 'alarm' | 'now')}
              data={[
                { value: 'alarm', label: `Момент тревоги ${dayjs(data.alarm_at).format('DD.MM HH:mm')}` },
                { value: 'now', label: 'Сейчас' },
              ]}
            />
          )}
          <Snapshot
            key={`${camera.id}-${moment}`}
            camera={camera}
            at={moment === 'alarm' ? data.alarm_at : null}
            incident={incident}
          />
          <Text size="xs" c="dimmed">
            Камеры отсортированы по расстоянию от места тревоги{data.picket != null && ` (ПК ${data.picket})`}. Кадр
            берётся из системы видеонаблюдения в режиме чтения; просмотр записывается в хронологию карточки.
          </Text>
        </Stack>
      )}
    </Card>
  )
}
