import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

const dir = path.dirname(fileURLToPath(import.meta.url))

const BUNDLED = [
  'data/manifest.json',
  'results.json',
  'data/forge.json',
  'data/small-model.json',
  'data/runs/solver/medium/episodes.jsonl',
  'data/runs/heuristic/medium/episodes.jsonl',
]

function canaryBundledData(): Plugin {
  const virtual = 'virtual:canary-bundled'
  const resolved = '\0' + virtual
  return {
    name: 'canary-bundled-data',
    resolveId(source) {
      if (source === virtual) return resolved
      return null
    },
    load(source) {
      if (source !== resolved) return null
      const root = path.join(dir, 'public')
      const out: Record<string, string> = {}
      for (const rel of BUNDLED) {
        out[rel] = fs.readFileSync(path.join(root, rel), 'utf8')
      }
      const optional = 'data/runs/committed/gpt-5.5/episodes.jsonl'
      const optPath = path.join(root, optional)
      if (fs.existsSync(optPath) && fs.statSync(optPath).size > 0) {
        const text = fs.readFileSync(optPath, 'utf8').trim()
        if (text && !text.startsWith('Placeholder')) out[optional] = text
      }
      return `export default ${JSON.stringify(out)}`
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), canaryBundledData(), viteSingleFile()],
  build: {
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
  },
})
