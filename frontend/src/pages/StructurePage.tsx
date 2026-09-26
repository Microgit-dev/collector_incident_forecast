import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  ColorInput,
  Group,
  Loader,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  UnstyledButton,
  useComputedColorScheme,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconBuilding,
  IconCheck,
  IconCurrentLocation,
  IconPencil,
  IconPlus,
  IconPolygon,
  IconTrash,
  IconUserShare,
  IconX,
} from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from '../api/client'
import { ROLE } from '../api/labels'
import type {
  DetectedBuilding,
  LonLat,
  Polygon,
  Structure,
  StructureObject,
  StructurePerson,
  StructureSensor,
  StructureZone,
} from '../api/types'
import { createMap, maplibregl, type MapHandle } from '../map/engine'
import { areaM2, bounds, centroidOf, contains, simplify } from '../map/geometry'
import { PolygonEditor } from '../map/PolygonEditor'

type Tool = 'none' | 'draw' | 'edit' | 'pick' | 'point'
const EMPTY = { type: 'FeatureCollection' as const, features: [] }

function Dot({ color }: { color: string }) {
  return <Box w={10} h={10} style={{ borderRadius: 3, background: color, flexShrink: 0 }} />
}

/** Карта редактора: зоны, объекты, датчики выбранного объекта и контур в правке. */
function StructureMap({
  data,
  selectedObject,
  selectedZone,
  sensors,
  point,
  onReady,
  onClick,
}: {
  data: Structure
  selectedObject: number | null
  selectedZone: number | null
  sensors: StructureSensor[]
  point: LonLat | null
  onReady: (h: MapHandle, editor: PolygonEditor) => void
  onClick: (at: LonLat, objectId: number | null, building: Polygon | null) => void
}) {
  const dark = useComputedColorScheme('light') === 'dark'
  const box = useRef<HTMLDivElement>(null)
  const [handle, setHandle] = useState<MapHandle | null>(null)
  const click = useRef(onClick)
  click.current = onClick
  const ready = useRef(onReady)
  ready.current = onReady
  const fitted = useRef(false)

  useEffect(() => {
    if (!box.current) return
    const map = createMap(box.current, (dark ? data.map.dark : data.map.light) || null, dark, (h) => {
      const m = h.map
      for (const id of ['zones', 'zone-labels', 'objects', 'sensors', 'point']) m.addSource(id, { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'zones-fill', type: 'fill', source: 'zones', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['case', ['get', 'sel'], 0.14, 0.05] } })
      m.addLayer({ id: 'zones-line', type: 'line', source: 'zones', paint: { 'line-color': ['get', 'color'], 'line-width': ['case', ['get', 'sel'], 3, 1.5] } })
      m.addLayer({ id: 'objects-fill', type: 'fill', source: 'objects', paint: { 'fill-color': ['case', ['get', 'sel'], '#1c7ed6', '#495057'], 'fill-opacity': 0.45 } })
      m.addLayer({ id: 'objects-line', type: 'line', source: 'objects', paint: { 'line-color': ['case', ['get', 'sel'], '#1c7ed6', '#495057'], 'line-width': ['case', ['get', 'sel'], 3, 1] } })
      m.addLayer({
        id: 'sensors',
        type: 'circle',
        source: 'sensors',
        paint: { 'circle-radius': 5, 'circle-color': '#12b886', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 },
      })
      m.addLayer({
        id: 'point',
        type: 'circle',
        source: 'point',
        paint: { 'circle-radius': 8, 'circle-color': '#e03131', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 },
      })
      if (h.basemap) {
        m.addLayer({
          id: 'zone-labels',
          type: 'symbol',
          source: 'zone-labels',
          maxzoom: 15,
          layout: { 'text-field': ['get', 'name'], 'text-font': ['noto_sans_bold'], 'text-size': 13 },
          paint: { 'text-color': ['get', 'color'], 'text-halo-color': '#fff', 'text-halo-width': 2 },
        })
      }
      const editor = new PolygonEditor(m, () => undefined)
      m.on('click', (e) => {
        const hit = m.queryRenderedFeatures(e.point, { layers: ['objects-fill'] })
        // здание под точкой — прямо из векторной подложки (мгновенно, без внешнего запроса)
        let building: Polygon | null = null
        if (m.getLayer('building')) {
          const found = m.queryRenderedFeatures(e.point, { layers: ['building'] })[0]
          const g = found?.geometry
          if (g?.type === 'Polygon') building = { type: 'Polygon', coordinates: g.coordinates as number[][][] }
          else if (g?.type === 'MultiPolygon') {
            const parts = (g.coordinates as number[][][][]).map((c) => ({ type: 'Polygon' as const, coordinates: c }))
            building = parts.sort((a, b) => areaM2(b) - areaM2(a))[0] ?? null
          }
        }
        click.current([e.lngLat.lng, e.lngLat.lat], hit.length ? Number(hit[0].properties?.id) : null, building)
      })
      setHandle(h)
      ready.current(h, editor)
    })
    const resize = new ResizeObserver(() => map.resize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      setHandle(null)
      map.remove()
    }
    // стиль подложки меняется только с темой
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark])

  useEffect(() => {
    if (!handle) return
    const m = handle.map
    const zones = data.zones
      .filter((z) => z.geometry)
      .map((z) => ({ type: 'Feature' as const, properties: { id: z.id, name: z.name, color: z.color || '#1c7ed6', sel: z.id === selectedZone }, geometry: z.geometry! }))
    ;(m.getSource('zones') as maplibregl.GeoJSONSource).setData({ type: 'FeatureCollection', features: zones })
    // подпись — одна точка на зону, иначе она повторяется в каждом тайле
    ;(m.getSource('zone-labels') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: zones.map((f) => ({ ...f, geometry: { type: 'Point' as const, coordinates: centroidOf(f.geometry) } })),
    })
    ;(m.getSource('objects') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: data.objects
        .filter((o) => o.geometry)
        .map((o) => ({ type: 'Feature', properties: { id: o.id, name: o.name, sel: o.id === selectedObject }, geometry: o.geometry! })),
    })
    if (!fitted.current) {
      const b = bounds([...data.zones.map((z) => z.geometry), ...data.objects.map((o) => o.geometry)])
      if (b) {
        fitted.current = true
        m.fitBounds(b, { padding: 40, duration: 0, maxZoom: 16 })
      }
    }
  }, [handle, data, selectedObject, selectedZone])

  useEffect(() => {
    if (!handle) return
    ;(handle.map.getSource('sensors') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: sensors
        .filter((s) => s.location)
        .map((s) => ({ type: 'Feature', properties: { id: s.id }, geometry: { type: 'Point', coordinates: s.location! } })),
    })
    ;(handle.map.getSource('point') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: point ? [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: point } }] : [],
    })
  }, [handle, sensors, point])

  return <div ref={box} style={{ position: 'absolute', inset: 0 }} />
}

