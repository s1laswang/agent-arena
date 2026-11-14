import { useEffect, useState } from 'react'
import { useReducedMotion } from '../hooks/useReducedMotion'

const PHASES = ['source', 'split', 'delivered', 'leaked'] as const

const GROUPS = [
  { label: 'A', name: 'Engineering', color: '#e0b15a', n: 5 },
  { label: 'B', name: 'Finance', color: '#3ec4b2', n: 5 },
  { label: 'C', name: 'Sales', color: '#e36d7a', n: 5 },
]

export function Trap() {
  const reduced = useReducedMotion()
  const [phase, setPhase] = useState(3)
  useEffect(() => {
    if (reduced) return
    const id = window.setInterval(() => setPhase((current) => (current + 1) % PHASES.length), 1800)
    return () => window.clearInterval(id)
  }, [reduced])
  const shown = reduced ? 'leaked' : PHASES[phase]

  return (
    <div className="trap">
      <div className="trap-copy">
        <p className="kicker">One document, three ways</p>
        <p className="lede">
          Give each group a different variant. When a copy surfaces in the leak feed, the variant names the group.
        </p>
        <p>
          One variant sent to everyone teaches nothing. There is no split to read. A careful mole also tends to skip a
          copy that too many people hold.
        </p>
        <p className="fine">You cannot hand every person a unique copy. A few variants have to do the work.</p>
      </div>
      <div className="trap-stage" data-phase={shown}>
        <div className="source-doc">
          <span>Source</span>
          <strong>Q3 pricing strategy</strong>
        </div>
        <div className="groups">
          {GROUPS.map((group) => (
            <article key={group.label} className={group.label === 'B' ? 'group is-b' : 'group'} style={{ ['--v' as string]: group.color }}>
              <header>
                <b>Variant {group.label}</b>
                <span>{group.name}</span>
              </header>
              <div className="silhouettes" aria-hidden="true">
                {Array.from({ length: group.n }, (_, i) => (
                  <i key={i} />
                ))}
              </div>
              <p>{group.n} recipients</p>
              {group.label === 'B' && <em className="came-back">In the feed</em>}
            </article>
          ))}
        </div>
        <div className="feed-line" role="status">
          <span>Leak feed · day 6</span>
          <strong>Variant B surfaced · Q3 pricing strategy</strong>
        </div>
      </div>
    </div>
  )
}
