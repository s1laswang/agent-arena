# Compute plan until 09:30 (Sun 15 Nov, ~00:00; revised 00:25)

**Revision 00:25 (reality check):** Verda has had near-zero capacity all night, so the 4 A100s don't exist.
- Held: H100 (v3-4k s0, then v3-8k s0) and one A100-80G spot (v3-8k s1).
- S7's 7B pipeline runs on 3 FR8 V100s *if Momin frees them* (Silas is asking). Otherwise S7 is dropped and the tiebreaker is v3-4k plus v3-8k (2 seeds).
- Meta's A100 waits for Verda capacity.
- The tables below are the original plan.

## The one result: "an open 7B model, trained on Canary experience overnight, versus Gemini on the judged tier"
The chart: v1.4 hard, held-out seeds, n=30 each, every episode replay-verified.

| agent | where it ran | score |
|---|---|---|
| Qwen2.5-7B-Instruct, base | A100 (vLLM) | measured |
| Qwen2.5-7B + SFT on full-history solver play | A100 | measured |
| Qwen2.5-7B + expert iteration (its own best episodes) | A100 | measured |
| gemini-4-carbon (OpenCode) | API | 0.322 (65% of solver) |
| reference solver | CPU | 0.499 |

Why this is the breakthrough candidate:
- It is the tiebreaker, at a scale nobody else brings: a 7B model, full 16k-32k history, thousands of self-play rollouts on 4 GPUs.
- The v2 failure was diagnosed: the 1.5B model at 4k context accuses at the right time but at the wrong person, because the evidence is outside its window.
- A 7B model with the whole episode in context attacks exactly that.
- Win condition: 7B-trained > 0 with a CI excluding 0 (it beats its base, which scores 0). Stretch: it beats gemini-4-carbon. Either is honest; a null result is reported as a null.

## Gemini is essential (already real, and it gets sharper)
1. **Gemini is the frontier subject** whose failure we measure: committed runs and a failure analysis tied to decisions.
2. **Gemini is the adversary.** As the mole it found the canary trap's blind spot (4/4 vs the solver, arena mode). As a 100-attack red-team swarm it attacked our reward (0 exploits; one flag refuted at n=40).
3. **Gemini is the long-context analyst** over all ~1,000 committed trajectories (atlas).
4. **New: Gemini vs our trained open model, head to head** on the same seeds. It answers the question labs care about: can cheap environment experience close the gap to a frontier API model?

## GPU queue (FR8 session provisions; S7 builds and runs the pipeline; the Gemini side uses no GPUs)
Spot A100-40G about €0.85/h; H100 €4.74/h.

| slot | 00:30-02:30 | 02:30-05:00 | 05:00-07:30 | 07:30-08:30 |
|---|---|---|---|---|
| H100 (running) | v3-4k s0 train + eval | v3-8k train | v3-8k eval | deleted |
| A100 #1 | vLLM Qwen2.5-7B: base eval, v1.4 hard held-out n=30 | vLLM: expert-iteration rollouts (round 1, train seeds) | vLLM: eval EI-1 n=30 | final eval / spare |
| A100 #2 | vLLM Qwen2.5-7B: rollouts on train seeds (easy/medium) | vLLM: rollouts | eval SFT n=30 | spare |
| A100 #3 | SFT 7B LoRA, 16k ctx, on 3k full-history v1.4 solver episodes (generated on CPU) | SFT continues, then EI-1 SFT | EI-2 SFT (if EI-1 improved) | - |
| A100 #4 | **Meta glasses CEO**: PaliGemma 2 3B LoRA (~2 h), then a real-time endpoint until 11:00 (≤ 10 A100-h; Verda Track evidence) | Meta | Meta | Meta |

The third model family (an open-weight investigator) goes through the **Verda Inference API / Nemotron endpoint** (session S6), so it needs no A100. If that fails, the 7B base row already gives an open-model comparison.

Budget:
- 4 A100 × 8 h × €0.85 ≈ €27;
- H100 ≈ €42 (already approved);
- total ≈ €70-80, under a €150 cap.

Idle rule: any slot idle for 30 min gets the next eval item, e.g. more held-out n for the 7B, or the 7B on medium.

## The demo moment
A live leaderboard panel on the dashboard (Gemini side) reads `results/leaderboard_v14_hard.json`. The panel:
- shows the 7B model's held-out score climbing round by round (base → SFT → EI-1 → EI-2);
- shows it next to gemini-4-carbon and the solver;
- has error bars, plus the GPU-hours and euros behind each row.

Then the replay of hard seed 4: Gemini plants 2 canaries and does 29 interviews by day 5, while the solver catches the mole on day 5 with 7 canaries.

## Kill criteria
- 01:30: if vLLM + the tool-calling loop doesn't run end to end on 1 episode, R4 (the 32B agent) is dropped and A100 #4 joins the 7B rollouts.
- 05:00: if SFT-7B is ≤ base on 10 held-out episodes, skip EI-2 and spend the GPUs on n for the final eval.
- No result goes in the README without committed, replay-verified episodes.
