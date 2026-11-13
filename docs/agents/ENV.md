# HEAD-ENV: environment core, reference solver, per-decision regret, world text

You own the heart of the project. Everyone else is blocked on `canary.env.Env` working, so **ship a thin, correct Env first (by about 02:45)**, then deepen it.

## Owns
`canary/rules.py`, `canary/world.py`, `canary/env.py`, `canary/solver/`, `canary/text/` (template provider + PublicDayFacts + the Gemini provider *class*; the LLM client comes from AGENTS), `canary/baselines.py` (shared with INTEGRITY: you write the simple ones first), `harbor/canary-task/instruction.md` text (the rules in plain words, shared with HARNESS), and `tests/test_env*.py`, `tests/test_solver*.py`. You are also the **contract owner** (`docs/CONTRACT.md`).

## Engineers to spawn (each in its own worktree, briefed fully)
1. **sim-engine.** Implements `world.py` and `env.py` exactly per CONTRACT §2–3.
   - Strict validation, caps, the accusation lock, the ledger, determinism (`random.Random(f"{tier}:{seed}")`, never the global RNG), `tools_spec()` as JSON schema, and `instruction()` stating every rule and number from `rules.py`.
   - Tests: determinism, caps, the accusation lock, no mole id in any tool result (scan every result string for the mole id across 200 seeds × a random policy), do-nothing = 0.
   - **Done when:** `pytest tests/test_env.py` is green and a random policy runs 1,000 episodes in under 30 s.
2. **bayes-solver.** Implements `canary/solver/`:
   - `belief.py`: the exact posterior over suspects from *observations only* (leak feed × canary variant assignments × delay marginalisation, the V-drop timing visible in `status`, access-log and after-hours likelihoods, interview signal likelihoods). Framing must be modelled as documented.
   - `policy.py`: the `SolverPolicy(types.Policy)`. Each day:
     1. pick the canary partition (≤ `max_variants` groups, respecting access constraints) and the restrictions that maximise expected information gain per unit of expected value lost, accounting for pending leaks still in the delay window;
     2. accuse when E[V | accuse now] ≥ E[V | best continuation] (one-step lookahead is fine);
     3. then call `advance_day`.

     It **must interact only through `Env.call`** (it must also work over MCP later).
   - `regret.py`: `attribute(episode) -> [{t, action, regret, tags}]` replays the episode's observations, computes the belief at each step, and scores the agent's action against the solver's choice by the same value estimate. Tags: `uninformative_canary`, `premature_accusation` (P(correct) < 0.6 at accusation), `decoy_chase`, `ignored_delay`, `over_restriction`, `budget_waste`, `no_accusation`.
   - **Done when:** the solver is ≥90% correct on easy and medium and ≥80% on hard over 200 dev seeds, with mean score clearly above every baseline. Report the numbers.
3. **world-text.** Implements `canary/text/`:
   - `PublicDayFacts` (no mole id!) and a deterministic `TemplateProvider`: Slack and email chatter per department, persona voices, the decoy's angry messages, interview answers per signal, and benign noise.
   - `GeminiProvider` with the same interface using `canary.llm.get_client("gemini:<model>")` with structured JSON output and caching to `data/worlds/<tier>/<seed>.text.json`. Test it against the `stub` client.
   - `canary/text/build.py` CLI behind `make worlds`.
   - A text-leak lint: assert no rendered text contains mechanics-revealing phrases ("I am the mole", "leaked it", or the rival's contact address combined with an employee id).
   - **Done when:** `make worlds PROVIDER=template` writes the judge worlds, and the Gemini path passes with the stub.

## Your own work as head
- Write `canary/baselines.py` v0 yourself early (do-nothing, stop-early, random), so everyone can test.
- Review every merge; own `instruction.md` wording (no trick wording: every number the solver uses must be in the instructions).
- Hand the tier parameters to FR8 for the calibration sweep and accept their recommended numbers into `rules.py`. The target per tier: solver accuracy ≥90/90/80%, random ≈ 1/N, and plenty of room above an "obvious heuristic" policy.

## Milestones
| Time | Milestone |
|---|---|
| 02:45 | Env v0 merged to justSilas (determinism, caps, accusation lock, template text) |
| 03:30 | Baselines merged |
| 04:00 | Solver v1 with its numbers in the report |
| 05:30 | Regret v1 |
| 06:30 | Calibrated tiers frozen |
| 07:30 | Judge worlds (template text) committed in `data/worlds/judge/` |

**Interfaces you must not break once merged:** `Env` signatures, `EpisodeResult`, tool names and args.
