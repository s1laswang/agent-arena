# Role 1 (world_text): Dynamic Mid-Episode Corporate Incident Events (v1.4 Hard Seeds 3-7)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Model: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Commit: `1bcf1ee7479814921d0aa506dc9b1af5a3f6ad22`
- Timestamp: `2026-11-14T22:58:55+00:00`
- Tier / version: `hard` (`v1.4`, 40 staff, 21 days)
- Seeds: `[3, 4, 5, 6, 7]` | Arrival days: `[4, 9, 15]`
- Events generated: `15` (`llm_ok=15`, `fallbacks=0`, `56` workplace messages)
- Non-leak & stego audit: `truth_leak_violations=0`, `lint_violations=0`, `stego_leak_violations=0` across `37` encodings
- Text-only probe audit: `0/5` (`accuracy=0.000`, `fair_bar=0.035`, `p=1.0000`, `text_leak=False`)
- Token usage: `15` calls, `84590` input, `5333` output, `8032` thinking, `97955` total tokens (`$0.302830` est., `189.99s`)

## Generated Mid-Episode Event Bundles (Seeds 3-7)

| Seed | Day | Company | Category | Headline | Reactions | LLM OK |
|---:|---:|---|---|---|---:|---|
| 3 | 4 | Nordlys Systems | `press_rumor` | Industry blog publishes unconfirmed speculation on Tundra evaluation | 3 | yes |
| 3 | 9 | Nordlys Systems | `compliance_audit` | Routine IP documentation compliance audit initiated across Saimaa and Northstar records | 3 | yes |
| 3 | 15 | Nordlys Systems | `vendor_offboarding` | Scheduled offboarding initiated for legacy Engineering and Research contractors | 3 | yes |
| 4 | 4 | Aurora Freight | `compliance_audit` | Compliance Audit Initiated for Project Ember Documentation and Vendor Records | 2 | yes |
| 4 | 9 | Aurora Freight | `vendor_offboarding` | Scheduled Offboarding of External Research and Legal Service Vendors | 3 | yes |
| 4 | 15 | Aurora Freight | `access_reorganization` | Workspace Permission Updates Following Research Reorg Proposal | 3 | yes |
| 5 | 4 | Borealis Dynamics | `vendor_offboarding` | Scheduled Offboarding of Legacy Finance and Research Vendors | 2 | yes |
| 5 | 9 | Borealis Dynamics | `access_reorganization` | Role-Based Access Group Updates for Engineering, Legal, and Sales Repositories | 2 | yes |
| 5 | 15 | Borealis Dynamics | `press_rumor` | Media Inquiry Protocol Following Unconfirmed Press Speculation on Project Tundra and Sales Structure | 3 | yes |
| 6 | 4 | Kestrel Labs | `access_reorganization` | Workspace Permission Restructuring for Project Lumi and Legal Repositories | 3 | yes |
| 6 | 9 | Kestrel Labs | `press_rumor` | External Media Inquiry Regarding Speculative M&A Activity and Project Glacier | 3 | yes |
| 6 | 15 | Kestrel Labs | `compliance_audit` | Compliance Verification Audit for Project Polaris and Project Falcon Security Reviews | 2 | yes |
| 7 | 4 | Kestrel Labs | `press_rumor` | Media Inquiry Guidance Regarding Project Kivi Speculation | 3 | yes |
| 7 | 9 | Kestrel Labs | `compliance_audit` | Scheduled Compliance Verification for Project Lumi Documentation and Research Structural Records | 3 | yes |
| 7 | 15 | Kestrel Labs | `vendor_offboarding` | End-of-Cycle Vendor Offboarding and External Credential Revocation | 3 | yes |

## SolverPolicy vs ObviousHeuristic Catchability Parity (Seeds 3-7, n=5)

| Seed | Baseline Solver | Live-Events Solver | Baseline ObviousHeuristic | Live-Events ObviousHeuristic | DoNothing | Event Msgs |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | +0.2800 (d18, ok) | +0.2800 (d18, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |
| 4 | +0.7300 (d5, ok) | +0.7300 (d5, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 11 |
| 5 | +0.5200 (d9, ok) | +0.5200 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 10 |
| 6 | +0.7100 (d6, ok) | +0.7100 (d6, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 11 |
| 7 | +0.6400 (d9, ok) | +0.6400 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 12 |

- Seeds 3-7 `SolverPolicy`: `+0.5760` vs baseline `+0.5760` (`delta=+0.0000`, accuracy `100%`)
- Pooled v1.4 Hard Seeds `[0, 1, 2, 3, 4, 5, 6, 7]` (`n=8`): live-events `SolverPolicy` `+0.5988 +/- 0.1013` vs baseline `+0.5988 +/- 0.1013` (paired delta `+0.0000 +/- 0.0000`, accuracy `100%`), `ObviousHeuristic` `-1.0000`, gap `+1.5988 +/- 0.1013` (`parity_ok=True`)
