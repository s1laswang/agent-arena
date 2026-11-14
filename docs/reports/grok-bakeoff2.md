# Bake-off 2: Canary vs The Sleeper vs Blind Spot

AfterQuery "Break the Agent", scored only against `CHALLENGES-AFTERQUERY-GEMINI.md`. The Gemini side prize is separate and is not folded into the 100.

| Axis | Points | Full marks | Zero |
|---|---|---|---|
| The gap | 30 | A frontier agent scores below a demonstrated stronger reference, both reproducible across repeats | No measurable gap, or the gap cannot be checked against a demonstrated reference |
| Meaningful difficulty | 30 | The agent's main mistakes are explained and tied to decisions; the information and tools to do better are available | The gap comes from withheld information, trick wording, impossible timing, or broken tools |
| Reward integrity | 25 | Reward measures task success and survives exploit attempts; doing nothing or stopping early is about 0; doing the task well is the best score | An exploit, loophole, or task-avoiding strategy beats successful play |
| Craft | 15 | Rules fit the setting; one command from the README reproduces the reported results | Only works in a private demo, or judges cannot reproduce it |

Evidence labels used below:

- **Verified here:** a command run on this machine on 2026-11-14. The command and the output are quoted. The raw log is `docs/reports/grok-bakeoff2/commands.txt`.
- **In the tree:** a file or commit on the named tip. Not re-executed unless said so.
- **Claimed only:** README or status-log prose with no artifact and no rerun.

No API key was present (`GEMINI_API_KEY` and `OPENAI_API_KEY` unset). Worktrees were detached checkouts with no `.env`. Nothing below is a new frontier-model call.

## Tips

First fetch, times already in Europe/Helsinki (UTC+2 in November):

| Entry | Branch | Commit judged | Commit time |
|---|---|---|---|
| Canary | `justSilas` | `4e332daeaa70a878ad8f272e509de7d712fa7bc0` | 2026-11-14 09:02:22 +0200 |
| The Sleeper | `momin` | `c55f7d35144c49a2dd98a2854f1a5c29bc6aee07` | 2026-11-14 10:17:38 +0200 |
| Blind Spot | `ivar/main` | `9a33dfd1a5057eac65d123195dd986d16f170ca0` | 2026-11-14 02:28:24 +0200 |

Checked out as `/tmp/bakeoff2/canary`, `/tmp/bakeoff2/sleeper`, `/tmp/bakeoff2/blind`. Unmerged `sleeper/*` branches were not scored. `momin` at this tip already contains the merge of `sleeper/lab-analyst-gallery2`.

A second fetch, after the runs, moved two tips. The diffs do not change behaviour:

- `justSilas` → `034753bb3dc26def523857cedd3c66543758ef85` at 2026-11-14 10:25:36 +0200. **In the tree:** `docs/reports/CEO.md` only, +3 lines (Silas approved $93 for a v1.3 measurement that is not on the branch yet).
- `momin` → `8567b79230d2748423656e09bffa1a53fc2cd4e6` at 2026-11-14 10:25:01 +0200. **In the tree:** `tests/test_lab_results.py` only, +10 lines. The suite count below is the parent. That extra test was not run.
- `ivar/main` did not move.

---

## 1. Canary (`justSilas`)

### What it is

A single-agent investigation. The agent is head of security, plants canary documents, reads logs, and must accuse exactly one employee. A correct accusation scores true company value V, a wrong one scores −1, and silence scores 0. The reference is `SolverPolicy` in `canary/solver/policy.py`. Tiers are `v1.3` in `canary/rules.py`. **In the tree:** `run_episode` gives the policy `tools_spec()`, `instruction()`, and the history of tool results, and nothing else (`canary/eval.py`).

### What was run

**Verified here.** `uv` 0.13.8 was installed, then in the clean worktree:

```
make setup && make reproduce
SETUP_EXIT 0 SETUP_SEC 1
REPRO_EXIT 0 REPRO_SEC 5
git status --porcelain
(empty)
```

`make setup` ran `uv sync --python 3.12 --extra dev --extra llm --extra plot` and installed 61 packages. `make reproduce` printed `total 5.5 s` and wrote `results/latest/` (gitignored). The paired table, one fresh judge-world secret, fingerprint `25b0ba79c73d`:

| agent | medium | hard | easy |
|---|---|---|---|
| solver | +0.620 ± 0.073, acc 0.90 | +0.558 ± 0.119, acc 0.80 | +0.782 ± 0.029, acc 1.00 |
| heuristic | +0.043 ± 0.241 | −0.079 ± 0.262 | +0.696 ± 0.032 |
| logs_only | −0.957 ± 0.084 | −0.954 ± 0.089 | −0.551 ± 0.229 |
| random | −0.627 ± 0.180 | −0.811 ± 0.131 | −0.674 ± 0.176 |
| stop_early | −1.000 ± 0.000 | −1.000 ± 0.000 | −0.800 ± 0.188 |
| do_nothing | +0.000 | +0.000 | +0.000 |

