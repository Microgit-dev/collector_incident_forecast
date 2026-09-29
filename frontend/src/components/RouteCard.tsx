/**
 * Маршрут нарушителя в карточке НСД: сработки охраны по времени — линией на карте объекта
 * (с планом этажа, если он привязан) и хронологией шагов. Подряд идущие сработки одного датчика
 * склеены в шаг на бэкенде (apps/incidents/route.py).
 */
import { ActionIcon, Badge, Box, Card, Group, SegmentedControl, Stack, Text, Timeline, Tooltip, useComputedColorScheme } from '@mantine/core'
import { IconSatellite, IconWalk } from '@tabler/icons-react'
import dayjs from 'dayjs'
import { useEffect, useRef, useState } from 'react'

import type { IntrusionRoute } from '../api/types'
import { createMap, maplibregl, type MapHandle } from '../map/engine'
import { bounds } from '../map/geometry'
import { setSatellite, showPlan, usePlanUrl } from '../map/plans'

const ROUTE = '#c2255c'
const EMPTY = { type: 'FeatureCollection' as const, features: [] }

function duration(seconds: number): string {
  if (seconds < 90) return `${seconds} с`
  if (seconds < 5400) return `${Math.round(seconds / 60)} мин`
  return `${(seconds / 3600).toFixed(1)} ч`
}

