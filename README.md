# Canary: catch the mole

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=justSilas)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

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

**Expected numbers on the frozen tiers v1.3.** We ran keyless `make reproduce` 30 times on the 40 judge seeds per tier (commit 21e5b2e), each run with a fresh secret. Each cell is the mean of the 30 run means, with the lowest and highest run mean in brackets. A single run prints its own 95% CI, about ±0.03–0.12 for the solver and ±0.25 for the heuristic. To rebuild this table: `uv run python scripts/repro_spread.py 30` (about 5 minutes).

| agent | medium (headline) | hard (headline) | easy (sanity tier only) |
|---|---:|---:|---:|
| **solver** (reference) | **+0.64** [+0.58, +0.69] | **+0.55** [+0.40, +0.66] | +0.77 [+0.74, +0.82] |
| frontier agents (gpt-5.5, gpt-5.6-sol) | pending (AGENTS commit runs to `data/runs/committed/`) | pending | – |
| heuristic (canary bisection, no Bayes) | −0.06 [−0.39, +0.14] | −0.30 [−0.58, −0.09] | +0.64 [+0.56, +0.72] |
| logs_only (best no-canary log reader) | −0.98 [−1.00, −0.91] | −0.99 [−1.00, −0.91] | −0.51 [−0.76, −0.28] |
| random | −0.68 [−0.72, −0.58] | −0.81 [−0.85, −0.72] | −0.69 [−0.80, −0.58] |
| stop_early (random accusation, day 1) | −0.90 [−1.00, −0.75] | −0.95 [−1.00, −0.85] | −0.84 [−0.95, −0.60] |
| do_nothing | 0.00 (exact) | 0.00 (exact) | 0.00 (exact) |

- **Committed run.** [`results/judge_table.md`](results/judge_table.md) and [`results/gap_chart.png`](results/gap_chart.png) come from one keyless run on v1.3 (secret fingerprint `f4cacdb8537b`), written with `make reproduce-update`. Solver: medium **+0.65 ± 0.07** (92.5% correct), hard **+0.60 ± 0.10** (90% correct). Heuristic: medium +0.04 ± 0.24, hard −0.50 ± 0.24.
- **Fresh seeds.** On seeds never used for tuning, the gap holds and is measured paired (same seed, agent − solver):
  - [`results/fresh_table_v1.3.md`](results/fresh_table_v1.3.md), 400 dev seeds per tier (1000–1399): solver easy/medium/hard **+0.760 / +0.639 / +0.559**, accuracy 99.2 / 89.2 / 83.5%. The strongest scripted baseline, `grok_tactics` (a scripted replay of a strong Grok agent's tactics: the agent's runs and transcripts are in [docs/reports/grok-agent.md](docs/reports/grok-agent.md), the replay is `GrokTactics` in [`canary/baselines.py`](canary/baselines.py)), trails the solver by **0.070 ± 0.021 / 0.180 ± 0.040 / 0.252 ± 0.058**; the heuristic by 0.125 / 0.674 / 0.831.
  - FR8's recalibration on 800 more seeds per tier (5000–5799, [CONTRACT §13](docs/CONTRACT.md)): solver **.779 / .632 / .575**, accuracy 99.6 / 88.7 / 84.8%; solver − grok_tactics **+.089 ± .016 / +.174 ± .025 / +.233 ± .040**.
  - On hard the solver is honest rather than perfect: it abstains (no accusation, score 0) in about 12% of episodes instead of guessing.
