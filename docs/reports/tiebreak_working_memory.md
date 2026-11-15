# Working-Memory & Prompt-Header Token-Tax Audit (`train/render.py` vs `train/compact_render.py`)

Deterministic offline working-memory and prompt-header token-tax audit strictly over `TRAIN_SEEDS [100000, 200000)` (`106000..106044`, `45` `SolverPolicy` episodes across `easy`, `medium`, `hard`) comparing raw OpenAI JSON chat rendering (`train/render.py` + `HFPolicy` sliding-window truncation) against lossless working-memory rendering (`train/compact_render.py` + `_CompactStateTracker`).

- **Seed Isolation (Panel Fix A)**: All active trajectory simulations strictly use `45` `TRAIN_SEEDS` episodes (`106000..106044`, `15`/tier; `0` `HELDOUT_SEEDS`, `0` `DEV_SEEDS`, and `0` `JUDGE_SEEDS` touched). Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Non-LLM structured and parametric policies operating on the lossless working-memory ledger (`TinyMLPPolicy`, `CompactLinearDAggerPolicy`, `EmpiricalBayesPolicy`, `ScalingLogisticPolicy`; `is_open_weight_llm = False`) are strictly separated from open-weight `Qwen2.5` LoRA runs.

## 1. Static Prompt-Header & Tool-Schema Token-Tax Decomposition

