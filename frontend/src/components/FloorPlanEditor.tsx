/**
 * Привязка плана этажа к местности по контрольным точкам.
 *
 * Слева — план этажа, справа — местность (спутник, контур здания, живое наложение плана) или план
 * контрольного этажа. Точка — пара щелчков: место на плане и то же место справа (порядок любой).
 * Маркеры перетаскиваются. Контрольный этаж подгоняется «по контуру здания» (прямоугольник вокруг
 * контура, выделенного по снимку, ↔ рамка чертежа), остальные — «по контрольному этажу»: щелчок по его
 * плану пересчитывается в координаты его привязкой, и планы ложатся друг на друга.
 */
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Table,
  Text,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconBuilding, IconEraser, IconRotateClockwise, IconStack2, IconTrash } from '@tabler/icons-react'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api/client'
import type { ControlPoint, Floor, LonLat, MapConfig, Polygon } from '../api/types'
import { BLANK_STYLE, createMap, maplibregl } from '../map/engine'
import { bounds } from '../map/geometry'
import {
  type Affine,
  type PlanBox,
  bestTurn,
  contourPoints,
  drawingBox,
  fitAffine,
  minAreaRect,
  planCorners,
} from '../map/georef'
import { setSatellite, showPlan, usePlanUrl } from '../map/plans'

type Pending = { px: number; py: number } | { lon: number; lat: number } | null
const COLORS = { point: '#1c7ed6', selected: '#e03131', pending: '#f08c00', off: '#adb5bd' }
const markerColor = (i: number, p: ControlPoint, selected: number | null) =>
  !p.on ? COLORS.off : i === selected ? COLORS.selected : COLORS.point

// ---------- маркеры ----------

interface MarkerItem {
  key: string
  at: LonLat
  label: string
  color: string
}

function markerElement(label: string, color: string): HTMLElement {
  const el = document.createElement('div')
  el.textContent = label
  el.style.cssText =
    `width:22px;height:22px;border-radius:50%;background:${color};color:#fff;font:600 11px/22px sans-serif;` +
    'text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);cursor:grab'
  return el
}

/** Маркеры точек на карте: перетаскиваются, по окончании — onDrag(ключ, новая точка). */
function useMarkers(map: maplibregl.Map | null, items: MarkerItem[], onDrag: (key: string, at: LonLat) => void) {
  const drag = useRef(onDrag)
  useEffect(() => {
    drag.current = onDrag
  })
  useEffect(() => {
    if (!map) return
    const markers = items.map((item) => {
      const marker = new maplibregl.Marker({ element: markerElement(item.label, item.color), draggable: item.key !== 'pending' })
        .setLngLat(item.at)
        .addTo(map)
      marker.on('dragend', () => {
        const p = marker.getLngLat()
        drag.current(item.key, [p.lng, p.lat])
      })
      return marker
    })
    return () => markers.forEach((m) => m.remove())
  }, [map, items])
}

// ---------- план: картинка в «пиксельных» координатах ----------

// План показывается той же картой MapLibre (зум, перенос, маркеры), но в условных координатах у экватора:
// длинная сторона плана — SPAN градусов, искажение проекции на таком участке пренебрежимо мало
const SPAN = 0.02
const toFake = (px: number, py: number, scale: number): LonLat => [(px / scale) * SPAN, (-py / scale) * SPAN]
const fromFake = ([lon, lat]: LonLat, scale: number): [number, number] => [(lon / SPAN) * scale, (-lat / SPAN) * scale]

