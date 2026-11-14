import { useDeck } from '../deck'
import type { ForgeGen } from '../lib/types'

function Chart({ gens, illustrative }: { gens: ForgeGen[]; illustrative: boolean }) {
  const points = gens.filter((gen): gen is ForgeGen & { regret: number } => typeof gen.regret === 'number')
  const w = 720
  const h = 280
  const pad = 36
  if (points.length === 0) {
    return <p className="empty-chart">No generations recorded. TODO</p>
  }
  const maxG = Math.max(...points.map((point) => point.generation), 1)
  const maxR = Math.max(0.3, ...points.map((point) => point.regret))
  const x = (generation: number) => pad + (generation / maxG) * (w - pad * 2)
  const y = (regret: number) => h - pad - (regret / maxR) * (h - pad * 2)
  const d = points
    .map((point, i) => `${i === 0 ? 'M' : 'L'}${x(point.generation).toFixed(1)},${y(point.regret).toFixed(1)}`)
    .join(' ')
  return (
    <svg className="forge-chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Placeholder Mole Forge chart">
      <line className="grid" x1={pad} x2={w - pad} y1={y(0)} y2={y(0)} />
      <path className={illustrative ? 'series is-fake' : 'series'} d={d} />
      {points.map((point) => (
        <g key={point.generation}>
          <circle cx={x(point.generation)} cy={y(point.regret)} r="4.5" />
          <text x={x(point.generation)} y={h - 12} textAnchor="middle">
            {point.generation}
          </text>
        </g>
      ))}
      <text className="ylab" x="14" y="20">
        regret
      </text>
      {illustrative && (
        <text className="watermark" x={w / 2} y={h / 2} textAnchor="middle">
          PLACEHOLDER
        </text>
      )}
    </svg>
  )
}

export function Forge() {
  const deck = useDeck()
  if (!deck) return <p className="loading">Loading the forge file…</p>
  const file = deck.forge
  const illustrative = file.illustrative === true || file.placeholder === true || file.generations.some((gen) => gen.illustrative)
  return (
    <div className="forge">
      <div className="forge-copy">
        <p className="kicker">Gemini writes the mole</p>
        <p className="lede">
          Gemini proposes mole strategies. The loop keeps the ones that widen the gap, and only if our reference still
          catches them.
        </p>
        {file.constraint && <p>{file.constraint}</p>}
        {file.disclaimer && <p className="disclaimer">{file.disclaimer}</p>}
      </div>
      <div className="forge-panel">
        {file.todo !== false && <p className="stamp-banner">TODO · illustrative</p>}
        <Chart gens={file.generations} illustrative={illustrative} />
      </div>
    </div>
  )
}
