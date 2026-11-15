# Maintainer Proposal: Harbor Sidecar `GEMINI_API_KEY` Gating and Inline Rehearsal Retry Marking

**Squad:** Integrity (`canary-integrity-w1`)
**Protected paths touched:** `0` (`harbor/` left untouched per `.github/protected-paths.txt`)

## 1. Harbor Sidecar `GEMINI_API_KEY` Gating (`docs/EXPLOITS.md` Residual Risk 1)

### Finding
`harbor/template/environment/docker-compose.yaml:33` currently passes `GEMINI_API_KEY: "$${GEMINI_API_KEY:-}"` into the `canary-server` sidecar unconditionally, even under the default `CANARY_PROVIDER=template` judge build where `GEMINI_API_KEY` is never read (documented as Residual Risk 1 in `docs/EXPLOITS.md:38`). While container isolation (`J9`) prevents the `main` agent container from reading sidecar environment variables or `/proc`, omitting `GEMINI_API_KEY` completely when `provider` is `template` removes the residual key-exposure surface if a judge exports `GEMINI_API_KEY` in the host shell.

### Non-Protected Helper and Read-Only Auditor Shipped
- `canary/redteam/harbor_sidecar_audit.py`:
  - `gemini_api_key_compose_line(provider: str) -> str`: returns `'      GEMINI_API_KEY: "${GEMINI_API_KEY:-}"'` only when `provider.strip().lower().startswith("gemini")`, and `""` otherwise (matching `LEDGER_TOKEN_LINE` in `harbor/build.py:111`).
  - Note on `string.Template`: `harbor/build.py:115` runs `string.Template(p.read_text()).substitute(subs)` once, which unescapes `$$` in the template file itself but substitutes `subs` values verbatim. Returning single-dollar `'      GEMINI_API_KEY: "${GEMINI_API_KEY:-}"'` ensures `provider="gemini"` renders byte-for-byte identically to the current `harbor/build.py` output while `provider="template"` omits `GEMINI_API_KEY` completely.
  - `audit_harbor_sidecar_key_gating(root: Path) -> dict`: read-only verification of `harbor/build.py` and `harbor/template/environment/docker-compose.yaml` plus simulated rendering under `template`, `gemini`, and `gemini:gemini-4-carbon`.
- `tests/test_harbor_sidecar_key_audit.py`: 12 keyless unit tests covering `gemini_api_key_compose_line` and `audit_harbor_sidecar_key_gating` across both unpatched and patched layouts.

### Exact Protected-Path Patch Proposal for Silas

1. `harbor/template/environment/docker-compose.yaml` (line 33):
```diff
-      GEMINI_API_KEY: "$${GEMINI_API_KEY:-}"
+${GEMINI_API_KEY_LINE}
```

2. `harbor/build.py` (`build_task` signature + `subs` + `--provider` CLI flag):
```diff
-def build_task(out: Path, tier: str, seed: int, verifier: str, world_secret: bytes, ledger_key: bytes) -> Path:
+def build_task(out: Path, tier: str, seed: int, verifier: str, world_secret: bytes, ledger_key: bytes, provider: str = "template") -> Path:
@@
         "LEDGER_TOKEN_LINE": f'      CANARY_LEDGER_TOKEN: "{token}"' if token else "",
+        "GEMINI_API_KEY_LINE": gemini_api_key_compose_line(provider),
     }
@@
     ap.add_argument("--secret-file", default=None,
                     help="world secret to bake into the sidecars (default: a fresh random secret per build)")
+    ap.add_argument("--provider", default="template",
+                    help="sidecar text provider (default: 'template'; 'gemini' forwards GEMINI_API_KEY)")
@@
-            build_task(out, t, s, a.verifier, world_secret, ledger_key)
+            build_task(out, t, s, a.verifier, world_secret, ledger_key, provider=a.provider)
```
(with `from canary.redteam.harbor_sidecar_audit import gemini_api_key_compose_line` imported in `build_task`).

## 2. Rehearsal Table Inline `--retry-include` Retry Marking (`scripts/rehearsal_table.py`)

### Enhancement Summary
`scripts/rehearsal_run.sh` launches OpenCode runs with `--max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError`. Previously, `scripts/rehearsal_table.py` iterated `sorted(job.glob("canary-*/result.json"))` alphabetically by Harbor's random 7-character trial suffix rather than chronologically, did not guard against overwriting a valid first attempt if multiple trial directories existed for one task, and did not surface Harbor 0.26 in-place job retries (`<job>/result.json` `stats.n_retries > 0` or `config.source_trial`).

Updated `scripts/rehearsal_table.py` (non-protected):
1. **Chronological ordering and non-replacement of valid attempts:** Sorts candidate trial directories within a job by `(str(r.get("started_at") or ""), rf.parent.name)` and returns tasks in sorted task-id order. If a task has multiple directories in the same job, a later directory replaces an earlier one **only** when the earlier attempt was `infra`, setting `"rerun": True`, `"first": <first_infra_reason>`, and `"inline": True` (marked with dagger `\u2020` and disclosed in the footnote). Valid first attempts are never overwritten. Also marks single-directory `config.source_trial` retries as `inline` reruns.
2. **Harbor 0.26 in-place `stats.n_retries` disclosure:** When any base job (excluding `*-infra-rerun`) records `stats.n_retries > 0` in `<job>/result.json` without per-task `inline` multi-directory markers, emits an explicit disclosure line at the bottom of the markdown output:
   `Note: Harbor inline --retry-include infra retries recorded in job result.json: <job> (n_retries=<k>).`
3. **Byte-for-byte parity on `results/harbor/rehearsal-dry`:** All 4 base jobs in `results/harbor/rehearsal-dry` have `n_retries: 0` and 1 directory per task, and all 3 reruns come from `opencode-infra-rerun`, so `scripts/rehearsal_table.py results/harbor/rehearsal-dry` remains 100% byte-for-byte identical to `results/harbor/rehearsal-dry/TABLE.md` (verified by `tests/test_rehearsal_table_reruns.py` and `tests/test_replay_tamper_guard.py`).
