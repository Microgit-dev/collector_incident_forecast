/**
 * Привязка плана этажа к местности на клиенте — для живого предпросмотра, пока точки ставятся.
 * Та же модель, что на бэкенде (apps/topology/georef.py): аффинная МНК-подгонка пиксель → веб-меркатор
 * (в метрах меркатора, а не в градусах: на широте Москвы градус долготы вдвое короче градуса широты).
 * Сохраняет углы бэкенд — здесь только превью и пересчёт точек между планами этажей.
 *
 * «Подогнать по контуру»: прямоугольник минимальной площади вокруг контура здания (выделенного по
 * снимку) сопоставляется с рамкой чертежа на плане — тёмные линии стен, без полей листа. Это грубый
 * старт: дальше план уточняется парами точек «угол на плане ↔ угол на снимке».
 */
import type { ControlPoint, LonLat, Polygon } from '../api/types'

const R = 6378137
const MIN_SPREAD = 5e-3

const mercX = (lon: number) => (R * lon * Math.PI) / 180
const mercY = (lat: number) => R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
const invX = (x: number) => ((x / R) * 180) / Math.PI
const invY = (y: number) => ((2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180) / Math.PI

export interface Affine {
  toLonLat: (px: number, py: number) => LonLat
  toPixel: (lon: number, lat: number) => [number, number]
  /** невязка каждой включённой точки, м (в порядке points) */
  residuals: (number | null)[]
  rmse: number
}

function solve3(m: number[][], rhs: number[]): number[] | null {
  const a = m.map((row, i) => [...row, rhs[i]])
  for (let col = 0; col < 3; col++) {
    let pivot = col
    for (let r = col + 1; r < 3; r++) if (Math.abs(a[r][col]) > Math.abs(a[pivot][col])) pivot = r
    if (Math.abs(a[pivot][col]) < 1e-12) return null
    ;[a[col], a[pivot]] = [a[pivot], a[col]]
    for (let r = 0; r < 3; r++) {
      if (r === col) continue
      const f = a[r][col] / a[col][col]
      for (let c = col; c < 4; c++) a[r][c] -= f * a[col][c]
    }
  }
  const out = [a[0][3] / a[0][0], a[1][3] / a[1][1], a[2][3] / a[2][2]]
  return out.every(Number.isFinite) ? out : null
}

/** Разброс точек поперёк главной оси (доля размера): почти коллинеарные точки дают ложную подгонку. */
function spreadOk(us: number[], vs: number[]): boolean {
  const n = us.length
  const mu = us.reduce((s, x) => s + x, 0) / n
  const mv = vs.reduce((s, x) => s + x, 0) / n
  let cuu = 0
  let cuv = 0
  let cvv = 0
  for (let i = 0; i < n; i++) {
    cuu += (us[i] - mu) ** 2
    cuv += (us[i] - mu) * (vs[i] - mv)
    cvv += (vs[i] - mv) ** 2
  }
  cuu /= n
  cuv /= n
  cvv /= n
  const tr = cuu + cvv
  const lambda = (tr - Math.sqrt(Math.max(0, tr * tr - 4 * (cuu * cvv - cuv * cuv)))) / 2
  return Math.sqrt(Math.max(0, lambda)) >= MIN_SPREAD
}

/** Подгонка по включённым точкам; null — точек меньше трёх или они на одной линии. */
export function fitAffine(points: ControlPoint[], width: number, height: number): Affine | null {
  const used = points.filter((p) => p.on && [p.px, p.py, p.lon, p.lat].every(Number.isFinite))
  if (used.length < 3 || !(width > 0) || !(height > 0)) return null
  const scale = Math.max(width, height)
  const us = used.map((p) => p.px / scale)
  const vs = used.map((p) => p.py / scale)
  if (!spreadOk(us, vs)) return null
  const xs = used.map((p) => mercX(p.lon))
  const ys = used.map((p) => mercY(p.lat))
  // центрирование меркатора: абсолютные значения ~10⁶ м съедают точность
  const ox = xs.reduce((s, x) => s + x, 0) / xs.length
  const oy = ys.reduce((s, y) => s + y, 0) / ys.length
  let suu = 0, suv = 0, su = 0, svv = 0, sv = 0, sux = 0, svx = 0, sx = 0, suy = 0, svy = 0, sy = 0
  used.forEach((_, i) => {
    const u = us[i]
    const v = vs[i]
    const x = xs[i] - ox
    const y = ys[i] - oy
    suu += u * u
    suv += u * v
    su += u
    svv += v * v
    sv += v
    sux += u * x
    svx += v * x
    sx += x
    suy += u * y
    svy += v * y
    sy += y
  })
  const normal = [
    [suu, suv, su],
    [suv, svv, sv],
    [su, sv, used.length],
  ]
  const fx = solve3(normal, [sux, svx, sx])
  const fy = solve3(normal, [suy, svy, sy])
  if (!fx || !fy) return null
  const det = fx[0] * fy[1] - fx[1] * fy[0]
  if (Math.abs(det) < 1e-12) return null
  const toMerc = (px: number, py: number): [number, number] => {
    const u = px / scale
    const v = py / scale
    return [fx[0] * u + fx[1] * v + fx[2] + ox, fy[0] * u + fy[1] * v + fy[2] + oy]
  }
  const toLonLat = (px: number, py: number): LonLat => {
    const [x, y] = toMerc(px, py)
    return [invX(x), invY(y)]
  }
  const toPixel = (lon: number, lat: number): [number, number] => {
    const x = mercX(lon) - ox - fx[2]
    const y = mercY(lat) - oy - fy[2]
    const u = (fy[1] * x - fx[1] * y) / det
    const v = (-fy[0] * x + fx[0] * y) / det
    return [u * scale, v * scale]
  }
  const k = Math.cos((used[0].lat * Math.PI) / 180)
  let sq = 0
  const residuals = points.map((p) => {
    if (!p.on) return null
    const [x, y] = toMerc(p.px, p.py)
    const d = Math.hypot(x - mercX(p.lon), y - mercY(p.lat)) * k
    sq += d * d
    return d
  })
  return { toLonLat, toPixel, residuals, rmse: Math.sqrt(sq / used.length) }
}

/** Углы картинки nw, ne, se, sw на местности — порядок MapLibre ImageSource. */
export function planCorners(fit: Affine, width: number, height: number): LonLat[] {
  return [fit.toLonLat(0, 0), fit.toLonLat(width, 0), fit.toLonLat(width, height), fit.toLonLat(0, height)]
}

// ---------- прямоугольник вокруг контура здания ----------

type XY = [number, number]

function hull(points: XY[]): XY[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  if (pts.length < 3) return pts
  const cross = (o: XY, a: XY, b: XY) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lower: XY[] = []
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper: XY[] = []
  for (const p of [...pts].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)]
}

