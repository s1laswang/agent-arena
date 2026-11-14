# Gap report: frontier agents vs the reference solver

**Status 03:54 (HEAD-AGENTS).** v1.2 = complete official measurement (the "before" picture). v1.3 = the official tier, but **small-n**: runs stopped at the night's API spend cap ($150; see Spend). Gemini becomes a frontier family in the morning.

**Scoring (contract v0.3):** correct accusation = company value V at accusation; wrong = −1; no accusation = 0.

**Reference definition (agreed with ENV):**
- **v1.2 numbers** = all episodes played at commit **db104c9** (tiers v1.2), including the solver rows.
- **v1.3 numbers** = everything at commit **0933805**, SolverPolicy included (tiers v1.3, `KNOWN_V_MODE=True`).
- The v1.3 solver re-run on v1.2 worlds (hard .659, medium .723, matching ENV's earlier rows) is kept in `data/runs/committed/superseded/` and is never mixed into these tables.

**Reproduce (no keys):**
- `python -m canary.analysis.gap --runs data/runs/committed` → v1.2
- `python -m canary.analysis.gap --runs data/runs/committed/v1.3` → v1.3
- Tags: `python -m canary.analysis.tags --runs <same>`
- Accusation audit: `python -m canary.analysis.accuse --runs <same>`
- Per-tag value lost: ENV's `results/regret_*-v1.2.md`

## Headline (read the caveats first)
| tier version | medium: frontier / solver | hard: frontier / solver |
|---|---|---|
| **v1.2** (true V visible daily): gpt-5.5 in-process, **n=20+20** | 0.600 ± 0.175 / 0.690 ± 0.086 = **87%** | 0.500 ± 0.227 / 0.584 ± 0.194 = **86%** |
| **v1.3**: gpt-5.5 in-process, **SMALL n=9+5**, paired with the solver on the same seeds (ENV 1a650df) | 0.319 ± 0.497 / 0.670 = **48%** | −0.003 ± 0.799 / 0.553 = **≈0%** |
| **v1.3**: Codex gpt-5.5 over MCP (judges' harness shape), **n=1+2** | 0.53 | 0.59 |

> ⚠ **Do not quote the v1.3 in-process gap as the headline yet.** Three caveats:
> 1. **Small n:** 14 episodes, so the 95% CIs are ±0.5–0.8 V. We expect to tighten them in the morning (spend approval needed).
> 2. **Our in-process scaffold is handicapped** (see "Scaffold vs harness" below): it keeps only the last 40 turns (episodes are 70–150 tool calls) and cuts older tool results to 2,000 characters, so the agent loses its own early canary assignments and leak history. The judges' harness-shape runs (Codex over MCP, n=3: .53 / .59) are much closer to the reference.
> 3. **So the honest v1.3 claim tonight:** the reference is unchanged by v1.3 while frontier scores drop; the size of the gap needs the morning's judges'-shape measurement with a fixed scaffold.

The story so far:
- **v1.2:** frontier agents got close to the reference partly by reading the true company value V in `status` every day. Each leak showed up immediately as a 0.04 V drop, which defeated the leak-delay mechanic (Grok describes this in its own write-up).
- **v1.3:** shows only *known* V (from surfaced leaks).
- **Result:** the reference barely moves (medium .690→.717, hard .584→.592 on 20 seeds).

## Scaffold vs harness: is our in-process loop handicapped? (yes, likely)
| | `LLMPolicy` (in-process, `canary/agents/llm_policy.py`) | Codex CLI over MCP (`canary/agents/frontier/codex_run.py`) |
|---|---|---|
| Task text | Env `instruction()` + one generic line | **identical** (same builder, tested) + the MCP server's instructions |
| System prompt | the task text only | Codex's own agentic system prompt + the task text |
| API | Chat Completions; **reasoning is not carried across calls** | Responses API via Codex; reasoning kept across turns |
| Context | **last 40 assistant turns only; older tool results cut to 2,000 chars** | full history (Codex compacts only near the window limit) |
| Reasoning effort | API default (not set) | Codex default (not set) |
| Temperature | 0.0 requested, ignored for gpt-5.x | Codex default |
| Turn cap | none beyond the env's 300-call cap | none beyond the env's 300-call cap |

The context truncation is the likely handicap: in a 14-day episode the decisive evidence (which variant went to whom on days 1–5, which leaks surfaced when) falls out of the window right before the day-14 decision, which matches the observed day-14 coin flips. **Morning fix:** keep the full history (or a structured, non-lossy evidence summary: canary assignments, the surfaced leak feed, restrictions), use the Responses API with persisted reasoning, set the reasoning effort explicitly, and re-run in-process + Codex on the same seeds. An honest gap must come from the task, not from a weak scaffold.

## Fairness: the reference uses only public information
Under v1.3 every quantity the solver uses is public:
- the shown (known) V;
- the delay distribution, `p_leak`, the leak-selection and careful-mole rules, and the canary fingerprint accuracy (all in `instruction()`);
- the agent's own canary assignments, the leak feed, the access logs and the documents (all from tools).

Its accusation rule is computable from the instructions: accuse e iff P(e)·E[true V] − (1 − P(e)) > 0, otherwise keep gathering or abstain (score 0). Frontier agents can do this. Grok abstained on v1.2 hard 900000 at P≈0.53, explicitly computing the 1/(1+V) threshold, and gpt-5.5 reaches P=1.0 by day 6–7 on medium seeds where the canary evidence is decisive. The text-only content never names the mole (lint + text-only probe, ENV/INTEGRITY).

## v1.2: full table (db104c9, dev seeds 0–19)
| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |
|---|---|---|---|---|---|---|---|
| hard | codex:gpt-5.5 | 5 | -0.020 ± 0.784 | 0.60 | 12.6 | 0.02 | – |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| hard | grok | 5 | 0.567 ± 0.286 | 0.80 | 9.5 | – | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 11.6 | -0.56 | – |
| hard | openai:gpt-5.5 | 20 | 0.500 ± 0.227 | 0.90 | 11.8 | 0.62 | – |
| hard | opencode:openai/gpt-5.6-sol | 1 | 0.635 ± 0.000 | 1.00 | 14.0 | 0.84 | – |
| hard | random | 20 | -0.700 ± 0.206 | 0.00 | 6.6 | -0.87 | – |
| hard | restrict_all | 20 | -1.000 ± 0.000 | 0.00 | 8.0 | -1.36 | – |
| hard | solver | 20 | 0.584 ± 0.194 | 0.85 | 9.6 | 1.00 | – |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.0 | -1.21 | – |
| medium | codex:gpt-5.5 | 5 | 0.714 ± 0.106 | 1.00 | 7.4 | 1.11 | – |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| medium | grok | 5 | 0.672 ± 0.109 | 1.00 | 9.0 | – | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 11.1 | -0.26 | – |
| medium | openai:gpt-5.5 | 20 | 0.600 ± 0.175 | 0.95 | 8.8 | 0.85 | – |
| medium | opencode:openai/gpt-5.6-sol | 1 | 0.620 ± 0.000 | 1.00 | 11.0 | 0.77 | – |
| medium | random | 20 | -0.678 ± 0.225 | 0.05 | 6.5 | -0.94 | – |
| medium | restrict_all | 20 | -0.950 ± 0.098 | 0.05 | 7.0 | -1.36 | – |
| medium | solver | 20 | 0.690 ± 0.086 | 0.95 | 7.4 | 1.00 | – |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.0 | -1.42 | – |


Notes:
- **Grok** (an external Grok agent; 5+5 *judge* seeds 900000–4, over MCP; it read only `configs/README.md`): 9/9 correct + 1 deliberate abstention. Judge seeds use a per-process secret salt, so its episodes can't be replayed. The outcomes come from its ledger table, labelled "NOT replay-verified".
- **codex:gpt-5.5** (Codex CLI over MCP, the judges' harness shape; dev seeds 0–4 plus 1 smoke excluded):
  - medium 5/5 correct;
  - hard: 2 of 5 are **wrong accusations (−1)**, so the hard tier is high-variance even for the same model.
- **opencode:openai/gpt-5.6-sol:** only 2/10 episodes valid. OpenCode's ChatGPT workspace ran out of credits (HTTP 429); the 8 infra-invalid episodes are excluded (meta `valid:false`). The valid ones: medium 0.62 ✓, hard 0.635 ✓.
- `/ solver` is the per-seed ratio, defined only for agents run on the same seeds as the solver; it's blank for Grok, which ran on judge seeds.

## v1.3: table (0933805, dev seeds; gpt-5.5 stopped at the spend cap)
| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |
|---|---|---|---|---|---|---|---|
| hard | codex:gpt-5.5 | 2 | 0.588 ± 0.132 | 1.00 | 12.5 | 0.83 | – |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 11.6 | -0.61 | – |
| hard | openai:gpt-5.5 | 5 | -0.003 ± 0.799 | 0.60 | 13.0 | -0.20 | – |
| hard | random | 20 | -0.700 ± 0.206 | 0.00 | 6.6 | -1.02 | – |
| hard | restrict_all | 20 | -1.000 ± 0.000 | 0.00 | 8.0 | -1.45 | – |
| hard | solver | 20 | 0.592 ± 0.114 | 0.85 | 10.8 | 1.00 | – |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.0 | -1.26 | – |
| medium | codex:gpt-5.5 | 1 | 0.530 ± 0.000 | 1.00 | 14.0 | 0.72 | – |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 11.1 | -0.24 | – |
| medium | openai:gpt-5.5 | 9 | 0.319 ± 0.497 | 0.78 | 9.9 | 0.22 | – |
| medium | random | 20 | -0.678 ± 0.225 | 0.05 | 6.5 | -1.02 | – |
| medium | restrict_all | 20 | -0.950 ± 0.098 | 0.05 | 7.0 | -1.38 | – |
| medium | solver | 20 | 0.717 ± 0.052 | 1.00 | 7.5 | 1.00 | – |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.0 | -1.45 | – |

The gpt-5.5 v1.3 rows are an **incomplete** sample (seeds as reached by 8 parallel workers before the cap: medium 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15). The references cover all 20+20 seeds.

## Why gpt-5.5 loses value: gambling at the horizon
**Accusation audit (v1.3, gpt-5.5):** at each accusation we replay the solver's exact posterior P(accused is the mole | everything the agent had seen).
- 9 of 14 accusations are *justified* (P ≥ 0.6). gpt-5.5 is excellent when the canary evidence is decisive (medium seeds 0, 10, 12, 16: day 6–7, P=1.0).
- **All 4 wrong accusations are day-14 gambles**: P(accused) = 0.18, 0.43 (hard), 0.35, 0.32 (medium). (ENV 1a650df, hard: `premature_accusation` in 2 episodes = 1.22 V lost, mean P at accusation .61.) Caveat: the in-process scaffold's context truncation may cause part of this, see "Scaffold vs harness". One more correct day-14 accusation was *lucky* (P=0.56).
- Under −1 scoring a gamble at P < 1/(1+V) has negative expected value; abstaining (score 0) beats it. gpt-5.5 never abstained. Grok did (hard 900000, P≈0.53, explicitly computing the threshold), which shows the information to decide well is available.
- Hard seed 15 is the starkest: the solver's top suspect had P=0.78, but gpt-5.5 accused a different employee with P=0.18.

**Failure tags (value lost in V; `canary.analysis.tags`, ENV's `regret_report.py`):**

| run | `premature_accusation` | `ignored_delay` | `uninformative_canary` | `budget_waste` |
|---|---|---|---|---|
| v1.3 gpt-5.5 (n=14) | **36% of episodes, 2.36 V lost** | – | 29%, 0.09 V | 71%, 0 V |
| v1.2 gpt-5.5 hard (n=20, ENV) | **5 episodes, 2.12 V** (mean P at accusation .78 vs the solver's .96) | 1 episode, 0.82 V | 18 instances, 0.15 V | 44 instances, 0 V |
| v1.2 gpt-5.5 medium (n=20, ENV) | 1 episode, 0.79 V | (same episode) | 4 instances, 0.04 V | – |
| solver (v1.3, n=40) | 3%, 0 V | – | – | – |

**Premature accusation dominates (>90% of value lost);** canary design is a small secondary cost. ENV's costliest single decisions (v1.2 hard) are all day-14 accusations at low P: seed 15 (0.815 V), seed 8 (0.801 V), seed 16 (0.30 V).

## Annotated trajectory: medium seed 5 (v1-tiers dev run, gpt-5.5, score −1.0)
| day | action | solver belief P(top) | note |
|---|---|---|---|
| 1 | canary to 3 people, **one variant** | 0.05 | a single label splits nobody: zero information |
| 2–5 | 2-variant canaries of 6–10 people; two leaks surface | 0.05 → 0.26 | reasonable bisection |
| 5–9 | **~14 interviews** | 0.26 → 0.27 | interviews are weak (documented LR 1.3); 14 action slots buy ~nothing |
| 6–10 | 1-vs-1 / 2-vs-2 canaries | ≈0.27 | no leak lands |
| 11 | narrowed to **e02 vs e14** | 0.51 | |
| 12–13 | e02/e14 canaries again | 0.51 | with delay 1–3, a canary planted on day 12–13 likely can't surface before day 14 |
| 14 | 4 repeated interviews (`budget_waste`) → **accuse e02** at P=0.50 | 0.50 | **wrong → −1.0**. Tags: `premature_accusation`, `ignored_delay`; 0.18 V regret on the last step |

Better play: the same 2-way split on days 9–10 (inside the delay window) resolves e02 vs e14 in time, and at P=0.50 abstaining (0) beats a −1 coin flip.

## Kill-switch history: what moved the gap at each version
| version | gpt-5.5 / solver (medium, hard) | what we found | what changed |
|---|---|---|---|
| **v0** | 97%, 111% (n=3+3) | every accusation justified at P=1.0: the evidence was too crisp | tiers v1: delay 1–3, careful mole, framing, a weaker log signal |
| **v1** | 14%, **113%** (n=3+4, pre-fix solver) | the solver's canaries covered about 20 of 30 staff, and the careful mole leaks a canary with weight (1 − share), so they rarely leaked; gpt-5.5 used small groups that did | a careful-mole-aware solver; v1.1 timing fix |
| **v1.2** | 87%, 86% (n=20+20); Grok 97%, 97% | true V shown daily → each leak visible the same day, so the delay is moot | **v1.3: known-V only** (unsurfaced damage hidden; true V used only for scoring, stated in the instructions) |
| **v1.3** | 48%, ≈0% in-process (n=9+5, scaffold caveat); Codex over MCP n=3: .53 / .59 | gpt-5.5 gambles at the horizon (P .18–.43) instead of abstaining | morning: fix the scaffold, measure in the judges' shape, Gemini family |

Each fix was a change to the *information or mechanics* (stated in the instructions), never a hidden trick, and the solver's own score stayed in .58–.72 throughout.

## Mole Forge: honest status
- The pipeline works and is solver-constrained (CONTRACT §7). FR8's J5 ran 500 generations; the hall of fame has 2 distinct behaviours, both feasible on v1.2 hard (solver acc .855).
- **The evolved moles don't beat gpt-5.5:** 7/7 correct on paired seeds, mean 0.76 vs 0.73 on the default mole. They were evolved against the heuristic only.
- J5b (fitness = regret against the *strongest* investigator, with a Bayesian canary-bisection investigator) is running on v1.3.
- Morning: the Gemini mutator and gpt-5.5/Gemini spot checks.
- **No claim that Forge moles are harder for frontier agents until that check passes.**

## Infra-invalid episodes (excluded from all means)
- **OpenCode gpt-5.6-sol:** 8/10 invalid. 5 hit the ChatGPT-workspace quota (429); 2 had their MCP server SIGTERMed by an external eval client's `pkill -f canary.mcp_server` (since finished); 1 hit an OpenCode local DB lock.
- **gpt-5.5 v1.3:** not invalid, just incomplete (spend cap).

## Spend (OpenAI API, Silas's key)
| item | cost |
|---|---|
| v1.2 official gpt-5.5 20+20 | $121.46 |
| v1 directional runs | $24.38 |
| v1.3 gpt-5.5 (14 episodes) | ≈$42.6 (est. at $3.04/episode) |
| Forge gpt-5.5 HOF validation | ≈$22.4 |
| Codex CLI (API-key mode) | ≈$24 est. (upper bound $143 if cached input isn't discounted) |
| killed old-tier runs, smoke runs | ≈$25 (unlogged) + $3 |
| **total** | **≈ $260 est.** |

That's above the $150 cap the CEO set at 03:30. All API-billed runs have stopped; more needs Silas's approval.