function PlanPane({
  url,
  width,
  height,
  points,
  pending,
  onPick,
  onDrag,
  title,
}: {
  url: string | null
  width: number
  height: number
  points: { key: string; px: number; py: number; label: string; color: string }[]
  pending: { px: number; py: number } | null
  onPick: (px: number, py: number) => void
  onDrag: (key: string, px: number, py: number) => void
  title: string
}) {
  const dark = useComputedColorScheme('light') === 'dark'
  const box = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const scale = Math.max(width, height, 1)
  const pick = useRef(onPick)
  useEffect(() => {
    pick.current = onPick
  })

  useEffect(() => {
    if (!box.current || !url) return
    const m = new maplibregl.Map({
      container: box.current,
      style: BLANK_STYLE(dark),
      center: [0, 0],
      zoom: 1,
      attributionControl: false,
      dragRotate: false,
      renderWorldCopies: false,
    })
    m.touchZoomRotate.disableRotation()
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    const corners = [toFake(0, 0, scale), toFake(width, 0, scale), toFake(width, height, scale), toFake(0, height, scale)]
    m.once('load', () => {
      m.addSource('plan', { type: 'image', url, coordinates: corners as [LonLat, LonLat, LonLat, LonLat] })
      m.addLayer({ id: 'plan', type: 'raster', source: 'plan', paint: { 'raster-fade-duration': 0 } })
      m.fitBounds([corners[3], corners[1]], { padding: 20, duration: 0 })
      m.on('click', (e) => {
        const [px, py] = fromFake([e.lngLat.lng, e.lngLat.lat], scale)
        if (px >= 0 && py >= 0 && px <= width && py <= height) pick.current(px, py)
      })
      setMap(m)
    })
    const resize = new ResizeObserver(() => m.resize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      setMap(null)
      m.remove()
    }
  }, [url, width, height, scale, dark])

  const items = useMemo<MarkerItem[]>(
    () => [
      ...points.map((p) => ({ key: p.key, at: toFake(p.px, p.py, scale), label: p.label, color: p.color })),
      ...(pending ? [{ key: 'pending', at: toFake(pending.px, pending.py, scale), label: '+', color: COLORS.pending }] : []),
    ],
    [points, pending, scale],
  )
  useMarkers(map, items, (key, at) => {
    const [px, py] = fromFake(at, scale)
    onDrag(key, Math.min(Math.max(px, 0), width), Math.min(Math.max(py, 0), height))
  })

  return (
    <Paper withBorder radius="md" pos="relative" style={{ flex: 1, minHeight: 260, overflow: 'hidden' }}>
      <Badge pos="absolute" top={8} left={8} style={{ zIndex: 2 }} variant="filled" color="dark">
        {title}
      </Badge>
      {url ? (
        <div ref={box} style={{ position: 'absolute', inset: 0 }} />
      ) : (
        <Text size="sm" c="dimmed" p="md" pt={44}>
          План не загружен
        </Text>
      )}
    </Paper>
  )
}

// ---------- местность: спутник, контур, наложение плана ----------

const OWN_LAYERS = ['object-fill', 'object-line']

function GeoPane({
  config,
  geometry,
  points,
  pending,
  preview,
  satellite,
  onPick,
  onDrag,
}: {
  config: MapConfig
  geometry: Polygon | null
  points: MarkerItem[]
  pending: LonLat | null
  preview: { url: string | null; corners: LonLat[] | null; opacity: number }
  satellite: boolean
  onPick: (at: LonLat) => void
  onDrag: (key: string, at: LonLat) => void
}) {
  const dark = useComputedColorScheme('light') === 'dark'
  const box = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const pick = useRef(onPick)
  const shape = useRef(geometry)
  useEffect(() => {
    pick.current = onPick
    shape.current = geometry
  })

  useEffect(() => {
    if (!box.current) return
    const m = createMap(box.current, (dark ? config.dark : config.light) || null, dark, ({ map: mm }) => {
      mm.addSource('object', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      mm.addLayer({ id: 'object-fill', type: 'fill', source: 'object', paint: { 'fill-color': '#f76707', 'fill-opacity': 0.08 } })
      mm.addLayer({ id: 'object-line', type: 'line', source: 'object', paint: { 'line-color': '#f76707', 'line-width': 2 } })
      mm.on('click', (e) => {
        // щелчок рядом с вершиной контура — точка ровно в вершину (углы здания по снимку)
        const ring = shape.current?.coordinates[0] ?? []
        let best: LonLat = [e.lngLat.lng, e.lngLat.lat]
        let dist = 12
        for (const v of ring) {
          const p = mm.project(v as LonLat)
          const d = Math.hypot(p.x - e.point.x, p.y - e.point.y)
          if (d < dist) {
            dist = d
            best = [v[0], v[1]]
          }
        }
        pick.current(best)
      })
      setMap(mm)
    })
    const resize = new ResizeObserver(() => m.resize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      setMap(null)
      m.remove()
    }
  }, [dark, config])

  useEffect(() => {
    if (!map) return
    ;(map.getSource('object') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: geometry ? [{ type: 'Feature', properties: {}, geometry }] : [],
    })
    const b = bounds([geometry])
    if (b) map.fitBounds(b, { padding: 60, maxZoom: 19, duration: 0 })
  }, [map, geometry])

  useEffect(() => {
    if (map) setSatellite(map, config, satellite, ['plan-preview', ...OWN_LAYERS])
  }, [map, config, satellite])

  useEffect(() => {
    if (map) showPlan(map, 'preview', preview.url, preview.corners, preview.opacity, OWN_LAYERS)
  }, [map, preview.url, preview.corners, preview.opacity])

  const items = useMemo<MarkerItem[]>(
    () => [...points, ...(pending ? [{ key: 'pending', at: pending, label: '+', color: COLORS.pending }] : [])],
    [points, pending],
  )
  useMarkers(map, items, onDrag)

  return <div ref={box} style={{ position: 'absolute', inset: 0 }} />
}

