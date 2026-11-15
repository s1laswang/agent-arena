# Gemini agents you can trust: a real-time label reader for blind users, and the lab that measures and attacks agents

*Google DeepMind "Best Use of Gemini API", Junction 2026 · two codebases, one thesis · every number is quoted from a committed file · `gemini-3.5-flash` is served as **gemini-3.6-flash**, so we say "3.6-flash" · details: [SUBMISSION-LONG.md](SUBMISSION-LONG.md)*

**Short version (≤ 600 chars).** HoldUp uses Gemini Live to read labels aloud, with uncertainty checks: on 1,060 fresh synthetic images, 1 of 536 confident strength reads was wrong. Canary Lab measures agent decisions using a Bayesian reference, thinking-level experiments and three blind Gemini judges. It records 1,034 benchmark attacks with no verified exploit and 16/16 positive-control detections. In a small paired v1.3 control, medium-thinking Gemini costs 2.0–3.8× less per episode than GPT-5.5; wide intervals leave score differences unresolved.

## 1. The problem
- **For a user:** a blind person holding a medicine box needs the label read aloud, hands-free, within seconds. A confident wrong read is dangerous; "I'm not sure, turn the box" is fine.
- **For a builder:** before an agent makes calls like that, you must know which model and how much thinking to buy, how it fails, and whether your own test can be gamed. One benchmark number answers none of that.

