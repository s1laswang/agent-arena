# Canary on Verda: Compute Track

**Challenge:** AfterQuery "Break the Agent". Canary is a replay-verified RL environment: an investigator agent plants canary documents and has to name the mole who leaks them. **Verda example idea we are doing:** "Make an agent stronger than it was on Friday. Run thousands of rollouts in your AfterQuery RL environment and fine-tune a smaller model on the experience."

**Honesty rule for this page.** Most of our compute this weekend ran on **FR8 freighter**, a Slurm cluster with CPU nodes and V100 GPUs, and on **the Mac**, which made every Gemini API call. Nothing from FR8 or the Mac is counted as Verda. Every number below is labelled **[Verda]**, **[FR8]** or **[Mac]**. Sources are in the repo:
- the Verda ledger: `fr8/verda/README.md` (branch `justSilas-fr8`);
- the run log: `docs/reports/fr8.md`, section "Verda" (branch `justSilas-fr8`);
- the eval tables: `fr8/analysis/out/ws4_table_*.md`;
- the Meta glasses runs: `docs/reports/verda-evidence.md`.

Times are Helsinki time (EET), Sat 14 → Sun 15 Nov 2026, unless they end in Z.

---

## 1. What compute bought us (Ambition)

Two things would not have fit on a laptop, and they did not fit on our V100 cluster before the deadline either:

1. **The small-model RL tiebreaker.**
   - We ran decision-point GRPO for a Qwen2.5-1.5B LoRA "investigator" against the live Canary environment. Every sampled action is scored by finishing the episode with the reference solver, which gives 8 rollouts per state.
   - That makes it one 4k run plus **4 parallel 8k-context GRPO replicates** (a 4k replicate was lost to spot preemption), plus two extra held-out evaluations, all inside one night.
   - On FR8's V100 one replicate gets about 250 steps in 4 h. **[Verda]** an H100 did 609 steps in 2.0 h.
2. **Several teams' GPU work on one queue.** The same Verda boxes also ran:
   - a self-hosted open-weight agent (Qwen3-14B under vLLM) playing Canary;
   - two vision models for our Meta glasses entry (YOLOv8n and PaliGemma 2 3B);
   - the host for the Gemini agent runners of our causal-hint experiment;
   - a DAgger round on the small model.

   One FR8-owned queue packed all of it onto **9 instances**, with an on-instance reaper on each.

## 2. Timeline: idea → prototype

| time | where | what |
|---|---|---|
| Sat 02:24–08:17 | [FR8] V100 | **v1**: SFT of Qwen2.5-1.5B LoRA on solver episodes (J4, job 44397). 450 steps, 14.3M tokens, 2.82 h. |
| Sat 14:36 | [FR8] V100 | **v2**: dense-window SFT (job 44410), 5 h. Held-out eval: learned *when* to accuse, not *whom*. |
| Sat 15:55–22:40 | [Mac] + [FR8] | **v3** designed: decision-point GRPO from v2 with an anti-collapse kit, verified on CPU. Seed 1 started on an FR8 V100 at about 78 s/step. Seed 0 stayed queued: no FR8 GPU was free. |
| 22:40 | [Verda] | No A100, A6000, L40S or RTX6000 Ada on-demand capacity in FIN-01/02/03. Took the **H100 80GB on-demand** (`3bb74f5a`, FIN-02, €4.74/h). |
| 22:46–23:32 | [Verda] | Created. Three setup failures (§6), then v3-4k seed 0 started. |
| 00:05 | [Verda] | Step-140 watcher verdict **IMPROVING**: valid-only gain vs the solver −0.647 → −0.556 (+0.091, pooled SE .050). Entropy flat at 1.10, so no collapse. |
| 00:15–00:24 | [Verda] | Cap raised $30 → €100 → €300 (Silas). An H100 **spot** appeared and v3-8k seed 2 started on it. v3-8k seed 1 runs on an A100 spot. |
| 00:16–00:25 (22:16–22:25Z) | [Verda] | Meta glasses YOLOv8n FieldSpotter, 80 epochs, shared on the H100 at no extra cost. |
| 00:49 | [Verda] | Gemini J1-lite: **vLLM serving Qwen3-14B bf16** on an A100 spot, with the Canary in-process runner as the client. vLLM failed to start: the new vLLM rejected `--rope-scaling`. The box sat idle until 03:10 (§7). |
| 01:01–01:08 | [Verda] | Extra held-out eval box (A100 on-demand). Then v3-8k seed 3 on a second A100 on-demand. |
| 01:30 | [Verda] | **v3-4k s0 training done: 609 GRPO steps in 2.0 h.** |
| 01:35–02:12 (23:35–00:12Z) | [Verda] | Meta glasses PaliGemma 2 3B LoRA, shared on A100 `f4378173`. |
| 02:17 | [Verda] | Backup base eval on A100 `18acfa5d`, because FR8 SSH was down. |
| 02:39 | [Verda] | v3-4k s0 held-out eval: **−0.103 ± 0.081 (n=90), +0.306 ± 0.136 vs v2 (paired)**. v3-4k seed 1 replicate starts on an A100 spot. |
| 02:58 | [Verda] | X1 causal-hint runners (Gemini via OpenCode) hosted on `18acfa5d`. No Verda CPU instance was free in any region. |
| 03:02 | [Verda] | X2 DAgger box: A100 40GB on-demand `e9ea8b2e`. |
| 03:08 | [Verda] | Spot A100 `714d8144` (v3-4k s1) **preempted** about 30 min in: no result. Steps so far: 8k s0 167, 8k s1 370, 8k s2 619, 8k s3 211. **€46.02 spent.** |
| 03:10 | [Verda] | J1 restarted with `--hf-overrides` for YaRN 131k. |
| ~07:30 | [Verda] | Reapers delete every instance (the X2 box at 08:00). Final rows land in §4. |