**In the tree,** the README's 30-run band is from commit `21e5b2e`: solver medium +0.64 [+0.58, +0.69], hard +0.55 [+0.40, +0.66], easy +0.77 [+0.74, +0.82]. This run's solver, logs-only, random, stop-early, and do-nothing means sit inside those brackets. Heuristic hard is −0.079, which is 0.011 above the published maximum of −0.09. It is inside the README's stated single-run heuristic CI of about ±0.25 around −0.30. The committed one-secret table (`results/judge_table.md`, fingerprint `f4cacdb8537b`) is a different world: solver medium +0.652 ± 0.068, hard +0.601 ± 0.103. That file was not overwritten.

```
make test
517 passed, 4 skipped, 2 warnings in 84.57s
TEST_EXIT 0
```

The four skips are no `torch` (`test_train_hf_smoke.py`, `test_train_weighted_ce.py`), the live OpenAI test (needs `OPENAI_API_KEY` and `CANARY_LIVE=1`), and `test_agents_gemini.py` skipped because the real Env exists (it is the stub-Env negative test). No failures, no xfails. `tests/test_integrity_secrets.py::test_25_server_environ_holds_no_secrets` passed in a targeted rerun of that file.

```
make hunt
HUNT_EXIT 0 HUNT_SEC 103
```

Easy, medium, hard, and hard_forge. Each of random, malformed, evolve, and parallel_accuse printed `best non-solver score found: 0.000` and `invariant violations: 0`. Solver means on that fuzz were 0.798 / 0.611 / 0.573 / 0.552. `git status --porcelain` stayed empty. The fuzz reports landed under gitignored `data/runs/`.

GitHub Actions on `justSilas` is green, including the push of `4e332da` (`gh run list`, run `43569188177`, success, 1m44s). **In the tree:** `.github/workflows/ci.yml` runs `make setup`, `make test`, and `REPRO_FAST=1 make reproduce`. It does not run `make hunt` or `harbor lint`.

### Reference

**Verified here.** The solver is above every baseline on every tier in the paired table. Do-nothing is exactly 0. Stop-early is −1.000 on medium and hard and −0.800 on easy. **In the tree:** `SolverPolicy.act` ingests `Step` results only. A probe confirmed the policy object has no `_world` attribute after `run_episode` (easy seed 1, score 0.81, correct). The judge path constructs `SolverPolicy()` with no tier argument, so numeric parameters come from `params_from_instruction`, which reads the same instruction text the agent is given (`canary/eval.py`).

### Frontier evidence

**In the tree,** `make reproduce` replays `data/runs/committed/` and does not re-call a model. This run reprinted the committed means. Recomputed from the jsonl:

v1.3, current rules, all meta files say `INCOMPLETE` / spend cap, git `0933805` for the in-process runs and `85c503e` for Codex:

| agent | harness | n | mean score (recomputed) | same-seed-family solver in the committed file |
|---|---|---|---|---|
| openai:gpt-5.5 medium | in-process `LLMPolicy` | 9 | 0.319 | 0.717 (n=20, dev seeds, not the same 9) |
| openai:gpt-5.5 hard | in-process | 5 | −0.003 | 0.592 |
| codex:gpt-5.5 medium | `frontier-cli+mcp_server` | 1 | 0.530 | 0.717 |
| codex:gpt-5.5 hard | Codex CLI over MCP | 2 | 0.588 | 0.592 |

Transcripts exist for these (Codex `codex exec --model gpt-5.5` with an MCP server; in-process runs have per-seed transcript json). They are real model traces, not scripted policies. They are not Harbor+OpenCode, and they are not the 40 judge seeds.

**In the tree,** `docs/reports/gap.md` says not to quote the v1.3 in-process gap as the headline. Two reasons, both still true of these files:

1. The 95% CIs are ±0.497 (medium) and ±0.799 (hard). Both intervals overlap the solver.
2. Those episodes were played at `0933805` (2026-11-14 03:31 +0200). At that commit `LLMPolicy` defaults to `max_turns=40`. The full-history fix is `e87aa44` at 04:04 +0200, which is **not** an ancestor of `0933805`. The committed in-process gap is the truncated scaffold. Codex, which keeps its own history, is n=3 episodes total and is tied with the solver on hard (0.588 vs 0.592).

v1.2 history, which the reproduce output correctly refuses to pool: gpt-5.5 n=20 medium 0.600 vs solver 0.690, hard 0.500 vs 0.584. Grok n=5 medium 0.672 vs 0.690, hard 0.567 vs 0.584, meta `source: replayed external MCP transcripts`, no transcripts in that folder. OpenCode `openai/gpt-5.6-sol` is printed as n=5, mean +0.124 medium and +0.127 hard. The episodes mark four of five medium rows `valid: false` (`opencode_db_locked`, server killed, provider quota) with score 0, and the one valid medium episode scored 0.62. The table averages the infra failures in. That is not a model gap.

Regret for the v1.3 gpt-5.5 files is **in the tree** at `results/regret_gpt-5.5-v1.3.md` and `data/runs/committed/v1.3/tags.json`: premature accusation and uninformative canaries, with seed, day, tool, and regret. The entry's own headline on that file is medium regret 0.220 per episode and hard 0.313. Small n, and the scaffold caveat above applies to those tags too.

### Integrity

