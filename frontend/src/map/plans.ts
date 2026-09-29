/**
 * Спутниковая подложка и планы этажей на картах MapLibre.
 *
 * Спутник — растровые XYZ-тайлы (Esri World Imagery по умолчанию, адрес с бэкенда): слой кладётся
 * поверх векторной подложки, но под своими слоями (зоны, объекты, датчики), и включается переключателем.
 * План этажа — картинка, растянутая по четырём углам на местности (ImageSource). Файл плана отдаётся
 * API с авторизацией, поэтому картинка скачивается один раз и передаётся карте как blob-URL.
 */
import { useEffect, useState } from 'react'

import { apiBlob } from '../api/client'
import type { LonLat, MapConfig } from '../api/types'
import type { maplibregl } from './engine'

type MapLibre = maplibregl.Map

const SATELLITE = 'satellite'
const cache = new Map<string, Promise<string>>()

/** blob-URL плана по адресу API (адрес содержит отметку версии — новая версия скачивается заново). */
export function planUrl(path: string): Promise<string> {
  let url = cache.get(path)
  if (!url) {
    url = apiBlob(path).then((blob) => URL.createObjectURL(blob))
    url.catch(() => cache.delete(path))
    cache.set(path, url)
  }
  return url
}

export function usePlanUrl(path: string | null | undefined): string | null {
  const [url, setUrl] = useState<{ path: string; url: string } | null>(null)
  useEffect(() => {
    if (!path) return
    let alive = true
    planUrl(path)
      .then((u) => alive && setUrl({ path, url: u }))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [path])
  return path && url?.path === path ? url.url : null
}

/** Первый собственный слой карты: спутник и планы ложатся под него. */
function firstOwnLayer(map: MapLibre, candidates: string[]): string | undefined {
  return candidates.find((id) => map.getLayer(id))
}

export function setSatellite(map: MapLibre, config: MapConfig, on: boolean, beforeIds: string[]): void {
  if (!config.satellite) return
  if (!map.getSource(SATELLITE)) {
    if (!on) return
    map.addSource(SATELLITE, {
      type: 'raster',
      tiles: [config.satellite],
      tileSize: 256,
      maxzoom: 19,
      attribution: config.satellite_attribution ?? '',
    })
    map.addLayer({ id: SATELLITE, type: 'raster', source: SATELLITE }, firstOwnLayer(map, beforeIds))
    return
  }
  map.setLayoutProperty(SATELLITE, 'visibility', on ? 'visible' : 'none')
}

/**
 * План этажа на карте: key — свой слой на каждый показанный план. url или corners пусты — слой убирается.
 */
export function showPlan(
  map: MapLibre,
  key: string,
  url: string | null,
  corners: LonLat[] | null,
  opacity: number,
  beforeIds: string[] = [],
): void {
  const id = `plan-${key}`
  if (!url || !corners || corners.length !== 4) {
    if (map.getLayer(id)) map.removeLayer(id)
    if (map.getSource(id)) map.removeSource(id)
    shownUrls(map).delete(key)
    return
  }
  const coordinates = corners.map((c) => [c[0], c[1]]) as [[number, number], [number, number], [number, number], [number, number]]
  const urls = shownUrls(map)
  const source = map.getSource(id) as maplibregl.ImageSource | undefined
  if (source && map.getLayer(id)) {
    if (urls.get(key) !== url) source.updateImage({ url, coordinates })
    else source.setCoordinates(coordinates)
    urls.set(key, url)
    map.setPaintProperty(id, 'raster-opacity', opacity)
    return
  }
  map.addSource(id, { type: 'image', url, coordinates })
  map.addLayer(
    { id, type: 'raster', source: id, paint: { 'raster-opacity': opacity, 'raster-fade-duration': 0 } },
    firstOwnLayer(map, beforeIds),
  )
  urls.set(key, url)
}

// какой файл показан в слое плана: при смене файла картинку надо заменить, а не только сдвинуть углы
const shown = new WeakMap<MapLibre, Map<string, string>>()
function shownUrls(map: MapLibre): Map<string, string> {
  let urls = shown.get(map)
  if (!urls) {
    urls = new Map()
    shown.set(map, urls)
  }
  return urls
}

/** Убрать все планы, кроме перечисленных ключей. */
export function hidePlans(map: MapLibre, keep: string[] = []): void {
  for (const layer of map.getStyle()?.layers ?? []) {
    if (!layer.id.startsWith('plan-') || keep.includes(layer.id.slice(5))) continue
    map.removeLayer(layer.id)
    if (map.getSource(layer.id)) map.removeSource(layer.id)
    shownUrls(map).delete(layer.id.slice(5))
  }
}
