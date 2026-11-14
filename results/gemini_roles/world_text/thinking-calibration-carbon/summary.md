# Role 1 (world_text): gemini-4-carbon Thinking-Level Calibration

- Role / Subrole: `world_text` / `thinking_level_calibration`
- Model ID: `gemini-4-carbon` (`feature=worldtext_thinking`)
- Commit: `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9`
- Timestamp: `2026-11-14T17:15:57Z`
- Tier / Seeds / Levels: `medium` (`v1.4`), seeds `[6, 7]`, levels `['low', 'medium', 'high']` (`count=6`)
- Non-Leak & Safety: `truth_leak_violations=0`, `lint_violations=0`, `leak_encoding_violations=0` across `37` encodings
- SolverPolicy Parity: `ok=True` (`TemplateProvider` mean `+0.8050`, cross-level spread `0.0000`, accuracy `100%` across all arms)
- Total Usage: `24` calls, `24102` in, `14232` out, `42377` thinking, `80711` total tokens, `866.12s`, `$0.614294`

## Thinking-Level Calibration Matrix (Seeds [6, 7])

| Thinking Level | LLM OK | LLM Personas | Fallbacks | Mean TTR | Distinct Bigrams | Tone Entropy (bits) | Thinking Tokens | Output Tokens | Latency (s) | Cost (USD) | Solver Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `low` | `100%` (`2/2`) | `20/20` | `0` | `0.6602` | `1178` | `2.7955` | `0` | `4668` | `127.08` | `$0.062748` | `+0.7800` |
| `medium` | `100%` (`2/2`) | `20/20` | `0` | `0.6671` | `1124` | `2.7955` | `3703` | `4307` | `183.11` | `$0.096168` | `+0.7800` |
| `high` | `100%` (`2/2`) | `20/20` | `0` | `0.5543` | `1750` | `2.7955` | `38674` | `5257` | `555.94` | `$0.455378` | `+0.7800` |

## Paired SolverPolicy Score & Accuracy Parity

| Seed | TemplateProvider | `low` | `medium` | `high` | Same Accused | Max Spread |
|---:|---:|---:|---:|---:|---|---:|
| `6` | `+0.7900` (`e17`, d6) | `+0.7900` (`e17`, d6, ok) | `+0.7900` (`e17`, d6, ok) | `+0.7900` (`e17`, d6, ok) | `yes` | `0.0000` |
| `7` | `+0.8200` (`e09`, d7) | `+0.7700` (`e09`, d8, ok) | `+0.7700` (`e09`, d8, ok) | `+0.7700` (`e09`, d8, ok) | `yes` | `0.0500` |

## Non-Leak & Steganographic Audit Summary

- `assert_no_truth` violations: `0`
- `lint_messages` violations: `0`
- `lint_text` violations: `0`
- `canary.gemini.leak_encodings` violations: `0` (`37` encodings checked across WorldText, Day 1 messages, HR interviews, and full episodes)

## Sample Synthesized Outputs Across Thinking Levels

### Level `low` (Seed `6`, Aurora Freight)

- Company blurb: Aurora Freight operates digital logistics and cross-border shipping networks across Northern Europe. Headquartered in Helsinki, the company connects regional carriers with automated routing software to keep cargo moving reliably through harsh winter ports and busy transit hubs.
- Persona `e00` (`tone=dry`): Tuomas Saarinen maintains the core routing algorithms and database clusters in Engineering, ensuring real-time shipment tracking stays online during peak port traffic.
- Day 1 message (`#engineering`, `e07`): Morning team. Staging is running a bit slow after the morning build. If anyone runs into timeout errors during integration tests, please open a ticket for DevOps so we can track it.
- Cooperative HR interview (`e00`): I opened the Project Northstar roadmap and the Project Saimaa security review this morning to align our backend sprint tasks with the upcoming architecture milestones. I also briefly viewed the Q4 pricing strategy and Board deck draft Q4 because they were linked in the shared engineering planning folder, and I wanted to check if the proposed tier changes require new rate-limiting features. Happy to walk you through my browser history or the specific Jira tickets I was updating at the time.
- Evasive HR interview (`e01`): I communicate with standard external auditors and vendors just like anyone else in Finance. Right now my whole day is taken up reviewing numbers for the Q4 pricing strategy and the Board deck draft Q4. I do not see how my professional network is relevant to whatever issue you are looking into.

