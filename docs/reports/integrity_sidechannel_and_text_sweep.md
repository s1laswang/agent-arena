# Canary `v1.4` Non-Canary Side-Channel, Text-Leak & Post-`1bc3e281` `detail` Parity Sweep

## 1. Executive Summary

- **Scope & Base:** Large zero-API-call side-channel, non-canary feature, steganographic/encoded-secret, and tool-response byte/error `detail` parity sweep across all `5` Canary `v1.4` judge targets (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`) on `1,200` primary episodes (`200` dev seeds `0-199` + `40` judge seeds `900000-900039` per target under deterministic public test secret `canary-anticheat-public-test-v1`). Zero protected paths were modified (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`).
- **Overall Gate Status: PASS (`ok = True` across all `6` audit families, `0` API calls, runtime `369.928s` full / `6.479s` `--quick`).**
  - **Non-canary feature & text predictors (`24` predictors x `5` targets = `120` pooled tests + `240` band-stratified dev/judge tests):** **`0` predictors beat their documented fair bar** at family-wise `alpha = 0.01` (`non_canary_predictors_beating_fair_bar = 0` on pooled `n = 240`, dev `n = 200`, and post-hoc lock judge band `900000-900039` `n = 40`). Every non-canary predictor has strictly negative `always_accuse_mean_score` across all `5` targets (`-1.000000` to `-0.002292`).
  - **Ordering, sequence & text-lint invariants (`65,572` documents, `704,193` access logs, `145,512` messages, `358,204` prose texts):** `0` document recipient order/duplication inversions, `0` access-log `(day, employee, doc_id, after_hours)` sort inversions, `0` per-day message ID sequence gaps, `0` `lint_messages` violations, and `0` interview signal-to-template mismatches across all `1,200` episodes.
  - **Conditional interview prose parity (`8` `(topic, signal)` strata x `5` targets = `40` strata):** Conditioning on the true `(topic, cooperative/evasive)` draw eliminates template-length confounding: **`0 / 40` strata flag a byte or token length leak** at Bonferroni-corrected `alpha = 0.01` (`conditional_interview_leaks = 0`; minimum `16x`-adjusted `p = 0.02096` on `hard` `access_needs:evasive`, `0.033856` on `hard_forge`, `0.367776` on `medium`, `0.69976` on `hard_rl`, `0.939296` on `easy`).
  - **State-matched `13`-tool byte parity & post-`1bc3e281` error `detail` audit (`1,200` seed pairs, `179,040` `detail` probes):** All `13` public tools (`list_employees`, `status`, `list_documents`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `plant_canary`, `check_leak_feed`, `restrict_access`, `unrestrict_access`, `advance_day`, `accuse`) exhibit exact `0`-byte serialized size difference between state-matched mole vs innocent calls (`1,200 / 1,200` pairs, `0` `ok`-flag mismatches). Across `179,040` invalid-argument and state-error probes auditing commit `1bc3e281` (`{"detail": ...}` on `BAD`), there are `0` actor parity mismatches (`mole` vs `innocent` vs `decoy`), `0` schema envelope violations, `0` cross-seed `detail` fingerprint drifts, `0` mole ID/name leaks, `0` world-seed leaks, and `0` hidden-`V` leaks (`1,148 / 1,200` episodes reached `true_V < visible_V()` during hidden-`V` stress).
  - **Deep `107`-encoding steganographic & secret-token scan (`300` episodes, `84,976` texts + `358,204` fast-scan texts):** `canary.redteam.encodings.self_test()` achieves `118 / 118` (`recall = 1.0`, `0` false positives across `107` encodings and `11` split modes), and scanning `60` episodes per target (`0-19` dev + `900000-900039` judge, `84,976` texts) plus fast zero-width/Braille/homoglyph/punycode/Morse/NATO scans across all `358,204` primary texts yields **`0` encoded secret leaks** (`encoded_secret_leaks = 0`).
  - **Planted positive controls (`6 / 6` synthetic side-channels caught) & solver calibration (`5 / 5` targets):** All `6` planted positive controls (roster name-length leak, document/access-log ordering leak, `restrict_access` byte-padding leak, zero-byte-diff `detail` actor-parity leak, `detail` `[mole, world_seed, true_v]` secret leak, and `5` steganographic modes) are deterministically caught (`planted_positive_controls_all_detected = True`), and `SolverPolicy` strictly outperforms both always-accuse and calibrated selective non-canary Bayes policies on all `5` targets (`solver_beats_non_canary_all_targets = True`).
