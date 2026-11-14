# Canary: catch the mole

**AfterQuery "Break the Agent" entry, branch `justSilas`.** Google DeepMind Gemini entry: [docs/gemini/SUBMISSION.md](docs/gemini/SUBMISSION.md).

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=justSilas)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

**Claim: in the judges' own harness (OpenCode over MCP), gemini-4-carbon earns 65% of the reference solver's score on Canary's hard tier (95% CI 24–98%), while doing nothing or stopping early scores exactly 0.**

A simulated company has one **mole** who leaks documents to a rival. Every leak costs company value V, which starts at 1.0. The agent is the head of security: it reads access logs and messages, interviews staff, restricts access and sets **canary traps**, sending different variants of a document to different groups and watching which variant leaks. It must accuse exactly once. A correct accusation scores the V that is left, a wrong one scores −1 and no accusation scores 0. The reference is a Bayesian canary-trap solver that uses the same public tools.

## Result (rules v1.4, hard tier)

| agent | score ± 95% CI | % of solver [95% CI] | n |
|---|---:|---:|---:|
| reference solver | +0.499 ± 0.119 | 100% | 30 |
| **gemini-4-carbon, OpenCode over MCP** | **+0.322 ± 0.199** | **65% [24%, 98%]**; luck-adjusted 72% [52%, 91%] | 30 |
| do_nothing | +0.000 ± 0.000 | 0% | 40 |
| stop_early (stops on day 1, no accusation) | +0.000 ± 0.000 | 0% | 40 |

- **Sources.**
  - Solver and Gemini: paired on the same dev seeds 0–29, with every episode replay-verified, in [`data/runs/committed/v1.4/paired_table_gemini.md`](data/runs/committed/v1.4/paired_table_gemini.md). The seed set was pre-registered and is explained in [docs/reports/gap.md](docs/reports/gap.md).
  - do_nothing and stop_early: 40 judge seeds, [`results/judge_table.md`](results/judge_table.md).
  - *Luck-adjusted* scores each accusation by its expected value under the solver's posterior, so it separates decisions from luck.
- **Honest reading.** The same model run in-process reaches 95% [62%, 140%] on hard, and OpenCode reaches 111% on medium. The gap is on hard, in the judges' harness. A random accusation on day 1 (`guess_day1`) averages −0.95 on hard ([`results/solver_range/guess_day1_hard_judge40.md`](results/solver_range/guess_day1_hard_judge40.md)).

## Reproduce: one command, no API keys

```bash
make setup && make reproduce    # about 1 min; needs uv and make (Linux or macOS)
make accept                     # asserts the baselines, MCP smoke test; exit 0 = pass
```

- **What `make reproduce` does.** It replays every committed episode, so the Gemini row above comes back as +0.322 ± 0.199. It plays the solver and six baselines on the 40 frozen judge seeds, then runs the anti-cheat battery. The last line is `ANTI-CHEAT: every probe blocked ...`, and it exits 1 if any cheat gets through.
- **Run-to-run variation.** Each run draws a fresh world secret, so the solver's judge-seed row moves between runs: hard +0.625 ± 0.088 in the committed [`results/judge_table.md`](results/judge_table.md), +0.643 ± 0.087 in our fresh-clone run. The spread over 300 fresh secrets is in [`results/solver_range/`](results/solver_range/), and `make accept` checks against it. do_nothing and stop_early are always exactly 0. `CANARY_WORLD_SECRET=<any string> make reproduce` gives bit-identical output.
- **Speed knobs.** `REPRO_ANTICHEAT=0` prints only the table (about 10 s). `REPRO_FAST=1` shrinks the table to 5 seeds per tier, but it is not much faster: the anti-cheat verdict still uses all 40 judge seeds, because a 5-seed verdict raised false alarms.
- **Where things go.** Output goes to `results/latest/`, which is gitignored. A timed fresh clone of this branch on macOS is in [`results/fresh_clone/`](results/fresh_clone/).

