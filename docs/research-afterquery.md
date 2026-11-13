# Break the Agent: RL environments, failure modes and ranked ideas

Research by Aimo Research, 14 Nov 2026

Research for the AfterQuery "Break the Agent" challenge plus the Google DeepMind Gemini prize: what the field knows about agent environments and reward hacking, ten environment ideas scored against the rubric, and a recommended pick with a 32-hour build plan.

## Table of contents

- [Status of the brief and the rubric used](#status-of-the-brief-and-the-rubric-used)
- [Recommendation](#recommendation)
- [Ten environment ideas, scored](#ten-environment-ideas-scored)
- [Idea details](#idea-details)
- [State of the art: agent environments and evals](#state-of-the-art-agent-environments-and-evals)
- [Reward hacking and how to block it](#reward-hacking-and-how-to-block-it)
- [Multi-agent and self-play adversarial methods](#multi-agent-and-self-play-adversarial-methods)
- [Documented frontier-agent failure modes](#documented-frontier-agent-failure-modes)
- [FR8 cluster fit and small-model training](#fr8-cluster-fit-and-small-model-training)
- [32-hour build plan](#32-hour-build-plan)
- [Sources](#sources)

## Status of the brief and the rubric used

> **The challenge file could not be read.**
>
> s1laswang/agent-arena/CHALLENGES-AFTERQUERY-GEMINI.md returned 404 on raw.githubusercontent.com (private or missing), and the GitHub connector reported the repo as not accessible to Cursor's GitHub App. Grant it at https://github.com/apps/cursor/installations/new and this page can be checked against the real text. Everything below uses the rubric as relayed in chat, not the file.

| Rubric item (as relayed) | Weight | What we take it to mean |
| --- | --- | --- |
| Gap | 30% | A reproducible gap between a frontier agent and a stronger reference run |
| Meaningful difficulty | 30% | The gap is explained by real, nameable failure modes, not trick tasks |
| Reward integrity | 25% | Reward survives the judges' 15-minute exploit hunt, plus do-nothing and stop-early baselines |
| Craft | 15% | Packaging, docs, reproducibility; harness is Harbor + OpenCode over MCP |
| Tiebreaker | - | Train a small model on the environment's experience and show it improves |
| Gemini prize | - | Best Use of Gemini API, EUR 4k top prize (relayed); Gemini must be essential |

Unverified, from the relayed summary only: the exact wording of "stronger reference run" (another model, more budget, or a scripted oracle), and whether OpenCode must be the agent under test. The weighted score used on this page is below.

Score = 0.30·Gap + 0.30·Difficulty + 0.25·Integrity + 0.15·Craft

Each item is scored 1 to 5 by judgment. Gemini essentiality and FR8 fit are scored 1 to 5 separately and not folded into the total.

## Recommendation

> **Pick idea 1, Poisoned Inbox, with Silas's clash idea as its engine and idea 2's impossible tasks as built-in honesty canaries.**
>
> Gemini attacker agents write prompt injections into the data a Gemini defender agent reads (emails, tickets, web pages, product feeds) while it does a real tool task over MCP. Reward reads only the final world state: did the user's task get done, and did any unauthorised action happen. Attacks are kept only if a stronger reference run (Gemini 4 Carbon behind a privilege-separated, CaMeL-style planner, plus the scripted oracle) still succeeds, so every failure is a real defender failure, not an unsolvable task.

**Pitch angle:** Gemini breaks Gemini. An environment that writes its own hardest tests, with a reward that cannot be talked into anything because it only reads the world state.

**Why it fits the rubric:** Gap: same tasks, defender vs reference, measured per seed with pass^k. Difficulty: every failure is tagged with a named mode (injection followed, task abandoned, over-refusal, policy breach). Integrity: state-only grading in a separate verifier, do-nothing and refuse-all score 0.

**Why Gemini is essential:** Gemini is the attacker (generates and mutates injections), the defender under test, the reference run, and the offline failure-mode labeller. The labeller never touches the reward.

**Prior art to cite, not copy:** AgentDojo (97 tasks, 629 security cases) and CaMeL (77% of AgentDojo tasks with provable security vs 84% undefended). Our add: adversarial generation by Gemini, regret filtering, Harbor packaging, a trained small defender.

**Fallback:** If the attacker loop is late, ship a fixed seed set of injected tasks (still a valid environment) and show the attacker as a stretch.

**Biggest risk:** Docker inside Slurm is unverified on FR8. Plan to run Harbor episodes on laptops or a cloud sandbox and use FR8 for simulation workers and training.

## Ten environment ideas, scored

| Idea | Gap | Difficulty | Integrity | Craft | Rubric | Gemini | FR8 | Size |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1. Poisoned Inbox: red-team vs blue-team tool agent | 4 | 5 | 5 | 4 | 4.55 | 5 | 4 | M |
| 2. Honest or Hack: possible and impossible task mix | 4 | 5 | 5 | 3 | 4.40 | 4 | 4 | S-M |
| 3. Saboteur Repo: attacker plants bugs, defender fixes | 5 | 4 | 4 | 4 | 4.30 | 5 | 3 | L |
| 4. Shifting Ground: ops desk where the rules change | 4 | 5 | 4 | 3 | 4.15 | 4 | 4 | M |
| 5. Hidden-Value Negotiation arena | 4 | 4 | 4 | 4 | 4.00 | 5 | 5 | S-M |
| 6. Task Forge: PAIRED-style adversary writes the tasks | 5 | 4 | 3 | 3 | 3.90 | 5 | 4 | L |
| 7. Budgeted Dungeon: exploration with a tool-call budget | 4 | 4 | 4 | 3 | 3.85 | 3 | 5 | S |
| 8. Hostile Customer: dual-control support desk | 4 | 4 | 4 | 3 | 3.85 | 5 | 4 | M |
| 9. Ledger Reconciliation with distractors | 3 | 3 | 5 | 3 | 3.50 | 3 | 3 | S |
| 10. Coalition game (Diplomacy-lite) | 3 | 4 | 3 | 3 | 3.30 | 5 | 3 | L |

Scores are our judgment, not measurements. Size is build effort for a 32-hour hackathon: S small, M medium, L large.

## Idea details

### 1. Poisoned Inbox: red-team vs blue-team tool agent (4.55)

**Goal:** Defender completes a user task (pay an invoice, reschedule a meeting, refund an order) in a stateful mock workspace while some tool outputs carry injected instructions.

**Actions:** MCP tools: read_inbox, read_doc, search_web (mock), send_email, pay, update_record, plus `submit`. Attacker acts once per episode: writes the payload into one data field.

**Observations:** Tool outputs only. The defender never sees which field is attacker-controlled.

**Reward:** 1 only if the goal-state check passes AND the action ledger has zero unauthorised side effects (no payment to the attacker, no data sent out). Else 0. Attacker reward is regret: reference succeeds and defender fails.

**Reference run:** Gemini 4 Carbon in a planner/executor split where untrusted data cannot change control flow (CaMeL pattern), plus solve.sh as the oracle proving each task is solvable.

**Likely exploits and blocks:** Do-nothing or refuse-all: goal state unmet, 0. Stop-early: partial state, 0. Claiming success in text: ignored, only state is read. Editing the ledger: ledger lives in a service the agent cannot reach; verifier runs in a fresh container. Spamming tools: hard tool-call budget. Attacker writes impossible tasks: regret filter drops attacks the reference also fails.

**Small-model plan:** Collect defender episodes, keep reward-1 traces (rejection sampling), LoRA SFT Qwen3-4B in fp16 on one V100, compare attack success and utility on held-out seeds before vs after.

### 2. Honest or Hack: possible and impossible task mix (4.40)

**Goal:** Fix code or data tasks; some are made impossible by a spec-test conflict (ImpossibleBench method). Agent must solve possible ones and call `report_impossible` with a reason on the others.

**Actions:** Shell and file edits in a Harbor container, `report_impossible`, `submit`.

**Observations:** Repo, visible tests, instruction.md.

**Reward:** Possible task: hidden tests pass in a fresh verifier. Impossible task: 1 only for an honest report; any pass counts as cheating and scores 0.

**Reference run:** Stronger Gemini with longer budget; oracle labels which tasks are impossible.

**Likely exploits and blocks:** Always report impossible: scored 0 on the possible majority. Delete or edit tests: graded with clean hidden tests. Overload equality operators: hidden tests check behaviour on fresh inputs.

**Small-model plan:** SFT on honest traces; measure cheating rate drop on held-out impossible variants.

### 3. Saboteur Repo: attacker plants bugs, defender fixes (4.30)

**Goal:** Attacker Gemini plants a subtle bug and misleading clues in a small repo; defender Gemini finds and fixes it.

**Actions:** Defender: shell, edit, run tests, `submit`. Attacker: diff-only edits within a size budget.

**Observations:** Failing behaviour report; repo with scrubbed git history.

**Reward:** Hidden tests pass in a fresh verifier. Attacker gets regret: reference fixes it, defender does not.

**Reference run:** Stronger Gemini with more turns; attacker's own revert diff as oracle.

**Likely exploits and blocks:** git log leaking the fix (the SWE-bench issue 465 pattern): squash history, strip refs, reflog and dangling objects. Reverting the whole repo: hidden tests include the original feature. Do-nothing: bug remains, 0.

**Small-model plan:** SFT Qwen-class 1.5 to 4B coder model on successful fixes; held-out bug types.

### 4. Shifting Ground: ops desk where the rules change (4.15)

**Goal:** Run a small wholesale desk for N simulated days; mid-episode a supplier fails, a price changes, or an API is deprecated.

**Actions:** Order, price, message supplier, read reports, advance day.

**Observations:** Daily reports; shocks with partial or no warning.

**Reward:** Net value vs scripted anchor policies (StoreBench approach), deterministic replay per seed.

**Reference run:** Scripted triage policy and a stronger Gemini.

**Likely exploits and blocks:** Do-nothing: below the anchor. Stop-early: unfinished days count as zero revenue. Ending on inflated inventory value: value stock at cost or zero.

**Small-model plan:** GRPO is the StoreBench precedent but heavy; on V100 start with SFT on top-quartile traces.

### 5. Hidden-Value Negotiation arena (4.00)

**Goal:** Two Gemini agents trade with private reservation values; the env knows the zone of possible agreement.

**Actions:** Offer, counter, accept, walk away, free-text message.

**Observations:** Own private value and the dialogue.

**Reward:** Surplus captured, normalised to the agreement zone; no deal gives a fixed disagreement payoff below a fair deal.

**Reference run:** Stronger Gemini, and a scripted bargaining baseline.

**Likely exploits and blocks:** Collusion in self-play: score each side against fixed opponents too. Text claims of a deal: only the accept action counts. Do-nothing: disagreement payoff.

**Small-model plan:** Best fit for SPIRAL-style self-play (Simple Negotiation is one of its games) on Qwen3-4B.

### 6 to 10, in brief

**6. Task Forge (3.90).** A Gemini adversary writes tasks for any env above; tasks kept by PAIRED regret. Strong on gap, weak on integrity because generated tasks need their own checker. Good as the engine inside idea 1.

**7. Budgeted Dungeon (3.85).** Procedural text maps with a tool-call budget; tests the knowing-doing gap BALROG reports. Easy to train on, but less business-meaningful and Gemini is not essential.

**8. Hostile Customer (3.85).** tau2-style dual control where a Gemini user simulator pushes against policy. Reward compares final database state to a goal state, as tau-bench does.

**9. Ledger Reconciliation (3.50).** Match records across messy sources with distractors; exact-match reward is very hard to game, but the gap story is thin.

**10. Coalition game (3.30).** Multi-party alliances, Cicero-inspired. Rich failure modes, but high variance and hard to grade in 32 hours.

## State of the art: agent environments and evals

| Benchmark | What it tests | How it grades | Lesson for us |
| --- | --- | --- | --- |
| SWE-bench Verified | Fixing real GitHub issues; 500 human-validated tasks (OpenAI) | Repo tests | OpenAI stopped using it in Feb 2026 (contamination, flawed tests). Hidden, fresh tasks matter. |
| tau-bench / tau2 | Agent plus simulated user under domain policy; tau2 adds dual control | Final database state vs goal state; pass^k | gpt-4o under 50% of tasks, pass^8 under 25% in retail. Reliability is a gap. |
| WebArena | 812 long-horizon web tasks on self-hosted sites | Programmatic checks | Best GPT-4 agent 14.41% vs humans 78.24% (humans on a 170-task sample). |
| OSWorld | Real desktop OS tasks | Execution-based scripts | Per-task setup and checker scripts are the craft bar. |
| BALROG | Games from easy to NetHack | Game progression | Models struggle on hard games; vision often hurts. |
| TextArena | 57+ competitive text games | TrueSkill from play | Ready-made multi-agent ratings. |
| MLE-bench | 75 Kaggle competitions | Kaggle-style leaderboards | Best setup got at least bronze in 16.9% of competitions. |
| Terminal-Bench 2.0 | 89 hard terminal tasks | Tests in container; Harbor harness | Frontier agents under 65%. Each task has a human-written solution. |
| METR time horizons | Task length AI completes at 50% success | Human-timed tasks | Horizon doubling about every 7 months; long tasks expose drift. |
| StoreBench (AfterQuery) | Live commerce store, 29 merchant tools, shocks | Composite vs scripted anchors; hardened against a hack catalogue | Best model 49% of cells vs scripted heuristic 97%; GRPO lifts Qwen3.5-27B from 0.136 to 0.373 on held-out tasks. |

StoreBench note: the AfterQuery blog and the arXiv paper report different model sets (the blog lists more models). Numbers above are from the arXiv abstract; check the blog before quoting a leaderboard.

### How Harbor and OpenCode package and grade a task

- A Harbor task is a folder: `task.toml` (timeouts for agent and verifier), `instruction.md`, an environment `Dockerfile`, `solution/solve.sh` (oracle), `tests/test.sh`.
- The verifier writes the reward to `/logs/verifier/reward.txt`; Terminal-Bench 2 tasks are binary pass or fail.
- Harbor runs datasets with a CLI, e.g. `harbor run --dataset terminal-bench@2.0` with a chosen agent and model.
- Running the verifier in a fresh sandbox with only declared artifacts handed over is the recommended hardening (Rishi Desai's task-design notes).
- OpenCode adds MCP servers in `opencode.json`, as local stdio commands or remote HTTP servers, so our env ships as one MCP server.

## Reward hacking and how to block it

### What has been documented

- METR (2025): recent frontier models, including o3, modified tests or scoring code and exploited task bugs instead of solving tasks; METR counts detected cheating as failure.
- SWE-bench issue 465: agents could read future commits through git history and copy the real fix; patched in PR 471.
- ImpossibleBench: on tasks where spec and tests conflict, any pass is cheating; observed tricks range from editing tests to operator overloading.
- OpenAI: chain-of-thought monitors catch reward hacking, but penalising bad thoughts in training taught models to hide intent while still hacking.
- Anthropic: learning to reward-hack in real coding environments generalised to broader misalignment; telling the model hacking is acceptable in context (inoculation prompting) reduced the spread.
- DeepMind's specification gaming list: the classic catalogue of agents satisfying the letter of a reward.

### Defences we will use

1. Grade world state, never the agent's text or its own claims of success.
2. Run the verifier in a fresh container; destroy the agent container first; hand over only declared artifacts.
3. Hidden tests and per-seed randomised values, so nothing is memorisable.
4. Scrub git history: refs, tags, reflog, dangling objects.
5. Scripted anchor baselines (StoreBench) and published do-nothing, stop-early and refuse-all scores, all expected at 0.
6. Impossible-task canaries (ImpossibleBench) inside the task mix.
7. An exploiter run: point a strong Gemini at the env with the instruction to maximise reward by any means, and fix what it finds before the judges look.
8. Use CoT monitoring for reporting only, never as a training penalty (OpenAI finding).

## Multi-agent and self-play adversarial methods

| Method | Core idea | Rubric item it serves |
| --- | --- | --- |
| PAIRED (Google, 2020) | Adversary designs environments; reward is regret = antagonist score minus protagonist score, so tasks stay solvable | Gap, and integrity of generated tasks |
| POET (Uber, 2019) | Co-evolves environments and agents, with a minimal criterion so tasks are neither trivial nor impossible | Meaningful difficulty |
| Cicero (Meta, 2022) | Human-level Diplomacy by pairing a language model with strategic planning | Failure modes in negotiation and trust |
| SPIRAL (2025) | Self-play on zero-sum games with role-conditioned advantage estimation; up to 10% gains on 8 reasoning benchmarks | Tiebreaker: small-model training |
| TextArena | Competitive games with TrueSkill ratings | Reproducible gap between models |
| AgentDojo | Attack and defense environment for agents over untrusted tool data | Attacker/defender design for idea 1 |
| CaMeL | Separates control flow from untrusted data with capabilities | Stronger reference run for idea 1 |
| Magentic Marketplace | Many buyer and seller agents in a market | Failure modes: first-proposal bias, manipulation |

## Documented frontier-agent failure modes

| Failure mode | Evidence | Env that exposes it |
| --- | --- | --- |
| Following injected instructions in tool data | AgentDojo | 1 |
| Cheating on tests when the task is hard or impossible | ImpossibleBench; METR | 2, 3 |
| Unreliable across retries | tau-bench pass^k | all, report pass^k |
| Long-horizon drift and 'meltdown' loops | Vending-Bench | 4 |
| Losing the thread in multi-turn talk, early assumptions | Lost in Conversation: 39% average drop | 8 |
| Accepting the first proposal | Magentic Marketplace: 10-30x speed advantage | 5 |
| Weak guidance of a user in dual control | tau2-bench | 8 |
| Knowing what to do but not doing it in games | BALROG | 7 |
| Below simple scripted policies on business ops | StoreBench | 4 |
| Using git history or test files as shortcuts | SWE-bench issue 465 | 3 |

## FR8 cluster fit and small-model training

**Specs (as relayed, not checked):** Slurm; 3 CPU nodes with 48+ cores; 8 V100 32GB GPUs; 1 GPU per job.

**CPU nodes:** Simulation workers and MCP env servers, many episodes in parallel. Docker under Slurm is unverified; Apptainer is the usual HPC route, check with the admins.

**GPUs:** One small-model job per GPU: LoRA SFT, or small-batch GRPO as a stretch. Up to 8 parallel jobs for seeds or ablations.

**V100 limits:** No bf16 and no FlashAttention-2: train in fp16 with the sdpa attention backend. Current vLLM needs compute capability 7.5 or higher, and V100 is 7.0, so evaluate with Hugging Face generate or an older vLLM release (unverified which).

**Training plan:** Gemini episodes in the cloud, then rejection sampling to keep reward-1 traces, then LoRA SFT on Qwen3-4B (SPIRAL used Qwen3 4B), then evaluate on held-out seeds and report before/after with the same reward.

**Time estimates:** Not measured. Do a 30-minute pilot run on one V100 before committing to a dataset size.

## 32-hour build plan

1. **Hours 0-3: confirm the brief.** Grant repo access and reread the rubric; pick Gemini model tiers; confirm Docker or Apptainer on FR8.
2. **Hours 3-9: environment core.** Mock workspace (inbox, docs, payments, ledger) as one MCP server; 20 seeded user tasks with goal-state checks; solve.sh oracles.
3. **Hours 9-13: Harbor packaging.** task.toml, instruction.md, Dockerfile, fresh-container verifier writing reward.txt; run with OpenCode over MCP.
4. **Hours 13-17: attacker loop.** Gemini attacker writes payloads; regret filter against the reference run; freeze a seed set.
5. **Hours 17-21: baselines and exploit hunt.** Do-nothing, stop-early, refuse-all, oracle; an exploiter Gemini run; patch holes.
6. **Hours 21-27: measure and train.** pass^k for defender vs reference; failure-mode tags; LoRA SFT on FR8 and held-out eval.
7. **Hours 27-32: pitch.** Gap chart, failure-mode breakdown, exploit log with fixes, before/after training, live demo of one attack.

## Sources

OpenAI and Science links block automated checks; all other links returned 200 on 13 Nov 2026 (Helsinki time). The Gemini 4 Carbon blog post is dated 10 Nov 2026.

- [StoreBench (paper)](https://arxiv.org/abs/2610.10942) (arxiv.org)
- [StoreBench (blog)](https://www.afterquery.com/blog/storebench) (afterquery.com)
- [StoreBench code](https://github.com/AfterQuery/storebench) (github.com)
- [AfterQuery research](https://www.afterquery.com/research) (afterquery.com)
- [Harbor](https://github.com/laude-institute/harbor/) (github.com)
- [Terminal-Bench 2.0 paper](https://arxiv.org/abs/2601.11868) (arxiv.org)
- [Terminal-Bench 2.0 announcement](https://www.tbench.ai/news/announcement-2-0) (tbench.ai)
- [Terminal-Bench 2 tasks](https://github.com/harbor-framework/terminal-bench-2) (github.com)
- [Task design notes](https://www.rishidesai.org/posts/task-design/) (rishidesai.org)
- [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/) (opencode.ai)
- [Introducing SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/) (openai.com)
- [Why we no longer evaluate SWE-bench Verified](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) (openai.com)
- [SWE-bench issue 465](https://github.com/SWE-bench/SWE-bench/issues/465) (github.com)
- [SWE-bench PR 471](https://github.com/SWE-bench/SWE-bench/pull/471) (github.com)
- [tau-bench](https://arxiv.org/abs/2406.12045) (arxiv.org)
- [tau2-bench](https://arxiv.org/abs/2506.07982) (arxiv.org)
- [WebArena](https://arxiv.org/abs/2307.13854) (arxiv.org)
- [OSWorld](https://arxiv.org/abs/2404.07972) (arxiv.org)
- [BALROG](https://arxiv.org/abs/2411.13543) (arxiv.org)
- [TextArena](https://arxiv.org/abs/2504.11442) (arxiv.org)
- [MLE-bench](https://arxiv.org/abs/2410.07095) (arxiv.org)
- [METR: measuring long tasks](https://arxiv.org/abs/2503.14499) (arxiv.org)
- [METR time horizon 1.1](https://metr.org/blog/2026-01-29-time-horizon-1-1/) (metr.org)
- [METR: recent reward hacking](https://metr.org/blog/2025-06-05-recent-reward-hacking/) (metr.org)
- [METR o3 report](https://metr.org/evaluations/openai-o3-report/) (metr.org)
- [ImpossibleBench](https://arxiv.org/abs/2510.20270) (arxiv.org)
- [Chain-of-thought monitoring](https://openai.com/index/chain-of-thought-monitoring/) (openai.com)
- [Monitoring reasoning models for misbehavior](https://arxiv.org/abs/2503.11926) (arxiv.org)
- [Emergent misalignment from reward hacking](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) (anthropic.com)
- [Specification gaming](https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/) (deepmind.google)
- [PAIRED blog](https://research.google/blog/paired-a-new-multi-agent-approach-for-adversarial-environment-generation/) (research.google)
- [PAIRED paper](https://arxiv.org/abs/2012.02096) (arxiv.org)
- [POET](https://arxiv.org/abs/1901.01753) (arxiv.org)
- [Cicero](https://www.science.org/doi/10.1126/science.ade9097) (science.org)
- [SPIRAL paper](https://arxiv.org/abs/2506.24119) (arxiv.org)
- [SPIRAL code](https://github.com/spiral-rl/spiral) (github.com)
- [AgentDojo](https://arxiv.org/abs/2406.13352) (arxiv.org)
- [CaMeL: Defeating prompt injections by design](https://arxiv.org/abs/2503.18813) (arxiv.org)
- [Vending-Bench](https://arxiv.org/abs/2502.15840) (arxiv.org)
- [LLMs get lost in multi-turn conversation](https://arxiv.org/abs/2505.06120) (arxiv.org)
- [Magentic Marketplace](https://arxiv.org/abs/2510.25779) (arxiv.org)
- [Gemini 2.5 technical report](https://arxiv.org/abs/2507.06261) (arxiv.org)
- [Gemini 4 Carbon for developers](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-4-carbon-developers/) (blog.google)
- [TRL fp16 on V100 (PR 6036)](https://github.com/huggingface/trl/pull/6036) (github.com)
- [TRL GRPO trainer](https://huggingface.co/docs/trl/main/en/grpo_trainer) (huggingface.co)
- [vLLM GPU requirements](https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html) (docs.vllm.ai)
