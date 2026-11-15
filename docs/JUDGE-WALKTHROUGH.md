# Canary: Judge Verification and Peer-Review Walkthrough

**Submission:** AfterQuery "Break the Agent" (branch `justSilas`) | **One-page card:** [`JUDGE_QUICKSTART.md`](../JUDGE_QUICKSTART.md)  
**Frozen rules:** `TIERS_VERSION = "v1.4"` (SHA-256 prefix `a8f99c2537c91d72` in [`canary/rules.py`](../canary/rules.py))  
**Headline claim:** In the judges' own harness (OpenCode + `google/gemini-4-carbon` over MCP) on Canary's hard tier (`n=30` locked dev seeds `0-29`, paired with the reference solver on identical worlds), `gemini-4-carbon` earns **`+0.322 +/- 0.199` vs `+0.499 +/- 0.119`** - **`65% [24%, 98%]`** raw and **`72% [52%, 91%]`** luck-adjusted - while `do_nothing`, `stop_early`, and `cheat_probe` score **exactly `0.000`**.

Every command in Section 1 and every audit/replay command in Section 2 runs locally with **no API keys** and leaves tracked files untouched (`results/latest/` is gitignored). Docker and a model API key are needed only if you want to run fresh Harbor + OpenCode rollouts yourself.

---

## 1. 2-Minute Quick Verification Card (Keyless)

Run these commands from the repository root (requires `uv` and GNU `make` on Linux or macOS):

```bash
# 1) Install Python 3.12 + dependencies and run the full keyless reproduction (~1-2 min)
make setup && make reproduce

# 2) End-to-end acceptance gate: setup, reproduce, +/-4 SD baseline bands, live HTTP MCP smoke (~2 min)
make accept

# 3) Recompute the v1.4 paired bootstrap gap table (10,000 resamples) from committed trajectories (~14 s)
uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29

# 4) Replay hard seed 4 in a fresh Env and inspect the day-by-day solver vs Gemini divergence (~0.5 s)
uv run python scripts/demo_replay.py --seed 4 --verify

# 5) Re-play all 90 v1.4 hard episodes (OpenCode, in-process, solver) and verify exact V accounting (~1 min)
uv run python scripts/failure_analysis_v14.py --check   # or omit --check: uv run python scripts/failure_analysis_v14.py

# 6) Re-run the 40-judge-seed x 3-tier anti-cheat battery and diff against committed exploits.json (~2 min)
make anticheat-verify

# 7) Build (<1 s) and serve the real Canary package in Pyodide at http://localhost:8000
make game-serve
```

### Expected outputs at a glance

| Command | Wall-clock | Exact pass / output check |
|---|---:|---|
| `make setup && make reproduce` | ~1-2 min | Writes gitignored `results/latest/judge_table.md`; replays committed runs (table pools `n=32` hard OpenCode `+0.349 +/- 0.190` incl. 2 extension seeds and `n=60` solver `+0.498 +/- 0.097`); plays solver + 6 baselines on 40 judge seeds (`900000-900039`); prints `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent` and a final `HEADLINE` line recomputing locked `n=30` (`+0.322 +/- 0.199` vs `+0.499`, `65% [24%, 98%]`, luck-adj. `72% [52%, 91%]`; exit `0`). Use `REPRO_ANTICHEAT=0` (~25-75 s) for table-only or `CANARY_WORLD_SECRET=<str>` for bit-identical judge-seed rows. |
| `make accept` | ~2 min | Runs [`scripts/judge_accept.sh`](../scripts/judge_accept.sh): verifies `do_nothing` and `stop_early` = `+0.000` exact across easy/medium/hard, checks `solver` and `guess_day1` against 300-secret `+/- 4 SD` bands in [`results/solver_range/`](../results/solver_range/), binds a live `canary.mcp_server` over HTTP, and prints `RESULT: PASS` (exit `0`). |
| `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` | ~14 s | Prints hard `OpenCode + gemini-4-carbon over MCP`: `0.322 +/- 0.199` vs solver `0.499`, **`65% [24%, 98%]`** raw, **`72% [52%, 91%]`** luck-adjusted (`0.360` vs `0.499`), plus in-process hard (`95% [62%, 140%]`) and OpenCode medium (`111% [99%, 127%]`). |
| `uv run python scripts/demo_replay.py --seed 4 --verify` | ~0.5 s | Prints `verify solver recorded +0.73 replayed +0.73 -> MATCH` and `verify gemini recorded +0.40 replayed +0.40 -> MATCH`; shows solver isolating and accusing mole `e11` on day 5 (`7` canaries, `0` interviews, `44` calls) while Gemini accuses `e11` on day 16 (`10` canaries, `84` interviews, `155` calls, keeping `55%` of solver value). Try `--seed 26` for a `-1.00` wrong accusation after a disclosed 5% fingerprint flip. |
| `uv run python scripts/failure_analysis_v14.py` (`--check`) | ~1 min | Replays every episode in a fresh `Env`, verifies exact score reproduction against [`docs/reports/failure_analysis_v1.4.md`](reports/failure_analysis_v1.4.md) and [`results/failure_analysis_v1.4.json`](../results/failure_analysis_v1.4.json) (`--check` asserts clean match without touching disk; bare command regenerates both files). |
| `make anticheat-verify` | ~2 min | Prints `verify results/anticheat/exploits.json: 99 rows rerun on 40 seeds x 3 tiers under the public secret; 0 differences` (exit `0`). |
| `make game-serve` | <1 s build | Builds `game/site/` and serves `http://localhost:8000` (open `?seed=3000`; solver trajectory on medium seed `3000` scores `0.79`, matching CPython). |

