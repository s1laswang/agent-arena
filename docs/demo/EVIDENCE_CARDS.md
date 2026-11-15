# Out-Think Gemini: Multimodal Evidence Cards Reference (`demo/out-think-gemini/evidence_cards.js`)

`demo/out-think-gemini/evidence_cards.js` packages verified `gemini-4-carbon` multimodal PNG runs into an offline, zero-network JavaScript bundle for **Out-Think Gemini: Pixel Detective Room**. It is built deterministically by `python -m canary.gemini.outthink_evidence_cards` (`--check` verified) and attaches `OUTTHINK_EVIDENCE_CARDS` plus 5 lookup helpers to `window`, `globalThis`, and CommonJS `module.exports`.

## Bundle Rollup (`OUTTHINK_EVIDENCE_CARDS.summary`)

- **Schema & Role:** `schema_version = 1`, `role = "multimodal_evidence"`, `model_id = "gemini-4-carbon"`
- **SDK Ingestion Path:** `google.genai.types.Part.from_bytes(mime_type='image/png')`
- **Verified Totals:** `17` runs, `100` cards (`94` on `v1.4` indexed in `by_world` + `6` historical `v1.3` cards in `belief-chart-forensics-carbon`), `226` vision API calls, `260` PNGs read, `$3.521048` USD
- **Token Totals (`summary.total_tokens`):** `486,594` input (`in`), `47,941` output (`out`), `206,845` thinking (`thinking`), `0` cached (`cached`)
- **World Coverage (`worlds_covered_v14`):** `27` `v1.4` worlds (`12` medium + `15` hard)

## Four Modalities and Detective Room Stations (`summary.by_modality` & `room_stations`)

| Modality | Station ID | Sprites (`prop` / `icon` / `analyst` / `badge`) | Runs | Cards | Calls | PNGs | Input Tok | Output Tok | Thinking Tok | Cost (USD) | Verified Headline Metrics |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `scan` | `scan_desk` | `desk` / `icon_memo` / `agent_low` / `icon_magnifier` | 6 | 30 | 156 | 156 | 297,024 | 20,133 | 9,420 | $0.889578 | `49/49` canary watermarks (`1.0`), `30/30` (`1.0`) mole accuracy vs `10/30` (`0.3333`) blind, `1.0` oracle score recovery (`880x620` PNGs) |
| `heatmap` | `soc_terminal` | `terminal` / `icon_log` / `agent_high` / `icon_correct` | 5 | 28 | 28 | 28 | 58,425 | 13,301 | 115,434 | $1.404200 | `27/28` (`0.9643`) top-1 mole, `28/28` (`1.0`) top-3 mole, `28/28` (`1.0`) decoy ID & trap avoidance vs `0/28` (`0.0`) naive (`1880x1020` medium, `2180x1660` hard; `agent_low` on `low` cards) |
| `dossier` | `dossier_board` | `evidence_board` / `icon_badge` / `agent_medium` / `icon_accuse` | 3 | 17 | 17 | 51 | 76,652 | 6,876 | 66,726 | $0.889324 | `3` PNGs per call (`badge_raster`, `leaked_memo_scans`, `org_canary_map`), `43/43` watermarks matched, `14/17` (`0.8235`) top-1 mole, `16/17` (`0.9412`) top-3 & decoy ID, `17/17` (`1.0`) trap avoidance vs `0/17` (`0.0`) single-image |
| `forensics` | `forensics_rack` | `server_rack` / `icon_brain` / `agent_xhigh` / `icon_coin` | 3 | 25 | 25 | 25 | 54,493 | 7,631 | 15,265 | $0.337946 | `25/25` (`1.0`) visual EV-threshold, `25/25` (`1.0`) exact stop/accuse day, `25/25` (`1.0`) hidden-bleed gap (`19` `v1.4` at `2208x2624` + `6` `v1.3` at `1984x1792`) |
| **Total** | **4 stations** | **CC0 manifest keys** | **17** | **100** | **226** | **260** | **486,594** | **47,941** | **206,845** | **$3.521048** | **All 260 PNGs carry SHA-256, byte length, pixel dimensions, and verbatim `gemini_quote`** |

## Verified Run Ledger (`OUTTHINK_EVIDENCE_CARDS.runs`, 17 Runs)

