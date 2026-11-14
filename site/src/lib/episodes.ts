import type { Episode, Step, ToolResult } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export function unwrapResult(result: unknown): ToolResult {
  if (!isRecord(result)) return { ok: false, data: {}, error: null }
  if (isRecord(result.data) || 'ok' in result || 'error' in result) {
    return {
      ok: result.ok !== false,
      data: isRecord(result.data) ? result.data : {},
      error: typeof result.error === 'string' ? result.error : null,
    }
  }
  return { ok: true, data: result, error: null }
}

function looksLikeEpisode(value: unknown): boolean {
  return isRecord(value) && (Array.isArray(value.steps) || ('seed' in value && 'agent' in value))
}

function coerceStep(raw: unknown, index: number): Step {
  if (!isRecord(raw)) throw new Error(`Step ${index} is not an object`)
  const args = isRecord(raw.args) ? raw.args : {}
  return {
    t: typeof raw.t === 'number' ? raw.t : index,
    day: typeof raw.day === 'number' ? raw.day : 1,
    tool: typeof raw.tool === 'string' ? raw.tool : 'unknown',
    args,
    result: unwrapResult(raw.result),
  }
}

function coerceEpisode(raw: unknown, index: number): Episode {
  if (!isRecord(raw)) throw new Error(`Episode ${index + 1} is not an object`)
  if (!Array.isArray(raw.steps)) throw new Error(`Episode ${index + 1} has no steps array`)
  const steps = raw.steps.map((step, i) => coerceStep(step, i)).sort((a, b) => a.t - b.t)
  return {
    tier: typeof raw.tier === 'string' ? raw.tier : 'unknown',
    seed: typeof raw.seed === 'number' ? raw.seed : Number(raw.seed),
    agent: typeof raw.agent === 'string' ? raw.agent : 'unknown',
    steps,
    score: typeof raw.score === 'number' ? raw.score : Number(raw.score ?? 0),
    accused: typeof raw.accused === 'string' ? raw.accused : null,
    correct: raw.correct === true,
    final_day: typeof raw.final_day === 'number' ? raw.final_day : steps.at(-1)?.day ?? 0,
    end_reason: typeof raw.end_reason === 'string' ? raw.end_reason : 'unknown',
    meta: isRecord(raw.meta) ? raw.meta : {},
  }
}

export function parseEpisodes(text: string): Episode[] {
  const trimmed = text.replace(/^\uFEFF/, '').trim()
  if (!trimmed) throw new Error('File is empty')
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed) as unknown
      const records = Array.isArray(parsed) ? parsed : [parsed]
      if (records.length > 0 && looksLikeEpisode(records[0])) {
        return records.map((record, i) => coerceEpisode(record, i))
      }
    } catch (err) {
      if (trimmed.startsWith('[')) {
        throw new Error(err instanceof Error ? err.message : 'Could not parse JSON array of episodes')
      }
    }
  }
  const lines = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('#'))
  if (lines.length === 0) throw new Error('No episode lines')
  return lines.map((line, i) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(line)
    } catch {
      throw new Error(`Line ${i + 1} is not valid JSON`)
    }
    return coerceEpisode(parsed, i)
  })
}

export function episodeFor(episodes: Episode[], tier: string, seed: number): Episode | null {
  return episodes.find((episode) => episode.tier === tier && episode.seed === seed) ?? null
}

export function tiersIn(episodes: Episode[]): string[] {
  const order = ['easy', 'medium', 'hard']
  const found = new Set(episodes.map((episode) => episode.tier))
  return [...found].sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    if (ia === -1 && ib === -1) return a.localeCompare(b)
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
}

export function contrastScore(left: Episode, right: Episode): number {
  let score = Math.abs(left.score - right.score)
  if (left.correct !== right.correct) score += 1
  if (left.correct && !right.correct) score += 0.5
  if (left.final_day + 3 < right.final_day) score += 0.25
  return score
}

export function bestSeed(seeds: number[], left: Episode[], right: Episode[], tier: string): number | null {
  let best: number | null = null
  let bestScore = -Infinity
  for (const seed of seeds) {
    const a = episodeFor(left, tier, seed)
    const b = episodeFor(right, tier, seed)
    if (!a || !b) continue
    const value = contrastScore(a, b)
    if (value > bestScore) {
      bestScore = value
      best = seed
    }
  }
  return best ?? seeds[0] ?? null
}
