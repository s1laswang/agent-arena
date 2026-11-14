# PLAN: Canary, the combined team entry (AfterQuery "Break the Agent")

Owner: Arena CEO (Claude), with Silas. Updated Sat 14 Nov ~15:00 Helsinki. **Aligned with `docs/IDEAS.md`** (the team decisions from the 14 Nov brainstorm; notes in `docs/meetings/2026-11-14-mole-company-simulation.md`) and with `~/junction-aimo-team/FLEET-CONTEXT.md` (Momin's Gemini fleet). Final submission: **Sun 15 Nov 10:00**. The detailed agent briefs are in `docs/agents/NEXT-LEVEL.md`; the history of every decision is in `docs/reports/CEO.md`.

## The idea
A fictional company has a **mole** leaking secrets, and every leak costs company value V. The agent under test is the **head of security**. It reads logs and messages, interviews staff, plants **canary documents** (different variants to different groups), watches a **delayed, noisy leak feed**, can restrict access, and must **accuse exactly once**. Scoring: correct = V left, wrong = −1, none = 0. The **reference** is a Bayesian canary-trap solver that sees only what the agent sees. Rules are frozen at **v1.4** (8f87ed1); **v1.5** (human-biased employees: rumours, grudges, authority posts, misforwards, a mole that seeds rumours) is a gated candidate.

**The measured failure we sell:** frontier agents never say "I don't know". They accuse at 18–45% certainty when the stated break-even says abstaining (0) beats a likely −1, and they ignore leak delays. The **skill ladder** shows those two skills (the EV accusation rule and delay reasoning) are exactly what decides the game.

## Status vs the rubric (CEO estimate ≈ 79/100; bake-off 2 gave 70 before the latest work)
| Criterion | Now | Evidence | Missing |
|---|---|---|---|
| Gap (30) | ~17 | v1.2 gpt-5.5 86–87%; v1.3 Codex 55% medium / 106% hard; v1.4 gemini-4-carbon OpenCode hard 58% (n=9, CI to 107%); Harbor judge path (6 tasks, one run each): gemini-4-carbon 0.50 vs oracle 0.76, below on 6/6 (paired diff 0.25, 95% t-interval [−0.07, +0.58]; sign test p = 0.03 two-sided) | gemini-4-carbon v1.4 at n ≥ 30 per tier with a CI excluding parity (running) |
| Difficulty (30) | ~25 | premature accusation ≈ 97% of tagged loss; no agent ever abstains; skill ladder; rules all in the instructions | hint ablations, human playtests |
| Integrity (25) | ~23 | anti-cheat battery in `make reproduce` (13 probes, stop-early ladder = 0, control, 299 replays); `make hunt` = 0; real Harbor boot, isolation 11/11 | Harbor cheat-solution run; an external judge hunt on the final tip |
| Craft (15) | ~14 | `make reproduce` in seconds, keyless; version-grouped replay; CI; browser game identical to Python; 571 tests | final refresh on the submit commit |

## Who builds what (no duplication)
| Lane | Owner | Branch |
|---|---|---|
| Rules, solver, skill ladder, v1.5 bias layer | HEAD-ENV (Claude) | `justSilas-env2`, `justSilas-v15` |
| Frontier measurement: gemini-4-carbon headline, v1.5 spot check | CEO measurement engineer (Claude) | `justSilas-gemini` |
| Anti-cheat battery (design: **Vaishnav**) | HEAD-INTEGRITY (Claude) | `justSilas-integrity2` |
| RL mole (light CPU + GRPO LLM mole), hint ablations, Forge (owner: **Momin**) | HEAD-AGENTS (Claude) + Momin | `justSilas-agents2` |
| Small investigator v2 (tiebreaker), GRPO GPU jobs | HEAD-FR8 (Claude) | `justSilas-fr8` |
| Gemini ladder / atlas (failure analyst) / swarm (red team) / gateway | Gemini CEO (Claude) | `gemini-track` (PR 1 by 19:30) |
| Browser game + video + research grounding | **Ivar** (+ the game build already merged) | `game/` |
| Pitch, decisions, presenting | **Silas** | |
| **Momin's fleet** (afterquery team, `fr8/afterquery/*` on freighter; `sleeper/*` + `momin` on GitHub) | Momin's fleet leads | see below |

### Momin's fleet: proposed lanes (for Silas/Momin to set on the board; the CEO does NOT touch fleet files)
To avoid duplicating the Claude org, the fleet's **afterquery team** takes the IDEAS.md weak points that need breadth, not core-code changes:
1. **More frontier families on paired v1.4 seeds** (weak point 1), using Momin's runners: a `claude -p` seat, gemini-3.5-flash, other available models. Paired with the solver, labelled REAL with model id and commit; the gemini-4-carbon headline stays with the CEO engineer.
2. **Research grounding** (weak point 4): sourced papers on organisational bias and real company-failure and insider-leak cases → `docs/research-biases.md`, for Ivar's video and the v1.5 instructions.
3. **Large exploit sweeps on v1.4 and v1.5** (Momin's 265k-style random search plus his cheat corpus), with findings reported to HEAD-INTEGRITY and the CEO, never patched by the fleet.
4. **The office replay dashboard with the "Fooled" moment** for Canary episodes (demo; for Ivar).

It does **not** change `canary/env.py`, `rules.py`, `solver/`, `reproduce.py` or `harbor/`; anything there goes as a PR reviewed by the CEO. The fleet's **gemini team** coordinates with the Gemini CEO.

### Which fleet / Sleeper outputs merge into the Canary base
| From | Merge? | Why |
|---|---|---|
| Momin's frontier runners (`claude -p` seat, Gemini thought-signature handling, **cache + byte-identical offline replay with provenance labels**) | **Yes** | more model families; judges can replay Gemini runs without a key |
| Cheat corpus + sweeps (`redteam/` on `momin`) | **Yes**, via HEAD-INTEGRITY | widens the anti-cheat battery |
| Office replay dashboard ("Fooled" moment) | **Yes**, into the demo/game | best-overall video |
| Failure analysis tied to ledger actions | Partly | overlaps Atlas (Gemini CEO); take the format |
| Sleeper world, verifier, leak-encoding detector | **No** | different environment; encodings don't apply to Canary's document leaks |

## Timeline
| Time | What |
|---|---|
| 16:52 | **Gate A:** gemini-4-carbon v1.4 interim; v1.5 numbers (done: the solver is unaffected, only chatter-trusting policies drop); RL mole held-out; FR8 job status |
| 19:30 | Gemini CEO PR 1 |
| 19:40 | gemini-4-carbon v1.5 hard spot check (seeds 0–9) |
| **20:00** | **Gate B:** ship or drop v1.5; **feature freeze** |
| 20:00–02:00 | Final judged runs (Gemini n ≥ 30 per tier), the Harbor cheat run, investigator v2 eval (~22:00), README/results refresh |
| 02:00–06:00 | Video, game deploy, Grok bake-off 3, pitch |
| 06:00–09:00 | Dry runs |
| **09:30** | **Submit** |

## Questions for Silas
1. **Fleet lanes:** OK to propose the four afterquery-fleet lanes above to Momin (he edits the board; I won't)?
2. **Fleet branches:** OK for Momin's fleet to push `fr8/afterquery/*` to GitHub and open PRs into `justSilas` for CEO review?
3. **Browser game publishing:** GitHub Pages (private repo, may need a paid plan), Vercel, or local only?
4. **Main branch:** rename `main` → `archive/sleeper-main` and make `justSilas` the submission branch?