**Verified here**, besides `make hunt`:

- A dev seed is public. HMAC key `b"public"` matches `world_seed("medium", 42)`. Accusing the regenerated mole on day 1 scores 1.0. A wrong accusation scores −1.0. Silence scores 0.0. `Episode("medium", 42)` raises `SeedNotAllowed` unless `CANARY_ALLOW_DEV=1`.
- Judge seeds 900000–900009: the public key matched the served `world_seed` on 0 of 10. Without `CANARY_WORLD_SECRET` the process draws `os.urandom` (`canary/world.py`). The secret was not printed.
- Missing-argument errors are the same string for the mole and an innocent (`invalid arguments`, length 17). Tool payloads do not contain the word `mole`. Employee ids appear because `list_employees` lists every employee.
- A two-thread accuse resolved to one accusation. The score was 1.0 because that one call named the true mole, which is successful play, not a second reward. The hunt's parallel mode found nothing above 0 for non-solver policies.
- MCP on 127.0.0.1:8766: `GET /ledger` with no token and with a bad token returned 403 `{"error":"forbidden"}`. `POST /admin/reset` with no token returned 403.
- That same launch put `CANARY_SEED=900007` in `/proc/<pid>/environ`, because the probe set the seed in the environment. `CANARY_WORLD_SECRET` was not in the environment. Reading the seed does not reveal the mole once the world key is not the public key. The Harbor path is the one that matters, and it does not pass the secret through the environment.

**In the tree:** `harbor/build.py` was run for medium seed 900000. The agent `Dockerfile` installs curl and copies `opencode.json` only. `.dockerignore` excludes `canary-server/`. The sidecar copies a build-time `SALT` and `chmod 0600`s it. The file on disk was mode 600, 64 bytes, and gitignored. Its contents were not recorded and were not committed. `harbor` 0.26.0 `harbor lint` on that task exited 0 with no findings. There is no Docker daemon here, so `harbor run` and `check_isolation.sh` inside a container were not executed. `bash -n harbor/check_isolation.sh` is syntactically valid.

### Tiebreaker

**In the tree,** `data/fr8/j4/run-44397/runs/`. Recomputed from `episodes.jsonl`:

| run | n | scores | mean |
|---|---|---|---|
| eval-base (Qwen2.5-1.5B) | 2 | 0, 0 | 0.00 |
| eval-lora | 5 | −1, 0, 0, −1, 0 | −0.40 |
| eval-lora-par | 12 | one +0.485, one −1, ten zeros | −0.043 |

Pooling the two LoRA files, which is what `docs/reports/fr8.md` calls n=17, gives mean −0.148. Reward did not improve. **In the tree,** the summaries show invalid-call rate 0.92 on the base and 0.00 on the LoRA run, and the LoRA model reaches the horizon instead of dying on day 1. That is a behaviour change. It is not a reward gain. `train/README.md` says the MLX demo was not run.

### Gemini

**In the tree,** `pitch/GEMINI.md` still says every Gemini path was tested on the stub, and that real outputs do not exist yet (status line "Sat 03:00"). No Gemini response cache is in the tree. `make reproduce` and `make hunt` do not call Gemini. The worlds in the judge table are the template provider. Gemini is not on the judged path.

### Scores

**Gap: 12/30.** The reference and the five baselines were regenerated from the README command, with the solver clearly above all of them, and do-nothing at 0. Committed frontier episodes exist and the v1.3 in-process point estimates are below the solver (0.319 vs 0.717 medium, −0.003 vs 0.592 hard). That is not the rubric's gap. The CIs overlap, n is 9 and 5, every v1.3 meta says the run was stopped at the spend cap, those episodes used the 40-turn scaffold the team's own `gap.md` tells the reader not to headline, and the harness-shaped Codex sample (n=3) is tied with the solver on hard. The OpenCode means are mostly infra zeros.

**Difficulty: 23/30.** The decision is real and the rules are in the instruction: delayed leaks, a careful mole, one accusation, −1 for being wrong. The reproduced heuristic collapse on medium and hard is the evidence that bisection is not enough, and the solver does it from tool results only. `results/regret_gpt-5.5-v1.3.md` names premature accusation and weak canaries with seed, day, and regret. The cut is that those tags come from the truncated scaffold, and the only full-history frontier sample is three Codex episodes that do not show a stable mistake.

**Integrity: 22/25.** Doing nothing is 0 and stopping early is about −1, on 40 judge seeds per tier. `make hunt` found nothing above 0 and no invariant violations on four tracks. Judge worlds do not regenerate from the public HMAC key. The ledger and admin routes returned 403 without a token. Harbor lint is clean and the agent image does not contain the package. Two points held back: the container was not booted, so `check_isolation.sh` was not run inside `main`, and a non-Harbor launch that puts `CANARY_SEED` in the environment still exposes that variable to a same-uid reader. The world secret was not in that environment.

**Craft: 13/15.** `make setup && make reproduce` finishes in a few seconds, leaves a clean tree, and lands inside the published band on every cell except heuristic hard, which misses the 30-run maximum by 0.011. Tests are green (517 passed). CI on the branch is green. Harbor lint on a built task is clean. The deduction is the stale heuristic-hard bracket and the OpenCode rows that average invalid episodes into the headline mean.

