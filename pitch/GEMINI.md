# Canary × Gemini

**1. The problem.** AI agents are being put in charge of security work: triage, insider-risk, incident
response. Nobody can measure whether they actually reason under uncertainty or just pattern-match.
Canary is an RL environment where an agent is head of security at a simulated company and must catch
the one mole leaking documents (canary traps, logs, interviews), while company value bleeds out.
A Bayesian reference solver sets the bar. On v1.4 hard, gemini-4-carbon played through OpenCode over MCP (run locally, not inside Harbor) scores 65% of the solver [95% CI 24%, 98%], 72% [52%, 91%] luck-adjusted, over 30 paired dev seeds (`docs/reports/gap.md`). With OpenCode on medium it is level with the solver (111%), and in-process on hard there is no clear gap (95% [62%, 140%]). The earlier in-process bake-off (n=10 per tier, 21:26) that showed parity on both tiers is superseded by this n=30 set. The tiebreaker's notes gain is the generic hint (notes minus hint −0.039±0.204), not a weight update and not evidence the model learned the task.

**2. How Gemini is integrated: six roles, all behind one `canary.llm` client with structured output**
(`response_schema` + pydantic validation + deterministic fallback on every call):
| Role | What Gemini does |
|---|---|
| **Mole Forge** | Evolves mole strategies in a JSON rule DSL (AlphaEvolve-style mutation/crossover) against our investigators. |
| **World builder** | Writes the company from public facts only: personas, department culture, chat templates (`canary/agents/world_builder.py`). |
| **Scenario designer** | PAIRED-style: proposes mole strategies + tier knobs; kept only if the solver scores ≥ X **and** the agent scores ≤ Y (`designer.py`). |
| **Exploit hunter** | Red-teams the reward and tools for loopholes before judges do. |
| **Analyst** | Uses long context to read N full episodes + regret tags at once; returns clustered failure modes with verbatim, verified quotes (`analyst.py`). |
| **Arena mole** | Plays the mole live, day by day: what to leak, when to go quiet, whom to frame (`mole_arena.py`, `make clash`). |

**3. What's innovative.** The adversary evolves under an LLM, but with a *solvability constraint*:
every evolved or designed mole is verified to remain catchable by the reference solver. So hardness comes
from the agent's reasoning failures, never from impossible or unfair scenarios. That is how the
difficulty gap gets built by design, not by luck.

**4. Why Gemini is essential.** Without it there is no company (no personas or text), no evolved moles,
and therefore no hard tier. The judge tier is literally Gemini's output, frozen and solver-verified.
Long context makes the analyst possible: one call over dozens of full trajectories.

**Status (Sat 14 Nov, 18:23):** the Gemini paths have run against the live Gemini API. Every call is ledgered:
11,180 calls, $88.72 at list price (`results/gemini/dashboard.html`). Results: `results/gemini/ladder.md`, `atlas.md`,
`swarm.md`; write-up: `docs/gemini/SUBMISSION.md`. The deterministic `stub` client remains for keyless tests.