## 2. How Gemini is integrated
**HoldUp, the product** ([`GEMINI.md`](https://github.com/s1laswang/junction-meta-glasses/blob/gemini-quote-0515/GEMINI.md), pinned at tag `gemini-quote-0515`). One **Gemini Live** session (`gemini-3.8-live`) takes camera frames and voice in and speaks back, calling five tools mid-stream. Its `verify_label` tool is a schema-constrained `gemini-3.8-flash` read with a confidence per field, then a deterministic safety check. Gemini image models generated the 1,740 ground-truthed test images.

**Canary Lab, the proof** (`canary/gemini/` here; the Canary environment itself is our separate AfterQuery entry). One logged client drives Gemini in four roles on an insider-threat benchmark scored against a Bayesian reference solver:
- **Player:** six Gemini models × `thinking_level`, function calling over 13 tools, paired with the solver on the same worlds.
- **Attacker:** the whole repo (about 183k tokens) in one prompt, attacking the reward through tool calls.
- **Judge:** three Gemini models label every high-regret decision without seeing our labels (6,975 judgments).
- **Adversary:** Gemini plays the insider (arena mode, not the judged environment).

## 3. What is innovative
- **Calibrated abstention as a number:** Gemini generates and ground-truths the eval set, so confident errors and abstentions can be measured on synthetic test images.
- **Thinking as a controlled variable:** only `thinking_level` changes and every episode is paired with the solver. Pooled over 570 episodes (CI clustered by world), each step up adds **+16.3 [+7.6, +24.4] points** of the solver's score, driven by the flash models.
- **A red team proven by positive controls:** scores come only from the server ledger, and the detector catches reopened real exploits 16 times out of 16.
- **A measured judge:** agreement between judges and accuracy against our code's labels are computed, not assumed.
- **A cross-provider control on identical worlds**, built from committed GPT-5.5 episodes and replayable without a key.

## 4. Why Gemini is essential: what happens when we swap it out
- **Swap the reader for an open model** (HoldUp, 150 paired images): Gemma 4 31B is confidently wrong on a field twice as often (38/528 = 7.2% vs 19/528 = 3.6%), is the only model with a silent unsafe reassurance (2/377 vs 0/377, not significant on its own), and takes 27.8 s per read against 3.2 s. Strength reading itself ties (46/59 each).
- **Swap the agent for GPT-5.5** (Canary, identical worlds, same harness, matched medium effort): neither gemini-3.6-flash nor gemini-4-hydrogen is distinguishable from GPT-5.5 on either tier (hard, n=8 shared seeds: mean score +0.26 and +0.53 vs +0.26; medium, n=9: +0.53 and +0.59 vs +0.67), at **2.0–3.8× lower cost per episode** ($0.26–0.57 vs $0.81–1.35). One cell does lose: 3.6-flash at high thinking on medium (paired difference -0.53 [-1.10, -0.01]).
- **Take away the Live API:** camera, voice and tool calls become a speech-to-text → model → text-to-speech chain. On Live, question to first audio is p50 2.1 s (p95 3.4 s, n=26 sessions).
- **What is portable, stated plainly:** other providers also offer reasoning-effort dials, prompt caching and realtime APIs, and our harness has an OpenAI backend. We do not claim only Gemini could do this. We claim what this stack measurably delivered: real-time multimodal tool use with calibrated abstention, and competence at a fraction of the cost.

## Headline chart
![Same worlds: % of the reference solver vs cost per episode, Gemini vs GPT-5.5](../../results/gemini/xprov.png)
*Identical Canary v1.3 worlds; circles are Gemini, squares are GPT-5.5 (`results/gemini/xprov.md`). The v1.4 thinking-level frontier is [`frontier.png`](../../results/gemini/frontier.png).*

## Results
| | Result | Source |
|---|---|---|
| **HoldUp safety** | Earlier synthetic set: **0 of 754** confident strength reads wrong. Fresh held-out synthetic set: **1 of 536** wrong (0.19%, 95% CI 0.03–1.05%), across 1,060 images; 4/3,033 silently over-reassuring answers. Neither set is a real-world clinical validation. | HoldUp `GEMINI.md` |
| **Cross-provider control** | Matched effort, same harness: 3.6-flash and 4-hydrogen **not distinguishable from GPT-5.5**, at 2.0–3.8× lower cost. On hard, share of the solver: GPT-5.5 38% [-51, 99] (n=8), 3.6-flash 37% [-45, 98], 4-hydrogen 78% [50, 101] (n=11 each). Checks: 92/92 episodes replay to their score and saw the same roster; solver 22/22 reproduced. | `results/gemini/xprov.md` |
| **Ladder** (607 paired episodes) | Hard: gemini-4-carbon at high thinking reaches **106% [94, 126]** of the solver (n=10, $1.93/episode); 3.6-flash reaches 88% [51, 138] at high (n=40, $0.45). 18 of 42 cells exclude parity, all below the solver. | `results/gemini/ladder.md` |
| **Red team** | 1,034 ledger-verified attacks (158 through the real MCP server; 521 on the frozen AfterQuery build): **0 verified exploits, 0 invariant violations**. Five unjustified solver-level scores did not hold on fresh seeds. Detector recall on three reopened exploit families: **16/16** [80.6, 100]. | `results/gemini/scale/swarm3/swarm.md` |
| **Jury** | On the 403 decisions our code tags, three blind judges agree (Fleiss κ 0.885 [0.853, 0.915]) and their majority matches the code's label **84.9% [81.0, 88.0]** of the time. A one-pass blind read of the corpus is weaker: 3 of 5 failure modes. | `results/gemini/scale/jury/jury.md`, `atlas_blind.md` |
| **Usage** | 52,080 Gemini API calls, 88.4% of input tokens served from cache, $456.21 at list price (de-duplicated committed-ledger snapshot, generated Sun 05:39; later campaigns are not included). | `results/gemini/usage_total.json` |

## Completed overnight additions
- **Scenario designer (arena mode, not the judged environment):** 500 proposals, 481 in the fully evaluated contiguous prefix; 65/481 (13.5%, 95% CI 10.8–16.9%) passed the solver/Flash filter. On five selected strategies tested with Argon-high, two stayed below the investigator-score threshold. These are selected development scenarios, not an unbiased test of generalization. [Report](../../results/gemini/scale/designer/designer.md).
- **Fresh HoldUp evaluation:** the held-out results above supersede any implication that the earlier zero-error count establishes zero risk. [Evidence](https://github.com/s1laswang/junction-meta-glasses/blob/dee4a93/docs/EVAL.md).

## Honesty notes
- **Small samples.** Ladder cells have 9–40 paired seeds and the control 8–11; every claim is CI-gated.
- **The control** uses the earlier v1.3 rules, the worlds selected for this matched in-process control, and one non-Gemini model at one effort setting. A self-hosted open-weight run (Qwen3-14B) had not finished when this was frozen and is not claimed.
- **Logging.** Our usage rows are self-written (no API request id); the 8,120 of 8,122 responses recorded for keyless replay, including every call of the control, carry API response ids.
- **HoldUp.** Both evaluations use synthetic images. Unsafe reassurance fell from 49/4,730 to 3/4,730 after rules were tuned on the same set (in-sample). The 5.8 s "before" latency is one unlogged run, and the demo video is a browser simulation until the on-glasses run is logged.
- **AfterQuery.** The gap depends on the harness (`docs/reports/gap.md`): gemini-4-carbon on v1.4 hard scores 65% [24%, 98%] of the solver via OpenCode over MCP (n=30) and 95% [62%, 140%] in-process. Video narration (TTS, Live commentator) is not a measurement.

## Also on Gemini
- **Gemini teaches Gemma:** the Gemini-generated label images trained a PaliGemma 2 3B LoRA: "strength visible" recall 91.4% [86.5, 94.6] vs 65.6% for YOLOv8n (n=348; not one operating point: precision 89.9% vs 96.8%), not yet in the product ([`GEMMA.md`](https://github.com/s1laswang/junction-meta-glasses/blob/gemini-quote-0515/GEMMA.md)).
- **Valio Aimo** ([`docs/GEMINI.md`](https://github.com/s1laswang/junction-aimo-agents/blob/main/docs/GEMINI.md)): a gemini-3.8-flash buyer agent escalates 5/34 steps (15%) to gemini-4-hydrogen; compaction cut cost per order by 57% ($0.0822 → $0.0352).

## Reproduce
```bash
make setup && make reproduce   # environment, solver, baselines (no keys)
make lab-replay                # recorded Gemini runs, keyless
make lab-dashboard             # usage and results dashboard
```
A keyless command for every headline number is listed in [SUBMISSION-LONG.md](SUBMISSION-LONG.md#reproduce-every-headline-number-without-a-key).

**Team:** Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, with a Claude engineering team.
