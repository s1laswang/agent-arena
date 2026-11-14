import type { ReactNode } from 'react'
import { Mark } from './Mark'

export function Frame({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return (
    <div className="section flex h-full min-h-0 flex-col">
      <header className="section-head flex shrink-0 items-baseline justify-between gap-4">
        <span className="idx">{String(index).padStart(2, '0')}</span>
        <h2>{title}</h2>
        <span className="brand">
          <Mark size={16} />
          Canary
        </span>
      </header>
      <div className="section-body min-h-0 flex-1">{children}</div>
    </div>
  )
}
