import { useEffect, useMemo, useState } from 'react'
import { useReducedMotion } from '../hooks/useReducedMotion'
import { initials } from '../lib/format'

type Person = { name: string; dept: string; role: string; room: string }

const PEOPLE: Person[] = [
  { name: 'Teemu Korhonen', dept: 'Engineering', role: 'tech lead', room: 'eng' },
  { name: 'Ville Makinen', dept: 'Engineering', role: 'senior engineer', room: 'eng' },
  { name: 'Kalle Heikkinen', dept: 'Engineering', role: 'engineer', room: 'eng' },
  { name: 'Pihla Lehtinen', dept: 'Engineering', role: 'engineer', room: 'eng' },
  { name: 'Hanna Salminen', dept: 'Finance', role: 'controller', room: 'fin' },
  { name: 'Petri Jokinen', dept: 'Finance', role: 'analyst', room: 'fin' },
  { name: 'Emma Laine', dept: 'Finance', role: 'accountant', room: 'fin' },
  { name: 'Janne Koskinen', dept: 'Finance', role: 'analyst', room: 'fin' },
  { name: 'Mikko Heinonen', dept: 'Sales', role: 'sales manager', room: 'sales' },
  { name: 'Sofia Salo', dept: 'Sales', role: 'account exec', room: 'sales' },
  { name: 'Iida Rantanen', dept: 'Sales', role: 'sales ops', room: 'sales' },
  { name: 'Aleksi Laitinen', dept: 'Sales', role: 'account exec', room: 'sales' },
  { name: 'Noora Karjalainen', dept: 'Legal', role: 'counsel', room: 'legal' },
  { name: 'Olli Hamalainen', dept: 'Legal', role: 'compliance officer', room: 'legal' },
  { name: 'Riikka Makinen', dept: 'Legal', role: 'paralegal', room: 'legal' },
  { name: 'Markus Nieminen', dept: 'Legal', role: 'counsel', room: 'legal' },
]

const ROOMS = [
  { id: 'eng', name: 'Engineering', x: 20, y: 16, w: 390, h: 294 },
  { id: 'fin', name: 'Finance', x: 590, y: 16, w: 390, h: 294 },
  { id: 'sales', name: 'Sales', x: 20, y: 326, w: 390, h: 294 },
  { id: 'legal', name: 'Legal', x: 590, y: 326, w: 390, h: 294 },
]

type Desk = Person & { x: number; y: number; w: number; h: number; index: number }

function layout(): Desk[] {
  const desks: Desk[] = []
  for (const room of ROOMS) {
    const group = PEOPLE.filter((person) => person.room === room.id)
    const gapX = 10
    const gapY = 8
    const insetX = 16
    const insetY = 42
    const cardW = (room.w - insetX * 2 - gapX) / 2
    const cardH = 86
    group.forEach((person, i) => {
      desks.push({
        ...person,
        index: desks.length,
        w: cardW,
        h: cardH,
        x: room.x + insetX + (i % 2) * (cardW + gapX),
        y: room.y + insetY + Math.floor(i / 2) * (cardH + gapY),
      })
    })
  }
  return desks
}

export function Company() {
  const desks = useMemo(layout, [])
  const reduced = useReducedMotion()
  const [focus, setFocus] = useState(0)
  const [pinned, setPinned] = useState(false)
  useEffect(() => {
    if (reduced || pinned) return
    const id = window.setInterval(() => setFocus((i) => (i + 1) % desks.length), 3200)
    return () => window.clearInterval(id)
  }, [reduced, pinned, desks.length])
  const person = desks[focus] ?? desks[0]!

  return (
    <div className="company">
      <div className="floor-hold">
        <div className="floor-stage">
          <svg viewBox="0 0 1000 640" role="img" aria-label="Synthetic floor plan of Halcyon Metrics">
            <rect className="shell" x="8" y="6" width="984" height="628" />
            <rect className="well" x="418" y="16" width="164" height="604" />
            <text className="well-label" x="500" y="300" textAnchor="middle">
              LEAK WELL
            </text>
            <text className="well-out" x="500" y="590" textAnchor="middle">
              OUT
            </text>
            {ROOMS.map((room) => (
              <g key={room.id}>
                <rect className="room" x={room.x} y={room.y} width={room.w} height={room.h} />
                <text className="room-label" x={room.x + 16} y={room.y + 26}>
                  {room.name}
                </text>
              </g>
            ))}
            {desks.map((desk) => (
              <g
                key={desk.name}
                className={desk.index === focus ? 'desk is-hot' : 'desk'}
                tabIndex={0}
                role="button"
                aria-pressed={desk.index === focus}
                aria-label={`${desk.name}, ${desk.role}, ${desk.dept}`}
                onClick={() => {
                  if (focus === desk.index && pinned) {
                    setPinned(false)
                    return
                  }
                  setFocus(desk.index)
                  setPinned(true)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    setFocus(desk.index)
                    setPinned(true)
                  }
                }}
              >
                <rect x={desk.x} y={desk.y} width={desk.w} height={desk.h} />
                <text className="ini" x={desk.x + 14} y={desk.y + 38}>
                  {initials(desk.name)}
                </text>
                <text className="dn" x={desk.x + 62} y={desk.y + 36}>
                  {desk.name.split(' ')[0]}
                </text>
              </g>
            ))}
          </svg>
          <span className="courier" aria-hidden="true" />
        </div>
      </div>
      <aside className="dossier">
        <p className="kicker">Synthetic company</p>
        <p className="co">Halcyon Metrics</p>
        <p className="fine">Not a real firm. The names are made up.</p>
        <p className="who" key={person.name}>
          {person.name}
        </p>
        <p className="who-role">
          {person.dept} · {person.role}
        </p>
        {pinned && (
          <button type="button" className="texty" onClick={() => setPinned(false)}>
            Release the desk
          </button>
        )}
        <ul className="facts">
          <li>One mole. The plan does not say who.</li>
          <li>Every leak spends company value. It starts at 1.</li>
          <li>Eight investigative calls a day, then the day turns.</li>
          <li>Fourteen days. Accuse exactly once.</li>
        </ul>
      </aside>
    </div>
  )
}
