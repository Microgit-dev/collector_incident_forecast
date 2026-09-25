import { Group, Stack, Text } from '@mantine/core'
import dayjs from 'dayjs'
import { useState, type MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { CHANNEL_STATE, INCIDENT_TYPE, RISK } from '../api/labels'
import type { HistoryIncident, HistoryInterval, HistoryPoint, HistoryPrediction, RiskLevel } from '../api/types'

const W = 1000
const LABEL = 130
const FACET: Record<string, string> = {
  primary: 'Состояние',
  power: 'Питание',
  operation: 'Работа',
  guard: 'Охрана',
  temperature: 'Температура',
  pumps: 'Насосы',
  diagnostics: 'Диагностика',
}
const RISK_FILL: Record<RiskLevel, string> = {
  low: 'var(--mantine-color-gray-5)',
  medium: 'var(--mantine-color-yellow-6)',
  high: 'var(--mantine-color-orange-6)',
  critical: 'var(--mantine-color-red-7)',
}

const stateColor = (state: string) => `var(--mantine-color-${CHANNEL_STATE[state]?.color ?? 'gray'}-5)`

function ticks(from: number, to: number) {
  const span = to - from
  const hour = 3_600_000
  const step = [hour, 3 * hour, 6 * hour, 12 * hour, 24 * hour, 48 * hour, 7 * 24 * hour].find((s) => span / s <= 9) ?? 14 * 24 * hour
  // выравниваем по местным суткам, чтобы подписи шли по целым часам
  const out = []
  let t = dayjs(from).startOf('day').valueOf()
  while (t < from) t += step
  for (; t <= to; t += step) out.push(t)
  return { values: out, format: span > 2 * 24 * hour ? 'DD.MM' : 'HH:mm' }
}

interface Props {
  from: string
  to: string
  numeric: HistoryPoint[]
  unit: string
  warn: number | null
  alarm: number | null
  states: Record<string, HistoryInterval[]>
  incidents: HistoryIncident[]
  predictions: HistoryPrediction[]
  invalid: { t: string; quality: string; raw: string }[]
}

/** Показания, состояния, карточки и прогнозы канала на одной оси времени. */
export function TimeTracks({ from, to, numeric, unit, warn, alarm, states, incidents, predictions, invalid }: Props) {
  const navigate = useNavigate()
  const [hover, setHover] = useState<number | null>(null)
  const t0 = new Date(from).getTime()
  const t1 = new Date(to).getTime()
  const x = (t: string | number) => ((new Date(t).getTime() - t0) / (t1 - t0)) * W
  const axis = ticks(t0, t1)

  // шкала показаний: данные и пороги, если они рядом с данными
  const values = numeric.flatMap((p) => [p.min ?? p.v, p.max ?? p.v])
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  for (const th of [warn, alarm]) if (th !== null && values.length && th <= hi * 2 && th >= lo) hi = Math.max(hi, th)
  if (!values.length || lo === hi) {
    lo = (lo || 0) - 1
    hi = (hi || 0) + 1
  }
  const pad = (hi - lo) * 0.08
  lo -= pad
  hi += pad
  const NH = 170
  const y = (v: number) => NH - 18 - ((v - lo) / (hi - lo)) * (NH - 30)
  const line = numeric.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const band = numeric.some((p) => p.min !== undefined)
    ? numeric.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.max ?? p.v).toFixed(1)}`).join(' ') +
      ' ' +
      [...numeric]
        .reverse()
        .map((p) => `L${x(p.t).toFixed(1)},${y(p.min ?? p.v).toFixed(1)}`)
        .join(' ') +
      ' Z'
    : null

  const nearest =
    hover === null || !numeric.length
      ? null
      : numeric.reduce((best, p) => (Math.abs(x(p.t) - hover) < Math.abs(x(best.t) - hover) ? p : best), numeric[0])
  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    setHover(((e.clientX - box.left) / box.width) * W)
  }

  const facets = Object.entries(states)
  const row = (label: string, height: number, content: React.ReactNode, key: string) => (
    <Group key={key} gap="xs" wrap="nowrap" align="center">
      <Text size="xs" c="dimmed" w={LABEL} style={{ flexShrink: 0 }} ta="right">
        {label}
      </Text>
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
          {content}
        </svg>
      </div>
    </Group>
  )

  return (
    <Stack gap={4}>
      {numeric.length > 0 && (
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Stack w={LABEL} gap={0} style={{ flexShrink: 0 }} align="flex-end">
            <Text size="xs" c="dimmed">
              Показания{unit ? `, ${unit}` : ''}
            </Text>
            {nearest && (
              <>
                <Text size="sm" fw={600}>
                  {nearest.v}
                  {nearest.min !== undefined ? ` (${nearest.min}…${nearest.max})` : ''}
                </Text>
                <Text size="xs" c="dimmed">
                  {dayjs(nearest.t).format('DD.MM HH:mm')}
                </Text>
              </>
            )}
          </Stack>
          <div style={{ flex: 1, minWidth: 0 }}>
            <svg
              viewBox={`0 0 ${W} ${NH}`}
              preserveAspectRatio="none"
              style={{ width: '100%', height: NH, display: 'block' }}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              {[lo + pad, (lo + hi) / 2, hi - pad].map((v) => (
                <g key={v}>
                  <line x1={0} x2={W} y1={y(v)} y2={y(v)} stroke="var(--mantine-color-default-border)" strokeWidth={0.5} />
                  <text x={4} y={y(v) - 3} fontSize={10} fill="var(--mantine-color-dimmed)">
                    {Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(0)}
                  </text>
                </g>
              ))}
              {band && <path d={band} fill="var(--mantine-color-blue-5)" opacity={0.15} />}
              <path d={line} fill="none" stroke="var(--mantine-color-blue-6)" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
              {[
                { v: warn, color: 'yellow', label: 'предупреждение' },
                { v: alarm, color: 'red', label: 'тревога' },
              ].map(
                (th) =>
                  th.v !== null &&
                  th.v >= lo &&
                  th.v <= hi && (
                    <g key={th.label}>
                      <line
                        x1={0}
                        x2={W}
                        y1={y(th.v)}
                        y2={y(th.v)}
                        stroke={`var(--mantine-color-${th.color}-6)`}
                        strokeDasharray="6 4"
                        vectorEffect="non-scaling-stroke"
                      />
                      <text x={W - 4} y={y(th.v) - 3} fontSize={10} textAnchor="end" fill={`var(--mantine-color-${th.color}-7)`}>
                        {th.label} {th.v}
                      </text>
                    </g>
                  ),
              )}
              {invalid.map((m, i) => (
                <line key={i} x1={x(m.t)} x2={x(m.t)} y1={NH - 14} y2={NH - 4} stroke="var(--mantine-color-red-6)" strokeWidth={1.5} vectorEffect="non-scaling-stroke">
                  <title>{`${dayjs(m.t).format('DD.MM HH:mm:ss')} · ${m.raw} (${m.quality})`}</title>
                </line>
              ))}
              {nearest && (
                <g>
                  <line x1={x(nearest.t)} x2={x(nearest.t)} y1={0} y2={NH} stroke="var(--mantine-color-dark-3)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
                  <circle cx={x(nearest.t)} cy={y(nearest.v)} r={3} fill="var(--mantine-color-blue-7)" />
                </g>
              )}
            </svg>
          </div>
        </Group>
      )}

      {facets.map(([facet, intervals]) =>
        row(
          FACET[facet] ?? facet,
          18,
          intervals.map((iv, i) => (
            <rect key={i} x={x(iv.from)} y={2} width={Math.max(x(iv.to) - x(iv.from), 0.8)} height={14} fill={stateColor(iv.state)} opacity={iv.state === 'normal' ? 0.45 : 0.95}>
              <title>{`${CHANNEL_STATE[iv.state]?.label ?? iv.state}: ${iv.raw} · ${dayjs(iv.from).format('DD.MM HH:mm:ss')} — ${dayjs(iv.to).format('DD.MM HH:mm:ss')}`}</title>
            </rect>
          )),
          facet,
        ),
      )}

      {row(
        `Карточки (${incidents.length})`,
        22,
        incidents.map((inc) => {
          const a = Math.max(x(inc.opened_at), 0)
          const b = inc.resolved_at ? Math.min(x(inc.resolved_at), W) : W
          return (
            <g key={inc.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/incidents/${inc.id}`)}>
              <title>
                {`#${inc.id} ${inc.title} · ${INCIDENT_TYPE[inc.type]} · открыта ${dayjs(inc.opened_at).format('DD.MM HH:mm')}` +
                  (inc.decision ? ` · ${inc.decision.outcome}${inc.decision.cause ? `, ${inc.decision.cause}` : ''}` : '')}
              </title>
              <rect x={a} y={9} width={Math.max(b - a, 2)} height={4} fill={RISK_FILL[inc.severity]} opacity={0.5} />
              <path d={`M ${a} 4 l 6 7 l -6 7 l -6 -7 z`} fill={RISK_FILL[inc.severity]} />
            </g>
          )
        }),
        'incidents',
      )}

      {predictions.length > 0 &&
        row(
          `Прогнозы (${predictions.length})`,
          22,
          predictions.map((p, i) => (
            <circle key={i} cx={x(p.t)} cy={11} r={2 + p.p * 6} fill={RISK_FILL[p.level]} opacity={0.85}>
              <title>{`${dayjs(p.t).format('DD.MM HH:mm')} · ${Math.round(p.p * 100)}% · ${RISK[p.level].label}`}</title>
            </circle>
          )),
          'predictions',
        )}

      {row(
        '',
        16,
        axis.values.map((t) => (
          <text key={t} x={x(t)} y={12} fontSize={10} textAnchor="middle" fill="var(--mantine-color-dimmed)">
            {dayjs(t).format(axis.format)}
          </text>
        )),
        'axis',
      )}
    </Stack>
  )
}
