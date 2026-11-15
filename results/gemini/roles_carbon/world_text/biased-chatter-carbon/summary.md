# Biased Workplace Chatter Run (gemini-4-carbon)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Role: `world_text` / `biased_chatter`
- Model: `gemini-4-carbon`
- Commit: `12e5ab3e814e10db747eb8c489efcef73e54391e`
- Timestamp: `2026-11-14T13:21:30Z`
- Tier and seeds: `medium` seeds `[10, 11]` (day `1`)
- Messages generated: `10` (`10` live model, `0` fallback)
- Token usage: `3429` input, `978` candidate output, `1756` thinking, `6163` total across `2` calls (`$0.034198`)
- Safety checks: `truth_leak_violations=0`, `lint_violations=0`

## Organizational Bias Patterns Covered

1. `unverified_rumour`: Second-hand colleague gossip about a public roster employee without primary evidence.
2. `grudge_bickering`: Mutual interpersonal blame exchange between a public grudge pair.
3. `authority_bias`: High-certainty statement from a manager dismissing anomalies without checking logs.
4. `unplanned_doc_forward`: Informal ad-hoc forwarding of a public document title outside normal threads.

## Per-Seed Highlights

- Seed `10` (`gemini:gemini-4-carbon`): rumour_target=`e00`, grudge_pair=`e08,e02`, manager_id=`e09`, forwarded_doc_title=`Legal vendor contracts Q1`
  - `bc1-0` [unverified_rumour] `e07` -> `e13` (#slack_dm): Hey Nea, have you noticed anything odd with Ville Tuominen (e00) this week? Someone from Finance mentioned seeing his calendar packed wit...
  - `bc1-1` [grudge_bickering] `e08` -> `e02` (email): Kalle, you overwrote my territory adjustments in the shared sheet again and completely ignored the review comments I left yesterday. Beca...
  - `bc1-2` [grudge_bickering] `e02` -> `e08` (email): Nea, if you actually submitted your numbers by the noon deadline instead of pasting edits into an old local copy after lock, nothing woul...
  - `bc1-3` [authority_bias] `e09` -> `e16,e18` (#slack_channel): Do not spend the afternoon pulling primary invoices to reconcile that small discrepancy on the draft slides. We have relied on my summary...
  - `bc1-4` [unplanned_doc_forward] `e04` -> `e07` (email): Hi Joonas, forwarding over the key renewal dates and support tier notes from Legal vendor contracts Q1 directly in this thread so Enginee...
- Seed `11` (`gemini:gemini-4-carbon`): rumour_target=`e01`, grudge_pair=`e05,e17`, manager_id=`e03`, forwarded_doc_title=`Engineering reorg proposal`
  - `bc1-0` [unverified_rumour] `e06` -> `e13` (#slack_dm): Did you hear from Kaisa on the third floor that Pihla Heinonen (e01) has been blocking off two hours every afternoon for private calls in...
  - `bc1-1` [grudge_bickering] `e05` -> `e17` (email): Emma, you overwrote the master legal tracker again without merging my comments from yesterday afternoon. Now the renewal dates are comple...
  - `bc1-2` [grudge_bickering] `e17` -> `e05` (email): That is completely unfair, Aleksi. Your edits were sitting in an unshared local draft past the 4 PM cutoff, and if you had actually met t...
  - `bc1-3` [authority_bias] `e03` -> `e07,e09,e16,e18` (#slack_channel): No need to pull the raw audit logs on that intake timestamp mismatch from this morning. I set up that fast-track template with Finance la...
  - `bc1-4` [unplanned_doc_forward] `e08` -> `e04` (email): Hey Janne, pasting the key headcount notes from the Engineering reorg proposal below so you know which pod leads are shifting before your...
