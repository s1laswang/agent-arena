# Research Squad Lane (`origin/fr8/afterquery/research`) PR Packaging, Citation, Link, and Assembly Audit

## 1. Branch Inventory, Part Coverage (`00..10`), and `verify_pr_branch.py` Gate Matrix

### 1.1 Audited Refs and Verification Command

`origin/fr8/afterquery/research` (`4bcfd3e9604c6c01ace7357c2b28181a066dc932`) and all nine worker branches (`origin/fr8/afterquery/afterquery-research-w1..w9`) were fetched and audited against `origin/justSilas` (`7232f8008423c8a52f3307946fd09ff466e4eaa1` at dispatch, which advanced during the audit window to `bf70e7440b4c56d78892b8ad3a2741bf99c187c5` via PR #18 `game/{app.js,index.html,style.css}`) and `origin/justSilas-v15` (`de9cc50ea46420d507010b02f3562e370ca2b34b`) using:

```bash
PY="/home/silas/agent-arena-data/fleet-shared-venv/bin/python"
PYTHONPATH=. TMPDIR=/tmp/opencode $PY scripts/verify_pr_branch.py \
  --base 7232f800 --branch origin/fr8/afterquery/research --require-ff-base
PYTHONPATH=. TMPDIR=/tmp/opencode $PY scripts/verify_pr_branch.py \
  --base origin/justSilas --branch origin/fr8/afterquery/research --require-ff-base
```

Exact CLI output against `7232f800` (`10/10` PASS; against live tip `bf70e744`, default mode is `10/10` PASS with `0` conflicts and `--require-ff-base` is `9/10` pending merge of `bf70e744`):

```text
PR Branch Verification: 7232f800 (7232f800) -> origin/fr8/afterquery/research (4bcfd3e9)
Changed files: 9
  [PASS] merge_conflict: clean merge-tree (ff-base 7232f800)
  [PASS] protected_core: 0 protected core files touched
  [PASS] finalize_reserved_path: 0 reserved finalize paths touched
  [PASS] python_comments: 0 .py file(s) checked, 0 comment violation(s)
  [PASS] unicode_dashes: 9 file(s) checked, 0 unicode dash line(s)
  [PASS] co_authored_by: 22 commit(s) checked, 0 Co-Authored-By trailer(s)
  [PASS] secret_leak: 9 file(s) checked, 0 secret leak(s)
  [PASS] timeout_episode: 0 episode file(s) checked, 0 episode violation(s)
  [PASS] orphan_transcript: 0 shard manifest(s) checked, 0 manifest/transcript issue(s)
  [PASS] replay_mismatch: 0 v1.4 episode(s) replayed, 0 mismatch(es)
OVERALL: PASS (10/10 gates passed)
```

### 1.2 10-Branch `verify_pr_branch.py` Matrix (`research` and `research-w1..w9` vs `justSilas` `7232f800` / `bf70e744`)

| Branch (`origin/fr8/afterquery/...`) | Tip SHA | Merge-Base vs `justSilas` | `ff_base` vs `7232f800` (`bf70e744`) | Merged into `research` (`4bcfd3e9`) | `Changed files` (`verify_pr_branch`) | Default Gates | `--require-ff-base` (`7232f800` / `bf70e744`) | Notes |
|---|---|---|---|---|---:|---|---|---|
| `research` | `4bcfd3e9` | `7232f800` | `True` (`False`) | `True` (tip) | `9` (`docs/research/_parts/*.md`) | `10/10` PASS | **`10/10` PASS** / `9/10` | `0` overlap with `bf70e744` (`game/*`); `22` commits checked |
| `afterquery-research-w1` | `ee026519` | `b4557e00` | `False` (`False`) | `True` (`dcfdb0e2`) | `2` (`00_*`, `01_*`) | `10/10` PASS | `9/10` / `9/10` | Both blobs identical on `research` |
| `afterquery-research-w2` | `4ba0efd4` | `b4557e00` | `False` (`False`) | `True` (`ebb41b44`) | `2` (`02_*`, `10_*`) | `10/10` PASS | `9/10` / `9/10` | Both blobs identical on `research` |
| `afterquery-research-w3` | `5604bf65` | `7232f800` | `True` (`False`) | `True` (`4bcfd3e9`) | `1` (`03b_*`) | `10/10` PASS | **`10/10` PASS** / `9/10` | Blob identical on `research` |
| `afterquery-research-w4` | `ad67d8c4` | `b4557e00` | `False` (`False`) | `True` (`463aee81`) | `1` (`04_*`) | `10/10` PASS | `9/10` / `9/10` | Blob identical on `research` |
| `afterquery-research-w5` | `0696df8e` | `b4557e00` | `False` (`False`) | `True` (`44cce77c`) | `1` (`05_*`) | `10/10` PASS | `9/10` / `9/10` | Blob identical on `research` |
| `afterquery-research-w6` | `c01f371a` | `f19cc71f` | `False` (`False`) | `True` (via `justSilas` sync) | `79` (stale pre-sync tree) | `7/10` FAIL | `7/10` / `7/10` | Untouched initial worker base; `0` research commits (`merge_conflict` on `canary/mcp_server.py`, `97` `.py` comments, `3` en-dashes in `scripts/paired_gemini.py`) |
| `afterquery-research-w7` | `9ad3123e` | `b4557e00` | `False` (`False`) | `True` (`f5381e0c`) | `1` (`07_*`) | `10/10` PASS | `9/10` / `9/10` | Blob identical on `research` |
| `afterquery-research-w8` | `bf390ada` | `b4557e00` | `False` (`False`) | `True` (`908458d2`) | `0` | `10/10` PASS | `9/10` / `9/10` | Parked at pre-`7232f800` sync commit; `0` research commits |
| `afterquery-research-w9` | `bc3b411e` | `b4557e00` | `False` (`False`) | `True` (`ee3fd903`) | `1` (`09_*`) | `10/10` PASS | `9/10` / `9/10` | Blob identical on `research` |

- **Zero unmerged worker blobs on `origin`:** Every `docs/research/_parts/*.md` file across `w1..w9` has the exact same git blob SHA as `origin/fr8/afterquery/research` (`4bcfd3e9`). No in-flight commits exist on `origin/fr8/afterquery/afterquery-research-w*` ahead of `4bcfd3e9`.
- **`_audits/` remote status:** `0` files under `docs/research/_audits/` are committed on `origin/fr8/afterquery/research` or any `origin/fr8/afterquery/afterquery-research-w1..w9` ref (`git ls-tree -r` shows only the `9` files under `docs/research/_parts/`).

### 1.3 Part-by-Part Status (`00..10`)

| Part Slot | Expected Section & Topic (from `00` and `10` Matrix) | Committed Path on `research` (`4bcfd3e9`) | Blob SHA | Author Branch & Commit | Merge Commit on `research` | Status |
|---|---|---|---|---|---|---|
| `00` | Title, Provenance, Epistemic Protocol, Executive Summary | `docs/research/_parts/00_header_and_exec_summary.md` | `6c73519c` | `research-w1` (`ee026519`) | `dcfdb0e2` | **MERGED** |
| `01` | Sec. 1: Rumour Psychology, Serial Distortion & Attribution Biases | `docs/research/_parts/01_rumours_attribution.md` | `b350bf73` | `research-w1` (`2e91b936`) | `dcfdb0e2` | **MERGED** |
| `02` | Sec. 2: Interpersonal Grudges, Subgroup Faultlines & Conflict | `docs/research/_parts/02_grudges_conflict.md` | `9c11bb42` | `research-w2` (`da1a2360`) | `ebb41b44` | **MERGED** |
| `03` / `03b` | Sec. 3: Authority Bias, Implicit Voice Theories & Silence | `docs/research/_parts/03b_voice_whistleblowing_authority.md` | `2f0adf29` | `research-w3` (`5604bf65`) | `4bcfd3e9` | **MERGED** (no `03_`/`03a_` file; `03b` has H2 `## 3.` + `3.1..3.4`) |
| `04` | Sec. 4: Miscommunication, Delayed Feedback & Coordination Failure | `docs/research/_parts/04_miscommunication_coordination.md` | `ba479c29` | `research-w4` (`ad67d8c4`) | `463aee81` | **MERGED** |
| `05` | Sec. 5: Overconfidence, Base-Rate Neglect, Escalation & Stopping | `docs/research/_parts/05_overconfidence_commitment.md` | `1555bc1b` | `research-w5` (`0696df8e`) | `44cce77c` | **MERGED** |
| `06` | Sec. 6: Tech Collapses -- Nokia & Yahoo (Vuori & Huy 2016; strategic drift) | `--` (none) | `--` | `research-w6` at `c01f371a` (`0` commits) | `--` | **MISSING** |
| `07` | Sec. 7: Corporate Governance, Whistleblower Suppression & Probes | `docs/research/_parts/07_corporate_governance_failures.md` | `47a9eb1f` | `research-w7` (`9ad3123e`) | `f5381e0c` | **MERGED** |
| `08` | Sec. 8: Insider Espionage & Framing Forensics (CERT, Hanssen/Snowden/Tesla/Winner) | `--` (none) | `--` | `research-w8` at `bf390ada` (`0` commits) | `--` | **MISSING** |
| `09` | Sec. 9: Canary Traps, Traitor Tracing & Synthetic Benchmarks | `docs/research/_parts/09_canary_traps_watermarking.md` | `924202fb` | `research-w9` (`bc3b411e`) | `ee3fd903` | **MERGED** |
| `10` | Sec. 10: Architectural Synthesis & Master Literature-to-Code Matrix | `docs/research/_parts/10_synthesis_and_canary_mapping.md` | `90696372` | `research-w2` (`4ba0efd4`) | `ebb41b44` | **MERGED** |

---

## 2. Unicode Dashes, Non-ASCII Characters, Secrets, and Markdown Link Scan

All `9` markdown files (`851` lines, `26,108` words, `206,386` bytes) on `origin/fr8/afterquery/research` (`4bcfd3e9`) were scanned programmatically:

| Check | Scope | Result | Verdict |
|---|---|---:|---|
| Unicode em dash (`U+2014`) | All `9` `_parts/*.md` files (`851` lines) | `0` lines | **PASS** |
| Unicode en dash (`U+2013`) | All `9` `_parts/*.md` files (`851` lines) | `0` lines | **PASS** |
| Other non-ASCII code points (`> U+007F`) | All `9` `_parts/*.md` files (`851` lines) | `7` lines (all in `05_*`) | **INFO** (`0` in `8/9` files) |
| Secret patterns & forbidden paths | `AIza*`, `sk-*`, `ghp_*`, `AKIA*`, `*_API_KEY=`, `.env*`, `SALT` | `0` matches | **PASS** |
| Markdown links `[text](target)` | All `9` `_parts/*.md` files (`155` links, `151` unique URLs) | `155 / 155` valid `https://` syntax | **PASS** |
| Relative file links / `#anchor` links | All `9` `_parts/*.md` files | `0` relative, `0` `#anchor` (`0` broken) | **PASS** |
| Unresolved HTML template placeholders | `<!-- ... -->` comments across all `9` files | `1` (`00_header_and_exec_summary.md:74`) | **FIX IN ASSEMBLY** |

### Supporting Details

- **Non-ASCII typography note (`05_overconfidence_commitment.md` only):** `8` of the `9` files are pure 7-bit ASCII. `05_overconfidence_commitment.md` contains `U+2018`/`U+2019`/`U+201C`/`U+201D` curly quotation marks inside verbatim academic blockquotes on lines `23, 50, 52, 76` and `U+00B1` (`+/-`) inside inline code spans on lines `122, 123, 124`. None violate `verify_pr_branch.py`, though replacing `U+00B1` with `+/-` on lines `122-124` aligns code spans with Parts `00, 04, 09, 10`.
- **Markdown link breakdown (`155` links total, `100%` `https://`):** `7` in `00_*`, `14` in `01_*`, `20` in `02_*`, `23` in `03b_*`, `26` in `04_*`, `18` in `05_*`, `15` in `07_*`, `23` in `09_*`, and `9` in `10_*`. Every link has a non-empty label, valid `https` scheme and hostname, zero whitespace in URL targets, and URL-encoded parentheses (`%28`/`%29`) wherever target URLs contain parentheses (`01_rumours_attribution.md:20`, `02_grudges_conflict.md:13`). No repo paths are formatted as relative `[text](path)` links, preventing broken-link failures for cross-branch references.
- **Template placeholder (`00_header_and_exec_summary.md:74`):** Line `74` ends with `<!-- TOC_PLACEHOLDER -->`. During assembly, either populate this with verified GitHub-flavored Markdown `#anchor` links matching each final `##` heading or delete the HTML comment.

---

## 3. Repo Path, Python Symbol, Branch/Commit, and Quantitative Citation Audit

### 3.1 Repository File and Directory Paths Cited Across Parts `00..10`

All `45` distinct repository file, directory, glob, and runtime paths cited in prose or inline code spans were checked against the git trees of `origin/justSilas` (`7232f800`), `origin/justSilas-v15` (`de9cc50e`), and `origin/justSilas-grok-research` (`bd8cd776`):

| Category | Count | Paths & Exact Locations in `_parts/` | `justSilas` (`7232f800`) | `justSilas-v15` (`de9cc50e`) | Action Required |
|---|---:|---|---|---|---|
| Core Canary code, docs, scripts, tests, and v1.4/Harbor results | `37` | `canary/agents/{frontier/common.py,llm_policy.py}`, `canary/analysis/{accuse.py,tags.py}`, `canary/baselines.py`, `canary/env.py`, `canary/forge/{fitness.py,rl_mole.py}`, `canary/mcp_server.py`, `canary/mole/dsl.py`, `canary/redteam/anticheat.py`, `canary/rules.py`, `canary/solver/{ablation.py,belief.py,policy.py}`, `canary/text/`, `canary/text/template.py`, `canary/world.py`, `docs/{CONTRACT.md,EXPLOITS.md,IDEAS.md,PLAN-95.md,PLAN.md}`, `docs/reports/{CEO.md,env.md,gap.md}`, `harbor/`, `harbor/template/environment/canary-server/Dockerfile`, `harbor/template/tests/test.sh`, `results/fresh_table_v1.4.md`, `results/harbor/c1-*` (`c1-cheat`, `c1-do_nothing`, `c1-oracle`), `results/harbor_negative/c1-tamper/`, `results/skill_ladder_v1.4.md`, `scripts/{gemini_runner.py,regret_report.py}`, `tests/test_env_frozen.py` | **Present (`37/37`)** | `29/37` (`8` landed on `justSilas` after `v15` branched) | None (exact match on target base `justSilas`) |
| `justSilas-v15`-only candidate table | `1` | `results/fresh_table_v1.5-candidate.md` (`01:113`, `02:71`, `04:75`, `10:13, 21, 22`) | Absent | **Present (`1/1`)** | Keep as non-link code span qualified with `justSilas-v15` (`de9cc50e`) |
| `justSilas-grok-research`-only doc (**unqualified branch**) | `1` | `docs/research-grounding.md` (`00:10`, cited with commit `bd8cd776`) | **Absent** | **Absent** | **Qualify branch:** exists only on `origin/justSilas-grok-research` (`bd8cd776`), not on `justSilas` |
| Missing `tests/` prefix + unimplemented v0 test name | `1` | `test_integrity.py::test_canary_edges` (`09:125`) | **Absent** (`tests/test_integrity.py` exists, `test_canary_edges` does not) | **Absent** | **Fix citation:** `test_canary_edges` is a planned v0 placeholder in `docs/EXPLOITS.md:63`; real tests in `tests/test_integrity.py` are `test_canary_too_many_variants` (`L158`) and `test_canary_unique_copy_per_person_rejected` (`L168`) |
| Intentional gitignored secret & Harbor container runtime paths | `5` | `data/worlds/judge/SALT`, `episode.json`, `canary-server/ledger_key`, `tests/ledger_key`, `/logs/verifier/reward.txt` (`07:125-126`) | Untracked by design (`harbor/build.py` + `.gitignore`) | Untracked by design | None (`tests/test_integrity.py::test_salt_never_tracked` enforces `SALT` stays untracked) |

### 3.2 Python Symbols, Classes, Functions, and Config Keys (`126` Symbols Checked)

Programmatic source verification across `126` cited Python identifiers, methods, tier fields, baseline names, ablation rungs, and CLI flags shows:

1. **Present on `origin/justSilas` (`7232f800`) (`105 / 126` symbols):**
   - `91` symbols exist on both `origin/justSilas` and `origin/justSilas-v15` (all `v1.4` `TierParams` fields, `KNOWN_V_MODE`, `TIERS_VERSION`, `Env` tools and methods `visible_V`, `verdict`, `instruction`, `_cost`, `_facts`, `_t_interview`, `_t_plant_canary`, `PublicDayFacts`, `INVESTIGATIVE_TOOLS`, `canary_level`, `generate_world`, `ROLES`, `by_dept`, `min_clearance`, `TemplateProvider`, `_ANGRY`, `MoleStrategy`, `MoleView`, `FRAME_SELECTORS`, `recent_low_recipient_docs`, `low_recipient_threshold`, `SolverPolicy` methods `accuse_value`, `expected_true_V`, `plan_canaries`, `partition_balanced`, `partition_search`, `canary_mi`, `joint_mi`, `_candidates`, `_cweight`, `_pending_canaries`, `behaviour_logliks`, `leak_loglik`, `FEASIBLE_SOLVER_RATIO`, `FEASIBLE_SOLVER_ACC`, `min_solver_acc`, all `v1.4` baselines, and `premature_accusation`, `ignored_delay`, `budget_waste`).
   - `14` symbols exist on `origin/justSilas` (`7232f800`) and not on `origin/justSilas-v15` (`de9cc50e`) because they merged into `justSilas` after `v15` branched: `hard_rl`, `RLMole` (`canary/forge/rl_mole.py`), the `7` skill-ladder ablation rungs in `canary/solver/ablation.py` (`accuse_last`, `accuse_p50`, `no_delay`, `no_careful`, `single_canary`, `no_decoy`, `no_framing`), `sign_ledger` (`canary/mcp_server.py`), `canary_per_person` (`canary/redteam/anticheat.py`), and `ev_delay` (`canary/agents/llm_policy.py`, `canary/agents/frontier/common.py`, `scripts/gemini_runner.py`).
2. **Present ONLY on `origin/justSilas-v15` (`de9cc50e`) (`17 / 126` symbols):**
   - `canary/rules.py`: `TIERS_V15`, `rumour_rate`, `rumour_frame_share`, `grudge_pairs`, `grudge_rate`, `authority_day`, `p_misforward`.
   - `canary/env.py`: `AUTHORITY_ROLES`, `_grudges`, `_misforward`, `_social_instruction`, `forwarded_to`.
   - `canary/mole/dsl.py`: `RUMOUR_SELECTORS`, `seed_rumour`.
   - `canary/baselines.py`: `RumourFollower`, `rumour_follower`.
   - `canary/solver/belief.py`: `social_loglik`.
   - Every occurrence of these `17` symbols across Parts `00`, `01`, `02`, `03b`, `04`, `05`, `07`, and `10` is explicitly scoped to `justSilas-v15` (`de9cc50e`) / `v1.5-candidate`.
3. **Minor symbol/module discrepancies (`4` items out of `126` checks):**
   - `GeminiWorldText` (`10_synthesis_and_canary_mapping.md:40`, checked under `canary/text/`): `class GeminiWorldText` is defined in `canary/agents/world_builder.py:188`, whereas `canary/text/gemini.py:135` defines wrapper `class GeminiWorldTextProvider` (`2` path-scoped checks in `canary/text/` missed, symbol exists in `canary/agents/world_builder.py` on both `justSilas` and `justSilas-v15`).
   - `CANARY_*_FILE` (`07_corporate_governance_failures.md:125`): wildcard shorthand for `CANARY_EPISODE_FILE`, `CANARY_WORLD_SECRET_FILE`, `CANARY_LEDGER_TOKEN_FILE`, `CANARY_ADMIN_TOKEN_FILE`, and `CANARY_LEDGER_KEY_FILE` in `canary/mcp_server.py:18-24` (`all 5` concrete variables verified on `justSilas`).
   - `test_canary_edges` (`09_canary_traps_watermarking.md:125`): missing pytest function (`see Section 3.1 above`).

### 3.3 Commit Hashes, Branch References, Line Citations, and Benchmark Numbers

| Cited Ref / Hash | Cited In | Resolved Git Object / Source | Ancestor of `justSilas` (`7232f800` / `bf70e744`) | Ancestor of `justSilas-v15` (`de9cc50e`) | Verification Note |
|---|---|---|---|---|---|
| `origin/justSilas` (`b4557e00`) | `00:4,44,59,70`, `01:106`, `04:65`, `05:102` | Commit `b4557e00` (`Merge PR #7: hard-only judge set...`) | **Yes** (`7232f800~1` / `bf70e744~2`) | No | Valid; `justSilas` advanced only in `docs/agents/SESSIONS.md`, `docs/reports/CEO.md` (`7232f800`), and `game/*` (`bf70e744`) |
| `origin/justSilas-v15` (`de9cc50e`) | `00:63,72`, `01:111`, `02:71-73`, `03b:62-65`, `04:65,75`, `05:128`, `07:129-130`, `10:13-14` | Commit `de9cc50e` (`Merge justSilas-v15-bias: WS2...`) | No (held back at Gate B) | **Yes** (tip) | Exact tip of `origin/justSilas-v15` |
| `bd8cd776` | `00:10` | Commit `bd8cd776` (`docs: add fact-checked research grounding...`) | **No** | **No** | Tip of `origin/justSilas-grok-research`; qualify branch name in `00:10` |
| `8f87ed1e` / `8f87ed1` | `00:59,70`, `01:106`, `05:110` | Commit `8f87ed1e` (`Merge ... into justSilas-v14`) | **Yes** | **Yes** | Exact v1.4 merge commit |
| `0933805` | `05:106` | Commit `09338056` (`Merge justSilas-env-v13: tiers v1.3...`) | **Yes** | **Yes** | Exact v1.3 `KNOWN_V_MODE` merge commit |
| `07cb8865` | `00:63,72`, `01:111`, `02:73`, `03b:62,65`, `04:75`, `05:126,128`, `07:128,130`, `10:13` | Commit `07cb8865` (`Gate B: drop v1.5...`) | **Yes** | No | Exact Gate B CEO decision commit |
| `abbb486b` | `00:63,72`, `03b:62,65`, `04:75`, `05:126,128`, `10:13` | Commit `abbb486b` (`env report: Gate B record...`) | **Yes** | No | Exact Gate B `docs/reports/env.md` commit |
| `11e08c9f` | `05:126-127` | Commit `11e08c9f` (`PLAN-95 B1: opt-in ev_delay hint...`) | **Yes** | No | Exact `--hint ev_delay` commit |
| `9fc4f9d9` | `07:123,125` | Commit `9fc4f9d9` (`PLAN-95 A1 + C1: hard judge set...`) | **Yes** | No | Exact A1 + C1 implementation commit |
| `ac2d5cbe` | `07:123,125-126` | Commit `ac2d5cbe` (`PLAN-95 C1: Harbor runs with the signed ledger...`) | **Yes** | No | Exact C1 Harbor verification commit |
| `a8f99c2537c91d72` | `00:59,70`, `04:67`, `05:110`, `10:15` | `TIERS_HASH` constant in `tests/test_env_frozen.py` | **Yes** (in `tests/test_env_frozen.py`) | **Yes** | Frozen `v1.4` `TIERS` SHA-256 prefix (not a git commit SHA) |

- **Line-number and numerical parity (`27/27` line citations verified):** Every explicit line reference (`canary/rules.py` lines `26, 45, 63, 87-95, 94`; `canary/env.py` lines `154-155, 438, 495-496, 527-530`; `canary/solver/policy.py` lines `463-485, 488-590, 537`; `harbor/template/environment/canary-server/Dockerfile` line `15`; `docs/reports/gap.md` lines `48, 50-58, 60-70, 203`; `results/skill_ladder_v1.4.md` lines `60-81`), `docs/CONTRACT.md` Sections `7, 13, 14`, `docs/EXPLOITS.md` `#1, #27, #41`, and every quoted benchmark figure in `results/fresh_table_v1.4.md`, `results/skill_ladder_v1.4.md`, `results/fresh_table_v1.5-candidate.md`, `docs/reports/CEO.md`, and `docs/reports/env.md` matches `origin/justSilas` (`7232f800`) and `origin/justSilas-v15` (`de9cc50e`) identically. (Minor precision note on `09:134`: in `canary/solver/policy.py`, `canary_mi` is lines `463-485` while `partition_search` is lines `388-461`, and `plan_canaries` + `_cweight` + `_pending_canaries` + `joint_mi` span lines `488-590`.)

---

## 4. Section Structure, Numbering Continuity, Metrics, and Exact PR Assembly Steps

### 4.1 Per-Part Metrics and Heading Structure (`origin/fr8/afterquery/research` `4bcfd3e9`)

| File (`docs/research/_parts/...`) | Lines | Words | Bytes | Links | Top Heading(s) | Subsections (`H3`) |
|---|---:|---:|---:|---:|---|---|
| `00_header_and_exec_summary.md` | `74` | `1,525` | `12,216` | `7` | `H1` Title + `H2` Epistemic Protocol + `H2` Executive Summary | `2` unnumbered `H3`s + `<!-- TOC_PLACEHOLDER -->` (`L74`) |
| `01_rumours_attribution.md` | `114` | `2,895` | `23,297` | `14` | `## 1. Rumour Psychology, Serial Distortion, and Workplace Attribution Biases` | `1.1` .. `1.8` (`8` `H3`s) |
| `02_grudges_conflict.md` | `77` | `2,402` | `19,964` | `20` | `## 2. Interpersonal Grudges, Subgroup Faultlines, and Intragroup Conflict` | `2.1` .. `2.4` (`4` `H3`s) |
| `03b_voice_whistleblowing_authority.md` | `65` | `2,710` | `21,910` | `23` | `## 3. Authority Bias, Implicit Voice Theories, and Organisational Silence` | `3.1` .. `3.4` (`4` `H3`s) |
| `04_miscommunication_coordination.md` | `75` | `2,461` | `20,833` | `26` | `## 4. Miscommunication, Delayed-Feedback Misperception, and Coordination Failure` | `4.1` .. `4.4` (`4` `H3`s) |
| `05_overconfidence_commitment.md` | `128` | `3,884` | `29,446` | `18` | `## 5. Overconfidence, Base-Rate Neglect, Escalation of Commitment, and Premature Accusation` | `5.1` .. `5.5` (`5` `H3`s) |
| `07_corporate_governance_failures.md` | `130` | `4,725` | `35,690` | `15` | `## 7. Corporate Governance, Whistleblower Suppression, and Botched Internal Probes` | `7.1` .. `7.8` (`8` `H3`s) |
| `09_canary_traps_watermarking.md` | `134` | `3,327` | `25,415` | `23` | `## 9. Canary Traps, Combinatorial Traitor Tracing, and Synthetic Insider Benchmarks` | `9.1` .. `9.4` (`4` `H3`s) |
| `10_synthesis_and_canary_mapping.md` | `54` | `2,179` | `17,615` | `9` | `## 10. Architectural Synthesis: Human Biases, Frontier LLM Failure Modes, and Canary v1.4 vs. v1.5` | `10.1` .. `10.3` (`3` `H3`s) |
| **Total (9 merged parts)** | **`851`** | **`26,108`** | **`206,386`** | **`155`** | **`1` `H1`, `10` `H2` (`2` frontmatter + Secs `1,2,3,4,5,7,9,10`)** | **`42` `H3`s (`0` `H4+` jumps)** |

### 4.2 Continuity Gaps and Cross-Part Editorial Findings

1. **Blocking numbering gaps -- Missing Sections `6` and `8` (`06_*.md` and `08_*.md`):**
   - Concatenating the `9` merged parts jumps directly from `## 5.` to `## 7.` and from `## 7.` to `## 9.`, leaving **6 dangling internal section references** across Parts `00`, `09`, and `10`:
     - `00_header_and_exec_summary.md:50` -- cites `(Sections 6 and 7)`.
     - `09_canary_traps_watermarking.md:30` -- cites `*Tesla, Inc. v. Tripp* (2018) and *United States v. Reality Leigh Winner* (2017), examined in Section 8`.
     - `10_synthesis_and_canary_mapping.md:3` -- cites `Across Sections 1 through 9`.
     - `10_synthesis_and_canary_mapping.md:8` -- cites `(Sections 1-3, 6-8)`.
     - `10_synthesis_and_canary_mapping.md:9` -- cites `(Sections 4-5, 6-9)`.
     - `10_synthesis_and_canary_mapping.md:26, 28` -- Master Matrix rows `**6. Tech collapses: Nokia & Yahoo** (Sec. 6)` and `**8. Insider espionage & framing forensics** (Sec. 8)`.
   - By contrast, `03b_voice_whistleblowing_authority.md` has **no numbering discontinuity**: its heading is `## 3.` (`3.1..3.4`), and lexical glob order `00..02, 03b, 04..10` places it in the exact Section `3` slot.
2. **Repeated primary-source entries across parts (non-blocking editorial overlap):**
   - Three foundational papers appear with full citation + verbatim abstract blockquotes in two sections each: `Tversky & Kahneman (1974)` (`00` Executive Summary and `05` Sec. `5.2`), `Kruger, Epley, Parker & Ng (2005)` (`01` Sec. `1.6` and `04` Sec. `4.1`), and `Sterman (1989)` (`04` Sec. `4.3` and `05` Sec. `5.3`). Optional trim during assembly if tightening length, or leave intact as self-contained domain sections.
3. **Output filename collision check across upstream and sibling branches:**
   - `docs/research-afterquery.md` **already exists** on `origin/justSilas` (`7232f800`, `319` lines, `11` verified `#anchor` links) and must **not** be overwritten.
   - `docs/research-biases.md` exists on `origin/ivar/aq-game-ux` (`96c9c7d5`) and `origin/fr8/afterquery/afterquery-w31` (`b0af8f4c`); `docs/research-grounding.md` exists on `origin/justSilas-grok-research` (`bd8cd776`).
   - **Collision-free target path:** `docs/research/organisational_biases_and_canary.md` (or `docs/reports/organisational_biases_and_canary.md`), touching `0` existing files on `justSilas`, `justSilas-canary-integration` (`0fb992aa`), `vaishnav/canary-cheat` (`ea762204`), or `ivar/aq-game-ux` (`96c9c7d5`).

### 4.3 Exact Pre-PR Assembly Procedure Before Shipping into `justSilas`

1. **Resolve Sections `6` and `8`:** Either merge completed `06_tech_collapses_nokia_yahoo.md` (`## 6.`) and `08_insider_espionage_forensics.md` (`## 8.`) onto `fr8/afterquery/research`, or -- if shipping without them -- renumber `07 -> 6`, `09 -> 7`, `10 -> 8` and update the `6` cross-references listed in Section 4.2.
2. **Apply the 3 citation fixes in `_parts/` before concatenation:**
   - `00_header_and_exec_summary.md:10`: qualify ``(`docs/research-grounding.md`, `bd8cd776`)`` with branch `origin/justSilas-grok-research`.
   - `09_canary_traps_watermarking.md:125`: replace `test_integrity.py::test_canary_edges` with `tests/test_integrity.py::test_canary_too_many_variants` and `tests/test_integrity.py::test_canary_unique_copy_per_person_rejected`.
   - `10_synthesis_and_canary_mapping.md:40`: clarify `canary/agents/world_builder.py` (`GeminiWorldText`) and `canary/text/gemini.py` (`GeminiWorldTextProvider`).
   - *(Optional ASCII normalization)* `05_overconfidence_commitment.md:122-124`: replace `U+00B1` with `+/-`.
3. **Resolve `<!-- TOC_PLACEHOLDER -->` (`00_header_and_exec_summary.md:74`):** Generate a GFM `#anchor` Table of Contents over all final `##` headings (verifying every `#slug` resolves in the assembled file) or remove the placeholder comment.
4. **Assemble single markdown report and remove scratch directories:**
   ```bash
   mkdir -p docs/research
   $PY -c '
   from pathlib import Path
   parts = sorted(Path("docs/research/_parts").glob("*.md"))
   out = "\n\n".join(p.read_text(encoding="utf-8").rstrip() for p in parts) + "\n"
   Path("docs/research/organisational_biases_and_canary.md").write_text(out, encoding="utf-8")
   '
   git rm -rf --ignore-unmatch docs/research/_parts docs/research/_audits
   git add docs/research/organisational_biases_and_canary.md
   ```
5. **Sync onto latest `origin/justSilas` and verify single-file PR diff + `10/10` gates:**
   ```bash
   git fetch origin
   git merge --no-edit origin/justSilas
   git diff --name-status origin/justSilas..HEAD
   PYTHONPATH=. TMPDIR=/tmp/opencode $PY scripts/verify_pr_branch.py \
     --base origin/justSilas --branch HEAD --require-ff-base
   ```
   Confirm `git diff --name-status origin/justSilas..HEAD` outputs **only** `A docs/research/organisational_biases_and_canary.md` and `verify_pr_branch.py` reports `OVERALL: PASS (10/10 gates passed)` before opening the PR into `justSilas`.