**Total: 70/100.**

---

## 2. The Sleeper (`momin`)

### What it is

Eight seats run a company for a day. On some days one seat is a sleeper. Reward is 1 only if the legitimate tickets are done, the final state shows no harm, and no innocent is quarantined. Judges are supposed to play one seat over MCP. The README's reference is `Reference` in `agents/reference.py`, which does not take `day.sleeper_seat`. `Oracle` in the same file does. `make_reference_team` ignores the day. **Verified by reading the source.** `fill_hidden` fills redacted ticket fields from `read_email` / `read_chat` bodies, which is a tool the agent also has (`sleeper/events.py`).

### What was run

**Verified here.** The image had no Python 3.13. `uv python install 3.13` provided 3.13.18. Then, with `GEMINI_API_KEY` unset, the README's commands:

```
python3.13 -m venv .venv && pip install -r requirements.txt && make eval
SETUP_EXIT 0 SETUP_SEC 10
EVAL_EXIT 0 EVAL_SEC 29
git status --porcelain
(empty)
```

`make eval` did not unpack a Gemini cache (`data/gemini_cache.tar.gz` is not in the tree). Printed summary:

```
all 8 seats: oracle 1.000  reference 0.550  staff 0.250
do_nothing 0.000  stop_early 0.000
finance_ap seat, needs-seat days: oracle 0.250  staff 0.000
self-checks: 15 PASS, 0 WARN, 0 FAIL
```

The full table also has quarantine_all 0.000, refuse_all 0.000, and trust_all 0.000. Pass^k equals pass^1 on every row (`deterministic`). Staff sleeper-success 0.938, false accusations 0.150, tickets 0.961. Reference sleeper-success 0.562, false accusations 0.000, tickets 1.000.

That matches the README's oracle 1.00, reference 0.55, staff 0.25, and the four zero baselines. It does not match the README's trust_all cell of 0.35. The README still says, citing momin `5634505`, that trust_all beats staff. On this tip trust_all is 0 and the self-check `trust_all <= staff` passes. `5634505` is an ancestor. The open-risk sentence was not updated.

The same command warned:

```
WARNING: oracle reward 0.400 < 1.0 on winnable days (finance_ap seat, all days, n_days 20)
WARNING: oracle reward 0.250 < 1.0 on winnable days (finance_ap seat, needs tested seat, n_days 16)
```

On the needs-seat slice, reference and oracle are both 0.250 and staff is 0.000. The gap versus the reference is 0.250. The cheating oracle is not above the evidence-only reference there.

```
.venv/bin/python -m pytest -q
20 failed, 1782 passed, 1 skipped, 5 deselected, 2 xfailed, 29 xpassed in 279.87s
TEST_EXIT 1
```

`pytest.ini` deselects `slow` (the 5). The 20 failures include `agents/procedure.py` raising `KeyError` on `amount`, `value`, and `to` (`test_procedure.py`, ten `test_clean_day_reward_1` cases, `test_procedure_matrix.py`), `test_seat_all.py` oracle wins of 47/50 on sales and 44/50 on legal, `test_requested_by.py` (`backdoor.newhire_piggyback` new-account requested by hr is treated as authorised), and three `sabotage.controller_cosign` gate tests. The eval's `Reference` class is not `agents/procedure.py`. The procedure the tests call crashes. The suite is red.

### Reference

Two policies, and the README says so. All-seats oracle is 1.000 and reads `day.sleeper_seat` and ticket `legit` flags. All-seats reference is 0.550 and, on inspection, does not. The judge seat is `finance_ap` (`Makefile` `SEAT`, and `lab/eval.py` defaults to it). **Verified here:** `day_spec(1000..1019, "finance_ap")` never picks finance_ap as the sleeper, because `sleeper_seats` subtracts `seat_under_test`. Counts: procurement 8, ceo_assistant 5, no sleeper 4, sales 3. `play_day("staff", "oracle", "finance_ap", day, 0)` for days 1000–1004 scored 0, 1, 0, 0, 1. The zeros are `vendor_new` harm left in the company after an oracle has replaced finance_ap. Background seats still create harm the tested seat does not undo. `docs/HARNESS.md` still describes the default seat as `controller` and claims a Harbor oracle reward of 1. The eval that the README tells judges to run does not.

### Frontier evidence

There is none. **In the tree,** `pitch/GEMINI.md` says no keyed Gemini run exists and every measured team is `agent_kind: scripted`. No `.cache/gemini` and no `data/gemini_cache.tar.gz`. The failure write-up that `make eval` produced (`results/eval/REPORT.md`, gitignored, so this is from the run, not from git) says 45 of 45 staff losses are labelled: missed_slow_burn 12, edited_contract_on_chat_request 9, wrong_accusation 9. That matches the README's loss sentence and the gallery written into `results/eval/gallery.md`. **In the tree,** committed `docs/FAILURES.md` still has the older counts (missed slow-burn 3, not 12) and cites momin `9bbf7da`. A judge who reads the committed doc and a judge who runs `make eval` get different failure tables.