| Run Directory (`run_dir`) | Modality | Version | Thinking | Cards | PNGs | Calls | Cost (USD) | Commit |
|---|---|---|---|---:|---:|---:|---:|---|
| `memo-watermark-ablation-carbon` | `scan` | `v1.4` | `default` | 3 | 16 | 16 | $0.095448 | `8df685ee` |
| `memo-watermark-hard-ablation-carbon` | `scan` | `v1.4` | `low` | 5 | 18 | 18 | $0.092454 | `c75a9393` |
| `memo-watermark-hard-seeds10to14-carbon` | `scan` | `v1.4` | `default` | 5 | 39 | 39 | $0.235082 | `898dbbb4` |
| `memo-watermark-hard-seeds5to9-carbon` | `scan` | `v1.4` | `default` | 5 | 25 | 25 | $0.149770 | `726f9de0` |
| `memo-watermark-med-seeds6to11-carbon` | `scan` | `v1.4` | `default` | 6 | 21 | 21 | $0.127808 | `85855aff` |
| `scanned-evidence-ablation-carbon` | `scan` | `v1.4` | `low` | 6 | 37 | 37 | $0.189016 | `48baa20e` |
| `access-heatmap-carbon` | `heatmap` | `v1.4` | `default` | 3 | 3 | 3 | $0.055460 | `62ea18ba` |
| `access-heatmap-hard-carbon` | `heatmap` | `v1.4` | `default` | 3 | 3 | 3 | $0.090356 | `933f5183` |
| `access-heatmap-v14-high-s8to11-carbon` | `heatmap` | `v1.4` | `high` | 6 | 6 | 6 | $0.916102 | `c89f0fc1` |
| `access-heatmap-v14-low-s8to11-carbon` | `heatmap` | `v1.4` | `low` | 6 | 6 | 6 | $0.076122 | `c89f0fc1` |
| `access-heatmap-v14-sweep-carbon` | `heatmap` | `v1.4` | `default` | 10 | 10 | 10 | $0.266160 | `b40e5c8d` |
| `multi-image-dossier-carbon` | `dossier` | `v1.4` | `default` | 5 | 15 | 5 | $0.174376 | `5ee07419` |
| `multi-image-dossier-med6to8-hard5to7-carbon` | `dossier` | `v1.4` | `default` | 6 | 18 | 6 | $0.330920 | `a6b5a80e` |
| `multi-image-dossier-v14-expanded-carbon` | `dossier` | `v1.4` | `default` | 6 | 18 | 6 | $0.384028 | `1c51dca7` |
| `belief-chart-forensics-carbon` | `forensics` | `v1.3` | `default` | 6 | 6 | 6 | $0.055224 | `42341129` |
| `carbon-trajectory-forensics` | `forensics` | `v1.4` | `default` | 7 | 7 | 7 | $0.105996 | `44b700f1` |
| `carbon-trajectory-forensics-v14-expanded` | `forensics` | `v1.4` | `default` | 12 | 12 | 12 | $0.176726 | `c89f0fc1` |

## World Coverage (`OUTTHINK_EVIDENCE_CARDS.by_world`, 27 `v1.4` Worlds)

`by_world` indexes all `94` `v1.4` cards across `27` world keys (`12` medium + `15` hard), asserting zero ground-truth conflicts across modalities per world (`true_mole` and `true_decoy` agree across every modality covering that seed). The `6` historical `v1.3` cards in `belief-chart-forensics-carbon` remain accessible via `cards`, `by_modality.forensics`, and `listOutthinkEvidenceCards({ run_dir: "belief-chart-forensics-carbon" })`.

- **Medium Keys (`12`):** `medium/0`, `medium/1`, `medium/2`, `medium/3`, `medium/4`, `medium/5`, `medium/6`, `medium/7`, `medium/8`, `medium/9`, `medium/10`, `medium/11`
- **Hard Keys (`15`):** `hard/0`, `hard/1`, `hard/2`, `hard/3`, `hard/4`, `hard/5`, `hard/6`, `hard/7`, `hard/8`, `hard/9`, `hard/10`, `hard/11`, `hard/12`, `hard/13`, `hard/14`
- **Per-Modality World Span:**
  - `scan` (`27` worlds, `30` `v1.4` cards): all `27` keys (`medium/0`..`medium/11`, `hard/0`..`hard/14`; `2` cards each on `medium/3`, `medium/4`, `medium/5`)
  - `heatmap` (`22` worlds, `28` `v1.4` cards): `medium/0`..`medium/9` and `hard/0`..`hard/11` (`2` paired `low` + `high` cards each on `medium/8`, `medium/9`, `hard/8`, `hard/9`, `hard/10`, `hard/11`, with `primary_card_ids.heatmap` selecting `high`)
  - `dossier` (`17` worlds, `17` `v1.4` cards): `medium/0`..`medium/8` and `hard/0`..`hard/7` (`1` card per world)
  - `forensics` (`14` `v1.4` worlds, `19` `v1.4` cards): `medium/1`, `medium/2`, `medium/3`, `medium/5`, `medium/6`, `medium/7`, `medium/8`, `medium/9`, `hard/4`, `hard/6`, `hard/7`, `hard/8`, `hard/9`, `hard/11` (`2` cards each on `medium/1`, `medium/5`, `medium/7`, `medium/8`, `hard/6`)