export function RouteCard({ route }: { route: IntrusionRoute }) {
  const dark = useComputedColorScheme('light') === 'dark'
  const box = useRef<HTMLDivElement>(null)
  const [handle, setHandle] = useState<MapHandle | null>(null)
  const [satellite, setSatelliteOn] = useState(false)
  const placed = route.floors.filter((f) => f.corners)
  // по умолчанию — этаж последней сработки: там нарушитель сейчас
  const lastFloor = [...route.steps].reverse().find((s) => s.floor)?.floor ?? null
  const [floorId, setFloorId] = useState<number | null>(
    placed.find((f) => f.id === lastFloor)?.id ?? placed.find((f) => f.is_base)?.id ?? null,
  )
  const floor = placed.find((f) => f.id === floorId)
  const planUrl = usePlanUrl(floor?.plan)

  useEffect(() => {
    if (!box.current) return
    const map = createMap(box.current, (dark ? route.map.dark : route.map.light) || null, dark, (h) => {
      const m = h.map
      m.addSource('object', { type: 'geojson', data: EMPTY })
      m.addSource('route', { type: 'geojson', data: EMPTY })
      m.addSource('steps', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'object-line', type: 'line', source: 'object', paint: { 'line-color': '#495057', 'line-width': 1.5 } })
      m.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ROUTE, 'line-width': 3.5, 'line-dasharray': [2, 1] },
      })
      m.addLayer({
        id: 'route-arrows',
        type: 'symbol',
        source: 'route',
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 50,
          'text-field': '›',
          'text-font': ['noto_sans_bold'],
          'text-size': 22,
          'text-keep-upright': false,
          'text-allow-overlap': true,
        },
        paint: { 'text-color': ROUTE, 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
      })
      m.addLayer({
        id: 'steps',
        type: 'circle',
        source: 'steps',
        paint: {
          'circle-radius': ['case', ['get', 'last'], 11, 9],
          'circle-color': ['case', ['get', 'last'], ROUTE, '#ffffff'],
          'circle-stroke-color': ROUTE,
          'circle-stroke-width': 2,
          'circle-opacity': ['case', ['get', 'other'], 0.45, 1],
        },
      })
      m.addLayer({
        id: 'step-labels',
        type: 'symbol',
        source: 'steps',
        layout: { 'text-field': ['get', 'n'], 'text-font': ['noto_sans_bold'], 'text-size': 11, 'text-allow-overlap': true },
        paint: { 'text-color': ['case', ['get', 'last'], '#ffffff', ROUTE] },
      })
      setHandle(h)
    })
    const resize = new ResizeObserver(() => map.resize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      setHandle(null)
      map.remove()
    }
  }, [dark, route.map])

  useEffect(() => {
    if (!handle) return
    const m = handle.map
    ;(m.getSource('object') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: route.geometry ? [{ type: 'Feature', properties: {}, geometry: route.geometry }] : [],
    })
    ;(m.getSource('route') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: route.line ? [{ type: 'Feature', properties: {}, geometry: route.line }] : [],
    })
    ;(m.getSource('steps') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: route.steps
        .filter((s) => s.position)
        .map((s) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: s.position! },
          // шаги на других этажах — бледнее, чтобы было видно, где нарушитель на показанном плане
          properties: { n: String(s.n), last: s.n === route.steps.length, other: Boolean(floorId && s.floor && s.floor !== floorId) },
        })),
    })
    const pts = route.steps.flatMap((s) => (s.position ? [s.position] : []))
    const b = bounds([route.geometry, pts.length ? { type: 'Polygon', coordinates: [[...pts, pts[0]]] } : null])
    if (b) m.fitBounds(b, { padding: 40, maxZoom: 19, duration: 0 })
  }, [handle, route, floorId])

  useEffect(() => {
    if (handle) setSatellite(handle.map, route.map, satellite, ['object-line'])
  }, [handle, route.map, satellite])
  useEffect(() => {
    if (handle) showPlan(handle.map, 'floor', planUrl, floor?.corners ?? null, floor?.opacity ?? 0.85, ['route-line'])
  }, [handle, planUrl, floor])

  const last = route.last
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap={6}>
          <IconWalk size={18} color={ROUTE} />
          <Text fw={600}>Маршрут нарушителя</Text>
        </Group>
        <Badge color="pink" variant="light">
          шагов {route.steps.length}
          {route.distance_m ? ` · ~${route.distance_m} м` : ''} · {duration(route.duration_s)}
        </Badge>
      </Group>
      <Text size="sm" mb={4}>
        Последняя сработка: <b>{last.name}</b> в {dayjs(last.at).format('HH:mm:ss')}
        {last.floor_title ? `, ${last.floor_title}` : ''}
        {route.heading ? `; движение ${route.heading}` : ''}.
      </Text>
      <Text size="xs" c="dimmed" mb="xs">
        Маршрут строится по сработкам охраны (люки, двери, датчики движения) в порядке времени. Это не факт
        проникновения: сверьте с нарядами-допусками и видеонаблюдением.
      </Text>
      <Box pos="relative" h={300} style={{ borderRadius: 8, overflow: 'hidden' }}>
        <div ref={box} style={{ position: 'absolute', inset: 0 }} />
        {route.map.satellite && (
          <Tooltip label={satellite ? 'Векторная карта' : 'Спутниковый снимок'}>
            <ActionIcon
              pos="absolute"
              bottom={30}
              right={8}
              variant={satellite ? 'filled' : 'default'}
              style={{ zIndex: 2 }}
              onClick={() => setSatelliteOn((v) => !v)}
              aria-label="Спутниковый снимок"
            >
              <IconSatellite size={16} />
            </ActionIcon>
          </Tooltip>
        )}
        {placed.length > 0 && (
          <SegmentedControl
            pos="absolute"
            top={8}
            left={8}
            size="xs"
            style={{ zIndex: 2 }}
            value={floorId ? String(floorId) : 'none'}
            onChange={(v) => setFloorId(v === 'none' ? null : Number(v))}
            data={[...placed.map((f) => ({ value: String(f.id), label: f.title })), { value: 'none', label: 'Без плана' }]}
          />
        )}
      </Box>
      <Timeline mt="sm" bulletSize={18} lineWidth={2} color="pink" active={route.steps.length - 1}>
        {route.steps.slice(-12).map((s) => (
          <Timeline.Item key={s.n} bullet={<Text size="10px">{s.n}</Text>} title={<Text size="sm">{s.name}</Text>}>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {dayjs(s.at).format('HH:mm:ss')}
                {s.count > 1 ? `–${dayjs(s.until).format('HH:mm:ss')}, сработок ${s.count}` : ''}
                {s.floor_title ? ` · ${s.floor_title}` : ''}
                {s.picket != null ? ` · ПК${s.picket}` : ''}
                {!s.placed ? ' · место по пикету' : ''}
              </Text>
            </Stack>
          </Timeline.Item>
        ))}
      </Timeline>
      {route.steps.length > 12 && (
        <Text size="xs" c="dimmed">
          Показаны последние 12 шагов из {route.steps.length}
        </Text>
      )}
    </Card>
  )
}