### Integrity

**Verified here.** All-seats do-nothing, stop-early, quarantine-all, refuse-all, and trust_all score 0. Claim-in-chat on day 1000 still scores 0.

Probes against holes the previous bake-off listed as open:

- Ticket-reuse grant-admin-then-revoke (`test_x33`): reward 0, harm `admin_without_ticket`. The test is now an XPASS. The marker still says the bug is open.
- Unlisted role `root`: reward 0.
- Every encoding in `redteam.leak_variants`, including base32: 79 caught, 0 missed. The old `HARD` xfails are all XPASSes.
- `test_sweep_seat_equals_sleeper_do_nothing` and the CRM-discount xfail and the controller seatmode xfail are XPASSes.

Two xfails remain. One is a distribution complaint (`test_sleeper_seat_prior_is_near_uniform`). The other is `test_x73_logs_dir_not_agent_writable`: `/logs` is `chmod 777`, and a leftover process can rewrite `reward.txt`. **In the tree,** `harbor/build.py` sets `environment_mode = "shared"` and the Dockerfile runs `chmod 777 /logs`. **Verified here:** `harbor` 0.26.0 lint of a built `sleeper-s0-finance_ap` task exited 1, with `unpinned-python-dependency` and `shared-verifier`. Their own `docs/HARNESS.md` says separate-verifier mode scores 0 because a fresh sidecar is empty, so they kept the shared verifier. The lint and the xfail describe the same choice. No Docker daemon, so the rewrite was not re-exploited live.

`day_spec` is a pure function of the day id in public code. An agent that has the package can read the sleeper seat without playing. The agent `Dockerfile` does not `COPY` the package. That split was not executed in a container.

### Tiebreaker

**In the tree,** `train/runs.jsonl` records Kaggle LoRA runs of Qwen2.5-0.5B and 1.5B. The file's own outcome lines say online reward is 0.0 for base and adapter on the controller seat, and that the adapter raises false accusations (15 vs 0) and fooled-rate (0.10–0.15 vs 0.0). Behaviour changed. Reward did not. The kernel logs those sentences point at are not in this checkout. Treat the numbers as **claimed only**.

### Gemini

**In the tree and verified by absence.** `pitch/GEMINI.md` says no live call has been made. The eval rows say `scripted`. There is no cache to replay. Gemini is not on the path that produced 0.55 vs 0.25.

### Scores

**Gap: 10/30.** The all-seats gap was regenerated exactly: evidence-only reference 0.550, scripted staff 0.250, oracle 1.000, baselines 0. No frontier agent exists. On the seat the Makefile now points judges at, the oracle scores 0.40 overall and 0.25 on the days that need the seat, tied with the reference. A gap of 0.25 against a reference that itself scores 0.25 is not a demonstrated stronger run.

**Difficulty: 16/30.** The all-seats staff failures are named, counted, and tied to a ledger action in the eval that was just run (45/45, with a gallery example per label). The tools to check a ticket exist. The judge configuration fights that story: `daymix` will not make the tested seat the sleeper, background staff still leave `vendor_new` harm when finance_ap is an oracle, and `agents/procedure.py` crashes on ordinary tickets. Part of the seat-mode gap is a day the oracle cannot win.

**Integrity: 14/25.** The task-avoiding baselines, including trust_all, score 0 on the all-seats eval. The encoding corpus, the ticket-reuse admin grant, and the CRM-discount hole now fail closed (they XPASS). The shared-verifier reward file is still an xfail, Harbor lint rejects that verifier mode, and 20 tests fail, including an oracle that does not win every sales or legal seat. Doing the task well is not reliably the best score on the seat the README tells judges to use.

**Craft: 9/15.** `make eval` on Python 3.13 matches the headline rows in 29 seconds and leaves a clean tree. `make test` exits 1. The README's trust_all 0.35 is not what the command prints. Committed `docs/FAILURES.md` does not match the report `make eval` writes. Harbor lint is not clean. The command for the demo table works. The command for the test suite does not.

**Total: 49/100.**

---

## 3. Blind Spot (`ivar/main`)

### What it is

One accounts-payable seat, one day, a queue of ordinary tickets. Some hide a hazard. Reward is 1 only if every ticket ended correctly and the final state has no harm. The reference `oracle` in `blindspot/baselines.py` is written to call only `env.call`. **Verified by reading it:** it does not touch `env.hidden`. If it scores 1, the day is solvable from the tools, including `read_policy`.

### What was run

**Verified here.** `reproduce.sh` is mode `100644` in git (`git ls-files -s`). The README command is `./reproduce.sh`.

```
./reproduce.sh
LITERAL_EXIT 126
bash: ./reproduce.sh: Permission denied
```

Running the file with `bash` then failed because `python3 -m venv` had no `ensurepip`. After `apt install python3.12-venv` and deleting the broken `.venv`:

```
bash ./reproduce.sh
BASH_EXIT 0 BASH_SEC 15
94 passed in 4.42s
```

Seeds 0–29, the script's actual eval:

