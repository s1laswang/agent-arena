# HEAD-AGENTS: LLM layer, frontier runs (the gap), Gemini roles (the clash), failure analysis

You produce the two numbers the whole pitch hangs on: **how far the frontier agent falls below our reference, and why.** You also make Gemini essential.

## Owns
`canary/llm/`, `canary/agents/`, `configs/agents/`, `canary/analysis/` (failure tags and report), `tests/test_llm*.py`, `tests/test_agents*.py`, and `docs/reports/gap.md` (the gap table + failure-mode report).

## Engineers to spawn
1. **llm-providers.** `canary/llm/`:
   - `get_client(spec)` with backends:
     - `stub`: deterministic; scripted tool calls so the agent loop can be tested;
     - `openai`: Responses or Chat Completions API with function calling, key `OPENAI_API_KEY`;
     - `gemini`: the `google-genai` SDK with function calling + structured output + a thinking budget, key `GEMINI_API_KEY`, default model from `CANARY_GEMINI_MODEL`.
   - Retries with backoff, token and cost accounting, temperature control.
   - `canary/llm/check.py` behind `make gemini-check`.
   - Unit-test everything with the stub. The Gemini backend gets a mocked-transport test, because there's no key tonight.
2. **investigator-runner.** The frontier evaluation, three ways:
   - (a) **Our own tool loop:** `canary/agents/llm_policy.py` implements `types.Policy` on top of `get_client`. It gets the same instruction and tools as the judges' agent, so `make eval AGENT=openai:<model>` works.
   - (b) **The judges' harness shape:** **OpenCode** with OpenAI connected to our MCP server (config from HARNESS; until then, write it yourself from https://opencode.ai/docs/mcp-servers/).
   - (c) **The Codex CLI** (`codex exec`, already logged in) connected to the MCP server via `-c` overrides. **Never edit ~/.codex/config.toml.**

   Runs (b) and (c) go **from a clean temp dir containing no repo source**, so the agent can't read the solver or the world. Run 10 dev seeds × medium first (about 05:00), then 3 runs × 10 seeds × each tier. Save the transcripts. Convert every run to `EpisodeResult` JSONL from the server ledger and history.
3. **gemini-roles.** `canary/agents/`, all runnable with `stub` tonight and Gemini tomorrow:
   - `world_builder.py`: Gemini writes the company: personas, department culture, chatter (the GeminiProvider from ENV uses it).
   - `mole_arena.py`: **arena mode, not the judge path.** A Gemini mole picks which doc to leak, when to go quiet and whom to frame, within the rules (the env validates). The investigator is any Policy. This is Silas's "agents clash".
   - `designer.py`: a PAIRED-style scenario designer. Gemini proposes scenario parameters (decoy behaviour, framing targets, document flow). Keep a scenario only if the solver scores ≥ X **and** the investigator agent scores ≤ Y (regret filter). This proves every hard case is solvable.
   - `analyst.py`: Gemini's long context reads N episodes plus the regret tags and writes a clustered failure-mode report with quotes.
   - `canary/agents/clash.py` behind `make clash`.

## Your own work as head
- `canary/analysis/`: aggregate the regret tags from ENV's `solver.regret.attribute` across runs.
- `docs/reports/gap.md` contains:
  - the gap table (solver vs frontier vs baselines per tier, with confidence intervals);
  - the top failure modes with counts and one annotated trajectory each ("day 3: planted a canary to everyone → zero information; cost 0.06 V").
- **Gap check (kill switch):** if the frontier agent gets ≥85% of the solver's score on medium, tell the CEO immediately with evidence, and propose which mechanics to harden (to ENV).

## Milestones
| Time | Milestone |
|---|---|
| 03:30 | `get_client` stub + openai working |
| 04:15 | `llm_policy` plays an episode in-process |
| 05:00 | First 10 OpenAI episodes on medium |
| 05:30 | OpenCode-over-MCP episode |
| 06:30 | Full frontier runs |
| 07:30 | `gap.md` with failure modes; Gemini roles all pass with the stub |

## v2 additions (01:55). P0 first (llm layer, frontier gap), then these
1. **Mole Forge** (`canary/forge/evolve.py`) per CONTRACT §7.
   - **Tonight:** the `stub` mutator, investigators = heuristic + hinted heuristic (+ the solver as the constraint). **Morning:** a `gemini:<model>` mutator, investigators += OpenAI/Gemini LLM policies.
   - Hand a CPU-only runner to FR8 (job J5).
   - The hall of fame becomes the hard-tier judge moles, frozen by ENV.
2. **Hint ablations:** an `LLMPolicy` with `hint=<failure_tag>` that adds one sentence per failure mode to the system prompt. Run them on medium: each hint must lower its tag's rate and raise the score. These go in `docs/reports/gap.md`.
3. **`pitch/GEMINI.md`:** answer the Gemini brief's 4 questions:
   - the problem and why it matters;
   - how Gemini is integrated: 6 roles (Forge, world builder, designer, exploit hunter, analyst, arena mole);
   - what's innovative: LLM-driven adversary evolution with a solver-verified solvability constraint;
   - why Gemini is essential: no company, no evolved moles, no hard tier without it.
