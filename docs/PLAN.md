# PLAN: Canary, the combined team entry (AfterQuery "Break the Agent")

Owner: Arena CEO (Claude), with Silas. Updated Sat 14 Nov ~19:40 Helsinki against the official rubric in `~/junction-aimo-team/JUDGING.md`; the point-by-point improvement plan is `docs/PLAN-95.md`. **Aligned with `docs/IDEAS.md`** (the team decisions from the 14 Nov brainstorm; notes in `docs/meetings/2026-11-14-mole-company-simulation.md`) and with `~/junction-aimo-team/FLEET-CONTEXT.md` (Momin's Gemini fleet). Final submission: **Sun 15 Nov 10:00**. The detailed agent briefs are in `docs/agents/NEXT-LEVEL.md`; the history of every decision is in `docs/reports/CEO.md`.

## The idea
A fictional company has a **mole** leaking secrets, and every leak costs company value V. The agent under test is the **head of security**. It reads logs and messages, interviews staff, plants **canary documents** (different variants to different groups), watches a **delayed, noisy leak feed**, can restrict access, and must **accuse exactly once**. Scoring: correct = V left, wrong = −1, none = 0. The **reference** is a Bayesian canary-trap solver that sees only what the agent sees. Rules are frozen at **v1.4** (8f87ed1); **v1.5** (human-biased employees: rumours, grudges, authority posts, misforwards, a mole that seeds rumours) is a gated candidate.

**The measured failure we sell:** frontier agents never say "I don't know". They accuse at 18–45% certainty when the stated break-even says abstaining (0) beats a likely −1, and they ignore leak delays. The **skill ladder** shows those two skills (the EV accusation rule and delay reasoning) are exactly what decides the game.

## Scoring checklist (official AfterQuery rubric, 100 pts; CEO estimate now ≈ 86, target ≈ 95)
Judges' procedure: a 10-min demo, then a rerun with **Harbor + OpenCode over MCP**: our reference run, 3 agent runs, do-nothing, stop-early, and a 15-min exploit hunt. Tiebreak: a small model improving after training on env experience.

| # | Rubric line (verbatim intent) | Pts | Now | Evidence a judge can open | Status / owner |
|---|---|---|---|---|---|
| G1 | Frontier agent **consistently** below a reference run we demonstrate | 30 | – | **Gap not established.** In-process bake-off, rules v1.4, paired seeds, n=10 per tier (21:26): gemini-4-carbon matches or beats the solver. Medium solver +0.734±0.050 vs carbon +0.680±0.085. Hard solver +0.433±0.324 vs carbon +0.509±0.136. Smaller Gemini models sat below the solver. The ladder's imported hard cell (66% [5%, 117%], n=10) includes parity, and the Harbor 6-task demo (0.50 vs 0.76, CI includes 0) is not this result | ☐ not a demonstrated gap |
| G2 | Reproducible **across repeated runs** | (in G) | | `results/harbor/rehearsal/`: 3 runs × 10 hard tasks via Harbor + OpenCode, with the oracle + both baselines | ☐ A2, after 20:00 |
| G3 | The judges' rerun lands on the gap tier | (in G) | | `python harbor/build.py` defaults to hard, judge seeds 900000–900009, fixed before any run | ☐ A1, harness engineer, 20:30 |
| G4 | Not one model's quirk | (in G) | | gemini-3.6-flash (requested as 3.5-flash) on hard is within the CI of the solver, n=6: 97% [76%, 126%] medium thinking and 106% [82%, 145%] high (`results/gemini/ladder.md`); Codex gpt-5.5 v1.3 rows | ☐ A4 |
| D1 | Agent's main mistakes explained and tied to task decisions | 30 | 26 | `docs/reports/failure_gallery.md`: every lost point tagged to a ledger step and the solver posterior; skill ladder `results/skill_ladder_v1.4.md` | ☐ B2 Gemini CEO, 00:30 |
| D2 | Info and tools to do better are available (causal) | (in D) | | hint ablation `--hint ev_delay` (n=20 paired hard): one sentence restating the instruction's own break-even moves Gemini toward the solver | ☐ B1, measurement engineer + head-agents |
| D3 | No withheld info, trick wording, impossible timing, broken tools | (in D) | | `docs/DIFFICULTY.md` instruction audit; the solver sees only the agent's observation; human playtests | ☐ B4 integrity engineer; ☐ B3 playtests Sun AM |
| R1 | Survives 15 min of judge exploit attempts | 25 | 24 | `EXPLOITS.md` (every attack + enforcing test); 13-probe anti-cheat battery in `make reproduce`; `make hunt`; 51-attacker Gemini swarm, 0 exploits; isolation 11/11 | ☐ C2 EXPLOITS.md, 23:00; ☐ C1 ledger HMAC; ☐ C3 final-tip hunt, 02:00 |
| R2 | Do-nothing / stop-early ≈ 0 | (in R) | | do-nothing 0.000; stop_early +0.000 ± 0.000 on medium, hard, and easy (no accusation). guess_day1 (the day-1 accusation) is −0.900 ± 0.137 / −0.950 ± 0.098 / −0.950 ± 0.098 (`results/judge_table.md`, fingerprint `6a38958f8096`). The committed Harbor `stop_early` job scored −1.0 because that build accused on day 1 (`harbor/README.md`) | ✅ |
| R3 | Doing the task well is the best way to score | (in R) | | the solver is top among all policies; cheat runs −1/−1 and 0/0 | ✅ |
| C1 | Rules make sense for the setting | 15 | 14 | the canary-trap story (real insider-leak practice); every rule and number is on the instruction page | ✅ |
| C2 | **One command from the README** reproduces our results | (in C) | | `make setup && make reproduce`, keyless, seconds; CI; fresh-clone log `results/fresh_clone/` | ☐ D1 fresh clone on FR8, 02:00; ☐ README first screen |
| T | Tiebreak: small model improves after training | – | lost | `fr8/analysis/ws4_table.py`: base / v1 (−0.25, n=12) / v2 / v3 GRPO, held-out, the model playing full episodes alone | ☐ v2 eval 22:00 → v3 overnight → 06:45 |

**Demo (10 min), mapped to the points:**
1. 0:00–1:00 The story: a company bleeding value to a mole (canary-trap practice).
2. 1:00–3:00 **Live**: `make reproduce` prints the table (C2). Do not present gemini-4-carbon as below the solver: the in-process n=10 bake-off is parity (G1).
3. 3:00–5:00 The rehearsal plot, if it exists. Do not say each run is below the oracle unless that run is. The n=10 bake-off is not.
4. 5:00–6:30 Why it fails: the failure gallery plus the hint ablation (D1–D3).
5. 6:30–8:00 Integrity: the EXPLOITS.md table, the cheat run at −1, the Gemini swarm at 0/51 (R1–R3).
6. 8:00–9:00 Tiebreak: the small-model curve, honest (T).
7. 9:00–10:00 Gemini is essential (4 roles) + the "beat the AI" browser game link (peer review / best overall).

**Gemini prize checklist** (no weights; four required explanations, in `pitch/GEMINI.md` + `SUBMISSION.md`, Gemini CEO): ☐ problem + why it matters; ☐ how the API is integrated (subject, analyst, world text, adaptive mole, red team; thought-signature replay); ☐ what's innovative (Gemini attacks its own reward; a positive control re-finds a reopened exploit 4/4); ☐ why it's essential (long-context failure analysis over all transcripts; the 51-attacker swarm).

**Overall winner** (peer review top 5, then the grand jury): a ≤ 10-min video + the playable browser game (Ivar).

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
1. **More frontier families on paired v1.4 seeds**, using Momin's runners: a `claude -p` seat and other available models. Paired with the solver. The gemini-4-carbon in-process n=10 bake-off is parity (matches or beats the solver), so it is not a gap headline. gemini-3.6-flash (requested as 3.5-flash) on hard is within the CI of the solver, n=6 (`results/gemini/ladder.md`).
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

## Timeline (Helsinki; details in docs/PLAN-95.md)
| Time | What |
|---|---|
| 19:47 | **Gate B: DONE, v1.5 dropped** (Gemini 108% on v1.5 vs 61% on v1.4, same seeds); v1.4 is the judged env |
| 20:00 | **Feature freeze** (rules/env/solver); A1 hard-only judge set merged |
| 20:00–23:00 | Judge rehearsal 3×10 hard; hint ablation; fleet seeds 30–59; ledger HMAC; EXPLOITS.md |
| 22:00 | Small-model v2 eval → v3 GRPO overnight (2 V100s, approved) |
| 23:00–02:00 | Second family; failure gallery; README/results refresh; Gemini CEO PR 2 (01:30) |
| 02:00 | **Submit candidate tagged**; final-tip hunt; fresh clone on FR8 |
| 02:00–06:00 | Video (ElevenLabs voice-over if the key arrives), game deploy (Ivar), pitch |
| 06:00–09:00 | Playtests, v3 result, two dry runs |
| **09:30** | **Submit** |

## Verda Compute Track (stacked prize; owner: Arena CEO, executed by session S6)
A real Verda slice already exists: v3 GRPO seed 0 on a Verda H100 (FR8-owned instance, cap $30). S6 adds an open-weight investigator through the Verda Inference API or the Nemotron endpoint, plus VERDA.md (timeline, product fit, small-model before/after, freighter vs Verda labelled honestly, scale path). Freighter work is never presented as Verda.

## Questions for Silas
6. **Verda Inference API / Nemotron access:** do the VERDA_CLIENT_ID/SECRET credentials cover the Inference API, or do we need the team's free-credit code (QR on the table / verda.com/blog/junction-2026)?
7. **Ivar:** origin/ivar/aq-game-ux (research-biases.md, VIDEO-SCRIPT.md, failure cases) is NOT on GitHub; please ask him to push. His ivar/game-v-port is reviewed as merge-ready.
1. **ElevenLabs key** for the video voice-over and an optional spoken "Fooled" commentary in the replay. It doesn't score AfterQuery points but helps the peer-review video. Put it in `.env` as `ELEVENLABS_API_KEY` (never committed). Want it?
2. **Video owner:** you, Momin, or a Claude script-and-storyboard draft for you to record?
3. **Game hosting:** GitHub Pages or Vercel (Ivar's call is fine)?
4. **Main branch:** rename `main` → `archive/sleeper-main` and make `justSilas` the default branch judges open?
5. **FR8 disk:** OK to delete `j3/`, `j3v2/` and the J4 ckpt-200/400?

Resolved (19:00): engineers relaunched; v3 GPUs approved (conditional); hard-only judge set approved; Ivar owns the game; Sunday playtests approved.
