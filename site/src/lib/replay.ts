import type { Employee, Episode, Step } from './types'

const VARIANT_COLOR: Record<string, string> = {
  A: '#e0b15a',
  B: '#3ec4b2',
  C: '#e36d7a',
  D: '#b79bff',
  E: '#8eb4e8',
  F: '#e0a06a',
  G: '#d6d0c4',
  H: '#d27bba',
}

export function variantColor(label: string): string {
  const key = label.trim().toUpperCase()
  return VARIANT_COLOR[key] ?? VARIANT_COLOR.A!
}

export type Beat = {
  day: number
  leftCount: number
  rightCount: number
}

export function buildBeats(left: Episode, right: Episode): Beat[] {
  const days = new Set<number>()
  for (const step of left.steps) days.add(step.day)
  for (const step of right.steps) days.add(step.day)
  const ordered = [...days].sort((a, b) => a - b)
  const leftByDay = countByDay(left.steps)
  const rightByDay = countByDay(right.steps)
  const beats: Beat[] = []
  let leftTotal = 0
  let rightTotal = 0
  for (const day of ordered) {
    const leftN = leftByDay.get(day) ?? 0
    const rightN = rightByDay.get(day) ?? 0
    const n = Math.max(leftN, rightN, 1)
    for (let i = 1; i <= n; i += 1) {
      beats.push({
        day,
        leftCount: leftTotal + Math.min(i, leftN),
        rightCount: rightTotal + Math.min(i, rightN),
      })
    }
    leftTotal += leftN
    rightTotal += rightN
  }
  return beats
}

function countByDay(steps: Step[]): Map<number, number> {
  const map = new Map<number, number>()
  for (const step of steps) map.set(step.day, (map.get(step.day) ?? 0) + 1)
  return map
}

export type Point = { x: number; v: number }

export type CanaryGroup = { label: string; color: string; ids: string[] }

export type CanaryView = {
  day: number
  t: number
  id: string
  title: string
  groups: CanaryGroup[]
  leakedVariant: string | null
}

export type LeakView = {
  surfacedDay: number
  docId: string
  title: string
  variant: string | null
  canary: boolean
}

export type ToolLine = {
  t: number
  day: number
  tool: string
  ok: boolean
  summary: string
}

export type EpisodeView = {
  employees: Map<string, Employee>
  day: number
  V: number
  points: Point[]
  canaries: CanaryView[]
  leaks: LeakView[]
  tools: ToolLine[]
  accused: string | null
  showVerdict: boolean
  finished: boolean
  current: ToolLine | null
}

