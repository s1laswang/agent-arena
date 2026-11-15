# Gemini agents you can trust: a real-time label reader for blind users, and the lab that measures and attacks agents

*Google DeepMind "Best Use of Gemini API", Junction 2026 · two codebases, one thesis · every number comes from a committed file (sources in the tables) · `gemini-3.5-flash` is served as **gemini-3.6-flash**, so we say "3.6-flash" · full write-up: [SUBMISSION-LONG.md](SUBMISSION-LONG.md)*

**Short version (≤ 600 chars).** ⟨SHORT⟩

## 1. The problem
- **For a user:** a blind person holding a medicine box needs the label read aloud, hands-free, within seconds. A confident wrong read is dangerous; "I'm not sure, turn the box" is fine.
- **For a builder:** before an agent makes calls like that, you must know which model and how much thinking to buy, how it fails, and whether your own test can be gamed. One benchmark number answers none of that.

## 2. How Gemini is integrated
**HoldUp, the product** ([`junction-meta-glasses`](https://github.com/s1laswang/junction-meta-glasses/blob/gemini-quote-0515/GEMINI.md), pinned at `gemini-quote-0515`). One **Gemini Live** session (`gemini-3.8-live`) takes camera frames and voice in and speaks back, calling five tools mid-stream (`verify_label`, `find_item`, `add_medication`, `show_cue`, `log_dose`). `verify_label` is a schema-constrained `gemini-3.8-flash` read with a confidence per field, followed by a deterministic safety check. Gemini image models generated the 1,740 ground-truthed label images it is tested on.

**Canary Lab, the proof** (`canary/gemini/` in this repo; the Canary environment itself is our separate AfterQuery entry). One logged client drives Gemini in four roles on an insider-threat benchmark scored against a Bayesian reference solver:
- **Player:** six Gemini models × `thinking_level`, function calling over 13 tools, paired with the solver on the same worlds.
- **Attacker:** the whole repo (about 183k tokens) in one prompt, attacking the reward through tool calls.
- **Analyst:** 153 trajectories (751k tokens) in one explicit cache, finding failure modes without our labels.
- **Adversary:** Gemini plays the insider (arena mode, not the judged environment).

## 3. What is innovative
- **Calibrated abstention, measured at scale:** Gemini generates and ground-truths the eval set, so "never confidently wrong" is a number, not a hope.
- **Speculative verify:** the server reads the sharpest frame while the user is still asking, so the Live tool call returns from cache.
- **Thinking as a controlled variable:** `thinking_level` is the only factor changed, every cell is paired with the solver, and a CI gate words every headline. Pooled over 570 episodes, each step up in thinking level adds **+16.3 [+7.6, +24.4] points** of the solver's score, driven by the flash models (`results/gemini/thinking_effect.md`).
- **A red team proven by a positive control:** scores come only from the server ledger, and the detector is shown to catch a reopened real exploit.
- **A cross-provider control on identical worlds**, built from committed GPT-5.5 episodes at no extra cost.

## 4. Why Gemini is essential: what happens when we swap it out
- **Swap the reader for an open model (HoldUp, 150 paired images):** Gemma 4 31B is confidently wrong on a field twice as often (38/528 = 7.2% vs 19/528 = 3.6%), is the only model with a silent unsafe reassurance (2/377 vs 0/377, not significant on its own), and takes 27.8 s per read against 3.2 s. Strength reading itself ties (46/59 each).
- **Swap the agent for GPT-5.5 (Canary, same worlds, same harness):** ⟨XPROV⟩
- **Take away the Live API:** camera, voice and tool calls would become a speech-to-text → model → text-to-speech chain. On Live, question to first audio is p50 2.1 s (p95 3.4 s, n=26 sessions).
- **What is portable, stated plainly:** other providers also offer reasoning-effort dials, prompt caching and realtime APIs, and our harness has an OpenAI backend. We do not claim only Gemini could do this. We claim what this stack measurably delivers: real-time multimodal tool use for HoldUp, and the cost per unit of competence shown above for agents.

## Headline chart
![Same worlds: % of the reference solver vs cost per episode, Gemini vs GPT-5.5](../../results/gemini/xprov.png)
*Identical Canary v1.3 worlds; circles are Gemini, squares are GPT-5.5 (`results/gemini/xprov.md`). The v1.4 thinking-level frontier is in [`frontier.png`](../../results/gemini/frontier.png).*

## Results
| | Result | Source |
|---|---|---|
| **HoldUp safety** | **0 of 754** confident strength reads wrong across 1,740 images (95% upper bound 0.4%); calibration ECE 0.022 (0.018–0.028). Silent unsafe reassurance 49/4,730 (1.04%) → 3/4,730 (0.06%) after the safety rules were tightened (re-scored on the same reads, so in-sample). | HoldUp `GEMINI.md` at `gemini-quote-0515` |
| **Ladder** (⟨LADDER_N⟩ paired episodes, v1.4) | Hard: gemini-4-carbon at high thinking reaches **106% [94, 126]** of the solver (n=10, $1.93/episode); 3.6-flash reaches 88% [51, 138] at high and 87% [50, 147] at medium (n=40 each, $0.42–0.45): not distinguishable from the solver, with wide CIs. 18 of 42 cells exclude parity, all below the solver. | `results/gemini/ladder.md` |
| **Cross-provider control** (v1.3) | ⟨XPROV_ROW⟩ | `results/gemini/xprov.md` |
| **Red team (integrity)** | 100 ledger-verified attacks: **0 verified exploits, 0 invariant violations**; positive control caught 4/4. Best score not justified by evidence: 0.38 on hard; one attempt flagged in-run was overturned on review (n=4). | `results/gemini/swarm.md` |
| **Blind atlas** | Without our labels, Gemini recovers 3 of 5 code-defined failure modes and names 2 new ones; coverage is weak (127 cited steps, 3.7% of high-regret steps). | `results/gemini/atlas_blind.md` |
| **Usage** | ⟨USAGE⟩ | `results/gemini/usage_total.json` |

## Honesty notes
- Small samples: ladder cells have 9–40 paired seeds and the control 8–11, so CIs are wide and every claim is CI-gated.
- The control uses the earlier v1.3 rules because those are the only worlds with committed GPT-5.5 episodes; one non-Gemini frontier model, no Anthropic model. ⟨J1⟩
- Canary's logged rows are written by our client (no API request id); 608 recorded responses used for keyless replay do carry response ids.
- HoldUp's 5.8 s "before" latency was one unlogged run; its demo video is a browser simulation until the on-glasses run is logged. The PaliGemma comparison below is not at one operating point.
- The AfterQuery gap depends on the harness (`docs/reports/gap.md`): gemini-4-carbon on v1.4 hard scores 65% [24%, 98%] of the solver via OpenCode over MCP (n=30) and 95% [62%, 140%] in-process. Demo narration (TTS, Live commentator) is not a measurement.

## Also on Gemini
- **Gemini teaches Gemma:** the Gemini-generated label images trained a PaliGemma 2 3B LoRA: "strength visible" recall 91.4% [86.5, 94.6] vs 65.6% for YOLOv8n (n=348 held-out; YOLOv8n precision 96.8% vs 89.9%), not yet in the product ([`GEMMA.md`](https://github.com/s1laswang/junction-meta-glasses/blob/main/GEMMA.md)).
- **Valio Aimo** ([`docs/GEMINI.md`](https://github.com/s1laswang/junction-aimo-agents/blob/main/docs/GEMINI.md)): a gemini-3.8-flash buyer agent escalates 5/34 steps (15%) to gemini-4-hydrogen; compaction cut cost per order from $0.0822 to $0.0352 (−57%); 6/6 scenarios pass.

## Reproduce
```bash
make setup && make reproduce   # environment, solver, baselines (no keys)
make lab-replay                # recorded Gemini runs, keyless
make lab-dashboard             # usage and results dashboard
```
HoldUp: see its README (server 288/288 and web 323/323 tests, 13/13 live smoke checks).

**Team:** Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, with a Claude engineering team.