/**
 * Прямоугольник минимальной площади вокруг контура: углы по часовой от «северо-западного»
 * (ось прямоугольника ближе к направлению восток—запад считается шириной).
 */
export function minAreaRect(polygon: Polygon): LonLat[] | null {
  const ring = polygon.coordinates[0].slice(0, -1)
  if (ring.length < 3) return null
  const lat0 = (ring[0][1] * Math.PI) / 180
  const k = 6371000
  const lon0 = ring[0][0]
  const toXY = ([lon, lat]: number[]): XY => [(((lon - lon0) * Math.PI) / 180) * k * Math.cos(lat0), ((lat * Math.PI) / 180) * k]
  const fromXY = ([x, y]: XY): LonLat => [lon0 + ((x / (k * Math.cos(lat0))) * 180) / Math.PI, ((y / k) * 180) / Math.PI]
  const h = hull(ring.map(toXY))
  if (h.length < 3) return null
  let best: { area: number; angle: number; box: number[] } | null = null
  for (let i = 0; i < h.length; i++) {
    const [ax, ay] = h[i]
    const [bx, by] = h[(i + 1) % h.length]
    let angle = Math.atan2(by - ay, bx - ax)
    // ось ближе к востоку: угол в (−45°, 45°]
    while (angle > Math.PI / 4) angle -= Math.PI / 2
    while (angle <= -Math.PI / 4) angle += Math.PI / 2
    const c = Math.cos(angle)
    const s = Math.sin(angle)
    let umin = Infinity, umax = -Infinity, vmin = Infinity, vmax = -Infinity
    for (const [x, y] of h) {
      const u = x * c + y * s
      const v = -x * s + y * c
      umin = Math.min(umin, u)
      umax = Math.max(umax, u)
      vmin = Math.min(vmin, v)
      vmax = Math.max(vmax, v)
    }
    const area = (umax - umin) * (vmax - vmin)
    if (!best || area < best.area) best = { area, angle, box: [umin, umax, vmin, vmax] }
  }
  if (!best) return null
  const c = Math.cos(best.angle)
  const s = Math.sin(best.angle)
  const [umin, umax, vmin, vmax] = best.box
  const back = (u: number, v: number): LonLat => fromXY([u * c - v * s, u * s + v * c])
  return [back(umin, vmax), back(umax, vmax), back(umax, vmin), back(umin, vmin)]
}