- **Three Report-Only Issues Logged (Zero Protected-Path Edits):** `ISSUE-W1-TEXTPROBE-TRACKS` (low), `ISSUE-W1-SOLVER-IV-INGEST` (low), and `ISSUE-W1-HARD-RL-DEPTS` (medium).

## 2. Reproduce Commands (`0` API Calls)

Run the fast smoke sweep, report validator, and pytest suite (`< 10s`, `0` API calls):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_sidechannel_and_text_sweep.py --quick --out-json /tmp/opencode/w1_sweep/quick_check.json --check-report docs/reports/integrity_sidechannel_and_text_sweep.md
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_sidechannel_and_text_sweep.py
```

Reproduce the full `1,200`-episode (`0-199` dev + `900000-900039` judge x `5` targets) sweep:

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_sidechannel_and_text_sweep.py --workers 4 --out-json /tmp/opencode/w1_sweep/summary.json --check-report docs/reports/integrity_sidechannel_and_text_sweep.md
```

## 3. Fair Bars & Non-Canary Feature Sweep (`1,200` Episodes Across `5` Targets)

### 3.1 Exact & Monte Carlo (`20,000` Trials) Non-Canary Fair Bars (`v1.4`)

| Target | Staff `N` (`N_cand`) | Closed Days | Budget `k_iv` | Chance `1/N` | Decoy-Excl `1/N_cand` | Interview `k_iv` Bar (Decoy-Excl) | Interview `k=4` Bar (Decoy-Excl) | Access-Logs Exact Poisson Bayes | Joint Non-Canary (Logs + `4` IVs) |
|---|---|---|---|---|---|---|---|---|---|
| `easy` | `12` (`12`) | `13` | `4` | `0.083333` | `0.083333` | `0.170325` | `0.170325` | `0.387729` | `0.418446` |
| `medium` | `20` (`19`) | `13` | `2` | `0.050000` | `0.052632` | `0.077130` | `0.089491` | `0.107392` | `0.124033` |
| `hard` | `40` (`39`) | `20` | `2` | `0.025000` | `0.025641` | `0.035358` | `0.039769` | `0.484333` | `0.487267` |
| `hard_forge` | `40` (`39`) | `20` | `2` | `0.025000` | `0.025641` | `0.035358` | `0.039769` | `0.484333` | `0.487267` |
| `hard_rl` | `40` (`39`) | `20` | `2` | `0.025000` | `0.025641` | `0.035358` | `0.039769` | `0.484333` | `0.487267` |

### 3.2 Corpus Scale, Ordering Invariants & Roster Uniformity (`n = 240` Pooled Episodes / Target)

