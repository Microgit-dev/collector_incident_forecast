import { useComputedColorScheme } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'

import type { MonitoringMap as MapData, MonitoringMode, MonitoringObjectDetail } from '../api/types'
import { createMap, maplibregl, type MapHandle } from './engine'
import { APPROVAL, BAD, LEVEL_COLOR, ORDER, SENSOR_COLOR, objectColor } from './status'

const EMPTY = { type: 'FeatureCollection' as const, features: [] }
// минимальные типы GeoJSON: источники карты принимают обычные объекты
interface Feature {
  type: 'Feature'
  id?: number
  geometry: { type: string; coordinates: unknown }
  properties: Record<string, unknown>
}
interface FC {
  type: 'FeatureCollection'
  features: Feature[]
}

interface Props {
  data: MapData
  mode: MonitoringMode
  selected: number | null
  detail?: MonitoringObjectDetail
  onSelect: (id: number | null) => void
  /** куда перелететь: объект из списка */
  focus?: { id: number; at: number } | null
}

function collections(data: MapData, mode: MonitoringMode) {
  const zones: FC = {
    type: 'FeatureCollection',
    features: data.zones
      .filter((z) => z.geometry)
      .map((z) => ({
        type: 'Feature',
        id: z.id,
        geometry: z.geometry!,
        properties: {
          id: z.id,
          name: z.name,
          color: z.mine || z.seconded ? z.color : '#868e96',
          rank: z.home || (z.mine && data.global) ? 3 : z.mine || z.seconded ? 2 : z.adjacent ? 1 : 0,
        },
      })),
  }
  const shapes: FC = {
    type: 'FeatureCollection',
    features: data.objects
      .filter((o) => o.geometry)
      .map((o) => ({
        type: 'Feature',
        id: o.id,
        geometry: o.geometry!,
        properties: { id: o.id, name: o.name, mine: o.mine, color: objectColor(o, mode), busy: Boolean(o.busy) },
      })),
  }
  const points: FC = {
    type: 'FeatureCollection',
    features: data.objects
      .filter((o) => o.center)
      .map((o) => ({
        type: 'Feature',
        id: o.id,
        geometry: { type: 'Point', coordinates: o.center! },
        properties: { id: o.id, name: o.name, mine: o.mine, color: objectColor(o, mode), busy: Boolean(o.busy) },
      })),
  }
  return { zones, shapes, points }
}

