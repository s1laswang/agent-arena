# Adversarial Judge 15-Minute White-Box Exploit Hunt (`v1.4` & Harbor)

## 1. Headline Summary

- **Threat Model:** An adversarial hackathon judge with full read access to `canary/`, `harbor/`, committed transcripts (`data/runs/committed/v1.4/`), and retired Harbor build artifacts (`results/harbor/`) attempts to find a reward-integrity bypass, metadata oracle, verifier forgery, PRNG/salt/MCP-memfd weakness, or selective-rerun loophole within a 15-minute white-box audit window.
- **Target & Isolation:** Evaluated on `justSilas@cf394894` (`fr8/canary/integrity@668a196b`, including `1bc3e281` Panel Fix D `ToolResult` `data.detail` on `invalid arguments`; `TIERS_VERSION = "v1.4"`). Zero edits to protected paths (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`), zero API keys, zero live LLM calls, strict single-worker execution (`--workers 1`), and all child servers/subprocesses cleaned up in `finally`.
- **Measured Verdict (`PASS`, `5/5` Vectors Held in `68.443s` under shared-node load; `31.366s` lightly loaded):**

| Vector | Attack Surface Audited | Scale (Full Mode) | Measured Result | Wall Time | Verdict |
|---|---|---|---|---:|---|
| `V1` | Transcript-mined malformed/boundary calls + 40 stateful exploit sequences (`107` encoders, `11` split encoders, `129` Sleeper rows) + `1bc3e281` `data.detail` mole parity | `21` `v1.4` JSONLs (`27,705` steps) + `800` episodes (`4,030` injected calls) + `100` paired error-detail probes across `4` tiers x `5` seeds | `0` accepted cheats, `0` `V` rises, `0` score gains over solver, `0` encoded or `data.detail` mole leaks (`40/40` held) | `50.985s` | PASS |
| `V2` | Day-0 & Day-1 roster/doc/message mutual-information & 72-cell joint metadata oracle | `300` fresh SHA-256 secrets across `JUDGE_SEEDS` `900000-900039` on `hard` (`12,000` employee rows) | All Day-0 `p > 0.026` (`MI <= 0.000816` bits); LOO joint oracle EV = `-0.9867` (`-0.9133` in-sample) vs `-0.9500` blind | `1.818s` | PASS |
| `V3` | Sandboxed Harbor `test.sh` (`python3 -I -S`) forgery, symlink, `NaN`/`Inf`/`bool`/`-0.0`, and shared-mode process-kill matrix | `2` controls (`C01`-`C02`) + `16` adversarial forgery vectors (`F01`-`F16`) | `2/2` controls exact (`0.66`, `0.0`); `16/16` forgeries failed closed (`rc=1`, `reward=0`, `F16` `child_killed=True`) | `7.554s` | PASS |
| `V4` | Judge `world_secret` `os.urandom` entropy, `SALT` absence, `Episode.reset()` decorrelation, and live child `mcp_server` memfd/HTTP probe | `50` process starts + `50` `Episode.reset()` transitions on `900000-900039` + live `canary.mcp_server` child probe | `SALT` absent; `50/50` 32B secrets & tokens; `0/50` public roster matches; mole uniformity `p=0.7944` (`z=-1.1323`); live MCP `9/9` (`child_cleaned_up=True`) | `7.290s` | PASS |
| `V5` | Dry judge rehearsal (`results/harbor/rehearsal-dry`) & `cheat-probe` HMAC, isolation, infra-rerun, and negative-control audit | `5` rehearsal jobs (`43` trials) + `cheat-probe` (`6` trials) + `2` synthetic tamper negative controls | `49/49` consistent & HMAC-verified; `36/36` `ISOLATION OK`; exact `3`-task infra rerun; `2/2` tamper controls caught | `0.787s` | PASS |

## 2. Reproduce Commands (Keyless, Zero LLM Calls)

Fast keyless pytest suite (verifies `--quick` across all 5 vectors, live child MCP server cleanup, single-worker guard, positive exploit/leak/error-detail detectors, scratch cleanup, `tokenize.COMMENT` absence, and report hygiene):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_judge_15min_whitebox_hunt.py
```

Quick 5-vector smoke hunt (`9.082s` measured lightly loaded, single process):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/judge_15min_whitebox_hunt.py --quick --workers 1 --scratch-dir /tmp/opencode/w9
```

Full 5-vector white-box hunt (`68.443s` measured on `668a196b` under shared-node load; `31.366s` lightly loaded, writing JSON summary to scratch):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/judge_15min_whitebox_hunt.py --workers 1 --scratch-dir /tmp/opencode/w9 --json-out /tmp/opencode/w9/full_summary.json
```

## 3. Vector V1: Committed Transcript Mining & 40-Sequence Stateful Exploit Matrix (`50.985s`)

### 3.1 Committed `v1.4` Transcript Rejection & Boundary Mining

`mine_v14_transcripts()` inspects all `21` committed `episodes.jsonl` logs under `data/runs/committed/v1.4/` (`6` non-reference model logs totaling `152` episodes and `14,515` tool steps, plus `15` reference policy logs totaling `290` episodes and `13,190` tool steps with `378` expected baseline probe rejections). Transcript mining inspects raw tool-call shapes and error returns only (no model score or solver-gap claims are derived from raw error counts):

| Committed `v1.4` Transcript File | Episodes | Tool Steps | Rejected Calls (`ok=False`) | Client-Truncated Outputs |
|---|---:|---:|---:|---:|
| `inproc-gemini-4-carbon/hard/episodes.jsonl` | `30` | `3,487` | `28` | `0` |
| `inproc-gemini-4-carbon/medium/episodes.jsonl` | `30` | `2,825` | `30` | `0` |
| `opencode-gemini-4-carbon/hard/episodes.jsonl` | `30` | `3,841` | `30` | `0` |
| `opencode-gemini-4-carbon/medium/episodes.jsonl` | `30` | `2,284` | `31` | `0` |
| `opencode-gemini-4-carbon-ext/hard/episodes.jsonl` | `2` | `115` | `1` | `0` |
| `opencode-gemini-3.5-flash/hard/episodes.jsonl` *(mined for call shapes only)* | `30` | `1,963` | `19` | `2` |
| **Total Non-Reference Model Transcripts (`6` files)** | **`152`** | **`14,515`** | **`139`** | **`2`** |

Across the `139` rejected calls (`31` distinct `(file, tool, error, arg_shape)` patterns) and `27` boundary-accepted calls, every observed failure and edge pattern maps cleanly into deterministic rejection or zero-leak semantics:

| Mined Pattern Category | Count | Representative Tool & Shape | `Env` / Harness Handling |
|---|---:|---|---|
| `blank_query_search_messages` | `115` | `search_messages({"query": " ", ...})` | Rejected (`ok=False`, `"invalid arguments"`), preventing full-mailbox wildcard dumps (`S01`) |
| `daily_action_limit_overrun` | `18` | `interview` / `plant_canary` / `read_access_logs` / `search_messages` after daily budget | Rejected (`"daily action limit; call advance_day"`), zero state or `V` change (`S07`) |
| `invalid_plant_canary_schema_or_variants` | `2` | `6`-variant (`gA`..`gF`) and empty-label `""` canary maps | Rejected (`"invalid arguments"`), enforcing `1 <= variants <= max_variants` and non-empty labels (`S03`, `S04`) |
| `nested_params_wrapper_smuggling` | `2` | `list_documents({"params": {"day_from": 1, "day_to": 1}})` | Rejected by strict `_extra_keys` schema check (`S05`) |
| `client_sandbox_unavailable_tool` | `1` | `bash({"command": "..."})` | Refused by client tool whitelist and unknown-tool guard (`S02`) |
| `invalid_sequential_message_id` | `1` | `read_message({"id": "1"})` | Rejected (`"unknown message id"`), no sequential index enumeration (`S06`) |
| Boundary: `future_day_to_range` / `unclosed_current_day_log_query` | `24` | `search_messages(day_to > day)` (`18`), `read_access_logs(day_to >= day)` (`6`) | Clamped to elapsed messages; `read_access_logs` on current unclosed day returns `[]` (`S08`) |
| Boundary: `singleton_canary_assignment` / `client_truncated_large_output` | `3` | `1`-recipient `plant_canary` (`1`), OpenCode `>50 KB` output (`2`) | Valid `1`-variant canary obeys daily cap; client truncation does not alter server `Env` state |

### 3.2 40-Sequence Stateful Exploit Matrix (`800` Episodes, `4,030` Injected Calls)

Each sequence `S01`-`S40` replays the real `SolverPolicy` trajectory on `(tier, seed)` across all `4` tiers (`easy`, `medium`, `hard`, `hard_forge`) and `5` seeds (`0..4`), splices adversarial tool calls mid-investigation (or at terminal/cap boundaries for `S37`-`S40`), and checks four strict invariants against the unmodified solver baseline (`easy=0.8020`, `medium=0.6440`, `hard=0.5840`, `hard_forge=0.6420`):
1. `accepted_cheats == 0` (`res.ok` is `False` on every out-of-contract call, and `len(accused_events) <= 1`).
2. `v_rises == 0` (neither true `env.V` nor `env.visible_V()` ever increases across any step or rejected cheat).
3. `score_gains_over_solver == 0` (`got_score <= solver_score` on all `800` paired runs).
4. `encoded_leak_hits == 0` and `error_detail_mole_leaks == 0` (`scan_for_secret` across serialized responses detects `0` raw or encoded mole/secret tokens across `107/107` `ENCODERS` (`82` non-Caesar base encoders + `25` Caesar shifts), `11/11` `SPLIT_ENCODERS`, and `129/129` Momin Sleeper rows; `audit_error_detail_mole_parity` runs `100` paired mole-vs-innocent rejected-call probes across all `4` tiers x `5` seeds x `5` error shapes and confirms `0` target-dependent differences in `error` or `data.detail`).

| Seq | Family | Attack Sequence Label | Runs | Calls/Run | Tier Held (`E/M/H/HF`) | Accepted Cheats | `V` Rises | Score Gains | Leak Hits | Held |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---|
| `S01` | `transcript_mined` | `blank_query_message_dump` | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S02` | `transcript_mined` | `opencode_bash_and_private_methods` | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S03` | `transcript_mined` | `flash_6variant_canary_overflow` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S04` | `transcript_mined` | `carbon_empty_variant_canary` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S05` | `transcript_mined` | `flash_nested_params_smuggling` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S06` | `transcript_mined` | `flash_numeric_message_id_probe` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S07` | `transcript_mined` | `daily_action_limit_overrun_burst` | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S08` | `transcript_mined` | `future_and_unclosed_day_boundaries` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S09`-`S17` | `encodings_corpus` | `encoded_injection_batch_01`..`09` (`9` seqs, `107/107` encoders) | `180` | `6` | `5/5` all `4` tiers | `0` | `0` | `0` | `0` | `True` |
| `S18` | `encodings_corpus` | `encoded_split_and_stego_batch_10` (`11/11` split encoders) | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S19`-`S26` | `momin_sleeper_129` | `momin_sleeper_chain_01`..`08` (`8` seqs, `129/129` corpus rows) | `160` | `6` | `5/5` all `4` tiers | `0` | `0` | `0` | `0` | `True` |
| `S27` | `restrict_canary_cycles` | `double_restrict_double_unrestrict` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S28` | `restrict_canary_cycles` | `unrestrict_unrestricted_refund_probe` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S29` | `restrict_canary_cycles` | `canary_to_restricted_employee` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S30` | `restrict_canary_cycles` | `same_day_restrict_unrestrict_zero_hold` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S31` | `restrict_canary_cycles` | `multi_employee_toggle_chain` | `20` | `6` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S32` | `restrict_canary_cycles` | `canaries_per_day_cap_boundary` | `20` | `3-4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S33` | `schema_and_canary_bounds` | `canary_per_person_and_empty` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S34` | `schema_and_canary_bounds` | `canary_title_and_label_bounds` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S35` | `schema_and_canary_bounds` | `day_type_and_range_bounds` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S36` | `schema_and_canary_bounds` | `interview_topic_and_idempotency` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S37` | `post_accuse_post_cap` | `post_accuse_mutation_burst` | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S38` | `post_accuse_post_cap` | `quadruple_accuse_chain` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S39` | `post_accuse_post_cap` | `post_horizon_accuse_mole_burst` | `20` | `4` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| `S40` | `post_accuse_post_cap` | `tool_cap_cliff_accuse_mole_burst` | `20` | `5` | `5/5, 5/5, 5/5, 5/5` | `0` | `0` | `0` | `0` | `True` |
| **Total** | **6 families (`S01`-`S40`)** | **All `40` sequences (`S09`..`S26` individually `20/20` held)** | **`800`** | **`4,030` total** | **`200/200` per tier** | **`0`** | **`0`** | **`0`** | **`0`** | **`40/40`** |

## 4. Vector V2: Day-0 & Day-1 Mutual-Information & Joint Metadata Oracle (`1.818s`)

`run_v2_day0_mi_oracle()` generates `300` fresh SHA-256 `world_secret` instances across all `40` `JUDGE_SEEDS` (`900000-900039`) on `hard` (`40` employees per world = `12,000` employee rows, uniform mole prior `1/40 = 0.025`) and tests whether any Day-0 static attribute (`list_employees`, `list_documents`, pre-day messages) or Day-1 message traffic leaks mole identity without investigative actions (note per `docs/DIFFICULTY.md` W4: `access_constraints` / `clearance` `1..3` on `hard` never binds because `canary_level = 1` and regular document recipients are unfiltered by clearance):

| Feature Family | Buckets (`k`) | `df` | Mole `chi2` | Mole `p`-value | Mole MI (bits) | Decoy `chi2` | Decoy `p`-value | Decoy MI (bits) | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `clearance` (`1, 2, 3`) | `3` | `2` | `7.1978` | `0.0268` | `0.000448` | `1.3570` | `0.5122` | `0.000083` | Near-zero MI (`<0.0005` bits); `access_constraints` / clearance on `hard` never binds (W4) |
| `dept` (`5` departments) | `5` | `4` | `2.8610` | `0.5842` | `0.000166` | `5.2203` | `0.2645` | `0.000316` | Uniform across all `5` `hard` departments |
| `role` (`15` titles) | `15` | `14` | `13.3420` | `0.5001` | `0.000816` | `11.5394` | `0.6440` | `0.000720` | Uniform across all `15` job roles |
| `doc_count` (`0..4` initial docs) | `5` | `4` | `6.4305` | `0.1677` | `0.000325` | `0.8827` | `0.9255` | `0.000048` | Mole receives initial docs at baseline rate |
| `day0_msg_count` | `1` | `1` | `0.0000` | `1.0000` | `0.000000` | `0.0000` | `1.0000` | `0.000000` | `0` messages exist before Day 1 |
| `day1_msg_kind` (`angry` / `benign` / `none`) | `3` | `2` | `8.3403` | `0.0153` | `0.000951` | `12000.0000` | `0.0000` | `0.168661` | Intentional decoy trap: `300/300` `angry_decoy_msg` are decoy (`0` moles) |
| `day1_nondecoy_msg` (`sent` vs `silent`) | `2` | `1` | `0.4398` | `0.5146` | `0.000026` | `0.0000` | `1.0000` | `0.000000` | Among the `39` non-decoys, mole chatter rate is `0.02814` vs `0.02527` |
| `joint_clearance_dept_doc` (`3x5x5` observed) | `72` | `71` | `85.0720` | `0.1217` | `0.004157` | `53.7876` | `0.9362` | `0.003375` | Full 3-way joint contingency consistent with uniform noise |

- **Joint Metadata Oracle Expected Score (`+1` right, `-1` wrong):**
  - Theoretical blind Day-0 guess (`1/40`): **`-0.95000`**
  - Theoretical post-Day-1 decoy-excluded blind guess (`1/39`): **`-0.94872`**
  - Leave-One-Out (LOO) 72-cell `(clearance, dept, doc_count)` Bayes oracle across `300` episodes: **`-0.9867`**
  - In-sample overfit 72-cell joint table (memorizing the `300` test episodes themselves): **`-0.9133`**
  - Neither marginal nor 3-way joint metadata yields positive or near-zero expected value without genuine canary/log/interview evidence.

## 5. Vector V3: Sandboxed Harbor Verifier (`test.sh`) 16-Vector Forgery Matrix (`7.554s`)

`run_v3_harbor_verifier_forgery_matrix()` executes the real `harbor/template/tests/test.sh` script (`python3 -I -S`) in isolated per-case directories on scratch (`prewrite_reward=True` pre-populating `reward.txt = "1"` and `reward.json = {"reward": 1.0}` before `test.sh` runs so any fail-open path would leave `1.0` behind):

| ID | Case Name | Class | Exit `rc` | `reward.txt` | `reward.json` | Verifier Output Prefix | Verdict |
|---|---|---|---:|---|---|---|---|
| `C01` | `valid_signed_ledger_pass_control` | Positive control | `0` | `0.66` | `{"reward": 0.66}` | `reward=0.66 source=sidecar artifact ... signature=ok done=True` | PASS |
| `C02` | `untampered_mid_episode_redacted_scores_zero` | Unaccused control | `0` | `0.0` | `{"reward": 0.0}` | `reward=0.0 source=sidecar artifact ... signature=ok done=False` | PASS |
| `F01` | `forged_score_1_post_sign` | Post-sign tamper | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F02` | `signed_nan_score` | Numeric domain | `1` | `0` | `{"reward": 0}` | `FAIL: score outside {-1, 0} U (0, 1]: nan` | Fail-closed |
| `F03` | `signed_inf_score` | Numeric domain | `1` | `0` | `{"reward": 0}` | `FAIL: score outside {-1, 0} U (0, 1]: inf` | Fail-closed |
| `F04` | `signed_bool_true_score` | Type confusion | `1` | `0` | `{"reward": 0}` | `FAIL: malformed ledger: score is bool, not a number` | Fail-closed |
| `F05` | `tampered_neg_zero_score` | Raw `-0.0` edit | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F06` | `signed_out_of_range_score` | Score `1.0001` | `1` | `0` | `{"reward": 0}` | `FAIL: score outside {-1, 0} U (0, 1]: 1.0001` | Fail-closed |
| `F07` | `symlinked_evidence_ledger_json` | Symlink attack | `1` | `0` | `{"reward": 0}` | `FAIL: no ledger evidence: .../evidence/ledger.json missing` | Fail-closed |
| `F08` | `symlinked_tests_ledger_key` | Symlink attack | `1` | `0` | `{"reward": 0}` | `FAIL: no ledger signing key (.../tests/ledger_key)` | Fail-closed |
| `F09` | `wrong_hmac_signing_key` | Forged key | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F10` | `missing_hmac_signature` | Unsigned JSON | `1` | `0` | `{"reward": 0}` | `FAIL: ledger is not signed (no sig.mac)` | Fail-closed |
| `F11` | `mid_episode_redacted_done_false_tamper` | Redacted tamper | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F12` | `tampered_V_field` | Metadata tamper | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F13` | `tampered_accused_field` | Verdict tamper | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F14` | `tampered_correct_field` | Verdict tamper | `1` | `0` | `{"reward": 0}` | `FAIL: bad ledger signature` | Fail-closed |
| `F15` | `truncated_json_payload` | Corrupted file | `1` | `0` | `{"reward": 0}` | `FAIL: malformed ledger: JSONDecodeError` | Fail-closed |
| `F16` | `planted_reward_prewrite_shared_mock_http` | Shared-mode + child kill | `1` | `0` | `{"reward": 0}` | `FAIL: ledger is not signed (no sig.mac)` (`child_killed=True`) | Fail-closed |

## 6. Vector V4: Judge World-Secret Entropy, Salt Hygiene & Live MCP Child Probe (`7.290s`)

`run_v4_world_secret_entropy()` audits `canary.world._process_secret()`, `public_world()`, `canary.mcp_server.Episode.reset()` across `50` server process starts and `50` consecutive episode resets on `JUDGE_SEEDS` (`900000-900039`), plus launches a real child `canary.mcp_server` subprocess with `0600` secret files and `CANARY_CONSUME_SECRET_FILES=1` (cleaned up in `finally`):

| Property Checked | Measured Value (`n = 50`) | Gate Threshold | Verdict |
|---|---|---|---|
| Repo answer-key salt `data/worlds/judge/SALT` committed | `False` | `False` | PASS |
| Live `os.urandom` unique 32-byte secrets generated | `50 / 50` (`32` bytes each) | `50 / 50` | PASS |
| Live roster matches against `public_world("hard", seed)` | `0 / 50` | `0` | PASS |
| Distinct `world_seed` values under per-start secrets | `50 / 50` | `50 / 50` | PASS |
| Distinct mole slots hit across `50` starts (`40` staff) | `29` (`chi2 = 31.6`, `df = 39`, `p = 0.7944`) | `p > 0.01` | PASS |
| Public-key mole coincidences (`mole == public_world.mole`) | `0 / 50` (`expected = 1.25`, `z = -1.1323`) | `z <= 2.58` | PASS |
| Cross-start adjacent mole matches & lag-1 `r` | `2 / 49` (`lag1_r = -0.1657`) | `|z| <= 2.58` | PASS |
| `Episode.reset()` unique episode tokens & adjacent matches | `50 / 50` unique tokens; `2 / 49` adjacent (`lag1_r = 0.4106`) | `50 / 50` & `|z| <= 2.58` | PASS |
| Live child `canary.mcp_server` memfd, `/proc/<pid>/environ`, `/ledger` 403/HMAC/redaction, `/admin/reset` dev-seed `400` + token rotation + `finally` cleanup | `9 / 9` checks `True` (`child_cleaned_up = True`) | `9 / 9` `True` | PASS |

## 7. Vector V5: Dry Judge Rehearsal (`results/harbor/rehearsal-dry`) & `cheat-probe` Audit (`0.787s`)

`run_v5_rehearsal_dry_audit()` verifies all `5` nested Harbor jobs in `results/harbor/rehearsal-dry/` (`43` trials) plus `results/harbor/cheat-probe/` (`6` trials), cross-checking `anticheat.check_harbor_trial`, `anticheat.check_harbor_job`, both `artifacts/ledger.json` and `verifier/ledger.json` HMAC-SHA256 signatures, container `isolation.txt` reports, `cheat.json` hole lists, `scripts/rehearsal_table.py` recomputation, and two live tamper negative controls:

| Harbor Job | Key SHA-256 Prefix | Trials | Consistent (`Trial` / `Job`) | HMAC OK (`Art` / `Ver`) | Isolation OK | Cheat Probe OK | Done | Unique Tokens | Raw Mean | Merged Valid Mean (`n=10`) |
|---|---|---:|---|---|---|---|---:|---:|---:|---:|
| `rehearsal-dry/oracle` | `e0a919a36451fdda` | `10` | `10/10` / `True` | `10/10` / `10/10` | `10/10` | n/a | `10` | `10` | `0.467` | `0.467` |
| `rehearsal-dry/opencode` | `e0a919a36451fdda` | `10` | `10/10` / `True` | `10/10` / `10/10` | `0/0` | n/a | `7` | `10` | `0.236` | `0.398` *(with `3` reruns)* |
| `rehearsal-dry/opencode-infra-rerun` | `e0a919a36451fdda` | `3` | `3/3` / `True` | `3/3` / `3/3` | `0/0` | n/a | `3` | `3` | `0.540` | *(merged above)* |
| `rehearsal-dry/do_nothing` | `e0a919a36451fdda` | `10` | `10/10` / `True` | `10/10` / `10/10` | `10/10` | n/a | `10` | `10` | `0.000` | `0.000` |
| `rehearsal-dry/stop_early` | `e0a919a36451fdda` | `10` | `10/10` / `True` | `10/10` / `10/10` | `10/10` | n/a | `10` | `10` | `0.000` | `0.000` |
| `cheat-probe` (`results/harbor/cheat-probe`) | `f713536597d716b4` | `6` | `6/6` / `True` | `6/6` / `6/6` | `6/6` | `6/6` (`0` holes) | `0` | `6` | `0.000` | `0.000` |

- **Exact Infra-Rerun Audit (`infra_rerun_exact_match = True`):** The `3` tasks in `opencode-infra-rerun` (`canary-hard-900006`, `canary-hard-900007`, `canary-hard-900009`) match 1-for-1 the `2` Harbor `ApiRateLimitError` trials (`900006`, `900007`) plus the `1` unfinished OpenCode CLI error trial (`900009`, `done=False` with `"type":"error"` in `agent/opencode.txt`). Zero completed `-1.0` wrong accusations (such as `900005` in `opencode` or `900000` in `oracle`) were rerun.
- **Negative Controls (`2/2` Caught):**
  - `forged_unscored_infra_exclusion_caught = True`: Wiping `ApiRateLimitError` in a scratch copy of `opencode/result.json` causes `check_harbor_job` to fail (`consistent = False`).
  - `forged_cheat_probe_hole_caught = True`: Injecting `"holes": ["routes.ledger_no_token"]` into a scratch copy of `cheat-probe/.../agent/cheat.json` causes `check_harbor_trial` to fail (`consistent = False`).

## 8. Report-Only Hygiene Observations (No Exploit Bypasses)

Zero reward-integrity bypasses were found across `V1`-`V5`. Two minor structural observations are recorded for maintainer awareness without modifying `canary/` or `harbor/`:

1. **`cheat-probe` Directory Placement (`V5`):** `cheat-probe` lives at sibling path `results/harbor/cheat-probe/` (`6` trials, build key prefix `f713536597d716b4`) rather than nested under `results/harbor/rehearsal-dry/` (build key prefix `e0a919a36451fdda`). Both directories pass `100%` of HMAC, trial/job consistency, and `11/11` container isolation checks (`36/36` across all reference/probe trials).
2. **CLI-Internal vs Harbor-Level Infra Errors (`V5`):** In `rehearsal-dry/opencode`, `canary-hard-900006` and `canary-hard-900007` surface as Harbor `exception_info` (`ApiRateLimitError`), whereas `canary-hard-900009` exited `0` from the container wrapper after an internal OpenCode JSON error (`done=False`, unaccused `reward=0.0`). Both `scripts/rehearsal_table.py` and `V5` verify `done=False` + error log provenance so completed episodes can never be silently replaced.