| Target | Episodes (`Dev + Judge`) | Docs Checked | Access Logs Checked | Messages Checked | Prose Texts Scanned | Decoy ID Acc | Roster Index `chi^2` (`df`) | Order / ID / Lint / Template Violations | Predictors Beating Fair Bar |
|---|---|---|---|---|---|---|---|---|---|
| `easy` | `240` (`200 + 40`) | `10,125` | `37,669` | `21,812` | `43,697` | `n/a` (no decoy) | `8.2000` (`11`) | `0` | `0 / 24` |
| `medium` | `240` (`200 + 40`) | `10,058` | `66,968` | `21,978` | `51,476` | `1.000000` | `21.3333` (`19`) | `0` | `0 / 24` |
| `hard` | `240` (`200 + 40`) | `15,130` | `198,632` | `33,758` | `87,528` | `1.000000` | `47.3333` (`39`) | `0` | `0 / 24` |
| `hard_forge` | `240` (`200 + 40`) | `15,166` | `199,040` | `34,036` | `87,842` | `1.000000` | `54.3333` (`39`) | `0` | `0 / 24` |
| `hard_rl` | `240` (`200 + 40`) | `15,093` | `201,884` | `33,928` | `87,661` | `1.000000` | `35.0000` (`39`) | `0` | `0 / 24` |
| **Total** | **`1,200` (`1,000 + 200`)** | **`65,572`** | **`704,193`** | **`145,512`** | **`358,204`** | **`1.000000` (`960/960`)** | **All uniform** | **`0`** | **`0 / 120`** |

### 3.3 Representative Non-Canary Predictor Accuracy & Always-Accuse EV (`n = 240` / Target)

All `24` predictors per target (`8` roster metadata/2-fold CV Naive Bayes, `3` document recipient frequency/position, `3` Slack message volume/length/2-fold BoW, `5` interview stub/length/token/BoW/template Bayes, `4` access-log rank/linear/Poisson Bayes, and `1` joint non-canary Bayes) were tested against their exact channel fair bar with `24x` Bonferroni correction (`alpha = 0.01`), both pooled (`n = 240`) and separately on `dev` (`0-199`, `n = 200`) and `judge` (`900000-900039`, `n = 40`):

| Predictor (`Family`) | `easy` Acc (`EV`) | `medium` Acc (`EV`) | `hard` Acc (`EV`) | `hard_forge` Acc (`EV`) | `hard_rl` Acc (`EV`) | `beats_fair_bar` |
|---|---|---|---|---|---|---|
| `roster_first_id` (`roster`) | `0.083333` (`-0.879583`) | `0.050000` (`-0.918500`) | `0.025000` (`-0.965417`) | `0.045833` (`-0.917917`) | `0.033333` (`-0.951250`) | `False` (`5/5`) |
| `roster_joint_cv_nb` (`roster`) | `0.062500` (`-0.910417`) | `0.033333` (`-0.945000`) | `0.016667` (`-0.977708`) | `0.004167` (`-0.992917`) | `0.029167` (`-0.957708`) | `False` (`5/5`) |
| `doc_recipient_count_max` (`documents`) | `0.070833` (`-0.900417`) | `0.070833` (`-0.883000`) | `0.033333` (`-0.954583`) | `0.045833` (`-0.922708`) | `0.037500` (`-0.945417`) | `False` (`5/5`) |
| `msg_bow_cv_llr` (`messages`) | `0.054167` (`-0.921875`) | `0.058333` (`-0.906000`) | `0.033333` (`-0.954167`) | `0.016667` (`-0.971875`) | `0.041667` (`-0.940208`) | `False` (`5/5`) |
| `text_probe_stub_budget` (`interviews`) | `0.204167` (`-0.708333`) | `0.062500` (`-0.899167`) | `0.033333` (`-0.953958`) | `0.037500` (`-0.935417`) | `0.025000` (`-0.963958`) | `False` (`5/5`) |
| `iv_4topic_bow_cv_llr` (`interviews`) | `0.120833` (`-0.822708`) | `0.058333` (`-0.904333`) | `0.033333` (`-0.953333`) | `0.037500` (`-0.932083`) | `0.037500` (`-0.946042`) | `False` (`5/5`) |
| `log_position_mean_rank` (`access_logs`) | `0.100000` (`-0.855417`) | `0.058333` (`-0.903833`) | `0.020833` (`-0.972500`) | `0.020833` (`-0.964167`) | `0.012500` (`-0.982083`) | `False` (`5/5`) |
| `log_naive_after_hours` (`access_logs`) | `0.329167` (`-0.521458`) | `0.004167` (`-0.992833`) | `0.000000` (`-1.000000`) | `0.000000` (`-1.000000`) | `0.000000` (`-1.000000`) | `False` (`5/5`) |
| `log_exact_poisson_bayes` (`access_logs`) | `0.337500` (`-0.511042`) | `0.091667` (`-0.851333`) | `0.479167` (`-0.340625`) | `0.554167` (`-0.030625`) | `0.391667` (`-0.426667`) | `False` (`5/5`) |
| `joint_non_canary_bayes` (`joint_behaviour`) | `0.358333` (`-0.480625`) | `0.091667` (`-0.850667`) | `0.500000` (`-0.312500`) | `0.570833` (`-0.002292`) | `0.400000` (`-0.413542`) | `False` (`5/5`) |

