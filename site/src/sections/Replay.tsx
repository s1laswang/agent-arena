import { useEffect, useMemo, useRef, useState } from 'react'
import { ValueChart } from '../components/ValueChart'
import { useDeck } from '../deck'
import { bestSeed, episodeFor, parseEpisodes, tiersIn } from '../lib/episodes'
import { formatScore, formatV, shortName } from '../lib/format'
import { pickSides } from '../lib/load'
import { buildBeats, variantColor, viewAt, type Beat, type CanaryView, type EpisodeView } from '../lib/replay'
import type { Episode } from '../lib/types'

type DropState = { episodes: Episode[]; name: string } | null

export function Replay({ active }: { active: boolean }) {
  const deck = useDeck()
  const [tier, setTier] = useState('medium')
  const [seedPick, setSeedPick] = useState<number | null>(null)
  const [beat, setBeat] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [leftDrop, setLeftDrop] = useState<DropState>(null)
  const [rightDrop, setRightDrop] = useState<DropState>(null)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState<'left' | 'right' | null>(null)

  const baseTiers = useMemo(() => {
    if (!deck) return ['medium']
    const fromRef = deck.manifest.runs
      .filter((run) => run.role === 'reference')
      .flatMap((run) => deck.episodes[run.id] ?? [])
    const tiers = tiersIn(fromRef)
    return tiers.length ? tiers : ['medium']
  }, [deck])

  const tierOk = baseTiers.includes(tier) ? tier : (baseTiers[0] ?? 'medium')
  const sides = deck ? pickSides(deck, tierOk) : null
  const leftEpisodes = leftDrop?.episodes ?? sides?.left.episodes ?? []
  const rightEpisodes = rightDrop?.episodes ?? sides?.right.episodes ?? []
  const tiers = useMemo(() => {
    const merged = tiersIn([...leftEpisodes, ...rightEpisodes])
    return merged.length ? merged : baseTiers
  }, [leftEpisodes, rightEpisodes, baseTiers])
  const activeTier = tiers.includes(tierOk) ? tierOk : (tiers[0] ?? 'medium')

  const seeds = useMemo(() => {
    const rightSeeds = new Set(rightEpisodes.filter((ep) => ep.tier === activeTier).map((ep) => ep.seed))
    return leftEpisodes
      .filter((ep) => ep.tier === activeTier && rightSeeds.has(ep.seed))
      .map((ep) => ep.seed)
      .sort((a, b) => a - b)
  }, [leftEpisodes, rightEpisodes, activeTier])

  const seed = seedPick != null && seeds.includes(seedPick) ? seedPick : bestSeed(seeds, leftEpisodes, rightEpisodes, activeTier)
  const left = seed == null ? null : episodeFor(leftEpisodes, activeTier, seed)
  const right = seed == null ? null : episodeFor(rightEpisodes, activeTier, seed)
  const beats = useMemo(() => (left && right ? buildBeats(left, right) : []), [left, right])
  const beatSafe = beats.length === 0 ? 0 : Math.min(beat, beats.length - 1)
  const frame: Beat | null = beats[beatSafe] ?? null
  const leftView = left && frame ? viewAt(left, frame.leftCount) : null
  const rightView = right && frame ? viewAt(right, frame.rightCount) : null
  const prev = beatSafe > 0 ? beats[beatSafe - 1] : null
  const leftAdvanced = !prev || (frame?.leftCount ?? 0) !== prev.leftCount
  const rightAdvanced = !prev || (frame?.rightCount ?? 0) !== prev.rightCount

  const standIn = !rightDrop && (sides?.right.standIn ?? false)
  const rightLabel = rightDrop
    ? rightDrop.episodes[0]?.agent ?? rightDrop.name
    : (sides?.right.spec?.label ?? 'Frontier')

  useEffect(() => {
    setBeat(0)
    setPlaying(false)
  }, [seed, activeTier, leftDrop, rightDrop])

  useEffect(() => {
    if (!active) setPlaying(false)
  }, [active])

  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => {
      setBeat((current) => {
        if (current >= beats.length - 1) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 520)
    return () => window.clearInterval(id)
  }, [playing, beats.length])

  const playingRef = useRef(playing)
  playingRef.current = playing
  const beatRef = useRef(beatSafe)
  beatRef.current = beatSafe
  const beatsRef = useRef(beats)
  beatsRef.current = beats

  useEffect(() => {
    if (!active) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement && target.closest('input, textarea, select')) return
      if (event.key === ' ' || event.code === 'Space') {
        event.preventDefault()
        const list = beatsRef.current
        if (!playingRef.current && beatRef.current >= list.length - 1) setBeat(0)
        setPlaying((value) => !value)
      } else if (event.key === ']' || event.key === '.') {
        event.preventDefault()
        setPlaying(false)
        setBeat((current) => Math.min(beatsRef.current.length - 1, current + 1))
      } else if (event.key === '[' || event.key === ',') {
        event.preventDefault()
        setPlaying(false)
        setBeat((current) => Math.max(0, current - 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active])

  async function takeFile(file: File, side: 'left' | 'right') {
    try {
      const text = await file.text()
      const episodes = parseEpisodes(text)
      if (episodes.length === 0) throw new Error('No episodes in that file')
      setError(null)
      setSeedPick(null)
      if (side === 'left') setLeftDrop({ episodes, name: file.name })
      else setRightDrop({ episodes, name: file.name })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read that file')
    }
  }

  function jumpDay(dir: -1 | 1) {
    if (!frame) return
    setPlaying(false)
    const days = [...new Set(beats.map((item) => item.day))].sort((a, b) => a - b)
    const next = days[days.indexOf(frame.day) + dir]
    if (next == null) return
    const index = beats.findIndex((item) => item.day === next)
    if (index >= 0) setBeat(index)
  }

  if (!deck) return <p className="loading">Loading episodes…</p>

  return (
    <div className="replay">
      <div className="replay-bar">
        <div className="seeds" role="group" aria-label="Seed">
          {seeds.length === 0 && <span className="fine">No shared seed</span>}
          {seeds.length > 0 && seeds.length <= 8 &&
            seeds.map((value) => (
              <button
                key={value}
                type="button"
                className={value === seed ? 'ctrl is-on' : 'ctrl'}
                onClick={() => setSeedPick(value)}
              >
                Seed {value}
              </button>
            ))}
          {seeds.length > 8 && (
            <select aria-label="Seed" value={seed ?? ''} onChange={(event) => setSeedPick(Number(event.target.value))}>
              {seeds.map((value) => (
                <option key={value} value={value}>
                  Seed {value}
                </option>
              ))}
            </select>
          )}
        </div>
        {tiers.length > 1 && (
          <div className="seeds" role="group" aria-label="Tier">
            {tiers.map((value) => (
              <button
                key={value}
                type="button"
                className={value === activeTier ? 'ctrl is-on' : 'ctrl'}
                onClick={() => {
                  setTier(value)
                  setSeedPick(null)
                }}
              >
                {value}
              </button>
            ))}
          </div>
        )}
        <div className="transport">
          <button type="button" className="ctrl" onClick={() => jumpDay(-1)}>
            Prev day
          </button>
          <button
            type="button"
            className="ctrl"
            onClick={() => {
              setPlaying(false)
              setBeat((current) => Math.max(0, current - 1))
            }}
          >
            Step back
          </button>
          <button
            type="button"
            className="ctrl is-play"
            aria-pressed={playing}
            onClick={() => {
              if (!playing && beatSafe >= beats.length - 1) setBeat(0)
              setPlaying((value) => !value)
            }}
          >
            {playing ? 'Pause' : 'Play'}
          </button>
          <button
            type="button"
            className="ctrl"
            onClick={() => {
              setPlaying(false)
              setBeat((current) => Math.min(beats.length - 1, current + 1))
            }}
          >
            Step
          </button>
          <button type="button" className="ctrl" onClick={() => jumpDay(1)}>
            Next day
          </button>
        </div>
        <p className="day-read">
          Day {String(frame?.day ?? 1).padStart(2, '0')}
          <span> / {String(beats.at(-1)?.day ?? 14).padStart(2, '0')}</span>
        </p>
        {beats.length > 1 && (
          <input
            className="scrub"
            type="range"
            min={0}
            max={beats.length - 1}
            value={beatSafe}
            aria-label="Scrub the replay"
            onChange={(event) => {
              setPlaying(false)
              setBeat(Number(event.target.value))
            }}
          />
        )}
        <p className="keys fine">space plays · [ ] steps</p>
      </div>

      {standIn && (
        <p className="standin">
          Right seat is a stand-in. This is the heuristic, not gpt-5.5. Drop a committed run on the right, or add
          data/runs/committed/gpt-5.5/episodes.jsonl.
        </p>
      )}
      {!standIn && rightDrop && <p className="standin is-live">Right seat loaded from {rightDrop.name}.</p>}
      {!standIn && !rightDrop && sides?.right.spec?.role === 'frontier' && (
        <p className="standin is-live">Right seat is {sides.right.spec.label}, loaded from the committed run.</p>
      )}
      {error && <p className="load-error">{error}</p>}
      {seeds.length === 0 && <p className="load-error">These two files share no seed on this tier.</p>}

      <div className="replay-grid">
        <Column
          eyebrow="Reference"
          title={left?.agent ?? sides?.left.spec?.label ?? 'Solver'}
          note={leftDrop ? leftDrop.name : 'Bundled sample'}
          episode={left}
          view={leftView}
          highlight={leftAdvanced}
          globalDay={frame?.day ?? 1}
          hot={over === 'left'}
          onDragOver={() => setOver('left')}
          onDragLeave={() => setOver((value) => (value === 'left' ? null : value))}
          onDrop={(file) => void takeFile(file, 'left')}
        />
        <Column
          eyebrow={standIn ? 'Stand-in for gpt-5.5' : 'Frontier'}
          title={rightLabel}
          note={rightDrop ? rightDrop.name : standIn ? 'Heuristic sample' : 'Committed run'}
          episode={right}
          view={rightView}
          highlight={rightAdvanced}
          globalDay={frame?.day ?? 1}
          hot={over === 'right'}
          standIn={standIn}
          onDragOver={() => setOver('right')}
          onDragLeave={() => setOver((value) => (value === 'right' ? null : value))}
          onDrop={(file) => void takeFile(file, 'right')}
        />
      </div>
      <p className="fine sample-note">Three-seed sample, not the 40-seed judge table. Variant A gold, B teal, C rose.</p>
    </div>
  )
}

function Column({
  eyebrow,
  title,
  note,
  episode,
  view,
  highlight,
  globalDay,
  hot,
  standIn,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  eyebrow: string
  title: string
  note: string
  episode: Episode | null
  view: EpisodeView | null
  highlight: boolean
  globalDay: number
  hot: boolean
  standIn?: boolean
  onDragOver: () => void
  onDragLeave: () => void
  onDrop: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const latest = view?.canaries.at(-1) ?? null
  const earlier = view ? view.canaries.slice(0, -1).slice(-4) : []
  const finishedEarly = !!view && !!episode && view.finished && globalDay > episode.final_day
  const nameOf = (id: string | null) => {
    if (!id || !view) return id ?? '—'
    return view.employees.get(id)?.name ?? id
  }

  return (
    <section
      className={hot ? 'panel is-hot' : standIn ? 'panel is-standin' : 'panel'}
      onDragOver={(event) => {
        event.preventDefault()
        onDragOver()
      }}
      onDragLeave={onDragLeave}
      onDrop={(event) => {
        event.preventDefault()
        const file = event.dataTransfer.files[0]
        if (file) onDrop(file)
      }}
    >
      <header className="panel-head">
        <div>
          <p className="kicker">{eyebrow}</p>
          <h3>{title}</h3>
        </div>
        <div className="panel-meta">
          <span>{note}</span>
          <button type="button" className="texty" onClick={() => input.current?.click()}>
            Load JSONL
          </button>
          <input
            ref={input}
            type="file"
            accept=".jsonl,.json,text/plain"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) onDrop(file)
              event.target.value = ''
            }}
          />
        </div>
      </header>

      {!view || !episode ? (
        <p className="drop-hint">Drop an episodes.jsonl here.</p>
      ) : (
        <>
          <div className="metrics">
            <p className="v-read">
              <strong>{formatV(view.V)}</strong>
              <span>company value</span>
            </p>
            <p className="panel-day">
              {finishedEarly ? `Finished day ${String(episode.final_day).padStart(2, '0')}` : `Acting on day ${String(view.day).padStart(2, '0')}`}
            </p>
          </div>
          <ValueChart points={view.points} cursorDay={globalDay} />
          {view.showVerdict && (
            <p className={episode.correct ? 'verdict is-ok' : episode.end_reason === 'accused' ? 'verdict is-bad' : 'verdict'}>
              <b>
                {episode.end_reason === 'accused' ? (episode.correct ? 'Correct' : 'Wrong') : 'No accusation'}
              </b>
              <span>{formatScore(episode.score)}</span>
              <span>{nameOf(episode.accused)}</span>
            </p>
          )}
          <div className="canary-block">
            <p className="kicker">Canary recipients</p>
            {latest ? <CanaryCard canary={latest} view={view} /> : <p className="fine">No canary planted yet.</p>}
            {earlier.length > 0 && (
              <p className="earlier">
                {earlier.map((canary) => (
                  <span key={canary.id}>
                    d{canary.day} {canary.id}
                    {canary.leakedVariant ? ` · ${canary.leakedVariant} leaked` : ''}
                  </span>
                ))}
              </p>
            )}
          </div>
          <div className="leak-block">
            <p className="kicker">Leak feed</p>
            {view.leaks.length === 0 ? (
              <p className="fine">Nothing surfaced yet.</p>
            ) : (
              <ul>
                {view.leaks.slice(-4).reverse().map((leak) => (
                  <li key={`${leak.docId}-${leak.surfacedDay}`} className={leak.variant ? 'is-canary' : ''}>
                    <span>d{leak.surfacedDay}</span>
                    {leak.variant ? (
                      <b style={{ color: variantColor(leak.variant) }}>variant {leak.variant}</b>
                    ) : (
                      <b>ordinary</b>
                    )}
                    <span>{leak.title}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="tool-block">
            <p className="now">
              {highlight && view.current ? view.current.tool.replaceAll('_', ' ') : finishedEarly ? 'Holding' : view.current?.tool.replaceAll('_', ' ') ?? '—'}
            </p>
            <p className="now-sum">{highlight && view.current ? view.current.summary : view.current?.summary}</p>
            <ul>
              {view.tools.slice(-6).map((tool) => (
                <li key={tool.t} className={highlight && tool.t === view.current?.t ? 'is-now' : ''}>
                  <span>{tool.tool}</span>
                  <span>{tool.summary}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  )
}

function CanaryCard({ canary, view }: { canary: CanaryView; view: EpisodeView }) {
  return (
    <div>
      <p className="canary-title">
        <span style={{ color: 'var(--gold)' }}>{canary.id}</span> {canary.title}
      </p>
      {canary.groups.map((group) => (
        <div key={group.label} className="variant-row">
          <b style={{ background: group.color }}>{group.label}</b>
          <span className="dots" aria-hidden="true">
            {group.ids.map((id) => (
              <i key={id} style={{ background: group.color }} title={view.employees.get(id)?.name ?? id} />
            ))}
          </span>
          <span className="who-line">
            {group.ids.length > 6
              ? `${group.ids.length} staff`
              : group.ids.map((id) => shortName(view.employees.get(id)?.name ?? id)).join(' · ')}
            {group.label === canary.leakedVariant ? ' · leaked' : ''}
          </span>
        </div>
      ))}
    </div>
  )
}
