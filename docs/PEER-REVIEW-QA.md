# Canary: Hostile-Reviewer and Judge Peer-Review Q&A

**Submission:** AfterQuery "Break the Agent" (branch `justSilas`, tag `afterquery-final` at `1bc3e281`, latest integrity audit `58716742`) | **Frozen rules:** `TIERS_VERSION = "v1.4"` (SHA-256 `a8f99c2537c91d72` in [`canary/rules.py`](../canary/rules.py))  
**Companion guides:** [`README.md`](../README.md) | [`JUDGE_QUICKSTART.md`](../JUDGE_QUICKSTART.md) | [`docs/JUDGE-WALKTHROUGH.md`](JUDGE-WALKTHROUGH.md) | [`docs/SUBMISSION.md`](SUBMISSION.md)

Every factual claim below is backed by committed artifacts in this repository and a keyless `<1 min` verification command that leaves tracked files untouched.

| # | Hostile-Reviewer Question | Short Verdict | Primary Committed Source | Keyless `<1 min` Check |
|---|---|---|---|---|
| [Q1](#q1-statistical-significance-headline-ordering-and-empty-reply-sensitivity) | Is `65% [24%, 98%]` raw / `72% [52%, 91%]` luck-adj. on hard (`n=30`) statistically meaningful, and why lead with raw before luck-adjusted? | **Yes, with full CIs disclosed:** raw `65% [24%, 98%]` (`+0.322 +/- 0.199` vs `+0.499 +/- 0.119`) leads before luck-adj. `72% [52%, 91%]` (`+0.360` vs `+0.499`); raw paired diff (`-0.177 +/- 0.194`) touches `0` while both ratio CIs exclude `100%`; scoring empty-reply retries as `0` widens the gap to `56% [19%, 87%]` raw / `55% [34%, 77%]` luck-adj. | [`paired_table_gemini.json`](../data/runs/committed/v1.4/paired_table_gemini.json), [`gap.md`](reports/gap.md) | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| [Q2](#q2-post-hoc-seed-lock-2010-solver-dirs-n60-extension-and-cross-model-scope) | Were dev seeds `0-29` pre-registered, why is the solver split across `20+10` dirs, and what about `n=60` extension or non-Gemini models? | **Disclosed accurately:** `0-29` is a **post-hoc lock** (`671ed96`, `28 s` after `8fd4dec`), **not** pre-registered; solver spans `20+10` dirs; pre-registered `n=60` ext (`f9fb7a4a`, `2` valid seeds `34, 37` -> pooled `n=32`: `+0.349 +/- 0.190`, `68% [32%, 100%]` raw, `75% [56%, 93%]` luck-adj.) and pre-registered `gpt-5.5` (`cf394894`) are on record. | [`gap.md`](reports/gap.md), [`paired_table_pooled0to59.json`](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json) | `uv run python scripts/demo_replay.py --seed 4 --verify` |
| [Q3](#q3-what-are-the-25-excluded-infra-invalid-hard-attempts-and-can-an-agent-game-exclusion) | `meta.json` lists `25` excluded hard attempts on OpenCode `gemini-4-carbon` - what were they, and can an agent void a losing run? | **Pure infra (`13 + 6 + 6`), tamper-proof:** `13` `infra:cli_error_event`, `6` `infra:empty_model_response`, `6` `infra:provider_unavailable` across `11` seeds; agent text never voids a run, and killing `mcp_server` scores a valid `0.0`. | [`hard/meta.json`](../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json), [`test_integrity_valid_filter.py`](../tests/test_integrity_valid_filter.py) | `uv run pytest -q tests/test_integrity_valid_filter.py` |
| [Q4](#q4-harness-parity-sidecar-isolation-and-panel-fix-d-on-w1-w4-and-tool-errors) | Does denying `bash`/`python3` in CLI runs vs Harbor, or Panel Fix D (`1bc3e281`: `data.detail` + `W1` wording) & `W4`, skew fairness or replay? | **Isolated & step-exact:** Harbor allows `bash`/`python3` under `11/11` sidecar checks (`61/61` trials; `rehearsal-dry` `43/43` HMAC-verified); `1bc3e281` (`afterquery-final`) added `data.detail` (`28/3,841` calls) + reworded `W1` (`0` losses) while keeping `1,021/1,031` replay (`51,814` results, `0` differ); `W4` clearance never binds. | [`DIFFICULTY.md`](DIFFICULTY.md), [`harbor/README.md`](../harbor/README.md), [`rehearsal-dry/TABLE.md`](../results/harbor/rehearsal-dry/TABLE.md) | `uv run python scripts/careful_mole_check.py` |
| [Q5](#q5-causal-530-v-gap-decomposition-parity-disclosures-and-negative-ablations) | Why does in-process hard reach `95%` and OpenCode medium `111%`, what explains the `5.30 V` hard gap, and what negative ablations failed? | **Exact `5.30 V` identity (`4.19 V` skill + `1.11 V` luck):** `68` vs `0` interviews crowd out `8.5` vs `14.1` canaries -> `9/29` un-isolated accusations (`+3.39 V`), `295`-ep gallery `0.0e+00` residual; `3` failed ablations (`v1.5` `108%`, `solver_v2` `+0.012 +/- 0.029`, `expert` `84% [52%, 128%]` `n=13`) disclosed. | [`failure_analysis_v1.4.json`](../results/failure_analysis_v1.4.json), [`reference_optimality.md`](reports/reference_optimality.md), [`failure_gallery.md`](reports/failure_gallery.md) | `uv run python scripts/failure_analysis_v14.py --check` |
| [Q6](#q6-reward-integrity-and-the-final-judge-protocol-hunt-on-afterquery-final) | Can an agent guess, scrape secrets, forge `/evidence/ledger.json`, or break the tagged `afterquery-final` MCP server? | **All blocked (`52` `EXPLOITS` rows + `58716742` final hunt):** `do_nothing = stop_early = cheat_probe = +0.000`, `guess_day1 = -0.953`, `99x40 = 3,960` battery (`0` diffs), `91` Gemini attackers (`4,325` calls, `0` exploits, `4/4` control) + `424` phase-1 attacks, `1,161` corpus runs (`0` accepted), `12/12` `judge_hunt.py` (`52 s`), `make hunt` `0.000`, `1,057` tests, `accept` `PASS=20 FAIL=0`. | [`EXPLOITS.md`](EXPLOITS.md), [`integrity.md`](reports/integrity.md), [`exploits.json`](../results/anticheat/exploits.json), [`swarm.json`](../results/gemini/swarm.json) | `uv run python scripts/audit_submission.py` |
| [Q7](#q7-did-fine-tuning-a-small-open-model-beat-the-untrained-base-on-held-out-seeds) | Did the `Qwen2.5-1.5B-Instruct` LoRA small model beat the untrained base on held-out Canary seeds? | **Honest status: bar NOT met.** `base n=36` `0.000` (`3%` valid calls); `v2` SFT `-0.457 +/- 0.086` (`n=172`); `v3-4k` GRPO `-0.147 +/- 0.063` (`n=180`, `+0.310 +/- 0.107` two-sample vs `v2`, `100%` valid, train mole ID `0.19 -> 0.89`); `v3-8k` s2 `-0.050 +/- 0.049` (`n=90`), s1 `-0.777 +/- 0.118` (`n=90`). | [`fr8.md`](reports/fr8.md), [`ws4_table_v3.md`](../fr8/analysis/out/ws4_table_v3.md), [`j4_proxy.md`](../fr8/analysis/out/j4_proxy.md) | `uv run python -m fr8.analysis.j4_proxy data/fr8/j4/run-44397/runs` |
| [Q8](#q8-reproducibility-pooled-judge-table-rows-accept-bands-and-fresh-clone-timing) | Why does `make reproduce` print `n=32` / `n=60` rows above `HEADLINE`, how wide are fresh-secret bands, and how fast is a clean Linux clone on `afterquery-final`? | **Deterministic & timed on `1bc3e281`:** `judge_table` pools `n=32` (`+0.349 +/- 0.190`) & `n=60` (`+0.498 +/- 0.097`) while `HEADLINE` diffs locked `n=30`; `300`-secret `4-SD` accept bands & `200`-build Harbor oracle band (`+0.39` to `+0.68`, mean `+0.569`, sd `0.094`); Linux x86_64 fresh clone on `1bc3e281`: `118 s` reproduce, `0 FAIL`. | [`fresh_clone/README.md`](../results/fresh_clone/README.md), [`oracle_range_v1.4.json`](../results/oracle_range_v1.4.json), [`solver_hard_judge40.json`](../results/solver_range/solver_hard_judge40.json) | `uv run pytest -q tests/test_reproduce.py tests/test_game.py` |

---

## Q1. Statistical significance, headline ordering, and empty-reply sensitivity

**Objection:** *"On hard seeds `0-29`, OpenCode `gemini-4-carbon` scores `+0.322 +/- 0.199` against the reference solver's `+0.499 +/- 0.119`. Why lead with the raw `65% [24%, 98%]` ratio before the luck-adjusted `72% [52%, 91%]` ratio, doesn't the raw paired score difference touch zero, and did retrying empty replies help or hurt the model?"*

**Answer:** Following Panel Fix A (`92708834`), we lead everywhere with the raw unadjusted score ratio first, disclose the exact paired difference alongside both bootstrap ratio CIs ([`data/runs/committed/v1.4/paired_table_gemini.json`](../data/runs/committed/v1.4/paired_table_gemini.json), [`docs/reports/gap.md`](reports/gap.md)), and report the un-retried sensitivity bound:

1. **Raw ratio first (`65% [24%, 98%]`), luck-adjusted second (`72% [52%, 91%]`):** Across all `n=30` paired hard worlds (`seeds 0-29`, 10,000 paired bootstrap resamples), OpenCode + `google/gemini-4-carbon` over MCP scores **`+0.322 +/- 0.199`** vs the reference solver's **`+0.499 +/- 0.119`** - **`65% [24%, 98%]`** raw, and **`72% [52%, 91%]`** luck-adjusted (**`+0.360`** vs **`+0.499`**, replacing each binary `+V / -1` accusation outcome with its exact Bayesian expected value `P * V - (1 - P)` under the solver's posterior given the agent's own received tool outputs, and `0` if abstaining).
2. **Honest reading of CIs (ratio CIs vs raw paired difference):** Both paired bootstrap ratio 95% CIs (`[24%, 98%]` raw and `[52%, 91%]` luck-adjusted) exclude parity (`100%`). However, because a single wrong accusation (`-1` vs `~+0.6 V`, a `~1.6 V` swing from 5% canary fingerprint noise or a binary pair gamble) inflates raw per-seed variance, the raw paired score difference is **`-0.177 +/- 0.194`** (`95% CI [-0.371, +0.017]`), which slightly touches zero. Removing binary accusation luck via calibrated posteriors (`95.6%-98.6%` empirical accuracy on `400` tuning seeds `8000-8399` and `400` fresh seeds `9000-9399` in [`docs/reports/reference_optimality.md`](reports/reference_optimality.md)) tightens the CI to **`72% [52%, 91%]`**, excluding parity with wide margin.
3. **Scoring empty-reply retries as `0` widens the gap (`56%` raw, `55%` luck-adjusted):** In the "alternative" row of [`paired_table_gemini.json`](../data/runs/committed/v1.4/paired_table_gemini.json), counting first-attempt `infra:empty_model_response` failures as valid `0` scores instead of retrying lowers OpenCode `gemini-4-carbon` hard to **`+0.279 +/- 0.180`**, or **`56% [19%, 87%]`** raw and **`55% [34%, 77%]`** luck-adjusted (`+0.277` vs `+0.499`, paired diff `-0.220 +/- 0.174`). Retrying infrastructure failures is therefore strictly conservative: it helps the frontier agent and narrows the reported gap.

```bash
uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29
```

---

## Q2. Post-hoc seed lock, 20+10 solver dirs, n=60 extension, and cross-model scope

**Objection:** *"Were dev seeds `0-29` pre-registered before you saw the runs, why does the solver reference live in two directories, what happened to the `n=60` extension (`seeds 30-59`), and did you evaluate non-Gemini frontier models on `v1.4`?"*

**Answer:** Every timestamp, directory split, quota stop, and model-family boundary is disclosed verbatim in [`docs/reports/gap.md`](reports/gap.md), [`README.md`](../README.md), and [`docs/SUBMISSION.md`](SUBMISSION.md):

1. **Seeds `0-29` are a post-hoc lock (`671ed96` came `28 s` after `8fd4dec`), NOT a pre-registration:** The `30` primary OpenCode episodes were committed in `8fd4dec`, and commit `671ed96` (`28 s` later, Sat 14 Nov 22:41 Helsinki) locked `seeds 0-29` as the immutable primary evaluation set. We state explicitly (Panel Fix A, `92708834` and `dcd8c372`) that `0-29` is a **post-hoc lock** preventing later reruns or cherry-picking from being swapped in, **not** a pre-registration. By contrast, the Harbor judge set (`canary-hard-900000` .. `canary-hard-900009`) was fixed in [`docs/PLAN-95.md`](PLAN-95.md) before any frontier run on it.
2. **Why the `n=30` solver reference spans `20+10` committed directories:** The solver originally ran `dev20` (`seeds 0-19`) in [`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`20` episodes) and was then completed on `seeds 20-29` in [`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`10` episodes) so all `30` seeds are paired 1-to-1 (superseding the early `8fd4dec` table that had divided by the 20-seed solver mean).
3. **Pre-registered `n=60` extension (`f9fb7a4a`) and pooled `n=32` table:** Extension `seeds 30-59` was pre-registered before any episode ran in commit `f9fb7a4a` ([`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/`](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md), paired against all `30` solver episodes in [`solver-hard-seeds30to59/`](../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl)) and stopped early at `03:22` Helsinki to preserve the shared 2M-TPM Gemini quota for the judge rehearsal. Two valid OpenCode episodes completed (`seeds 34, 37`: `+0.790` and `+0.700`, mean `+0.745 +/- 0.088` vs solver `+0.735`; `31` other attempts hit `infra:provider_quota` and were excluded). Pooled across all `n=32` valid episodes (`0-29, 34, 37` in [`paired_table_pooled0to59.json`](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json)), OpenCode `gemini-4-carbon` scores **`+0.349 +/- 0.190` vs solver `+0.514`**: **`68% [32%, 100%]`** raw and **`75% [56%, 93%]`** luck-adjusted (paired diff `-0.165 +/- 0.182`). Because `n=2` under quota pressure can favor shorter episodes, `n=30` remains the headline and `n=32` is reported alongside it.
4. **Cross-model scope on `v1.4` (Panel Fix C + `cf394894` pre-registration):** Committed `v1.4` runs cover the Gemini family (`gemini-4-carbon`, `opencode:google/gemini-3.5-flash` at `+0.373 +/- 0.177` / `75% [36%, 123%]` raw / `22% [-23%, 63%]` luck-adjusted on `n=30`, and `587` ladder episodes across `42` cells in [`results/gemini/ladder.md`](../results/gemini/ladder.md) including hosted Gemma 4). Committed `gpt-5.5`, Codex, and Grok runs are on `v1.2`/`v1.3` history (where Codex `gpt-5.5` over MCP hit `97% [89%, 107%]` on `v1.3` hard `seeds 0-9`, triggering the `v1.4` 40-staff / 21-day scaling in [`docs/HISTORY.md`](HISTORY.md)). A second-family **`gpt-5.5` OpenCode `1.19.5` run on `v1.4` hard `seeds 0-29`** (tag `afterquery-final`, `13` MCP tools only, `7,200 s` cap, `$200` spend cap) was pre-registered before any episode in commit `cf394894` ([`docs/reports/gap.md`](reports/gap.md); OpenAI key unavailability at panel time noted in [`docs/agents/PANEL-0500.md`](agents/PANEL-0500.md)).

```bash
uv run python scripts/demo_replay.py --seed 4 --verify
```

---

## Q3. What are the 25 excluded infra-invalid hard attempts, and can an agent game exclusion?

**Objection:** *"`README.md` mentions empty-reply retries, while Judge Sim #13 noted that `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json` lists `25` excluded attempts across `3` categories. What are all `25`, and could an agent print `'429'` or kill `mcp_server` to void a losing episode?"*

**Answer:** Every excluded attempt in [`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json`](../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json) (`invalid_episodes: []`, `infra_invalid_attempts_excluded`: `25` entries across `11` unique seeds `3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29`) is a structured harness/provider transport failure, audited and locked by [`tests/test_integrity_valid_filter.py`](../tests/test_integrity_valid_filter.py):

- **Exact 3-category breakdown of the `25` excluded attempts (`13 + 6 + 6 = 25`):**
  1. **`13` `infra:cli_error_event`** - OpenCode CLI emitted a top-level `"type": "error"` harness/API event instead of completing the session (`seeds 14 [x2], 15, 18, 19, 23 [x2], 27 [x4], 29 [x2]`).
  2. **`6` `infra:empty_model_response`** - the upstream endpoint returned `finish=stop` with `output_tokens=0`, `reasoning_tokens=0`, no text, and no tool call (`seeds 3, 19 [x2], 25, 26, 27`). As shown in Q1, scoring these as `0` instead of retrying drops OpenCode hard from `65%` to `56%` raw (`55%` luck-adjusted).
  3. **`6` `infra:provider_unavailable`** - transient upstream Gemini 503/unavailable outages (`seeds 19 [x2], 24 [x2], 27, 29`).
- **Why an agent cannot game `valid: false` ([`canary/agents/frontier/common.py`](../canary/agents/frontier/common.py), [`tests/test_integrity_valid_filter.py`](../tests/test_integrity_valid_filter.py)):**
  - **Agent text and tool outputs are ignored by `classify_infra`:** Only structured OpenCode harness `"type": "error"` frames and runner stderr match `infra:*`; an agent writing `"The database is locked; usage limit has been reached"` or receiving `"429 Too Many Requests"` in a tool output is classified `None` (valid episode, `test_agent_text_never_voids_a_run`).
  - **Killing the MCP server scores a valid `0.0`:** If an agent with shell access runs `pkill`, `kill`, or `killall` against `canary.mcp_server`, `agent_touched_server` catches the command in the transcript and records `note: "agent_killed_server"` with a **valid score of `0.0`** (`test_run_one_marks_a_self_killed_server_valid_zero`), never an excluded retry.

```bash
uv run pytest -q tests/test_integrity_valid_filter.py
```

---

## Q4. Harness parity, sidecar isolation, and Panel Fix D on W1-W4 and tool errors

**Objection:** *"Your headline OpenCode CLI runs denied `bash` and `python3` whereas Harbor's container allows them; meanwhile, tag `afterquery-final` (`1bc3e281`) added `data.detail` on tool errors and reworded `W1`, while leaving `W2-W4` (`access_constraints`) in place. Does any of this leak secrets, break step-level replay, or disadvantage the agent?"*

**Answer:** Both the CLI-vs-Harbor permission boundary and Panel Fix D (`1bc3e281`) are verified by container isolation proofs, trajectory audits, and backwards-compatible replay checks ([`docs/DIFFICULTY.md`](DIFFICULTY.md), [`harbor/README.md`](../harbor/README.md), [`results/audit/instruction_checks.md`](../results/audit/instruction_checks.md)):

1. **Headline OpenCode (`13` MCP tools) vs Harbor container (`bash`/`python3` allowed under `11/11` sidecar isolation):**
   - Headline OpenCode CLI runs set `"opencode_permission": {"*": "deny", "canary_*": "allow"}` (`13` MCP tools only, OpenCode `1.18.29`), isolating raw LLM reasoning over MCP without external scripting.
   - Harbor's agent container (`main`) allows `bash` and `python3` (so a Harbor agent may compute posteriors in Python), while running `canary-server` (uid `10001`) in a separate sidecar container with its own filesystem, separate PID namespace, `0600` consumed `CANARY_*_FILE` secrets (`#27`), and no Docker socket. [`harbor/check_isolation.sh`](../harbor/check_isolation.sh) passes **`11/11` checks (`0` findings) across all `61/61` committed Harbor `solve.sh` `isolation.txt` trials** (negative control inside the sidecar flags `6` findings). In our committed 10-task Harbor dry rehearsal ([`results/harbor/rehearsal-dry/TABLE.md`](../results/harbor/rehearsal-dry/TABLE.md)), **`43/43` trials are HMAC-verified** (`oracle +0.467` vs `OpenCode +0.398`, `85% [11%, 355%]` single 10-task harness check; `do_nothing = stop_early = +0.000`; full 3x10 protocol in [`results/harbor/rehearsal/README.md`](../results/harbor/rehearsal/README.md)).
2. **Panel Fix D in `1bc3e281` (tag `afterquery-final`) - `data.detail` + `W1` wording, with `1,021/1,031` step replay preserved:**
   - **Specific tool error details (`data.detail`):** Tool errors keep the exact top-level `error: "invalid arguments"` string while adding `data.detail` naming the specific schema/argument issue from public state only (mole-independence guarded by `tests/test_env.py::test_error_detail_does_not_depend_on_who_the_mole_is`). In the `30` headline OpenCode hard episodes, only **`28` of `3,841` tool calls (`0.7%`)** hit `invalid arguments`, and pre-`1bc3e281` committed episodes compare without `data.detail` so **`1,021` of `1,031` replayable episodes (`51,814` recorded tool results) still replay with `0` differences**.
   - **`W1` careful-mole wording fixed & `0` W1 losses verified:** `MoleView` has no `is_canary` field; default random leak selection weights documents by `1 - recipients/N`. Commit `1bc3e281` reworded the medium/hard sentence to state this explicitly (`harbor/canary-task/instruction.md` regenerated; `Exact parameters` block unchanged). Replaying all `30` committed hard episodes via [`scripts/careful_mole_check.py`](../scripts/careful_mole_check.py) confirms Gemini sized canaries identically to the solver (**`254` vs `424` canaries, mean staff share `0.26` vs `0.24`**, careful weight `0.74` vs `0.76`, observed leaks/plant `55/254 = 0.22` vs `64/424 = 0.15`), `0/30` summaries blamed avoidance, and **`0` W1 losses occurred**.
3. **Complete parameter disclosure & `W2-W4` (`W4` clearance never binds):** All **`34/34` `TierParams` fields** are printed in the prompt (`39/39` tool smokes `ok`; Harbor agent timeout raised `3600.0 -> 10800.0` s in `512836b9`). `W2` (base tiers run empty `DEFAULT_STRATEGY` rule list) and `W3` (`advance_day` event order; `0.00`-day Gemini feed read lag) are documented in `DIFFICULTY.md`; **`W4` (`access_constraints` clearance rule on hard never binds)** is explicitly disclosed in `README.md` and `DIFFICULTY.md` because `canary_level = 1` lets every employee (clearance `1-3`) receive every canary.

```bash
uv run python scripts/careful_mole_check.py
uv run python scripts/rehearsal_table.py results/harbor/rehearsal-dry
```

---

## Q5. Causal 5.30 V gap decomposition, parity disclosures, and negative ablations

**Objection:** *"Why does `gemini-4-carbon` reach `95% [62%, 140%]` in-process on hard and `111% [99%, 127%]` in OpenCode on medium, what exact decisions account for the `5.30 V` OpenCode hard gap, and did you cherry-pick mechanics to manufacture a gap?"*

**Answer:** Parity cells, an exact zero-residual `5.30 V` causal identity ([`results/failure_analysis_v1.4.json`](../results/failure_analysis_v1.4.json)), and three unsuccessful gap-widening ablations ([`docs/reports/gap.md`](reports/gap.md), [`docs/reports/reference_optimality.md`](reports/reference_optimality.md)) show the hard gap comes from active canary gathering and stopping calibration under delayed noisy leaks:

- **Parity disclosures (OpenCode medium `111%` & in-process hard `95%`) and Gemini ladder (`587` episodes):**
  - **OpenCode medium (`111% [99%, 127%]` raw, `101% [85%, 119%]` luck-adjusted):** `+0.713 +/- 0.042` vs solver `+0.645 +/- 0.087` (`30/30` correct on mean day `8.0`), proving OpenCode + MCP + the 13 tool schemas work cleanly when canary fingerprints are noiseless (`1.00`) over `20` staff.
  - **In-process hard (`95% [62%, 140%]` raw, `84% [65%, 106%]` luck-adjusted; `+0.473 +/- 0.118`, medium `+0.530 +/- 0.138`, `82% [56%, 108%]` raw, `74% [52%, 99%]` luck-adjusted):** Our custom in-process loop replays full history and encrypted `thought_signature` tokens across turns (stripping `thought_signature` causes `400 INVALID_ARGUMENT` in **`10/10`** hard episodes vs **`0/628`** API errors with replay ON in [`results/gemini/ablations.md`](../results/gemini/ablations.md); explicit context caching saved **`62.9%`** on Atlas/gallery reads and **`75.9%`** across **`29,150`** programme calls; across the **`587`-episode, `42`-cell** thinking ladder in [`results/gemini/ladder.md`](../results/gemini/ladder.md), `gemini-4-carbon` high reaches `106% [94%, 126%]` at `n=10` and `gemini-3.6-flash` rises from `-32%` minimal to `87%` / `88%` at medium/high, `n=40`). Yet on hard `seeds 0-29`, in-process `gemini-4-carbon` still plants only **`8.6` vs `8.5`** canaries (solver: **`14.1`**), uses **`33%` vs `32%`** of daily canary capacity (solver: **`67%`**), and runs **`57` vs `68`** low-value interviews (`<= 0.005` nats KL at `interview_lr: 1.2` vs `ln 3 ~= 1.1` nats per leaked 3-variant canary; solver: **`0`** interviews). Without bespoke signature scaffolding, OpenCode additionally commits more often before isolating the mole (`9/29` vs `6/29` unresolved accusations).
- **Exact additive `5.30 V` decomposition across `30` paired hard seeds ([`results/failure_analysis_v1.4.json`](../results/failure_analysis_v1.4.json)):**
  - **`+3.39 V` (`+0.113`/ep) - premature un-isolated accusations:** **`9/29`** Gemini accusations occurred with `>=2` suspects still consistent with every leak (`+3.50 V` lost; `20/29` isolated net `-0.11 V`) vs **`3/30`** for the solver, including `3` negative-EV horizon gambles on seeds `5, 18, 23` (`1.64 V` lost where abstaining for `0` beat accusing; [`docs/reports/failure_gallery_breakeven.md`](reports/failure_gallery_breakeven.md)).
  - **`+0.62 V` (`+0.021`/ep) - seed 11 abstention:** `121` interviews left `7` consistent suspects (`P <= 0.40`); Gemini abstained (`0.00`) while the solver caught the mole on day `9` (`+0.62`).
  - **`+1.75 V` (`+0.058`/ep) - waiting leak drain** (mean accuse day `13.2` vs `10.6`) + **`+0.12 V` (`+0.004`/ep) restriction cost** - **`1.69 V` (`-0.056`/ep) saved canary cost** (`8.5` vs `14.1` canaries at `0.01 V`).
  - **Zero-residual identity:** `+3.39 + 0.62 + 1.75 + 0.12 - 1.69 =` **`+4.19 V`** (`+0.140`/ep **skill / luck-adjusted gap**) `+` **`+1.11 V`** (`+0.037`/ep **luck**: `4` wrong vs `3.4` expected for Gemini, `1` vs `1.0` for solver) `=` **`+5.30 V`** (`+0.177`/ep **raw gap**). Across **`295` episodes** in [`docs/reports/failure_gallery.md`](reports/failure_gallery.md), causal regret attribution leaves **`0.0e+00` unexplained residual**.
- **Three negative ablations disclosed and NOT shipped ([`docs/reports/gap.md`](reports/gap.md)):**
  1. **`v1.5` biased staff** (rumours, grudges, authority, misforwards): `gemini-4-carbon` rose from `61%` to **`108%` of the solver** on paired hard seeds `0-9` (`data/runs/committed/v1.5-candidate/`); dropped at Gate B.
  2. **`solver_v2` stronger reference:** gained only **`+0.012 +/- 0.029`** on `400` fresh hard seeds `9000-9399` (`0.561 -> 0.573`, below our `+0.08` replacement bar; threshold grid search improved hard by only `+0.005` in [`docs/reports/reference_optimality.md`](reports/reference_optimality.md)).
  3. **`expert` 70%-fingerprint tier** (branch `justSilas-expert` `29ca3bc5`): scripted `grok_tactics` collapsed (`0.36 -> 0.01`), while OpenCode `gemini-4-carbon` held at **`84% [52%, 128%]` luck-adjusted (`n=13`)**.

```bash
uv run python scripts/failure_analysis_v14.py --check
uv run python scripts/reference_optimality.py --tier hard --seed0 8000 --seeds 40 --procs 2
```

---

## Q6. Reward integrity and the final judge-protocol hunt on afterquery-final

**Objection:** *"How do we know an agent cannot game the score on day 1, read secrets or `SALT`, forge `/evidence/ledger.json`, exploit MCP wire edge cases, or break the tagged `afterquery-final` commit?"*

**Answer:** [`docs/EXPLOITS.md`](EXPLOITS.md) logs **`52` numbered attack entries (`#0` to `#51`, plus judge-hunt rows `J1-J15`)**, closing real red-team findings (`#1` wrong accusation `= -1`, `#10` log-signal recalibration, `#23/#24/#28` fail-closed world secret & `CANARY_ALLOW_DEV`, `#27` `0600` `CANARY_*_FILE` + sidecar isolation, `#42` shared-verifier guard), backed by automated batteries and the final CEO judge-protocol hunt on `afterquery-final` (`1bc3e281`) recorded at commit `58716742` in [`docs/reports/integrity.md`](reports/integrity.md):

1. **Zero abstention & negative-EV guessing:** Abstaining, stopping early, or probing without accusing scores **exact `+0.000`** (`do_nothing = stop_early = cheat_probe = +0.000`; [`results/judge_table.md`](../results/judge_table.md), `cheat_probe` `0.0` on `6/6` Harbor trials across `149` attempts each with `"holes": []`). Wrong accusation pays **`-1`**, so `guess_day1` averages **`-0.953`** (`sd 0.045`, range `[-1.00, -0.80]`) across `300` fresh secrets x `40` hard judge seeds in [`results/solver_range/guess_day1_hard_judge40.json`](../results/solver_range/guess_day1_hard_judge40.json) (`-1.000 +/- 0.000` hard, **`-0.950 +/- 0.098`** medium in `judge_table.md`; Harbor `cheat` `-1.0` on `6/6`), and `status` hides unsurfaced leaks (`665` states audited, `0` leak true `V`).
2. **HMAC-SHA256 signed ledger (`c1-tamper -> 0`):** `/ledger` is signed with a per-build `0600` `ledger_key` held only by the sidecar and separate verifier; tampered `score: 1.0` in [`results/harbor_negative/c1-tamper/result.json`](../results/harbor_negative/c1-tamper/result.json) scores **`0`** (`FAIL: bad ledger signature`). Across `results/harbor/`, **`80/80` Harbor trials and `18/18` job summaries** pass `harbor_consistency`.
3. **Committed `99 x 40 = 3,960`-run anti-cheat battery (`0` differences) & `1,161` Sleeper corpus runs:** [`results/anticheat/exploits.json`](../results/anticheat/exploits.json) runs **`99` rows x `40` judge seeds = `3,960` runs** (`14` scripted attack probes + `1` swarm probe `swarm_w2b008` per tier, effort ladder peaking at `+0.051 +/- 0.244` on hard 90% vs solver `+0.545 +/- 0.098`, plus sanity/control rows) with **`0` differences** on `make anticheat-verify`. Injecting `129` Sleeper red-team tricks across `3` seeds x `3` tiers (**`1,161` runs** in [`results/anticheat/corpus_eval.txt`](../results/anticheat/corpus_eval.txt)) yields **`0` accepted calls and `0` score changes**.
4. **`91` finished Gemini swarm attackers (`4,325` calls, `0` exploits, `4/4` positive control) + `424` phase-1 attacks:** `75` full-repo whitebox attackers + `16` blackbox attackers (**`91` finished attackers**) + `9` MCP reruns (**`100` attempts**, **`4,325` tool calls** in [`results/gemini/swarm.json`](../results/gemini/swarm.json)) found **`0` verified exploits and `0` invariant violations**, while catching **`4/4` reopened positive-control exploits** (`16/16` reruns `= 1.0` in [`results/gemini/swarm_control.json`](../results/gemini/swarm_control.json); wave-2b candidate `w2b-008` refuted at `+0.363` vs `+0.545` on `40` hard judge seeds). Gemini phase-1 red-teaming added **`424` ledger-verified attacks** (`0` verified exploits; [`docs/reports/integrity.md`](reports/integrity.md)).
5. **Final judge-protocol hunt on tagged `afterquery-final` (`1bc3e281`, committed in `58716742` [`docs/reports/integrity.md`](reports/integrity.md)):** Executed sequentially on the tagged code with no keys and no Docker:
   - `python scripts/judge_hunt.py --out results/anticheat/judge_hunt.md` ([`results/anticheat/judge_hunt.md`](../results/anticheat/judge_hunt.md)): **`12/12` (`12 of 12`) wire attacks held** on the live MCP server in **`52 s`** (double-session accuse, 15 homoglyph IDs, JSON-RPC batch, 5 MB / 20k-deep JSON, 16 grader routes, V inflation, 200 parallel `advance_day`, post-accuse view parity).
   - `make hunt`: best non-solver score **`0.000`** and **`0` invariant violations** across all 4 modes and every tier/track (**`4 min 57 s`**).
   - `make reproduce` (full `40` judge seeds/tier): exit `0`, all probes blocked, `HEADLINE` unchanged (`65% [24%, 98%]`).
   - `make anticheat-verify`: `99` rows rerun, **`0` differences**; `make test`: **`1,057` passed**; `make accept`: **`PASS=20`, `FAIL=0`**.

```bash
uv run python scripts/audit_submission.py
uv run pytest -q tests/test_harbor_ledger_sig.py tests/test_harbor_cheat.py tests/test_gemini_lab_swarm.py
uv run python scripts/judge_hunt.py
```

---

## Q7. Did fine-tuning a small open model beat the untrained base on held-out seeds?

**Objection:** *"For the small-model tiebreaker (`Qwen2.5-1.5B-Instruct` LoRA), does your SFT or GRPO checkpoint actually score above `0` on held-out seeds, and why are the reported deltas two-sample rather than paired?"*

**Answer:** **No - the tiebreaker bar (held-out mean `> 0` with 95% CI excluding `0`) is NOT met**, and we claim **no held-out reward gain over base** ([`README.md`](../README.md), [`docs/reports/fr8.md`](reports/fr8.md) "04:45 WS4 small-model tiebreaker readout", [`fr8/analysis/out/ws4_table_v3.md`](../fr8/analysis/out/ws4_table_v3.md)):

- **Held-out progression (`Qwen2.5-1.5B-Instruct` LoRA trained strictly on `TRAIN_SEEDS`, playing full held-out episodes alone):**
  - **`base` (untrained, `n=36`):** **`0.000`** (`0.000 +/- 0.000` at **`3%` valid tool calls**; emits unparseable calls, never leaves day 1, and scores `0` only by abstaining every episode; in the earlier J4 pilot [`fr8/analysis/out/j4_proxy.md`](../fr8/analysis/out/j4_proxy.md), valid calls rose **`0.08 -> 0.99`** and solver action-type agreement rose **`0.00 -> ~0.85`**, with deduplicated `v1` at `-0.250 +/- 0.256`, `n=12`).
  - **`v2` (SFT on solver trajectories, dense 4k windows, `n=172`):** **`-0.457 +/- 0.086`** (`92%` valid tool calls, but accuses recklessly on `55%` of episodes at `0.09` precision).
  - **`v3-4k` (`v3-4k-s0`, GRPO from `v2` on environment reward, Verda H100, `n=180`):** **`-0.147 +/- 0.063`** - a **`+0.310 +/- 0.107` two-sample recovery vs `v2`**, reaching **`100%` valid tool calls**, curbing accusation rate `0.55 -> 0.21`, and raising **training decision-state mole ID accuracy `0.19 -> 0.89`** (`1,218` draws across `2,000` states), but held-out precision remained `6/38 = 0.16` (partial V100 replicate `v3-4k-s1`, `n=25`: `-0.240 +/- 0.171`).
  - **`v3-8k` (GRPO at 8k context, `n=90` per seed):** **`v3-8k seed 2` (`v3-8k-s2`, Verda H100 spot)** reached **`-0.050 +/- 0.049` (`n=90`)** by abstaining on `93%` of episodes, whereas **`v3-8k seed 1` (`v3-8k-s1`)** scored **`-0.777 +/- 0.118` (`n=90`)** (`94%` accusation rate).
- **Why WS4 deltas are two-sample (`04:00` correction in [`docs/reports/fr8.md`](reports/fr8.md)):** Unlike public-key dev seeds `0-29` (where Gemini vs solver is truly seed-paired), held-out seeds fail closed to a fresh per-process world secret when `CANARY_WORLD_SECRET` is unset, so separate `eval_hf` runs drew distinct worlds on the same seed numbers (`115/115` step-0 rosters differed) and all WS4 model-to-model deltas are computed two-sample.
- **Takeaway:** SFT + GRPO taught protocol compliance (`3% -> 100%`), calibrated abstention (`+0.310` over `v2`), and identifying the mole when solver-gathered evidence is in view (`0.19 -> 0.89`), but did not teach active canary gathering on the model's own states - the exact bottleneck `gemini-4-carbon` hits on hard.

```bash
uv run python -m fr8.analysis.j4_proxy data/fr8/j4/run-44397/runs
```

---

## Q8. Reproducibility, pooled judge-table rows, accept bands, and fresh-clone timing

**Objection:** *"When a judge runs `make reproduce` or `harbor/build.py` on a fresh clone of `afterquery-final` (`1bc3e281`), why do the replayed OpenCode and solver rows in `judge_table` show `n=32` and `n=60`, how much do fresh world secrets move the means, and how long does keyless verification actually take?"*

**Answer:** Every output difference between pooled replay rows, the locked `n=30` `HEADLINE` check, fresh-secret statistical bands, and clean-environment wall-clock timings on `afterquery-final` (`1bc3e281`) is documented and tested ([`README.md`](../README.md), [`results/fresh_clone/README.md`](../results/fresh_clone/README.md), [`results/oracle_range_v1.4.json`](../results/oracle_range_v1.4.json)):

1. **Pooled `judge_table` rows (`n=32`, `n=60`) vs locked `n=30` `HEADLINE` recompute:** `make reproduce` writes scratch files only to gitignored `results/latest/`. In its "reported agent runs" section, it pools all committed `v1.4` episodes on disk - printing **`+0.349 +/- 0.190` (`n=32`)** for `opencode:google/gemini-4-carbon` hard (`seeds 0-29` + extension `seeds 34, 37`) and **`+0.498 +/- 0.097` (`n=60`)** for `solver` hard (`seeds 0-59` across the `3` reference directories). Immediately after `ANTI-CHEAT`, the final **`HEADLINE`** step runs `scripts/paired_gemini.py --version v1.4 --seeds 0-29`, recomputes the locked **`n=30`** primary row (**`+0.322 +/- 0.199` vs `+0.499 +/- 0.119` = `65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted**), and exits `1` on any byte diff against `data/runs/committed/v1.4/paired_table_gemini.md` (`CANARY_WORLD_SECRET=<any_string> make reproduce` makes the 40-seed table bit-identical too).
2. **`300`-secret `4-SD` accept bands & `200`-build `10`-task Harbor oracle range (`+0.39` to `+0.68`):**
   - **Keyless `make accept` (`300` secrets, `mean +/- 4 SD`):** [`scripts/judge_accept.sh`](../scripts/judge_accept.sh) checks 40-judge-seed means against `mean +/- 4 SD` measured over **`300` fresh world secrets** in [`results/solver_range/`](../results/solver_range/solver_hard_judge40.json) (hard `solver` mean **`+0.567`**, sd **`0.050`**, band `[+0.37, +0.77]`; medium `+0.630`, sd `0.040`; easy `+0.774`, sd `0.020`; `do_nothing` and `stop_early` exact `0.000`, honest false-fail rate `< 1e-4`).
   - **Live Docker Harbor rerun (`200` builds, `10` tasks `900000-900009`):** Across **`200` simulated fresh-secret builds** in [`results/oracle_range_v1.4.json`](../results/oracle_range_v1.4.json), the 10-task hard oracle 90% range is **`+0.39` to `+0.68`** (mean **`+0.569`**, sd **`0.094`**, `p5 = +0.393`, `p95 = +0.678`; dry rehearsal landed at `+0.467` oracle vs `+0.398` OpenCode). Run `uv run python harbor/build.py` **once** so oracle and frontier share worlds, pass `--api-key-name GOOGLE_GENERATIVE_AI_API_KEY`, and pass `--agent-setup-timeout-multiplier 3`.
   - **Keyless Gemini gateway & Pyodide browser parity:** `make lab-replay` replays recorded Gemini runs locally with zero keys (`lab_replay: ALL OK`), and `make game-serve` / [`tests/test_game.py`](../tests/test_game.py) verify Pyodide == CPython (`0.79` accusing `e09` on day `6` of medium seed `3000`, judge/dev seeds blocked).
3. **Timed clean-env fresh-clone log on `afterquery-final` (`1bc3e281`, [`results/fresh_clone/README.md`](../results/fresh_clone/README.md)):** Cloned at tag `afterquery-final` (`1bc3e281`) on Rocky Linux 9.5 x86_64 under `env -i` (no `.venv`, no `CANARY_*` vars, no API keys, no `.env`; [`linux_x86_64_afterquery_final_1bc3e281.log.txt`](../results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt)): `clone` **`3 s`**, fast 40-seed table (`REPRO_ANTICHEAT=0`) **`27 s`**, full 40-seed **`make reproduce` `118 s`** (`118.17 s` wall, exit `0`, `1,021/1,031` episodes & `80/80` Harbor trials consistent, `HEADLINE` identical), `audit_submission.py` **`4 s` (`3 PASS, 1 WARN, 0 FAIL`)**, and core security/replay tests **`175 s` (`100 passed`)**, with `git status --porcelain: empty` after every step (macOS arm64 cold clone at `09e7363`: `52 s` reproduce, `142 s` `make accept` `RESULT: PASS`).

```bash
make setup && make reproduce
make accept
uv run pytest -q tests/test_reproduce.py tests/test_game.py
make lab-replay
```

Reference live Docker Harbor rerun sequence (build once, then run paired oracle + baselines + OpenCode):

```bash
uv tool install harbor && uv run python harbor/build.py
harbor run -p harbor/dataset -a oracle -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4
GOOGLE_GENERATIVE_AI_API_KEY=<your_key> harbor run -p harbor/dataset -a opencode \
    -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY \
    --agent-setup-timeout-multiplier 3 -n 4
```