Note on `hard_forge`: because `hof_v12` (`forge_g432_2251`) suppresses early leaks, unperturbed `final_V` averages `0.742500` (vs `0.380625` on `hard`) and fewer innocent framing events accumulate early, giving `joint_non_canary_bayes` `137 / 240 = 0.570833` (`p_bonf = 0.137949 >= 0.01`, still non-significant and negative EV `-0.002292`). On both `dev` (`min p_bonf = 0.189604`) and `judge` (`900000-900039`, `min p_bonf = 0.418788`), `0` predictors cross `alpha = 0.01`.

### 3.4 Conditional Interview Byte & Token Length Stratification (`40` Strata)

Unconditionally, mole interview answers are slightly shorter (`-0.87` to `-3.70` bytes) solely because `interview_lr > 1` makes the mole draw the shorter `"evasive"` template more often. Within every `(topic, signal)` stratum (`8` strata x `2` metrics = `16` tests/target), mole vs innocent answer lengths are indistinguishable:

| Target | Signal-Template Mismatches | Worst Stratum (`topic:signal`) | Byte `z` (`p`) | Token `z` (`p`) | `16x` Adjusted Min `p` | `conditional_leak` |
|---|---|---|---|---|---|---|
| `easy` | `0` | `workload:evasive` | `1.6583` (`0.097260`) | `1.8904` (`0.058706`) | `0.939296` | `False` (`0/8`) |
| `medium` | `0` | `access_needs:cooperative` | `2.2737` (`0.022986`) | `1.2140` (`0.224740`) | `0.367776` | `False` (`0/8`) |
| `hard` | `0` | `access_needs:evasive` | `-2.9323` (`0.003364`) | `-3.2137` (`0.001310`) | `0.020960` | `False` (`0/8`) |
| `hard_forge` | `0` | `workload:cooperative` | `2.7647` (`0.005697`) | `3.0735` (`0.002116`) | `0.033856` | `False` (`0/8`) |
| `hard_rl` | `0` | `recent_documents:cooperative` | `1.0547` (`0.291549`) | `2.0166` (`0.043735`) | `0.699760` | `False` (`0/8`) |

## 4. State-Matched `13`-Tool Byte Parity & Post-`1bc3e281` Error `detail` Audit

Across `1,200` paired episodes (`240` per target), each of the `13` tools was invoked on identically prepared `Env(target, seed)` instances targeting `mole` vs a seeded random non-decoy `innocent` peer, alongside `179,040` invalid-schema, day-bound, unknown-ID, state-conflict, daily-cap, and hidden-`V` (`true_V < visible_V()`) error `detail` probes verifying commit `1bc3e281`:

