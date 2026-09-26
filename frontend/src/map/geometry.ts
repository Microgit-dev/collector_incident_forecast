import type { LonLat, Polygon } from '../api/types'

export function contains(polygon: Polygon | null | undefined, [lon, lat]: LonLat): boolean {
  const pts = polygon?.coordinates[0] ?? []
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]
    const [xj, yj] = pts[j]
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi + 1e-15) + xi) inside = !inside
  }
  return inside
}

export function bounds(polygons: (Polygon | null | undefined)[]): [LonLat, LonLat] | null {
  const pts = polygons.flatMap((p) => p?.coordinates[0] ?? [])
  if (!pts.length) return null
  const lons = pts.map((p) => p[0])
  const lats = pts.map((p) => p[1])
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ]
}

/** Площадь контура, м² (плоская проекция у контура — точности хватает для зданий). */
export function areaM2(polygon: Polygon): number {
  const pts = polygon.coordinates[0]
  if (pts.length < 4) return 0
  const lat0 = (pts[0][1] * Math.PI) / 180
  const k = 6371000
  const xy = pts.map(([lon, lat]) => [((lon * Math.PI) / 180) * k * Math.cos(lat0), ((lat * Math.PI) / 180) * k])
  let a = 0
  for (let i = 0; i < xy.length - 1; i++) a += xy[i][0] * xy[i + 1][1] - xy[i + 1][0] * xy[i][1]
  return Math.abs(a) / 2
}

export function centroidOf(polygon: Polygon): LonLat {
  const pts = polygon.coordinates[0].slice(0, -1)
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length]
}

/** Прореживание контура из тайлов: вершины ближе `meters` к предыдущей и почти на одной прямой — убираются. */
export function simplify(polygon: Polygon, meters = 0.8): Polygon {
  const ring = polygon.coordinates[0].slice(0, -1)
  const lat0 = (ring[0][1] * Math.PI) / 180
  const k = 6371000
  const xy = (p: number[]) => [((p[0] * Math.PI) / 180) * k * Math.cos(lat0), ((p[1] * Math.PI) / 180) * k]
  let pts = ring.filter((p, i) => {
    if (i === 0) return true
    const [ax, ay] = xy(ring[i - 1])
    const [bx, by] = xy(p)
    return Math.hypot(bx - ax, by - ay) >= meters
  })
  // точки почти на прямой между соседями (отклонение < meters)
  pts = pts.filter((p, i) => {
    if (pts.length <= 4) return true
    const [ax, ay] = xy(pts[(i - 1 + pts.length) % pts.length])
    const [bx, by] = xy(p)
    const [cx, cy] = xy(pts[(i + 1) % pts.length])
    const len = Math.hypot(cx - ax, cy - ay) || 1
    return Math.abs((cx - ax) * (ay - by) - (ax - bx) * (cy - ay)) / len >= meters
  })
  if (pts.length < 3) return polygon
  return { type: 'Polygon', coordinates: [[...pts, pts[0]]] }
}
