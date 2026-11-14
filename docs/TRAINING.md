# Training a small model on Blind Spot (outline, tiebreaker)

AfterQuery's tiebreaker: "a small model that improves after training". Nothing here needs a GPU
tonight; the data export and eval pieces exist and are tested.

## Why this environment is trainable

- **Verifiable reward**: 0/1 per day from final state only (`blindspot/verify.py`), plus dense
  diagnostics we can use for analysis but NOT as reward (tickets OK, hazards caught, EUR lost).
- **Unlimited fresh days**: a day is a pure function of the seed. Train on seeds >= 100, evaluate on
  0-49 (standard) and 0-29 (hard). Hazard and benign twins share wording, so memorising surface
  text does not help; the model has to learn the checks.
- **A demonstrator that only uses visible information**: the scripted oracle never reads hidden
  state, so its trajectories are legal demonstrations.

## Plan

1. **Baseline**: run the small model (e.g. Gemma 3 4B/12B via the Gemini API or locally, or
   Qwen2.5-7B-Instruct) as plain staff over MCP: `python -m blindspot.eval --agents <agent>
   --seeds 0-49 --repeats 3`. Expect near-autopilot behaviour: valid work done, hazards missed.
2. **SFT warm start** on reference trajectories:
   `python -m blindspot.export_sft --seeds 100-399 --out data/sft/oracle_train.jsonl`
   (OpenAI-style tool-calling messages, loads directly into TRL `SFTTrainer` / Unsloth). Add
   `--difficulty hard` for long-queue days. Optionally replace the oracle with successful
   Gemini-reference transcripts (they contain reasoning text, the oracle's do not).
3. **RL with the environment reward** (GRPO / RLOO, group of 4-8 rollouts per seed): reward =
   final-state reward. Because the reward is binary and all-or-nothing per day, use a curriculum:
   start on single-family days (`families=[fam, "ap_report"]`), then standard days, then hard.
   Keep the per-ticket score only for logging, so the trained policy cannot learn to farm
   partial credit.
4. **Evaluate** on held-out seeds and report: mean reward, pass^3, hazards caught per family,
   valid work done (to show it did not just learn to refuse), EUR lost.

## What "improves" should look like

| Metric | Before (plain staff) | After (expected direction) |
|---|---|---|
| Mean reward | low | up |
| Hazards caught | low | up |
| Valid work done | high | stays high (refusal is punished by benign twins) |
| EUR lost | high | down |

## Risks

- Oracle demonstrations are terse (read everything, then act). A model may learn the order of
  calls rather than the reason. Mitigation: mix in reasoning-bearing transcripts from the Gemini
  reference agent, and evaluate on hard days whose families appear in a different mix.
- Reward hacking during RL: every integrity baseline is a test (`tests/test_exploits.py`); rerun
  them against the trained policy's behaviours that look suspicious (many flags, many figures).