In `WS4-v2` (`slurm-44410.out` / `forensics_prior_runs.json`), `train/render.py` + `to_openai_tools` consumed **`2,842 / 4,096 = 69.4%`** (`0.6938`) of the `4,096`-token context window on static system instructions plus the verbose `13`-tool OpenAI JSON schema on every turn, leaving a **`1,254`-token** (`30.6%`) body budget (`1,152.0` mean tokens under `HFPolicy`'s `4,000`-token prompt cap with `max_new_tokens=96`). `train/compact_render.py` compresses the static system + tool-schema header to **`966.0` tokens** (`66.1%` reduction, saving `1882.0` tokens/turn):

| Tier (`n_emp`, Horizon, Delays) | Raw Header Tokens (Schema + Sys) | Share of `4,096` | Raw `4,096` / `4,000` Body Budget | Compact Sys+Tools Tokens | Empty State / Prompt Tokens | Static Header Savings |
|---|---|---|---|---|---|---|
| `easy` (`12`, `14d`, `[1]`) | `2,731` (`1,252` + `1,479`) | `66.7%` | `1,365` / `1,269` | `963` | `67` / `1,036` | `-1,768` (`-64.7%`) |
| `medium` (`20`, `14d`, `[1,2,3]`) | `2,877` (`1,252` + `1,625`) | `70.2%` | `1,219` / `1,123` | `967` | `67` / `1,040` | `-1,910` (`-66.4%`) |
| `hard` (`40`, `21d`, `[2,3]`) | `2,936` (`1,252` + `1,684`) | `71.7%` | `1,160` / `1,064` | `968` | `67` / `1,041` | `-1,968` (`-67.0%`) |
| `3-tier mean` | `2,848.0` (`1,252.0` + `1,596.0`) | `69.5%` | `1,248.0` / `1,152.0` | `966.0` | `67.0` / `1,039.0` | `-1,882.0` (`-66.1%`) |
| `slurm-44410 ref` (`WS4-v2`) | `2,842` | `69.4%` | `1,254` (`4,096` window) | n/a (raw SFT) | n/a | baseline tax reference |

## 2. FIFO Eviction Before Delayed Leaks Surface vs Lossless `CompactStateTracker` (`TRAIN_SEEDS 106000..106044`, `n=45`)

Across `45` `SolverPolicy` episodes on `TRAIN_SEEDS 106000..106044` (`15`/tier), raw `4k` chat rendering exceeds `4,096` tokens on **`45/45` (`100.0%`)** of episodes, FIFO-evicts Day-1 `list_employees` rosters on **`45/45` (`100.0%`)**, and evicts early `(doc_id, variant -> recipients)` `plant_canary` maps **before** delayed leaks surface in `check_leak_feed` on **`21/21` (`100.0%`)** of `medium` (`1-3d` delay) and **`27/27` (`100.0%`)** of `hard` (`2-3d` delay) canary leaks (`63/70 = 90.0%` overall; `374/375 = 99.7%` evicted by terminal decision). By contrast, `train/compact_render.py` and `_CompactStateTracker` keep working-memory state strictly **`< 900` tokens** (terminal max `624`, any-step max `624`, `0%` `>= 900`) with **`100.0%` lossless retention** of employee clearances, active canary variant maps, surfaced leak candidates, `known_v`, and breakeven `1 / (1 + known_v)`:

| Scope | Raw Prefix Tokens (Mean / Max) | Day-1 Roster Evicted (`4k` / `8k`) | Canary Map Evicted Before Leak Surfaces (`4k` / `8k`) | Canary Map Evicted at Terminal (`4k` / `8k`) | Compact State Tokens (Mean / Max / Any-Step Max) | Compact Retention (Roster / Canary Maps / Leaks / `known_v` & `1/(1+V)`) |
|---|---|---|---|---|---|---|
| `easy` (`n=15`) | `8,631.3` / `14,993` | `15/15 (100.0%)` / `7/15 (46.7%)` | `15/22 (68.2%)` / `0/22 (0.0%)` | `53/54 (98.1%)` / `17/54 (31.5%)` | `313.1` / `365` / `505` | `15/15` / `54/54` / `22/22` / `15/15` (`100.0%`) |
| `medium` (`n=15`) | `24,018.1` / `33,491` | `15/15 (100.0%)` / `15/15 (100.0%)` | `21/21 (100.0%)` / `16/21 (76.2%)` | `145/145 (100.0%)` / `125/145 (86.2%)` | `436.9` / `624` / `624` | `15/15` / `145/145` / `21/21` / `15/15` (`100.0%`) |
| `hard` (`n=15`) | `27,414.1` / `67,235` | `15/15 (100.0%)` / `15/15 (100.0%)` | `27/27 (100.0%)` / `26/27 (96.3%)` | `176/176 (100.0%)` / `166/176 (94.3%)` | `465.2` / `568` / `612` | `15/15` / `176/176` / `27/27` / `15/15` (`100.0%`) |
| `all` (`n=45`) | `20,021.2` / `67,235` | `45/45 (100.0%)` / `37/45 (82.2%)` | `63/70 (90.0%)` / `42/70 (60.0%)` | `374/375 (99.7%)` / `308/375 (82.1%)` | `405.0` / `624` / `624` | `45/45` / `375/375` / `70/70` / `45/45` (`100.0%`) |

## 3. Full `14/21`-Day Horizon Working-Memory Stress Test (`TRAIN_SEEDS 106000..106044`, `n=45`)

To verify boundedness across full `14`-day (`easy`, `medium`) and `21`-day (`hard`) horizons without early termination, all `45` `TRAIN_SEEDS 106000..106044` episodes were also rolled out to their terminal horizon day while planting canaries daily (`376` total planted canaries, up to `25`/episode on `21`-day `hard`). Working-memory state (`compact_user_text`) stayed strictly **`< 900` tokens on `45/45` (`100.0%`)** full-horizon episodes (overall mean `480.6`, max `709` vs `38,399.7` mean / `67,280` max raw prefix tokens; `100.0%` lossless ledger + `_CompactStateTracker` parity, including `600/600` `hard` employee clearance records):

| Scope | Horizon Reached | Planted Canaries (Total / Max Ep) | Raw Full-Horizon Tokens (Mean / Max) | Compact State Tokens (Mean / P90 / Max) | `>= 900` State Tokens | Compact Prompt Mean / Max | Lossless Tracker Parity |
|---|---|---|---|---|---|---|---|
| `easy` (`n=15`) | `14d` | `54` / `7` | `22,262.1` / `24,273` | `418.6` / `463.2` / `478` | `0/15 (0.0%)` | `1,622.1` / `1,676` | `15/15 (100.0%)` |
| `medium` (`n=15`) | `14d` | `145` / `14` | `31,099.5` / `33,491` | `470.6` / `578.0` / `624` | `0/15 (0.0%)` | `1,626.0` / `1,679` | `15/15 (100.0%)` |
| `hard` (`n=15`) | `21d` | `177` / `25` | `61,837.6` / `67,280` | `552.5` / `606.4` / `709` | `0/15 (0.0%)` | `1,633.0` / `1,682` | `15/15 (100.0%)` |
| `all` (`n=45`) | `14..21d` | `376` / `25` | `38,399.7` / `67,280` | `480.6` / `588.2` / `709` | `0/45 (0.0%)` | `1,627.0` / `1,682` | `45/45 (100.0%)` |

## 4. Cross-Verification Against Committed Historical Forensics (`forensics_prior_runs.json` & `context_confound/audit_summary.json`)

| Artifact & Cohort | Metric | Raw `4k` / `8k` OpenAI Chat (`train/render.py`) | Lossless `train/compact_render.py` | Agreement With `TRAIN_SEEDS 106000..106044` Audit |
|---|---|---|---|---|
| `forensics_prior_runs.json` (`WS4-v2`, `n=82`, `42` accused) | Static header tax & `4k` body budget | `2,842 / 4,096 = 69.4%` tax (`1,254` body budget) | `966.0` sys+tools tokens (`-66.1%`) | 3-tier deterministic raw header mean `2,848.0` (`0.21%` from `2,842`) |
| `forensics_prior_runs.json` (`WS4-v2`, `n=82`) | Day-1 `list_employees` roster eviction | **`68/70 = 97.1%`** evicted (`41/42` missing at accuse) | `0.0%` evicted (`100.0%` roster + clearances kept) | Matches `45/45 = 100.0%` `4k` Day-1 roster eviction |
| `context_confound/audit_summary.json` (`all_450_verda`, `n=450`) | `plant_canary` `(doc_id, variant -> recipients)` eviction | **`1,162/1,186 = 98.0%`** (`97.98%` at `4k`, `84.65%` at `8k`) | **`0/1,186 = 0.0%`** evicted | Matches `99.7%` `4k` terminal & `100.0%` `medium`/`hard` pre-leak eviction vs `0.0%` compact |
| `context_confound/audit_summary.json` (`all_450_verda` + `60` `21d` hard ref) | Working-memory token budget (`< 900` target) | `93.50%` ep roster evicted; raw mean `24,035.4` tokens | State mean `444.0`, max `661` (`21d` ref max `666`, `0` `>= 900`) | Matches `106000..106044` state max `624` (natural) and `709` (full `14/21d` horizon) |

### Mechanistic Takeaway

1. **`69.4%` Static Header Tax Crowds Out Delayed-Leak Evidence**: Because `train/render.py` repeats `2,842` static header + OpenAI JSON tool-schema tokens in every `4,096`-token window (`1,254`-token body budget), routine daily `list_documents`, `read_access_logs`, and `search_messages` responses consume the entire body budget within `1-2` simulated days, FIFO-evicting Day-1 `list_employees` (`97.1%` on `WS4-v2`, `100.0%` on `106000..106044`) and early `plant_canary` recipient maps (`98.0%` across `450` Verda episodes, `100.0%` before `1-3d` `medium` and `2-3d` `hard` leaks surface on `106000..106044`).
2. **Lossless Working Memory Eliminates Eviction in `< 900` State Tokens**: `train/compact_render.py` (`extract_public_ledger` / `compact_user_text`) and `_CompactStateTracker` fold public tool outputs into a sufficient-statistic working memory (`<= 709 < 900` state tokens even at Day `21` on `hard`), preserving `100.0%` of employee clearances, active canary variant assignments, surfaced leak candidate sets, `known_v`, and breakeven `1 / (1 + known_v)` with `0.0%` eviction.

## 5. Offline Verification Commands

```bash
python scripts/tiebreak_working_memory_audit.py --check
pytest -q tests/test_tiebreak_working_memory.py
```
