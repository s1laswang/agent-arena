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
RESULTS_PENDING

## Cost
RESULTS_PENDING