function fail(e: unknown) {
  notifications.show({ color: 'red', message: e instanceof Error ? e.message : 'Ошибка' })
}

export function StructurePage() {
  const client = useQueryClient()
  const phone = useMediaQuery('(max-width: 48em)')
  const q = useQuery({ queryKey: ['structure'], queryFn: () => api<Structure>('/topology/structure/') })
  const data = q.data
  const [chosenTab, setTab] = useState<string | null>(null)
  // вкладка по умолчанию — первая доступная по правам
  const tab =
    chosenTab ??
    (data ? (data.can.zones ? 'zones' : data.can.objects ? 'objects' : data.can.sensors ? 'sensors' : 'staff') : null)
  const [tool, setTool] = useState<Tool>('none')
  const [draft, setDraft] = useState<Polygon | null>(null)
  const [zoneId, setZoneId] = useState<number | null>(null)
  const [objectId, setObjectId] = useState<number | null>(null)
  const [candidate, setCandidate] = useState<DetectedBuilding | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [point, setPoint] = useState<LonLat | null>(null)
  const [pointFor, setPointFor] = useState<number | 'new' | null>(null)
  const map = useRef<MapHandle | null>(null)
  const editor = useRef<PolygonEditor | null>(null)
  const [editorReady, setEditorReady] = useState(0)

  const refresh = () => void client.invalidateQueries({ queryKey: ['structure'] })
  const sensors = useQuery({
    queryKey: ['structure-sensors', objectId],
    queryFn: () => api<StructureSensor[]>(`/topology/objects/${objectId}/`),
    enabled: objectId != null && tab === 'sensors',
  })

  // черновик контура из редактора
  useEffect(() => {
    editor.current?.listen(setDraft)
  }, [editorReady])

  const resetTool = () => {
    editor.current?.clear()
    setTool('none')
    setDraft(null)
    setCandidate(null)
    setPoint(null)
    setPointFor(null)
  }

  const fly = (poly: Polygon | null | undefined) => {
    const b = bounds([poly])
    if (b && map.current) map.current.map.fitBounds(b, { padding: 60, maxZoom: 18, duration: 500 })
  }

  const zoneAt = (at: LonLat) => data?.zones.find((z) => contains(z.geometry, at))

  const onMapClick = async (at: LonLat, hitObject: number | null, building: Polygon | null) => {
    if (tool === 'pick' && building && areaM2(building) >= 20) {
      // контур из подложки; на стыке тайлов он может быть обрезан — тогда поправить вершины или «Выделить заново»
      building = simplify(building)
      const b: DetectedBuilding = {
        geometry: building,
        source: 'osm:tiles',
        name: '',
        address: '',
        levels: null,
        area_m2: Math.round(areaM2(building)),
        center: centroidOf(building),
        exact: true,
      }
      setCandidate(b)
      editor.current?.edit(building)
      setDraft(building)
      setTool('edit')
      // адрес здания — из OpenStreetMap в фоне; контур остаётся тем, что на экране
      void api<DetectedBuilding>('/topology/detect-building/', { query: { lon: at[0], lat: at[1] } })
        .then((osm) => {
          if (osm.exact) setCandidate((c) => (c && c.source === 'osm:tiles' ? { ...c, name: osm.name, address: osm.address, levels: osm.levels } : c))
        })
        .catch(() => undefined)
      return
    }
    if (tool === 'pick') {
      setDetecting(true)
      try {
        const b = await api<DetectedBuilding>('/topology/detect-building/', { query: { lon: at[0], lat: at[1] } })
        setCandidate(b)
        editor.current?.edit(b.geometry)
        setDraft(b.geometry)
        setTool('edit')
      } catch (e) {
        notifications.show({ color: 'orange', message: e instanceof ApiError ? e.message : 'Не удалось выделить здание' })
      } finally {
        setDetecting(false)
      }
      return
    }
    if (tool === 'point') {
      setPoint(at)
      return
    }
    if (tool === 'none' && hitObject != null && tab !== 'zones') setObjectId(hitObject)
  }

  if (q.isError) {
    return <Alert color="red">Раздел доступен руководителю, аналитику и администратору.</Alert>
  }
  if (!data) return <Loader />

  const zoneOptions = data.zones.map((z) => ({ value: String(z.id), label: z.name }))
  const toolbar =
    tool !== 'none' ? (
      <Paper shadow="sm" withBorder p={6} radius="md" pos="absolute" top={8} left={8} style={{ zIndex: 2 }} maw="calc(100% - 60px)">
        <Group gap={6}>
          <Text size="xs" fw={500}>
            {tool === 'draw' && 'Щёлкайте по карте — вершины контура; двойной щелчок или «Готово» замыкает'}
            {tool === 'edit' && 'Тяните вершины, щелчок по точке на ребре — новая вершина'}
            {tool === 'pick' && (detecting ? 'Ищу здание…' : 'Щёлкните по зданию — контур выделится сам')}
            {tool === 'point' && 'Щёлкните место датчика на карте'}
          </Text>
          {tool === 'draw' && (
            <Button size="compact-xs" onClick={() => editor.current?.finishDraw()} leftSection={<IconCheck size={12} />}>
              Готово
            </Button>
          )}
          {tool === 'edit' && (
            <ActionIcon size="sm" variant="light" color="red" onClick={() => editor.current?.deleteSelected()} aria-label="Удалить вершину">
              <IconTrash size={14} />
            </ActionIcon>
          )}
          <ActionIcon size="sm" variant="subtle" onClick={resetTool} aria-label="Отменить">
            <IconX size={14} />
          </ActionIcon>
        </Group>
      </Paper>
    ) : null

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={3}>Зоны и объекты</Title>
        <Text size="sm" c="dimmed">
          {data.district.name}
        </Text>
      </Group>
      <Box
        style={{
          display: 'flex',
          flexDirection: phone ? 'column' : 'row',
          gap: 'var(--mantine-spacing-md)',
          height: phone ? undefined : 'calc(100dvh - var(--app-shell-header-height, 56px) - 110px)',
          minHeight: phone ? undefined : 480,
        }}
      >
        <Paper withBorder radius="md" pos="relative" style={{ flex: 1, minHeight: phone ? '45vh' : undefined, overflow: 'hidden' }}>
          <StructureMap
            data={data}
            selectedObject={objectId}
            selectedZone={zoneId}
            sensors={sensors.data ?? []}
            point={point}
            onReady={(h, ed) => {
              map.current = h
              editor.current = ed
              setEditorReady((n) => n + 1)
            }}
            onClick={onMapClick}
          />
          {toolbar}
        </Paper>
        <Paper withBorder radius="md" p="sm" w={phone ? undefined : 420} style={{ display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <Tabs
            value={tab}
            onChange={(v) => {
              resetTool()
              setTab(v)
            }}
            style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}
          >
            <Tabs.List grow>
              {data.can.zones && <Tabs.Tab value="zones">Зоны</Tabs.Tab>}
              {data.can.objects && <Tabs.Tab value="objects">Объекты</Tabs.Tab>}
              {data.can.sensors && <Tabs.Tab value="sensors">Датчики</Tabs.Tab>}
              {data.can.staff && <Tabs.Tab value="staff">Сотрудники</Tabs.Tab>}
            </Tabs.List>
            <ScrollArea style={{ flex: 1 }} mt="sm" offsetScrollbars>
              <Tabs.Panel value="zones">
                <ZonesTab
                  key={zoneId ?? 'list'}
                  data={data}
                  zoneId={zoneId}
                  setZoneId={(id) => {
                    setZoneId(id)
                    fly(data.zones.find((z) => z.id === id)?.geometry)
                  }}
                  tool={tool}
                  draft={draft}
                  startDraw={() => {
                    editor.current?.startDraw()
                    setTool('draw')
                    setDraft(null)
                  }}
                  startEdit={(p) => {
                    editor.current?.edit(p)
                    setDraft(p)
                    setTool('edit')
                  }}
                  done={() => {
                    resetTool()
                    refresh()
                  }}
                />
              </Tabs.Panel>
              <Tabs.Panel value="objects">
                <ObjectsTab
                  data={data}
                  objectId={objectId}
                  setObjectId={(id) => {
                    setObjectId(id)
                    fly(data.objects.find((o) => o.id === id)?.geometry)
                  }}
                  tool={tool}
                  draft={draft}
                  candidate={candidate}
                  zoneAt={zoneAt}
                  zoneOptions={zoneOptions}
                  startPick={() => {
                    editor.current?.clear()
                    setCandidate(null)
                    setDraft(null)
                    setTool('pick')
                  }}
                  startDraw={() => {
                    editor.current?.startDraw()
                    setCandidate(null)
                    setTool('draw')
                  }}
                  startEdit={(p) => {
                    editor.current?.edit(p)
                    setDraft(p)
                    setTool('edit')
                  }}
                  done={() => {
                    resetTool()
                    refresh()
                  }}
                />
              </Tabs.Panel>
              <Tabs.Panel value="sensors">
                <SensorsTab
                  data={data}
                  objectId={objectId}
                  setObjectId={(id) => {
                    setObjectId(id)
                    fly(data.objects.find((o) => o.id === id)?.geometry)
                  }}
                  sensors={sensors.data}
                  loading={sensors.isLoading}
                  point={point}
                  pointFor={pointFor}
                  askPoint={(target) => {
                    setPointFor(target)
                    setPoint(null)
                    setTool('point')
                  }}
                  done={() => {
                    resetTool()
                    void client.invalidateQueries({ queryKey: ['structure-sensors'] })
                    refresh()
                  }}
                />
              </Tabs.Panel>
              <Tabs.Panel value="staff">
                <StaffTab data={data} done={refresh} />
              </Tabs.Panel>
            </ScrollArea>
          </Tabs>
        </Paper>
      </Box>
    </Stack>
  )
}