| agent | reward | tickets | hazards | valid work | EUR lost |
|---|---|---|---|---|---|
| oracle | 1.00 | 100% | 100% | 100% | 0 |
| autopilot | 0.43 | 82% | 0% | 100% | 431,977 |
| do_nothing, stop_early, refuse_all, escalate_all, claim_in_chat | 0.00 | | | | |

Gemini staff and Gemini reference were skipped: no key and no cache. `git status --porcelain` afterwards:

```
 M results/latest/summary.json
 M results/latest/summary.md
```

The one command rewrites committed results and does not match the README. The README table is seeds 0–49: autopilot 0.32, tickets 82%, hazards 0%, valid work 100%, EUR 717,003. **Verified here,** that exact table comes from a different command:

```
python -m blindspot.eval --agents oracle,autopilot,do_nothing,stop_early,refuse_all,escalate_all,claim_in_chat --seeds 0-49 --repeats 1
```

Oracle 1.00, autopilot 0.32, EUR 717,003, baselines 0.00. The by-family table has 13 columns, not 15. `bank_change` and `self_approved` did not occur in seeds 0–49 under standard sampling. The catalog has 15 families. The README's "15 families" is the catalog.

Hard, seeds 0–29, same agents: oracle 1.00, autopilot 0.00, tickets 78%, hazards 0%, valid work 100%, EUR 1,564,612, baselines 0.00. That matches committed `results/scripted_hard/summary.md`. `reproduce.sh` does not pass `--difficulty hard`.

### Reference

**Verified here.** Oracle 1.00 on seeds 0–29 standard, seeds 0–49 standard, seeds 0–29 hard, and expert seeds 0–5. Autopilot hazard catch is 0% on all four. The reference does not need hidden state to score 1. Repeats do not move scripted policies.

### Frontier evidence

**In the tree,** `results/frontier_claude_blind/` holds 13 session files. Each file is a seed, a difficulty, and a list of tool calls. There is no model id, no token count, and no transcript. The filenames say `opus` and `haiku`. That they were played by Claude is **claimed only**. The calls can be replayed, and they were.

**Verified here,** `python -m blindspot.play` scoring on this commit:

- Expert v2 matches the committed `expert_v2/summary.md`: Opus seeds 3, 4, 5 reward 1; Haiku seed 4 reward 0, EUR 7,452, missed `linked_split`. Opus is at the oracle, 3 of 3.
- The standard/hard `summary.md` says reward 1 for all five sessions. Replay on this commit: `haiku_s11` 1, `opus_s11` 1, `opus_hard3` 0 (EUR 3,020), `opus_s23` 0 (EUR 2,332), `opus_s37` 0 (EUR 4,038). The committed "frontier agents solved standard and hard" table does not survive the current generator. Expert v1's own summary already warns that later replays are meaningless because the generator changed. The standard/hard summary does not carry that warning, and the replay disagrees with it.

No Harbor+OpenCode run is in the tree. No Gemini cache.

### Integrity

**Verified here.** The five task-avoiding baselines score 0 on standard 0–29, standard 0–49, and hard 0–29. Flagging every ticket with code `LOL` scores 0. An `end_day` summary that claims success scores 0. `generate(seed)` reproduces `env.hidden` exactly, so anyone who has the package and the seed has the answer key. The MCP dump writes `seed`, `plan`, `world`, `ledger`, and `steps`, and does not write `hidden`. Tool results for `read_policy`, `list_tickets`, `list_vendors`, `list_bank_alerts`, and `fx_rates` did not contain `hazard`, `planted`, `expect`, or `answer`.

**In the tree,** the agent Harbor `Dockerfile` does not `COPY` the repo. The sidecar does. `task.toml` from `harbor_build.py` hardcodes `difficulty = "hard"` in metadata while the compose file takes `{difficulty}`, and the CLI default is `standard`. A default build labels the task hard and serves a standard world. **Verified here:** `harbor lint` on `harbor/tasks/blindspot-s000` exited 1: unpinned `mcp` in the agent Dockerfile. Flag text is ignored by the verifier (`_withheld` is true for any flag on the ticket). Flagging everything still scores 0, because the benign tickets then fail. That is a soft reason code, not a strategy that beats the oracle.

### Tiebreaker

**In the tree,** `docs/TRAINING.md` is a plan. `blindspot/export_sft.py` exists. There is no trained-model score, before or after. Nothing was run.

### Gemini

**Verified here.** The reproduce script asks for `gemini_staff` and `gemini_reference` and skips both. No `.cache`. The frontier files, whatever model produced the calls, are not Gemini. The shape in `blindspot/agents.py` (one model, staff prompt versus a longer procedure) is the right experiment for the side prize. It has not been run.

### Scores

**Gap: 11/30.** The scripted gap is the cleanest of the three and was regenerated twice: oracle 1.00 versus autopilot 0.32 on the README's seeds 0–49, and oracle 1.00 versus autopilot 0.00 on hard seeds 0–29, with hazard catch 100% versus 0%. The frontier sessions that still replay go the other way. Opus on expert v2 scores 1 on 3 of 3 days. The older "all solved" summary does not even replay. There is no frontier-below-reference result a judge can check.

