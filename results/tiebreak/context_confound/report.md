# Tiebreaker Context-Confound & Belief-Replay Forensic Audit (`n=450` Held-Out Verda Episodes)

Deterministic CPU forensic audit over all five committed Verda held-out evaluation runs (`v2-off30`, `v3-verda-s0`, `v3-4k-s0-off30`, `v3-verda-8k-s1`, `v3-verda-8k-s2`; `90` held-out episodes each, `450` total across `HELDOUT_SEEDS` `800000..800059`), aligned with Silas's 05:07 EET WS4 `8k` confound readout (`v3-4k-s0@8k` and paired `v3-8k-s3` on shared secret `1ca0c2a64d`).

## 1. Header Tax and Raw vs Compact Prompt Length Distribution

- **Header crowding (`train.render.render_messages` + Qwen2.5 tool template)**: `easy = 2731` tokens (`66.7%` of `4096`), `medium = 2877` tokens (`70.2%` of `4096`; `2842` tokens in the `slurm-44410.out` pre-freeze snapshot), `hard = 2936` tokens (`71.7%` of `4096`); mean header = **`2848.0` tokens** (`69.5%` of `4096`, `71.2%` of `HFPolicy`'s `4000`-token prompt cap, leaving only `1152.0` body tokens at `4k`).
- **Empirical tokenizer calibration**: pure-Python Qwen2.5 token model verified against live Verda GPU `prefill_tokens + reused_tokens` counters across `21` un-evicted `8k` episodes: `mean_rel_error = +0.00918`, `max_abs_rel_error = 0.01521` (`<1.6%`).
- **Pooled `450`-episode raw vs `train.compact_render` contrast**:
  - Raw `render_messages` prefix length: mean **`24035.4`** tokens (p50 `22533.0`, max `61908`); **`450/450` (`100.0%`)** exceed `4096` tokens and **`329/450` (`73.1%`)** exceed `8192` tokens.
  - Raw `HFPolicy` eviction before `accuse` or episode end: **`1162/1186` (`98.0%` sticky, `96.2%` suffix; `92.2-98.1%` across all `plant_canary` turns per run)** of planted `plant_canary` maps evicted at `4k`, and **`1004/1186` (`84.7%` sticky, `81.4%` suffix; `51.4%` suffix to `84.7%` pooled sticky)** still evicted at `8k`; **`6440/6464` (`99.6%`)** of `list_employees` calls evicted at `4k` (`93.1%` at `8k`).
  - `CompactState` (`compact_user_text` in `train.compact_render`) on the exact same `450` episode prefixes: state block mean **`444.0`** tokens, max **`661`** tokens (`< 900` on **`450/450`**; full compact prompt mean **`1615.4`**, max **`1679`** `< 1800` on **`450/450`**, max chars `5376`), **`0.0%` (`0/1186`)** eviction of canary recipient maps, and **`0.0%` (`0/354`)** eviction of employee rosters (even on full 21-day `hard` reference solver episodes, max `CompactState` = `666` `< 900` tokens, Day-21 full prompt max = `1639` across `2` Day-21 episodes, and `1680` across all `60` reference `hard` episodes, with `0` evicted canary maps).

### Per-Run and Per-Tier Raw vs Compact Context Audit (`450` Held-Out Episodes)

| Run | Tier | N | Score (+/- CI95) | Raw Tok Mean / P50 / Max | >4k / >8k | `plant_canary` Evicted 4k / 8k | `list_employees` Evicted 4k / 8k | `CompactState` / Prompt Max Tok | Compact Evicted |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| `v2-off30` | `easy` | 30 | `-0.839 +/- 0.182` | `5819 / 5300 / 13505` | `100% / 3%` | `15/34 (44.1%)` / `0/34 (0.0%)` | `39/39 (100.0%)` / `4/39 (10.3%)` | `450 / 1678` (`5212c`) | `0.0%` |
| `v2-off30` | `medium` | 30 | `-0.070 +/- 0.127` | `50965 / 57872 / 61908` | `100% / 87%` | `84/84 (100.0%)` / `77/84 (91.7%)` | `1746/1749 (99.8%)` / `1699/1749 (97.1%)` | `561 / 1673` (`5234c`) | `0.0%` |
| `v2-off30` | `hard` | 30 | `-0.633 +/- 0.175` | `16302 / 11365 / 30125` | `100% / 63%` | `72/72 (100.0%)` / `65/72 (90.3%)` | `10/10 (100.0%)` / `9/10 (90.0%)` | `574 / 1674` (`5254c`) | `0.0%` |
| `v2-off30` | `all` | 90 | `-0.514 +/- 0.115` | `24362 / 8846 / 61908` | `100% / 51%` | `171/190 (90.0%)` / `142/190 (74.7%)` | `1795/1798 (99.8%)` / `1712/1798 (95.2%)` | `574 / 1678` (`5254c`) | `0.0%` |
| `v3-verda-s0` | `easy` | 30 | `-0.276 +/- 0.223` | `15070 / 9074 / 39127` | `100% / 53%` | `45/45 (100.0%)` / `36/45 (80.0%)` | `434/438 (99.1%)` / `353/438 (80.6%)` | `463 / 1666` (`5217c`) | `0.0%` |
| `v3-verda-s0` | `medium` | 30 | `+0.000 +/- 0.000` | `56582 / 57466 / 61078` | `100% / 100%` | `97/97 (100.0%)` / `97/97 (100.0%)` | `1965/1976 (99.4%)` / `1856/1976 (93.9%)` | `540 / 1676` (`5135c`) | `0.0%` |
| `v3-verda-s0` | `hard` | 30 | `-0.033 +/- 0.065` | `26181 / 26456 / 29778` | `100% / 100%` | `189/189 (100.0%)` / `184/189 (97.3%)` | `6/6 (100.0%)` / `6/6 (100.0%)` | `581 / 1679` (`5376c`) | `0.0%` |
| `v3-verda-s0` | `all` | 90 | `-0.103 +/- 0.081` | `32611 / 27822 / 61078` | `100% / 84%` | `331/331 (100.0%)` / `317/331 (95.8%)` | `2405/2420 (99.4%)` / `2215/2420 (91.5%)` | `581 / 1679` (`5376c`) | `0.0%` |
| `v3-4k-s0-off30` | `easy` | 30 | `-0.542 +/- 0.236` | `10178 / 5970 / 37871` | `100% / 30%` | `29/29 (100.0%)` / `13/29 (44.8%)` | `204/205 (99.5%)` / `160/205 (78.0%)` | `475 / 1620` (`5111c`) | `0.0%` |
| `v3-4k-s0-off30` | `medium` | 30 | `+0.000 +/- 0.000` | `53636 / 55993 / 60013` | `100% / 100%` | `95/95 (100.0%)` / `95/95 (100.0%)` | `1876/1881 (99.7%)` / `1805/1881 (96.0%)` | `570 / 1674` (`5145c`) | `0.0%` |
| `v3-4k-s0-off30` | `hard` | 30 | `-0.033 +/- 0.065` | `26117 / 26738 / 29442` | `100% / 100%` | `181/181 (100.0%)` / `176/181 (97.2%)` | `10/10 (100.0%)` / `10/10 (100.0%)` | `590 / 1678` (`5244c`) | `0.0%` |
| `v3-4k-s0-off30` | `all` | 90 | `-0.192 +/- 0.096` | `29977 / 26918 / 60013` | `100% / 77%` | `305/305 (100.0%)` / `284/305 (93.1%)` | `2090/2096 (99.7%)` / `1975/2096 (94.2%)` | `590 / 1678` (`5244c`) | `0.0%` |
| `v3-verda-8k-s1` | `easy` | 30 | `-0.580 +/- 0.250` | `9535 / 6343 / 26519` | `100% / 40%` | `21/26 (80.8%)` / `6/26 (23.1%)` | `30/30 (100.0%)` / `12/30 (40.0%)` | `495 / 1674` (`5205c`) | `0.0%` |
| `v3-verda-8k-s1` | `medium` | 30 | `-0.938 +/- 0.122` | `10698 / 10389 / 27654` | `100% / 57%` | `83/83 (100.0%)` / `52/83 (62.6%)` | `30/30 (100.0%)` / `17/30 (56.7%)` | `643 / 1679` (`5217c`) | `0.0%` |
| `v3-verda-8k-s1` | `hard` | 30 | `-0.813 +/- 0.204` | `9856 / 10966 / 16478` | `100% / 70%` | `99/99 (100.0%)` / `60/99 (60.6%)` | `0/0 (0.0%)` / `0/0 (0.0%)` | `479 / 1676` (`5190c`) | `0.0%` |
| `v3-verda-8k-s1` | `all` | 90 | `-0.777 +/- 0.118` | `10030 / 9248 / 27654` | `100% / 56%` | `203/208 (97.6%)` / `118/208 (56.7%)` | `60/60 (100.0%)` / `29/60 (48.3%)` | `643 / 1679` (`5217c`) | `0.0%` |
| `v3-verda-8k-s2` | `easy` | 30 | `-0.067 +/- 0.091` | `18900 / 22476 / 24303` | `100% / 93%` | `34/34 (100.0%)` / `28/34 (82.3%)` | `30/30 (100.0%)` / `28/30 (93.3%)` | `607 / 1672` (`5245c`) | `0.0%` |
| `v3-verda-8k-s2` | `medium` | 30 | `+0.000 +/- 0.000` | `22879 / 22270 / 29425` | `100% / 100%` | `47/47 (100.0%)` / `47/47 (100.0%)` | `30/30 (100.0%)` / `30/30 (100.0%)` | `643 / 1674` (`5168c`) | `0.0%` |
| `v3-verda-8k-s2` | `hard` | 30 | `-0.083 +/- 0.116` | `27813 / 30031 / 36341` | `100% / 100%` | `71/71 (100.0%)` / `68/71 (95.8%)` | `30/30 (100.0%)` / `30/30 (100.0%)` | `661 / 1677` (`5160c`) | `0.0%` |
| `v3-verda-8k-s2` | `all` | 90 | `-0.050 +/- 0.049` | `23197 / 23364 / 36341` | `100% / 98%` | `152/152 (100.0%)` / `143/152 (94.1%)` | `90/90 (100.0%)` / `88/90 (97.8%)` | `661 / 1677` (`5245c`) | `0.0%` |

## 2. Full-History `SolverPolicy` Belief Replay Across All `450` Verda Episodes

- Across all `181` terminal accusations in the `450` held-out Verda episodes, only **`18/181` (`9.94%`)** identified the true mole.
- Full-history `SolverPolicy` replay shows **`173/181` (`95.58%`)** accused strictly below breakeven `1 / (1 + V_known)` (mean `P_full(accused) = 0.0942` vs mean breakeven `0.5241`, mean full-history `EV(accuse) = -0.8208`).

| Run | Tier | N | Accused / Abstain | Precision | Mean `plant_canary` / Ep (Pre-Accuse) | Mean `P_full(accused)` vs Breakeven | Accusing Below Breakeven | Rejected `accuse` Eps (Calls) |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| `v2-off30` | `easy` | 30 | `29/30 (0.97)` / `0.03` | `2/29 (0.07)` | `1.13` (`1.17`) | `0.1472 vs 0.5160` | `27/29 (93.1%)` | `0/30 (0)` |
| `v2-off30` | `medium` | 30 | `4/30 (0.13)` / `0.87` | `1/4 (0.25)` | `2.80` (`1.75`) | `0.1117 vs 0.5202` | `4/4 (100.0%)` | `0/30 (0)` |
| `v2-off30` | `hard` | 30 | `19/30 (0.63)` / `0.37` | `0/19 (0.00)` | `2.40` (`0.95`) | `0.0232 vs 0.5123` | `19/19 (100.0%)` | `0/30 (0)` |
| `v2-off30` | `all` | 90 | `52/90 (0.58)` / `0.42` | `3/52 (0.06)` | `2.11` (`1.13`) | `0.0992 vs 0.5150` | `50/52 (96.2%)` | `0/90 (0)` |
| `v3-verda-s0` | `easy` | 30 | `14/30 (0.47)` / `0.53` | `3/14 (0.21)` | `1.50` (`0.64`) | `0.1673 vs 0.5214` | `13/14 (92.9%)` | `30/30 (812)` |
| `v3-verda-s0` | `medium` | 30 | `0/30 (0.00)` / `1.00` | `n/a (0 acc)` | `3.23` (`0.00`) | `n/a` | `0/0` | `3/30 (3)` |
| `v3-verda-s0` | `hard` | 30 | `1/30 (0.03)` / `0.97` | `0/1 (0.00)` | `6.30` (`4.00`) | `0.0000 vs 0.5525` | `1/1 (100.0%)` | `14/30 (40)` |
| `v3-verda-s0` | `all` | 90 | `15/90 (0.17)` / `0.83` | `3/15 (0.20)` | `3.68` (`0.87`) | `0.1561 vs 0.5234` | `14/15 (93.3%)` | `47/90 (855)` |
| `v3-4k-s0-off30` | `easy` | 30 | `22/30 (0.73)` / `0.27` | `3/22 (0.14)` | `0.97` (`0.73`) | `0.1319 vs 0.5242` | `20/22 (90.9%)` | `30/30 (523)` |
| `v3-4k-s0-off30` | `medium` | 30 | `0/30 (0.00)` / `1.00` | `n/a (0 acc)` | `3.17` (`0.00`) | `n/a` | `0/0` | `2/30 (90)` |
| `v3-4k-s0-off30` | `hard` | 30 | `1/30 (0.03)` / `0.97` | `0/1 (0.00)` | `6.03` (`4.00`) | `0.0000 vs 0.5525` | `1/1 (100.0%)` | `11/30 (42)` |
| `v3-4k-s0-off30` | `all` | 90 | `23/90 (0.26)` / `0.74` | `3/23 (0.13)` | `3.39` (`0.87`) | `0.1262 vs 0.5254` | `21/23 (91.3%)` | `43/90 (655)` |
| `v3-verda-8k-s1` | `easy` | 30 | `25/30 (0.83)` / `0.17` | `4/25 (0.16)` | `0.87` (`1.00`) | `0.1129 vs 0.5378` | `23/25 (92.0%)` | `6/30 (50)` |
| `v3-verda-8k-s1` | `medium` | 30 | `30/30 (1.00)` / `0.00` | `1/30 (0.03)` | `2.77` (`2.77`) | `0.0621 vs 0.5293` | `30/30 (100.0%)` | `0/30 (0)` |
| `v3-verda-8k-s1` | `hard` | 30 | `30/30 (1.00)` / `0.00` | `3/30 (0.10)` | `3.30` (`3.30`) | `0.0243 vs 0.5124` | `30/30 (100.0%)` | `0/30 (0)` |
| `v3-verda-8k-s1` | `all` | 90 | `85/90 (0.94)` / `0.06` | `8/85 (0.09)` | `2.31` (`2.44`) | `0.0637 vs 0.5258` | `83/85 (97.7%)` | `6/90 (50)` |
| `v3-verda-8k-s2` | `easy` | 30 | `2/30 (0.07)` / `0.93` | `0/2 (0.00)` | `1.13` (`1.50`) | `0.1097 vs 0.5305` | `2/2 (100.0%)` | `14/30 (320)` |
| `v3-verda-8k-s2` | `medium` | 30 | `0/30 (0.00)` / `1.00` | `n/a (0 acc)` | `1.57` (`0.00`) | `n/a` | `0/0` | `30/30 (345)` |
| `v3-verda-8k-s2` | `hard` | 30 | `4/30 (0.13)` / `0.87` | `1/4 (0.25)` | `2.37` (`2.75`) | `0.2515 vs 0.5954` | `3/4 (75.0%)` | `19/30 (119)` |
| `v3-verda-8k-s2` | `all` | 90 | `6/90 (0.07)` / `0.93` | `1/6 (0.17)` | `1.69` (`2.33`) | `0.2042 vs 0.5738` | `5/6 (83.3%)` | `63/90 (784)` |

### Mechanistic Explanation of the Three Verda `v3` Regimes

1. **Why `v3-4k-s0` hit `0.892` (`~0.89`) forced-accuse accuracy on solver states yet `0.1579` (`6/38 ~ 0.16`) precision in its own rollouts (`n=180`)**: In `train/grpo_investigator.py`, `60%` of prompts are sampled from the last `6` steps before `SolverPolicy` commits, where the reference solver has already planted **`14.13`** canaries on `hard` (`7.3` on `medium` across the 30-seed post-hoc locked dev set `0..29`). Reading culprit identity off solver-gathered evidence is learnable (`0.190 -> 0.892` over `609` steps). In standalone rollouts, `v3-4k-s0` plants only **`3.53`** canaries/episode (**`0.87`** prior to its `38` accusations, `92.1%` below breakeven) and `100.0%` of its planted canary maps on `medium`/`hard` scroll out of the `4k` window.
2. **Why `v3-8k-s1` accused `94.4%` (`85/90`) at `0.0941` (`8/85 ~ 0.09`) precision**: After `371` GRPO steps on A100 at `8k`, forced-accuse whom-accuracy reached only `0.412` while `free_accuse_frac` climbed (`0.106 -> 0.115`). In its own rollouts `s1` plants `2.31` canaries/episode, calls `list_employees` `0` times on `hard`, evicts `56.7%` sticky (`51.4%` suffix) of canary maps even at `8k`, and fires day-`3.9` accusations with `97.7%` (`83/85`) below breakeven.
3. **Why `v3-8k-s2` abstained `93.3%` (`84/90`)**: Over `693` GRPO steps on H100 spot (`1.87x` `s1`), forced-accuse accuracy stalled at `0.458`, driving `free_accuse_frac` down (`0.068 -> 0.014`). Simultaneously, `train/grpo_investigator.py` rewarded empty-argument `accuse({})` calls as `valid=True` pass-to-solver no-ops (`+0.76` solver continuation reward without risking `-1.0`); at standalone evaluation `s2` emitted **`784`** rejected `accuse({})` calls across **`63/90`** episodes while planting only `1.69` canaries/episode (`94.1%` evicted at `8k`), stalling to `eval_cap`/`horizon` on `84/90` episodes.

## 3. Verified `v3-4k-s0@8k` Inference-Length Confound & Paired `v3-8k-s3` Control (`-0.716 +/- 0.105` vs `-0.147 +/- 0.063`)

Evaluating the **identical `609`-step `4k`-trained adapter** (`v3-4k-s0`, sha256 prefix `3d0cd43b8037`) at `--max-ctx 8192` on Verda A100 `68bbe201` (shared world secret `1ca0c2a64d`, `n=90`, Silas's 05:07 EET WS4 readout) flips the cautious `4k` policy into reckless over-accusing (two-sample delta **`-0.568 +/- 0.123`**), while `8k`-trained `v3-8k-s3` (`344` steps, same shared secret `1ca0c2a64d`) scores **`-0.788 +/- 0.117`**:

| Tier | `v3-4k-s0` @ `4k` (`n=180`) | Accused / Acc @ `4k` | `v3-4k-s0@8k` @ `8k` (`n=90`) | Accused / Acc @ `8k` | `8k - 4k` Two-Sample Delta | `v3-8k-s3` @ `8k` (`n=90`) | Accused / Acc (`s3`) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `easy` | `-0.409 +/- 0.164` | `0.60 / 0.10` | `-0.447 +/- 0.233` | `0.63 / 0.10` | `-0.038 +/- 0.285` (30 vs 60) | `-0.643 +/- 0.249` | `0.90 / 0.13` |
| `medium` | `+0.000 +/- 0.000` | `0.00 / 0.00` | `-0.800 +/- 0.146` | `0.80 / 0.00` | `-0.800 +/- 0.146` (30 vs 60) | `-0.878 +/- 0.166` | `1.00 / 0.07` |
| `hard` | `-0.033 +/- 0.046` | `0.03 / 0.00` | `-0.900 +/- 0.109` | `0.90 / 0.00` | `-0.867 +/- 0.118` (30 vs 60) | `-0.843 +/- 0.178` | `0.97 / 0.07` |
| `all` | `-0.147 +/- 0.063` | `0.21 / 0.03` | `-0.716 +/- 0.105` | `0.78 / 0.03` | `-0.568 +/- 0.123` (90 vs 180) | `-0.788 +/- 0.117` | `0.96 / 0.09` |

- **Out-of-distribution prompt length shift**: On `easy`, accusation rate barely moves (`0.60 -> 0.63`). On `medium` (`0.00 -> 0.80`) and `hard` (`0.03 -> 0.90`, `0/51` correct), allowing prompts to grow from `<=4000` into `4000..8096` tokens pushes the `4k`-trained LoRA outside its SFT/GRPO training context support, collapsing its learned abstention gate while `51-85%` of planted canary recipient maps still scroll out of the `8k` window.
- **Paired `8k`-training control (`v3-8k-s3`)**: Evaluated on the exact same shared secret (`1ca0c2a64d`, `60/60` verified identical step-0 rosters, `n=90`), `v3-8k-s3` (`344` GRPO steps at `8k`) scored `-0.788 +/- 0.117` (accused `0.96`, accuracy `0.09`), yielding a truly paired `8k`-trained minus `4k`-trained difference at `8k` inference of **`-0.073 +/- 0.173`**.

## 4. Reproducibility Check

```bash
python scripts/tiebreak_context_confound_audit.py --check
```