// ---------------- зоны ----------------

function ZonesTab({
  data,
  zoneId,
  setZoneId,
  tool,
  draft,
  startDraw,
  startEdit,
  done,
}: {
  data: Structure
  zoneId: number | null
  setZoneId: (id: number | null) => void
  tool: Tool
  draft: Polygon | null
  startDraw: () => void
  startEdit: (p: Polygon | null) => void
  done: () => void
}) {
  const zone = data.zones.find((z) => z.id === zoneId)
  const [creating, setCreating] = useState(false)
  // форма берёт значения выбранной зоны при монтировании; при смене зоны компонент пересоздаётся (key)
  const [name, setName] = useState(zone?.name ?? '')
  const [color, setColor] = useState(zone?.color ?? '')
  const [adjacent, setAdjacent] = useState<string[]>((zone?.adjacent ?? []).map(String))

  const save = useMutation({
    mutationFn: () =>
      creating
        ? api<StructureZone>('/topology/zones/', { method: 'POST', body: { name, color, geometry: draft } })
        : api<StructureZone>(`/topology/zones/${zoneId}/`, {
            method: 'PATCH',
            body: { name, color, adjacent: adjacent.map(Number), ...(draft ? { geometry: draft } : {}) },
          }),
    onSuccess: (z) => {
      notifications.show({ color: 'teal', message: creating ? `Зона «${z.name}» создана` : 'Зона сохранена' })
      setCreating(false)
      setZoneId(z.id)
      done()
    },
    onError: fail,
  })
  const suggest = useMutation({
    mutationFn: () => api<{ suggested: number[] }>(`/topology/zones/${zoneId}/`),
    onSuccess: (r) => {
      setAdjacent(r.suggested.map(String))
      notifications.show({ message: r.suggested.length ? 'Смежные подобраны по карте — проверьте и сохраните' : 'Рядом зон нет' })
    },
  })

  if (creating || zone) {
    return (
      <Stack gap="sm">
        <Text fw={600}>{creating ? 'Новая зона' : zone!.name}</Text>
        <TextInput label="Название" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <ColorInput label="Цвет на карте" value={color} onChange={setColor} placeholder="подберётся сам" />
        {!creating && (
          <>
            <MultiSelect
              label="Смежные зоны"
              description="К соседям сотрудников направляют без «крайнего случая»; их объекты видны подробнее"
              data={data.zones.filter((z) => z.id !== zoneId).map((z) => ({ value: String(z.id), label: z.name }))}
              value={adjacent}
              onChange={setAdjacent}
            />
            <Button size="xs" variant="subtle" onClick={() => suggest.mutate()} loading={suggest.isPending} style={{ alignSelf: 'flex-start' }}>
              Подобрать смежные по карте
            </Button>
            <Text size="xs" c="dimmed">
              Объектов: {zone!.objects} · сотрудников: {zone!.staff}
            </Text>
          </>
        )}
        <Group gap="xs">
          {creating ? (
            <Button size="xs" variant="light" leftSection={<IconPolygon size={14} />} onClick={startDraw}>
              {draft ? 'Обвести заново' : 'Обвести границу'}
            </Button>
          ) : (
            <Button size="xs" variant="light" leftSection={<IconPencil size={14} />} onClick={() => startEdit(zone!.geometry)} disabled={tool === 'edit'}>
              Изменить границу
            </Button>
          )}
          {draft && (
            <Badge color="orange" variant="light">
              контур изменён
            </Badge>
          )}
        </Group>
        <Group justify="flex-end" gap="xs">
          <Button
            size="xs"
            variant="default"
            onClick={() => {
              setCreating(false)
              setZoneId(null)
              done()
            }}
          >
            Закрыть
          </Button>
          <Button size="xs" onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim() || (creating && !draft)}>
            Сохранить
          </Button>
        </Group>
      </Stack>
    )
  }

  return (
    <Stack gap="xs">
      <Button
        size="xs"
        leftSection={<IconPlus size={14} />}
        onClick={() => {
          setCreating(true)
          setName('')
          setColor('')
          startDraw()
        }}
      >
        Новая зона
      </Button>
      {data.zones.map((z) => (
        <UnstyledButton key={z.id} onClick={() => setZoneId(z.id)} py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
          <Group gap="xs" wrap="nowrap">
            <Dot color={z.color || '#1c7ed6'} />
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={500} truncate>
                {z.name}
              </Text>
              <Text size="xs" c="dimmed">
                объектов {z.objects} · сотрудников {z.staff} · смежных {z.adjacent.length}
                {!z.geometry && ' · граница не задана'}
              </Text>
            </Box>
          </Group>
        </UnstyledButton>
      ))}
      {!data.zones.length && (
        <Text size="sm" c="dimmed">
          Зон пока нет — обведите первую на карте.
        </Text>
      )}
    </Stack>
  )
}

