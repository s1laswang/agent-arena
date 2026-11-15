# X2: DAgger round 1 for the small investigator (Canary tiebreaker)

AfterQuery tiebreaker: "a smaller model that improves after training on the environment's experience".
Owner: session x2-dagger-a6. Code: `train/dagger.py`, `fr8/verda/x2_train.sh`, `fr8/verda/x2_eval.sh`.

## Diagnosis being fixed
v3-4k s0 (decision-point GRPO from v2, Qwen2.5-1.5B LoRA, H100, 609 steps) learned WHOM from evidence on its
training states (forced-accuse whom-accuracy .19 → .89) but held-out precision stayed .19 (3/16). Its GRPO states
were the last steps of SOLVER trajectories, where the solver had already gathered the evidence; in its own
episodes the evidence is never gathered. DAgger trains on the states the model itself reaches.

## Method (round 1)
1. **Expert.** `expert_action(instruction, tools_spec, history)`: the reference solver's next call from ANY
   agent-visible history. SolverPolicy is a phase machine whose queue comes from its own past calls, so it cannot be
   queried on a foreign history directly. The expert rebuilds the solver's daily loop from the history: day queue
   from the belief at the day's first `status` (list_documents, check_leak_feed, decoy searches, yesterday's access
   logs) → first item not yet done today; then the solver's accuse rule on the belief from everything seen (minus
   today's own canaries); else today's canary plan minus canaries already planted; then status → advance_day.
   **Check:** equals the solver's own call on 2,603/2,603 steps of 45 solver episodes (15/tier, TRAIN seeds).
   If the student never called `list_employees` (99/300 episodes), the expert labels `list_employees` at the first
   state only and otherwise acts with the (static, public) roster, so later labels stay informative.
2. **Rollouts.** v3-4k s0 merged into the base, served by vLLM 0.6.6 (fp16, prefix caching), 300 episodes on TRAIN
   seeds 170000–170099 × {easy, medium, hard}, 8k context, eval_hf's exact render/truncation/parse (invalid → status,
   cap 120 calls); 75% greedy, 25% T=0.7. 13 min on an A100-40.
   **Check:** prompt token ids identical to eval_hf's tokenizer path (hash over solver states, both venvs); greedy
   vLLM outputs identical to HF eval on 5 probe states.
3. **Relabel.** Each episode is replayed into a fresh Env (0 result mismatches in 300 episodes) and the expert labels
   every state: 24,074 states, student agrees with the expert on 43%.
4. **SFT.** LoRA SFT continuing the v3-4k s0 adapter (r16), 8k context, loss only on the expert's assistant turn
   (prompt = eval_hf's prompt for that state). Selection: every disagreement and every key state (expert
   plant_canary/accuse, or student accuse), 10% of agreeing routine states, at most 2 copies of the same non-key
   correction per (episode, day); key states weighted 3×; 4,000 examples (25.7M tokens), 1 epoch, lr 1e-4,
   grad-accum 16 (250 steps). Labels: plant_canary 1,595, search_messages 922, read_access_logs 421,
   list_documents 371, status 255, check_leak_feed 174, accuse 159, list_employees 62, advance_day 41.
5. **Eval.** eval_hf (greedy, KV reuse, call cap 120), held-out seeds 0–29/tier, ONE shared world secret for every
   X2 eval (fingerprint 1ca0c2a64d), so DAgger vs v3-4k s0 at the same inference context is seed-paired.
   **Verified:** the step-0 `list_employees` results are identical across DAgger, v3-4k s0 @8k and v3-8k s0/s3
   (50/50, 35/35, 36/36 shared (tier, seed)), and 0/38 match the older own-secret v3-4k s0 run.
   **Generation cap 256 (not 96).** DAgger learned the solver's `plant_canary` calls, whose full assignments (one
   entry per employee) run past eval_hf's default 96-token cap. They were truncated and parsed as invalid (probe:
   4/4 invalid calls were cut-off plant_canary; 38/59 calls invalid in one episode). The solver's own hard-tier
   plants exceed 96 tokens 64% of the time; earlier models never emit more than ~81 tokens (valid calls ≈1.00), so
   the cap never showed. All DAgger rows AND their paired v3-4k s0 baselines use `--max-new-tokens 256`. For
   v3-4k s0 @8k the cap barely matters: cap 96 vs cap 256 on shared worlds, paired Δ +0.052 ± 0.196 (n=43).

## Finding on the way: inference context flips v3-4k s0's behaviour
Same adapter (v3-4k s0, trained at 4k), greedy, only the inference context changes. vLLM rollouts on TRAIN seeds
(no held-out seed touched; greedy subset):