## 3. Verda products used, and why (Fit)

| product | what we ran on it | why this product |
|---|---|---|
| **GPU instance, on-demand: H100 80GB** (1H100.80S.32V) | v3-4k s0 GRPO + held-out eval, then v3-8k s0. Shared with the Meta YOLOv8n run. | The only ≥ 40 GB card with capacity at 22:40. GRPO is generation-bound: 8 samples × 2 prompts per step. H100 = **12 s/step vs 78 s/step on the FR8 V100 (6.5×)**, same code, data and hyperparameters, 83% GPU utilisation. On-demand, so the 2 h run could not be preempted the night before the deadline. |
| **GPU instance, spot: H100 80GB, A100 80GB** | v3-8k seeds 1 and 2, the v3-4k seed 1 replicate, and the J1 open-weight agent | Replicates and side experiments can survive a preemption: we would lose one seed, not the headline. Spot cost **€1.08/h for an A100** vs €2.16/h on-demand, and **€2.37/h for an H100** vs €4.74/h. |
| **GPU instance, on-demand: A100 80GB / 40GB** | Extra held-out eval (n 82 → 172 for v2), backup base eval, v3-8k s3, DAgger box | Evals gate the headline numbers, so they ran on-demand. FR8 V100s were held by other jobs, and FR8 SSH went down at about 02:00. |
| **Self-hosted open-weight serving** (vLLM on a GPU instance) | Qwen3-14B bf16 behind an OpenAI-compatible endpoint, driving `canary.agents.play` on 10 hard + 10 medium dev seeds (`fr8/verda/j1_run.sh`) | An open-weight point next to the Gemini rows, under our control: same tool-call parser, 131k context with YaRN, prefix caching. The weights load from `/dev/shm` because the instance's 48 GB disk can't hold model + vLLM. |
| **Agent hosting** (a GPU box used as a CPU host) | X1's Gemini OpenCode runners: node 22, opencode 1.19.5, ≤ 8 parallel | Verda CPU instances had no capacity in any region at 02:58. The base-eval A100 box has 22 vCPU and the eval uses about 1, so the runners rode along at no extra cost. |

**Not used tonight:**
- **Verda Inference API / Nemotron endpoint.** Our `.env` only holds cloud-instance client credentials, and the CEO cancelled the task. That is why the open-weight agent is self-hosted (above), and it is the first item in the scale path (§7).
- **Instant Clusters, batch jobs and auto-scaling containers.** Also scale-path items.

## 4. Small model before/after (the tiebreaker)

**Eval:** the model plays full **held-out** Canary episodes alone (`train.eval_hf`, greedy, call cap 120). Seeds 800000+, never used in training. Score is in [−1, 1]:
- correct accusation is positive;
- wrong accusation is −1;
- abstaining is 0.

