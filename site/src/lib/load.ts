import bundled from 'virtual:canary-bundled'
import { parseEpisodes } from './episodes'
import type { Episode, ForgeFile, Manifest, ResultsFile, RunSpec, SmallModelFile } from './types'

export type DeckData = {
  manifest: Manifest
  results: ResultsFile
  forge: ForgeFile
  smallModel: SmallModelFile
  episodes: Record<string, Episode[]>
  missing: string[]
}

function assetUrl(rel: string): string {
  const base = new URL(import.meta.env.BASE_URL, window.location.href)
  return new URL(rel.replace(/^\//, ''), base).href
}

export async function loadText(rel: string): Promise<string> {
  if (window.location.protocol !== 'file:') {
    try {
      const res = await fetch(assetUrl(rel))
      if (res.ok) {
        const text = await res.text()
        if (!text.trimStart().startsWith('<') && !text.trimStart().startsWith('Placeholder')) return text
      }
    } catch {
      /* bundled copy below */
    }
  }
  const fallback = bundled[rel]
  if (fallback != null) return fallback
  throw new Error(`Missing ${rel}`)
}

function asManifest(raw: unknown): Manifest {
  if (!raw || typeof raw !== 'object' || !Array.isArray((raw as Manifest).runs)) {
    throw new Error('manifest.json needs a runs array')
  }
  return raw as Manifest
}

function asResults(raw: unknown): ResultsFile {
  if (!raw || typeof raw !== 'object' || !Array.isArray((raw as ResultsFile).tiers)) {
    throw new Error('results.json needs a tiers array')
  }
  return raw as ResultsFile
}

function asForge(raw: unknown): ForgeFile {
  if (!raw || typeof raw !== 'object' || !Array.isArray((raw as ForgeFile).generations)) {
    throw new Error('forge.json needs a generations array')
  }
  return raw as ForgeFile
}

function asSmall(raw: unknown): SmallModelFile {
  if (!raw || typeof raw !== 'object' || !Array.isArray((raw as SmallModelFile).tags)) {
    throw new Error('small-model.json needs tags')
  }
  return raw as SmallModelFile
}

export async function loadDeck(): Promise<DeckData> {
  const manifest = asManifest(JSON.parse(await loadText('data/manifest.json')))
  const results = asResults(JSON.parse(await loadText('results.json')))
  const forge = asForge(JSON.parse(await loadText('data/forge.json')))
  const smallModel = asSmall(JSON.parse(await loadText('data/small-model.json')))
  const episodes: Record<string, Episode[]> = {}
  const missing: string[] = []
  for (const run of manifest.runs) {
    try {
      episodes[run.id] = parseEpisodes(await loadText(run.file))
    } catch (err) {
      if (run.optional) missing.push(run.id)
      else throw err instanceof Error ? err : new Error(String(err))
    }
  }
  return { manifest, results, forge, smallModel, episodes, missing }
}

export type SidePack = {
  spec: RunSpec | null
  episodes: Episode[]
  standIn: boolean
  standInFor: string | null
}

export function pickSides(data: DeckData, tier: string): { left: SidePack; right: SidePack } {
  const loaded = data.manifest.runs.filter((run) => (data.episodes[run.id] ?? []).some((ep) => ep.tier === tier))
  const reference = loaded.find((run) => run.role === 'reference') ?? null
  const frontier = loaded.find((run) => run.role === 'frontier') ?? null
  const stand = loaded.find((run) => run.role === 'stand-in' || run.standInFor) ?? null
  const right = frontier ?? stand
  return {
    left: {
      spec: reference,
      episodes: reference ? (data.episodes[reference.id] ?? []).filter((ep) => ep.tier === tier) : [],
      standIn: false,
      standInFor: null,
    },
    right: {
      spec: right,
      episodes: right ? (data.episodes[right.id] ?? []).filter((ep) => ep.tier === tier) : [],
      standIn: !!right && right.role !== 'frontier',
      standInFor: right?.standInFor ?? null,
    },
  }
}
