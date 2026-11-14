export type SectionMeta = { id: string; short: string }

export function Progress({
  sections,
  index,
  onJump,
}: {
  sections: SectionMeta[]
  index: number
  onJump: (index: number) => void
}) {
  return (
    <nav className="progress" aria-label="Sections">
      <div className="progress-track" aria-hidden="true">
        <span style={{ width: `${((index + 1) / sections.length) * 100}%` }} />
      </div>
      <ol>
        {sections.map((section, i) => (
          <li key={section.id}>
            <button
              type="button"
              aria-current={i === index ? 'step' : undefined}
              onClick={() => onJump(i)}
            >
              <i>{String(i + 1).padStart(2, '0')}</i>
              {section.short}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}