| Target | Seed Pairs | `13`-Tool State-Matched Max Byte Diff | `ok`-Flag Mismatches | `detail` Probes Checked | Actor Parity / Envelope / Cross-Seed Mismatches | `mole` / `seed` / `hidden_V` Leaks | Hidden-`V` States Exercised | Roster Row Paired `z` (`p`) |
|---|---|---|---|---|---|---|---|---|
| `easy` | `240` | `0` (`13/13` tools) | `0` | `28,320` | `0 / 0 / 0` | `0 / 0 / 0` | `240 / 240` | `0.6271` (`0.530585`) |
| `medium` | `240` | `0` (`13/13` tools) | `0` | `37,680` | `0 / 0 / 0` | `0 / 0 / 0` | `240 / 240` | `0.7117` (`0.476651`) |
| `hard` | `240` | `0` (`13/13` tools) | `0` | `37,680` | `0 / 0 / 0` | `0 / 0 / 0` | `240 / 240` | `-0.9214` (`0.356820`) |
| `hard_forge` | `240` | `0` (`13/13` tools) | `0` | `37,680` | `0 / 0 / 0` | `0 / 0 / 0` | `188 / 240` | `-0.2669` (`0.789539`) |
| `hard_rl` | `240` | `0` (`13/13` tools) | `0` | `37,680` | `0 / 0 / 0` | `0 / 0 / 0` | `240 / 240` | `0.5735` (`0.566299`) |
| **Total** | **`1,200`** | **`0` (`100%` exact)** | **`0`** | **`179,040`** | **`0 / 0 / 0`** | **`0 / 0 / 0`** | **`1,148 / 1,200`** | **All `p >= 0.3568`** |

## 5. Deep `107`-Encoding Scan, Policy Calibration & Planted Positive Controls

### 5.1 Deep Steganographic & `107`-Encoding Audit (`300` Episodes, `84,976` Texts)

- **Encoder/decoder self-test:** `107` encodings, `107` decoders, `11` split modes -> `118 / 118` planted cases detected (`recall = 1.0`, `false_positives = 0`).
- **Live world prose audit (`seeds 0-19` dev + `900000-900039` judge = `60` episodes/target, `300` total):** `10,431` (`easy`) + `12,398` (`medium`) + `20,706` (`hard`) + `20,703` (`hard_forge`) + `20,738` (`hard_rl`) = **`84,976` texts scanned**, **`0` leaks** (`total_leaks = 0`). Fast scans across all `358,204` primary prose texts likewise found `0` zero-width characters, `0` Braille patterns, `0` non-ASCII characters, `0` punycode tokens, `0` Morse runs, and `0` `>= 3`-word NATO runs.

### 5.2 Solver vs Non-Canary Policy Calibration (`40` Dev Seeds `0-39` / Target)

Even when a non-canary investigator combines all `n_days - 1` interview slots with full access logs, anger-based decoy exclusion, and selective accusation only when posterior `P(best) > 1 / (1 + visible_V)`, `SolverPolicy` strictly dominates across every target:

| Target | `SolverPolicy` Mean Score (`Acc`) | Non-Canary Always-Accuse Score (`Acc`) | Non-Canary Selective Score (`Accuse Rate`, `Precision`) | Solver Margin Over Best Non-Canary |
|---|---|---|---|---|
| `easy` | `0.800500` (`1.000`) | `-0.352500` (`0.450`) | `0.022500` (`0.050`, `1.000000`) | `+0.778000` |
| `medium` | `0.643500` (`0.900`) | `-0.759000` (`0.150`) | `0.000000` (`0.000`, `n/a`) | `+0.643500` |
| `hard` | `0.441000` (`0.900`) | `-0.353750` (`0.475`) | `0.068750` (`0.175`, `1.000000`) | `+0.372250` |
| `hard_forge` | `0.520000` (`0.925`) | `-0.052500` (`0.525`) | `0.250000` (`0.525`, `0.809524`) | `+0.270000` |
| `hard_rl` | `0.275750` (`0.675`) | `-0.307500` (`0.475`) | `0.096250` (`0.425`, `0.823529`) | `+0.179500` |

### 5.3 Planted Positive Controls (`6 / 6` Detected)