// ---------------- объекты ----------------

function ObjectsTab({
  data,
  objectId,
  setObjectId,
  tool,
  draft,
  candidate,
  zoneAt,
  zoneOptions,
  startPick,
  startDraw,
  startEdit,
  done,
}: {
  data: Structure
  objectId: number | null
  setObjectId: (id: number | null) => void
  tool: Tool
  draft: Polygon | null
  candidate: DetectedBuilding | null
  zoneAt: (at: LonLat) => StructureZone | undefined
  zoneOptions: { value: string; label: string }[]
  startPick: () => void
  startDraw: () => void
  startEdit: (p: Polygon | null) => void
  done: () => void
}) {
  const obj = data.objects.find((o) => o.id === objectId)
  const [creating, setCreating] = useState(false)
  const [filter, setFilter] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [zone, setZone] = useState<string | null>(null)
  const [criticality, setCriticality] = useState<number | string>(3)
  useEffect(() => {
    setName(obj?.name ?? '')
    setZone(obj?.zone ? String(obj.zone) : null)
    setCriticality(obj?.criticality ?? 3)
  }, [obj])
  // предложение автовыделения: название — из OSM, зона — по контуру
  useEffect(() => {
    if (!candidate || !creating) return
    if (!name) setName(candidate.name || candidate.address || '')
    const z = zoneAt(candidate.center)
    if (z) setZone(String(z.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidate])

  const save = useMutation({
    mutationFn: () =>
      creating
        ? api<StructureObject & { warning?: string }>('/topology/objects/', {
            method: 'POST',
            body: { name, zone: zone ? Number(zone) : null, criticality, geometry: draft, source: candidate?.source ?? 'manual' },
          })
        : api<StructureObject>(`/topology/objects/${objectId}/`, {
            method: 'PATCH',
            body: { name, criticality, zone: zone ? Number(zone) : undefined, ...(draft ? { geometry: draft, source: candidate?.source ?? 'manual' } : {}) },
          }),
    onSuccess: (o) => {
      notifications.show({ color: 'teal', message: creating ? `Объект «${o.name}» создан` : 'Объект сохранён' })
      if ('warning' in o && o.warning) notifications.show({ color: 'orange', message: o.warning as string })
      setCreating(false)
      setObjectId(o.id)
      done()
    },
    onError: fail,
  })

  if (creating || obj) {
    return (
      <Stack gap="sm">
        <Text fw={600}>{creating ? 'Новый объект' : obj!.name}</Text>
        {creating && !draft && (
          <Card withBorder padding="sm">
            <Stack gap={6}>
              <Text size="sm">
                Щёлкните по зданию на карте — контур выделится автоматически по данным OpenStreetMap. Его можно поправить
                перед сохранением.
              </Text>
              <Group gap="xs">
                <Button size="xs" leftSection={<IconBuilding size={14} />} onClick={startPick} variant={tool === 'pick' ? 'filled' : 'light'} disabled={!data.overpass}>
                  Выделить здание
                </Button>
                <Button size="xs" variant="default" leftSection={<IconPolygon size={14} />} onClick={startDraw}>
                  Обвести вручную
                </Button>
              </Group>
              {!data.overpass && (
                <Text size="xs" c="dimmed">
                  Автовыделение выключено (нет картографического сервиса) — обведите контур вручную.
                </Text>
              )}
            </Stack>
          </Card>
        )}
        {candidate && (
          <Alert color={candidate.exact ? 'teal' : 'yellow'} p="xs" title={candidate.exact ? 'Здание выделено' : 'Ближайшее здание'}>
            <Text size="xs">
              {[candidate.name, candidate.address].filter(Boolean).join(', ') || 'без адреса'} · {candidate.area_m2} м²
              {candidate.levels ? ` · этажей ${candidate.levels}` : ''} · {candidate.source}
            </Text>
            <Text size="xs" c="dimmed">
              Поправьте контур на карте, если нужно, и сохраните.
            </Text>
          </Alert>
        )}
        <TextInput label="Название" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Select label="Зона" data={zoneOptions} value={zone} onChange={setZone} placeholder="выберите зону" />
        <NumberInput label="Критичность (1–5)" min={1} max={5} value={criticality} onChange={setCriticality} />
        {!creating && (
          <Group gap="xs">
            <Button size="xs" variant="light" leftSection={<IconPencil size={14} />} onClick={() => startEdit(obj!.geometry)} disabled={!obj!.geometry}>
              Изменить контур
            </Button>
            <Button size="xs" variant="default" leftSection={<IconBuilding size={14} />} onClick={startPick} disabled={!data.overpass}>
              Выделить заново
            </Button>
          </Group>
        )}
        {!creating && (
          <Text size="xs" c="dimmed">
            Каналов: {obj!.channels} · контур: {obj!.source || 'не задан'}
          </Text>
        )}
        <Group justify="flex-end" gap="xs">
          <Button
            size="xs"
            variant="default"
            onClick={() => {
              setCreating(false)
              setObjectId(null)
              done()
            }}
          >
            Закрыть
          </Button>
          <Button size="xs" onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim() || !zone || (creating && !draft)}>
            Сохранить
          </Button>
        </Group>
      </Stack>
    )
  }

  const rows = data.objects.filter((o) => !filter || String(o.zone) === filter)
  return (
    <Stack gap="xs">
      <Button
        size="xs"
        leftSection={<IconPlus size={14} />}
        onClick={() => {
          setCreating(true)
          setName('')
          setZone(filter)
          startPick()
        }}
      >
        Новый объект
      </Button>
      <Select size="xs" placeholder="Все зоны" data={zoneOptions} value={filter} onChange={setFilter} clearable />
      {rows.map((o) => (
        <UnstyledButton key={o.id} onClick={() => setObjectId(o.id)} py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
          <Text size="sm" fw={500} truncate>
            {o.name}
          </Text>
          <Text size="xs" c="dimmed">
            {data.zones.find((z) => z.id === o.zone)?.name ?? 'без зоны'} · каналов {o.channels}
            {!o.geometry && ' · не на карте'}
          </Text>
        </UnstyledButton>
      ))}
    </Stack>
  )
}

// ---------------- датчики ----------------

function SensorsTab({
  data,
  objectId,
  setObjectId,
  sensors,
  loading,
  point,
  pointFor,
  askPoint,
  done,
}: {
  data: Structure
  objectId: number | null
  setObjectId: (id: number | null) => void
  sensors?: StructureSensor[]
  loading: boolean
  point: LonLat | null
  pointFor: number | 'new' | null
  askPoint: (target: number | 'new') => void
  done: () => void
}) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [type, setType] = useState<string | null>(null)
  const [picket, setPicket] = useState<number | string>('')
  const [target, setTarget] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const obj = data.objects.find((o) => o.id === objectId)
  const nodes = useMemo(
    () => [
      ...(obj ? [{ value: String(obj.id), label: `Объект: ${obj.name}` }] : []),
      ...data.zones.map((z) => ({ value: String(z.id), label: `Зона: ${z.name}` })),
      ...data.objects.filter((o) => o.id !== objectId).map((o) => ({ value: String(o.id), label: `Объект: ${o.name}` })),
    ],
    [data, obj, objectId],
  )
  const types = useMemo(() => {
    const groups = new Map<string, { value: string; label: string }[]>()
    for (const t of data.sensor_types) {
      const g = t.system_type || 'Прочее'
      groups.set(g, [...(groups.get(g) ?? []), { value: String(t.id), label: t.name }])
    }
    return [...groups].map(([group, items]) => ({ group, items }))
  }, [data])

  const create = useMutation({
    mutationFn: () =>
      api<{ external_id: number; name: string }>('/topology/sensors/', {
        method: 'POST',
        body: { node: Number(target ?? objectId), name, sensor_type: type ? Number(type) : null, picket: picket === '' ? null : picket, location: pointFor === 'new' ? point : null },
      }),
    onSuccess: (s) => {
      notifications.show({ color: 'teal', message: `Датчик «${s.name}» создан, ид канала ${s.external_id} — задайте его в СМВУ` })
      setCreating(false)
      setName('')
      done()
    },
    onError: fail,
  })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api(`/topology/sensors/${id}/`, { method: 'PATCH', body }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Датчик обновлён' })
      done()
    },
    onError: fail,
  })

  return (
    <Stack gap="sm">
      <Select
        label="Объект"
        searchable
        data={data.objects.map((o) => ({ value: String(o.id), label: o.name }))}
        value={objectId ? String(objectId) : null}
        onChange={(v) => setObjectId(v ? Number(v) : null)}
        placeholder="выберите объект или щёлкните его на карте"
      />
      {objectId != null && !creating && (
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => { setCreating(true); setTarget(String(objectId)) }}>
          Новый датчик
        </Button>
      )}
      {creating && (
        <Card withBorder padding="sm">
          <Stack gap="xs">
            <TextInput size="xs" label="Название" placeholder="например, Газ ПК12" value={name} onChange={(e) => setName(e.currentTarget.value)} />
            <Select size="xs" label="Тип датчика" searchable data={types} value={type} onChange={setType} />
            <NumberInput size="xs" label="Пикет" value={picket} onChange={setPicket} decimalScale={2} />
            <Select size="xs" label="Прикрепить к" data={nodes} value={target} onChange={setTarget} />
            <Group gap="xs">
              <Button size="xs" variant="light" leftSection={<IconCurrentLocation size={14} />} onClick={() => askPoint('new')}>
                {pointFor === 'new' && point ? 'Точка выбрана — изменить' : 'Точка на карте'}
              </Button>
            </Group>
            <Group justify="flex-end" gap="xs">
              <Button size="xs" variant="default" onClick={() => setCreating(false)}>
                Отмена
              </Button>
              <Button size="xs" onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim()}>
                Создать
              </Button>
            </Group>
          </Stack>
        </Card>
      )}
      {typeof pointFor === 'number' && (
        <Alert p="xs" color="blue">
          <Group justify="space-between" gap="xs">
            <Text size="xs">{point ? 'Точка выбрана' : 'Щёлкните место датчика на карте'}</Text>
            <Button size="compact-xs" disabled={!point} onClick={() => patch.mutate({ id: pointFor, body: { location: point } })}>
              Сохранить точку
            </Button>
          </Group>
        </Alert>
      )}
      {loading && <Loader size="sm" />}
      {sensors && (
        <>
          <TextInput size="xs" placeholder="Найти датчик" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
          <Text size="xs" c="dimmed">
            Датчиков: {sensors.length}, с точкой на карте: {sensors.filter((s) => s.location).length}
          </Text>
          {sensors
            .filter((s) => !q || s.name.toLowerCase().includes(q.toLowerCase()))
            .slice(0, 80)
            .map((s) => (
              <Group key={s.id} gap={6} wrap="nowrap" py={4} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                <Box style={{ flex: 1, minWidth: 0 }}>
                  <Text size="sm" truncate>
                    {s.name}
                    {s.manual && (
                      <Badge size="xs" variant="light" ml={4}>
                        вручную
                      </Badge>
                    )}
                  </Text>
                  <Text size="xs" c="dimmed" truncate>
                    {s.type || 'тип не задан'} · {s.node_name} · ид {s.external_id}
                    {s.location ? ' · на карте' : ''}
                  </Text>
                </Box>
                <ActionIcon size="sm" variant="subtle" onClick={() => askPoint(s.id)} aria-label="Точка на карте">
                  <IconCurrentLocation size={14} />
                </ActionIcon>
                <Select
                  size="xs"
                  w={120}
                  placeholder="прикрепить"
                  data={nodes}
                  value={null}
                  onChange={(v) => v && patch.mutate({ id: s.id, body: { node: Number(v) } })}
                  comboboxProps={{ width: 260, position: 'bottom-end' }}
                />
              </Group>
            ))}
        </>
      )}
    </Stack>
  )
}