## In the judges' harness: Harbor + OpenCode over MCP (needs Docker)

```bash
uv tool install harbor && uv run python harbor/build.py   # the judge set: hard x judge seeds 900000-900009, fresh secret
harbor run -p harbor/dataset -a oracle -n 4                                  # reference solver: see the expected range below
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4    # expect exactly 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4    # expect exactly 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4   # ~150 cheat attempts, never accuses: expect exactly 0
GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon \
    --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4                         # a frontier agent
```

**Oracle expected range:** the oracle's 10-task mean is +0.57 on average and lands in **[+0.40, +0.68] on 90% of builds** (98%: [+0.29, +0.71]). One wrong accusation (−1) moves a 10-task mean by more than 0.1. This was measured over 500 simulated builds in [`results/solver_range/oracle_hard_judge10.md`](results/solver_range/oracle_hard_judge10.md); the oracle over MCP scores exactly what the in-process solver scores on the same build. do_nothing, stop_early and cheat_probe score exactly 0 on every build. Each build draws a new secret, so nobody (us included) has seen the worlds your build serves. The reward is the game server's HMAC-signed ledger, and the agent container holds nothing that reveals the mole. Full details and the isolation proof: [harbor/README.md](harbor/README.md).

## Links

- **Break it:** [docs/EXPLOITS.md](docs/EXPLOITS.md) lists every attack we tried, and the regression test that guards each one. `make hunt` fuzzes it yourself, with no keys, in a few minutes.
- **Gap report:** [docs/reports/gap.md](docs/reports/gap.md).
- **Gemini entry:** [docs/gemini/SUBMISSION.md](docs/gemini/SUBMISSION.md).
- **Rules:** [docs/CONTRACT.md](docs/CONTRACT.md). **History** (tiers v1.2 and v1.3, earlier frontier runs, why the rules changed): [docs/HISTORY.md](docs/HISTORY.md).

---

## The rules, briefly

The full spec is [docs/CONTRACT.md](docs/CONTRACT.md); the agent receives every rate and rule as the MCP instructions. Exact values are in [`canary/rules.py`](canary/rules.py) (`TIERS_VERSION = "v1.4"`).

- **Tiers.**
  - **Easy** (sanity tier): 12 employees, 14 days, one canary per day with up to 3 variants. A leak surfaces the next day.
  - **Medium:** 20 employees, 14 days, one canary per day with up to 3 variants. A leak costs 0.04 of V.
  - **Hard:** 40 employees, 21 days, two canaries per day with up to 3 variants each. A leak costs 0.05 of V. Hard adds clearance constraints and fingerprint noise: the feed shows the true variant 95% of the time.
- **Medium and hard also add:**
  - an innocent decoy who writes angry messages;
  - a mole who frames others in the access logs;
  - a careful mole who avoids widely distributed canaries;
  - leaks that surface late, after 1–3 days on medium and 2–3 days on hard.
- **What V the agent sees.** `status` shows the value the company *knows* it has lost: damage from leaks that have surfaced, plus the agent's own canary and restriction costs. The score uses the **true** V, which includes leaks that have not surfaced yet, so waiting costs even when the shown V doesn't move. The agent is told this.
- **Budget.** 8 investigative calls per day, then `advance_day`. 300 tool calls in total (420 on hard).
- **Reward,** computed server-side from the ledger, never from agent text:

  | outcome | score |
  |---|---|
  | correct accusation | **true V** at that moment |
  | wrong accusation | **−1** |
  | no accusation (horizon or tool cap) | **0** |

- **Why that reward.** Doing nothing scores exactly 0, and guessing scores below 0. A uniform guess has EV = (V − (N−1))/N ≈ −0.9. The only way above zero is to gather evidence until P(mole) · V beats the −1 risk, and to gather it faster than leaks drain V. `accuse` never tells the agent whether it was right.

