# Integrity & Social-Layer Exploit Audit: `justSilas-v15` (`v1.5-candidate`)

## 1. Headline Summary

- **Target Audited:** `origin/justSilas-v15` @ `de9cc50e` (`de9cc50ea46420d507010b02f3562e370ca2b34b`, `rules.tiers_version("v1.5-candidate")` WS2 human-bias social layer: `rumour_rate=2.0`, `rumour_frame_share=0.4`, `grudge_pairs=2`, `grudge_rate=0.5`, `authority_day=3`, `p_misforward=0.15`).
- **Base Branch & Constraints:** Packaged on `justSilas` (`f9fb7a4a` / `fr8/canary/integrity` @ `19a2dc93`) with **zero edits to protected files** (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`), `--workers 1`, and **`0` LLM/API calls**.
- **Harness:** `scripts/integrity_v15_social_sweep.py` (includes standalone keyless `--self-test` synthetic mirror so regression tests run on `justSilas` in `<15s` without requiring an external `v15` worktree).
- **Reward & State Integrity Verdict: HELD (`0` exploits, `0` invariant violations).**
  - **321,360-episode 4-tier fuzzer sweep** (`easy`, `medium`, `hard`, `hard_forge`, seeds `7500-7649`, `--budget 80100 --mode all --workers 1 --tiers-version v1.5-candidate`, `1,387.3s`): **`best_non_solver_score = 0.000`** and **`0` invariant violations** across `>= 6,577,180` `env.call` invocations (`6,470,380` exact deterministic calls across `random`, `malformed`, `parallel_accuse`, `parity`, and setup + `>= 106,800` `evolve` calls).
  - **200-seed invariant & `known_V` audit** (`medium` and `hard`, seeds `7500-7699`, `400` episodes per check): `DoNothing = 0.000`, `StopEarly = 0.000`, Day-1 random guess `< 0` (`-0.8800 +- 0.0660` medium, `-0.9600 +- 0.0389` hard), `0` `V`-monotonicity violations across `17,400` checked steps, and **`0` hidden-leak `V` reveals** across `10,972` unsurfaced-leak states.
  - **Word & secret-token leak scan** (`650` episodes across `easy`, `medium`, `hard`, and `hard` `random_peer`; `33,445` social messages and `4,963` misforwarded documents): **`0` occurrences of the word `"mole"`**, **`0` truth-pattern leaks**, and **`0` `world_seed` / raw seed / secret-token leaks** (confirming the `dbae1096` template fix holds across all message kinds).
- **Social-Layer Statistical & Side-Channel Verdict: 5 Report-Only Structural Tells Identified for `v1.6` Hardening.**
  1. **Rumour & authority anti-inversion (`ISS-V15-01`):** Because `seed_rumour` (`rumour_frame_share=0.4`) never targets the mole, `P(is_mole | rumoured) = (1 - s)/n = 0.6/n` is strictly below the `1/n` prior on every tier (`0.0170` vs `0.0250` on `hard`; `0.0306` vs `0.0500` on `medium`; `0.0443` vs `0.0833` on `easy`). Under the default mole, the top-rumoured employee is the true decoy on **`200/200` (`100.0%`)** of `hard` episodes and **`199/200` (`99.5%`)** of `medium` episodes, and is the true mole on **`0/200` (`0.0%`)** of `hard` episodes (`0/205 = 0.0%` whenever `rumours >= 5`).
  2. **Grudge decoy-exclusion side-channel (`ISS-V15-02`):** `Env._grudges()` (`canary/env.py:370`) draws the 2 grudge pairs (`4` employees) from `[e for e in self._ids if e != self._world.decoy]`. Consequently, **`P(is_decoy | grudge_participant) = 0/800 = 0.000000`** on every tier. Filtering out grudge participants before ranking rumour targets yields **`94.5%` exact decoy identification by Day 6** and **`100.0%` safe non-mole exclusion from Day 6 onward** on `hard` (`200/200` seeds), boosting log-only Day-6 probes by `+0.1865 +- 0.0778` (`-0.9080` to `-0.7215`, still safely negative without canary evidence).
  3. **Machine-readable social subject prefixes (`ISS-V15-03`):** `render_social()` (`canary/text/template.py:222-231`) emits `rumour: eXX`, `unverified accusation: eXX`, and `grudge: eXX` subjects with `m{day}-s{k}` IDs, allowing 1-call prefix queries (`search_messages(query="rumour:")`) to extract or invert the entire social graph without natural-language parsing.
  4. **`SolverPolicy` unqueried `o.social` path vs non-default `seed_rumour` model mismatch (`ISS-V15-04`):** `SolverPolicy.decoy_queries()` (`canary/solver/policy.py:243-247`) only searches `ANGER_WORDS`, ingesting `0.00` social messages in live play (`450/450` episodes). Actively querying rumours (`AntiRumourSolver`) raises `hard` decoy identification from `66.5%` to `87.5%` (`+0.0500 +- 0.0627` on Gate B seeds `0-9`, `+0.0018 +- 0.0516` over `200` seeds), but suffers `-0.0684 +- 0.1175` under an adversarial `seed_rumour="random_peer"` mole (`decoy_id_rate` `2.0%`), showing why hard-threshold rumour-to-decoy inference is brittle against `hard_forge` moles.
  5. **Misforward holder-set expansion (`ISS-V15-05`):** `p_misforward=0.15` (`canary/env.py:358-365`) forwards `14.61%-15.57%` of regular documents to a uniform non-restricted non-recipient (`P(is_mole | forwarded_to)` matches `1/n` within 95% CI: `0.0220 +- 0.0065` vs `0.0250` on `hard`). Including `forwarded_to` in `doc["recipients"]` preserves exact Bayesian soundness; ignoring `forwarded_to` would falsely exclude the true mole in **`9.0%` (`hard`), `13.0%` (`medium`), and `19.5%` (`easy`)** of episodes where the mole leaked a document obtained solely via misforward.

## 2. Reproduce Commands (Keyless, Zero API Calls)

Run the fast standalone synthetic self-test and unit/report test suite on `justSilas` (`<15s`, no external `v15` checkout required):

```bash
python scripts/integrity_v15_social_sweep.py --self-test
python -m pytest -p no:cacheprovider -q tests/test_integrity_v15_social_sweep.py
```

Reproduce the full 4-tier fuzzer sweep and 200-seed statistical/policy audit against a checkout of `origin/justSilas-v15` (`de9cc50e`, `--workers 1`):

```bash
python -m canary.redteam.fuzz --tier easy --seeds 7500-7649 --budget 80100 --mode all --workers 1 --tiers-version v1.5-candidate --out /tmp/opencode/v15-fuzz
python -m canary.redteam.fuzz --tier medium --seeds 7500-7649 --budget 80100 --mode all --workers 1 --tiers-version v1.5-candidate --out /tmp/opencode/v15-fuzz
python -m canary.redteam.fuzz --tier hard --seeds 7500-7649 --budget 80100 --mode all --workers 1 --tiers-version v1.5-candidate --out /tmp/opencode/v15-fuzz
python -m canary.redteam.fuzz --tier hard_forge --seeds 7500-7649 --budget 80100 --mode all --workers 1 --tiers-version v1.5-candidate --out /tmp/opencode/v15-fuzz
python scripts/integrity_v15_social_sweep.py --v15-root /path/to/justSilas-v15 --fuzz-dir /tmp/opencode/v15-fuzz --seeds 7500:7700 --tiers hard,medium --workers 1
```

## 3. Four-Tier Reward-Integrity Fuzz & Invariant Sweep (`origin/justSilas-v15 @ de9cc50e`)

### 3.1 Four-Tier `canary.redteam.fuzz` Results (`--mode all`, Seeds `7500-7649`, `150` Seeds/Tier)

Each tier executed `budget=80,100` search episodes (`26,700` `random` + `26,700` `malformed` + `26,700` `evolve`), `150` 8-thread `parallel_accuse` barrier races (`1,200` concurrent `accuse` threads + `150` `list_employees` setup calls = `1,350` calls), `90` target-substitution parity-probe episodes (`5` seeds x `3` probes x `2` targets x `3` search modes = `255` calls including setup), and `450` `_emps_for` setup calls. With `--rng 0 --workers 1`, `random` (`len(g) ~ Uniform(1..60)`) and `malformed` (`len(g) = 30`) call counts are deterministic; `evolve` executes `>= 1` `env.call` per episode (`best_score_per_call = 1.0` comes from a lucky 1-call Day-1 `accuse` of the true mole, which is a valid accusation rather than an exploit, so `best_non_solver_score = 0.000`).

| Tier | Seeds (`n`) | Search Budget (`random` / `malformed` / `evolve`) | Parallel Races (`8` thr/race) | Parity Episodes | Total Episodes | Deterministic Non-Evolve Calls | Total `env.call` Invocations (Floor) | `best_non_solver_score` | `best_score_per_call` (`random` / `malformed` / `evolve` / `race`) | Invariant Violations | Wall Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `easy` | `7500-7649` (`150`) | `80,100` (`26,700` x `3`) | `150` (`1,200` thr) | `90` | `80,340` | `1,616,146` | `>= 1,642,846` | `0.000` | `0.250` / `0.000` / `1.000` / `0.000` | `0` | `265.4` |
| `medium` | `7500-7649` (`150`) | `80,100` (`26,700` x `3`) | `150` (`1,200` thr) | `90` | `80,340` | `1,622,918` | `>= 1,649,618` | `0.000` | `0.250` / `0.000` / `1.000` / `0.000` | `0` | `260.6` |
| `hard` | `7500-7649` (`150`) | `80,100` (`26,700` x `3`) | `150` (`1,200` thr) | `90` | `80,340` | `1,615,658` | `>= 1,642,358` | `0.000` | `0.333` / `0.000` / `1.000` / `0.000` | `0` | `389.9` |
| `hard_forge` | `7500-7649` (`150`) | `80,100` (`26,700` x `3`) | `150` (`1,200` thr) | `90` | `80,340` | `1,615,658` | `>= 1,642,358` | `0.000` | `0.250` / `0.000` / `1.000` / `0.000` | `0` | `471.4` |
| **Total** | **`600` tier-seeds** | **`320,400`** | **`600` (`4,800` thr)** | **`360`** | **`321,360`** | **`6,470,380`** | **`>= 6,577,180`** | **`0.000`** | **max `1.000` (valid Day-1 accuse)** | **`0` (`0` JSONL lines)** | **`1,387.3`** |

Per-mode deterministic call breakdown across all 4 tiers: `random = 3,258,160` (`813,091` easy + `819,863` medium + `812,603` hard + `812,603` hard_forge), `malformed = 3,204,000` (`801,000` x `4`), `parallel_accuse = 5,400` (`1,350` x `4`), `parity = 1,020` (`255` x `4`), `_emps_for` setup `= 1,800` (`450` x `4`), and `evolve >= 106,800` (`26,700` x `4`).

### 3.2 200-Seed Score, `V`-Monotonicity, and `known_V` Redaction Audit (Seeds `7500-7699`)

| Tier | Seeds (`n`) | `DoNothing` Mean (All `== 0`?) | `StopEarly` Mean (All `== 0`?) | Day-1 Random Guess Mean (`+-95% CI`) | Score Invariant Violations | `V` Steps Checked | `V` Monotonicity Violations | Unsurfaced Leak States | `known_V == true_V` Reveals | All Invariants Hold |
|---|---|---|---|---|---|---|---|---|---|---|
| `medium` | `7500-7699` (`200`) | `0.000000` (`True`) | `0.000000` (`True`) | `-0.8800 +- 0.0660` | `0` | `6,800` | `0` | `3,838` | `0` | `True` |
| `hard` | `7500-7699` (`200`) | `0.000000` (`True`) | `0.000000` (`True`) | `-0.9600 +- 0.0389` | `0` | `10,600` | `0` | `7,134` | `0` | `True` |

## 4. 200-Seed Statistical & Social Side-Channel Audit (`origin/justSilas-v15 @ de9cc50e`)

### 4.1 Word-Leak & Secret-Token Audit (`"mole"`, Truth Patterns, `world_seed`, Raw Seeds)

Every generated social message (`rumour`, `unverified accusation`, `grudge`) and every misforwarded document record across seeds `7500-7699` was scanned for (a) literal `\bmole\b` or `"mole"` substrings, (b) `mole_named_leak` regex patterns tying the true mole ID to culpability, and (c) `world_seed` integers, 4-digit episode seed tokens, or internal identifiers (`world_seed`, `canary_world_secret`, `seed_rumour`, `true_mole`, `is_mole`, `true_culprit`).

| Tier (`seed_rumour`) | Seeds (`n`) | Social Messages Scanned | `rumour` | `unverified accusation` | `grudge` | Misforwarded Docs Scanned | `"mole"` Word Leaks | Truth-Pattern Leaks | Seed / Secret Token Leaks | Clean |
|---|---|---|---|---|---|---|---|---|---|---|
| `easy` (`default` -> `random_peer`) | `7500-7699` (`200`) | `8,756` | `5,663` | `200` | `2,893` | `1,223` | `0` | `0` | `0` | `True` |
| `medium` (`default` -> `decoy`) | `7500-7699` (`200`) | `8,581` | `5,629` | `200` | `2,752` | `1,295` | `0` | `0` | `0` | `True` |
| `hard` (`default` -> `decoy`) | `7500-7699` (`200`) | `12,882` | `8,473` | `200` | `4,209` | `1,958` | `0` | `0` | `0` | `True` |
| `hard` (`random_peer`) | `7500-7549` (`50`) | `3,226` | `2,135` | `50` | `1,041` | `487` | `0` | `0` | `0` | `True` |
| **Total Scanned** | **`650` episodes** | **`33,445`** | **`21,900`** | **`650`** | **`10,895`** | **`4,963`** | **`0`** | **`0`** | **`0`** | **`True`** |

### 4.2 Rumour & Authority Anti-Inversion Conditionals (`n=200` Seeds/Tier, Seeds `7500-7699`)

Let $n$ be staff size and $s = \text{rumour\_frame\_share} = 0.4$. Because `seed_rumour_target()` (`canary/mole/dsl.py:169-174`) chooses from `peers` (`e != mole`) or `decoy` (`decoy != mole`), a seeded rumour (`40%`) **never** targets the mole. An unseeded rumour (`60%`) picks `(speaker, target)` uniformly among distinct employees, hitting the mole with probability $1/n$. Hence for any single rumour event:

$$P(\text{is\_mole} \mid \text{rumoured}) = \frac{1 - s}{n} = \frac{0.6}{n} < \frac{1}{n}, \qquad P(\text{is\_mole} \mid \text{not\_rumoured}) = \frac{1 - (1 - s)/n}{n - 1} > \frac{1}{n}.$$

On decoy tiers (`medium`, `hard`) under the default mole (`seed_rumour = "default"` -> `decoy`), $P(\text{is\_decoy} \mid \text{rumoured}) = s + (1 - s)/n$ (`0.4300` on `medium`, `0.4150` on `hard`), turning cumulative rumour counts into a near-deterministic decoy oracle:

| Metric | `easy` (`n=12`, `default` -> `random_peer`) | `medium` (`n=20`, `default` -> `decoy`) | `hard` (`n=40`, `default` -> `decoy`) | `hard` (`n=40`, `seed_rumour="random_peer"`) |
|---|---|---|---|---|
| Unconditional prior $P(\text{is\_mole}) = 1/n$ | `0.083333` (`200/2,400`) | `0.050000` (`200/4,000`) | `0.025000` (`200/8,000`) | `0.025000` (`200/8,000`) |
| Analytical $P(\text{is\_mole} \mid \text{rumour event})$ | `0.050000` | `0.030000` | `0.015000` | `0.015000` |
| **Empirical $P(\text{is\_mole} \mid \text{rumour event})$** | **`0.044323 +- 0.005360`** (`251/5,663`) | **`0.030556 +- 0.004496`** (`172/5,629`) | **`0.016995 +- 0.002752`** (`144/8,473`) | **`0.017349 +- 0.002780`** (`147/8,473`) |
| **Empirical $P(\text{is\_mole} \mid \text{not rumour target})$** | **`0.086880 +- 0.002212`** (`5,412/62,293`) | **`0.051023 +- 0.001319`** (`5,457/106,951`) | **`0.025205 +- 0.000534`** (`8,329/330,447`) | **`0.025196 +- 0.000534`** (`8,326/330,447`) |
| **Empirical $P(\text{is\_decoy} \mid \text{rumour event})$** | `0.000000` (no decoy) | **`0.437556 +- 0.012960`** (`2,463/5,629`) | **`0.420984 +- 0.010513`** (`3,567/8,473`) | `0.028089 +- 0.003518` (`238/8,473`) |
| Employee $P(\text{is\_mole} \mid \text{rumours} == 0)$ | **`0.244635 +- 0.055197`** (`57/233`, `2.94x` prior) | `0.053528 +- 0.010881` (`88/1,644`) | `0.023575 +- 0.004612` (`98/4,157`) | **`0.035727 +- 0.006982`** (`97/2,715`, `1.43x` prior) |
| Employee $P(\text{is\_mole} \mid \text{rumours} \ge 1)$ | `0.065990 +- 0.010453` (`143/2,167`) | `0.047538 +- 0.008592` (`112/2,356`) | `0.026542 +- 0.005082` (`102/3,843`) | `0.019489 +- 0.003727` (`103/5,285`) |
| Employee $P(\text{is\_mole} \mid \text{rumours} \ge 3)$ | `0.028084 +- 0.010255` (`28/997`) | `0.027094 +- 0.015793` (`11/406`) | `0.012853 +- 0.011194` (`5/389`) | `0.008119 +- 0.006470` (`6/739`) |
| Employee $P(\text{is\_mole} \mid \text{rumours} \ge 5)$ | `0.009009 +- 0.012429` (`2/222`) | **`0.000000`** (`0/205`) | **`0.000000`** (`0/205`) | **`0.000000`** (`0/37`) |
| **Episode $P(\text{is\_mole} \mid \text{top rumoured})$** | `0.010000 +- 0.013790` (`2/200`) | **`0.005000 +- 0.009775`** (`1/200`) | **`0.000000`** (`0/200`) | **`0.005000 +- 0.009775`** (`1/200`) |
| **Episode $P(\text{is\_decoy} \mid \text{top rumoured})$** | `0.000000` (no decoy) | **`0.995000 +- 0.009775`** (`199/200`) | **`1.000000`** (`200/200`) | `0.040000 +- 0.027159` (`8/200`) |
| Day-3 authority $P(\text{is\_mole} \mid \text{target})$ | `0.040000 +- 0.027159` (`8/200`) | `0.025000 +- 0.021638` (`5/200`) | `0.020000 +- 0.019403` (`4/200`) | `0.015000 +- 0.016846` (`3/200`) |
| Day-3 authority $P(\text{is\_decoy} \mid \text{target})$ | `0.000000` (`0/200`) | **`0.430000 +- 0.068614`** (`86/200`) | **`0.340000 +- 0.065653`** (`68/200`) | `0.025000 +- 0.021638` (`5/200`) |

### 4.3 Grudge Decoy-Exclusion Side-Channel (`Env._grudges`, Seeds `7500-7699`)

In `canary/env.py:370`, `Env._grudges()` constructs `pool = [e for e in self._ids if e != self._world.decoy]` and selects `2` disjoint pairs (`4` employees per episode). Because `grudge_rate = 0.5` per pair per day over `14-21` days, almost every grudge-pair member appears as sender or target of `grudge: <id>` (`800/800` pair members observed as participants across `200` seeds on `easy`, `medium`, and `hard`). Every observed grudge participant is guaranteed **not** to be the decoy:

| Metric | `easy` (`n=12`, no decoy) | `medium` (`n=20`, decoy) | `hard` (`n=40`, decoy, `default`) | `hard` (`n=40`, decoy, `random_peer`) |
|---|---|---|---|---|
| Analytical $P(\text{is\_mole} \mid \text{grudge pair member})$ | `0.083333` (`1/12`) | `0.052632` (`1/19`) | `0.025641` (`1/39`) | `0.025641` (`1/39`) |
| Empirical $P(\text{is\_mole} \mid \text{grudge participant})$ | `0.100000 +- 0.020789` (`80/800`) | `0.053750 +- 0.015628` (`43/800`) | `0.026250 +- 0.011079` (`21/800`) | `0.026250 +- 0.011079` (`21/800`) |
| Empirical $P(\text{is\_mole} \mid \text{grudge event target})$ | `0.105427 +- 0.011191` (`305/2,893`) | `0.054142 +- 0.008455` (`149/2,752`) | `0.028273 +- 0.005008` (`119/4,209`) | `0.025946 +- 0.004807` (`109/4,201`) |
| Empirical $P(\text{is\_mole} \mid \text{not grudge target})$ | `0.075542 +- 0.012889` (`122/1,615`) | `0.048803 +- 0.007445` (`157/3,217`) | `0.024858 +- 0.003596` (`179/7,201`) | `0.024861 +- 0.003597` (`179/7,200`) |
| **Empirical $P(\text{is\_decoy} \mid \text{grudge target} \ge 1)$** | `0.000000` (`0/785`) | **`0.000000`** (`0/783`) | **`0.000000`** (`0/799`) | **`0.000000`** (`0/800`) |
| **Empirical $P(\text{is\_decoy} \mid \text{grudge participant})$** | `0.000000` (`0/800`) | **`0.000000`** (`0/800`) | **`0.000000`** (`0/800`) | **`0.000000`** (`0/800`) |
| **Empirical $P(\text{is\_decoy} \mid \text{grudge pair member})$** | `0.000000` (`0/800`) | **`0.000000`** (`0/800`) | **`0.000000`** (`0/800`) | **`0.000000`** (`0/800`) |

Combining both side-channels (`score[e] = count(rumour: e) + 2 * count(unverified accusation: e)` restricted to `e not in grudge_participants`) yields a rapid decoy-identification and safe-exclusion curve across checkpoints (`n=200` seeds, `7500-7699`):

| Tier | Checkpoint Day | Episodes w/ Candidate | Safe Exclusion (`top != mole`) | Exact Decoy Match (`top == decoy`) |
|---|---|---|---|---|
| `medium` | Day 3 | `200/200` | `98.0% +- 1.94%` (`196/200`) | `75.0% +- 6.00%` (`150/200`) |
| `medium` | Day 6 | `200/200` | `99.0% +- 1.38%` (`198/200`) | `92.5% +- 3.65%` (`185/200`) |
| `medium` | Day 10 | `200/200` | `99.5% +- 0.98%` (`199/200`) | `98.5% +- 1.68%` (`197/200`) |
| `medium` | Day 14 | `200/200` | `99.5% +- 0.98%` (`199/200`) | `99.5% +- 0.98%` (`199/200`) |
| `hard` | Day 3 | `200/200` | `98.5% +- 1.68%` (`197/200`) | `71.5% +- 6.26%` (`143/200`) |
| `hard` | Day 6 | `200/200` | **`100.0% +- 0.00%` (`200/200`)** | **`94.5% +- 3.16%` (`189/200`)** |
| `hard` | Day 10 | `200/200` | **`100.0% +- 0.00%` (`200/200`)** | **`99.5% +- 0.98%` (`199/200`)** |
| `hard` | Day 21 | `200/200` | **`100.0% +- 0.00%` (`200/200`)** | **`100.0% +- 0.00%` (`200/200`)** |

### 4.4 Misforward Holder-Set Expansion & Attribution (`p_misforward = 0.15`, Seeds `7500-7699`)

In `Env._misforward()` (`canary/env.py:358-365`), each published regular document is independently forwarded (`p_misforward=0.15`) using `random.Random(f"{world_seed}:fwd:{doc_id}")` to one uniform non-restricted non-recipient `x`, appending `x` to `doc["recipients"]` and setting `doc["forwarded_to"] = x`.

| Metric | `easy` (`n=12`, `200` seeds) | `medium` (`n=20`, `200` seeds) | `hard` (`n=40`, `200` seeds) |
|---|---|---|---|
| Regular documents published | `8,373` | `8,319` | `12,674` |
| Misforwarded documents (`rate +- 95% CI`) | `1,223` (`14.61% +- 0.76%`) | `1,295` (`15.57% +- 0.78%`) | `1,958` (`15.45% +- 0.63%`) |
| Mean base recipients -> effective recipients (`+%` slots) | `5.9963 -> 6.1424` (`+2.44%`) | `10.0206 -> 10.1762` (`+1.55%`) | `15.9954 -> 16.1499` (`+0.97%`) |
| Empirical $P(\text{is\_mole} \mid \text{forwarded\_to event})$ vs $1/n$ prior | `0.0670 +- 0.0140` vs `0.0833` | `0.0456 +- 0.0114` vs `0.0500` | `0.0220 +- 0.0065` vs `0.0250` |
| Empirical $P(\text{is\_mole} \mid \text{forwarded\_to} \ge 1)$ | `0.0737 +- 0.0164` (`72/977`) | `0.0440 +- 0.0121` (`49/1,113`) | `0.0216 +- 0.0068` (`38/1,761`) |
| Empirical $P(\text{is\_mole} \mid \text{forwarded\_to} == 0)$ | `0.0900 +- 0.0149` (`128/1,423`) | `0.0523 +- 0.0081` (`151/2,887`) | `0.0260 +- 0.0039` (`162/6,239`) |
| Total leaked regular documents | `2,441` | `2,023` | `2,525` |
| Leaks enabled solely by `forwarded_to == mole` | `43/2,441` (`1.76% +- 0.52%`) | `30/2,023` (`1.48% +- 0.53%`) | `19/2,525` (`0.75% +- 0.34%`) |
| **Episodes w/ `>= 1` mole leak via misforward** | **`39/200` (`19.50% +- 5.49%`)** | **`26/200` (`13.00% +- 4.66%`)** | **`18/200` (`9.00% +- 3.97%`)** |
| Mean leaked regular-doc holder intersection (base -> effective) | `2.875 -> 3.070` (`+0.195` suspects) | `4.985 -> 5.115` (`+0.130` suspects) | `7.970 -> 8.060` (`+0.090` suspects) |

Key takeaway: `forwarded_to` is mole-independent (no identity leak), widens the regular-document candidate intersection by `+0.09` (`hard`) to `+0.20` (`easy`) suspects per episode, and creates a soundness trap for any brittle rule-based parser that strips `forwarded_to` from `recipients` (`9.0%-19.5%` false mole elimination rate).

### 4.5 Adversarial Social Heuristics vs Paired `SolverPolicy`

Five policies were evaluated on identical paired seeds in `v1.5-candidate`:
- `solver`: Reference `SolverPolicy` (`canary/solver/policy.py`).
- `anti_rumour_solver`: `SolverPolicy` subclass that actively queries `grudge:`, `rumour:`, and `unverified accusation:` and applies `rumour - grudge` decoy inference (`n1 >= 3` and `n1 >= 2 * max(1, n2)`) plus exact `social_loglik` before decoy lock-in.
- `rumour_follower`: Bias-trap probe (`canary/baselines.py:311-327`) accusing `argmax(rumour + 3*authority + grudge)` on Day 7.
- `logs_minus_decoy`: Day-6 access-log accuser masking the `ANGER_WORDS` decoy.
- `logs_anti_rumour`: Day-6 access-log accuser replacing `ANGER_WORDS` masking with `rumour + 2*authority` minus `grudge_participants`.

| Slice (`seed_rumour`) | Seeds (`n`) | Policy | Mean Score (`+-95% CI`) | Paired Diff vs Baseline (`+-95% CI`, `W/T/L`) | Acc | Acc When Accusing | Abstain | Mean Accuse Day | Decoy ID Rate | Mean Social Ingested |
|---|---|---|---|---|---|---|---|---|---|---|
| `hard` (`default`) | `7500-7699` (`200`) | `solver` | `0.5767 +- 0.0365` | baseline | `97.5%` | `98.0%` | `0.5%` | `9.24` | `66.5%` | `0.00` |
| `hard` (`default`) | `7500-7699` (`200`) | `anti_rumour_solver` | `0.5785 +- 0.0402` | `+0.0018 +- 0.0516` (`92/35/73` vs `solver`) | `96.5%` | `97.5%` | `1.0%` | `8.80` | **`87.5%`** | `8.96` |
| `hard` (`default`) | `7500-7699` (`200`) | `rumour_follower` | `-0.9815 +- 0.0256` | `-1.5582` vs `solver` | `1.0%` | `1.0%` | `0.0%` | `7.00` | `0.0%` | `0.00` |
| `hard` (`default`) | `7500-7699` (`200`) | `logs_minus_decoy` | `-0.9080 +- 0.0557` | log baseline | `5.0%` | `5.0%` | `0.0%` | `6.00` | `0.0%` | `0.00` |
| `hard` (`default`) | `7500-7699` (`200`) | `logs_anti_rumour` | `-0.7215 +- 0.0921` | **`+0.1865 +- 0.0778`** (vs `logs_minus_decoy`) | **`15.0%`** | `15.0%` | `0.0%` | `6.00` | `0.0%` | `0.00` |
| `medium` (`default`) | `7500-7699` (`200`) | `solver` | `0.6523 +- 0.0331` | baseline | `90.0%` | `100.0%` | `10.0%` | `7.72` | `69.0%` | `0.00` |
| `medium` (`default`) | `7500-7699` (`200`) | `anti_rumour_solver` | `0.6307 +- 0.0341` | `-0.0216 +- 0.0368` (`48/86/66` vs `solver`) | `89.0%` | `100.0%` | `11.0%` | `8.11` | **`80.5%`** | `8.80` |
| `medium` (`default`) | `7500-7699` (`200`) | `rumour_follower` | `-0.9640 +- 0.0350` | `-1.6163` vs `solver` | `2.0%` | `2.0%` | `0.0%` | `7.00` | `0.0%` | `0.00` |
| `medium` (`default`) | `7500-7699` (`200`) | `logs_minus_decoy` | `-0.9630 +- 0.0360` | log baseline | `2.0%` | `2.0%` | `0.0%` | `6.00` | `0.0%` | `0.00` |
| `medium` (`default`) | `7500-7699` (`200`) | `logs_anti_rumour` | `-0.8988 +- 0.0583` | **`+0.0642 +- 0.0468`** (vs `logs_minus_decoy`) | **`5.5%`** | `5.5%` | `0.0%` | `6.00` | `0.0%` | `0.00` |
| `hard` Gate B (`default`) | `0-9` (`10`) | `solver` | `0.6150 +- 0.0678` | baseline | `100.0%` | `100.0%` | `0.0%` | `8.70` | `50.0%` | `0.00` |
| `hard` Gate B (`default`) | `0-9` (`10`) | `anti_rumour_solver` | `0.6650 +- 0.0708` | `+0.0500 +- 0.0627` (`7/0/3` vs `solver`) | `100.0%` | `100.0%` | `0.0%` | `8.00` | **`100.0%`** | `7.40` |
| `easy` (`default`) | `7500-7549` (`50`) | `solver` | `0.7854 +- 0.0339` | baseline | `100.0%` | `100.0%` | `0.0%` | `4.96` | `n/a` | `0.00` |
| `easy` (`default`) | `7500-7549` (`50`) | `anti_rumour_solver` | `0.7946 +- 0.0291` | `+0.0092 +- 0.0215` (`7/39/4` vs `solver`) | `100.0%` | `100.0%` | `0.0%` | `4.84` | `n/a` | `8.38` |
| `hard` (`random_peer`) | `7500-7549` (`50`) | `solver` | `0.6008 +- 0.0756` | baseline | `96.0%` | `98.0%` | `2.0%` | `8.53` | **`70.0%`** | `0.00` |
| `hard` (`random_peer`) | `7500-7549` (`50`) | `anti_rumour_solver` | `0.5324 +- 0.0980` | **`-0.0684 +- 0.1175`** (`14/7/29` vs `solver`) | `96.0%` | `96.0%` | `0.0%` | `9.60` | **`2.0%`** | `18.54` |
| `hard` (`random_peer`) | `7500-7549` (`50`) | `rumour_follower` | `-0.9640 +- 0.0706` | `-1.5648` vs `solver` | `2.0%` | `2.0%` | `0.0%` | `7.00` | `0.0%` | `0.00` |

Why `anti_rumour_solver` ties `solver` on 200-seed `hard` (`+0.0018 +- 0.0516`) and slightly trails on `medium` (`-0.0216 +- 0.0368`): `SolverPolicy` has `8` daily investigative actions; spending `1-2` actions/day querying `rumour:` / `grudge:` accelerates decoy lock-in (`87.5%` vs `66.5%` on `hard`, saving `0.44` accusation days), which helps when `behaviour_temper=0.3` access-log likelihoods are noisy (`+0.0500` on seeds `0-9`), whereas on `medium` (`20` staff) canary partitions already isolate the mole quickly and extra message searches occasionally consume daily action budget without shifting the canary schedule. Crucially, no social-inversion policy can bypass canary planting (`logs_anti_rumour = -0.7215` on `hard`, `-0.8988` on `medium`), confirming that **none of the social tells constitute a positive-score reward exploit**.

## 5. Report-Only Issues for Silas & `v1.6` Social-Layer Designers

Per project rules, zero protected files were edited. The five structural findings below are reported as design issues for `justSilas` / `v1.6` social-layer iteration:

1. **`ISS-V15-01` (Medium, Statistical Side-Channel): Rumour & Authority Anti-Inversion (`P(is_mole | rumoured) < prior`, Top-Rumoured = `100%` Decoy on `hard`).**
   - **Location:** `canary/env.py:382-401`, `canary/mole/dsl.py:169-174` (`origin/justSilas-v15 @ de9cc50e`).
   - **Finding:** Because `peers` excludes `w.mole` and `DEFAULT_STRATEGY` sets `seed_rumour="default"` (`decoy` if present, else `random_peer`), seeded rumours (`40%`) never name the mole. On `hard`, `P(is_mole | rumoured) = 0.0170` vs prior `0.0250`, and the single most-rumoured employee is the decoy on `200/200` (`100.0%`) episodes (`0/200` mole). On `easy` (no decoy), unrumoured employees have `P(is_mole | rumours == 0) = 0.2446` (`2.94x` prior).
   - **Recommendation for `v1.6`:** Draw episode rumour focal targets from a mole-independent office-salience prior (e.g., 1-2 latent "watercooler scapegoats" drawn uniformly from `self._ids` **including** the mole unless overridden by an explicit Mole DSL costed action, or mix a calibrated `1/n` self-inclusion floor into seeded rumours) so marginal $P(\text{is\_mole} \mid \text{rumour count})$ equals $1/n$ and high rumour volume cannot be mechanically inverted into a `100%` safe-exclusion oracle.

2. **`ISS-V15-02` (Medium, Structural Side-Channel): Grudge Pairs Exclude Decoy (`P(is_decoy | grudge_participant) = 0.000`).**
   - **Location:** `canary/env.py:257` and `canary/env.py:367-374` (`pool = [e for e in self._ids if e != self._world.decoy]`).
   - **Finding:** Excluding `self._world.decoy` from `_grudges()` makes every sender and target of a `grudge:` message `0%` likely to be the decoy (`0/800` across `easy`, `medium`, `hard`, and `hard` `random_peer`), allowing a 1-call `search_messages(query="grudge:")` filter to strip all grudge noise from rumour counts (`94.5%` exact decoy match by Day 6 on `hard`).
   - **Recommendation for `v1.6`:** Draw grudge pairs from `list(self._ids)` uniformly **without** excluding `self._world.decoy` (making grudges jointly independent of both `mole` and `decoy`), and update `_social_instruction` to state `"drawn uniformly from all employees"`.

3. **`ISS-V15-03` (Low-Medium, Surface Tell): Regex-Trivial Social Subject Prefixes (`rumour:`, `unverified accusation:`, `grudge:`) & `-s` Message IDs.**
   - **Location:** `canary/text/template.py:222-231` (`f"rumour: {t.id}"`, `f"m{facts.day}-s{k}"`), `canary/solver/policy.py:47`.
   - **Finding:** Structured prefixes and `-s` IDs let scripted heuristics or tool-calling LLMs isolate or discard the entire human-bias layer in 1-3 substring queries without reading message bodies, and distinguish social messages from organic decoy anger posts by ID format alone.
   - **Recommendation for `v1.6`:** Assign social messages sequential daily message IDs from the same counter as `day_messages` (`m{day}-{idx}`) and replace `rumour: eXX` / `grudge: eXX` subjects with naturalistic workplace subjects while keeping stated generative rules in the prompt.

4. **`ISS-V15-04` (Low, Solver Wiring / Strategy Robustness): `SolverPolicy.decoy_queries()` Never Queries Social Messages (`o.social` Always Empty in Live Play).**
   - **Location:** `canary/solver/policy.py:191-195, 231-247`, `canary/solver/belief.py:234-254`.
   - **Finding:** `SolverPolicy._ingest` parses `_SOCIAL_RE` into `o.social` and `belief.social_loglik` models it, but `SolverPolicy.decoy_queries()` only queries `ANGER_WORDS`, resulting in `0.00` social messages ingested across all `450` tested episodes. At the same time, `belief.social_loglik` assumes `DEFAULT_STRATEGY` (`seed_rumour="default"`), which would become misspecified on `hard_forge` if an evolved mole selects `seed_rumour="most_restricted_peer"` or `"decoy"` vs `"random_peer"`.
   - **Recommendation for `v1.6`:** Keep `SolverPolicy` independent of unverified social chatter on decoy/forge tracks (where canary MI already achieves `97.5%` accuracy and avoids `seed_rumour` model-mismatch traps), or guard `social_loglik` behind `not P.forge` when `o.social` is populated via broader message searches.

5. **`ISS-V15-05` (Informational, Verified Sound): Misforward `forwarded_to` Exposure & Base-Recipient Intersection Trap.**
   - **Location:** `canary/env.py:261-265, 358-365`.
   - **Finding:** `Env._misforward()` uses an independent `world_seed:fwd:doc_id` RNG stream (`P(is_mole | forwarded_to) = 0.0220 +- 0.0065` vs `0.0250` prior on `hard`, zero mole leak) and appends `forwarded_to` into `doc["recipients"]`. Across `200` seeds/tier, `9.0%` (`hard`) to `19.5%` (`easy`) of episodes feature a regular-document leak where `mole == forwarded_to`.
   - **Recommendation for `v1.6`:** Retain `forwarded_to` inside `doc["recipients"]` (essential for exact holder-set soundness). Optionally consider omitting the separate `"forwarded_to"` badge on a subset of misforwarded docs in a future noisy-paperwork tier only if explicitly parameterized by a known false-omission/addition rate; for `v1.5`/`v1.6` standard tiers, the current `p_misforward=0.15` design is clean, fair, and verified leak-free.
