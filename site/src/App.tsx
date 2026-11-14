import { useEffect, useState, type ReactNode } from 'react'
import { Frame } from './components/Frame'
import { Progress } from './components/Progress'
import { DeckContext } from './deck'
import { loadDeck, type DeckData } from './lib/load'
import { Company } from './sections/Company'
import { Failures } from './sections/Failures'
import { Forge } from './sections/Forge'
import { Gap } from './sections/Gap'
import { Hook } from './sections/Hook'
import { Integrity } from './sections/Integrity'
import { Replay } from './sections/Replay'
import { SmallModel } from './sections/SmallModel'
import { Trap } from './sections/Trap'

const SECTIONS: { id: string; short: string; title: string; cover?: boolean; node: (active: boolean) => ReactNode }[] = [
  { id: 'hook', short: 'Hook', title: 'Hook', cover: true, node: () => <Hook /> },
  { id: 'company', short: 'Company', title: 'The company', node: () => <Company /> },
  { id: 'trap', short: 'Trap', title: 'How a canary trap works', node: () => <Trap /> },
  { id: 'replay', short: 'Replay', title: 'Live replay', node: (active) => <Replay active={active} /> },
  { id: 'gap', short: 'Gap', title: 'The gap', node: () => <Gap /> },
  { id: 'failures', short: 'Failures', title: 'Why agents fail', node: () => <Failures /> },
  { id: 'integrity', short: 'Integrity', title: 'Reward integrity', node: () => <Integrity /> },
  { id: 'forge', short: 'Forge', title: 'Gemini evolves the moles', node: () => <Forge /> },
  { id: 'learn', short: 'Model', title: 'The small model learns', node: () => <SmallModel /> },
]

function indexFromHash(): number {
  const id = window.location.hash.replace(/^#/, '')
  const index = SECTIONS.findIndex((section) => section.id === id)
  return index >= 0 ? index : 0
}

export function App() {
  const [index, setIndex] = useState(indexFromHash)
  const [deck, setDeck] = useState<DeckData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadDeck()
      .then((data) => {
        if (!cancelled) setDeck(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the dossier')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const next = `#${SECTIONS[index]!.id}`
    if (window.location.hash !== next) history.replaceState(null, '', next)
  }, [index])

  useEffect(() => {
    const onPop = () => setIndex(indexFromHash())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement && target.closest('input, textarea, select')) return
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown' || event.key === 'PageDown') {
        event.preventDefault()
        setIndex((current) => Math.min(SECTIONS.length - 1, current + 1))
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp' || event.key === 'PageUp') {
        event.preventDefault()
        setIndex((current) => Math.max(0, current - 1))
      } else if (event.key === 'Home') {
        event.preventDefault()
        setIndex(0)
      } else if (event.key === 'End') {
        event.preventDefault()
        setIndex(SECTIONS.length - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <DeckContext.Provider value={deck}>
      <div className="deck">
        <div className="stage">
          {SECTIONS.map((section, i) => (
            <Slot key={section.id} active={i === index} preserve={section.id === 'replay'} label={section.title}>
              {section.cover ? (
                section.node(i === index)
              ) : (
                <Frame index={i + 1} title={section.title}>
                  {section.node(i === index)}
                </Frame>
              )}
            </Slot>
          ))}
        </div>
        {error && <p className="deck-error">{error}</p>}
        <Progress sections={SECTIONS} index={index} onJump={setIndex} />
      </div>
    </DeckContext.Provider>
  )
}

function Slot({
  active,
  preserve,
  label,
  children,
}: {
  active: boolean
  preserve: boolean
  label: string
  children: ReactNode
}) {
  const [seen, setSeen] = useState(active)
  useEffect(() => {
    if (active) setSeen(true)
  }, [active])
  if (!seen) return null
  if (!active && !preserve) return null
  return (
    <section className="slide" hidden={!active} aria-label={label}>
      {children}
    </section>
  )
}