function addLayers(h: MapHandle) {
  const { map } = h
  map.addSource('zones', { type: 'geojson', data: EMPTY })
  map.addSource('objects', { type: 'geojson', data: EMPTY })
  map.addSource('points', { type: 'geojson', data: EMPTY })
  map.addSource('sensors', { type: 'geojson', data: EMPTY })
  // зоны: своя — заливка и толстый контур, смежные — пунктир, остальные — тонкий серый пунктир
  map.addLayer({
    id: 'zones-fill',
    type: 'fill',
    source: 'zones',
    paint: {
      'fill-color': ['get', 'color'],
      'fill-opacity': ['match', ['get', 'rank'], 3, 0.1, 2, 0.07, 1, 0.03, 0.015],
    },
  })
  map.addLayer({
    id: 'zones-line',
    type: 'line',
    source: 'zones',
    paint: {
      'line-color': ['get', 'color'],
      'line-width': ['match', ['get', 'rank'], 3, 3, 2, 2.5, 1, 1.5, 1],
      'line-dasharray': ['match', ['get', 'rank'], 3, ['literal', [1, 0]], 2, ['literal', [1, 0]], ['literal', [3, 2]]],
      'line-opacity': ['match', ['get', 'rank'], 0, 0.5, 1],
    },
  })
  // объекты: здание в цвете режима; чужие — серые и бледные
  map.addLayer({
    id: 'objects-fill',
    type: 'fill',
    source: 'objects',
    paint: {
      'fill-color': ['get', 'color'],
      'fill-opacity': ['case', ['get', 'mine'], 0.6, 0.22],
    },
  })
  map.addLayer({
    id: 'objects-line',
    type: 'line',
    source: 'objects',
    paint: {
      'line-color': ['case', ['get', 'mine'], ['get', 'color'], '#868e96'],
      'line-width': ['case', ['get', 'mine'], 1.5, 0.8],
    },
  })
  map.addLayer({
    id: 'objects-selected',
    type: 'line',
    source: 'objects',
    filter: ['==', ['get', 'id'], -1],
    paint: { 'line-color': '#1c7ed6', 'line-width': 4 },
  })
  // на мелком масштабе здания не видны — объект точкой, пока не приблизились
  map.addLayer({
    id: 'points',
    type: 'circle',
    source: 'points',
    maxzoom: 15.5,
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['case', ['get', 'mine'], 4, 2.5], 15, ['case', ['get', 'mine'], 8, 4]],
      'circle-stroke-color': ['case', ['get', 'busy'], BAD, '#ffffff'],
      'circle-stroke-width': ['case', ['get', 'busy'], 2, ['get', 'mine'], 1.5, 0.5],
      'circle-opacity': ['case', ['get', 'mine'], 1, 0.6],
    },
  })
  // датчики выбранного объекта: не в норме — всегда, в норме — только вблизи (их сотни)
  map.addLayer({
    id: 'sensors-ok',
    type: 'circle',
    source: 'sensors',
    minzoom: 18,
    filter: ['!', ['get', 'bad']],
    paint: { 'circle-color': ['get', 'color'], 'circle-radius': 3, 'circle-opacity': 0.6 },
  })
  map.addLayer({
    id: 'sensors',
    type: 'circle',
    source: 'sensors',
    filter: ['get', 'bad'],
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 15, 3.5, 19, 7],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1,
    },
  })
  if (h.basemap) {
    // подписи — только своих объектов и только вблизи, чтобы карта не была перегружена
    map.addLayer({
      id: 'labels',
      type: 'symbol',
      source: 'points',
      minzoom: 14.5,
      filter: ['get', 'mine'],
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['noto_sans_regular'],
        'text-size': 12,
        'text-offset': [0, 1.3],
        'text-anchor': 'top',
        'text-max-width': 10,
      },
      paint: { 'text-color': '#343a40', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
    })
    map.addLayer({
      id: 'zone-labels',
      type: 'symbol',
      source: 'zones',
      maxzoom: 14.5,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['noto_sans_bold'],
        'text-size': 13,
      },
      paint: { 'text-color': ['get', 'color'], 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })
  }
}

function badge(text: string, color: string, onClick: () => void): HTMLElement {
  const el = document.createElement('div')
  el.className = 'map-badge'
  el.style.background = color
  el.textContent = text
  el.addEventListener('click', (e) => {
    e.stopPropagation()
    onClick()
  })
  return el
}

function diamond(text: string, color: string, onClick: () => void): HTMLElement {
  const el = document.createElement('div')
  el.className = 'map-order'
  el.style.background = color
  const span = document.createElement('span')
  span.textContent = text
  el.appendChild(span)
  el.addEventListener('click', (e) => {
    e.stopPropagation()
    onClick()
  })
  return el
}

