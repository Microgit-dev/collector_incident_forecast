/**
 * Картографический движок (MapLibre GL, векторная подложка OpenStreetMap).
 * Обработчик тайлов собирается отдельным модулем и подключается явно — иначе после сборки он ищется
 * рядом с бандлом и не находится. Логотип и ссылка на библиотеку не выводятся; остаётся только
 * обязательная по лицензии данных пометка «© OpenStreetMap».
 *
 * Шрифты подписей (glyph-диапазоны Noto Sans) лежат у нас в public/map/glyphs: латиница, кириллица,
 * типографские знаки и «№». Сервер подложки отдаёт их не всегда — CORS, прокси или закрытый контур, —
 * и тогда MapLibre рисует кириллицу запасным локальным шрифтом по одному символу. Поэтому запросы этих
 * диапазонов перехватываются и идут на свой origin, а редкие диапазоны по-прежнему берутся с сервера.
 */
import * as maplibregl from 'maplibre-gl'
import type { ErrorEvent, StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

import './map.css'

maplibregl.setWorkerUrl(workerUrl)

export { maplibregl }
export type { StyleSpecification }

export const LOCAL_FONTS = new Set(['noto_sans_regular', 'noto_sans_bold'])
const LOCAL_RANGES = new Set(['0-255', '256-511', '1024-1279', '8192-8447', '8448-8703'])
const GLYPH_PATH = /\/([^/]+)\/(\d+-\d+)\.pbf(?:\?.*)?$/

export function localGlyphs(): string {
  return `${window.location.origin}/map/glyphs/{fontstack}/{range}.pbf`
}

/** Адрес glyph-диапазона на своём сервере или null, если такого диапазона у нас нет. */
export function localGlyphUrl(url: string): string | null {
  const m = GLYPH_PATH.exec(url)
  if (!m) return null
  const font = decodeURIComponent(m[1]).split(',')[0].trim()
  if (!LOCAL_FONTS.has(font) || !LOCAL_RANGES.has(m[2])) return null
  return `${window.location.origin}/map/glyphs/${font}/${m[2]}.pbf`
}

/** Без подложки (нет сети или сервер тайлов не настроен): контуры зон и объектов, подписи — своими шрифтами. */
export const BLANK_STYLE = (dark: boolean): StyleSpecification => ({
  version: 8,
  glyphs: localGlyphs(),
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': dark ? '#1f2227' : '#eef0f3' } }],
})

export interface MapHandle {
  map: maplibregl.Map
  /** подложка загрузилась (подписи работают и без неё — шрифты свои) */
  basemap: boolean
}

export function createMap(
  container: HTMLElement,
  styleUrl: string | null,
  dark: boolean,
  onReady: (h: MapHandle) => void,
): maplibregl.Map {
  let done = false
  const map = new maplibregl.Map({
    container,
    style: styleUrl || BLANK_STYLE(dark),
    center: [37.62, 55.75],
    zoom: 11,
    attributionControl: false,
    cooperativeGestures: false,
    dragRotate: false,
    pitchWithRotate: false,
    maxPitch: 0,
    transformRequest: (url, resourceType) => {
      if (resourceType !== 'Glyphs') return undefined
      const local = localGlyphUrl(url)
      return local ? { url: local } : undefined
    },
  })
  map.touchZoomRotate.disableRotation()
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
  const ready = (basemap: boolean) => {
    if (done) return
    done = true
    onReady({ map, basemap })
  }
  map.once('load', () => ready(Boolean(styleUrl)))
  // подложка недоступна — переходим на пустой стиль, чтобы карта всё равно работала
  const fallback = window.setTimeout(() => {
    if (!done) {
      map.setStyle(BLANK_STYLE(dark))
      map.once('styledata', () => ready(false))
    }
  }, 8000)
  map.on('error', (e: ErrorEvent) => {
    if (!done && /style|Failed to fetch|NetworkError/i.test(String(e.error?.message ?? ''))) {
      window.clearTimeout(fallback)
      map.setStyle(BLANK_STYLE(dark))
      map.once('styledata', () => ready(false))
    }
  })
  map.once('remove', () => window.clearTimeout(fallback))
  return map
}