| inference ctx | tier | n | score | accused | correct/accused | valid calls |
|---|---|---|---|---|---|---|
| 4k | easy | 30 | −0.737 | 0.87 | 2/26 | 0.96 |
| 4k | medium | 30 | +0.000 | 0.00 | 0/0 | 1.00 |
| 4k | hard | 30 | +0.021 | 0.03 | 1/1 | 0.90 |
| 4k | all | 90 | −0.239 | 0.30 | 3/27 | 0.95 |
| 8k | easy | 76 | −0.485 | 0.64 | 7/49 | 0.99 |
| 8k | medium | 74 | −0.793 | 0.89 | 4/66 | 1.00 |
| 8k | hard | 86 | −0.735 | 0.76 | 1/65 | 0.95 |
| 8k | all | 236 | −0.672 | 0.76 | 12/180 | 0.98 |

The 4k pattern matches the held-out 4k eval of the same adapter (medium 0.00 accused, hard 0.03), so the vLLM
pipeline reproduces eval_hf. Held-out confirmation with eval_hf at 8k (shared secret, seeds 0–29/tier, cap 96):
**−0.716 ± 0.105, n=90, accused 0.78, whom 3/70**, vs −0.103 ± 0.081 at 4k. The same adapter goes from almost
never accusing to accusing nearly always, wrongly, when it sees more history. This matches v3-8k s1's over-accusing
(accused .94). So any 8k row must be compared with an 8k baseline: context is a factor, not a training effect.

## Results
**Partial n: data lost at box deletion (incident, below).** Each eval process plays its seeds in order, so what
survives is the complete episodes for the first seeds of each process (3 processes per model, seed idx 0–9, 10–19,
20–29); no episode was selected by outcome or length. Paired comparisons use the (tier, seed) pairs both runs
completed on the shared worlds.

**Verdict: honest null.** DAgger round 1 does NOT beat the base (0) and does not beat v3 at a significant level.

Three numbers (CEO framing):
1. **DAgger alone** (trained 8k, inference 8k, cap 256): **−0.542 ± 0.214, n=50**; accused 0.92, correct 0.20,
   abstain 0.08; whom-precision **10/46 = 0.22** (Wilson 0.12–0.36). Below the base (0.000 ± 0.000, n=36):
   two-sample Δ −0.542 ± 0.214.
2. **Paired vs v3-4k s0 at the same inference context** (8k, cap 256, shared worlds): **Δ +0.242 ± 0.304 (n=43)**;
   v3-4k s0 @8k on the same worlds: −0.754 ± 0.177, whom 4/40 = 0.10 (0.04–0.23). By tier: easy +0.098 ± 0.701
   (16), medium +0.471 ± 0.424 (14), hard +0.174 ± 0.279 (13). All CIs include 0.
3. **Two-sample vs v3-4k s0 as reported** (trained 4k, inference 4k, n=180, −0.147 ± 0.063): Δ **−0.395 ± 0.223**.
   At 4k inference DAgger is level with v3-4k s0: −0.101 ± 0.112 (n=41) vs −0.094 ± 0.103 (n=32), paired Δ
   −0.031 ± 0.139 (n=32); both mostly abstain (0.85 / 0.91).

What changed and what did not:
- **Gathering in its own states improved on TRAIN-distribution states**: on its own rollouts DAgger r1 agrees
  with the solver expert on 68% of states (152 episodes, TRAIN seeds 180000+), vs 43% for v3-4k s0 (300 episodes).
  Held-out whom-precision at 8k also doubled (0.10 → 0.22, overlapping CIs).
- **The commit decision did not improve.** DAgger at 8k still accuses in 92% of episodes and earlier than v3
  (median accusation at call 31 / day 3.9 vs call 57 / day 6.2), so the extra precision is spent on premature
  accusations. Only 159 of 4,000 SFT targets were `accuse` and the "don't accuse yet" signal is only implicit (the
  expert's alternative call at the student's accuse states); one epoch at lr 1e-4 did not override the 8k
  over-accusing inherited from the start adapter.
- The 8k-trained GRPO seeds split the same way (s0/s2 abstain, −0.06/−0.05; s1/s3 over-accuse, −0.78/−0.79),
  so over-accusing at 8k is a property of these adapters at long context, not of DAgger.

Round 2 was prepared but not evaluated: round 1 did not meet the "beats v3" gate, and its SFT (on box 1, shared
with 6 eval processes, 56 s/step) could not have been evaluated by 07:30. Stopped by PID at step 1/72.

Tables: `fr8/analysis/out/x2_dagger_8k_paired.md`, `fr8/analysis/out/x2_dagger_4k_paired.md` (shared-secret,
seed-paired) and `fr8/analysis/out/ws4_table_x2_dagger.md` (all WS4 rows, two-sample, with whom-precision,
GPU-h, €). Run dirs: `data/x2/evals/` (cap 256 + the complete cap-96 v3-4k s0 @8k), `data/x2/evals-cap96/` (the
stopped cap-96 DAgger starts, for the truncation evidence only).