- **Modality Breadth Tiers:**
  - **4 modalities (`10` worlds):** `medium/1`, `medium/2`, `medium/3`, `medium/5`, `medium/6`, `medium/7`, `medium/8`, `hard/4`, `hard/6`, `hard/7`
  - **3 modalities (`11` worlds):** `scan + heatmap + dossier` on `medium/0`, `medium/4`, `hard/0`, `hard/1`, `hard/2`, `hard/3`, `hard/5` (`7` worlds); `scan + heatmap + forensics` on `medium/9`, `hard/8`, `hard/9`, `hard/11` (`4` worlds)
  - **2 modalities (`1` world):** `scan + heatmap` on `hard/10`
  - **1 modality (`5` worlds):** `scan` on `medium/10`, `medium/11`, `hard/12`, `hard/13`, `hard/14`

## Paired Low-vs-High Thinking Comparison on `s8..11`

On `6` `v1.4` worlds (`medium/8`, `medium/9`, `hard/8`, `hard/9`, `hard/10`, `hard/11`), `gemini-4-carbon` evaluated identical 3-panel SOC raster PNGs at commit `c89f0fc1edbd01af0fef76a42231feab5b2f165f` under `thinking_level = "low"` (`access-heatmap-v14-low-s8to11-carbon`) and `thinking_level = "high"` (`access-heatmap-v14-high-s8to11-carbon`):

- **Aggregate Calibration (`summary.by_modality.heatmap.thinking_calibration`):**
  - `low`: `1,983` thinking tokens (`$0.076122` USD, `75.485s` latency), `6/6` top-1 mole & decoy, Brier `0.002117`, ECE `0.025333`
  - `high`: `85,629` thinking tokens (`$0.916102` USD, `925.638s` latency), `6/6` top-1 mole & decoy, Brier `0.000254` (`8.33x` lower, `-88.0%`), ECE `0.012667` (`2.0x` lower, `-50.0%`)

| World Key | True Mole | Framed Decoy | Low Tok | High Tok | Low Conf | High Conf | Low Brier | High Brier | Low Cost (USD) | High Cost (USD) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `medium/8` | `e02` | `e01` | 295 | 10,390 | 0.990 | 0.990 | 0.000100 | 0.000100 | $0.011072 | $0.112762 |
| `medium/9` | `e15` | `e13` | 0 | 14,262 | 0.990 | 0.990 | 0.000100 | 0.000100 | $0.007852 | $0.151542 |
| `hard/8` | `e06` | `e04` | 0 | 11,589 | 0.999 | 0.999 | 0.000001 | 0.000001 | $0.010342 | $0.126382 |
| `hard/9` | `e08` | `e31` | 0 | 19,243 | 0.890 | 0.970 | 0.012100 | 0.000900 | $0.010272 | $0.202542 |
| `hard/10` | `e10` | `e00` | 0 | 15,857 | 0.999 | 0.995 | 0.000001 | 0.000025 | $0.010122 | $0.169522 |
| `hard/11` | `e09` | `e32` | 1,688 | 14,288 | 0.980 | 0.980 | 0.000400 | 0.000400 | $0.026462 | $0.153352 |

Each paired world exposes `by_world[world_key].thinking_comparison` with keys `low_card_id`, `high_card_id`, `low_thinking_tokens`, `high_thinking_tokens`, `low_confidence`, `high_confidence`, `low_brier_score`, and `high_brier_score`.

## Helper Functions (`window` / `globalThis` / `module.exports`)

