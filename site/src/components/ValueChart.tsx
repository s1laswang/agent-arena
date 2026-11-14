import { HORIZON, type Point } from '../lib/replay'

export function ValueChart({ points, cursorDay }: { points: Point[]; cursorDay: number }) {
  const w = 360
  const h = 86
  const padL = 28
  const padR = 8
  const padT = 8
  const padB = 16
  const xOf = (x: number) => padL + ((x - 1) / (HORIZON - 1)) * (w - padL - padR)
  const yOf = (v: number) => padT + (1 - Math.min(1, Math.max(0, v))) * (h - padT - padB)
  const d = points
    .map((point, i) => `${i === 0 ? 'M' : 'L'}${xOf(point.x).toFixed(1)},${yOf(point.v).toFixed(1)}`)
    .join(' ')
  const last = points.at(-1)
  const area = last
    ? `${d} L${xOf(last.x).toFixed(1)},${yOf(0).toFixed(1)} L${xOf(points[0]!.x).toFixed(1)},${yOf(0).toFixed(1)} Z`
    : ''
  const label = last ? `Company value ${last.v.toFixed(2)}` : 'Company value'
  return (
    <svg className="vchart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
      <line className="grid" x1={padL} x2={w - padR} y1={yOf(1)} y2={yOf(1)} />
      <line className="grid" x1={padL} x2={w - padR} y1={yOf(0.5)} y2={yOf(0.5)} />
      <line className="axis" x1={padL} x2={w - padR} y1={yOf(0)} y2={yOf(0)} />
      <line className="cursor" x1={xOf(cursorDay)} x2={xOf(cursorDay)} y1={padT} y2={h - padB} />
      {area && <path className="area" d={area} />}
      {d && <path className="line" d={d} />}
      {last && <circle className="head" cx={xOf(last.x)} cy={yOf(last.v)} r="3.5" />}
      <text className="tick" x={padL - 6} y={yOf(1) + 3} textAnchor="end">
        1
      </text>
      <text className="tick" x={padL - 6} y={yOf(0) + 3} textAnchor="end">
        0
      </text>
      <text className="tick" x={xOf(1)} y={h - 2} textAnchor="start">
        1
      </text>
      <text className="tick" x={xOf(HORIZON)} y={h - 2} textAnchor="end">
        {HORIZON}
      </text>
    </svg>
  )
}
