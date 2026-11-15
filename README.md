# Canary: catch the mole

**AfterQuery "Break the Agent" entry, branch `justSilas`.** Google DeepMind Gemini entry: [docs/gemini/SUBMISSION.md](docs/gemini/SUBMISSION.md).

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=justSilas)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

**What we measured on the hard tier (rules v1.4), stated plainly.** (1) With only the 13 MCP tools (OpenCode), gemini-4-carbon earns 65% of the reference solver's score (95% CI 24–98%, n=30). (2) In the full judge path (Harbor container, where the agent also has a shell) that gap **did not reproduce**: three runs on the final tag scored 93%, 116% and 153% (partial run) of the reference ([`results/harbor/rehearsal/TABLE.md`](results/harbor/rehearsal/TABLE.md)). (3) gpt-5.5 with MCP tools only matches the reference (101%, CI 79–140%). (4) Doing nothing or stopping early scores exactly 0 in every setting. So: expect a frontier agent in your rerun to land near the reference, not clearly below it.**

A simulated company has one **mole** who leaks documents to a rival. Every leak costs company value V, which starts at 1.0. The agent is the head of security: it reads access logs and messages, interviews staff, restricts access and sets **canary traps**, sending different variants of a document to different groups and watching which variant leaks. It must accuse exactly once. A correct accusation scores the V that is left, a wrong one scores −1 and no accusation scores 0. The reference is a Bayesian canary-trap solver that uses the same public tools.

**Tags.** `afterquery-final` (1bc3e281) is the code freeze: the judge rehearsal ran on exactly that commit. `afterquery-submit` (what you are reading) adds results and docs, plus fixes to measurement tooling only (the OpenCode runner, the replay check, the submission audit, two table scripts). `git diff afterquery-final..afterquery-submit -- canary/env.py canary/rules.py canary/solver canary/mcp_server.py canary/world.py canary/mole canary/text harbor` is empty.

## Result (rules v1.4, hard tier)

| agent | score ± 95% CI | % of solver [95% CI] | n |
|---|---:|---:|---:|
| reference solver | +0.499 ± 0.119 | 100% | 30 |
| **gemini-4-carbon, OpenCode over MCP** | **+0.322 ± 0.199** | **65% [24%, 98%]**; luck-adjusted 72% [52%, 91%] | 30 |
| gpt-5.5, OpenCode over MCP (second frontier family) | +0.504 ± 0.064 | 101% [79%, 140%]; luck-adjusted 84% [67%, 103%] | 30 |
| gemini-4-carbon, **Harbor judge path** (3 runs × 10 judge tasks on the tag; run 3 partial) | +0.472 / +0.585 / +0.656 | 93% / 116% / 153% of the oracle on the same tasks (oracle +0.506) | 10 / 10 / 7 |
| do_nothing | +0.000 ± 0.000 | 0% | 40 |
| stop_early (stops on day 1, no accusation) | +0.000 ± 0.000 | 0% | 40 |

- **Sources.**
  - Solver and Gemini: paired on the same dev seeds 0–29, with every episode replay-verified, in [`data/runs/committed/v1.4/paired_table_gemini.md`](data/runs/committed/v1.4/paired_table_gemini.md). The seed set was locked right after those episodes were committed (a post-hoc lock against reruns and cherry-picking), explained in [docs/reports/gap.md](docs/reports/gap.md).
  - do_nothing and stop_early: 40 judge seeds, [`results/judge_table.md`](results/judge_table.md).
  - The solver reference for seeds 0-29 is two committed run dirs: seeds 0-19 in `data/runs/committed/v1.4/reference/solver-hard-20261114-121126/` and seeds 20-29 in `reference/solver-hard-seeds20to29/`. The paired table uses all 30.
  - *Luck-adjusted* scores each accusation by its expected value under the solver's posterior, so it separates decisions from luck.