// ---------- редактор ----------

export function FloorPlanEditor({
  floor,
  floors,
  geometry,
  config,
  onClose,
  onSaved,
}: {
  floor: Floor
  floors: Floor[]
  geometry: Polygon | null
  config: MapConfig
  onClose: () => void
  onSaved: (f: Floor) => void
}) {
  const phone = useMediaQuery('(max-width: 48em)')
  const width = floor.width ?? 0
  const height = floor.height ?? 0
  const base = floors.find((f) => f.is_base && f.id !== floor.id && f.corners && f.width && f.height)
  const baseFit = useMemo(
    () => (base ? fitAffine(base.points, base.width!, base.height!) : null),
    [base],
  )
  const [points, setPoints] = useState<ControlPoint[]>(floor.points ?? [])
  const [pending, setPending] = useState<Pending>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [target, setTarget] = useState<'map' | 'base'>(base && baseFit ? 'base' : 'map')
  const [satellite, setSatelliteOn] = useState(Boolean(config.satellite))
  const [opacity, setOpacity] = useState(floor.opacity ?? 0.85)
  // последняя автоподгонка по рамке: поворот перебирается кнопкой
  const [auto, setAuto] = useState<{ kind: 'contour' | 'base'; box: PlanBox; rect: LonLat[]; turn: number } | null>(null)
  const planUrl = usePlanUrl(floor.plan)
  const baseUrl = usePlanUrl(base?.plan)
  const fit: Affine | null = useMemo(() => fitAffine(points, width, height), [points, width, height])
  const corners = useMemo(() => (fit ? planCorners(fit, width, height) : null), [fit, width, height])

  const addPair = (px: number, py: number, lon: number, lat: number) => {
    setPoints((ps) => [...ps, { px: Math.round(px * 10) / 10, py: Math.round(py * 10) / 10, lon, lat, on: true }])
    setPending(null)
    setAuto(null)
  }
  const pickPlan = (px: number, py: number) => {
    if (pending && 'lon' in pending) addPair(px, py, pending.lon, pending.lat)
    else setPending({ px, py })
  }
  const pickGeo = ([lon, lat]: LonLat) => {
    if (pending && 'px' in pending) addPair(pending.px, pending.py, lon, lat)
    else setPending({ lon, lat })
  }
  const pickBase = (px: number, py: number) => {
    if (!baseFit) return
    const [lon, lat] = baseFit.toLonLat(px, py)
    pickGeo([lon, lat])
  }
  const movePoint = (key: string, patch: Partial<ControlPoint>) => {
    if (key === 'pending') return
    const i = Number(key)
    setPoints((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)))
    setAuto(null)
  }

  const runAuto = async (kind: 'contour' | 'base') => {
    if (!planUrl) return
    try {
      const planBox = await drawingBox(planUrl, width, height)
      let rect: LonLat[] | null = null
      if (kind === 'contour' && geometry) rect = minAreaRect(geometry)
      if (kind === 'base' && base && baseFit && baseUrl) {
        const [x0, y0, x1, y1] = await drawingBox(baseUrl, base.width!, base.height!)
        rect = [baseFit.toLonLat(x0, y0), baseFit.toLonLat(x1, y0), baseFit.toLonLat(x1, y1), baseFit.toLonLat(x0, y1)]
      }
      if (!rect) return
      const turn = kind === 'contour' ? bestTurn(planBox, rect) : 0
      setPoints(contourPoints(planBox, rect, turn))
      setAuto({ kind, box: planBox, rect, turn })
      setPending(null)
    } catch {
      notifications.show({ color: 'red', message: 'Не удалось прочитать план' })
    }
  }
  const rotate = () => {
    if (!auto) return
    const turn = (auto.turn + 1) % 4
    setPoints(contourPoints(auto.box, auto.rect, turn))
    setAuto({ ...auto, turn })
  }

  const save = useMutation({
    mutationFn: () => api<Floor>(`/topology/floors/${floor.id}/`, { method: 'PATCH', body: { points, opacity } }),
    onSuccess: (f) => {
      notifications.show({
        color: 'teal',
        message: f.corners ? `План привязан, невязка ${f.rmse_m?.toFixed(1)} м` : 'Точки сохранены — для привязки нужно не меньше трёх',
      })
      onSaved(f)
    },
    onError: (e) => notifications.show({ color: 'red', message: e instanceof Error ? e.message : 'Ошибка' }),
  })

  // маркеры пересоздаются при смене этих массивов — поэтому они мемоизированы
  const planPoints = useMemo(
    () => points.map((p, i) => ({ key: String(i), px: p.px, py: p.py, label: String(i + 1), color: markerColor(i, p, selected) })),
    [points, selected],
  )
  const geoPoints = useMemo(
    () => points.map((p, i) => ({ key: String(i), at: [p.lon, p.lat] as LonLat, label: String(i + 1), color: markerColor(i, p, selected) })),
    [points, selected],
  )
  const basePoints = useMemo(
    () =>
      baseFit
        ? points.map((p, i) => {
            const [px, py] = baseFit.toPixel(p.lon, p.lat)
            return { key: String(i), px, py, label: String(i + 1), color: markerColor(i, p, selected) }
          })
        : [],
    [points, selected, baseFit],
  )
  const basePending = useMemo(() => {
    if (!baseFit || !pending || !('lon' in pending)) return null
    const [px, py] = baseFit.toPixel(pending.lon, pending.lat)
    return { px, py }
  }, [baseFit, pending])
  const geoPending = useMemo<LonLat | null>(() => (pending && 'lon' in pending ? [pending.lon, pending.lat] : null), [pending])
  const planPending = useMemo(() => (pending && 'px' in pending ? pending : null), [pending])
  const preview = useMemo(() => ({ url: planUrl, corners, opacity }), [planUrl, corners, opacity])
  const enabled = points.filter((p) => p.on).length

  return (
    <Modal opened onClose={onClose} fullScreen title={`Привязка плана: ${floor.title}${floor.is_base ? ' (контрольный этаж)' : ''}`}>
      <Stack gap="sm" style={{ height: 'calc(100dvh - 80px)' }}>
        <Group gap="xs" wrap="wrap">
          {geometry && (
            <Tooltip label="Рамка чертежа на плане ↔ прямоугольник вокруг контура здания; дальше уточните точками">
              <Button size="xs" variant="light" leftSection={<IconBuilding size={14} />} onClick={() => void runAuto('contour')} disabled={!planUrl}>
                По контуру здания
              </Button>
            </Tooltip>
          )}
          {base && baseFit && (
            <Tooltip label={`Рамка чертежа ↔ рамка плана «${base.title}»: подходит, если листы начерчены в одном масштабе`}>
              <Button size="xs" variant="light" leftSection={<IconStack2 size={14} />} onClick={() => void runAuto('base')} disabled={!planUrl || !baseUrl}>
                По контрольному этажу
              </Button>
            </Tooltip>
          )}
          {auto && (
            <Button size="xs" variant="default" leftSection={<IconRotateClockwise size={14} />} onClick={rotate}>
              Повернуть на 90°
            </Button>
          )}
          <Button size="xs" variant="subtle" color="red" leftSection={<IconEraser size={14} />} onClick={() => { setPoints([]); setAuto(null); setPending(null) }} disabled={!points.length}>
            Очистить
          </Button>
          <Box style={{ flex: 1 }} />
          {base && baseFit && (
            <SegmentedControl
              size="xs"
              value={target}
              onChange={(v) => setTarget(v as 'map' | 'base')}
              data={[
                { value: 'base', label: `План: ${base.title}` },
                { value: 'map', label: 'Местность' },
              ]}
            />
          )}
          {target === 'map' && config.satellite && (
            <Checkbox size="xs" label="Спутник" checked={satellite} onChange={(e) => setSatelliteOn(e.currentTarget.checked)} />
          )}
          <Group gap={6} w={180}>
            <Text size="xs">Прозрачность</Text>
            <Slider size="xs" style={{ flex: 1 }} min={0.2} max={1} step={0.05} value={opacity} onChange={setOpacity} label={null} />
          </Group>
        </Group>

        <Text size="xs" c="dimmed">
          Точка — два щелчка: место на плане этажа и то же место {target === 'base' ? 'на плане контрольного этажа' : 'на снимке'} (порядок
          любой; рядом с вершиной контура щелчок попадает ровно в неё). Маркеры можно перетаскивать. Нужно не меньше трёх
          точек по углам здания, лучше 4–6.
          {pending && <b> Выбрано место {'px' in pending ? 'на плане' : 'справа'} — отметьте парное.</b>}
        </Text>

        <Box style={{ display: 'flex', flexDirection: phone ? 'column' : 'row', gap: 8, flex: 1, minHeight: 0 }}>
          <PlanPane
            title={`План: ${floor.title}`}
            url={planUrl}
            width={width}
            height={height}
            points={planPoints}
            pending={planPending}
            onPick={pickPlan}
            onDrag={(key, px, py) => movePoint(key, { px, py })}
          />
          {target === 'base' && base && baseFit ? (
            <PlanPane
              title={`Контрольный: ${base.title}`}
              url={baseUrl}
              width={base.width!}
              height={base.height!}
              points={basePoints}
              pending={basePending}
              onPick={pickBase}
              onDrag={(key, px, py) => {
                const [lon, lat] = baseFit.toLonLat(px, py)
                movePoint(key, { lon, lat })
              }}
            />
          ) : (
            <Paper withBorder radius="md" pos="relative" style={{ flex: 1, minHeight: 260, overflow: 'hidden' }}>
              <GeoPane
                config={config}
                geometry={geometry}
                points={geoPoints}
                pending={geoPending}
                preview={preview}
                satellite={satellite}
                onPick={pickGeo}
                onDrag={(key, [lon, lat]) => movePoint(key, { lon, lat })}
              />
            </Paper>
          )}
        </Box>

        <Group align="flex-start" gap="md" wrap={phone ? 'wrap' : 'nowrap'}>
          <ScrollArea h={150} style={{ flex: 1 }}>
            <Table fz="xs" verticalSpacing={2} highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>№</Table.Th>
                  <Table.Th>Пиксель плана</Table.Th>
                  <Table.Th>Долгота, широта</Table.Th>
                  <Table.Th>Невязка</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {points.map((p, i) => (
                  <Table.Tr key={i} onClick={() => setSelected(i === selected ? null : i)} style={{ cursor: 'pointer' }} bg={i === selected ? 'var(--mantine-color-red-light)' : undefined}>
                    <Table.Td>{i + 1}</Table.Td>
                    <Table.Td>
                      {p.px.toFixed(0)}, {p.py.toFixed(0)}
                    </Table.Td>
                    <Table.Td>
                      {p.lon.toFixed(6)}, {p.lat.toFixed(6)}
                    </Table.Td>
                    <Table.Td c={(fit?.residuals[i] ?? 0) > 2 ? 'orange' : undefined}>
                      {fit?.residuals[i] != null ? `${fit.residuals[i]!.toFixed(1)} м` : '—'}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                        <Checkbox size="xs" checked={p.on} onChange={(e) => movePoint(String(i), { on: e.currentTarget.checked })} aria-label="Учитывать точку" />
                        <ActionIcon size="xs" variant="subtle" color="red" onClick={() => { setPoints((ps) => ps.filter((_, j) => j !== i)); setSelected(null); setAuto(null) }} aria-label="Удалить точку">
                          <IconTrash size={12} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {!points.length && (
              <Text size="xs" c="dimmed" p="xs">
                Точек нет. Начните с «{floor.is_base || !base ? 'По контуру здания' : 'По контрольному этажу'}» или поставьте пары вручную.
              </Text>
            )}
          </ScrollArea>
          <Stack gap={6} w={phone ? '100%' : 260}>
            {fit ? (
              <Alert p="xs" color={fit.rmse > 3 ? 'orange' : 'teal'}>
                <Text size="xs">
                  Включено точек: {enabled}. Средняя невязка {fit.rmse.toFixed(1)} м
                  {fit.rmse > 3 ? ' — проверьте точки с большой невязкой' : ''}.
                </Text>
              </Alert>
            ) : (
              <Alert p="xs" color="gray">
                <Text size="xs">Нужно не меньше трёх включённых точек не на одной линии.</Text>
              </Alert>
            )}
            <Group justify="flex-end" gap="xs">
              <Button size="xs" variant="default" onClick={onClose}>
                Закрыть
              </Button>
              <Button size="xs" onClick={() => save.mutate()} loading={save.isPending}>
                Сохранить привязку
              </Button>
            </Group>
          </Stack>
        </Group>
      </Stack>
    </Modal>
  )
}
