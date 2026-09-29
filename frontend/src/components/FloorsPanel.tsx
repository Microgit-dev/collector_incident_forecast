/**
 * Этажи объекта в редакторе структуры: планы помещений, контрольный этаж, привязка к местности.
 *
 * Порядок: контур здания (ИИ по снимку) → контрольный этаж привязывается к снимку и контуру →
 * остальные этажи привязываются к плану контрольного → датчики ставятся на этажи (вкладка «Датчики»).
 */
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  FileInput,
  Group,
  Menu,
  NumberInput,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconDots, IconEye, IconEyeOff, IconMapPin, IconPlus, IconUpload } from '@tabler/icons-react'
import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { api, upload } from '../api/client'
import type { Floor, MapConfig, StructureObject } from '../api/types'
import { FloorPlanEditor } from './FloorPlanEditor'

function fail(e: unknown) {
  notifications.show({ color: 'red', message: e instanceof Error ? e.message : 'Ошибка' })
}

export function FloorsPanel({
  object,
  floors,
  config,
  shown,
  setShown,
  changed,
}: {
  object: StructureObject
  floors: Floor[] | undefined
  config: MapConfig
  /** этаж, чей план показан на карте редактора */
  shown: number | null
  setShown: (id: number | null) => void
  changed: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [level, setLevel] = useState<number | string>('')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [editing, setEditing] = useState<Floor | null>(null)
  const replaceFor = useRef<Floor | null>(null)
  const replaceInput = useRef<HTMLInputElement>(null)
  const list = floors ?? []
  const nextLevel = list.length ? Math.max(...list.map((f) => f.level)) + 1 : 1

  const create = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('level', String(level === '' ? nextLevel : level))
      form.append('name', name)
      if (file) form.append('plan', file)
      return upload<Floor>(`/topology/objects/${object.id}/floors/`, form)
    },
    onSuccess: (f) => {
      notifications.show({
        color: 'teal',
        message: f.is_base ? `${f.title} — контрольный этаж; привяжите его план к снимку` : `${f.title} добавлен`,
      })
      setAdding(false)
      setFile(null)
      setName('')
      setLevel('')
      setShown(f.id)
      changed()
      if (f.plan) setEditing(f)
    },
    onError: fail,
  })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api<Floor>(`/topology/floors/${id}/`, { method: 'PATCH', body }),
    onSuccess: () => changed(),
    onError: fail,
  })
  const replace = useMutation({
    mutationFn: ({ floor, plan }: { floor: Floor; plan: File }) => {
      const form = new FormData()
      form.append('plan', plan)
      return upload<Floor>(`/topology/floors/${floor.id}/`, form, undefined, 'PATCH')
    },
    onSuccess: (f) => {
      notifications.show({ message: f.corners ? 'План заменён, привязка сохранена' : 'План заменён — привяжите его заново' })
      changed()
    },
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/topology/floors/${id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      notifications.show({ message: 'Этаж удалён, его датчики остались без этажа' })
      changed()
    },
    onError: fail,
  })

  const base = list.find((f) => f.is_base)

  return (
    <Stack gap="sm">
      <Text fw={600}>Этажи: {object.name}</Text>
      {!object.geometry && (
        <Alert color="yellow" p="xs">
          <Text size="xs">
            Сначала задайте контур здания на вкладке «Объекты» (лучше — «По снимку (ИИ)»): по нему привязывается
            контрольный этаж.
          </Text>
        </Alert>
      )}
      <Text size="xs" c="dimmed">
        Контрольный этаж привязывается к снимку и контуру здания, остальные — к его плану: так планы ложатся друг на
        друга. Датчики ставятся на этаж на вкладке «Датчики».
      </Text>

      {[...list].reverse().map((f) => (
        <Card key={f.id} withBorder padding="xs">
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Stack gap={2} style={{ minWidth: 0 }}>
              <Group gap={6}>
                <Text size="sm" fw={500}>
                  {f.title}
                </Text>
                {f.is_base && (
                  <Badge size="xs" color="grape" variant="light">
                    контрольный
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {!f.plan
                  ? 'план не загружен'
                  : f.corners
                    ? `привязан по ${f.points.filter((p) => p.on).length} точкам, невязка ${f.rmse_m?.toFixed(1)} м`
                    : 'план не привязан'}
                {` · датчиков ${f.sensors}`}
              </Text>
            </Stack>
            <Group gap={4} wrap="nowrap">
              <Tooltip label={shown === f.id ? 'Скрыть план на карте' : 'Показать план на карте'}>
                <ActionIcon variant={shown === f.id ? 'filled' : 'subtle'} onClick={() => setShown(shown === f.id ? null : f.id)} disabled={!f.corners}>
                  {shown === f.id ? <IconEye size={16} /> : <IconEyeOff size={16} />}
                </ActionIcon>
              </Tooltip>
              <Button size="compact-xs" variant="light" leftSection={<IconMapPin size={12} />} onClick={() => setEditing(f)} disabled={!f.plan}>
                Привязать
              </Button>
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <ActionIcon variant="subtle" aria-label="Действия с этажом">
                    <IconDots size={16} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  {!f.is_base && (
                    <Menu.Item onClick={() => patch.mutate({ id: f.id, body: { is_base: true } })}>Сделать контрольным</Menu.Item>
                  )}
                  <Menu.Item
                    leftSection={<IconUpload size={14} />}
                    onClick={() => {
                      replaceFor.current = f
                      replaceInput.current?.click()
                    }}
                  >
                    {f.plan ? 'Заменить план' : 'Загрузить план'}
                  </Menu.Item>
                  <Menu.Item
                    color="red"
                    onClick={() => {
                      if (window.confirm(`Удалить «${f.title}»? Датчики этажа останутся без этажа.`)) remove.mutate(f.id)
                    }}
                  >
                    Удалить этаж
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>
        </Card>
      ))}
      {floors && !list.length && !adding && (
        <Text size="sm" c="dimmed">
          Этажей нет. Первый добавленный этаж с планом станет контрольным.
        </Text>
      )}
      <input
        ref={replaceInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => {
          const plan = e.currentTarget.files?.[0]
          if (plan && replaceFor.current) replace.mutate({ floor: replaceFor.current, plan })
          e.currentTarget.value = ''
        }}
      />

      {adding ? (
        <Card withBorder padding="sm">
          <Stack gap="xs">
            <Group grow gap="xs">
              <NumberInput size="xs" label="Этаж" placeholder={String(nextLevel)} value={level} onChange={setLevel} min={-10} max={150} />
              <TextInput size="xs" label="Название" placeholder="необязательно" value={name} onChange={(e) => setName(e.currentTarget.value)} />
            </Group>
            <FileInput
              size="xs"
              label="План помещений"
              description="PNG, JPEG или WEBP до 25 МБ; скан или выгрузка из САПР"
              placeholder="выберите файл"
              accept="image/png,image/jpeg,image/webp"
              value={file}
              onChange={setFile}
              clearable
            />
            {!base && (
              <Text size="xs" c="grape">
                Этот этаж станет контрольным: к нему привязываются остальные.
              </Text>
            )}
            <Group justify="flex-end" gap="xs">
              <Button size="xs" variant="default" onClick={() => setAdding(false)}>
                Отмена
              </Button>
              <Button size="xs" onClick={() => create.mutate()} loading={create.isPending}>
                Добавить
              </Button>
            </Group>
          </Stack>
        </Card>
      ) : (
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setAdding(true)} style={{ alignSelf: 'flex-start' }}>
          Добавить этаж
        </Button>
      )}

      {editing && (
        <FloorPlanEditor
          floor={editing}
          floors={list}
          geometry={object.geometry}
          config={config}
          onClose={() => setEditing(null)}
          onSaved={(f) => {
            setEditing(null)
            setShown(f.id)
            changed()
          }}
        />
      )}
    </Stack>
  )
}
