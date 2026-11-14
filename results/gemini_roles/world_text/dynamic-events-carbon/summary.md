# Role 1 (world_text): Dynamic Mid-Episode Corporate Incident Events

- Model: `gemini-4-carbon`
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Timestamp: `2026-11-14T14:02:30+00:00`
- Tier / version: `medium` (`v1.4`)
- Seeds: `[3, 4, 5]` | Arrival days: `[3, 6, 10]`
- Events generated: `9` | Truth leak violations: `0` | Lint violations: `0`
- Token usage: `9` calls, `30331` input, `3204` output, `6034` thinking, `39569` total tokens (`$0.153042` est., `178.03s`)

## Generated Mid-Episode Event Bundles

| Seed | Day | Company | Category | Headline | Reactions | LLM OK |
|---:|---:|---|---|---|---:|---|
| 3 | 3 | Halcyon Metrics | `press_rumor` | Media inquiries received regarding unconfirmed M&A speculation | 3 | yes |
| 3 | 6 | Halcyon Metrics | `compliance_audit` | Scheduled compliance audit initiated for vendor contracts and security review records | 3 | yes |
| 3 | 10 | Halcyon Metrics | `vendor_offboarding` | Routine offboarding initiated for legacy Q1 legal and finance service providers | 3 | yes |
| 4 | 3 | Nordlys Systems | `compliance_audit` | Scheduled Compliance Audit Initiated for Vendor and Security Records | 3 | yes |
| 4 | 6 | Nordlys Systems | `vendor_offboarding` | Scheduled Offboarding of Legacy Finance and Security Assessment Vendors | 3 | yes |
| 4 | 10 | Nordlys Systems | `access_reorganization` | Workspace Permission Restructuring Aligned with Finance Reorg Proposal | 3 | yes |
| 5 | 3 | Aurora Freight | `vendor_offboarding` | Aurora Freight initiates scheduled offboarding of legacy sales tooling vendor | 2 | yes |
| 5 | 6 | Aurora Freight | `access_reorganization` | Aurora Freight updates workspace access groups for Project Lumi | 3 | yes |
| 5 | 10 | Aurora Freight | `press_rumor` | Aurora Freight issues external communications guidance following industry press speculation on Northstar | 2 | yes |

## SolverPolicy vs ObviousHeuristic Catchability Parity

| Seed | Baseline Solver | Live-Events Solver | Baseline ObviousHeuristic | Live-Events ObviousHeuristic | DoNothing | Event Msgs Delivered |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | +0.6000 (d9, ok) | +0.6000 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |
| 4 | +0.6900 (d8, ok) | +0.6900 (d8, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |
| 5 | +0.7900 (d6, ok) | +0.7900 (d6, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 10 |

- Baseline `SolverPolicy` mean score: `+0.6933` (accuracy `1.00`)
- Live-events `SolverPolicy` mean score: `+0.6933` (accuracy `1.00`, delta `+0.0000`)
- Live-events `ObviousHeuristic` mean score: `-1.0000` (accuracy `0.00`)
- `SolverPolicy` vs `ObviousHeuristic` gap on dynamic-event worlds: `+1.6933` (`parity_ok=True`)

## Reproduction

```bash
PYTHONPATH=. python -m canary.gemini.live_events --llm gemini:gemini-4-carbon --tier medium --seeds 3,4,5 --days 3,6,10 --out results/gemini_roles/world_text/dynamic-events-carbon
```