---

## 2. 10-Minute Deep Walkthrough Mapped to the AfterQuery Rubric

| Rubric Pillar | Weight | Core Result | Primary Committed Evidence | Keyless Check |
|---|---:|---|---|---|
| **1. Frontier Gap & Rerun** | **30 pts** | `gemini-4-carbon` (OpenCode/MCP, hard, `n=30`): `65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adj.; parity disclosures on in-process hard (`95%`) & OpenCode medium (`111%`) | [`paired_table_gemini.md`](../data/runs/committed/v1.4/paired_table_gemini.md), [`gap.md`](reports/gap.md), [`harbor/README.md`](../harbor/README.md), [`oracle_range_v1.4.md`](../results/oracle_range_v1.4.md) | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| **2. Difficulty & Fairness** | **30 pts** | Exact `5.30 V` gap accounting (`4.19 V` skill + `1.11 V` luck); 295-episode step gallery; same 13 tools/observations; calibrated near-optimal solver; W1-W4 disclosed | [`failure_analysis_v1.4.md`](reports/failure_analysis_v1.4.md), [`failure_gallery.md`](reports/failure_gallery.md), [`DIFFICULTY.md`](DIFFICULTY.md), [`reference_optimality.md`](reports/reference_optimality.md) | `uv run python scripts/failure_analysis_v14.py --check` |
| **3. Reward Integrity** | **25 pts** | 43+ logged attacks, HMAC-signed ledger, `11/11` sidecar isolation, `cheat_probe = 0.0`, `1021/1031` step-verified (`0` differ in `51,814` steps), `0` exploits in 91-attacker swarm | [`EXPLOITS.md`](EXPLOITS.md), [`exploits.md`](../results/anticheat/exploits.md), [`judge_hunt.md`](../results/anticheat/judge_hunt.md), [`corpus_eval.txt`](../results/anticheat/corpus_eval.txt) | `make anticheat-verify` and `uv run python scripts/judge_hunt.py` |
| **4. Craft, Tiebreak & Game** | **15 pts + TB** | Clean-tree keyless `make reproduce`, `0 FAIL` submission audit, fresh-clone logs, honest LoRA SFT/GRPO tiebreak status, gateway replay + Pyodide parity | [`README.md`](../README.md), [`SUBMISSION.md`](SUBMISSION.md), [`fresh_clone/README.md`](../results/fresh_clone/README.md), [`fr8.md`](reports/fr8.md), [`gemini/SUBMISSION.md`](gemini/SUBMISSION.md) | `uv run python scripts/audit_submission.py` and `make lab-replay` |

---

### Pillar 1: Frontier Gap & Rerun Guide (30 pts)

#### A. Official `justSilas` v1.4 paired results (dev seeds `0-29`, `n=30` per cell, 100% replay-verified)

All frontier episodes on rules `v1.4` are paired seed-by-seed with the reference Bayesian canary-trap solver on locked dev seeds `0-29` (post-hoc seed lock recorded in [`docs/reports/gap.md`](reports/gap.md) at commit `671ed96`, 28 s after `8fd4dec`, against later reruns and cherry-picking; committed table in [`data/runs/committed/v1.4/paired_table_gemini.md`](../data/runs/committed/v1.4/paired_table_gemini.md); solver reference split across `solver-hard-20261114-121126/` for seeds `0-19` and `solver-hard-seeds20to29/` for seeds `20-29`; full multi-version judge table in [`results/judge_table.md`](../results/judge_table.md)). Confidence intervals use a paired 10,000-resample bootstrap over seeds.

| Tier | Agent & Harness | n | Score +/- 95% CI | Solver (same seeds) | Frontier / Solver [95% CI] | Luck-Adj. Score | Luck-Adj. / Solver [95% CI] | Accuracy | Mean Accuse Day | Mean P(accused) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **hard** | **OpenCode + `gemini-4-carbon` over MCP (headline)** | **30** | **`+0.322 +/- 0.199`** | **`+0.499 +/- 0.119`** | **`65% [24%, 98%]`** | **`+0.360`** | **`72% [52%, 91%]`** | **`83.3%`** (`25/30`) | **`13.2`** | **`0.88`** |
| hard | In-process `gemini-4-carbon` (full history + thought sigs) | 30 | `+0.473 +/- 0.118` | `+0.499 +/- 0.119` | `95% [62%, 140%]` | `+0.421` | `84% [65%, 106%]` | `93.3%` (`28/30`) | `12.7` | `0.93` |
| hard | Reference solver | 30 | `+0.499 +/- 0.119` | `+0.499` | `100%` | `+0.499` | `100%` | `96.7%` (`29/30`) | `10.6` | `0.97` |
| medium | OpenCode + `gemini-4-carbon` over MCP | 30 | `+0.713 +/- 0.042` | `+0.645 +/- 0.087` | `111% [99%, 127%]` | `+0.652` | `101% [85%, 119%]` | `100.0%` (`30/30`) | `8.0` | `0.96` |
| medium | In-process `gemini-4-carbon` | 30 | `+0.530 +/- 0.138` | `+0.645 +/- 0.087` | `82% [56%, 108%]` | `+0.479` | `74% [52%, 99%]` | `83.3%` (`25/30`) | `9.0` | `0.93` |

Key takeaways for peer review:

- **Both headline CIs on hard exclude parity (`100%`):** `gemini-4-carbon` over MCP trails the solver by `-0.177 +/- 0.194` raw (`65% [24%, 98%]`) and keeps **`72% [52%, 91%]`** of the solver's expected value once outcome variance is removed via the exact Bayesian posterior (`P * V - (1 - P)` at the moment of accusation, `0` if abstaining). Counting the single non-retried empty-reply sensitivity row as `0` instead of retrying lowers OpenCode hard further to `+0.279 +/- 0.180` (`56% [19%, 87%]` raw, `55% [34%, 77%]` luck-adjusted).
- **Honest parity & harness disclosures:** We report every cell where frontier models match the solver: `gemini-4-carbon` in-process on hard reaches `95% [62%, 140%]` (`+0.473 +/- 0.118`), and OpenCode over MCP on medium reaches `111% [99%, 127%]` (`+0.713 +/- 0.042` vs `+0.645`). On medium, noiseless canary fingerprints let strict set-elimination match Bayes; on hard, 5% fingerprint noise and 2-3 day delays break strict elimination, exposing OpenCode agents that under-plant canaries and commit on unresolved suspect sets. As disclosed in [`README.md`](../README.md) and [`docs/SUBMISSION.md`](SUBMISSION.md), headline OpenCode runs denied `bash`/`python3` (13 MCP tools only), whereas the Harbor agent container allows `bash` and `python3` under `11/11` sidecar isolation. Two post-run improvements on 15 Nov (`1bc3e281`, tag `afterquery-final`) are also disclosed: tool errors now carry `data.detail` (`28` of `3,841` headline calls hit `invalid arguments`; older episodes still replay step-for-step) and `W1` was reworded in medium/hard instructions. A pre-registered `n=60` extension (`f9fb7a4a`) stopped early after `2` valid episodes (`seeds 34, 37`) to preserve rehearsal quota; pooled (`n=32`, [`paired_table_pooled0to59.md`](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md)) reads `68% [32%, 100%]` raw and `75% [56%, 93%]` luck-adjusted, while the locked `n=30` set remains the primary headline (with a pre-registered `gpt-5.5` OpenCode hard `0-29` run logged in `gap.md` at `cf394894`).
- **Trivial policies lose or score zero:** `do_nothing` and `stop_early` (stops on day 1 without accusing) score **exactly `+0.000`** on all 40 judge seeds; `guess_day1` (random day-1 accusation) averages **`-0.950 +/- 0.098`** on hard ([`results/solver_range/guess_day1_hard_judge40.md`](../results/solver_range/guess_day1_hard_judge40.md)).
- **Disclosed negative ablations ([`docs/reports/gap.md`](reports/gap.md)):** Three candidate changes that did *not* widen the gap are reported in full rather than shipped: `v1.5` biased employees (`108%` of solver on hard seeds `0-9`), `solver_v2` (`+0.012 +/- 0.029` on fresh hard seeds `9000-9399`, `n=400`), and an `expert` 70%-fingerprint tier (`84% [52%, 128%]` luck-adjusted, `n=13`).

#### B. Live Judge Rerun Guide: Harbor + OpenCode over MCP (Docker)

Full packaging and isolation details are in [`harbor/README.md`](../harbor/README.md). Default [`harbor/build.py`](../harbor/build.py) builds the pre-registered **10-task hard judge set** (`canary-hard-900000` through `canary-hard-900009`) with a fresh 32-byte world `SALT` and a fresh 32-byte HMAC `ledger_key` (`0600`, mounted only in the sidecar and separate verifier):

```bash
# 1) Install Harbor (tested: 0.26.0) and build the 10 hard judge tasks (900000-900009, fresh world secret)
uv tool install harbor && uv run python harbor/build.py