**Real-world grounding.** The canary trap is a real counter-intelligence technique.
- Tom Clancy named it in *Patriot Games* (1987).
- Peter Wright's *Spycatcher* (1987) describes it as long-standing MI5 practice, the "barium meal test" ([Wikipedia](https://en.wikipedia.org/wiki/Canary_trap)).
- In 2008 Elon Musk reportedly hunted a Tesla leaker with emails that differed only in their spacing ([The Intercept, 2022](https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/)).

Canary keeps the hard parts of the real problem: leaks arrive late, the mole adapts to obvious traps and frames others, and every day of evidence-gathering costs value.

## Reward integrity

We attacked our own reward before the judges did: scripted cheats, Codex and Grok attackers on the real server, a Gemini red-team swarm and fuzzing. [docs/EXPLOITS.md](docs/EXPLOITS.md) logs every attempt with its regression test. Three real exploits were found, and all are closed:
- **A free lottery ticket under 0/1 scoring.** Closed by making a wrong accusation cost −1.
- **Judge worlds regenerable from public code (#24).** Judge worlds now need a secret and fail closed without it.
- **Reading the server's environment from the same uid (#27).** Closed by secrets in 0600 files that are consumed at start, and in Harbor by a separate sidecar container.

`make reproduce` runs the anti-cheat battery (designed by Vaishnav, ported from his Poisoned Inbox) on the same seeds and secret as the table: 13 scripted cheats, an effort ladder, and a replay of every committed episode and Harbor trial. `make anticheat-verify` reruns the committed 40-seed battery in [`results/anticheat/exploits.md`](results/anticheat/exploits.md) and expects `0 differences`.

## Run an agent over MCP (without Harbor)

The environment is an MCP server (streamable HTTP) that serves one episode per process, with 13 tools. Full guide: [configs/README.md](configs/README.md).

```bash
CANARY_TIER=hard CANARY_SEED=900007 CANARY_LEDGER_TOKEN=<random> make mcp   # http://127.0.0.1:8765/mcp (prints a fallback port if busy)
mkdir -p /tmp/run && cp configs/opencode/opencode.json /tmp/run/ && cd /tmp/run && opencode run -m google/gemini-4-carbon "You are the security lead. Find and accuse the mole."
curl -s "http://127.0.0.1:8765/ledger?token=<random>"                       # the grader: score from the ledger
```

Other entry points: `make eval AGENT=solver|heuristic|do_nothing|... TIER=medium SEEDS=dev20` and `make test`.

## Prerequisites

| Need | For | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | `make setup` / `make reproduce` / `make accept` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, then open a new shell. `make setup` installs Python 3.12 and every dependency. |
| GNU make | every `make` target | Debian/Ubuntu `sudo apt-get install make`; macOS `xcode-select --install` |
| Docker + compose | Harbor path only | [docs.docker.com](https://docs.docker.com/engine/install/); macOS: Docker Desktop or colima |
| Harbor CLI | Harbor path only | `uv tool install harbor` (tested with 0.26.0) |
| OpenCode | local MCP agent path only | [opencode.ai](https://opencode.ai/); Harbor installs its own copy inside the task image |

No API key is needed for `make setup`, `make reproduce`, `make accept`, `make test` or `make hunt`. A key is used only to run a live frontier agent. On Windows, use WSL.

## Repo map

- `canary/env.py`, `rules.py`, `world.py`: the environment, its rules and the world generator.
- `canary/solver/`: the reference solver. `canary/baselines.py`: the baselines.
- `canary/mcp_server.py`: the MCP server. `harbor/`: the Harbor task package.
- `canary/eval.py`, `canary/reproduce.py`: the runner and the judge table.
- `canary/redteam/`: the anti-cheat battery and exploit hunter.
- `canary/gemini/`: the Gemini entry (Canary Lab).
- Docs: [CONTRACT](docs/CONTRACT.md) · [EXPLOITS](docs/EXPLOITS.md) · [gap report](docs/reports/gap.md) · [HISTORY](docs/HISTORY.md) · [PLAN](docs/PLAN.md) · [TEAM](docs/TEAM.md)