GRPO training scores actions by letting the solver finish the episode; evaluation never does. Source: `fr8/analysis/out/ws4_table_v3s0.md` (justSilas-fr8).

| model | trained where | evaluated where | n (held-out episodes) | score ± 95% CI | accused | correct | abstain | Δ vs v2 (paired n) |
|---|---|---|---|---|---|---|---|---|
| base Qwen2.5-1.5B-Instruct | – | [FR8] V100 (backup run on [Verda] A100 `18acfa5d`: pending) | 16 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | +0.625 ± 0.245 (16) |
| v1 SFT (J4) | [FR8] V100 | [FR8] V100 | 12 | −0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | +0.333 ± 0.279 (12) |
| v2 SFT, dense windows | [FR8] V100 | 82 [FR8] V100 + 90 [Verda] A100 `68bbe201` | 172 | −0.457 ± 0.086 | 0.55 | 0.05 | 0.45 | – |
| **v3-4k s0** GRPO, 609 steps | **[Verda] H100 `3bb74f5a`** | [Verda] H100 | 90 | **−0.103 ± 0.081** | 0.17 | 0.03 | 0.83 | **+0.306 ± 0.136 (82)** |
| v3-4k s1 (replicate) | [Verda] A100 spot `714d8144` | – | **lost: spot preempted ~30 min into training** | – | | | | |
| v3-8k s0 | [Verda] H100 `3bb74f5a` | [Verda] | pending | pending | | | | |
| v3-8k s1 / s2 | [Verda] A100 spot / H100 spot | [Verda] | pending | pending | | | | |
| v3-8k s3 | [Verda] A100 on-demand | [Verda] | stops ~05:00 to free the box for DAgger: reported as "stopped at step N", not a seed result | | | | | |
| v3 s1 (4k) | [FR8] V100 (job 44572) | [FR8] | pending | pending | | | | |
| DAgger round 1 (from v3-4k s0) | [Verda] A100 | [Verda] | pending (`docs/reports/dagger.md`) | pending | | | | |

**Reading it honestly:**
- **v3 recovered most of v2's loss.** It is +0.31 vs v2 on 82 paired held-out episodes, mostly by learning to abstain instead of accusing wrongly. Hard-tier wrong accusations fell from 0.60 to 0.03.
- **It does not yet beat the base model**, which abstains on every episode and scores 0: −0.062 ± 0.122 paired, n=16.
- The diagnosis, from the X2 brief:
  - v3 learned *whom* to accuse on training states: forced-accusation whom-accuracy rose from 0.19 to 0.89.
  - Those states were the last steps of *solver* trajectories, where the evidence was already gathered.
  - On its own held-out trajectories, whom-precision is 3/16 ≈ 0.19.
- DAgger (rolling out v3 and labelling its *own* states with the solver) is the fix being tested now, on Verda.

## 5. FR8 freighter vs Verda (labelled)

| workload | where it ran | hardware | measure |
|---|---|---|---|
| v3 GRPO step time (group 8 × 2 prompts, 4k ctx, fp16) | **[FR8]** | V100 16/32 GB | ~78 s/step; seed 1 reached ~250 steps in 4 h |
| same code and data | **[Verda]** | H100 80GB | **~12 s/step (6.5×)**; seed 0 reached **609 steps in 2.0 h** |
| v1 SFT (J4) | [FR8] | V100 | 450 steps, 14.3M tokens, 2.82 h (5% of an epoch) |
| v2 SFT (dense windows) | [FR8] | V100 | 5 h, 53.3M tokens (≈ 0.47 epoch) |
| v2 held-out eval | [FR8] V100 n=82 + [Verda] A100 n=90 | | pooled n=172 |
| Momin's Gemini agent fleet: integrity probes | [FR8] Slurm CPU partition | CPU | 637 replayed episodes + 18 Harbor ledgers rescored, 0 mismatches (`EXPLOITS.md` #45) |
| Difficulty recalibration (J1) | [Mac] local, plus a bonus copy on [FR8] (job 43872, 306 tasks) | CPU | 153k episodes |
| SFT data (J3) | [Mac] | CPU | 20k train + 2k val solver episodes |
| Frontier agent runs (Gemini, GPT, Grok) | [Mac] (API calls; FR8 compute nodes have no internet) | API | **1,057 replay-verified episodes** committed in `data/runs/committed/`, including references |
| Open-weight agent (Qwen3-14B, vLLM) | **[Verda]** A100 80GB spot | A100 | 10 hard + 10 medium dev seeds; result pending from FR8 |
| Meta glasses YOLOv8n | **[Verda]** H100, shared | H100 | 80 epochs in 513 s, ≈ 0.15 GPU-h; mAP@0.5 0.572, strength precision 96.8% (n=348) |
| Meta glasses PaliGemma 2 3B LoRA | **[Verda]** A100, shared | A100 | 2 epochs in 29 min, ≈ 0.65 GPU-h; strength recall 91.4% vs YOLO 65.6% (n=348) |

