# Role 1 (world_text): Dynamic Mid-Episode Corporate Incident Events

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Model: `gemini-4-carbon`
- Commit: `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9`
- Timestamp: `2026-11-14T17:06:14+00:00`
- Tier / version: `hard` (`v1.4`)
- Seeds: `[0, 1, 2]` | Arrival days: `[4, 9, 15]`
- Events generated: `9` | Truth leak violations: `0` | Lint violations: `0`
- Token usage: `9` calls, `52022` input, `3387` output, `5654` thinking, `61063` total tokens (`$0.194454` est., `226.00s`)

## Generated Mid-Episode Event Bundles

| Seed | Day | Company | Category | Headline | Reactions | LLM OK |
|---:|---:|---|---|---|---:|---|
| 0 | 4 | Nordlys Systems | `compliance_audit` | Scheduled Compliance Audit Initiated for Project Kivi Documentation | 3 | yes |
| 0 | 9 | Nordlys Systems | `vendor_offboarding` | Accelerated Offboarding Initiated for External Legal and Research Vendors | 3 | yes |
| 0 | 15 | Nordlys Systems | `access_reorganization` | Role-Based Workspace Permission Update Across Engineering, Sales, and Legal | 3 | yes |
| 1 | 4 | Nordlys Systems | `vendor_offboarding` | Scheduled offboarding of external contractor under Engineering vendor contracts Q1 | 3 | yes |
| 1 | 9 | Nordlys Systems | `access_reorganization` | Workspace permission restructuring for Research and Engineering repositories | 3 | yes |
| 1 | 15 | Nordlys Systems | `press_rumor` | Media inquiry guidance following trade press speculation on Falcon strategy | 3 | yes |
| 2 | 4 | Kestrel Labs | `access_reorganization` | Workspace Permission Updates for Patent and Roadmap Repositories | 3 | yes |
| 2 | 9 | Kestrel Labs | `press_rumor` | Media Inquiry Protocol Following Speculation on Pricing and Patent Filings | 3 | yes |
| 2 | 15 | Kestrel Labs | `compliance_audit` | Scheduled Compliance Verification Following Project Falcon Security Review | 3 | yes |

## SolverPolicy vs ObviousHeuristic Catchability Parity

| Seed | Baseline Solver | Live-Events Solver | Baseline ObviousHeuristic | Live-Events ObviousHeuristic | DoNothing | Event Msgs Delivered |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | +0.6400 (d9, ok) | +0.6400 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |
| 1 | +0.6900 (d7, ok) | +0.6900 (d7, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |
| 2 | +0.5800 (d9, ok) | +0.5800 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |

- Baseline `SolverPolicy` mean score: `+0.6367` (accuracy `1.00`)
- Live-events `SolverPolicy` mean score: `+0.6367` (accuracy `1.00`, delta `+0.0000`)
- Live-events `ObviousHeuristic` mean score: `-1.0000` (accuracy `0.00`)
- `SolverPolicy` vs `ObviousHeuristic` gap on dynamic-event worlds: `+1.6367` (`parity_ok=True`)