| Planted Side-Channel Control | Perturbation Mechanism | Measured Detection Signal | Detected |
|---|---|---|---|
| `planted_roster_name_length_leak` | `+40` UTF-8 bytes added to mole `name_bytes` across `24` `easy` episodes | `roster_name_longest` accuracy `1.000000` (`p_bonf = 0.0`) | `True` |
| `planted_doc_and_log_ordering_leak` | Mole shifted to `doc_first` (`+50`) + `48` doc & `72` log inversions | `doc_first_recipient_freq` accuracy `1.000000` + `120` inversions | `True` |
| `planted_tool_response_byte_leak` | `PlantedToolByteLeakEnv` pads `restrict_access` on mole (`+15` bytes) | `restrict_access_max_byte_diff = 15` (`8` seeds) | `True` |
| `planted_tool_detail_parity_leak` | `PlantedToolDetailParityEnv` swaps equal-byte `detail` text on `unrestrict_access` for mole | `zero_byte_diff_evaded_size_check = True`, caught by `16` `detail` parity mismatches | `True` |
| `planted_tool_detail_secret_leak` | `PlantedToolDetailSecretLeakEnv` appends `[ref=mole ws=world_seed true_v=V]` to `read_message` `detail` | Caught `72` mole leaks, `96` seed leaks, `136` hidden-`V` leaks | `True` |
| `planted_stego_text_leaks` | Encodes `"mole=e07"` via `zero_width_stego`, `cyrillic_homoglyphs`, `morse`, `nato_phonetic`, `acrostic_words` | `5 / 5` steganographic modes decoded & flagged | `True` |

## 6. Report-Only Issues Logged for Silas (Zero Protected-Path Edits)

1. **`ISSUE-W1-TEXTPROBE-TRACKS` (Low - `canary/redteam/text_probe.py:72, 196`):**
   - `text_probe.collect` (`line 72`) and `text_probe.fair_bar` (`line 196`) look up `TIERS[tier]` directly instead of `tier_params(tier)`, raising `KeyError: 'hard_forge'` and `KeyError: 'hard_rl'` on judge tracks in `TRACKS`. In addition, `fair_bar` computes uniform tie-breaking over `n` employees rather than `n - 1` when `p.decoy == True` (where angry messages deterministically identify the decoy with `1.000000` accuracy across `960 / 960` decoy-tier episodes).
   - *Proposal for Silas:* Replace `TIERS[tier]` with `tier_params(tier)` in `canary/redteam/text_probe.py` and optionally expose `n_cand = p.n_employees - int(p.decoy)` for decoy-adjusted fair bars.
2. **`ISSUE-W1-SOLVER-IV-INGEST` (Low - `canary/solver/policy.py:210-211`):**
   - Live `Env` `interview` responses return `{"employee": emp, "topic": topic, "answer": <prose>}` without a `"signal"` key (only internal `canary/solver/_sim.py:114` emits `"signal"`). `SolverPolicy._ingest` (`canary/solver/policy.py:210-211`) evaluates `sig = str(data.get("signal", data.get("answer", ""))).lower()` and records `"evasive" in sig`. Because `0 / 16` evasive templates in `canary/text/template.py` contain the literal word `"evasive"`, live `Env` interviews ingested by `SolverPolicy` always record `evasive = False` (`0 / 3` sampled evasive answers ingested as `True`). Default `SolverPolicy(probing=False)` never calls `interview`, so default solver scores are unaffected, but `probing=True` treats evasive answers as cooperative.
   - *Proposal for Silas:* Match `data.get("answer")` against the known evasive template set (or return no interview observation when `"signal"` is absent) when `probing=True`.
3. **`ISSUE-W1-HARD-RL-DEPTS` (Medium - `canary/world.py:121`):**
   - `generate_world` computes `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]`, giving `hard_rl` `4` departments (omitting `"Research"`) instead of `5` departments like `hard` and `hard_forge`, increasing per-department concentration (`10` vs `8` employees) and slowing `SolverPolicy` accuracy (`0.675` on `hard_rl` seeds `0-39` vs `0.900` on `hard`).
   - *Proposal for Silas:* Use `TRACKS.get(tier, tier) == "hard"` in `canary/world.py:121` on future world-version bumps.