### Level `medium` (Seed `6`, Aurora Freight)

- Company blurb: Aurora Freight coordinates cross-border Nordic rail and road logistics from its Helsinki hub. The company builds proprietary routing software and manages customs clearance, cold-chain freight scheduling, and fleet capacity for regional manufacturing and retail clients.
- Persona `e00` (`tone=dry`): Tuomas Saarinen maintains the core dispatch API and fleet telemetry pipelines in Engineering, focusing on low-latency route recalculations during winter weather disruptions.
- Day 1 message (`#engineering`, `e07`): Morning team, the routing service staging build is green again. If anyone hits timeout errors on the local container runner today, please open a ticket with DevOps so we can track frequency before Friday.
- Cooperative HR interview (`e00`): Sure, I accessed the Project Northstar roadmap and the Project Saimaa security review earlier today to align our backend sprint tasks with the upcoming architecture requirements. I also briefly opened the Q4 pricing strategy and Board deck draft Q4 from our shared drive because I needed to verify the projected compute tier limits mentioned for our Q4 engineering milestones. Let me know if you want me to pull up my Jira tickets so you can see the exact context for those lookups.
- Evasive HR interview (`e01`): In Finance I deal with external auditors and vendors regularly, so I really do not keep a log of every routine industry contact. Right now I am just trying to finish checking the numbers for the Q4 pricing strategy and the Board deck draft Q4. If you have questions about standard external communication rules, you should probably speak with department leadership.

### Level `high` (Seed `6`, Aurora Freight)

- Company blurb: Aurora Freight is a Helsinki-based multimodal logistics carrier operating Nordic road, rail, and Baltic short-sea corridors. Across port hubs in Vuosaari and Turku, its teams coordinate container routing, customs compliance, fleet telemetry, and enterprise freight contracts for industrial shippers.
- Persona `e00` (`tone=dry`): Tuomas Saarinen maintains the vessel-slot booking API and EDI 315 status parsers in Engineering. He tracks carrier webhook latencies from Vuosaari terminals and documents edge cases in sober, detailed runbooks.
- Day 1 message (`#engineering`, `e19`): Pushed the telemetry hotfix for the vessel-tracking queue, though if staging lags again someone else can open a ticket with infra. Honestly, seeing management add two more deliverables to our sprint while stalling senior pay adjustments and promotion timelines makes me glad I started updating my CV after that Helsinki recruiter messaged me yesterday.
- Cooperative HR interview (`e00`): I am happy to walk through the files I opened today. This morning I used the Project Northstar roadmap and the Project Saimaa security review to scope out our upcoming backend architecture tasks. Later on, I checked the Q4 pricing strategy and the Board deck draft Q4 to verify that our new usage-tier limits and infrastructure metrics matched what leadership is presenting, and I can share the related Jira tickets if that helps.
- Evasive HR interview (`e01`): I deal with routine outside contacts whenever my Finance tasks require it. Unless there is a specific issue you can point to, I need to get back to my work on the Board deck draft Q4.

## Reproduction

```bash
PYTHONPATH=. python -m canary.gemini.worldtext_thinking_eval --llm gemini:gemini-4-carbon --tier medium --seeds 6,7 --levels low,medium,high --jobs 6 --require-live --out results/gemini_roles/world_text/thinking-calibration-carbon
GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_worldtext_thinking_eval.py tests/test_gemini_provenance.py
```