## 6. Cost and GPU-hours [Verda]

All prices come from the Verda API at creation (€). The **upper bound** assumes every instance runs until its reaper deadline. Instances that finish early are deleted early, so the actual cost can only be lower.

| instance | type | €/h | start → reaper | GPU-h (max) | € (max) | workloads |
|---|---|---|---|---|---|---|
| `3bb74f5a` | H100 80GB on-demand | 4.7421 | 22:46 → 07:30 | 8.73 | 41.41 | v3-4k s0, v3-8k s0, Meta YOLOv8n |
| `ac58df04` | A100 80GB spot | 1.0794 | 00:00 → 07:30 | 7.50 | 8.10 | v3-8k s1 |
| `dbd083ca` | H100 80GB spot | 2.3711 | 00:24 → 07:30 | 7.10 | 16.83 | v3-8k s2 |
| `924e81d8` | A100 80GB spot | 1.0794 | 00:49 → 07:30 | 6.68 | 7.21 | Gemini J1-lite, Qwen3-14B vLLM |
| `68bbe201` | A100 80GB on-demand | 2.1589 | 01:01 → 07:30 | 6.48 | 14.00 | extra held-out evals (v2, v3-4k s0) |
| `f4378173` | A100 80GB on-demand | 2.1589 | 01:08 → 07:30 | 6.37 | 13.74 | v3-8k s3, Meta PaliGemma 2 |
| `18acfa5d` | A100 80GB on-demand | 2.1589 | 02:17 → 07:30 | 5.22 | 11.26 | backup base eval, X1 agent runners |
| `714d8144` | A100 80GB spot | 1.0794 | 02:39 → ~03:10 (preempted) | ~0.5 | ~0.54 | v3-4k s1 (lost) |
| `e9ea8b2e` | A100 40GB on-demand | 1.5373 | 03:02 → 08:00 | 4.97 | 7.64 | X2 DAgger |
| **total** | 9 instances (2 H100, 7 A100) | | | **≤ 53.5 GPU-h** | **≤ €120.7** | cap €300 |

- **Measured spend:** the balance went from €200.00 (start) to €195.25 at 23:37, €191.71 at 00:20 and **€153.98 at 03:08 (€46.02 spent)**. The FR8 projection is €115–125 by the 07:30 reapers.
- **Final measured spend:** pending (from the account balance after the last reaper).
- **Cost per result:** the headline v3-4k s0 run cost about **€17** on the on-demand H100: 22:46 → 02:20, including setup failures, 2.0 h of training and the n=90 eval.

## 7. What didn't work (honest log)

- **Capacity scarcity.**
  - All night, Verda on-demand and spot capacity for A100, A6000, L40S and RTX PRO 6000 in FIN-01/02/03 was near zero. FR8 polled the API and launched queued work whenever a card appeared.
  - About **15–20 create attempts failed** between 22:40 and 03:00 (A100, H100, V100 and CPU, in all 3 FIN regions), from the FR8 session's logs; this count is not programmatic.
  - A V100 for the Meta glasses YOLO run failed to create (no spot or on-demand capacity), so Meta shared the H100 instead.
- **Spot preemption:** A100 spot `714d8144` (the v3-4k seed 1 replicate) was reclaimed about 30 min in, so the 4k row has one seed. This is the trade we chose: replicates go on spot, headline runs on on-demand.
- **vLLM flag drift (about 1 h 50 min idle on a paid A100):** the freshly installed vLLM rejected `--rope-scaling`. The J1 runner waited 30 min, then exited around 01:20, and our watcher didn't notice until 03:10. Fixed with `--hf-overrides`; the runner now exits as soon as vLLM dies. Cost about €2.
  - No CPU instance was free in any region for agent hosting; X1's runners ride on an A100 box.
  - The planned open 7B (S7) was dropped for lack of capacity.