# 2) Verify oracle and zero/anti-cheat baselines on the exact same built worlds
harbor run -p harbor/dataset -a oracle -n 4                                  # expect ~+0.39 to +0.68 (90% range)
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4    # expect 0.0 exact on all 10
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4    # expect 0.0 exact on all 10
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4   # 149 cheat probes, never accuses: 0.0 exact

# 3) Run OpenCode + gemini-4-carbon over MCP (note API key forwarding + setup timeout multiplier)
GOOGLE_GENERATIVE_AI_API_KEY=<your_key> harbor run -p harbor/dataset -a opencode \
    -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY \
    --agent-setup-timeout-multiplier 3 -n 4
```

- **Expected 10-task oracle range ([`results/oracle_range_v1.4.md`](../results/oracle_range_v1.4.md)):** Across 200 simulated fresh-secret builds, the 10-task hard oracle mean is **`+0.569` (sd `0.094`, median `+0.600`)**, landing in **`+0.39` to `+0.68` in 90% of builds** (`p5 = +0.393`, `p95 = +0.678`, `P(mean < 0) = 0.0%`). Because a single `-1` wrong accusation shifts a 10-task mean by `>0.1` (and gives `P(mean < 0) = 10.5%` on 2-task smoke runs), judge comparisons should use all 10 built tasks paired against the oracle on the same `harbor/dataset` build.
- **Two operational pitfalls to avoid infrastructure zeros:**
  1. **API key variable name:** OpenCode's Google provider reads `GOOGLE_GENERATIVE_AI_API_KEY` (not `GEMINI_API_KEY`), and Harbor only forwards it into the `main` container when `--api-key-name GOOGLE_GENERATIVE_AI_API_KEY` is passed. Without both, OpenCode exits before its first LLM call (`AI_LoadAPIKeyError`).
  2. **Container setup & episode wall-clock timeouts:** Pass `--agent-setup-timeout-multiplier 3` when running `-n >= 4` or on slow Wi-Fi so Harbor's per-container `nodejs`/`npm`/`opencode-ai` install does not hit the 360 s default `AgentSetupTimeoutError`. Episode wall-clock timeout is already set to `10800.0` s in [`harbor/template/task.toml`](../harbor/template/task.toml) (P0 fix `512836b9`).
- **Pre-registered rehearsal protocol & committed dry run:** [`results/harbor/rehearsal/README.md`](../results/harbor/rehearsal/README.md) fixes the paired 10-task rerun rules before execution; [`results/harbor/rehearsal-dry/README.md`](../results/harbor/rehearsal-dry/README.md) (`TABLE.md`) commits the full 1-run dry rehearsal (`oracle +0.467`, `OpenCode gemini-4-carbon +0.398` = `85% [11%, 355%]` single dry run, `do_nothing` & `stop_early` = `0.000`, `43/43` trials HMAC-verified).

---

### Pillar 2: Difficulty, Causal Failure Analysis & Fairness (30 pts)

#### A. Exact additive V accounting (`5.30 V` total gap across 30 paired hard seeds)

Every number in [`docs/reports/failure_analysis_v1.4.md`](reports/failure_analysis_v1.4.md) is deterministically computed by [`scripts/failure_analysis_v14.py`](../scripts/failure_analysis_v14.py) from committed `episodes.jsonl` and verified to sum identically:

| Component | V Lost (30 seeds) | Per Episode | Causal Mechanism |
|---|---:|---:|---|
| 1. Accusing before isolating one suspect (`(1-P)(1+V)` vs solver) | **`+3.39 V`** | `+0.113` | `9/29` Gemini accusations occurred with `>=2` suspects still consistent with every leak (solver: `3/30`), losing `+3.50 V` (`20/29` isolated accusations net `-0.11 V`), incl. **`3` negative-EV horizon gambles** on seeds `5, 18, 23` (`1.64 V` lost where abstaining for `0` had higher EV). |
| 2. Never reaching an accusable posterior -> abstention (seed `11`) | **`+0.62 V`** | `+0.021` | Gemini stayed at `P <= 0.40` (consistent set `7`, `121` interviews) and rightly abstained (`0.00`); solver isolated and caught the mole on day 9 (`+0.62`). |
| 3. Extra leak damage from accusing later | **`+1.75 V`** | `+0.058` | Mean accuse day `13.2` vs `10.6` (`13.4` vs `10.6` counting abstention as day 21); `7.3` vs `6.1` leaks before accusing. |
| 4. Restriction costs | **`+0.12 V`** | `+0.004` | Minor access-restriction overhead. |
| 5. Canary costs *saved* by under-planting | **`-1.69 V`** | `-0.056` | Gemini planted **`8.5` vs `14.1`** canaries (`0.01 V` each), nearly canceling the `+1.75 V` waiting leak drain. |
| **Luck-adjusted (skill) gap** | **`+4.19 V`** | **`+0.140`** | Exact sum of rows 1-5 (`0.499 - 0.360 = 0.140`/ep). |
| Outcome luck (`realised - expected`: Gemini `-1.12 V`, solver `-0.01 V`) | **`+1.11 V`** | `+0.037` | Gemini's posteriors predicted `3.4` wrong accusations and it made `4` (`P(>=4) = 0.46`); solver predicted `1.0` and made `1`. |
| **Total raw gap** | **`+5.30 V`** | **`+0.177`** | Matches `0.499 - 0.322 = 0.177`/ep in `paired_table_gemini.md`. |

- **Root behavioral cause (interviews crowding out canary capacity):** Hard allows `8` investigative actions/day and `2` three-variant canaries/day. Disclosed interview signal is tiny (`LR = 1.2`, worth `<= 0.005` nats per call), whereas one leaked 3-variant canary yields up to `ln 3 ~= 1.1` nats. Gemini spends **`68` interviews/episode** (solver: **`0`**), starts planting on day `3.0` vs day `1.0`, and uses only **`32%` vs `67%`** of daily canary capacity (`38%` vs `91%` of days with `>=1` canary). Hesitation after evidence is already decisive is small (`5` seeds: `4, 17, 21, 24, 25`, costing `0.37 V` total over `2.2` extra days by counterfactual replay).
- **Cross-version step gallery ([`docs/reports/failure_gallery.md`](reports/failure_gallery.md)):** Decomposes **`295` paired episodes** across `v1.2`, `v1.3`, and `v1.4` onto exact agent steps with **`0.0e+00` unexplained residual** (`4.4e-16` max per-episode float residual) and `40/40` verbatim quotes verified against transcripts (`uv run pytest tests/test_gemini_lab_gallery.py`).

#### B. Honest breakdown of Gemini's 4 wrong accusations on hard

| Seed | Day | Accused (True Mole) | Solver P(accused) on Gemini's Evidence | EV at Accusation | Consistent Set | Fingerprint Flip? | Solver Score on Seed | Honest Verdict |
|---:|---:|---|---:|---:|---|---|---:|---|
| `1` | 19 | `e39` (`e33`) | `0.99` | `+0.31` | `{e39}` | **Yes** | `+0.69` | **Disclosed 5% flip noise** (`P >= 0.95`); solver's rule on Gemini's evidence accuses the same innocent. |
| `15` | 12 | `e34` (`e37`) | `0.80` | `+0.32` | `{e34, e37}` | No | `-1.00` | **Unresolved pair** (`e34` and `e37` shared every canary label with 9 days left); **solver also lost this seed** (to a flip). |
| `18` | 18 | `e29` (`e27`) | `0.63` | **`-0.08`** | `{e09, e27, e29, e37}` | No | `+0.52` | **Negative-EV gamble:** 4 suspects still consistent after Gemini planted 0 canaries on days `14-17`. |
| `26` | 10 | `e04` (`e08`) | `0.95` | `+0.54` | `{e04}` | **Yes** | `+0.69` | **Disclosed 5% flip noise** (`P >= 0.95`); upstream sparse canaries left a single flipped readout decisive. |

#### C. Fairness, instruction audit (W1-W4), and reference solver calibration

- **Identical observations, tools, and budgets:** The solver uses only the 13 public MCP tools (`84` calls/ep vs Gemini's `128`), and every posterior `P(accused)` above is computed strictly from **tool outputs Gemini itself received** (`0.00`-day lag reading surfaced leaks). In-process `gemini-4-carbon` shows the exact same exploration profile (`8.6` canaries, `33%` capacity, `57` interviews/ep), confirming under-exploration is a model decision trait rather than an MCP harness artifact.
- **Instruction audit ([`docs/DIFFICULTY.md`](DIFFICULTY.md) & [`results/audit/instruction_checks.md`](../results/audit/instruction_checks.md)):** Mechanical checks confirm `34/34` `TierParams` fields are printed in every tier's instructions and `39/39` smoke calls across all 13 tools x 3 tiers return `ok`. Known Wording Issues **W1-W4** (and the 15 Nov `data.detail` tool-error addition across `28/3,841` headline calls) are audited and disclosed in full:
  - **W1 (fixed 15 Nov in medium/hard instructions; history for committed runs):** Mole DSL rules receive no `is_canary` flag; the environment applies weight `1 - recipients/N` in default leak selection, and the medium/hard instruction sentence was reworded on 15 Nov (`1bc3e281`) to state this explicitly while leaving the Exact-parameters block untouched. Trajectory audit ([`scripts/careful_mole_check.py`](../scripts/careful_mole_check.py)) confirms Gemini sized canaries identically to the solver (mean share `0.26` vs `0.24`, careful weight `0.74` vs `0.76`) and zero loss seeds hinged on W1.
  - **W2 (if-then rule list on base tiers, stays as written):** Base `easy`/`medium`/`hard` use `DEFAULT_STRATEGY` (empty rule list, weighted random leak, no extra DSL framing), stated in the final DSL bullet.
  - **W3 (within-day event order, stays as written):** Documented explicitly in `DIFFICULTY.md` D8 (`advance_day` on day `d` leaks from `d-2..d`, charges restrictions, emits day `d` logs/messages, and surfaces leaks on `d + delay`).
  - **W4 (`access_constraints` clearance rule on hard, stays as written):** Listed in hard instructions, but never binds on canary planting (disclosed in `DIFFICULTY.md` W4 and `README.md`).
- **Solver optimality ([`docs/reports/reference_optimality.md`](reports/reference_optimality.md)):** Across `400` hard dev seeds (`8000-8399`) and `400` fresh seeds (`9000-9399`), the solver's posterior is empirically calibrated (`95.6%-98.6%` accuracy across `0.85-1.00` bins), optimal `p >= a + b*V` grid search adds only `+0.005` on hard, and an upgraded `solver_v2` (joint pending-canary IG + suspect restriction tests) gained only `+0.012 +/- 0.029` on fresh hard seeds. Hard solver loss (`0.422`) is dominated by irreducible information-rate costs (`0.250` leak drain + `0.120` canary cost).

---

### Pillar 3: Reward Integrity & 15-Minute Exploit Hunt (25 pts)

[`docs/EXPLOITS.md`](EXPLOITS.md) ("Judges: start here") logs **52 entries (`#0-#51`, covering 43+ distinct attacks)** with pre-fix scores, fix commits, enforcing pytest cases, and 5 bounded residual risks. Three real vulnerabilities found during internal red-teaming were closed before v1.4 runs: free day-1 guessing under `0/1` scoring (`#1`, closed by `-1` wrong-accusation penalty), public judge-seed world regeneration (`#24`, closed by fail-closed secret derivation), and same-uid `/proc/<pid>/environ` secret reads (`#27`, closed by `0600` consumed secret files + separate sidecar container).

