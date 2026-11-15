<!-- Full-length write-up; the one-page version is SUBMISSION.md. Every number is quoted from a committed file. -->
# Gemini agents you can trust: a real-time label reader for blind users, and the lab that measures and attacks agents

*Google DeepMind "Best Use of Gemini API", Junction 2026. Two codebases: HoldUp ([`junction-meta-glasses`](https://github.com/s1laswang/junction-meta-glasses), quoted at tag `gemini-quote-0515`) and Canary Lab (`canary/gemini/` in this repo). Model ids are as listed by the Gemini API on our key on 14–15 Nov 2026. When we request `gemini-3.5-flash`, the API serves **`gemini-3.6-flash`** (recorded per call), so this text says "3.6-flash".*

## Short version (≤ 600 chars)
⟨SHORT⟩

## 1. The problem
**For a user.** A blind or low-vision person holding a medicine box needs the label read aloud, hands-free, within seconds. The worst outcome is a confident wrong read; "I'm not sure, turn the box" is acceptable. That is a real-time, multimodal, safety-critical agent.

**For a builder.** Before an agent makes calls like that, the team must decide which model and how much thinking to buy, learn how it fails, and know whether their own test can be gamed. A benchmark gives one number per model and answers none of that. Answering it takes controlled experiments and an adversarial audit at a scale nobody does by hand.

Our entry is both halves: a product whose mechanism is the Gemini Live API, and a lab where Gemini measures and attacks agents.

## 2. How Gemini is integrated

### 2a. HoldUp, the product
All HoldUp facts are from its `GEMINI.md` and `eval/results/` at tag `gemini-quote-0515` (commit 542773b).
- **One Gemini Live session** (`gemini-3.8-live`): camera frames and voice in, native audio out, with five tools called mid-stream: `verify_label`, `find_item`, `add_medication`, `show_cue` (non-blocking) and `log_dose` (`server/src/live.ts`).
- **`verify_label`** is a schema-constrained `gemini-3.8-flash` read (`responseJsonSchema`) that returns a confidence per field, followed by a deterministic safety check against the user's medication list.
- **Speculative verify:** the server reads the sharpest new frame while the user is still asking, so the Live tool call is answered from cache.
- **Gemini as test author:** Gemini image models rendered 1,740 label images from 172 Gemini-written specs, each with ground truth, so safety can be counted.
- **Tests** (HoldUp README): server 288/288, web 323/323, 13/13 live smoke checks against the real API.

### 2b. Canary Lab, the proof
The Canary environment (an insider-threat RL environment scored against a Bayesian reference solver) is our separate AfterQuery entry. Canary Lab is the Gemini layer on top of it. Every call goes through one client that writes one log row per call (`canary/gemini/ledger.py`). ⟨USAGE_LONG⟩

| Role | Gemini capability used | Result (committed) |
|---|---|---|
| **Player: the Ladder** (`ladder.py`) | `thinking_level` as the only changed factor; function calling over 13 tools with thought-signature replay | ⟨LADDER_N⟩ paired episodes, 42 cells (6 models × thinking levels × 2 tiers), same worlds as the solver (`results/gemini/ladder.md`) |
| **Attacker: the Red-team Swarm** (`swarm.py`) | The whole repo in one long-context prompt (about 183k tokens), function calling against the env | 513 ledger-verified attacks (369 whitebox, 144 blackbox; 81 through the real MCP server): **0 verified exploits**. Detector recall on three reopened exploit families: 16/16 (`results/gemini/scale/swarm3/swarm.md`) |
| **Analyst: Jury, Atlas and Gallery** (`jury.py`, `atlas.py`, `gallery.py`) | Three models as independent blind judges with structured output; a 751k-token corpus in one explicit context cache; multimodal belief charts; embeddings | 6,975 blind judgments over 1,423 high-regret decisions: Fleiss κ 0.736, and 84.9% majority-vote agreement with the code's labels on the 403 tagged decisions (`results/gemini/scale/jury/jury.md`). One-pass blind discovery recovers 3 of 5 code-defined failure modes (`atlas_blind.md`). Explains the code-attributed failures (`atlas.md`, `docs/reports/failure_gallery.md`) |
| **Adversary: the arena mole** (`roles.py`) | gemini-4-carbon plays the mole live | Finds the canary trap's blind spot (§3.7) |
| **Infrastructure** (`gateway.py`) | Token-gated relay; record/replay | The showcase and 4 ladder episodes replay keyless (`make lab-replay`); the cross-provider control was recorded through it |
| **Demo only** | TTS (3.8-flash-tts), Live API (3.8-live) | Narration and a live commentator clip for the video. Not part of any Canary measurement |

## 3. What is innovative
1. **Calibrated abstention, measured** (HoldUp). Across the 1,740 images, **0 of 754 confident strength reads were wrong** (95% upper bound 0.4%), and calibration ECE is 0.022 (0.018–0.028) (over 4,406 answered fields per `eval/results/v1_results.json`). End-to-end silent unsafe reassurance was 49/4,730 = 1.04% (0.78–1.37%) and is 3/4,730 = 0.06% (0.02–0.19%) after the safety rules were tightened. That second figure is a re-score of the same reads with rules tuned on this set, so it is in-sample. A Gemini-built red-team set (32 attack families, 2,264 images; HoldUp `docs/EVAL.md`) found 199 silent unsafe outcomes (8.79%) before new guards and 13 (0.57%) after, also in-sample.
2. **Speculative verify** (HoldUp). Question to first audio is p50 2.1 s, p95 3.4 s over 26 Live sessions. The one run before the change took 5.8 s and was not logged.
3. **Thinking as a controlled variable on a solver-referenced benchmark** (`results/gemini/ladder.md`). Each cell has 9–40 paired seeds, so the 95% paired-bootstrap CIs are wide; read these as directions.
   - Pooled over 570 episodes from 6 models (bootstrap clustered by world: 63 (tier, seed) clusters), each step up in `thinking_level` adds **+16.3 [+7.6, +24.4] points** of the solver's score, +3.8 [+1.2, +6.4] points of accusation accuracy, and cuts premature-accusation regret by 0.079 [0.047, 0.111] per episode (`results/gemini/thinking_effect.md`). The effect is driven by the flash models (3.6-flash +30.6 [+11.6, +49.6], 3.8-flash +38.1 [+1.8, +76.8] per step); it is not distinguishable from zero for the gemini-4 models, and thinking *tokens* spent do not predict the gain within a model.
   - On hard, gemini-4-carbon at high thinking reaches 106% [94, 126] of the solver (n=10, $1.93 per episode, 10/10 correct). 3.6-flash is 87% [50, 147] at medium and 88% [51, 138] at high (n=40 each, $0.42–0.45, 73/80 correct): not distinguishable from the solver, with wide CIs.
   - 3.1-flash-lite scores below do-nothing in all 8 (thinking level, tier) cells. Across the 42 cells, 18 exclude solver parity, all of them below the solver.
   - Hosted Gemma 4 (gemma-4-31b-it via the Gemini API) is exploratory only (n=5).
4. **A cross-provider control on identical worlds** (`results/gemini/xprov.md`). ⟨XPROV_LONG⟩
5. **Gemini as a measured judge** (`results/gemini/scale/jury/jury.md`). Three Gemini models (gemini-4-hydrogen, gemini-4-argon, gemini-3.8-flash) each label every high-regret decision (solver regret ≥ 0.01) from a closed taxonomy, seeing only what the agent saw and said. Over 1,423 decisions from 801 episodes (6,975 judgments), the judges agree with each other at Fleiss κ 0.736 [0.711, 0.759] (episode-clustered CI [0.703, 0.765]). On the 403 decisions our code tags, κ is 0.885 [0.853, 0.915] and the majority vote matches the code's label 84.9% [81.0, 88.0] of the time (ECE 0.068). Recall is high for the two common tags (premature accusation 83.2%, uninformative canary 93.7%) and poor for the rare ones (over-restriction 20.8%, ignored delay 0 of 5). The decisions are pre-selected by solver regret, so this measures labelling, not unaided detection.
6. **A red team with a validated detector** (`results/gemini/scale/swarm3/swarm.md`; waves 1–2 alone are in `results/gemini/swarm.md`).
   - Gemini attackers read the full source (whitebox, about 183k tokens in one prompt) or only the agent's instructions and tools (blackbox) and attack the reward through tool calls. Scores come only from the server's ledger, and every correct accusation is audited against what the attacker had seen, so detective work is not mistaken for an exploit.
   - **513 ledger-verified attacks** (369 whitebox, 144 blackbox; 81 through the real MCP server; 12,865 tool calls) across easy, medium and hard: **0 verified exploits, 0 invariant violations**. Five attempts reached solver level on an accusation the evidence did not justify (for example a correct day-1 guess scoring 1.0). Each was re-run on fresh seeds and none held: attacker means −0.90, −0.77, −0.77 and +0.32 against solver means of +0.63 to +0.72. The fifth (w2b-008) was confirmed in-run (0.68 vs solver 0.49 on 4 seeds) because the audit under-credited exact set-intersection deductions; we fixed the audit (commit 34d73c3, with a test), re-executed the plan on the same seeds (0.16 vs 0.55) and report it as overturned, n=4.
   - **Detector recall (positive controls).** We reopened three families of known, closed exploits in a sandbox configuration, without editing environment code: regenerating public dev-seed worlds (8 attackers), held-out seeds failing open without a secret (4), and an unauthenticated ledger endpoint (4). **16 of 16 attackers found their target** (Wilson 95% CI [80.6, 100]) and 49 of 52 fresh-seed re-run episodes scored 1.0, so all 16 were confirmed. "0 exploits" comes from a detector shown to catch real ones.
7. **Gemini as adversary finds the canary trap's blind spot** (arena mode, not the judged environment; medium, n=4 dev seeds 0–3, run `roles-mole-20261114-185950`). The gemini-4-carbon mole was caught 0/4 times (solver score +0.00), against 4/4 (+0.63) with the default mole, by leaking only documents everyone had (48 leaks, 1 of them a canary): *"Leaking c1 is completely safe because all 20 employees received it."* Caveats: the env charges flat damage per leak whatever the distribution; the judged tasks use scripted moles; the real-world fix (per-recipient watermarking) is not built.

## 4. Why Gemini is essential: what happens when we swap it out
We answer this with substitutions we measured, and we say what is portable.
- **Swap the reader for an open model (HoldUp, 150 paired images, same prompts).** Gemma 4 31B is confidently wrong on a field twice as often: 38/528 = 7.2% (5.3–9.7%) vs 19/528 = 3.6% (2.3–5.6%), mostly allergens. It is the only model with a silent unsafe reassurance (2/377 vs 0/377; not significant on its own, p = 0.5). It takes 27.8 s per read against 3.2 s (Gemma's speed depends on our hosted quota). Strength reading itself ties at 46/59.
- **Swap the agent for GPT-5.5 (Canary, same worlds, same harness).** ⟨XPROV⟩
- **Take away the Live API (HoldUp).** One Live session carries camera, voice and tool calls. Without it the loop is speech-to-text → model → text-to-speech. We did not build that chain, so we report only what Live achieves: p50 2.1 s from question to first audio.
- **An open-weight data point (Canary).** ⟨J1_LONG⟩
- **Protocol facts our harness depends on** (`results/gemini/ablations.md`): with thought-signature replay stripped, the API rejected the first function-call replay in 10/10 episodes (Wilson 95% CI [72.2, 100]); with it, 0/628 calls failed. This is a correctness requirement of Gemini tool use that we implement, not an advantage over other providers. ⟨CACHE⟩
- **What is portable, stated plainly.** Other providers offer reasoning-effort dials, prompt caching and realtime APIs, and our harness ships an OpenAI backend (used for the GPT-5.5 runs above). We do not claim only Gemini could do this. We claim what this stack measurably delivered in one weekend: real-time multimodal tool use with calibrated abstention for HoldUp, and the cost per unit of competence shown above for agents.

## Honesty notes
- **Small samples.** Ladder cells have 9–40 paired seeds and the cross-provider control 8–11; every headline is worded by a CI gate.
- **The control uses the earlier v1.3 rules**, because those are the only worlds with committed GPT-5.5 episodes. It compares one non-Gemini frontier model at its default effort; no Anthropic model was run.
- **Logging.** Canary's usage rows are written by our own client and carry no API request id; the responses recorded for keyless replay do carry API response ids (⟨RECORDED⟩).
- **Atlas v1 is not blind.** Its corpus showed Gemini our code-computed regret tags, so only the blind re-run counts as discovery: 3 of 5 code-defined modes recovered (premature accusation 44%, ignored delay 2 of 2, budget waste 46%; uninformative canary and over-restriction 0%), 2 new modes named, 127 cited steps covering 21% of solver regret and 3.7% of high-regret steps, 12 of 16 quotes verbatim (`results/gemini/atlas_blind.md`). The Failure Gallery is an exact code decomposition; Gemini only names its categories. No human-agreement number is claimed.
- **HoldUp limits.** The 5.8 s "before" latency is one unlogged run. Its demo video is a browser simulation until the on-glasses run is logged. The in-sample re-scores above are not held-out results.
- **The AfterQuery gap depends on the harness.** Per `docs/reports/gap.md`, gemini-4-carbon on v1.4 hard via OpenCode over MCP (the judges' harness) scores 65% [24%, 98%] of the reference solver at n=30, and 72% [52%, 91%] luck-adjusted (graded by the solver's own posterior); in-process it scores 95% [62%, 140%]. This submission makes no further gap claim.

## Also on Gemini
- **Gemini teaches Gemma.** The Gemini-generated, ground-truthed label images trained a PaliGemma 2 3B LoRA: "strength visible" recall 91.4% [86.5, 94.6] vs 65.6% for YOLOv8n on n=348 held-out images. The two are not at one operating point (YOLOv8n precision 96.8% vs 89.9%). Not yet wired into the product ([`GEMMA.md`](https://github.com/s1laswang/junction-meta-glasses/blob/gemini-quote-0515/GEMMA.md)).
- **Valio Aimo** ([`docs/GEMINI.md`](https://github.com/s1laswang/junction-aimo-agents/blob/main/docs/GEMINI.md)): the buyer agent uses function calling on gemini-3.8-flash and escalates 5/34 steps (15%) to gemini-4-hydrogen at high thinking; gemini-embedding-2 drives catalog substitution; compacting re-sent tool results cut cost per order from $0.0822 to $0.0352 (−57%); 6 of 6 demo scenarios pass.

## Reproduce every headline number without a key
```bash
make setup && make reproduce          # environment, solver and baselines
make lab-replay                       # recorded Gemini runs replay through a local gateway
lab() { uv run --python 3.12 --extra dev --extra llm --extra plot "$@"; }   # works in bash and zsh

# Cross-provider control: table, chart and the three checks (same roster, replay, solver)
lab python scripts/with_tiers.py v1.3 -m canary.gemini.xprov --gemini-runs results/gemini/xprov_episodes.jsonl.gz --out /tmp/xprov
# ...and any control episode replays from the recorded API responses (score, accusation and steps identical)
lab python -m canary.gemini.with_gateway --replay results/gemini/xprov-replay/flash -- \
    python scripts/with_tiers.py v1.3 -m canary.gemini.ladder --models gemini-3.5-flash --levels medium \
    --tiers hard --seeds 0 --out /tmp/xprov-replay --run-name xprov-v13

lab python -m canary.gemini.thinking_effect --out /tmp/thinking          # pooled thinking-level effect
lab python -m canary.gemini.ladder_report --runs results/gemini/ladder_episodes.jsonl.gz \
    --ledger results/gemini/ladder_ledger.jsonl.gz --out /tmp/ladder     # ladder table and frontier chart
cp -R results/gemini/scale/jury /tmp/jury && lab python -m canary.gemini.jury --replay --out /tmp/jury   # jury: 6,975 judgments replayed, 0 calls
lab python -m canary.gemini.atlas --blind --replay                      # blind atlas
lab python -m canary.gemini.usage_union --out /tmp/usage_total.json     # the one usage total
lab pytest -q tests/test_gemini_lab_*.py                                # all Canary Lab tests
```
The red-team results are static files (`results/gemini/scale/swarm3/`); their hold-out attack sequences replay in `tests/test_gemini_lab_swarm_found.py`. HoldUp: see its README and `GEMINI.md` at tag `gemini-quote-0515`.

## Team
Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, with a Claude engineering team.
