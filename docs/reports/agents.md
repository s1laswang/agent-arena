# HEAD-AGENTS report (branch `justSilas-agents2`)

Lane (per NEXT-LEVEL lane update): WS3 RL mole (with Momin) → Mole Forge on v1.4 hard with Gemini → hint ablations.
The Gemini failure analyst is dropped here (owned by the Gemini CEO's Atlas). gemini-4-carbon headline measurement is the
CEO engineer's; not duplicated.

## 15:xx status
- Done (verified: `uv run --extra dev pytest tests/test_rl_mole.py tests/test_forge_track.py` → 11 passed)
  - `canary/forge/rl_mole.py`: numpy MLP mole (MoleView features → leak selector × frame selector, same vocab as the
    Mole DSL, plugs into `Env(mole_strategy=...)`, samples with the env RNG → deterministic). REINFORCE on
    J = solver − max_k investigator (k ∈ grok_tactics, heuristic, hinted_heuristic; softmax-weighted max), with a
    Lagrange multiplier enforcing solver accuracy ≥ 0.75 (+0.05 margin). Train seeds 100000+, eval seeds 200000+.
  - `hard_rl` judge track (`rules.TRACKS`, `forge_track.hof_path(track)`, own instruction text); loads
    `data/rl_mole/hall_of_fame.jsonl` (rows with an `rl_mole` policy). NOT added to `make reproduce` (CEO's call).
  - `train/grpo_mole.py` (ready for FR8, GPU path untested): prompts = real MoleView snapshots (seed, day) from
    solver episodes; completion = one DSL action JSON; reward = counterfactual replay of solver + 3 investigators with
    that action on day d (regret − 0.5 if the solver misses, −1 if invalid). Backends: plain torch+peft GRPO (default,
    needs only pytorch-volta) or TRL. `--dry-run` verified on CPU: reward varies within 100% of groups.
  - `fr8/grpo_mole.sbatch` (+ `SMOKE=1`), `fr8/grpo_mole_setup.sh` (login node: model download, optional TRL).
- In progress: RL mole training run (150 iters × 64 seeds, Mac CPU) → curve + frozen policies in `data/rl_mole/`.
- For FR8 head: `bash fr8/grpo_mole_setup.sh` on the login node, then `sbatch --export=ALL,SMOKE=1 fr8/grpo_mole.sbatch`,
  then the real run (`SIZE=0.5B STEPS=200`, 1 GPU, 8 CPUs). Untested on GPU.
- For Momin: no overlap found on `momin` (no RL mole there). Proposed split: I own `rl_mole.py`/`hard_rl`; you take the
  Gemini-on-mole side and the GRPO run with FR8. Leave notes in this file.