| Defense / Red-Team Layer | Scope & Artifacts | Verified Outcome | Reproduce Command (No Keys) |
|---|---|---|---|
| **Anti-cheat battery** | `99` rows (`33` probes x `3` tiers, expanded from `96` with `swarm_w2b008`) x `40` judge seeds = `3,960` runs ([`results/anticheat/exploits.md`](../results/anticheat/exploits.md)) | **All probes blocked; `0 differences`** on rerun; `do_nothing`, `stop_early`, `garbage_args`, `accuse_after_end`, `calls_past_cap`, and `solver_cut_25/50/75` = **`0.000` exact** on every seed | `make anticheat-verify` |
| **HMAC-SHA256 signed ledger** | Per-build 32-byte `0600` `ledger_key` in sidecar + separate verifier; negative control [`results/harbor_negative/c1-tamper/result.json`](../results/harbor_negative/c1-tamper/result.json) | Tampering `/evidence/ledger.json` (`score: 1.0`) after signing scores **`0`** with `FAIL: bad ledger signature`; all signed Harbor trials verify `signature=ok` | `uv run pytest tests/test_harbor_ledger_sig.py` |
| **Sidecar container isolation** | Separate `canary-server` container (uid `10001`), separate FS & PID namespace, `0600` consumed `CANARY_*_FILE` secrets ([`harbor/check_isolation.sh`](../harbor/check_isolation.sh)) | **`ISOLATION OK: 11 checks passed, 0 findings`** in all `61/61` committed Harbor `solve.sh` trials (`0` `CANARY_*` vars in `main` or `/proc/*/environ`; sidecar negative control triggers `6` findings) | `uv run python scripts/audit_submission.py` |
| **Harbor `cheat_probe` & `cheat`** | `149` out-of-band/wire cheat attempts per trial (grader routes, `/proc`, `reward.txt` 15-min rewrite loop, fake MCP tools); never accuses (`results/harbor/cheat-probe/`) | **`0.0` exact on `6/6` trials** (`3` judge seeds x medium/hard, `"holes": []`, `signature=ok`); accuse-everyone `cheat` scores **`-1.0` on `6/6`**; planted-token positive control scores `> 0` | `uv run pytest tests/test_harbor_cheat.py` |
| **Trajectory & Harbor replay** | Every non-superseded committed `episodes.jsonl` + `results/harbor/` ([`results/anticheat/exploits.md`](../results/anticheat/exploits.md), [`rehearsal-dry`](../results/harbor/rehearsal-dry/README.md)) | **`1021/1031` episodes replayed** in fresh `Env` (`10` Grok judge-seed runs secret-keyed), **`51,814` tool results compared step-by-step, `0` differ**; **`80/80` Harbor trials & `18/18` jobs** consistent | `uv run pytest tests/test_anticheat.py -k "replay or harbor"` |
| **91-attacker Gemini swarm** | `75` whitebox attackers (waves 1/2/2b, ~183k prompt tokens) + `16` blackbox attackers, plus `9` MCP re-runs = `100` attempts ([`swarm.md`](../results/gemini/swarm.md), [`swarm_control.md`](../results/gemini/swarm_control.md)) | **`0` verified exploits, `0` invariant violations** across `4,325` tool calls; positive-control detector validation caught **`4/4` (`16/16` reruns = `1.0`)**; candidate `w2b-008` overturned on review (`+0.163` vs `+0.547`, [`swarm_review_w2b008.json`](../results/gemini/swarm_review_w2b008.json)) and refuted at `40` judge + `100` dev seeds/tier (`+0.363` vs `+0.545` hard) | `uv run pytest tests/test_gemini_lab_swarm.py` |
| **129-row Sleeper cheat corpus** | `129` real `gemini-3.5-flash` exploit calls from Sleeper ([`data/redteam/corpus.jsonl`](../data/redteam/corpus.jsonl), [`results/anticheat/corpus_eval.txt`](../results/anticheat/corpus_eval.txt)) | **`1,161` runs** (`129` x `3` seeds x `3` tiers), **`0` calls accepted, `0` runs where solver score changed** | `uv run pytest tests/test_anticheat.py -k corpus` |
| **15-min wire hunt & fuzzing** | Live HTTP/JSON-RPC attacks on `canary.mcp_server` ([`scripts/judge_hunt.py`](../scripts/judge_hunt.py), [`results/anticheat/judge_hunt.md`](../results/anticheat/judge_hunt.md)) + `make hunt` | **`12/12` wire attacks held** (~54 s: double-session accuse, homoglyphs, JSON-RPC batch, 5 MB / 20k-deep JSON, 16 grader routes, 200 parallel `advance_day`, post-accuse right-vs-wrong parity); `make hunt` `0` violations across 16 cells (and 4M-eval FR8 fuzz) | `uv run python scripts/judge_hunt.py` and `make hunt` |

