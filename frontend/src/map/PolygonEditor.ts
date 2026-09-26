/**
 * Редактор контура на карте без сторонних плагинов: рисование по щелчкам, перетаскивание вершин
 * (мышь и палец), вставка точки щелчком по середине ребра, удаление выбранной вершины.
 * Используется для границ зон и контуров объектов, в том числе для правки предложенного
 * автовыделением здания перед сохранением.
 */
import type {
  GeoJSONSource,
  Map as MapLibre,
  MapLayerMouseEvent,
  MapLayerTouchEvent,
  MapMouseEvent,
  MapTouchEvent,
} from 'maplibre-gl'

import type { LonLat, Polygon } from '../api/types'

type Mode = 'idle' | 'draw' | 'edit'
const COLOR = '#f76707'

export class PolygonEditor {
  private map: MapLibre
  private points: LonLat[] = []
  private mode: Mode = 'idle'
  private selected: number | null = null
  private dragging: number | null = null
  private onChange: (p: Polygon | null) => void

  constructor(map: MapLibre, onChange: (p: Polygon | null) => void) {
    this.map = map
    this.onChange = onChange
    const empty = { type: 'FeatureCollection' as const, features: [] }
    map.addSource('ed-poly', { type: 'geojson', data: empty })
    map.addSource('ed-verts', { type: 'geojson', data: empty })
    map.addSource('ed-mids', { type: 'geojson', data: empty })
    map.addLayer({ id: 'ed-fill', type: 'fill', source: 'ed-poly', paint: { 'fill-color': COLOR, 'fill-opacity': 0.2 } })
    map.addLayer({
      id: 'ed-line',
      type: 'line',
      source: 'ed-poly',
      paint: { 'line-color': COLOR, 'line-width': 2.5, 'line-dasharray': [2, 1] },
    })
    map.addLayer({
      id: 'ed-mids',
      type: 'circle',
      source: 'ed-mids',
      paint: { 'circle-radius': 4, 'circle-color': '#ffffff', 'circle-stroke-color': COLOR, 'circle-stroke-width': 1.5, 'circle-opacity': 0.8 },
    })
    map.addLayer({
      id: 'ed-verts',
      type: 'circle',
      source: 'ed-verts',
      paint: {
        'circle-radius': ['case', ['get', 'selected'], 8, 6],
        'circle-color': ['case', ['get', 'selected'], '#e03131', '#ffffff'],
        'circle-stroke-color': COLOR,
        'circle-stroke-width': 2,
      },
    })
    map.on('click', this.click)
    map.on('dblclick', this.finishDraw)
    map.on('mousedown', 'ed-verts', this.startDrag)
    map.on('touchstart', 'ed-verts', this.startDrag)
    map.on('click', 'ed-mids', this.insert)
    map.on('mouseenter', 'ed-verts', this.pointer)
    map.on('mouseleave', 'ed-verts', this.unpointer)
    map.on('mouseenter', 'ed-mids', this.pointer)
    map.on('mouseleave', 'ed-mids', this.unpointer)
  }

  destroy() {
    const map = this.map
    map.off('click', this.click)
    map.off('dblclick', this.finishDraw)
    map.off('mousedown', 'ed-verts', this.startDrag)
    map.off('touchstart', 'ed-verts', this.startDrag)
    map.off('click', 'ed-mids', this.insert)
  }

  /** Кому сообщать об изменении контура (черновик в форме). */
  listen(fn: (p: Polygon | null) => void) {
    this.onChange = fn
  }

  get active() {
    return this.mode !== 'idle'
  }

  /** Начать рисование: каждый щелчок — вершина, двойной щелчок или «Готово» — замкнуть. */
  startDraw() {
    this.points = []
    this.selected = null
    this.mode = 'draw'
    this.map.doubleClickZoom.disable()
    this.map.getCanvas().style.cursor = 'crosshair'
    this.render()
  }

