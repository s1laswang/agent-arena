export type ToolResult = {
  ok: boolean
  data: Record<string, unknown>
  error: string | null
}

export type Step = {
  t: number
  day: number
  tool: string
  args: Record<string, unknown>
  result: ToolResult
}

export type Episode = {
  tier: string
  seed: number
  agent: string
  steps: Step[]
  score: number
  accused: string | null
  correct: boolean
  final_day: number
  end_reason: string
  meta: Record<string, unknown>
}

export type Employee = {
  id: string
  name: string
  dept: string
  role: string
  clearance?: number
}

export type RunRole = 'reference' | 'frontier' | 'stand-in' | 'baseline'

export type RunSpec = {
  id: string
  agent: string
  tier: string
  role: RunRole
  label: string
  file: string
  optional?: boolean
  standInFor?: string
  note?: string
}

export type Manifest = {
  version: number
  howToAdd?: string
  committedLayout?: {
    repoGlob?: string
    sitePath?: string
    example?: string
  }
  sample?: Record<string, unknown>
  pairing?: {
    leftRole?: string
    rightPrefer?: string
    rightFallback?: string
  }
  runs: RunSpec[]
}

export type GapBar = {
  id: string
  label: string
  agent: string
  score: number | null
  todo?: boolean
  pending?: boolean
  ci?: number | null
}

export type GapTier = {
  tier: string
  kicker?: string
  headline?: boolean
  bars: GapBar[]
}

export type ResultsFile = {
  todo?: boolean
  title?: string
  disclaimer?: string
  scale?: { min: number; max: number }
  tiers: GapTier[]
}

export type ForgeGen = {
  generation: number
  regret: number | null
  solverCatches?: boolean | null
  todo?: boolean
  illustrative?: boolean
}

export type ForgeFile = {
  todo?: boolean
  placeholder?: boolean
  illustrative?: boolean
  title?: string
  yLabel?: string
  xLabel?: string
  constraint?: string
  disclaimer?: string
  generations: ForgeGen[]
}

export type ScorePlate = {
  label: string
  detail?: string
  score: number | null
  todo?: boolean
}

export type TagRow = {
  tag: string
  label: string
  before: number | null
  after: number | null
  todo?: boolean
}

export type SmallModelFile = {
  todo?: boolean
  placeholder?: boolean
  title?: string
  model?: string
  method?: string
  disclaimer?: string
  before: ScorePlate
  after: ScorePlate
  tags: TagRow[]
}