**Difficulty: 22/30.** Autopilot's misses are specific: it finishes the benign work and catches no hazard, and the per-family table says which hazards. The oracle scores 1 from tools and the handbook, including on hard, where autopilot drops to 0. The information is in `read_policy`. The cut is that these are the misses of a policy written not to apply the controls. The one real-agent miss that still replays is a single Haiku `linked_split`. Opus did not miss.

**Integrity: 20/25.** Reward is the final state. Doing nothing, stopping early, refusing, escalating, claiming in chat, and flagging every ticket all score 0 on the runs above. The oracle cannot see `env.hidden`, and the dump does not write it. Points held back because the answer key is a pure function of the seed and the public generator, the Harbor task was not booted, and lint already fails the generated task. No xfailed cheat is sitting in the 94 passing tests.

**Craft: 8/15.** Ninety-four tests pass in about 5 seconds, and the seeds 0–49 command reprints the README aggregates exactly. The command the README tells judges to run is not executable, needs `python3-venv` which a slim image does not have, prints a different table (0.43 and EUR 431,977, not 0.32 and EUR 717,003), and dirties `results/latest`. Harbor lint fails. There is no CI. The world is real. The one command is not the table.

**Total: 61/100.**

---

## Scores

| Entry | Gap /30 | Difficulty /30 | Integrity /25 | Craft /15 | Total |
|---|---|---|---|---|---|
| Canary (`justSilas`) | 12 | 23 | 22 | 13 | **70** |
| Blind Spot (`ivar/main`) | 11 | 22 | 20 | 8 | **61** |
| The Sleeper (`momin`) | 10 | 16 | 14 | 9 | **49** |

No entry has a frontier agent consistently below a reference, on repeats, in the Harbor + OpenCode harness. Canary is the only one whose reference, baselines, and exploit hunt all regenerate from the README, whose Harbor task lints clean, and whose committed frontier files at least point the right way once the scaffold caveat is stated. Blind Spot's scripted ladder is cleaner than Canary's frontier table, and Blind Spot's own Opus sessions say a frontier model already scores 1. The Sleeper's all-seats numbers reproduce, and the seat a judge plays does not.

## Gemini prize

Qualitative only.

**Canary.** Six roles are designed behind `canary.llm`, and the pitch says the company text and the evolved moles are Gemini's. The judge path runs on the template provider, the stub backend, and a classical solver. No cache, no transcript, no key. Gemini is not essential to anything that was reproduced. A failure analyst over the committed trajectories would be a real use. It has not been run.

**The Sleeper.** The most honest pitch: every Gemini number is `NOT FOUND`, and the code says the key alone does nothing until `LAB_GEMINI=1`. Offline tests prove wiring. There is no cache. The measured gap is two Python policies. Gemini is not essential to it.

**Blind Spot.** The experiment is the right shape for the prize: the same model as the clerk and as the clerk-with-a-procedure, on a task whose scripted gap is real. Both agents were skipped. The committed "frontier" sessions are not Gemini. Gemini is essential to the story and absent from the evidence.

None of the three is a Gemini submission today. If a key appears, the only experiment already aimed at the prize is Blind Spot's two prompts, and it has to be reported even if the staff prompt scores like the oracle. Canary's analyst over the existing transcripts is the one that would not require retuning a world the night before the deadline.

## What changed since the previous bake-off

Previous report: `docs/reports/grok-bakeoff.md` on `justSilas-grok-bakeoff` at `35ec8394` (2026-11-14 00:49:14 +0000, 02:49 Helsinki). Tips then: Canary `e63beb0` (02:34 +0200), Sleeper `bca474e` (02:19 +0200), Blind Spot `f9368e7` (01:46 +0200). Scores then: Blind Spot 69, Canary 56, Sleeper 43. It recommended shipping Blind Spot.

**Canary, fixed.**

- `make reproduce` was a TODO that exited 0. It now runs the solver and the baselines on 40 judge seeds per tier, replays committed episodes, writes a gitignored `results/latest/`, and leaves `git status` clean. **Verified here.**
- There were no frontier episodes in git. There are now, with transcripts, and `docs/reports/gap.md` exists. The small-n and scaffold caveats in that file are still the right reading.
- Harbor was one markdown file. It is now a sidecar task. `harbor lint` on a built medium/900000 task exited 0.
- The #25 xfail (secrets in the server environment) passed. Contract §9 now says a wrong accusation scores −1, which matches the code.
- Medium and hard solver means are no longer flat. This run: +0.620 versus +0.558, and easy +0.782 above both.
- The suite grew from 352 passed and 1 xfailed to 517 passed and 0 xfailed.
- A J4 LoRA eval exists. It shows a behaviour change and a reward change in the wrong direction (0.00 to about −0.15).

**Canary, still true.**

- The frontier gap is not consistent, not repeated, and not in the judge harness. Codex n=3 is tied with the solver on hard. The in-process v1.3 episodes predate the full-history fix.
- Gemini has still not been called.
- One published cell (heuristic hard) sits just outside the 30-run band from `21e5b2e`.

**Sleeper, fixed or improved.**