- **Easy is a sanity tier, not a headline.** The solver and the scripted baselines are close there, by design: the gap comes from the noise and adversaries in medium and hard.
- **v1.2 → v1.3: why `status` no longer shows the true V.** On v1.2, `status` showed the true company value, so a same-day drop in V told the agent a leak had just happened, before it surfaced in the feed. Frontier agents read those same-day drops to time leaks. In its own report the Grok agent writes that leaks were "visible immediately as 0.04 V drops" and used "day-1 V drops" to narrow the suspects ([docs/reports/grok-agent.md](docs/reports/grok-agent.md)). That made the leak delay meaningless and the task easier than the real problem. v1.3 shows only *known* damage (surfaced leaks plus the agent's own costs); undetected damage still counts in the score. Set `rules.KNOWN_V_MODE = False` to get the v1.2 behaviour back.

**Why the numbers are statistical.** The world behind a judge seed is derived with HMAC from a secret ([CONTRACT §8, §11](docs/CONTRACT.md)). The secret behind our Harbor image is not published, because it would reveal the judge-world moles. Without `CANARY_WORLD_SECRET`, `make reproduce` draws one fresh random secret and shares it across every agent in that run. The comparison is therefore paired, and the run prints only the secret's SHA-256 fingerprint. Each mean lands inside its CI rather than matching ours bit for bit. Committed frontier-agent runs were played on the team's own worlds, so they appear in a separate, unpaired "reported agent runs" block with their own CI. That block is grouped by tier version and never pools versions: v1.3 runs (current rules) come first, and v1.2 runs follow under "History" because they were played under earlier rules and are not comparable to the paired table. Superseded builds in `data/runs/committed/superseded/` are left out. **For exact numbers**, run `CANARY_WORLD_SECRET=<any string> make reproduce`: the same string always produces an identical `results/latest/judge_episodes.jsonl`. For a fast check use `REPRO_FAST=1 make reproduce` (5 seeds per tier, which CI runs), or `make test` for the full test suite.

## The rules, briefly

The full spec is in [docs/CONTRACT.md](docs/CONTRACT.md). The agent receives every rate and rule as the MCP instructions.

- **Tiers.** Easy has 12 employees, medium 20 and hard 30, over a horizon of 14 days. Every tier allows one canary per day. In easy, a leak surfaces the next day and a canary can have up to 3 variants. Medium and hard add the following:
  - an innocent decoy who writes angry messages;
  - a mole that frames others in the access logs;
  - a careful mole that avoids widely distributed canaries;
  - leaks that surface in the feed late: 1–3 days on medium, 2–3 days on hard.

  Hard also allows only 2 variants per canary and adds clearance constraints. The exact values live in [`canary/rules.py`](canary/rules.py) (`TIERS_VERSION = "v1.3"`).
- **What V you see (v1.3, known V).** `status` shows the value the company *knows* it has lost: damage from leaks that have already surfaced in the feed, plus the canary and restriction costs the agent itself paid. Damage from a leak that hasn't surfaced yet is invisible until it surfaces. The score uses the **true** V, which includes that undetected damage, so waiting still costs even when the shown V doesn't move. The agent is told this in the instructions ([CONTRACT §13](docs/CONTRACT.md)).
- **Budget.** The agent gets 8 investigative calls per day (then it must `advance_day`) and 300 tool calls in total.
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

We attacked our own reward 41 times before the judges did, including real-server hunts by a Codex attacker and an external Grok judge run. Every attempt is logged in [docs/EXPLOITS.md](docs/EXPLOITS.md), and every closed exploit and every probe that held has a regression test. The one exception is #32, an inconclusive hunt that moderation cut off; its attack class is covered by the #24 and #27 tests.

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

## Gemini

Gemini's role is described in [pitch/GEMINI.md](pitch/GEMINI.md). It covers the Mole Forge, the world builder, the scenario designer, the exploit hunter, the analyst and the arena mole, all behind `canary.llm`, with a stub backend so that everything here runs without keys.

## Repo map

- `canary/env.py`, `rules.py`, `world.py`: the environment, its rules and the world generator.
- `canary/solver/`: the reference solver.
- `canary/baselines.py`
- `canary/mcp_server.py`
- `canary/eval.py` and `canary/reproduce.py`: the runner and the judge table.
- `canary/redteam/`: the exploit hunter.
- Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [EXPLOITS](docs/EXPLOITS.md) · [TEAM](docs/TEAM.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)
