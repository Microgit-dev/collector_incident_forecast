import { Card, Grid, Group, SegmentedControl, Select, Stack, Switch, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api, type Page } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import {
  type ColorBy,
  type Layers,
  SchemeLegend,
  SchemeMap,
  SegmentDetails,
  type SegmentProps,
} from '../components/SchemeMap'
import { useRoutes } from '../components/useScheme'

interface NodeItem {
  id: number
  name: string
  depth: number
}

export function SchemePage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const node = params.get('node')
  const [task, setTask] = useState('all')
  const [colorBy, setColorBy] = useState<ColorBy>(can('forecasting.view_channelrisk') ? 'risk' : 'state')
  const [layers, setLayers] = useState<Layers>({
    objects: true,
    incidents: can('incidents.view_incident'),
    states: true,
    workorders: false,
  })
  const [selected, setSelected] = useState<SegmentProps | null>(null)

  const nodes = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () => api<Page<NodeItem>>('/topology/nodes/', { query: { page_size: 500, is_active: true } }),
    staleTime: 10 * 60_000,
  })
  const { routes, incidents, workorders } = useRoutes(node, task, layers.workorders)

  const options = (nodes.data?.results ?? [])
    .filter((n) => n.depth >= 2)
    .map((n) => ({ value: String(n.id), label: `${n.depth > 2 ? '   ' : ''}${n.name}` }))
  const selectedRoute = selected ? routes.find((r) => r.complex === selected.complex) : undefined
  const toggle = (key: keyof Layers, label: string) => (
    <Switch label={label} checked={layers[key]} onChange={(e) => setLayers({ ...layers, [key]: e.currentTarget.checked })} />
  )

  return (
    <Stack>
      <Title order={3}>Схема объектов</Title>
      <Text size="sm" c="dimmed">
        Линейная схема по пикетам: координат у заказчика нет, трасса каждого объекта строится по пикетам его каналов.
        Цвет участка — риск прогноза, качество данных или состояние каналов; точки — каналы не в норме и молчащие,
        треугольники — открытые карточки, ромбы — заявки. Щелчок по участку — подробности, по карточке — переход к ней.
      </Text>
      <Card withBorder radius="md">
        <Group wrap="wrap" align="flex-end">
          <Select
            label="Объект"
            placeholder="Все объекты"
            data={options}
            value={node}
            onChange={(v) => {
              setSelected(null)
              setParams(v ? { node: v } : {})
            }}
            searchable
            clearable
            w={300}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Окраска участков
            </Text>
            <SegmentedControl
              value={colorBy}
              onChange={(v) => setColorBy(v as ColorBy)}
              data={[
                ...(can('forecasting.view_channelrisk') ? [{ value: 'risk', label: 'Риск' }] : []),
                ...(can('forecasting.view_channelhealth') ? [{ value: 'health', label: 'Data Health' }] : []),
                { value: 'state', label: 'Состояние' },
              ]}
            />
          </Stack>
          {colorBy === 'risk' && (
            <SegmentedControl
              value={task}
              onChange={(v) => {
                setTask(v)
                setSelected(null)
              }}
              data={[
                { value: 'all', label: 'Все риски' },
                { value: 'sensor_failure', label: 'Отказ датчика' },
                { value: 'gas', label: 'Газ' },
                { value: 'flood', label: 'Подтопление' },
              ]}
            />
          )}
          {toggle('objects', 'Объекты и шкафы')}
          {can('incidents.view_incident') && toggle('incidents', 'Карточки')}
          {can('workorders.view_workorder') && toggle('workorders', 'Заявки')}
          {toggle('states', 'Состояния каналов')}
        </Group>
        <Group gap="md" mt="sm">
          <SchemeLegend colorBy={colorBy} layers={layers} />
          <Text size="xs" c="dimmed">
            На схеме: карточек {incidents}
            {layers.workorders ? `, заявок ${workorders}` : ''}
          </Text>
        </Group>
      </Card>

      <Grid>
        <Grid.Col span={{ base: 12, lg: selected ? 8 : 12 }}>
          <Card withBorder radius="md">
            <SchemeMap
              complex={node}
              task={task}
              layers={layers}
              colorBy={colorBy}
              selected={selected}
              onSelect={setSelected}
            />
          </Card>
        </Grid.Col>
        {selected && (
          <Grid.Col span={{ base: 12, lg: 4 }}>
            <SegmentDetails segment={selected} route={selectedRoute} />
          </Grid.Col>
        )}
      </Grid>
    </Stack>
  )
}
