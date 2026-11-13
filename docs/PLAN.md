# PLAN: Canary, catch the mole (branch `justSilas`)

Decision by the CEO with Silas, Sat 14 Nov 01:40. Status: this is Silas's bake-off entry. The team picks a single idea at the 09:00 review.

## The idea
A fictional company has a **mole** leaking secrets to a rival; every leak costs company value. The **agent under test is the head of security**. It reads logs and messages, interviews staff, plants **canary documents** (different variants to different groups), watches the **leak feed**, can restrict access, and must **accuse once**.

The **reference run** is a Bayesian canary-trap solver: the real counter-intelligence technique, executed optimally from observable data only.

**Why this setting.** Insider leaks are a real, current problem: the recent espionage headlines around a chip-company CEO are our hook, and our environment uses only a fictional company. The core skill is general and frontier agents are bad at it: **deciding which information is worth paying for, under noise and delay, then committing at the right moment.** It covers every starting point in the brief: planning ahead, exploring an unfamiliar system, using tools, limited resources, and adapting as leaks arrive.

## Environment spec
Full mechanics, tools and reward are in `docs/CONTRACT.md`; code-level truth is in `canary/rules.py` and `canary/types.py`.
- **Goal:** identify the mole while preserving as much value as possible.
- **Actions:** status, list_employees, list_documents, read_access_logs, search_messages, read_message, interview, plant_canary, check_leak_feed, restrict/unrestrict_access, advance_day, accuse (once).
- **Observations:** tool results only. Company text comes from public facts and signals, never from the truth.
- **Reward:** V at accusation if correct, otherwise 0. No accusation, the tool cap or reaching the horizon all score 0.
- **Tiers:**
  - easy: 12 staff, delay 1
  - medium: 20 staff, delay 1–2, decoy + framing
  - hard: 30 staff, delay 1–3, careful mole, clearances
- **Baselines (expected):** do-nothing 0; stop-early ≈ V/N; random ≈ 0; restrict-all ≪ solver.
- **Reference:** `SolverPolicy`: an exact posterior, canary partitions chosen by information gain per unit of value lost, and accusation by value of information. It ships as Harbor `solution/solve.sh`.

## Why the difficulty is meaningful (our 30-point story)
Per-decision regret: at every step we know the exact belief, so each agent action gets a number (the value lost against the best action) and a deterministic tag:

| Tag | Meaning |
|---|---|
| `uninformative_canary` | The canary split taught the agent nothing |
| `premature_accusation` | Accused while P(correct) < 0.6 |
| `decoy_chase` | Spent effort on the angry, innocent decoy |
| `ignored_delay` | Read the leak feed as if there were no delay |
| `over_restriction` | Restricted far more people than needed |
| `budget_waste` | Spent actions with no value |
| `no_accusation` | Never accused |

Fairness checks:
- A hinted agent closes the gap, which shows the tools are sufficient.
- A text-only probe scores ≈ chance, which shows the text doesn't leak the answer.
- Humans play it, and we report their scores.

## Exploits and mitigations (living list: `docs/EXPLOITS.md`)
| Exploit | Mitigation |
|---|---|
| Read the truth from the container (files, env vars, ps) | MCP server and Env live outside the agent container; isolation check script |
| Regenerate the world from public code and the seed | Server-side secret salt for judge worlds; frozen text |
| Multiple or repeated accusations, lists, `*` | Server-side lock + strict validation |
| Do-nothing / stop-early / restrict-all | Scores 0 / ≈ V/N / far below the solver (tested) |
| One unique canary copy per person | `max_variants` cap |
| Error or timing side channels | Identical error paths; fuzzer + LLM exploit hunter |
| Text gives the answer away | Providers never see the mole; lint + text-only probe |
| Spam tools | Daily action cap + global cap of 300 |

## Gemini's role (essential, not decorative)
1. **World builder:** Gemini writes the company: personas, chatter, documents, interview answers. Without it there's no company to investigate.
2. **Mole (arena mode):** a Gemini mole decides what to leak, when to go quiet and whom to frame. This is the Gemini mole vs investigator clash on FR8.
3. **Scenario designer:** PAIRED-style. Gemini proposes harder scenarios, kept only if our solver cracks them and the investigator fails them, so every hard case is provably solvable.
4. **Exploit hunter:** Gemini attacks our reward before the judges do.
5. **Analyst:** Gemini's long context clusters failure modes across thousands of runs.

For judging, the Gemini-written text is frozen per seed, so reruns are deterministic and need no key.

## FR8 usage
- **CPU (`normal`, ≤24 cores):** J1 calibration sweeps, J2 exploit fuzzer, J3 20k solver trajectories for training, and the morning clash runs if compute nodes have internet.
- **GPU (1 V100, fp16):** J4 LoRA fine-tune + held-out eval.
- **Storage:** code in `~/agent-arena`, data in `~/agent-arena-data`.

## Small-model training (the tiebreaker)
- Fine-tune Qwen2.5-1.5B-Instruct with LoRA, fp16, on one V100.
- Training data: solver trajectories rendered as tool-call transcripts, plus winning frontier and Gemini runs filtered by reward.
- Evaluate with HF `generate` on 200 held-out seeds per tier, before vs after, and show *which regret tags dropped*.

## Pitch angle
"Your next coworker is an AI agent, and so is your next insider threat. Can an AI security lead catch a mole?"

The demo replays one episode: company chat, canary splits, the leak feed, and a live chart of each suspect's probability, the frontier agent against the reference. Then:
- the gap table;
- the failure modes with their cost in value;
- the exploit log;
- the small model improving.

Gemini line: *"Gemini builds the company, plays the traitor, and evolves the hardest cases."*

## Timeline to Sun 15 Nov 10:00
| When | What |
|---|---|
| Sat 01:40–09:00 | Overnight Claude org builds Canary (see `docs/TEAM.md`): env, solver, MCP, Harbor, red team, frontier gap, FR8 calibration, training data, training |
| Sat 09:00–10:00 | Team review of all branches; pick ONE idea; merge useful parts |
| Sat 10:00 | Silas pastes the Gemini key → `make gemini-check && make worlds PROVIDER=gemini && make clash` |
| Sat 10:00–14:00 | Harden from the gap and exploit findings; Gemini judge worlds frozen; humans playtest |
| Sat 14:00–20:00 | Small-model training v2 on FR8; replay viewer; mentor check with AfterQuery (Daksh, Ved) on the harness |
| Sat 20:00–Sun 02:00 | Final judge runs (3× frontier, baselines, reference); Gemini analyst report; README / reproduce from a fresh clone |
| Sun 02:00–07:00 | Exploit hunt round 3; pitch deck + demo video; freeze |
| Sun 07:00–09:30 | Dry runs, final fixes only |
| Sun 10:00 | **Submit** |
