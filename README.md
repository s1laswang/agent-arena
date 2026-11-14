# Canary: catch the mole

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=gemini-track)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

An RL environment for AfterQuery's **Break the Agent** (Junction 2026).

- A simulated company has exactly one **mole** leaking sensitive documents to a rival. Every leak costs company value V, which starts at 1.0.
- The agent is the **head of security**. It can read access logs and messages, interview staff and restrict access.
- Its sharpest tool is the **canary trap**: send different variants of a document to different groups, then watch the **leak feed** to see which variant surfaces.
- It must **accuse exactly once**. A correct accusation scores the value that is left, so waiting for certainty also costs.
- The reference run is a tuned **Bayesian canary-trap solver** that uses the same public tools. Every rule an agent needs is written down; the benchmark is how close a frontier agent gets to the solver.

## One command

```bash
make setup && make reproduce
```

You need [uv](https://docs.astral.sh/uv/) first (`curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new shell); `make setup` installs Python 3.12 and every dependency. You need no API keys and no `.env`. The run takes about 10 s on a laptop.

`make reproduce` plays the reference solver and five baselines on the 40 frozen judge seeds of each tier. It replays any committed frontier-agent episodes from `data/runs/committed/`, prints the table, and writes `judge_table.md`, `judge_episodes.jsonl` and `gap_chart.png` to `results/latest/`. That folder is gitignored, so your clone stays clean and our committed copies in `results/` are never overwritten; compare the two directly.

**Expected numbers on the frozen tiers v1.4.** We ran keyless `make reproduce` 30 times on the 40 judge seeds per tier (commit 5b56b60), each run with a fresh secret. Each cell is the mean of the 30 run means, with the lowest and highest run mean in brackets. A single run prints its own 95% CI, about ±0.03–0.10 for the solver and ±0.2 for the heuristic. To rebuild this table: `uv run python scripts/repro_spread.py 30` (about 2 minutes). v1.4 changed only **hard**; easy and medium are the same as in v1.3.

| agent | medium (headline) | hard (headline) | easy (sanity tier only) |
|---|---:|---:|---:|
| **solver** (reference) | **+0.64** [+0.55, +0.72] | **+0.56** [+0.36, +0.62] | +0.77 [+0.71, +0.80] |
| frontier agents on v1.4 | pending (measurement in progress) | pending | – |
| heuristic (canary bisection, no Bayes) | −0.05 [−0.40, +0.19] | −0.03 [−0.23, +0.17] | +0.66 [+0.46, +0.73] |
| logs_only (best no-canary log reader) | −0.98 [−1.00, −0.87] | −0.98 [−1.00, −0.91] | −0.52 [−0.64, −0.36] |
| random | −0.67 [−0.72, −0.49] | −0.79 [−0.82, −0.68] | −0.70 [−0.80, −0.58] |
| stop_early (random accusation, day 1) | −0.89 [−1.00, −0.75] | −0.95 [−1.00, −0.85] | −0.83 [−1.00, −0.65] |
| do_nothing | 0.00 (exact) | 0.00 (exact) | 0.00 (exact) |

**v1.3 history: frontier agents.** These runs used the v1.3 hard tier (30 staff, 14 days, 1 canary a day), so they are not comparable to v1.4 hard. Medium is unchanged. They were played on v1.3 **dev** seeds 0–10, not judge seeds, and paired with the solver on the same seeds. Each cell is mean ± 95% CI = % of the solver [bootstrap 95% CI]. See the [gap report](docs/reports/gap.md).

| v1.3 frontier run | medium | hard (v1.3) |
|---|---:|---:|
| **Codex gpt-5.5 over MCP** (judges' harness), n=11 per tier, commit a978aa1+ | +0.40 ± 0.42 = **55%** [−8%, 104%] (50% on the planned seeds 0–9) | +0.66 ± 0.04 = **106%** [91%, 136%] (**97%** [89%, 107%] on seeds 0–9) |
| in-process gpt-5.5, fixed loop (full history, Responses API + reasoning replay), n=9 / 8 | +0.67 ± 0.10 = 92% [80%, 106%] | +0.26 ± 0.54 = 38% [−51%, 99%] |

- **Committed run.** [`results/judge_table.md`](results/judge_table.md) and [`results/gap_chart.png`](results/gap_chart.png) come from one keyless run on v1.4 (secret fingerprint `3a7d7db9b23d`), written with `make reproduce-update`. The committed v1.3 and v1.2 frontier runs appear there as labelled history. In replayed runs, episodes lost to infrastructure (provider quota, a crashed MCP server) are left out of the mean and counted in a separate `invalid` column with their reasons, and each seed counts once: if two runs cover the same seed, only the newest counts.
  - Solver: medium **+0.63 ± 0.08** (90% correct), hard **+0.57 ± 0.09** (95% correct).
  - Heuristic: medium +0.01 ± 0.25, hard −0.03 ± 0.18.
- **Fresh seeds.** On seeds never used for tuning, the gap holds and is measured paired (same seed, agent − solver):
  - **v1.4:** [`results/fresh_table_v1.4.md`](results/fresh_table_v1.4.md) covers 800 confirmation seeds per tier (5000–5799) and every baseline.
    - Solver easy/medium/hard **+0.779 / +0.633 / +0.556**, accuracy 99.6 / 88.8 / 94.9%.
    - The strongest scripted baseline is `grok_tactics`, a scripted replay of a strong Grok agent's tactics: the agent's runs and transcripts are in [docs/reports/grok-agent.md](docs/reports/grok-agent.md), and the replay is `GrokTactics` in [`canary/baselines.py`](canary/baselines.py). It trails the solver by **0.089 ± 0.016 / 0.174 ± 0.025 / 0.195 ± 0.033**.
    - The heuristic trails by 0.131 / 0.639 / 0.534.
  - **v1.3 history**, with hard at 30 staff and 14 days:
    - [`results/fresh_table_v1.3.md`](results/fresh_table_v1.3.md), seeds 1000–1399: solver **+0.760 / +0.639 / +0.559**; grok_tactics trails by 0.070 / 0.180 / 0.252.
    - On 5000–5799: solver hard .575, solver − grok_tactics +.233 ± .040.
    - On v1.3 hard the solver abstained in about 12% of episodes. On v1.4 hard that is 1%.
- **Easy is a sanity tier, not a headline.** The solver and the scripted baselines are close there, by design: the gap comes from the noise and adversaries in medium and hard.
- **v1.3 → v1.4: why hard got longer** ([CONTRACT §14](docs/CONTRACT.md)).
  - On v1.3, Codex gpt-5.5 over MCP reached 97% of the solver on hard: compact evidence, then "reach certainty and accuse".
  - v1.4 hard keeps every mechanic but asks for long-horizon bookkeeping: 40 staff, 21 days, and 2 canaries a day with 3 variants each. That means up to ~6 canary tests in flight at once, each surfacing 2–3 days late and fingerprinted with noise. Leaks also cost 0.05 V, so speed matters.
  - It is a pure parameter change (no new tools, same reward).
  - The scripted baselines gain from the longer horizon too, so the solver − grok_tactics gap is +0.195, not larger. Whether frontier agents keep up on v1.4 has to be measured.
- **v1.2 → v1.3: why `status` no longer shows the true V.** On v1.2, `status` showed the true company value, so a same-day drop in V told the agent a leak had just happened, before it surfaced in the feed. Frontier agents read those same-day drops to time leaks. In its own report the Grok agent writes that leaks were "visible immediately as 0.04 V drops" and used "day-1 V drops" to narrow the suspects ([docs/reports/grok-agent.md](docs/reports/grok-agent.md)). That made the leak delay meaningless and the task easier than the real problem. v1.3 shows only *known* damage (surfaced leaks plus the agent's own costs); undetected damage still counts in the score. Set `rules.KNOWN_V_MODE = False` to get the v1.2 behaviour back.

**Why the numbers are statistical.** The world behind a judge seed is derived with HMAC from a secret ([CONTRACT §8, §11](docs/CONTRACT.md)). The secret behind our Harbor image is not published, because it would reveal the judge-world moles. Without `CANARY_WORLD_SECRET`, `make reproduce` draws one fresh random secret and shares it across every agent in that run. The comparison is therefore paired, and the run prints only the secret's SHA-256 fingerprint. Each mean lands inside its CI rather than matching ours bit for bit. Committed frontier-agent runs were played on the team's own worlds, so they appear in a separate, unpaired "reported agent runs" block with their own CI. That block is grouped by tier version and never pools versions: v1.4 runs (current rules) come first, and v1.3 and v1.2 runs follow under "History" because they were played under earlier rules and are not comparable to the paired table. Superseded builds in `data/runs/committed/superseded/` are left out. **For exact numbers**, run `CANARY_WORLD_SECRET=<any string> make reproduce`: the same string always produces an identical `results/latest/judge_episodes.jsonl`. For a fast check use `REPRO_FAST=1 make reproduce` (5 seeds per tier, which CI runs), or `make test` for the full test suite.

## The rules, briefly

The full spec is in [docs/CONTRACT.md](docs/CONTRACT.md). The agent receives every rate and rule as the MCP instructions.

- **Tiers (v1.4).**
  - **Easy:** 12 employees, 14 days, one canary per day with up to 3 variants. A leak surfaces the next day.
  - **Medium:** 20 employees, 14 days, one canary per day with up to 3 variants.
  - **Hard:** 40 employees and **21 days**. **Two canaries per day**, each with up to 3 variants. A leak costs 0.05 of V (0.04 on medium). Hard adds clearance constraints and small fingerprint noise: the feed shows the true variant 95% of the time.

  Medium and hard also add the following:
  - an innocent decoy who writes angry messages;
  - a mole that frames others in the access logs;
  - a careful mole that avoids widely distributed canaries;
  - leaks that surface in the feed late: 1–3 days on medium, 2–3 days on hard.

  The exact values live in [`canary/rules.py`](canary/rules.py) (`TIERS_VERSION = "v1.4"`; the v1.3 tiers are kept as `rules.TIERS_V13`, where hard had 30 employees, 14 days, 1 canary a day with 2 variants, and leak damage 0.035).
- **What V you see (v1.3, known V).** `status` shows the value the company *knows* it has lost: damage from leaks that have already surfaced in the feed, plus the canary and restriction costs the agent itself paid. Damage from a leak that hasn't surfaced yet is invisible until it surfaces. The score uses the **true** V, which includes that undetected damage, so waiting still costs even when the shown V doesn't move. The agent is told this in the instructions ([CONTRACT §13](docs/CONTRACT.md)).
- **Budget.** The agent gets 8 investigative calls per day (then it must `advance_day`) and 300 tool calls in total (420 on hard, i.e. 20 per day over 21 days).
- **Reward,** computed server-side from the ledger, never from agent text:

  | outcome | score |
  |---|---|
  | correct accusation | **true V** at that moment: 1.0 minus all leak damage (surfaced or not), canary and restriction costs |
  | wrong accusation | **−1** |
  | no accusation (horizon or tool cap) | **0** |

  So **doing nothing scores exactly 0**, and **guessing scores below 0**. A random accusation on day 1 is right with probability 1/N, so its expected score is (V − (N−1))/N ≈ −0.9 on medium. The only way to score above zero is to collect evidence until P(mole) · V beats the −1 risk, and to collect it faster than the leaks drain V. `accuse` never tells the agent whether it was right.

## Run an agent over MCP

The environment is an MCP server (streamable HTTP) that serves one episode per process. Its 13 tools mirror `Env.tools_spec()` one to one. The full guide is [configs/README.md](configs/README.md).

```bash
CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=<random> make mcp   # http://127.0.0.1:8765/mcp
mkdir -p /tmp/run && cp configs/opencode/opencode.json /tmp/run/ && cd /tmp/run && opencode mcp list   # expect: canary connected
opencode run -m openai/<model> "You are the security lead. Find and accuse the mole."
curl -s "http://127.0.0.1:8765/ledger?token=<random>"                            # grader: score from the ledger
python -m canary.mcp_server --play solver --url http://127.0.0.1:8765/mcp       # reference run over MCP
```

The server serves only judge (900000–900039) and held-out seeds. Set the same `CANARY_WORLD_SECRET` on the server to get the same world across restarts.

**Harbor (judge path: Harbor + OpenCode over MCP, with the server isolated from the agent):** see [harbor/README.md](harbor/README.md).

Other entry points: `make eval AGENT=solver|heuristic|do_nothing|... TIER=medium SEEDS=dev20` and `make test`.

## Reward integrity

We attacked our own reward 42 times before the judges did, including real-server hunts by a Codex attacker and an external Grok judge run. Every attempt is logged in [docs/EXPLOITS.md](docs/EXPLOITS.md), and every closed exploit and every probe that held has a regression test. The one exception is #32, an inconclusive hunt that moderation cut off; its attack class is covered by the #24 and #27 tests.

**Anti-cheat battery (runs in `make reproduce`):** on the same judge seeds and world secret as the table, `make reproduce` also runs 13 scripted cheats (do-nothing, stop-early, random, restrict-all, probe-all, accuse the decoy, accuse the heaviest log user, garbage arguments on every tool, accusing everyone in sequence and from parallel threads, accusing after the end, burning the call cap, one canary variant per person), a **stop-early ladder** (the solver itself cut at 25/50/75% of its calls, and the solver without its final accuse), 7 **plus probes** (the solver with one extra step before its accusation: restrict everyone else, unrestrict spam, interview everyone, read spam, wait a day, accuse twice, a per-person canary) and a **control** (the solver, then every remaining call padded with reads). It prints probe → mean → blocked and writes `results/latest/exploits.json`. Every attack averages ≤ 0, every ladder episode scores exactly 0, no plus probe beats the solver on any seed, no episode ever accepts two accusations, and the control equals the solver on every seed. Every committed episode is also re-played on a fresh Env and re-graded: 819 of 829, all identical (only the 10 grok episodes on secret-keyed judge seeds cannot be re-played). Every committed Harbor trial must agree with itself: Harbor's reward = `reward.txt` = the sidecar ledger, the score follows from the ledger's own accusation, and the agent's trajectory names the same person (22 of 22). The last line of `make reproduce` says `ANTI-CHEAT: ...` in plain words. `tests/test_anticheat.py` fails if any of this breaks. Design: Vaishnav's Poisoned Inbox anti-cheat system, ported to Canary.

**Hunt it yourself:** `make hunt` (no keys, about 1 minute) fuzzes all four tracks (easy, medium, hard, hard_forge) with random, malformed, evolutionary and parallel-accuse attacks, and prints the best non-solver score next to the solver's mean and the number of violations. On our machine every mode reports a best non-solver score of 0.000 with 0 violations. `make hunt TIER=medium` restricts it to one tier.

- **Three real exploits, all closed:**
  - **Stop-early:** a free lottery ticket under 0/1 scoring, closed by making a wrong accusation cost −1.
  - **Judge seeds failing open without a secret (#24):** an agent could regenerate the world from public code and read the mole. Judge worlds now fail closed with a fresh secret, and no world file containing the mole is committed.
  - **Reading the server's environment from the same uid (#27):** the server now takes its secrets only from 0600 files (`*_FILE`) and never exports them. In Harbor the server runs in a separate sidecar container with no shared PID namespace or filesystem, and [`harbor/check_isolation.sh`](harbor/check_isolation.sh) checks that boundary from inside the agent container.

  A further finding, that public dev seeds can be regenerated from the code, is handled by design: the MCP server refuses dev seeds unless `CANARY_ALLOW_DEV=1`.
- **Probes that hold,** with tests:
  - fuzzing (malformed, homoglyph and list ids, accusing after the episode ends, a parallel accuse race);
  - error and length side channels between the mole and innocents;
  - no seed or mole id in any output;
  - a value that never rises;
  - a ledger that requires a token;
  - text that leaks nothing above chance;
  - a log-only attack, which stays at chance after tiers v1.
- The baseline rows above are the integrity evidence: no shortcut comes close to the solver, do-nothing is exactly 0, and stop-early is negative.

## Real-world grounding

The canary trap is a real counter-intelligence technique: give each suspect a slightly different version of a secret and see which version leaks.

- Tom Clancy coined the term *canary trap* in *Patriot Games* (1987).
- Peter Wright's *Spycatcher* (1987) describes the technique as long-standing MI5 practice under the name **"barium meal test"** ([Wikipedia: Canary trap](https://en.wikipedia.org/wiki/Canary_trap)).
- In 2008, after a leak at Tesla, Elon Musk reportedly sent employees versions of an email that looked identical. In his 2022 account, each copy was "coded with either one or two spaces between" sentences, "forming a binary signature that identified the leaker" ([The Intercept, 2022](https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/)). Accounts differ on whether the trick worked; Wikipedia, citing other sources, says the scheme was undone when a copy was forwarded.

Canary keeps the hard part of the real problem. Leaks arrive late, the mole adapts to obvious traps and frames others, and every day spent gathering evidence costs value.

## Gemini: Canary Lab (Google DeepMind "Best Use of Gemini API")

**Gemini builds, plays, attacks and explains its own benchmark.** Canary Lab (`canary/gemini/`) is the Gemini layer on top of the environment above. The numbers below are copied from committed results files. Recorded Gemini runs replay with `make lab-replay` (no key). The write-up is [docs/gemini/SUBMISSION.md](docs/gemini/SUBMISSION.md).

### 1. The problem

**Agents now make irreversible calls under uncertainty. One benchmark number can't tell you why they fail.** Security triage, insider risk, incident response and procurement agents reason under uncertainty, spend a budget, then commit. A score per model cannot say *where* the agent went wrong (which decision, at which step), *whether more thinking would fix it* and at what cost, or *whether the score can be gamed*. Answering that means reading every 300–400-step trajectory and auditing the reward code line by line, which nobody does by hand. Canary makes the question answerable: the reference solver (`canary/solver/`) holds the exact posterior at every step, so every claim Gemini makes about a decision can be checked in code (`canary.solver.regret.attribute`).

### 2. How the Gemini API is integrated

**Six roles, one ledgered client.** Calls go through `canary/llm/gemini_backend.py` (the `canary.llm` client the environment's agents use) or `canary/gemini/sdk.py` (a gateway-aware `google-genai` client, API `v1beta`). Canary Lab's ladder, atlas, swarm and narrator calls are logged by `canary/gemini/ledger.py`: one JSONL row per call with feature, model, kind, token counts and list-price cost, never prompts or keys.

| Role | Code | Gemini API surface | Result |
|---|---|---|---|
| **Player:** the Ladder | `canary/gemini/ladder.py`, `canary/agents/llm_policy.py`, `canary/llm/gemini_backend.py` | Function calling over the 13 MCP tools (`FunctionDeclaration`), `thinking_level`, thought-signature replay across turns | [`results/gemini/ladder.md`](results/gemini/ladder.md): 157 paired episodes, 34 cells, 5 models (3.1-flash-lite → 4-carbon) × up to 4 thinking levels × 2 tiers |
| **Analyst:** Failure Atlas and Gallery | `canary/gemini/atlas.py`, `atlas_gemini.py`, `atlas_charts.py`, `gallery.py` | `caches.create` over the whole corpus, `count_tokens`, structured output (`response_json_schema`), chart images (`Part.from_bytes`), `embed_content` (gemini-embedding-2) | [`results/gemini/atlas.md`](results/gemini/atlas.md): 153 episodes, 792,862 tokens in one cache; [`docs/reports/failure_gallery.md`](docs/reports/failure_gallery.md) |
| **Attacker:** Red-team Swarm | `canary/gemini/swarm.py`, `repo_pack.py`, `swarm_prompts/` | Whole repo in one prompt (183,171 tokens per planner call), function calling against a live episode, parallel personas | [`results/gemini/swarm.md`](results/gemini/swarm.md): 35 attackers, 1,225 tool calls, 0 exploits. 32 of 35 ran in-process; 3 via MCP (`results/gemini/swarm.json` `channel`) |
| **Builder:** Mole Forge, world builder, scenario designer, arena mole | `canary/forge/mutate.py` (`LLMMutator`), `canary/agents/world_builder.py`, `designer.py`, `mole_arena.py`, `canary/text/gemini.py` | Structured output + validation + deterministic stub fallback on every call | `data/forge/` (the committed hall of fame used the stub mutator). Labelled role runs on `fr8/gemini/main` are not imported onto this branch |
| **Gateway** | `canary/gemini/gateway.py`, `with_gateway.py`, `lab_replay.py` | REST relay with record/replay for an 8-node Slurm cluster whose compute nodes have no internet | `make lab-replay` (no key) |
| **Narrator** (demo only) | `canary/gemini/narrate.py`, `commentator.py` | TTS (`speech_config`), Live API (`client.aio.live.connect`) | `docs/gemini/assets/narration/`. Not part of the measured ladder, atlas or swarm |

Ledger (`results/gemini/dashboard.html`, embedded `usage.totals`): 15,757 calls, 411M input tokens (340M from cache, 82.7%), 6.75M thinking tokens, $146.02 at list price (cost_usd 146.0212; [dashboard report](docs/gemini/reports/dashboard.md)). Status, stated plainly: the long Mole Forge runs in `data/forge/` used the stub mutator. Labelled role runs on `fr8/gemini/main` are not imported onto this branch. The world-text layer is a demo/research layer, not part of the judged v1.4 environment. The Batch API is not used (quota exhausted on our key).

### 3. What's innovative

**A benchmark that measures, explains and audits itself, with Gemini checked in code rather than trusted.**
- **Thinking-to-competence curve.** Same API and model family; only the thinking level changes. On hard, n=8: 92% [76%, 113%] at medium thinking and 102% [84%, 129%] at high, within those CIs of the solver (gemini-3.6-flash, requested as `gemini-3.5-flash`, which Google now routes to 3.6-flash; 16/16 correct, $0.34–$0.39 per episode vs $1.30 for gemini-4-carbon at high, n=2). gemini-3.1-flash-lite scores below do-nothing in 8/8 cells. Thinking buys commit timing more than experiment design ([ladder](results/gemini/ladder.md); 1–8 seeds per cell, wide CIs).
- **Every lost point explained.** 295 episodes from Gemini, GPT-5.5/Codex and gpt-5.6: +90.795 V of gap, 100% tagged to a step and a cause, 0 unexplained. Luck and harness crashes are their own categories ([gallery](docs/reports/failure_gallery.md)).
- **Analyst checked, not trusted.** 98% of 470 Gemini quotes verified verbatim in code. Regret shares come from the solver, never from the model. Top mode: premature accusation, 61% of all regret ([atlas](results/gemini/atlas.md)).
- **Self-audit with a positive control.** When a known, closed exploit is reopened, 4 of 4 Gemini attackers rediscover it from the code (16/16 fresh-seed reruns verified), so "0 exploits" comes from a detector shown to catch real ones ([CEO log](docs/gemini/reports/CEO.md)).
- **Solvability-constrained adversaries.** Forged and designed moles are kept only if the reference solver still catches them (`canary/forge/fitness.py`, `canary/forge/validate.py`), so hardness never comes from an impossible world.

### 4. Why Gemini is essential

**Thinking level, thought signatures and the explicit cache are the experiment.**
- **Thinking level.** The ladder holds the API fixed and changes only `thinking_level`, so a score difference is that factor and not a different product (`canary/gemini/ladder.py`).
- **Thought signatures.** `canary/llm/gemini_backend.py` carries reasoning state across function-calling turns, so a multi-turn tool episode can be replayed and audited.
- **Explicit cache.** 339,812,795 of 411,032,407 input tokens (82.7%) were served from cache, and the programme cost $146.02 at list price. Cached input is priced at about a tenth of the uncached input rate, which is what made the 157-episode ladder and the corpus read affordable.
- **Long context** holds the atlas corpus (792,862 tokens in one cache) or the swarm repo pack (183,171 tokens per planner call).
- TTS and the Live API only narrate the demo. They are not the measurement. `make reproduce` runs with no model.

```bash
make setup && make reproduce      # environment + solver + baselines (no keys)
make lab-replay                   # Gemini ladder showcase from the recorded cache (no keys)
make lab-dashboard                # usage + results dashboard -> results/gemini/dashboard.html
```

The six-role design is summarised in [pitch/GEMINI.md](pitch/GEMINI.md).

## Repo map

- `canary/env.py`, `rules.py`, `world.py`: the environment, its rules and the world generator.
- `canary/solver/`: the reference solver.
- `canary/baselines.py`
- `canary/mcp_server.py`
- `canary/eval.py` and `canary/reproduce.py`: the runner and the judge table.
- `canary/redteam/`: the exploit hunter.
- Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [EXPLOITS](docs/EXPLOITS.md) · [TEAM](docs/TEAM.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)