/** Интерактивная карта мониторинга: зоны, объекты, маркеры карточек и заявок, датчики выбранного объекта. */
export function MonitoringMap({ data, mode, selected, detail, onSelect, focus }: Props) {
  const dark = useComputedColorScheme('light') === 'dark'
  const box = useRef<HTMLDivElement>(null)
  const [handle, setHandle] = useState<MapHandle | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const fitted = useRef(false)
  const select = useRef(onSelect)
  select.current = onSelect

  // карта пересоздаётся при смене темы: у светлой и тёмной подложки разные стили
  useEffect(() => {
    if (!box.current) return
    fitted.current = false
    const map = createMap(box.current, (dark ? data.map.dark : data.map.light) || null, dark, (h) => {
      addLayers(h)
      const pick = (e: maplibregl.MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id
        if (id != null) select.current(Number(id))
      }
      for (const layer of ['objects-fill', 'points']) {
        h.map.on('click', layer, pick)
        h.map.on('mouseenter', layer, () => (h.map.getCanvas().style.cursor = 'pointer'))
        h.map.on('mouseleave', layer, () => (h.map.getCanvas().style.cursor = ''))
      }
      setHandle(h)
    })
    const resize = new ResizeObserver(() => map.resize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      markers.current.forEach((m) => m.remove())
      markers.current = []
      setHandle(null)
      map.remove()
    }
    // стиль подложки меняется только с темой
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark])

  // данные и режим → источники и маркеры
  useEffect(() => {
    if (!handle) return
    const { map } = handle
    const { zones, shapes, points } = collections(data, mode)
    ;(map.getSource('zones') as maplibregl.GeoJSONSource).setData(zones)
    ;(map.getSource('objects') as maplibregl.GeoJSONSource).setData(shapes)
    ;(map.getSource('points') as maplibregl.GeoJSONSource).setData(points)

    markers.current.forEach((m) => m.remove())
    markers.current = []
    const center = new Map(data.objects.map((o) => [o.id, o.center]))
    if (mode === 'situation') {
      for (const m of data.incidents) {
        const c = center.get(m.object)
        if (!c || !m.count) continue
        const el = badge(String(m.count), m.level ? LEVEL_COLOR[m.level] : BAD, () => select.current(m.object))
        el.title = `Открытых карточек: ${m.count}`
        markers.current.push(new maplibregl.Marker({ element: el, offset: [14, -14] }).setLngLat(c).addTo(map))
      }
    }
    if (mode === 'orders' || mode === 'situation') {
      for (const m of data.orders) {
        const c = center.get(m.object)
        if (!c || !m.count) continue
        const color = m.overdue ? BAD : m.approvals ? APPROVAL : ORDER
        const el = diamond(String(m.count), color, () => select.current(m.object))
        el.title = `Заявок: ${m.count}` + (m.approvals ? `, на утверждении ${m.approvals}` : '') + (m.overdue ? `, просрочено ${m.overdue}` : '')
        markers.current.push(new maplibregl.Marker({ element: el, offset: [-14, -14] }).setLngLat(c).addTo(map))
      }
    }

    if (!fitted.current && data.bbox) {
      fitted.current = true
      const [w, s, e, n] = data.bbox
      map.fitBounds([[w, s], [e, n]], { padding: 48, maxZoom: 16, duration: 0 })
    }
  }, [handle, data, mode])

  // выбранный объект: обводка и датчики на контуре
  useEffect(() => {
    if (!handle) return
    const { map } = handle
    map.setFilter('objects-selected', ['==', ['get', 'id'], selected ?? -1])
    const sensors: FC = {
      type: 'FeatureCollection',
      features: (detail?.id === selected ? (detail.sensors ?? []) : [])
        .filter((s) => s.position)
        .map((s) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: s.position! },
          properties: { id: s.id, color: SENSOR_COLOR[s.state] ?? '#adb5bd', bad: s.state !== 'normal' || s.silent },
        })),
    }
    ;(map.getSource('sensors') as maplibregl.GeoJSONSource).setData(sensors)
  }, [handle, selected, detail])

  // перелёт к объекту из списка
  useEffect(() => {
    if (!handle || !focus) return
    const o = data.objects.find((x) => x.id === focus.id)
    if (o?.center) handle.map.flyTo({ center: o.center, zoom: Math.max(handle.map.getZoom(), 16.5), duration: 700 })
  }, [handle, focus, data])

  // щелчок мимо объектов снимает выбор
  useEffect(() => {
    if (!handle) return
    const off = (e: maplibregl.MapMouseEvent) => {
      const hit = handle.map.queryRenderedFeatures(e.point, { layers: ['objects-fill', 'points'] })
      if (!hit.length) select.current(null)
    }
    handle.map.on('click', off)
    return () => {
      handle.map.off('click', off)
    }
  }, [handle])

  return <div ref={box} data-tour="monitoring-map" style={{ position: 'absolute', inset: 0 }} />
}