- **Setup failures on the first H100**, about 50 of its first 60 minutes idle or failed (≈ €4):
  1. transformers 4.57 could not read the v2 tokenizer saved by 5.16. We pinned FR8's exact stack: torch 2.5.1, transformers 5.16.1, peft 0.20.0.
  2. `uv venv` refused to overwrite an existing venv. Our watcher missed it because of a case-sensitive grep. Fix: `--clear`. About 20 min lost.
  3. The solver continuation crashed on an off-distribution state (empty posterior) at step 55. The reward was made crash-proof (commit `0f397ce`).
  4. A zsh `$IP:a` modifier sent one upload to a local directory; fixed with `${IP}`.
- **The RTX PRO 6000 (Blackwell) was skipped:** it needs a newer torch than our pinned 2.5.1.
- **Disk:** the 48 GB root disk could not hold Qwen3-14B plus vLLM, so the weights load from `/dev/shm`.
- **Reaper gap:** the laptop's memory-pressure killer took out the Mac-side reaper, so reapers now run on each instance. For about 2 minutes during a swap, no reaper was armed.
- **Co-tenancy cost:** the Meta YOLO run slowed v3 s0 by about 12% for about 10 min. A PaliGemma batch-8 attempt OOM-exited at about 69 GB; it was capped at 0.58 of the card, and v3-8k s3 was unaffected.
- **The result itself:** GRPO beat v2 but not the always-abstain base (§4). We report that rather than an unpaired best seed.

## 8. Path to scale

1. **Instant Clusters for multi-node GRPO.**
   - Our GRPO is generation-bound and embarrassingly parallel per state: 8 rollouts per state, each finished by the CPU solver.
   - On a multi-node H100 cluster, vLLM workers generate, CPU workers replay with the solver, and one trainer node updates the LoRA.
   - That turns ~1,200 rollouts per hour on one H100 (609 steps × 16 samples / 2 h ≈ 4.9k samples in 2 h) into **thousands of rollouts per minute**, which makes full-trajectory on-policy RL (the DAgger lesson) affordable.
2. **Batch jobs for nightly eval sweeps.**
   - Each held-out eval is a fixed command (`train.eval_hf`, n=30 per tier) with deterministic seeds and replay-verified outputs.
   - Tonight we hand-placed evals on boxes; as nightly batch jobs they would rerun every new adapter and every new environment version against base/v1/v2/v3 and the frontier rows.
3. **Auto-scaling containers: Canary as eval-as-a-service.**
   - Canary already ships as an MCP environment and a Harbor task, with HMAC-signed ledgers and replay verification.
   - Packaged in an auto-scaling container, labs point their agent at an endpoint, play judge-seed episodes, and get a signed, replayable score.
   - It scales to zero between runs, and the data stays in EU data centres.
4. **Inference API for open-weight agents.**
   - Replace tonight's self-hosted vLLM with the Verda Inference API, or the Nemotron endpoint, for open-weight investigator baselines on every tier.
   - That needs no GPU setup and no 48 GB-disk workaround.
   - The tuned small model can be served from the same API for the demo.

## 9. Reproduce

- **Verda scripts** (branch `justSilas-fr8`):
  - `fr8/verda/run_v3.sh`: v3 GRPO + held-out eval on one GPU, e.g. `CTX=8192 TAG=verda-8k-s0 SEED=0 HOURS=3 EVAL_MIN=75`;
  - `fr8/verda/evals_run.sh` and `fr8/verda/evalbase_run.sh`: extra held-out evals;
  - `fr8/verda/j1_run.sh`: vLLM Qwen3-14B + Canary runner;
  - `fr8/verda/self_reaper.py`: the on-instance cost reaper.
- **Artifacts:**
  - `data/fr8/verda/h100-3bb7/` (curve, train summary, eval episodes);
  - `data/fr8/verda/evalbox-68bb/`;
  - `data/fr8/verda/instances-2337.txt` (CLI capture).
- **Table:** `python fr8/analysis/ws4_table.py` writes `fr8/analysis/out/ws4_table_*.md`.
