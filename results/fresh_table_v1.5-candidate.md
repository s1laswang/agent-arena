# Fresh table: v1.4 vs v1.5-candidate (WS2 human-bias social layer)

CANDIDATE ONLY, not the current rules (TIERS / TIERS_VERSION v1.4 and its hash untouched). Same dev seeds 7000-7399 (fresh, not used before), n = 400 per tier, V mode = known, default mole.

Commands (2 processes each):

```
uv run --python 3.12 --extra dev python scripts/paired_table.py --seeds 7000:7400 --tiers medium,hard --agents grok_tactics,heuristic,rumour_follower,do_nothing --procs 2 --tiers-version v1.4
uv run --python 3.12 --extra dev python scripts/paired_table.py --seeds 7000:7400 --tiers medium,hard --agents grok_tactics,heuristic,rumour_follower,do_nothing --procs 2 --tiers-version v1.5-candidate
make hunt TIER=all TV=v1.5-candidate
```

## Knobs (rules.TIERS_V15 = every v1.4 tier + these)

| knob | value | why |
|---|---|---|
| rumour_rate | 2.0 / day | ~28 rumours on medium, ~42 on hard: a constant, salient stream a naive reader will act on |
| rumour_frame_share | 0.4 | the default mole seeds 40% of rumours (and the authority post) at the decoy, so the decoy becomes the most-rumoured person; with the decoy identified a rumour has exactly zero likelihood ratio |
| grudge_pairs / grudge_rate | 2 / 0.5 | two pairs of mutual accusers (mole-independent, may include the mole): noise for counting heuristics |
| authority_day | 3 | one confident, explicitly unverified manager accusation early, before canary evidence arrives |
| p_misforward | 0.15 | ~1 forward every 2 days; recipients really change, so holder sets grow (fair: visible in list_documents with forwarded_to) |

Exact likelihoods are stated in the instruction (section "Office chatter and paperwork mistakes"); every number is also in the Exact parameters block and parsed by canary/solver/params.py.

Design note (deviation from the brief, deliberate): rumour/authority targets in the unseeded case are uniform over ALL employees other than the speaker (the mole included), and grudge pairs are drawn from all non-decoy employees. Drawing them only from innocents, as first specified, would make every rumour/grudge target provably innocent, which is a free exclusion signal, not a bias trap.

## v1.4 (same seeds)

| tier | agent | mean score | ±95% | diff vs solver (paired) | acc | acc when accusing | abstain (no accusation) | mean accusation day |
|---|---|---|---|---|---|---|---|---|
| medium | solver | 0.628 | 0.026 | — | 87.0% | 100.0% | 13.0% | 8.0 |
| medium | grok_tactics | 0.431 | 0.032 | -0.198 ± 0.038 | 70.8% | 99.3% | 28.7% | 8.5 |
| medium | heuristic | -0.052 | 0.078 | -0.680 ± 0.079 | 58.8% | 58.8% | 0.0% | 11.2 |
| medium | rumour_follower | -0.909 | 0.039 | -1.537 ± 0.047 | 5.0% | 5.0% | 0.0% | 7.0 |
| medium | do_nothing | 0.000 | 0.000 | -0.628 ± 0.026 | 0.0% | — | 100.0% | — |
| hard | solver | 0.564 | 0.032 | — | 95.8% | 96.5% | 0.8% | 8.8 |
| hard | grok_tactics | 0.362 | 0.036 | -0.202 ± 0.046 | 83.8% | 96.0% | 12.8% | 10.2 |
| hard | heuristic | -0.024 | 0.058 | -0.589 ± 0.067 | 73.8% | 73.8% | 0.0% | 15.2 |
| hard | rumour_follower | -0.960 | 0.026 | -1.524 ± 0.041 | 2.2% | 2.2% | 0.0% | 7.0 |
| hard | do_nothing | 0.000 | 0.000 | -0.564 ± 0.032 | 0.0% | — | 100.0% | — |

## v1.5-candidate

| tier | agent | mean score | ±95% | diff vs solver (paired) | acc | acc when accusing | abstain (no accusation) | mean accusation day |
|---|---|---|---|---|---|---|---|---|
| medium | solver | 0.641 | 0.024 | — | 89.0% | 100.0% | 11.0% | 8.0 |
| medium | grok_tactics | 0.456 | 0.032 | -0.185 ± 0.038 | 75.0% | 99.0% | 24.2% | 8.5 |
| medium | heuristic | 0.067 | 0.076 | -0.574 ± 0.076 | 65.5% | 65.5% | 0.0% | 10.9 |
| medium | rumour_follower | -0.986 | 0.016 | -1.627 ± 0.029 | 0.8% | 0.8% | 0.0% | 7.0 |
| medium | do_nothing | 0.000 | 0.000 | -0.641 ± 0.024 | 0.0% | — | 100.0% | — |
| hard | solver | 0.571 | 0.030 | — | 96.5% | 97.0% | 0.5% | 8.9 |
| hard | grok_tactics | 0.371 | 0.037 | -0.200 ± 0.047 | 85.0% | 95.8% | 11.2% | 10.1 |
| hard | heuristic | 0.002 | 0.059 | -0.569 ± 0.066 | 74.5% | 74.5% | 0.0% | 14.9 |
| hard | rumour_follower | -0.995 | 0.009 | -1.566 ± 0.032 | 0.2% | 0.2% | 0.0% | 7.0 |
| hard | do_nothing | 0.000 | 0.000 | -0.571 ± 0.030 | 0.0% | — | 100.0% | — |

## Read-out

- Solver accuracy when accusing: medium 100.0%, hard 97.0% on v1.5-candidate (target >= 85%: met). Abstain rate: medium 11.0%, hard 0.5%.
- Solver stays clearly above grok_tactics (paired -0.185 ± 0.038 medium, -0.200 ± 0.047 hard) and heuristic (-0.574 ± 0.076, -0.569 ± 0.066).
- Bias trap: rumour_follower (accuses the most-rumoured colleague, authority x3) is right 0.8% (medium) / 0.2% (hard), mean ~ -0.99: it walks straight into the decoy the mole seeds.
- v1.4 -> v1.5 solver deltas are within noise (forwards slightly change holder sets; rumours are zero-information to it). Scripted baselines don't read rumours so they are not hurt; the trap targets agents that read and trust messages (LLMs).
- `make hunt TIER=all TV=v1.5-candidate`: 0 invariant violations, best non-solver score 0.000 on easy, medium, hard, hard_forge. An earlier run flagged template wording ("<id> is the mole" in an unseeded rumour that happened to name the real mole) as truth_leak; rumour bodies no longer use the word mole (regression test added).
- Not done: Gemini rendering of the social chatter (Gemini providers fall back to the template renderer via render_social; no key needed).
