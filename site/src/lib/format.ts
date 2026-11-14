export function formatScore(n: number, digits = 2): string {
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n).toFixed(digits)
  if (n < 0) return '−' + abs
  if (n > 0) return '+' + abs
  return (0).toFixed(digits)
}

export function formatV(n: number): string {
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length < 2) return name
  return `${parts[0]} ${parts[1]!.slice(0, 1)}.`
}

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.slice(0, 1).toUpperCase())
    .join('')
}
