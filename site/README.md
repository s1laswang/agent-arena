# Canary dossier

A static, offline presentation for the Canary hackathon demo. Nine full-screen sections. Arrow keys move between them. No backend and no CDN: fonts and the sample episodes are bundled locally.

## Commands

From this directory:

```bash
npm ci
npm run dev        # http://127.0.0.1:5173
npm run build      # typecheck, then write dist/
npm run preview    # serve dist/ at http://127.0.0.1:4173
```

`npm run build` runs `tsc -b && vite build`. The Vite `base` is `./`, so `dist/` can be hosted at a subpath or opened as a folder.

### Offline, from the built folder

```bash
npm ci
npm run build
npm run preview
```

Or any static server pointed at `dist/`:

```bash
python3 -m http.server -d dist 4173
```

The build inlines the script, the stylesheet, and the fonts into `dist/index.html` (`vite-plugin-singlefile`), and copies `dist/data/` plus `dist/results.json` next to it. Opening `dist/index.html` directly (`file://`) still shows the nine sections, the bundled sample replay, and the charts, because those files are inside the page. A frontier file added after the build is picked up when `dist/` is served over HTTP (the page fetches it). `file://` cannot fetch a sibling file in every browser, so a post-build drop-in needs a static server, or a rebuild so the file is inlined too.

Nothing in the page requests a CDN. Fonts are `@fontsource` packages (Fraunces, IBM Plex Sans, IBM Plex Mono).

## Keys

Left / right, or up / down, move one section. Home and End jump to the ends. The bottom rail does the same.

On the live replay, Space plays and pauses, `[` and `]` (or `,` and `.`) step one tool call. Prev day / Next day jump the shared clock. If a seed menu or the scrubber is focused, arrows stay with that control.

## What the replay shows

Two episodes of the same seed, day by day: the reference solver on the left, and either a committed frontier run or the heuristic stand-in on the right.

The bundled sample is three medium dev seeds (0, 1, 2), produced with:

```bash
uv run --python 3.12 python -m canary.eval --agent solver --tier medium --seeds 3
uv run --python 3.12 python -m canary.eval --agent heuristic --tier medium --seeds 3
```

Dev seeds use the public world key, so those files are deterministic. They are a 3-seed sample, not the 40-seed judge table. The deck opens on the shared seed with the widest score gap.

The right-hand seat is the heuristic, labelled as a stand-in, until `data/runs/committed/gpt-5.5/episodes.jsonl` loads. Drag a jsonl onto either column, or use Load JSONL, to replace that side for the session.

## How to add a gpt-5.5 run

Committed frontier episodes land in the repo at `data/runs/committed/**/episodes.jsonl`. The reproduce tool reads that glob. This site does not scan it. The manifest is the list.

1. Copy the run to `site/public/data/runs/committed/gpt-5.5/episodes.jsonl`.
   The manifest already has an optional run with `"role": "frontier"`, `"agent": "gpt-5.5"`, and that `file`. A placeholder directory is in git; replace nothing but add the jsonl.
2. Rebuild (`npm run build`). If the file is present at build time it is inlined, so `file://` includes it.
   Or, after a build, copy the same jsonl to `dist/data/runs/committed/gpt-5.5/episodes.jsonl` and serve `dist/` over HTTP. Refresh. A parsed frontier file replaces the heuristic, and the stand-in banner comes down.
3. The deck groups lines by each episode's own `tier` and `seed`. One file can hold several tiers. The manifest `tier` field is only a hint.
4. Another agent (for example gpt-5.6-sol) needs another object in `runs`. Point `file` at `data/runs/committed/<agent>/episodes.jsonl` and set `"role": "frontier"`. Paths are relative to `site/public/`. If the committed run lives in a run-id folder such as `data/runs/committed/openai_gpt-5.5-medium-x/episodes.jsonl`, either copy it to the path above or set `file` to the nested path under `public/`.

`role` values the pairing understands:

| role | seat |
|---|---|
| `reference` | left |
| `frontier` | right, preferred |
| `stand-in` | right, only when no frontier file for that tier loaded |

`standInFor` is the model name the stand-in is holding the seat for. It is a label, not a second file.

## Data files

All paths are relative to `site/public/` (and, after a build, to `dist/`).

### `data/manifest.json`

```json
{
  "version": 1,
  "howToAdd": "string",
  "committedLayout": {
    "repoGlob": "data/runs/committed/**/episodes.jsonl",
    "sitePath": "data/runs/committed/<agent>/episodes.jsonl",
    "example": "data/runs/committed/gpt-5.5/episodes.jsonl"
  },
  "pairing": { "leftRole": "reference", "rightPrefer": "frontier", "rightFallback": "stand-in" },
  "runs": [
    {
      "id": "solver-medium",
      "agent": "solver",
      "tier": "medium",
      "role": "reference",
      "label": "Reference solver",
      "file": "data/runs/solver/medium/episodes.jsonl",
      "optional": false
    }
  ]
}
```