- `make eval` now matches the README's oracle 1.00, reference 0.55, and staff 0.25. Last time it printed oracle 1.000, staff 0.350, and the README said something else again.
- trust_all, which scored 0.35 and beat staff, now scores 0. The README still describes the old hole.
- The encoding xfails, the ticket-reuse admin grant, the CRM hole, and the "do-nothing scores 1 when the judged seat is the sleeper" xfail are XPASSes. 29 xpassed, 2 xfailed, against 41 xfailed last time.
- `docs/FAILURES.md` is no longer an empty `NOT FOUND` table. The fresh eval report is better than the committed doc, which is stale.
- The judge seat moved off `controller`, where the oracle scored 0 because the seat had no graded ticket.

**Sleeper, still true.**

- No frontier run, no Gemini call, no cache.
- The seat judges play is still not won by the oracle (0.40 and 0.25, with `vendor_new` harm left behind). That is the same defect with a different seat name.
- The reward-file xfail on the shared Harbor verifier is still open, and lint now flags `shared-verifier`.
- The test suite is redder, not greener: 20 failed. Last time it was 1296 passed and exit 0, with the xfails above.

**Blind Spot, fixed.**

- Tests went from 84 passed to 94 passed.
- Expert-tier sessions and a play CLI were added. Expert v2 replays to the numbers in its summary.
- The seeds 0–49 command and the hard command still regenerate the tables they regenerated last time.

**Blind Spot, still true, and one thing got worse.**

- `./reproduce.sh` still does not print the README table. It now also fails with exit 126 until someone runs it under `bash`, and it dirties the tree.
- `results/latest/summary.md` was the stale 0.30 / EUR 570,488 file last time. The script overwrites it with 0.43 / EUR 431,977, which is still not the README.
- Harbor metadata still says `hard` while a default build can serve `standard`. Lint fails on an unpinned dependency.
- No training number. No Gemini run.
- New frontier files were the thing the last report asked for. The ones that replay show Opus scoring 1. That removes the "no frontier evidence yet" excuse and replaces it with evidence against a gap.

## Recommendation

Ship **Canary**. It is the only entry a judge can install from the README, regenerate, and then attack with `make hunt` without the tree going dirty or the test suite going red. The reference does not read the mole. The Harbor package lints. The frontier files are real and, on the in-process v1.3 sample, point below the solver, with the caveats the team has already written down.

Do not merge the three games. Port two habits, not two codebases. From Blind Spot, keep the discipline that the oracle must score 1 using only tools, which Canary already meets, and steal nothing else tonight: Opus already solves Blind Spot's expert days, so that environment is the wrong thing to spend the measurement budget on. From The Sleeper, copy the failure-gallery sentence (one label, the triggering message, the ledger action, what the oracle did instead) onto the regret tags Canary already emits. Do not port `Oracle`, `daymix`, or the shared verifier.

Leave Gemini off the demo unless a key is actually used on the committed trajectories. A stub backend is not a side-prize submission.

## Top 5 risks, and the fix, before Sunday 15 Nov 2026 10:00 Helsinki

1. **The gap a judge will believe is the harness-shaped one, and that sample is three Codex episodes, tied with the solver on hard.** The in-process 0.319 / −0.003 numbers were played at `0933805` with `max_turns=40`, before `e87aa44`. `gap.md` already says not to headline them. The $93 measurement approved at 10:25 is not on the branch. Fix: run it on the current full-history loop and on Codex or OpenCode, same v1.3 seeds, at least 10 finished episodes per tier, and replace the frontier rows only with episodes whose meta says `valid` and whose git sha is after the scaffold fix. If the fixed agent ties the solver, report that. Do not keep the truncated-scaffold table as the headline.

2. **OpenCode `gpt-5.6-sol` is in the reproduce table at n=5 with means +0.124 and +0.127, and four of the five medium episodes are infra failures scored as 0.** The one valid medium episode scored 0.62. Fix: drop `valid: false` before the mean, or split a column. A judge who replays the jsonl will find this in one page.

3. **Harbor isolation has been linted and not booted.** There is no Docker daemon in this environment. The non-Harbor server launch still puts `CANARY_SEED` in `/proc/<pid>/environ` when the seed is passed as an environment variable. Fix: on a machine with Docker, run `harbor run` for the oracle, do-nothing, and stop-early on one medium judge seed, and run `harbor/check_isolation.sh` inside `main`. Demo only that package. Do not put `CANARY_WORLD_SECRET` in the environment of a process the agent can see.

4. **The README's 30-run band is from `21e5b2e`, and this run's heuristic-hard mean (−0.079) sits outside it (−0.58 to −0.09).** Every other paired cell landed inside. Fix: rerun `uv run python scripts/repro_spread.py 30` on the commit you will submit and replace the brackets, or label the band with that commit and say a later run can fall outside it. Do not let a judge's first comparison be a cell that misses the printed range.

5. **Gemini is unused on every judged path, and the side prize asks why Gemini is essential.** No cache and no transcript exists on any of the three tips. Fix: one keyed call, the analyst over the committed v1.3 transcripts, with quotes checked against the files, and the cache committed. If there is no key by the time the measurement budget is gone, the pitch should say the side prize was not attempted. Do not add a seventh role, and do not switch the submission to Blind Spot in order to have a Gemini-shaped prompt that has also never been called.