| Function Signature | Accepted Inputs | Return Value |
|---|---|---|
| `getOutthinkEvidenceCard(cardId)` | Exact `card_id` string (trimmed, e.g. `"scan:scanned-evidence-ablation-carbon:medium:0"`) | Matching card object from `OUTTHINK_EVIDENCE_CARDS.cards`, or `null` if not found / non-string |
| `getOutthinkWorldEvidence(caseOrTier, seed)` | `(tier, seed)` pair (`("hard", 8)`), canonical `"medium/3"`, delimited string (`"medium\|3"`, `"medium_3"`, `"medium-3"`), trajectory path (`"gemini-4-carbon/high/hard/8"`, taking the trailing two segments), or case object (`{ world_key }`, `{ tier, seed }`, `{ difficulty, worldSeed }`, `{ id }`) | World index entry from `OUTTHINK_EVIDENCE_CARDS.by_world[key]`, or `null` |
| `getOutthinkEvidenceForCase(caseOrTier, seed, modality)` | Same `caseOrTier` + `seed` inputs as `getOutthinkWorldEvidence`, plus optional `modality` (`"scan"`, `"heatmap"`, `"dossier"`, `"forensics"`, case-insensitive) | When `modality` is omitted / `null` / `""`, returns the `by_world` entry; otherwise resolves `worldEntry.primary_card_ids[modality]` via `getOutthinkEvidenceCard` (or `null` if unavailable) |
| `listOutthinkEvidenceCards(filter)` | Optional filter object supporting `{ modality, tier, seed, thinking_level, run_dir }` (`modality`, `tier`, `thinking_level` case-insensitive; `seed` numeric equality; `run_dir` exact string) | Shallow array copy of matching card objects (`100` cards when `filter` is omitted) |
| `listOutthinkEvidenceStations()` | None | Shallow array copy of the `4` station specs in `OUTTHINK_EVIDENCE_CARDS.room_stations` (`scan_desk`, `soc_terminal`, `dossier_board`, `forensics_rack`) |

## Pre-Decision vs Post-Reveal Fields (Spoiler Hygiene)

During active investigation (before the player locks in an accusation), UI components must only display provenance, room station metadata, compute budgets, and non-identifying document/image descriptors. All suspect IDs (`e00`..`e39`), oracle truth fields, model suspect rankings, and post-episode outcome prose are strictly post-reveal.

| Phase | Object Scope | Permitted Fields |
|---|---|---|
| **Pre-Decision (Active Investigation)** | Bundle & Stations | `schema_version`, `role`, `model_id`, `part_ingestion`, `summary`, `room_stations[]` (`station_id`, `modality`, `label`, `prop_sprite`, `icon_sprite`, `analyst_sprite`, `badge_sprite`, `card_count`, `images_read`, `summary_line`) |
| **Pre-Decision (Active Investigation)** | `by_world[wk]` | `world_key`, `pipe_key`, `tier`, `seed`, `modalities`, `card_ids`, `primary_card_ids`, `cards_by_modality`, `thinking_comparison.{low_card_id, high_card_id, low_thinking_tokens, high_thinking_tokens}` |
| **Pre-Decision (Active Investigation)** | `cards[i]` Envelope & Usage | `card_id`, `modality`, `subrole`, `station_id`, `sprite_key`, `prop_sprite_key`, `analyst_sprite_key`, `tier`, `seed`, `world_key`, `pipe_key`, `tiers_version`, `model_id`, `thinking_level`, `run_dir`, `ledger_run_id`, `commit`, `timestamp`, `n_images_read`, `episode_index`, `usage` (`calls`, `in`, `out`, `thinking`, `cached`, `cost_usd`, `latency_s`) |
| **Pre-Decision (Active Investigation)** | `cards[i].images[]` & Non-Spoiler Labels | `kind`, `path`, `sha256`, `bytes`, `size`, `finding.title`; for `scan` / `dossier` when gated to `day_surfaced <= current_day`: `doc_id`, `day_surfaced`, `predicted_variant`, `finding.decoded_watermarks[].{doc_id, day_surfaced, predicted_variant}`, `finding.decoded_leaked_canaries[].{doc_id, variant}` |
| **Post-Reveal Only (After Accusation)** | `by_world[wk]` | `true_mole`, `true_decoy`, `thinking_comparison.{low_confidence, high_confidence, low_brier_score, high_brier_score}` |
| **Post-Reveal Only (After Accusation)** | `cards[i].ground_truth` | All keys: `true_mole`, `true_decoy`, `true_mole_dept`, `true_decoy_dept`, `accused_employee`, `actual_accuse_day`, `episode_correct`, `episode_score`, `accused_below_ev_threshold`, `hidden_bleed_gap_present` |
| **Post-Reveal Only (After Accusation)** | `cards[i].images[]` & `cards[i].finding` | `images[].{expected_variant, exact_match}`, `finding.decoded_watermarks[].{expected_variant, exact_match}`, `badge`, `headline`, `gemini_quote`, `predicted_mole`, `top_suspect_ids`, `predicted_decoy`, `suspected_decoy_ids`, `suspect_department`, `naive_trapped_id`, `image1_only_trap_pick`, `mole_correct`, `top3_mole_hit`, `decoy_correct`, `avoided_framing_trap`, `confidence`, `brier_score`, `ablation`, `memo_scans_matched`, `memo_scans_total`, `source_agent`, `cohort`, `primary_failure_pattern`, `estimated_accuse_day`, `actual_accuse_day`, `threshold_match`, `day_exact`, `bleed_gap_match`, `entropy_lag_match`, `outcome_pattern_match` |