export function viewAt(episode: Episode, count: number): EpisodeView {
  const steps = episode.steps.slice(0, Math.max(0, Math.min(count, episode.steps.length)))
  const employees = new Map<string, Employee>()
  const planted: Omit<CanaryView, 'leakedVariant'>[] = []
  const points: Point[] = []
  const vSeen = new Map<number, number>()
  const leaks: LeakView[] = []
  let latestV = 1
  let accused: string | null = null
  let accuseSeen = false

  for (const step of steps) {
    const { ok, data } = step.result
    if (ok && step.tool === 'list_employees' && Array.isArray(data.employees)) {
      for (const raw of data.employees) {
        if (!raw || typeof raw !== 'object') continue
        const row = raw as Record<string, unknown>
        if (typeof row.id !== 'string') continue
        employees.set(row.id, {
          id: row.id,
          name: typeof row.name === 'string' ? row.name : row.id,
          dept: typeof row.dept === 'string' ? row.dept : '',
          role: typeof row.role === 'string' ? row.role : '',
          clearance: typeof row.clearance === 'number' ? row.clearance : undefined,
        })
      }
    }
    if (ok && typeof data.V === 'number' && Number.isFinite(data.V)) {
      latestV = data.V
      const n = vSeen.get(step.day) ?? 0
      vSeen.set(step.day, n + 1)
      points.push({ x: step.day + Math.min(0.85, n * 0.1), v: data.V })
    }
    if (ok && step.tool === 'plant_canary' && data && typeof step.args.assignment === 'object' && step.args.assignment) {
      const groups = new Map<string, string[]>()
      for (const [id, label] of Object.entries(step.args.assignment as Record<string, unknown>)) {
        if (typeof label !== 'string') continue
        const list = groups.get(label) ?? []
        list.push(id)
        groups.set(label, list)
      }
      planted.push({
        day: step.day,
        t: step.t,
        id: typeof data.canary_id === 'string' ? data.canary_id : `c${step.day}`,
        title: typeof step.args.doc_title === 'string' ? step.args.doc_title : 'Canary',
        groups: [...groups.entries()]
          .sort((a, b) => a[0].localeCompare(b[0]))
          .map(([label, ids]) => ({ label, color: variantColor(label), ids })),
      })
    }
    if (ok && step.tool === 'check_leak_feed' && Array.isArray(data.items)) {
      leaks.length = 0
      for (const raw of data.items) {
        if (!raw || typeof raw !== 'object') continue
        const item = raw as Record<string, unknown>
        leaks.push({
          surfacedDay: typeof item.surfaced_day === 'number' ? item.surfaced_day : step.day,
          docId: typeof item.doc_id === 'string' ? item.doc_id : '',
          title: typeof item.title === 'string' ? item.title : '',
          variant: typeof item.variant === 'string' ? item.variant : null,
          canary: typeof item.variant === 'string',
        })
      }
    }
    if (ok && step.tool === 'accuse') {
      accuseSeen = true
      accused =
        typeof step.args.employee === 'string'
          ? step.args.employee
          : typeof data.accused === 'string'
            ? data.accused
            : null
    }
  }

  if (!points.some((point) => point.x <= 1.001 && point.v >= 0.999)) {
    points.unshift({ x: 1, v: 1 })
  }

  const leakedByDoc = new Map<string, string>()
  for (const leak of leaks) {
    if (leak.variant) leakedByDoc.set(leak.docId, leak.variant)
  }
  const canaryIds = new Set(planted.map((canary) => canary.id))
  for (const leak of leaks) {
    if (canaryIds.has(leak.docId)) leak.canary = true
  }

  const canaries: CanaryView[] = planted.map((canary) => ({
    ...canary,
    leakedVariant: leakedByDoc.get(canary.id) ?? null,
  }))

  const currentStep = steps.at(-1) ?? null
  const toolDay = currentStep?.day ?? 1
  const tools = steps.filter((step) => step.day === toolDay).map(toLine)
  const finished = steps.length > 0 && steps.length === episode.steps.length
  const showVerdict = accuseSeen || (finished && episode.end_reason !== 'accused')

  return {
    employees,
    day: toolDay,
    V: latestV,
    points,
    canaries,
    leaks,
    tools,
    accused: accused ?? (showVerdict ? episode.accused : null),
    showVerdict,
    finished,
    current: tools.at(-1) ?? null,
  }
}

function toLine(step: Step): ToolLine {
  return {
    t: step.t,
    day: step.day,
    tool: step.tool,
    ok: step.result.ok,
    summary: summarize(step),
  }
}

function num(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—'
}

function len(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

export function summarize(step: Step): string {
  if (!step.result.ok) return step.result.error || 'rejected'
  const data = step.result.data
  const args = step.args
  switch (step.tool) {
    case 'status':
      return `V ${num(data.V)} · ${String(data.actions_left_today ?? '—')} actions left`
    case 'list_employees':
      return `${len(data.employees)} on the roster`
    case 'list_documents':
      return `${len(data.documents)} documents`
    case 'read_access_logs':
      return `${len(data.logs)} lines · days ${String(args.day_from ?? '?')}–${String(args.day_to ?? '?')}`
    case 'search_messages':
      return `${String(args.query ?? '')} · ${len(data.messages)} hits`
    case 'read_message':
      return String(args.id ?? 'message')
    case 'interview':
      return `${String(args.employee ?? '')} · ${String(args.topic ?? '').replaceAll('_', ' ')}`
    case 'plant_canary': {
      const assignment = args.assignment
      const ids = assignment && typeof assignment === 'object' ? Object.keys(assignment) : []
      const labels = assignment && typeof assignment === 'object' ? new Set(Object.values(assignment)) : new Set()
      return `${String(args.doc_title ?? 'Canary')} · ${ids.length} recipients · ${labels.size} variants`
    }
    case 'check_leak_feed':
      return `${len(data.items)} surfaced`
    case 'restrict_access':
      return `restrict ${String(args.employee ?? '')}`
    case 'unrestrict_access':
      return `restore ${String(args.employee ?? '')}`
    case 'advance_day':
      return data.episode_over
        ? `closed day ${String(data.closed_day ?? step.day)} · horizon`
        : `closed day ${String(data.closed_day ?? step.day)} · V ${num(data.V)}`
    case 'accuse':
      return `accuse ${String(args.employee ?? data.accused ?? '')}`
    default:
      return step.tool
  }
}

export const HORIZON = 14