| model | train ctx / inference ctx / cap | n | score ± 95% CI | accused | correct | abstain | whom-precision | GPU-h | € |
|---|---|---|---|---|---|---|---|---|---|
| base | – / 4k / 96 | 36 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | – | 0 | 0 |
| v1 (J4 SFT) | 4k / 4k / 96 | 12 | −0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 0/3 | 2.82 (FR8 V100) | 0 |
| v2 (dense SFT) | 4k / 4k / 96 | 172 | −0.457 ± 0.086 | 0.55 | 0.05 | 0.45 | 8/94 = 0.09 | 5.0 (FR8 V100) | 0 |
| v3-4k s0 (GRPO) | 4k / 4k / 96 | 180 | −0.147 ± 0.063 | 0.21 | 0.03 | 0.79 | 6/38 = 0.16 | 2.0 H100 | 9.48 |
| v3-4k s0 | 4k / **8k** / 96 (shared) | 90 | −0.716 ± 0.105 | 0.78 | 0.03 | 0.22 | 3/70 = 0.04 | (same) | – |
| v3-8k s0 | 8k / 8k / 96 (shared) | 90 | −0.060 ± 0.054 | 0.08 | 0.01 | 0.92 | 1/7 | 3.0 H100 | 14.23 |
| v3-8k s1 | 8k / 8k / 96 | 90 | −0.777 ± 0.118 | 0.94 | 0.09 | 0.06 | 8/85 = 0.09 | 3.0 A100 spot | 3.24 |
| v3-8k s2 | 8k / 8k / 96 | 90 | −0.050 ± 0.049 | 0.07 | 0.01 | 0.93 | 1/6 | 3.0 H100 spot | 7.11 |
| v3-8k s3 | 8k / 8k / 96 (shared) | 90 | −0.788 ± 0.117 | 0.96 | 0.09 | 0.04 | 8/86 = 0.09 | 3.0 A100 | 6.48 |
| v3-4k s0 | 4k / 8k / 256 (shared) | 43* | −0.754 ± 0.177 | 0.93 | 0.09 | 0.07 | 4/40 = 0.10 | (same) | – |
| **DAgger r1** | 8k / 8k / 256 (shared) | 50* | **−0.542 ± 0.214** | 0.92 | 0.20 | 0.08 | **10/46 = 0.22** | +1.15 A100-40 (3.15 incl. v3-4k s0) | +1.77 (11.25) |
| v3-4k s0 | 4k / 4k / 256 (shared) | 32* | −0.094 ± 0.103 | 0.09 | 0.00 | 0.91 | 0/3 | (same) | – |
| **DAgger r1** | 8k / 4k / 256 (shared) | 41* | −0.101 ± 0.112 | 0.15 | 0.02 | 0.85 | 1/6 | (same adapter) | – |

\* partial n (incident). GPU-h/€ = training only (DAgger: vLLM rollouts 0.22 h + SFT 0.93 h on the A100-40 at
€1.5373/h; "incl." adds the v3-4k s0 start adapter). FR8 V100 hours have no marginal €.

## Cost
- X2 training: 1.15 A100-40 GPU-h, €1.77 (rollouts 13 min, SFT 55.5 min). With the v3-4k s0 start: 3.15 GPU-h, €11.25.
- X2 evals and checks: box 1 68bbe201 (A100-80, €2.1589/h) from 03:35; box 2 e9ea8b2e (€1.5373/h) from 03:02,
  both until their reapers (07:30 / 08:00). This includes idle time after ~06:15 caused by the incident below.
  Exact per-box € is in FR8's final ledger (`fr8/verda/README.md`, total €104.46 for all Verda work).

## Incident: final eval outputs lost
I said I'd copy everything off both boxes by 07:00. I did not: my background waiters didn't wake this session, so
it sat idle from ~05:40 until 08:51, after both reapers had deleted the boxes. Lost: the remaining
~40 episodes per model of the four cap-256 evals (they were running normally; whether they finished is unknown),
the 152 round-2 rollouts' later analysis copies, and the merged models. Kept (pulled ~05:35): the run dirs above,
all 300 round-1 rollouts and labels, the 4k/8k dev rollouts, the DAgger adapter (`data/x2/dagger-r1/lora`,
weights not committed) and its train log. Lesson: pull partial results on a fixed schedule while a run is going,
not only at the end, and never rely on a single waiter for a hard deadline.

## Reproduce
```
python -m train.dagger selftest --n 15                                   # expert == solver, CPU
# on a GPU box (/root/x2): v3-4k s0 merged into the base + the BASE config.json (see note), vLLM 0.6.6 venv
python -m train.dagger rollout --model MERGED --tokenizer BASE --out r1 --episodes 300 --max-ctx 8192
ADAPTER=v3-4k-s0-lora KEEP_AGREE=0.1 MAX_EX=4000 LR=1e-4 bash fr8/verda/x2_train.sh      # relabel + SFT
ADAPTER=dagger-r1/lora OFFSET=0 N=10 NEW=256 RUN=... bash fr8/verda/x2_eval.sh           # needs /root/x2/world_secret
```
Note: a PEFT merge saved by transformers 5.x writes `rope_parameters`, which vLLM 0.6 (transformers 4.47) ignores,
so it runs with the wrong rope_theta (~80% invalid calls at 3–8k tokens). Copy the base model's `config.json` into
the merged dir; afterwards vLLM matches HF greedy outputs.
