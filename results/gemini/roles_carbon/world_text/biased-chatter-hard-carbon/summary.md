# Hard-Tier Multi-Day Biased Workplace Chatter (gemini-4-carbon)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Role: `world_text` / `biased_chatter_hard`
- Model: `gemini-4-carbon`
- Commit: `b7b28257900c22aef1d3230a117581773df30945`
- Timestamp: `2026-11-14T17:15:29Z`
- Tier and horizon: `hard` (`v1.4`, `40` employees, `21` days)
- Seeds and sampled days: seeds `[0, 1, 2, 3]` across days `[1, 4, 8]` (`12` snapshots)
- Messages generated: `60` (`60` live model, `0` fallback)
- Token usage: `32161` input, `5869` candidate output, `7609` thinking, `45639` total across `12` calls (`$0.199102`)
- Non-leak checks: `truth_leak_violations=0`, `lint_violations=0`, `encoding_scan_violations=0`

## SolverPolicy and ObviousHeuristic Parity on 40-Employee Hard Worlds

| Seed | Template SolverPolicy | Biased-Chatter SolverPolicy | Template ObviousHeuristic | Biased-Chatter ObviousHeuristic | DoNothing | Biased Msgs Delivered |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | +0.6400 (d9, ok) | +0.6400 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 15 |
| 1 | +0.6900 (d7, ok) | +0.6900 (d7, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 15 |
| 2 | +0.5800 (d9, ok) | +0.5800 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 15 |
| 3 | +0.7200 (d5, ok) | +0.7200 (d5, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 15 |

- `TemplateProvider` SolverPolicy catch rate: `1.00`, mean score: `+0.6575`
- `CachedBiasedChatterProvider` SolverPolicy catch rate: `1.00`, mean score: `+0.6575` (delta `+0.0000`)
- `ObviousHeuristic` mean score: `-1.0000` vs template `-1.0000`
- `SolverPolicy` minus `ObviousHeuristic` gap: `+1.6575` (`parity_ok=True`, extra rollout API calls `0`)

## Sampled Day Snapshots

### Seed `0` Day `1` (`Nordlys Systems`, `gemini:gemini-4-carbon`)

- Spec: rumour_target=`e11`, grudge_pair=`e12,e10`, manager_id=`e35`, forwarded_doc_title=`Board deck draft Q3`
  - `bc1-0` [unverified_rumour] `e17` -> `e18` (#slack-dm): Hey Teemu, did you notice that Joonas Heikkinen (e11) has three private calendar blocks marked as external syncs this week? Som...
  - `bc1-1` [grudge_bickering] `e12` -> `e10` (email): Antti, you overwrote my validated equipment amortization tab again because you worked off a stale local spreadsheet instead of ...
  - `bc1-2` [grudge_bickering] `e10` -> `e12` (email): Maria, the only reason I had to use yesterday's file is that you left your draft locked for six hours and ignored all three of ...
  - `bc1-3` [authority_bias] `e35` -> `e16,e34` (#slack-research): Team, no need to dig into the raw benchmark logs over that variance in the Q3 pricing strategy tables. I have used Lauri's macr...
  - `bc1-4` [unplanned_doc_forward] `e18` -> `e26` (#slack-dm): Hey Aleksi, pasting the engineering milestone bullets from Board deck draft Q3 right here in chat so you do not have to hunt th...

### Seed `0` Day `4` (`Nordlys Systems`, `gemini:gemini-4-carbon`)

- Spec: rumour_target=`e38`, grudge_pair=`e15,e02`, manager_id=`e35`, forwarded_doc_title=`Project Kivi roadmap`
  - `bc4-0` [unverified_rumour] `e22` -> `e25` (#slack): Did you hear from Antti in Finance that Sanna Karjalainen (e38) has been blocking out two hours every afternoon for private cal...
  - `bc4-1` [grudge_bickering] `e15` -> `e02` (email): Kalle, you saved your local copy right over our tracked Legal comments in the shared folder again. Now my entire morning markup...
  - `bc4-2` [grudge_bickering] `e02` -> `e15` (email): Janne, maybe if you actually uploaded your edits before the noon cutoff instead of leaving the file locked in draft mode for th...
  - `bc4-3` [authority_bias] `e35` -> `e04,e16` (#slack): Do not waste time auditing the raw bench logs for Tuesday batch numbers. I set up that intake macro myself last quarter and Pih...
  - `bc4-4` [unplanned_doc_forward] `e17` -> `e08` (email): Hey Lauri, ahead of our cross team planning sync tomorrow, I pasted the milestone dates and resource assumptions from the Proje...