// ---------------- сотрудники ----------------

function StaffTab({ data, done }: { data: Structure; done: () => void }) {
  const [sending, setSending] = useState<StructurePerson | null>(null)
  const [zone, setZone] = useState<string | null>(null)
  const [hours, setHours] = useState<number | string>(8)
  const [reason, setReason] = useState('')
  const [emergency, setEmergency] = useState(false)
  const [q, setQ] = useState('')
  const zoneById = new Map(data.zones.map((z) => [z.id, z]))
  const scopes = [
    { value: String(data.district.id), label: `Район: ${data.district.name}` },
    ...data.zones.map((z) => ({ value: String(z.id), label: `Зона: ${z.name}` })),
    ...data.objects.map((o) => ({ value: String(o.id), label: `Объект: ${o.name}` })),
  ]
  const home = sending?.zone ? zoneById.get(sending.zone) : undefined
  const adjacent = (id: number) => Boolean(home && (home.id === id || home.adjacent.includes(id)))
  const needEmergency = zone != null && !adjacent(Number(zone))

  const assign = useMutation({
    mutationFn: ({ user, node }: { user: number; node: number }) => api(`/topology/staff/${user}/assign/`, { method: 'POST', body: { node } }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Зона ответственности назначена, сотрудник уведомлён' })
      done()
    },
    onError: fail,
  })
  const second = useMutation({
    mutationFn: () =>
      api(`/topology/staff/${sending!.id}/second/`, {
        method: 'POST',
        body: { zone: Number(zone), hours, reason, emergency: needEmergency && emergency },
      }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: 'Сотрудник направлен и уведомлён' })
      setSending(null)
      done()
    },
    onError: fail,
  })
  const recall = useMutation({
    mutationFn: (id: number) => api(`/topology/secondments/${id}/recall/`, { method: 'POST' }),
    onSuccess: () => {
      notifications.show({ message: 'Командирование отозвано' })
      done()
    },
    onError: fail,
  })

  return (
    <Stack gap="sm">
      {data.secondments.length > 0 && (
        <Card withBorder padding="sm">
          <Text size="sm" fw={600} mb={4}>
            Командированы сейчас
          </Text>
          {data.secondments.map((s) => (
            <Group key={s.id} justify="space-between" wrap="nowrap" gap="xs">
              <Box style={{ minWidth: 0 }}>
                <Text size="sm" truncate>
                  {s.user_name} → {s.zone_name}
                  {s.emergency && (
                    <Badge size="xs" color="red" variant="light" ml={4}>
                      крайний случай
                    </Badge>
                  )}
                </Text>
                <Text size="xs" c="dimmed">
                  до {dayjs(s.ends_at).format('DD.MM HH:mm')}
                  {s.reason ? ` · ${s.reason}` : ''}
                </Text>
              </Box>
              <Button size="compact-xs" variant="subtle" color="red" onClick={() => recall.mutate(s.id)}>
                Отозвать
              </Button>
            </Group>
          ))}
        </Card>
      )}
      <TextInput size="xs" placeholder="Найти сотрудника" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      {data.staff
        .filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
        .map((p) => (
          <Stack key={p.id} gap={4} py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Box style={{ minWidth: 0 }}>
                <Text size="sm" fw={500} truncate>
                  {p.name}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {p.roles.map((r) => ROLE[r] ?? r).join(', ')}
                  {p.team ? ` · ${p.team}` : ''}
                </Text>
              </Box>
              <ActionIcon
                variant="light"
                onClick={() => {
                  setSending(p)
                  setZone(null)
                  setReason('')
                  setEmergency(false)
                  setHours(8)
                }}
                aria-label="Направить в другую зону"
                title="Направить в другую зону"
              >
                <IconUserShare size={16} />
              </ActionIcon>
            </Group>
            <Select
              size="xs"
              data={scopes}
              value={p.scope ? String(p.scope) : null}
              onChange={(v) => v && Number(v) !== p.scope && assign.mutate({ user: p.id, node: Number(v) })}
              searchable
              aria-label="Зона ответственности"
            />
          </Stack>
        ))}

      <Modal opened={sending != null} onClose={() => setSending(null)} title={`Направить: ${sending?.name ?? ''}`}>
        <Stack>
          <Text size="sm" c="dimmed">
            Сотрудник временно работает в другой зоне: видит её карточки и получает её уведомления, свою зону не теряет.
            {home ? ` Своя зона: ${home.name}.` : ''}
          </Text>
          <Select
            label="Зона"
            data={data.zones
              .filter((z) => z.id !== home?.id)
              .map((z) => ({ value: String(z.id), label: `${z.name}${adjacent(z.id) ? ' · смежная' : ''}` }))}
            value={zone}
            onChange={setZone}
          />
          <NumberInput label="На сколько часов" min={0.5} max={72} step={1} value={hours} onChange={setHours} />
          <TextInput label="Причина" value={reason} onChange={(e) => setReason(e.currentTarget.value)} placeholder="например, усиление смены при аварии" />
          {needEmergency && (
            <Alert color="red" p="xs">
              <Checkbox
                label="Крайний случай: зона не смежная с зоной сотрудника"
                checked={emergency}
                onChange={(e) => setEmergency(e.currentTarget.checked)}
              />
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSending(null)}>
              Отмена
            </Button>
            <Button
              onClick={() => second.mutate()}
              loading={second.isPending}
              disabled={!zone || (needEmergency && (!emergency || !reason.trim()))}
            >
              Направить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