---

### Pillar 4: Craft, Tiebreaker & Browser Game Parity (15 pts + Tiebreak)

#### A. Clean keyless reproduction, frozen hashes, and fresh-clone logs

- **Working-tree hygiene:** `make reproduce` writes exclusively to gitignored `results/latest/` and never mutates tracked files. Run the automated submission hygiene and Harbor static audit in ~4 s:
  ```bash
  uv run python scripts/audit_submission.py
  ```
  Expected summary (`0 FAIL`):
  - `[PASS] Secret & Answer-Key Hygiene`: `0` secrets, `SALT` files, or `.world.json` mole keys across all tracked files.
  - `[PASS] Frozen Tier Hashes`: `TIERS_VERSION=v1.4` (`a8f99c2537c91d72`), `TIERS_V13` (`8df71cf570bb48bc`).
  - `[WARN] Committed Runs Integrity`: `63` files, `1031` episodes audited, `0` duplicates, all score invariants hold (`8` historical v1.2 `opencode-gpt-5.6-sol` `valid:false` infra/quota episodes verified excluded from means).
  - `[PASS] Harbor Package Static Audit`: builds `canary-hard-900000` in temp dir and verifies `environment_mode = "separate"`, `[[verifier.collect]]`, `.dockerignore` sidecar exclusion, `0600` permissions on `SALT` / `episode.json` / `ledger_key`, and `0` `CANARY_*` agent env vars.
