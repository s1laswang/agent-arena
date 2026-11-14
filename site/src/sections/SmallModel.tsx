import { useDeck } from '../deck'
import { formatScore } from '../lib/format'
import type { ScorePlate, TagRow } from '../lib/types'

function Plate({ plate }: { plate: ScorePlate }) {
  return (
    <article className="plate">
      <p className="kicker">{plate.label}</p>
      <p className={plate.score == null ? 'plate-score is-empty' : 'plate-score'}>
        {plate.score == null ? 'No score' : formatScore(plate.score)}
      </p>
      {plate.detail && <p className="fine">{plate.detail}</p>}
      {plate.todo !== false && <p className="todo-chip">TODO</p>}
    </article>
  )
}

function Tag({ row }: { row: TagRow }) {
  const width = (value: number | null) => (value == null ? 0 : `${Math.max(4, Math.min(100, value))}%`)
  return (
    <li>
      <span>{row.label}</span>
      <span className="tag-track" aria-hidden="true">
        <i className="before" style={{ width: width(row.before) }} />
        <i className="after" style={{ width: width(row.after) }} />
      </span>
      <span className="tag-nums">
        {row.before == null || row.after == null ? 'TODO' : `${row.before} → ${row.after}`}
      </span>
    </li>
  )
}

export function SmallModel() {
  const deck = useDeck()
  if (!deck) return <p className="loading">Loading the small-model file…</p>
  const file = deck.smallModel
  return (
    <div className="learn">
      <div className="learn-copy">
        <p className="kicker">{file.model ?? 'Small model'}</p>
        {file.method && <p className="lede">{file.method}</p>}
        {file.disclaimer && <p className="disclaimer">{file.disclaimer}</p>}
      </div>
      <div className="plates">
        {file.todo !== false && <p className="stamp-banner">PLACEHOLDER</p>}
        <Plate plate={file.before} />
        <Plate plate={file.after} />
      </div>
      <ul className="tag-list">
        {file.tags.map((row) => (
          <Tag key={row.tag} row={row} />
        ))}
      </ul>
    </div>
  )
}
