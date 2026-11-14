# Canary Lab: one real Gemini run per role

Every row links a committed run and every number in it is read from that run's files by
`python -m canary.gemini.roles index` (nothing is typed by hand). Generated Sat 14 Nov 19:05 EET.
Dev seeds only for the two new roles: no judge world or judge mole is rendered or committed.

| Role | Committed run | Model (thinking) | Commit | Size | Headline (real numbers) |
|---|---|---|---|---|---|
| Frontier subject (the agent under test) | `results/gemini/ladder.json (+ ladder.md, ladder_episodes.jsonl.gz, ladder_ledger.jsonl.gz)` | gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon (minimal / low / medium / high (+ carbon model default, imported)) | `083726928a` | 134 episodes, 31 cells | gemini-4-carbon (default) reaches 66% of the solver on hard [95% CI 5%, 117%], n=10 |
| Analyst (Failure Atlas) | `results/gemini/atlas.json (+ atlas.md, atlas_charts/)` | long_context: gemini-4-carbon, cache: gemini-3.8-flash, embedding: gemini-embedding-2, batch: gemini-3.8-flash (model default) | `6826010` | 153 episodes, 792,862 tokens in one prompt | top failure mode "Premature Accusation on Sub-Threshold Posterior" = 61% of all solver regret; 461/470 quotes verbatim (98%); human agreement pending |
| Red-team swarm | `results/gemini/swarm.json (+ swarm.md, swarm_blackbox.json, swarm_control.json)` | gemini-3.8-flash, gemini-4-hydrogen, gemini-4-carbon (model default) | `50373a0566` | 35 attacks, 1225 tool calls | 0 verified exploits; best unjustified score hard +0.00 vs solver +0.60, medium +0.00 vs solver +0.75 |
| World-text renderer (demo/research layer, v1.5 candidate, not judged) | `results/gemini/roles/worldtext/ (worlds/, lint_probe.json, meta.json, ledger.jsonl)` | gemini-4-carbon (model default (not sent; gemini-4-carbon: medium)) | `ddbdd1a (launched at 6e2ba55)` | 6 dev seeds (medium) | 120 Gemini personas (0 fallbacks); lint clean on 6/6 seeds; text-only investigators named the mole 1/6 (keyword, p=0.37) and 0/6 (gemini-3.8-flash, p=1.00) vs fair bar 7%: no leak: lint.py clean, no text-only investigator above the fair bar |
| Adaptive mole (arena) | `results/gemini/roles/mole/ (episodes.jsonl per-day decisions, summary.json, meta.json, ledger.jsonl)` | gemini-4-carbon (model default (not sent; gemini-4-carbon: medium)) | `ddbdd1a (launched at 6e2ba55)` | 4 dev seeds x 2 investigators (medium) | vs solver: score +0.00 with the Gemini mole vs +0.63 with the default mole (paired -0.63), caught 0/4 vs 4/4, 48 leaks (1 of them canaries); vs heuristic: score -1.00 with the Gemini mole vs -1.00 with the default mole (paired +0.00), caught 0/4 vs 0/4, 6 leaks (4 of them canaries) |

The world-text renderer is a **demo/research layer (v1.5 candidate)**, not part of the judged environment: the judged
environment stays v1.4 and this layer does not change any score. Gemini both writes the office gossip and, as the
investigator, sees through it: on v1.5-candidate hard (dev seeds 0-9, OpenCode harness) the AfterQuery measurement has
gemini-4-carbon at 108% [96, 122] of the solver vs 61% [3, 104] on v1.4, same seeds (justSilas `docs/reports/CEO.md`,
`docs/reports/env.md`).

Not listed: the Mole Forge. Its committed hall of fame (data/forge/hall_of_fame_v1.*) was evolved with the **stub** mutator
(`canary.forge.evolve --mutator stub`), so there is no real Gemini Forge run to cite.

How the two new runs were made (`canary/gemini/roles.py`, every call through `canary.gemini.ledger`):
- **World-text renderer**: gemini-4-carbon writes personas, department culture and chat templates from public facts only
  (`canary.agents.world_builder.build_world_text`); every day of each dev episode is rendered and checked with
  `canary/text/lint.py`, `assert_no_truth`, the keyword text probe and an LLM text-only investigator, against the
  text probe's fair bar (the best accuracy the documented interview signal allows). Only correct/incorrect flags are stored.
- **Adaptive mole**: gemini-4-carbon plays the mole day by day (`canary.agents.mole_arena.LLMMole`, arena mode, never the
  judge path) against the reference solver and the heuristic on medium, respecting the env's p_leak gate; the same seeds
  are replayed with the default mole for a paired comparison. Investigator score: lower = the mole did better.