/** Рамка на плане [x0, y0, x1, y1] в пикселях. */
export type PlanBox = [number, number, number, number]

/**
 * Пары точек «углы рамки чертежа ↔ углы прямоугольника здания». turn — поворот плана на 90° × turn
 * по часовой (план может быть начерчен не «севером вверх»).
 */
export function contourPoints(box: PlanBox, rect: LonLat[], turn: number): ControlPoint[] {
  const [x0, y0, x1, y1] = box
  const planCorners: [number, number][] = [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ]
  return planCorners.map(([px, py], i) => {
    const [lon, lat] = rect[(i + turn) % 4]
    return { px: Math.round(px * 10) / 10, py: Math.round(py * 10) / 10, lon, lat, on: true }
  })
}

/** Поворот, при котором пропорции рамки плана ближе к пропорциям здания (0 или 1). */
export function bestTurn(box: PlanBox, rect: LonLat[]): number {
  const dist = (a: LonLat, b: LonLat) => {
    const k = Math.cos((a[1] * Math.PI) / 180)
    return Math.hypot((a[0] - b[0]) * k, a[1] - b[1])
  }
  const planWide = box[2] - box[0] >= box[3] - box[1]
  const rectWide = dist(rect[0], rect[1]) >= dist(rect[1], rect[2])
  return planWide === rectWide ? 0 : 1
}

/**
 * Рамка чертежа на плане: границы тёмных линий (стены), без белых полей листа. Край — первая строка
 * (столбец), где тёмные пиксели занимают не меньше 8 % длины: это линия наружной стены, а подписи
 * и отдельные значки по краю листа до такого порога не дотягивают.
 */
export async function drawingBox(url: string, width: number, height: number): Promise<PlanBox> {
  const image = new Image()
  image.src = url
  await image.decode()
  const k = Math.min(1, 900 / Math.max(width, height))
  const w = Math.max(1, Math.round(width * k))
  const h = Math.max(1, Math.round(height * k))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return [0, 0, width, height]
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(image, 0, 0, w, h)
  const data = ctx.getImageData(0, 0, w, h).data
  const rows = new Array<number>(h).fill(0)
  const cols = new Array<number>(w).fill(0)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4
      const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
      if (lum < 160) {
        rows[y]++
        cols[x]++
      }
    }
  }
  const edge = (arr: number[], len: number) => {
    const min = Math.max(1, len * 0.08)
    const first = arr.findIndex((n) => n >= min)
    let last = -1
    for (let i = arr.length - 1; i >= 0; i--)
      if (arr[i] >= min) {
        last = i
        break
      }
    return first < 0 || last <= first ? null : [first, last + 1]
  }
  const ys = edge(rows, w)
  const xs = edge(cols, h)
  if (!xs || !ys) return [0, 0, width, height]
  return [xs[0] / k, ys[0] / k, xs[1] / k, ys[1] / k]
}
