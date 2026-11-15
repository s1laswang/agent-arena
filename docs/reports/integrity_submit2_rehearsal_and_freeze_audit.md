# Submit-2 (`aa1c679e`) & `justSilas@5f9b3297` Harbor Rehearsal and Code-Freeze Integrity Audit

## 1. Executive Summary

- **Overall Verdict:** `PASS` (`0` code-freeze byte changes, `0` HMAC or reward-parity failures, `6/6` positive tamper controls caught, `0` live API calls).
- **Audited Git Lineage:** `afterquery-final` (`1bc3e281`) -> `afterquery-submit` (`9225f2ad`) -> `afterquery-submit-2` (`aa1c679e`) -> `origin/justSilas` (`5f9b3297`), plus raw rehearsal branch `s1-rehearsal-final` (`d0ead011`).
- **Code-Freeze Invariant (`PASS`):** `0` byte changes across all `6` frozen paths (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/solver/`, `canary/mcp_server.py`, `harbor/template/`) across `afterquery-final..afterquery-submit-2`, `afterquery-submit-2..origin/justSilas`, `afterquery-final..origin/justSilas`, and `HEAD`. Frozen tier hashes remain `v1.4 = a8f99c2537c91d72` and `v1.3 = 8df71cf570bb48bc`.
- **Judge Rehearsal & `CEO.md` Append-Only Consistency (`PASS`):** `BUILD.txt` pins `afterquery-final` (`1bc3e281dbfaa494a11e783d0c98369b41b2f675`) on Harbor `0.26.0` (`[verifier] timeout_sec = 120.0`, `[agent] timeout_sec = 10800.0`). Run 1 (`+0.472`, `n=10`, `9/10` correct, `93% [20%, 371%]`), Run 2 (`+0.585`, `n=10`, `10/10` correct, `116% [78%, 363%]`), and Run 3 final (`+0.626`, `n=9` valid with `5` after `08:30` Helsinki / `06:30Z` cut-off and `1` `ApiRateLimitError` infra-excluded, `9/9` correct, paired oracle `+0.478`, `131% [86%, 590%]`, infra-as-0 `+0.563`) are consistent across `TABLE.md`, `README.md`, `docs/SUBMISSION.md`, `docs/reports/gap.md`, `docs/reports/CEO.md` (`5f9b3297`, strictly append-only `+4` lines), and all `60/60` HMAC-verified raw trials on `s1-rehearsal-final` (`d0ead011`).
- **Harbor Published-Key HMAC, 5-Way Parity & Negative Control (`PASS`):** `18/18` jobs and `80/80` trials under `results/harbor/` pass `tamper_guard.harbor_consistency`. Across all `8` published-key jobs (`57` trials, including `43` in `results/harbor/rehearsal-dry/`), `57/57` verify HMAC-SHA256 and `57/57` satisfy exact `result.json == verifier/reward.txt == verifier/reward.json == verifier/ledger.json == artifacts/ledger.json` parity. Negative control `results/harbor_negative/c1-tamper` (`score=1.0` forged over `V=0.5`) fails closed at `reward=0.0` (`FAIL: bad ledger signature`) with `verifier/ledger.json` uncopied.

## 2. Keyless Reproduce Commands

```bash
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_submit2_rehearsal_and_freeze_audit.py --check-report docs/reports/integrity_submit2_rehearsal_and_freeze_audit.md
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -q tests/test_integrity_submit2_rehearsal_and_freeze_audit.py
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_submission.py
```

## 3. Code-Freeze Invariant (`1bc3e281` -> `aa1c679e` -> `5f9b3297`)

| Comparison Range | `rev_a` | `rev_b` | Frozen Path Changes | Frozen Byte Diff | Total Changed Files | Verdict |
|---|---|---|---:|---:|---:|---|
| `afterquery-final..afterquery-submit-2` | `1bc3e281` | `aa1c679e` | `0` | `0` | `58` | `PASS` |
| `afterquery-submit-2..justSilas` | `aa1c679e` | `5f9b3297` | `0` | `0` | `1` | `PASS` |
| `afterquery-final..justSilas` | `1bc3e281` | `5f9b3297` | `0` | `0` | `58` | `PASS` |

| Frozen Path | Git Object SHA (`1bc3e281` / `aa1c679e` / `5f9b3297`) | Identical Across All Refs |
|---|---|---|
| `canary/env.py` | `24ffbc5429bfca64f136758295949d14828cce11` | `True` |
| `canary/rules.py` | `8ae89071170cc3bb81b01b41cac04f2d5e7451e6` | `True` |
| `canary/world.py` | `d5c352d1a241f85cb4a7ce3129f8527ac622725a` | `True` |
| `canary/solver/` | `98483eebc3f3c8b808f64af7c940355fe3dcb85c` | `True` |
| `canary/mcp_server.py` | `6a9f1f6743a6904ca4efb2b67ecf2aaaff733019` | `True` |
| `harbor/template/` | `06ee0cddfeb0d2508eb7e7b88665e77734fe3c0e` | `True` |

- **`afterquery-submit-2` (`aa1c679e`) diff scope vs `afterquery-submit` (`9225f2ad`):** `4` files (`README.md, docs/SUBMISSION.md, docs/reports/gap.md, results/harbor/rehearsal/TABLE.md`).
- **`origin/justSilas` (`5f9b3297`) diff scope vs `afterquery-submit-2` (`aa1c679e`):** `docs/reports/CEO.md` (`append_only=True`, `+4` lines, `0` deletions).

## 4. Judge Rehearsal (`afterquery-final` / `aa1c679e` / `d0ead011`) and Dry Rehearsal Audit

### 4.1 Final Judge Rehearsal (`s1-rehearsal-final` `d0ead011` + `aa1c679e` Docs)

| Run | Valid Trials | Infra Excluded | Correct / Accused | Mean | Paired Oracle | Run / Oracle [95% Bootstrap CI] | Diff | Mean (Infra as 0) |
|---|---:|---:|---|---:|---:|---|---:|---:|
| `oracle` | `10` | `0` | `9 / 10` | `+0.506` | `n/a` | `100%` | `+0.000` | `+0.506` |
| `opencode-1` | `10` | `0` | `9 / 10` | `+0.472` | `+0.506` | `93% [20%, 371%]` | `-0.034` | `+0.472` |
| `opencode-2` | `10` | `0` | `10 / 10` | `+0.585` | `+0.506` | `116% [78%, 363%]` | `+0.079` | `+0.585` |
| `opencode-3` | `9` | `1` | `9 / 9` | `+0.626` | `+0.478` | `131% [86%, 590%]` | `+0.148` | `+0.563` |
| `do_nothing` | `10` | `0` | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` | `-0.506` | `+0.000` |
| `stop_early` | `10` | `0` | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` | `-0.506` | `+0.000` |

- **Raw Trial Cryptographic & Parity Check (`d0ead011`):** `6` jobs, `60` trials, `1` shared `ledger_key`, `60/60` HMAC-SHA256 verified, `60/60` exact 5-way `result.json == reward.txt == reward.json == verifier/ledger.json == artifacts/ledger.json` parity, `10/10` task checksums identical across all `6` jobs.
- **Cut-Off & Accusation Tally (`d0ead011`):** `opencode-3` completed `5` trials on or before `06:30:00Z` (`08:30` Helsinki: `4` valid + `1` `ApiRateLimitError` on `hard-900002`) and `5` valid trials between `06:31:30Z` and `07:23:17Z`. Across all `3` runs, `28/29` valid Gemini accusations were correct.
- **08:52 Snapshot Table Parity (`results/harbor/rehearsal/TABLE.md`):** Snapshot table rows independently recompute to `opencode-1 = 93% [20%, 371%]` (`+0.472`), `opencode-2 = 116% [78%, 363%]` (`+0.585`), `opencode-3 (n=7) = 153% [89%, 411%]` (`+0.656` vs paired oracle `+0.429`), `do_nothing = 0%`, `stop_early = 0%`.

### 4.2 Dry Rehearsal (`results/harbor/rehearsal-dry/`)

- **Jobs & Trials:** `5` jobs (`oracle`, `opencode`, `opencode-infra-rerun`, `do_nothing`, `stop_early`), `43/43` trials consistent, `43/43` HMAC verified under `1` shared retired `ledger_key`, `13/13` OpenCode trajectories matched, `table_md_matches=True` (`oracle=+0.467`, `opencode=+0.398` = `85% [11%, 355%]`, `do_nothing=+0.000`, `stop_early=+0.000`).

## 5. Signed Harbor Trials (`results/harbor/`) and Negative Control (`c1-tamper`)

| Published-Key Harbor Job | Trials | `ledger_key` SHA-256 Prefix | HMAC-SHA256 Verified | 5-Way Reward/Ledger Parity | Verdict |
|---|---:|---|---:|---:|---|
| `results/harbor/cheat-probe` | `6` | `f713536597d716b4` | `6/6` | `6/6` | `PASS` |
| `results/harbor/rehearsal-dry/do_nothing` | `10` | `e0a919a36451fdda` | `10/10` | `10/10` | `PASS` |
| `results/harbor/rehearsal-dry/opencode` | `10` | `e0a919a36451fdda` | `10/10` | `10/10` | `PASS` |
| `results/harbor/rehearsal-dry/opencode-infra-rerun` | `3` | `e0a919a36451fdda` | `3/3` | `3/3` | `PASS` |
| `results/harbor/rehearsal-dry/oracle` | `10` | `e0a919a36451fdda` | `10/10` | `10/10` | `PASS` |
| `results/harbor/rehearsal-dry/stop_early` | `10` | `e0a919a36451fdda` | `10/10` | `10/10` | `PASS` |
| `results/harbor/signed-cheat` | `6` | `f713536597d716b4` | `6/6` | `6/6` | `PASS` |
| `results/harbor/signed-stop_early` | `2` | `e6dfec5f547368bd` | `2/2` | `2/2` | `PASS` |

- **All Committed `results/harbor/` Runs:** `18/18` jobs and `80/80` trials consistent (`57` published-key signed trials with 5-way parity + `3` C1 signed trials with `signature=ok` and 4-way parity + `20` pre-C1 demo trials with 4-way parity).
- **Negative Control `results/harbor_negative/c1-tamper` (`canary-hard-900000__GZn8oUh`):** `artifacts/ledger.json` carries forged `score=1.0` over `V=0.5`; verifier logged `FAIL: bad ledger signature: the ledger was not written by this task's canary-server, or was edited`, failed closed with `result.json` `reward=0.0` and `verifier/reward.txt='0'`, and left `verifier/ledger.json` absent (`False`). Re-executing frozen `harbor/template/tests/test.sh` against the tampered ledger in `/tmp/opencode` exited `rc=1` with `reward.json={"reward": 0}`.

## 6. Synthetic Positive Tamper Controls (`/tmp/opencode`, Cleaned Up)

| Control ID | Synthetic Mutation | Caught |
|---|---|---|
| `C01` | `frozen_path_byte_edit_caught` | `True` |
| `C02` | `ceo_non_append_rewrite_caught` | `True` |
| `C03` | `published_key_hmac_forgery_caught` | `True` |
| `C04` | `reward_txt_json_ledger_desync_caught` | `True` |
| `C05` | `negative_control_fail_open_caught` | `True` |
| `C06` | `stale_153_snapshot_claim_in_docs_caught` | `True` |

## 7. Structured Report-Only Issues (Zero Protected Paths, Zero Edits to Silas Docs)

| Issue ID | Severity | Area | Paths | Finding |
|---|---|---|---|---|
| `ISSUE-W8-S2-1` | `low` | `rehearsal_table_snapshot_body` | `results/harbor/rehearsal/TABLE.md` | TABLE.md prepends an accurate 09:30 correction note with final Run 3 numbers (9 valid, +0.626, 131% [86%, 590%], s1-rehearsal-final d0ead011), while the markdown table body below retains the 08:52 snapshot (opencode-3 n=7, +0.656, 153% [89%, 411%]) and raw trial dirs live on d0ead011. |
| `ISSUE-W8-S2-2` | `info` | `rehearsal_shell_usage_denominator` | `README.md`, `docs/reports/gap.md` | aa1c679e updated valid Gemini accusation accuracy from 26/27 to 28/29, but retained the 08:52 snapshot shell-usage parenthetical ('20 of 28 trials'); on s1-rehearsal-final (d0ead011), bash was called in 22 of 30 total Gemini trajectories (21 of 29 valid). |
| `ISSUE-W8-S2-3` | `info` | `submit2_tag_and_ceo_log_sync` | `docs/reports/CEO.md`, `docs/SUBMISSION.md` | Commit 5f9b3297 (append-only 09:35 CEO.md correction) sits 1 commit ahead of tag afterquery-submit-2 (aa1c679e), and docs/SUBMISSION.md line 8 names afterquery-final and afterquery-submit without listing afterquery-submit-2. |
| `ISSUE-W8-S2-4` | `info` | `rehearsal_run3_unexecuted_infra_rerun` | `results/harbor/rehearsal/README.md` | In s1-rehearsal-final (d0ead011), opencode-3 hard-900002 failed with ApiRateLimitError (done=False) after inline retries and did not receive a <job>-infra-rerun job because Run 3 finished at 07:23:17Z (09:23 Helsinki); disclosed in rehearsal README and reported alongside infra-as-0 mean (+0.563). |
| `ISSUE-W8-S2-5` | `info` | `harbor_verifier_generation_heterogeneity` | `results/harbor/` | All 57/57 published-key Harbor trials include verifier/reward.json (5-way parity + HMAC), whereas 3 earlier C1 signed trials (c1-*) and 20 pre-C1 demo trials predate reward.json output (4-way parity holds). |
| `ISSUE-W8-S2-6` | `info` | `published_retired_key_non_repudiation_scope` | `results/harbor/rehearsal-dry/`, `results/harbor/` | Publishing retired <job>/ledger_key files enables third-party HMAC verification against un-re-signed edits, while post-publication re-signing is bounded by agent trajectory/log cross-checks and cross-job task_checksum parity. |
