import { useDeck } from '../deck'
import { formatScore } from '../lib/format'
import type { GapBar } from '../lib/types'

function geometry(score: number, min: number, max: number): { left: string; width: string } {
  const span = max - min || 1
  const zero = ((0 - min) / span) * 100
  const clamped = Math.min(max, Math.max(min, score))
  const pos = ((clamped - min) / span) * 100
  if (clamped >= 0) return { left: `${zero}%`, width: `${Math.max(0.8, pos - zero)}%` }
  return { left: `${pos}%`, width: `${Math.max(0.8, zero - pos)}%` }
}

function Row({ bar, min, max }: { bar: GapBar; min: number; max: number }) {
  const ref = bar.agent === 'solver'
  return (
    <div className={ref ? 'bar-row is-ref' : 'bar-row'}>
      <span className="bar-label">{bar.label}</span>
      <div className="bar-track">
        <i className="bar-zero" style={{ left: `${((0 - min) / ((max - min) || 1)) * 100}%` }} />
        {bar.score == null ? (
          <span className="bar-pending">TODO · pending</span>
        ) : (
          <i
            className={bar.score < 0 ? 'bar-fill is-neg' : 'bar-fill'}
            style={geometry(bar.score, min, max)}
          />
        )}
      </div>
      <span className="bar-score">
        {bar.score == null ? '—' : formatScore(bar.score)}
        <em>TODO</em>
      </span>
    </div>
  )
}

export function Gap() {
  const deck = useDeck()
  if (!deck) return <p className="loading">Loading the gap file…</p>
  const file = deck.results
  const min = file.scale?.min ?? -1
  const max = file.scale?.max ?? 1
  return (
    <div className="gap">
      {file.todo !== false && <p className="stamp-banner">TODO · not a measurement</p>}
      <div className="gap-cols">
        {file.tiers.map((tier) => (
          <section key={tier.tier} className={tier.headline ? 'tier is-hot' : 'tier'}>
            <header>
              <h3>{tier.tier}</h3>
              {tier.kicker && <span>{tier.kicker}</span>}
            </header>
            {tier.bars.map((bar) => (
              <Row key={bar.id} bar={bar} min={min} max={max} />
            ))}
          </section>
        ))}
      </div>
      {file.disclaimer && <p className="disclaimer">{file.disclaimer}</p>}
    </div>
  )
}