  /** Показать контур для правки (например, предложенный автовыделением). */
  edit(polygon: Polygon | null) {
    const ring = polygon?.coordinates[0] ?? []
    this.points = ring.slice(0, ring.length > 1 ? -1 : undefined).map((p) => [p[0], p[1]] as LonLat)
    this.selected = null
    this.mode = this.points.length >= 3 ? 'edit' : 'idle'
    this.map.doubleClickZoom.enable()
    this.map.getCanvas().style.cursor = ''
    this.render()
  }

  clear() {
    this.points = []
    this.selected = null
    this.mode = 'idle'
    this.map.doubleClickZoom.enable()
    this.map.getCanvas().style.cursor = ''
    this.render()
  }

  finishDraw = (e?: MapMouseEvent) => {
    if (this.mode !== 'draw') return
    e?.preventDefault()
    if (this.points.length >= 3) {
      this.mode = 'edit'
      this.map.getCanvas().style.cursor = ''
      window.setTimeout(() => this.map.doubleClickZoom.enable(), 0)
      this.emit()
    }
    this.render()
  }

  deleteSelected() {
    if (this.selected == null || this.points.length <= 3) return
    this.points.splice(this.selected, 1)
    this.selected = null
    this.render()
    this.emit()
  }

  polygon(): Polygon | null {
    if (this.points.length < 3) return null
    return { type: 'Polygon', coordinates: [[...this.points, this.points[0]]] }
  }

  hasSelection() {
    return this.selected != null
  }

  private emit() {
    this.onChange(this.mode === 'edit' ? this.polygon() : null)
  }

  private pointer = () => {
    if (this.mode === 'edit') this.map.getCanvas().style.cursor = 'move'
  }

  private unpointer = () => {
    if (this.mode === 'edit' && this.dragging == null) this.map.getCanvas().style.cursor = ''
  }

  private click = (e: MapMouseEvent) => {
    if (this.mode === 'draw') {
      this.points.push([e.lngLat.lng, e.lngLat.lat])
      this.render()
      return
    }
    if (this.mode === 'edit') {
      const hit = this.map.queryRenderedFeatures(e.point, { layers: ['ed-verts'] })
      this.selected = hit.length ? Number(hit[0].properties?.i) : null
      this.render()
    }
  }

  private insert = (e: MapLayerMouseEvent) => {
    if (this.mode !== 'edit') return
    const i = Number(e.features?.[0]?.properties?.i)
    this.points.splice(i + 1, 0, [e.lngLat.lng, e.lngLat.lat])
    this.selected = i + 1
    this.render()
    this.emit()
  }

  private startDrag = (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
    if (this.mode !== 'edit') return
    if ('points' in e && e.points.length !== 1) return
    e.preventDefault()
    this.dragging = Number(e.features?.[0]?.properties?.i)
    this.selected = this.dragging
    this.map.dragPan.disable()
    const move = (ev: MapMouseEvent | MapTouchEvent) => {
      if (this.dragging == null) return
      this.points[this.dragging] = [ev.lngLat.lng, ev.lngLat.lat]
      this.render()
    }
    const up = () => {
      this.dragging = null
      this.map.dragPan.enable()
      this.map.off('mousemove', move)
      this.map.off('touchmove', move)
      this.render()
      this.emit()
    }
    this.map.on('mousemove', move)
    this.map.on('touchmove', move)
    this.map.once('mouseup', up)
    this.map.once('touchend', up)
  }

  private render() {
    const pts = this.points
    const closed = this.mode === 'edit' && pts.length >= 3
    const line = closed ? [...pts, pts[0]] : pts
    ;(this.map.getSource('ed-poly') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features:
        line.length >= 2
          ? [
              closed
                ? { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [line] } }
                : { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: line } },
            ]
          : [],
    })
    ;(this.map.getSource('ed-verts') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: pts.map((p, i) => ({
        type: 'Feature',
        properties: { i, selected: i === this.selected },
        geometry: { type: 'Point', coordinates: p },
      })),
    })
    ;(this.map.getSource('ed-mids') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: closed
        ? pts.map((p, i) => {
            const q = pts[(i + 1) % pts.length]
            return {
              type: 'Feature',
              properties: { i },
              geometry: { type: 'Point', coordinates: [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] },
            }
          })
        : [],
    })
  }
}