- **Timed fresh-clone logs ([`results/fresh_clone/README.md`](../results/fresh_clone/README.md)):** Verified on both **macOS arm64** (`make setup` `2 s` / `7.3 s` cold Python, `make reproduce` `52 s`, `make accept` `142 s` -> `RESULT: PASS`, `967 passed`) and **Linux x86_64** (`git clone --no-hardlinks` under `env -i`, `make reproduce` `159 s` on loaded 24-CPU Xeon, `audit_submission.py --run-reproduce` `0 FAIL`, `git status --porcelain` empty after every step).

#### B. Small-model tiebreaker: honest committed readout (bar not met)

- **WS4 held-out readout ([`README.md`](../README.md), [`docs/reports/fr8.md`](reports/fr8.md) "04:45 WS4 readout", [`fr8/analysis/out/ws4_table_v3.md`](../fr8/analysis/out/ws4_table_v3.md)):** `Qwen2.5-1.5B-Instruct` with LoRA evaluated standalone on secret-keyed held-out seeds (trained strictly on `TRAIN_SEEDS`, never judge or held-out). **The tiebreak bar (above base `0.000` with CI excluding `0`) is not met**, and we do not claim a reward gain:
  - **Untrained `base` (`n=36`):** `0.000` (`3%` valid tool calls; abstains every episode).
  - **`v2` SFT on solver play (`n=172`):** `-0.457 +/- 0.086` (`0.08 -> 0.99` valid calls in J4, `~0.85` solver action-type agreement, but accuses recklessly on `55%` of episodes).
  - **`v3-4k` GRPO on environment reward (`n=180`, Verda H100):** `-0.147 +/- 0.063` (**`+0.310 +/- 0.107`** two-sample recovery vs `v2`, `100%` valid tool calls, training-state mole-identification `0.19 -> 0.89`).
  - **`v3-8k seed 2` GRPO at 8k context (`n=90`, Verda H100 spot):** `-0.050 +/- 0.049` (`v3-8k seed 1`: `-0.777 +/- 0.118`, `n=90`).
