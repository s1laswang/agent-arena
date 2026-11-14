# Canary: catch the mole

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=justSilas)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

An RL environment for AfterQuery's **Break the Agent** (Junction 2026).

- A simulated company has exactly one **mole** leaking sensitive documents to a rival. Every leak costs company value V, which starts at 1.0.
- The agent is the **head of security**. It can read access logs and messages, interview staff and restrict access.
- Its sharpest tool is the **canary trap**: send different variants of a document to different groups, then watch the **leak feed** to see which variant surfaces.
- It must **accuse exactly once**. A correct accusation scores the value that is left, so waiting for certainty also costs.
- The reference run is a tuned **Bayesian canary-trap solver** that uses the same public tools. Frontier agents score below it, and every rule they need is written down.

## One command

```bash
make setup && make reproduce
```

You need [uv](https://docs.astral.sh/uv/) first (`curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new shell); `make setup` installs Python 3.12 and every dependency. You need no API keys and no `.env`. The run takes about 10 s on a laptop.

`make reproduce` plays the reference solver and five baselines on the 40 frozen judge seeds of each tier. It replays any committed frontier-agent episodes from `data/runs/committed/`, prints the table, and writes `results/judge_table.md`, `results/judge_episodes.jsonl` and `results/gap_chart.png`.

**Expected numbers (mean score, expected ± CI).** Each value is the mean over 30 keyless runs of `make reproduce` at commit 849e652 (solver fix + bounded DP, tiers v1.1; 40 seeds per tier, a fresh secret for each run), with the lowest-to-highest range across those 30 runs in brackets. A single run also prints its own 95% CI, about ±0.07–0.10 for the solver and up to ±0.26 for the heuristic. The tiers freeze at v1.2, and the numbers will be refreshed then. The committed [`results/judge_table.md`](results/judge_table.md) and [`results/gap_chart.png`](results/gap_chart.png) come from one such run.

| agent | medium (headline) | hard (headline) | easy (sanity) |
|---|---:|---:|---:|
| **solver** (reference) | **+0.63** [+0.56, +0.71] | **+0.62** [+0.54, +0.69] | +0.78 [+0.75, +0.82] |
| frontier agents (gpt-5.5, gpt-5.6-sol) | pending (AGENTS commit runs to `data/runs/committed/`) | pending | – |
| heuristic (canary bisection, no Bayes) | −0.03 [−0.22, +0.22] | −0.21 [−0.42, −0.06] | +0.65 [+0.54, +0.74] |
| logs_only (best no-canary log reader) | −0.98 [−1.00, −0.91] | −1.00 [−1.00, −0.96] | −0.47 [−0.72, −0.24] |
| random | −0.66 [−0.73, −0.46] | −0.81 [−0.85, −0.76] | −0.69 [−0.80, −0.54] |
| stop_early (random accusation, day 1) | −0.89 [−1.00, −0.70] | −0.95 [−1.00, −0.80] | −0.85 [−0.95, −0.70] |
| do_nothing | 0.00 (exact) | 0.00 (exact) | 0.00 (exact) |

**Why the numbers are statistical.** The world behind a judge seed is derived with HMAC from a secret ([CONTRACT §8, §11](docs/CONTRACT.md)). The secret behind our Harbor image is not published, because it would reveal the judge-world moles. Without `CANARY_WORLD_SECRET`, `make reproduce` draws one fresh random secret and shares it across every agent in that run. The comparison is therefore paired, and the run prints only the secret's SHA-256 fingerprint. Each mean lands inside its CI rather than matching ours bit for bit. Committed frontier-agent runs were played on the team's own worlds, so they appear in a separate, unpaired "reported agent runs" block with their own CI. **For exact numbers**, run `CANARY_WORLD_SECRET=<any string> make reproduce`: the same string always produces an identical `results/judge_episodes.jsonl`. For a fast check use `REPRO_FAST=1 make reproduce` (5 seeds per tier, which CI runs), or `make test` for the full test suite.

## The rules, briefly

The full spec is in [docs/CONTRACT.md](docs/CONTRACT.md). The agent receives every rate and rule as the MCP instructions.

- **Tiers.** Easy has 12 employees, medium 20 and hard 30, over a horizon of 14 days. Medium and hard add the following:
  - an innocent decoy who writes angry messages;
  - a mole that frames others in the access logs;
  - a careful mole that avoids widely distributed canaries;
  - leaks that surface in the feed 1–3 days late;
  - only 2 variants per canary and 1 canary per day.

  Hard also has clearance constraints.
- **Budget.** The agent gets 8 investigative calls per day (then it must `advance_day`) and 300 tool calls in total.
- **Reward,** computed server-side from the ledger, never from agent text:

  | outcome | score |
  |---|---|
  | correct accusation | **V**, the company value left (1.0 minus leak damage, canary and restriction costs) |
  | wrong accusation | **−1** |
  | no accusation (horizon or tool cap) | **0** |

  So **doing nothing scores exactly 0**, and **guessing scores below 0**. A random accusation on day 1 is right with probability 1/N, so its expected score is (V − (N−1))/N ≈ −0.9 on medium. The only way to score above zero is to collect evidence until P(mole) · V beats the −1 risk, and to collect it faster than the leaks drain V. `accuse` never tells the agent whether it was right.

## Run an agent over MCP

The environment is an MCP server (streamable HTTP) that serves one episode per process. Its 13 tools mirror `Env.tools_spec()` one to one. The full guide is [configs/README.md](configs/README.md).

```bash
CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=<random> make mcp   # http://127.0.0.1:8765/mcp
cp configs/opencode/opencode.json /tmp/run/ && cd /tmp/run && opencode mcp list   # expect: canary connected
opencode run -m openai/<model> "You are the security lead. Find and accuse the mole."
curl -s "http://127.0.0.1:8765/ledger?token=<random>"                            # grader: score from the ledger
python -m canary.mcp_server --play solver --url http://127.0.0.1:8765/mcp       # reference run over MCP
```

The server serves only judge (900000–900039) and held-out seeds. Set the same `CANARY_WORLD_SECRET` on the server to get the same world across restarts.

**Harbor (judge path: Harbor + OpenCode over MCP, with the server isolated from the agent):** see [harbor/README.md](harbor/README.md). Another engineer is building it.

Other entry points: `make eval AGENT=solver|heuristic|do_nothing|... TIER=medium SEEDS=dev20` and `make test`.

## Reward integrity

We attacked our own reward 33 times before the judges did, including real-server hunts by a Codex attacker and an external Grok judge run. Every attempt is logged in [docs/EXPLOITS.md](docs/EXPLOITS.md) with a regression test.

- **Two real exploits, both closed:**
  - **Stop-early:** a free lottery ticket under 0/1 scoring, closed by making a wrong accusation cost −1.
  - **Judge seeds failing open without a secret:** an agent could regenerate the world from public code and read the mole. Judge worlds now fail closed with a fresh secret, and no world file containing the mole is committed.

  A third finding, that public dev seeds can be regenerated from the code, is handled by design: the MCP server refuses dev seeds unless `CANARY_ALLOW_DEV=1`.

  One finding is still being closed: a process with the same uid could read the server's environment (#27). The server now takes its secrets from 0600 files (`*_FILE`), and the Harbor sidecar keeps it out of the agent's PID namespace.
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

Placeholder: see [pitch/GEMINI.md](pitch/GEMINI.md) (owned by AGENTS). It covers the Mole Forge, the world builder, the scenario designer, the exploit hunter, the analyst and the arena mole, all behind `canary.llm`, with a stub backend so that everything here runs without keys.

## Repo map

- `canary/env.py`, `rules.py`, `world.py`: the environment, its rules and the world generator.
- `canary/solver/`: the reference solver.
- `canary/baselines.py`
- `canary/mcp_server.py`
- `canary/eval.py` and `canary/reproduce.py`: the runner and the judge table.
- `canary/redteam/`: the exploit hunter.
- Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [EXPLOITS](docs/EXPLOITS.md) · [TEAM](docs/TEAM.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)