- **Honest reading.** The 65% gap was measured with MCP tools only, on dev seeds. It did not reproduce in the Harbor judge-path rehearsal (protocol committed before the run; 26 of 27 valid Gemini accusations correct, against 25 of 29 in the MCP-only set). We do not know how much of that difference is the shell the Harbor agent has (it used it in 20 of 28 trials), the two disclosed changes of 15 Nov, or chance. There is also no gap for gpt-5.5 (pre-registered run, reported as measured). If you rerun with a GPT-class agent, expect parity with the reference. gemini-4-carbon run in-process reaches 95% [62%, 140%] on hard, and through OpenCode 111% on medium.
- **Why the two agents differ** ([`results/behaviour_compare_v1.4.md`](results/behaviour_compare_v1.4.md), same 30 seeds): gpt-5.5 plants 17.2 canaries and runs 4 interviews per episode (6% of its calls) and accuses on day 10.2, like the reference (14.1 canaries, day 10.6). gemini-4-carbon plants 8.5 canaries, runs 68 interviews (53% of its calls; an interview's stated likelihood ratio is 1.2) and accuses on day 13.2, with 4 wrong accusations to gpt-5.5's 0. gpt-5.5's own failure: in 2 of 30 episodes it announced its accusation in text and never called `accuse`, which scores 0. A random accusation on day 1 (`guess_day1`) averages −0.95 on hard ([`results/solver_range/guess_day1_hard_judge40.md`](results/solver_range/guess_day1_hard_judge40.md)).
- **Infra retries, disclosed.** Some OpenCode attempts ended on an empty model reply (a Gemini/OpenCode client failure, not a decision). Those attempts were retried and never counted. If they are instead scored 0, OpenCode hard is 56% [19%, 87%] of the solver (luck-adjusted 55% [34%, 77%]): the gap widens, so retrying is the conservative choice. Source: the "alternative" row in the paired table.
- **Harness difference, disclosed.** The committed headline runs used OpenCode with only the 13 MCP tools: `bash`/`python3` were denied. The Harbor template's agent container allows `bash` and `python3`, which cannot reach the world, the seed or the ledger (isolation check: 11/11). So in a Harbor rerun the agent may also compute with Python. The judge rehearsal (`results/harbor/rehearsal/`) uses the Harbor setting, so it measures exactly what you will run.
- **Two changes after the committed runs (15 Nov), disclosed.** Tool errors now carry a `detail` field saying what was wrong (the error string is unchanged, so every committed episode still replays; 28 of the 3,841 calls in the 30 headline episodes hit that error). One contradictory sentence about the careful mole was reworded in the medium and hard instructions. Details: [docs/DIFFICULTY.md](docs/DIFFICULTY.md).

## Reproduce: one command, no API keys

```bash
make setup && make reproduce    # about 1 min; needs uv and make (Linux or macOS)
make accept                     # asserts the baselines, MCP smoke test; exit 0 = pass
```

- **What `make reproduce` does.** It replays every committed episode. In the printed judge table the replayed OpenCode hard row pools all 32 committed episodes (+0.349 ± 0.190): the locked seeds 0–29 plus the two extension seeds 34 and 37 (`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/`). The replayed solver row likewise pools seeds 0–59 (+0.498 ± 0.097, n=60). The headline uses the locked n=30 only, and the last line, `HEADLINE`, recomputes it: +0.322 vs +0.499, 65% [24%, 98%]. It plays the solver and six baselines on the 40 frozen judge seeds, then runs the anti-cheat battery. It prints `ANTI-CHEAT: every probe blocked ...` (exit 1 if any cheat gets through), then the `HEADLINE` line: the 65% [24%, 98%] row above, recomputed from the committed episodes and diffed against the committed paired table (exit 1 on any difference). A `slow act()` line on stderr is a timing note from the solver, not an error.
- **Run-to-run variation.** Each run draws a fresh world secret, so the solver's judge-seed row moves between runs: hard +0.553 ± 0.093 in the committed [`results/judge_table.md`](results/judge_table.md), +0.643 ± 0.087 in our fresh-clone run. The spread over 300 fresh secrets is in [`results/solver_range/`](results/solver_range/), and `make accept` checks against it. do_nothing and stop_early are always exactly 0. `CANARY_WORLD_SECRET=<any string> make reproduce` gives bit-identical output.
- **Speed knobs.** `REPRO_ANTICHEAT=0` prints only the table (about 25–75 s on a laptop). `REPRO_FAST=1` shrinks the table to 5 seeds per tier, but it is not much faster: the anti-cheat verdict still uses all 40 judge seeds, because a 5-seed verdict raised false alarms.
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

**Oracle expected range:** a 10-task hard rerun of the oracle should land in about **+0.39 to +0.68** (90% of builds; mean +0.569, sd 0.094), and do_nothing, stop_early and cheat_probe score exactly 0 on every build. This was measured over 200 simulated builds: [harbor/README.md](harbor/README.md#expected-oracle-range-for-a-judge-rerun), [`results/oracle_range_v1.4.md`](results/oracle_range_v1.4.md). One wrong accusation (−1) moves a 10-task mean by more than 0.1. Each build draws a new secret, so nobody (us included) has seen the worlds your build serves. The reward is the game server's HMAC-signed ledger, and the agent container holds nothing that reveals the mole. Full details and the isolation proof: [harbor/README.md](harbor/README.md). If agent setup times out on a slow network or at high `-n`, add `--agent-setup-timeout-multiplier 3`: those trials are infrastructure failures, not scores.

## Tiebreak: a small model trained on Canary experience (honest result)
Qwen2.5-1.5B with LoRA, held-out seeds, the model plays every episode alone; full readout in [docs/reports/fr8.md](docs/reports/fr8.md) ("04:45 WS4 readout").

| model | held-out score ± 95% CI | n |
|---|---:|---:|
| base (untrained) | 0.000 (it cannot play: 3% valid tool calls) | 36 |
| v2 (SFT on solver play) | −0.457 ± 0.086 | 172 |
| v3-4k (GRPO on the environment's reward, Verda H100) | −0.147 ± 0.063 | 180 |
| v3-8k seed 2 (GRPO, 8k context, Verda H100 spot) | −0.050 ± 0.049 | 90 |

- **What was learned:** reward training fixed v2's reckless accusations (v3-4k vs v2: +0.310 ± 0.107, two-sample). It learned to play the protocol (100% valid calls), and on training states it learned to name the mole from evidence (0.19 → 0.89).
- **What was not:** the bar (above the untrained base, with the CI excluding 0) is **not met**. The model never learned to gather evidence in its own games: the same decision gemini-4-carbon gets wrong (fewer canaries, earlier commitment; [failure analysis](docs/reports/failure_analysis_v1.4.md)).
- **Final (08:55 on 15 Nov, `fr8/analysis/out/ws4_table_final.md` on branch `justSilas-fr8`):** seven trained runs, none above the base. v3-4k: −0.147 and −0.209; v3-8k: −0.060, −0.777, −0.050, −0.788 (the two ~650-step runs abstain, the two ~350-step runs over-accuse). Reward training (GRPO) beats imitation (v2) by +0.31 to +0.41. A DAgger round trained on the model's own states ended as an honest null (PR #90, not merged before the deadline): −0.542 ± 0.214 at 8k context (n=50, partial), level with v3-4k at 4k context; not above the base either.

## Links

- **Break it:** [docs/EXPLOITS.md](docs/EXPLOITS.md) lists every attack we tried, and the regression test that guards each one. `make hunt` fuzzes it yourself, with no keys, in a few minutes.
- **Gap report:** [docs/reports/gap.md](docs/reports/gap.md).
- **Submission write-up:** [docs/SUBMISSION.md](docs/SUBMISSION.md) (form fields, rubric map, judge commands, known limits).
- **Gemini entry:** [docs/gemini/SUBMISSION.md](docs/gemini/SUBMISSION.md).
- **Rules:** [docs/CONTRACT.md](docs/CONTRACT.md). **History** (tiers v1.2 and v1.3, earlier frontier runs, why the rules changed): [docs/HISTORY.md](docs/HISTORY.md).

---

## The rules, briefly

The full spec is [docs/CONTRACT.md](docs/CONTRACT.md); the agent receives every rate and rule as the MCP instructions. Exact values are in [`canary/rules.py`](canary/rules.py) (`TIERS_VERSION = "v1.4"`).

- **Tiers.**
  - **Easy** (sanity tier): 12 employees, 14 days, one canary per day with up to 3 variants. A leak surfaces the next day.
  - **Medium:** 20 employees, 14 days, one canary per day with up to 3 variants. A leak costs 0.04 of V.
  - **Hard:** 40 employees, 21 days, two canaries per day with up to 3 variants each. A leak costs 0.05 of V. Hard adds fingerprint noise: the feed shows the true variant 95% of the time. (Hard also lists a clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4.)
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

`make reproduce` runs the anti-cheat battery (designed by Vaishnav, ported from his Poisoned Inbox) on the same seeds and secret as the table: 14 scripted attack probes and 1 swarm probe, an effort ladder, and a replay of every committed episode and Harbor trial. `make anticheat-verify` reruns the committed 40-seed battery in [`results/anticheat/exploits.md`](results/anticheat/exploits.md) and expects `0 differences`.

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
