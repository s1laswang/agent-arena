# Replay, DATA-RULE, and Harbor Tamper-Resistance Audit (`justSilas@58716742`)

## 1. Headline Summary

- **Target:** Committed episode logs (`data/runs/committed/`), judge table (`results/judge_episodes.jsonl`), committed Harbor runs (`results/harbor/`, including PR #43 dry judge rehearsal `results/harbor/rehearsal-dry/`), `canary.redteam.anticheat` (`justSilas@58716742`, including Panel Fix D `1bc3e281`), and standalone wrapper `canary.redteam.tamper_guard`.
- **Path isolation & Panel Fix A/D honesty:** Zero edits to `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`, `canary/redteam/anticheat.py`, or `tests/test_anticheat.py`. Consistent with Panel Fix A/D disclosures (`README.md`, `docs/DIFFICULTY.md`), Canary's `v1.4` `hard` headline gap is led by raw `65% [24%, 98%]` before luck-adjusted `72% [52%, 91%]`, dev seeds `0-29` are disclosed as a post-hoc lock (`30+` and `900000+` serve as out-of-sample checks), `hard` canary clearance (`W4`) is non-binding, and `1bc3e281`'s `ToolResult` `data.detail` field was added after the committed frontier runs. All transcript cross-checks, strict truncation/refusal checks, post-`1bc3e281` OpenCode MCP-wrapped `data.detail` replay handling, Harbor artifact checks, retired `ledger_key` re-sign notices, and `results/harbor/rehearsal-dry` verifiers live in standalone `canary/redteam/tamper_guard.py`.
- **DATA-RULE Audit (`PASS`, `0` violations):**
  - **Active committed runs:** `63` files across `53` `(tiers_version, tier, agent)` cohorts (`v1.2`: `20` cohorts / `310` episodes; `v1.3`: `16` cohorts / `279` episodes; `v1.4`: `17` cohorts / `442` episodes), totaling **`1,031` episodes** (`1,023` valid, `8` invalid in `v1.2` `opencode:openai/gpt-5.6-sol` medium/hard). `0` duplicate seeds within files or cohorts, `0` invalid score domains, `0` `V` mismatches, `0` silent timeouts or `end_reason == 'error'` marked valid.
  - **Superseded runs & judge episodes:** `13` superseded files (`58` episodes, `58` valid, `0` violations) and `results/judge_episodes.jsonl` (`840` episodes across `21` cohorts x `40` distinct judge seeds, `0` violations).
- **Live `tamper_guard` Verification (`PASS`, `0` false positives):**
  - **Committed replay:** `1,021/1,031` episodes replayed (`10` secret-keyed judge seeds skipped), **`1,021/1,021` consistent**, **`51,814` tool steps** checked (`2` OpenCode client-truncated steps and `1` OpenCode client-refused step strictly validated), `22` companion `transcripts/` directories cross-checked step-for-step, `0` mismatches.
  - **Fix-D (`1bc3e281`) OpenCode MCP-wrapped `data.detail` parity:** Verified across pre-`1bc3e281` clean/tampered, post-`1bc3e281` OpenCode MCP-wrapped clean, and post-`1bc3e281` tampered (`detail` edit, outer `ok=True` wrapper spoof, score/verdict tamper, non-OpenCode `inproc` spoof, and mixed multi-seed JSONL) cases (`22/22` tests in `tests/test_replay_tamper_guard.py`).
  - **Harbor consistency:** **`18/18` jobs** (`13` top-level + `5` nested under `results/harbor/rehearsal-dry/`) and **`80/80` trials** consistent; `57` trials under retired builds with published `ledger_key` carry explicit `retired_key_resign_notice`.
  - **Dry judge rehearsal (`results/harbor/rehearsal-dry/`):** **`PASS`** across all `5` nested jobs (`oracle`, `opencode`, `opencode-infra-rerun`, `do_nothing`, `stop_early`) and `43` trials (`43/43` HMAC verified under `1` shared retired `ledger_key`, `13/13` OpenCode trajectories checked, `10/10` task checksums identical across jobs, `3/3` `opencode-infra-rerun` tasks verified as genuine `done=False` infrastructure failures in `opencode`, `TABLE.md` byte-for-byte identical to `scripts/rehearsal_table.py`).
- **31-Class Mutation Fuzzing (`17` Replay + `14` Harbor in `31.82s`):**
  - **Replay (`R01`-`R17`):** Upstream `anticheat.replay_committed` (`58716742`) catches `6/17`; standalone `tamper_guard.replay_committed` catches **`15/17`** (`100%` of adversarial tamper classes outside the documented `1e-6` float rounding tolerance `R10`; `R11` `+1e-12` is a benign rounding probe).
  - **Harbor (`H01`-`H14`):** Upstream `anticheat` (`58716742`) catches `6/14`; standalone `tamper_guard` catches **`13/14`** (**`0` bypasses**; `H04` benign trailing whitespace accepted cleanly).

## 2. Reproduce Commands (Keyless, Zero LLM Calls)

```bash
TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_replay_tamper_guard.py tests/test_integrity_replays_and_harbor.py

TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_audit_replays_and_harbor.py

TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_audit_replays_and_harbor.py --json
```

## 3. DATA-RULE and Dry Rehearsal (`results/harbor/rehearsal-dry/`) Audit

### 3.1 Committed Runs & Judge Table (`audit_data_rules`)

| Dataset | Files / Cohorts | Episodes | Valid | Invalid | Duplicate Seeds | Rule Violations | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| Active `data/runs/committed` | `63` files / `53` cohorts | `1,031` | `1,023` | `8` | `0` | `0` | PASS |
| Superseded `data/runs/committed` | `13` files | `58` | `58` | `0` | `0` | `0` | PASS |
| `results/judge_episodes.jsonl` | `1` file / `21` cohorts | `840` | `840` | `0` | `0` | `0` | PASS |

- **Advisory note (`1` episode, valid):** `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl:12` ran `wall_s=3958.2s` (`< 10800s` Harbor cap in `harbor/template/task.toml:45`, `>= 3600s` CLI default) and finished cleanly at `end_reason='horizon'`, `final_day=21`, `rc=0`.

### 3.2 Dry Judge Rehearsal Verification (`tamper_guard.verify_rehearsal_run`)

| Check | Measured Result | Verdict |
|---|---|---|
| Nested jobs scanned (`results/harbor/rehearsal-dry/<job>`) | `5` jobs: `oracle`, `opencode`, `opencode-infra-rerun`, `do_nothing`, `stop_early` | PASS |
| Trial & job consistency (`tamper_guard.harbor_consistency`) | `43/43` trials consistent, `5/5` job summaries consistent | PASS |
| Shared retired build `ledger_key` & HMAC-SHA256 | `1` unique `ledger_key` shared across all `5` jobs; `43/43` trials `hmac_verified=True` | PASS |
| Cross-job `task_checksum` parity (`hard-900000`..`900009`) | `10` distinct tasks, `1` unique `task_checksum` per task across all jobs | PASS |
| Companion trajectories & agent logs (`trajectory.json`, `opencode.txt`, `solver.txt`) | `13/13` OpenCode trajectories + `30/30` solver/oracle logs match `ledger.json` | PASS |
| `<job>-infra-rerun` anti-cherry-pick invariant | `3/3` rerun tasks (`hard-900006`, `hard-900007`, `hard-900009`) had `done=False` + verified infra error (`ApiRateLimitError` x2, `thought_signature` x1) in `opencode` | PASS |
| `TABLE.md` exact recomputation (`scripts/rehearsal_table.py`) | `oracle=+0.467`, `opencode=+0.398`, `do_nothing=+0.000`, `stop_early=+0.000` (`table_md_matches=True`) | PASS |
| Retired `ledger_key` re-sign notice | Emitted on all `43/43` trials (`57/80` across all `results/harbor/` trials) | PASS |

## 4. Replay Checker Mutation Matrix (`R01`-`R17`) and Fix-D (`1bc3e281`) OpenCode Parity

Each mutation writes a synthetic run on scratch storage and evaluates unmodified `anticheat.replay_committed` (`58716742`), standalone `tamper_guard.replay_committed`, and `scripts/audit_submission.py`.

### 4.1 Post-`1bc3e281` OpenCode MCP-Wrapped `data.detail` Replay Handling

In `justSilas@1bc3e281` (Panel Fix D), invalid-argument calls return `ToolResult(False, {"detail": detail}, "invalid arguments")`. When OpenCode runs against `canary.mcp_server` (`is_error=True`), `steps_from_events` (`canary/agents/frontier/common.py:201`) records `{"ok": False, "error": json.dumps(payload)}`. In `canary/redteam/anticheat.py:554-565`, `rec = st.get("result")` is inspected for `"detail" in rec["data"]` *before* `_norm_result(st.get("result"))` unwraps `rec["error"]`: on a post-`1bc3e281` OpenCode MCP-wrapped step, `anticheat.replay_committed` strips `got_payload["data"]` to `{}` and then compares it against unwrapped `want` containing `data.detail`, producing a false-positive step mismatch.

In `canary/redteam/tamper_guard.py`, `want_norm = ac._norm_result(want_raw)` is unwrapped before checking `"detail"`, outer MCP wrappers are validated via `_is_valid_mcp_error_wrapper` (`set(want_raw) <= {"ok", "data", "error"}` and `want_raw.get("ok") is False`), and `base_mism_by_seed` + `base["mismatches"]` are discounted **only** when `step_bad == 0 and score_ok and acc == e.get("accused") and not tamper_probs`, `allows_opencode_quirks(e, meta)` holds, and `int(upstream_mism["step_mismatches"]) == n_oc_post_1bc_detail > 0`. Pre-`1bc3e281` episodes, tampered `data.detail` payloads, forged outer `ok=True` wrappers, score/verdict edits, non-OpenCode (`inproc`) wrapper spoofs, and tampered sibling episodes in the same JSONL all fail closed (`test_fix_d_pre_1bc3e281_and_post_1bc3e281_opencode_error_detail_replay`).

| ID | Mutation | Category | Upstream `anticheat` | `tamper_guard` | `audit_submission` | Bad Steps | Residual Bypass | Mechanism / Guard |
|---|---|---|---|---|---|---:|---|---|
| R01 | `oc_trunc_prefix_injected` | `opencode_truncation` | Caught | Caught | PASS | 1 | no | `_OC_TRUNC` anchors at `\A\s*`; non-whitespace prefix fails `_canon` |
| R02 | `oc_trunc_wrong_byte_count` | `opencode_truncation` | Caught | Caught | PASS | 1 | no | Exact byte count `len(json.dumps(got_payload).encode()) == N` fails |
| R03 | `oc_trunc_tail_same_length_edit` | `opencode_truncation` | Missed | **Caught** | PASS | 1 | no | Upstream `_OC_TRUNC` matches prefix only; `tamper_guard._OC_TRUNC_STRICT` validates `tool-output/tool_<id>` path and footer |
| R04 | `oc_trunc_forged_on_small_step` | `opencode_truncation` | Missed | **Caught** | PASS | 1 | no | `allows_opencode_quirks` + `_OC_TRUNC_STRICT` reject forged truncation on non-OpenCode / malformed markers |
| R05 | `client_refused_fake_injected` | `client_refused` | Missed | **Caught** | PASS | 1 | no | `valid_client_only_step` blocks `_OC_NO_TOOL` spoofs on non-OpenCode runs; `check_companion_transcript` cross-checks steps |
| R06 | `client_refused_disguised_mid_call` | `client_refused` | Caught | Caught | PASS | 2 | no | Skipping a mid-episode `Env` call shifts subsequent state; `valid_client_only_step` also rejects spoof |
| R07 | `client_refused_disguised_final_call` | `client_refused` | Missed | **Caught** | PASS | 1 | no | Disguising the final non-accusing step leaves `env.done=False`; caught by `valid_client_only_step` + `check_episode_tamper` |
| R08 | `flip_valid_false_wrong_accusation` | `selective_dropping` | Missed | **Caught** | WARN | 0 | no | Flipping `meta.valid=False` on a `-1.0` wrong accusation drops it in `reproduce.py`; `tamper_guard` requires `not env.done` and `acc is None` |
| R09 | `null_step_results_wiped` | `step_tamper` | Missed | **Caught** | PASS | 126 | no | Upstream `want is None or ...` accepts `result: null`; `tamper_guard` requires `want is not None` |
| R10 | `float_perturb_5e_7` | `numeric_perturbation` | Missed | Missed | PASS | 0 | **yes (`<1e-6`)** | `abs(got - score) < 1e-6` permits `+-9.99e-7` drift (`+1e-5` is caught; negligible `<0.0001%` mean effect) |
| R11 | `float_perturb_1e_12` | `numeric_perturbation` | Accepted | Accepted | PASS | 0 | no (benign) | IEEE-754 float serialization rounding probe (`+1e-12`) cleanly tolerated |
| R12 | `score_nan` | `numeric_perturbation` | Caught | Caught | FAIL | 0 | no | `NaN < 1e-6` is `False`; explicit `math.isfinite` guard in `tamper_guard` and `audit_submission` |
| R13 | `neg_zero_and_flipped_correct_flag` | `metadata_verdict_mismatch` | Missed | **Caught** | FAIL | 0 | no | `tamper_guard` checks `isinstance(e['correct'], bool)` and `e['correct'] == env.verdict()['correct']` |
| R14 | `swapped_accused_id` | `verdict_tamper` | Caught | Caught | PASS | 0 | no | `acc == e.get('accused')` catches swapped accused employee ID |
| R15 | `truncated_steps_drop_wrong_accuse` | `step_truncation` | Missed | **Caught** | PASS | 0 | no | Dropping trailing wrong `accuse` leaves `env.done=False` (`end_reason='horizon'` mismatch) and fails companion `.txt`/`.json` transcript check even if marked `invalid` |
| R16 | `forged_meta_tiers_version` | `version_spoofing` | Missed | **Caught** | PASS | 0 | no | Upstream skips unknown `tiers_version='v9.9'` as `not_replayable`; `classify_tiers_version` marks non-legacy unknown versions `replay_consistent=False` |
| R17 | `bracket_truncated_suffix_spoof` | `bracket_truncation` | Caught | Caught | PASS | 1 | no | `valid_bracket_truncated_suffix` enforces exact UTF-8 prefix match and exact remaining byte count `N` on `[... truncated N bytes ...]` |

## 5. Harbor Verifier & Trial/Job Consistency Mutation Matrix (`H01`-`H14`)

Mutations `H01`-`H05` execute both the isolated Python verifier from `harbor/template/tests/test.sh` and post-hoc Harbor consistency; `H06`-`H14` test post-hoc trial, job, rehearsal rerun, and retired-key tampering.

| ID | Mutation | Category | `test.sh` Verifier | Upstream `anticheat` | `tamper_guard` | Bypass | Mechanism / Guard |
|---|---|---|---|---|---|---|---|
| H01 | `ledger_dup_key_after_sig` | `json_duplicate_keys` | Caught | Caught | Caught | no | Trailing `"score": 1.0` after `"sig"` overwrites `body["score"]` in `json.loads`, breaking HMAC |
| H02 | `ledger_dup_key_before_score` | `json_duplicate_keys` | Missed | Missed | **Caught** | no | Prepended `"score": 1.0` before `"score": 0.0` is overwritten in `json.loads` but preserved in raw copy; `tamper_guard._load_json_no_dup_keys` rejects duplicate keys |
| H03 | `ledger_trailing_garbage_bytes` | `trailing_data` | Caught | Caught | Caught | no | `json.loads` raises `JSONDecodeError` (`Extra data`); verifier fails closed to reward `0` |
| H04 | `ledger_trailing_newlines` | `trailing_data` | Accepted | Accepted | Accepted | no (benign) | Trailing ASCII whitespace accepted cleanly under canonical JSON HMAC |
| H05 | `symlinked_reward_txt_and_json` | `symlink_hygiene` | Missed | Missed | **Caught** | no | `tamper_guard` checks `.is_symlink()` across all 13 trial artifact paths and job `result.json` |
| H06 | `mismatch_reward_txt_vs_reward_json` | `reward_disagreement` | n/a | Caught | Caught | no | Cross-checks `result.json`, `reward.txt`, `reward.json`, `test-stdout.txt`, and both ledgers |
| H07 | `missing_isolation_txt` | `isolation_report` | n/a | Missed | **Caught** | no | Upstream checks `isolation.txt` only if present; `tamper_guard` requires it on every scored non-`opencode` trial |
| H08 | `cheat_probe_with_holes` | `cheat_probe` | n/a | Caught | Caught | no | Non-empty `holes` list in `agent/cheat.json` fails `check_harbor_trial` |
| H09 | `cheat_probe_missing_cheat_json` | `cheat_probe` | n/a | Caught | Caught | no | Missing `agent/cheat.json` with intact `config.json` fails `policy == 'cheat_probe'` |
| H10 | `cheat_probe_missing_config_and_cheat_json` | `cheat_probe` | n/a | Missed | **Caught** | no | Deleting `config.json` made `_trial_policy` return `None`; `tamper_guard` requires valid JSON `config.json` |
| H11 | `tampered_job_result_mean_and_n_errors` | `job_summary` | n/a | Caught | Caught | no | `check_harbor_job` recomputes `n_trials`, `n_errors`, `mean`, and reward buckets |
| H12 | `null_trial_reward_hides_signed_wrong_accuse` | `selective_trial_dropping` | n/a | Missed | **Caught** | no | Upstream returns early when `reward is None`; `tamper_guard` inspects `ledger.json` on null-reward trials and rejects any accusation or non-zero score |
| H13 | `rehearsal_rerun_cherry_picks_valid_loss` | `rehearsal_rerun_integrity` | n/a | Missed | **Caught** | no | Forged `opencode-infra-rerun` replacing completed `-1.0` `hard-900005` passes per-job stats; `tamper_guard._check_rerun_job_pair` requires base trial `done=False` and `is_infra=True` |
| H14 | `retired_key_resigned_accused_swap` | `retired_key_resigning` | n/a | Missed | **Caught** | no | Re-signing swapped `accused` with published `ledger_key` passes HMAC; `tamper_guard` catches mismatch against `agent/solver.txt` / `agent/opencode.txt` and emits `retired_key_resign_notice` |

### Note on Published Retired `ledger_key` Threat Model
As documented in `canary/redteam/anticheat.py:894-898` and `tests/test_anticheat.py:697-704`, publishing `<job>/ledger_key` on a retired Harbor build proves that committed ledgers were produced by that build's signing key unless someone re-signs after publication. `tamper_guard` narrows any post-publication re-signing surface by cross-checking `agent/trajectory.json`, `agent/opencode.txt`, `agent/solver.txt`, `agent/oracle.txt`, `verifier/test-stdout.txt` (`done=`, `end_reason=`, `final_day=`), cross-job `task_checksum`s, and `<job>-infra-rerun` base-trial `done=False` eligibility, while attaching `retired_key_resign_notice` on all `57` published-key trials so downstream consumers never conflate retired-key HMAC verification with live secret-key non-repudiation.

## 6. Report-Only Proposals for Silas (`justSilas` Maintainer)

Per squad rules, neither `canary/redteam/anticheat.py` nor `harbor/` was modified. To wire `tamper_guard` directly into `make reproduce` / `python -m canary.redteam.anticheat` with a minimal 3-line hook:

1. **Minimal 3-line hook in `canary/redteam/anticheat.py` (`run_and_write`, lines 975-979):**
   ```python
   from . import tamper_guard as tg
   rep = tg.replay_committed() if replay else None
   hb = tg.harbor_consistency() if replay else None
   ```
   Because `tamper_guard.replay_committed` and `tamper_guard.harbor_consistency` call and wrap `anticheat.replay_committed` and `anticheat.harbor_consistency` and return the identical row schema, this preserves all 76 existing `tests/test_anticheat.py` assertions while upgrading `replay_committed` (`6/17 -> 15/17`) and `harbor_consistency` (`6/14 -> 13/14`).
2. **Optional `harbor/template/tests/test.sh` defense-in-depth (`H02`, `H05`):**
   - Pass a duplicate-key `object_pairs_hook` to `json.loads` in `test.sh:95` and write canonical re-serialized JSON rather than `shutil.copyfile(src, "/logs/verifier/ledger.json")` (`test.sh:118`) so prepended duplicate keys (`H02`) cannot survive in raw `/logs/verifier/ledger.json`.
   - Unlink `/logs/verifier/reward.txt` and `/logs/verifier/reward.json` (or open with `O_NOFOLLOW`) before writing rewards in `test.sh:41,119-120` (`H05`).
3. **Optional replay score tolerance tightening (`R10`) & 1-line Fix-D OpenCode unwrap (`anticheat.py:554,576`):**
   - Calling `rec = _norm_result(st.get("result"))` at `canary/redteam/anticheat.py:554` (before checking `"detail" in rec["data"]`) makes upstream `anticheat.replay_committed` natively accept post-`1bc3e281` OpenCode MCP-wrapped `data.detail` steps while keeping pre-`1bc3e281` normalization intact.
   - Tightening `abs(got - float(e["score"])) < 1e-6` (`canary/redteam/anticheat.py:576`) to `1e-9` eliminates the `+-5e-7` tolerance band (`R10`) while still passing all `1,021/1,021` committed episodes (`round(V, 10)`).