`file` is the path the loader fetches, then falls back to the copy inlined at build time. `optional: true` means a missing file is skipped instead of failing the page. Required files are the solver sample, the heuristic sample, `results.json`, `data/forge.json`, and `data/small-model.json`.

### `data/runs/.../episodes.jsonl`

One `EpisodeResult` per line, the same object `canary.eval` writes (`dataclasses.asdict`, one JSON object per line). A JSON array of those objects, or one pretty-printed object, is also accepted. This is the contract in `canary/types.py`:

| field | type | meaning |
|---|---|---|
| `tier` | string | `easy`, `medium`, or `hard` |
| `seed` | number | world seed |
| `agent` | string | `solver`, `heuristic`, `gpt-5.5`, … |
| `steps` | array | public tool calls, in order |
| `score` | number | company value if the accusation was right, `-1` if it was wrong, `0` if there was none |
| `accused` | string or null | employee id, or null |
| `correct` | boolean | |
| `final_day` | number | |
| `end_reason` | string | `accused`, `horizon`, `tool_cap`, or `error` |
| `meta` | object | ignored by the deck |

Each step:

| field | type | meaning |
|---|---|---|
| `t` | number | tool-call index |
| `day` | number | day of that call |
| `tool` | string | one of the 13 public tools |
| `args` | object | arguments the agent passed |
| `result` | object | `{ "ok": bool, "data": object, "error": string or null }` — exactly what the agent saw |

The replay reads these `result.data` shapes:

| tool | fields used |
|---|---|
| `list_employees` | `employees[]` of `{ id, name, dept, role }` |
| `status`, `advance_day` | `V` (company value), `day`, `closed_day` |
| `plant_canary` | `args.assignment` maps employee id → variant label (`A`, `B`, `C`, …), `args.doc_title`, `data.canary_id` |
| `check_leak_feed` | `items[]` of `{ surfaced_day, doc_id, title, variant? }` |
| `accuse` | `args.employee` |

Variant colours are fixed: A gold `#e0b15a`, B teal `#3ec4b2`, C rose `#e36d7a`, then D violet, E blue, F copper, G paper, H magenta. The same label is the same colour on both sides.

Anything the agent has not called yet is not shown. The leak feed is the latest `check_leak_feed` result up to the playhead, not the hidden ledger.

### `results.json`

Bar chart for the gap section. Every current number is a placeholder.

```json
{
  "todo": true,
  "title": "The gap",
  "scale": { "min": -1, "max": 1 },
  "disclaimer": "TODO. …",
  "tiers": [
    {
      "tier": "medium",
      "kicker": "Headline",
      "headline": true,
      "bars": [
        { "id": "solver", "label": "Reference", "agent": "solver", "score": 0.63, "todo": true },
        { "id": "frontier", "label": "Frontier", "agent": "gpt-5.5", "score": null, "todo": true, "pending": true }
      ]
    }
  ]
}
```

`score: null` with `pending: true` draws an empty bar. `todo: true` keeps the TODO mark. Set `todo` false on the file, and on each bar you replace, when the official judge table is in. The zero line sits at score 0 inside `scale`. Optional `ci` is accepted and ignored by the current chart.

The numbers shipped here are the README's expected means, copied so the chart has a shape. They are not a measurement from this build. Frontier cells are empty on purpose.

### `data/forge.json`

Mole Forge chart.

```json
{
  "todo": true,
  "placeholder": true,
  "illustrative": true,
  "title": "Mole Forge",
  "yLabel": "Regret",
  "xLabel": "Generation",
  "constraint": "A generation is kept only while the reference solver still catches the mole.",
  "disclaimer": "PLACEHOLDER. …",
  "generations": [
    { "generation": 0, "regret": 0.04, "solverCatches": true, "todo": true, "illustrative": true }
  ]
}
```

`regret` may be `null`. A null series draws an empty chart instead of a curve. While `illustrative` or `placeholder` is true, the curve is dashed and watermarked PLACEHOLDER. Replace the generations and set those flags false when the evolution log exists. Do not leave the illustrative numbers in once real generations are mixed in.

### `data/small-model.json`

Before / after plate and the regret-tag rows.

```json
{
  "todo": true,
  "placeholder": true,
  "model": "Qwen2.5-1.5B-Instruct",
  "method": "…",
  "disclaimer": "PLACEHOLDER. …",
  "before": { "label": "Before", "detail": "Base instruct model", "score": null, "todo": true },
  "after": { "label": "After", "detail": "LoRA on solver trajectories", "score": null, "todo": true },
  "tags": [
    { "tag": "premature_accusation", "label": "Premature accusation", "before": null, "after": null, "todo": true }
  ]
}
```

`score`, `before`, and `after` are numbers once the held-out eval exists, and `null` until then. Null renders as an em dash and a TODO chip, not as a fake improvement.

## Sections

1. Hook
2. The company — synthetic floor of Halcyon Metrics
3. How a canary trap works
4. Live replay
5. The gap — `results.json`
6. Why agents fail — the draft gap report's medium seed 5
7. Reward integrity — summary of `docs/EXPLOITS.md`
8. Mole Forge — `data/forge.json`
9. The small model — `data/small-model.json`