- **Honest diagnosis & in-progress follow-up:** Reward training curbed `v2`'s reckless accusations and taught protocol + evidence reading on solver states, but did not teach active canary gathering on the model's own states (mirroring Gemini's failure mode). An on-policy DAgger follow-up is running (`docs/agents/PANEL-0500.md`).

#### C. Offline Gemini cache replay & Pyodide browser game parity

- **Keyless Gemini Lab gateway replay (~1 min):** [`docs/gemini/SUBMISSION.md`](gemini/SUBMISSION.md) documents Canary Lab's deterministic HTTP record/replay gateway. Verify recorded Gemini runs step-for-step with zero API keys:
  ```bash
  make lab-replay
  ```
  Expected tail: `showcase: REPLAY OK, 5 steps reproduced keyless from the gateway cache`, `lab_replay: ladder: REPLAY OK, 4 episodes reproduced step for step (scores [-1.0, 0.79, 0.63, 0.88])`, and `lab_replay: ladder-showcase: REPLAY OK, 6 episodes reproduced step for step (scores [-1.0, 0.67, 0.63, 0.51, 0.69, 0.59])` -> `lab_replay: ALL OK`. (Note: `make lab-replay` writes scratch outputs under gitignored `data/gemini/replay-check/`.)
- **Browser game == CPython parity:** `make game-serve` bundles the real `canary` Python package into `game/site/` for in-browser execution via Pyodide (`http://localhost:8000/?seed=3000`; dry-run notes in [`docs/DEMO.md`](DEMO.md)).
  - **Anti-leak guardrails ([`tests/test_game.py`](../tests/test_game.py)):** refuses judge, held-out, and benchmark dev seeds (`< 3000` or `>= 10000`), makes `0` hidden tool calls on load, blocks `reveal_json()` until `env.done`, and reveals how the reference solver played the exact same world upon completion.
  - **Exact parity ([`game/tests/parity.mjs`](../game/tests/parity.mjs)):** replaying the solver's action list on medium seed `3000` produces **`score: 0.79`** (accused `e09` on day 6, `V = 0.79`), identical between Pyodide WebAssembly and CPython.

---

## 3. Source-to-Claim Quick Index

- **Rules & frozen parameters:** [`docs/CONTRACT.md`](CONTRACT.md), [`canary/rules.py`](../canary/rules.py), [`docs/HISTORY.md`](HISTORY.md)
- **Frontier gap & paired tables:** [`docs/reports/gap.md`](reports/gap.md), [`data/runs/committed/v1.4/paired_table_gemini.md`](../data/runs/committed/v1.4/paired_table_gemini.md), [`results/judge_table.md`](../results/judge_table.md)
- **Causal failure analysis & instruction audit:** [`docs/reports/failure_analysis_v1.4.md`](reports/failure_analysis_v1.4.md), [`docs/reports/failure_gallery.md`](reports/failure_gallery.md), [`docs/DIFFICULTY.md`](DIFFICULTY.md), [`docs/reports/reference_optimality.md`](reports/reference_optimality.md), [`results/gemini/atlas.md`](../results/gemini/atlas.md)
- **Harbor packaging & oracle spread:** [`harbor/README.md`](../harbor/README.md), [`results/oracle_range_v1.4.md`](../results/oracle_range_v1.4.md)
- **Exploit ledger & anti-cheat proofs:** [`docs/EXPLOITS.md`](EXPLOITS.md), [`results/anticheat/exploits.md`](../results/anticheat/exploits.md), [`results/anticheat/judge_hunt.md`](../results/anticheat/judge_hunt.md), [`results/anticheat/corpus_eval.txt`](../results/anticheat/corpus_eval.txt)
- **Tiebreaker & Gemini Lab:** [`docs/reports/fr8.md`](reports/fr8.md), [`docs/gemini/SUBMISSION.md`](gemini/SUBMISSION.md), [`results/fresh_clone/README.md`](../results/fresh_clone/README.md)
