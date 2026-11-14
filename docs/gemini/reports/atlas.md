# G3 Failure Atlas: report (newest first)

DONE Sat 22:59

## Sat 22:59 (EET): blind atlas re-run

- **`--blind`**: the pack contains only agent-visible calls and results, the agent's own words, and the outcome.
  A test asserts that no REGRET, tags, `top=`, `mole:`, true_mole, total_regret or solver scores appear.
- **Run:** discovery and mining on the gemini-3.8-flash explicit cache, streamed: 153 episodes, 751k tokens.
  Served model_version `gemini-3.8-flash`; runs atlas-20261114-223741 and -224929; $2.73.
- **Result** (`results/gemini/atlas_blind.{json,md}`), scored in code against tags.py:
  - Recovered **3 of 5** code tags with recall >= 30%:
    - premature_accusation: 44%
    - ignored_delay: 2/2
    - budget_waste: 46%
  - Missed: uninformative_canary 0%, over_restriction 0%.
  - Named 2 modes our tags don't have:
    - canary fingerprint misattribution
    - passive delay / value depletion
  - Weak coverage: Gemini cited only 124 steps, 12% of them high-regret, covering 21% of all regret.
  - Quotes: 12 of 16 verbatim in the agents' own words.
- **v1:** atlas.md now opens with a "v1 was not blind" note; v1's files are otherwise unchanged.
- **Tests:** all 90 gemini lab tests pass.

## Sat 19:01 (EET, `date`): failure gallery (PLAN-95 B2) and atlas v2

**Failure gallery** (`python -m canary.gemini.gallery`): `docs/reports/failure_gallery.md`,
`results/gemini/failure_gallery.json`, plus `results/gemini/gallery_{cache,charts}`.
- **Scope:** 295 episodes, all rules versions, never pooled.
  - The AfterQuery measurement: gemini-4-carbon (in-process and OpenCode), gemini-3.5-flash OpenCode, Codex gpt-5.5
    v1.2/v1.3.
  - Every ladder episode on disk at 19:00.
  - The rest of the atlas corpus.
  - 10 Grok episodes on judge seeds are listed as skipped: no world secret, so no replay or solver baseline.
- **How the gap is accounted:**
  - gap = solver score - agent score on the same seed and rules, decomposed in code.
  - Both the agent's and the solver's recorded actions are replayed in the env, and the true-V drops per step are
    split by cause: leak, canary, restriction.
  - Fidelity: every replayed result and score matches the recording, except 2 results the harness itself produced
    (OpenCode output truncation, a rejected bash call).
  - Each part is assigned to a step and a category: wrong accusation (premature / decoy / evidence-backed luck),
    infrastructure error, slow commit, canary spend, restriction.
  - Luck and credit are explicit categories: leak-timing variance, early-commit credit, fewer-canaries credit, solver
    wrong or abstained.
- **Result:** net gap +90.795, tagged +90.795, **unexplained 0** (largest per-episode residual 4e-16). Tests in
  `tests/test_gemini_lab_gallery.py` check, on real committed runs, that the per-episode sums equal the gap.
- **Gemini's part:** gemini-3.8-flash named the 12 modes and quoted the agents; 40/40 quotes verbatim. Keyless
  `--replay` works (0 calls).
- **Headline:** wrong accusations on weak evidence (+63.0) and investigating past the solver's commit point (+23.7)
  dominate. 18.9 of the lost value is luck the solver's own posterior also backed. 7.8 was harness crashes
  (gpt-5.6-sol), not agent decisions.

**Atlas v2** (`results/gemini/v2/`; v1's headline is untouched):
- 111 episodes including ladder runs, capped per (model, thinking level) to fit one cache: 701k tokens.
- A thinking-level table computed in code.
- The carbon cross-check, run in 3 shards at LOW thinking, recovers 4/5 of the flash taxonomy's modes; 36/36 quotes
  verbatim.
- Blind multimodal localisation (belief-only chart, no regret in the excerpt) still matches the code 8/8.
- **Batch API is blocked on our key:** every request returns code 8 RESOURCE_EXHAUSTED inside a job that reports
  SUCCEEDED. This is recorded in the playbook.

**Also fixed:**
- The full5 clustering IndexError, with 2 regression tests.
- Cohorts are now split by thinking level.
- MCP-wrapped error results are compared correctly during replay.

**Next:**
- Rerun v2 with the full ladder once G2 finishes. Live discovery costs about $4.
- Retry the batch labels if the quota recovers.
- Read in Ivar's agreement score: `python -m canary.gemini.atlas_agreement`.

**Spend:** about $9.5 (atlas v1) + $7.4 (v2 runs) + $0.1 (gallery naming).
## Sat 18:27 (EET, `date`): atlas v1 committed

**Done (verified)**
- **atlas v1 results committed**: `results/gemini/atlas.{json,md}`, 8 charts (292 KB), `results/gemini/atlas_cache/`
  (1.1 MB: response cache plus corpus snapshot). Commit e4c68e4.
- **Discovery came from Gemini, not the fallback**: gemini-3.8-flash read the whole corpus in one sitting from an
  explicit context cache: 153 episodes, 9 cohorts, 792,862 tokens by count_tokens, 797,920 tokens cached. 13 further
  structured questions ran against the same cache: 11 label chunks, the cohort comparison and the solver
  counterfactuals. 3.99M input tokens were served from cache.
- **Failure modes, by share of all solver regret** (computed in code):
  - premature accusation on a sub-threshold posterior: 61%, 50 episodes;
  - narrow, uninformative canaries: 15%, 74 episodes;
  - costly early restriction: 9%;
  - accusing a decoy or framed innocent: 2%;
  - budget waste: 0%;
  - other: 3%.
  The labelled steps cover 90% of all regret (404 steps at regret >= 0.01).
- **Cross-family comparison** (by code; different rule versions, so not pooled):
  - Premature accusation is the top regret source for almost every cohort.
  - Grok (v1.2) loses most to restrictions (46%).
  - gemini-4-carbon inproc (v1.4) has the lowest premature share (41%), but 23% of its regret comes from one framed
    innocent (h6). That accusation was evidence-backed (bad luck).
  - Gemini's own reading: carbon runs about 50 interviews per episode and uses 3-variant canaries; GPT and Grok
    lean on restrictions and on accusing below 0.6. Gemini states the version caveat itself.
- **Verification**: 461/470 Gemini quotes verbatim (98.1%), 449 at the named step (95.5%); 9 dropped and listed in
  atlas.json.
- **Multimodal**: 8/8 divergence steps match the code's step. Honest caveat: the excerpt shown with the chart
  includes the per-step REGRET, so this agreement is partly given away. For v2, hide regret in the excerpt.
- **Embeddings**: 84 agent-rationale snippets, k=6, clusters named by Gemini. Purity vs the taxonomy labels 0.64
  (NMI 0.37).
- **Keyless replay**: `python -m canary.gemini.atlas --replay --charts 8 --embed` makes 0 live calls, uses 25
  recorded responses and rebuilds the same atlas.
- **Validation sheet** pushed: `docs/gemini/validation.md`, 30 claims (10 mode evidence, 12 step labels,
  5 counterfactuals, 3 localisations), plus `docs/gemini/validation_context.md` with the steps around each claim. For
  Ivar.
- **Fixes along the way**:
  - All generate calls stream. A non-streamed carbon call over 793k tokens was cut after 527 s.
  - max_output_tokens is set at the model ceiling. Discovery truncated at 32k after 31k thinking tokens.
  - Invalid structured output is never recorded for replay.
  - New cached questions think at "medium". Default thinking took 63k thinking tokens and ~8 min per question.
  - One SDK client, created under a lock (a racing second client was being closed).
  - Embeddings use one Content per text. gemini-embedding-2 merged a list of strings into ONE vector.
  - A failed discovery exits without writing atlas.json.

**Not in v1**
- Batch API labels: the batch job I cancelled was built on the fallback taxonomy.
- The carbon cross-check: 2 of 3 shards were truncated at default thinking, and the retry hit the client bug.
  Both are fixed in code and run in v2.

**Spend**: $9.54 across 157 atlas ledger calls, including every failed attempt; 21.8M of 27.0M input tokens were
cached.

**Next**: v2 with the ladder episodes (thinking-level question), the Batch API labels and the carbon cross-check.
**Blockers**: none.

## Sat 14:47 (EET, `date`)

**Done**
- Run 1 (14:30) lost its one-shot gemini-4-carbon discovery call: a non-streamed request over 793k tokens was cut by
  the server after 527 s (`RemoteProtocolError: Server disconnected`, nothing billed). The run fell back to the
  deterministic taxonomy, labelled 404/404 steps against it on the flash cache, and submitted a batch. **I stopped that
  process myself (pkill, 14:43) and cancelled its batch job** (`batches/vp4lpi7a...`, JOB_STATE_CANCELLED): both were
  built on the fallback taxonomy, which must never be published, so resuming the batch would have paid for useless
  labels. Run 1 cost $1.73 (cache creation $0.60 + 12 cached questions).
- Fixes (pushed): discovery is now a one-shot question over the whole corpus on the explicit 3.8-flash context
  cache; gemini-4-carbon re-reads the corpus independently in <=250k-token shards + one merge call (`--crosscheck`),
  mapped onto the taxonomy by flash; every generate call streams; a failed discovery exits without writing
  atlas.json (`--allow-fallback` only for drafts); the batch job runs concurrently with the cached questions.
- Merged gemini-track (133f546, fast-forward); all 60 gemini tests green. Atlas tests: 12.
- Ladder data loads: 44 episodes so far, tiers version now inferred from `ladder-v14`; dev seeds, so true moles known.

**Running:** run 2 (nohup, pid 91027, log `data/gemini/scratch/full2.log`), started 14:45.

## Sat ~14:30 (first entry; timestamp corrected)

**Done**
- `canary/gemini/atlas.py` + helpers (`atlas_data`, `atlas_gemini`, `atlas_schema`, `atlas_charts`, `atlas_report`,
  `atlas_agreement`). Pipeline: long-context discovery (one prompt, `models.count_tokens`), explicit context cache
  (`caches.create`) for the per-step labels / cohort comparison / solver counterfactuals / thinking-level question,
  belief-trace PNGs + multimodal localisation, gemini-embedding-2 clusters, Batch API labels, pydantic structured
  output everywhere, verbatim quote verification in code. Every response is stored gzip under
  `results/gemini/atlas_cache/` together with a corpus snapshot, so `python -m canary.gemini.atlas --replay` rebuilds
  the atlas keyless.
- Tests: `tests/test_gemini_lab_atlas.py`, 11 tests, keyless fake client, ~2-8 s (packing, transcript alignment,
  quote verification, schema, full pipeline with a fake Gemini, replay with zero live calls, deterministic fallback,
  agreement sheet round trip).
- Live smoke (12 episodes, gemini-3.8-flash for both roles): 83/83 quotes verbatim (96% at the named step), cache hit
  74k tokens per question, multimodal localisation agreed with the code's divergence step 2/2, $0.16.
- Corpus: 153 committed frontier episodes (gemini-4-carbon in-process + OpenCode v1.4, gemini-3.5-flash OpenCode v1.4,
  gpt-5.5 in-process v1.2/v1.3, Codex gpt-5.5 v1.2/v1.3, OpenCode gpt-5.6-sol v1.2, Grok replayed v1.2) =
  **793k tokens** (count_tokens, gemini-4-carbon): fits one prompt, no sharding yet.

**Gotchas** (also in the playbook): google-genai 3.x defaults to API `v1`, where `cachedContents` is a bare 404; use
`api_version="v1beta"`. gemini-4-* have no explicit caching (batch only), so caching runs on gemini-3.8-flash.

**Note on luck (no bug):** in `g4carbon.in.v14.h6` (v1.4 hard seed 6) the canary `c4-2` surfaced with variant Z at
t=64, which the reference solver's own posterior (replayed from the agent's observations) reads as evidence against
the true mole e34 (P 0.06 -> 0.002) and for the innocent e18 (~0.65). The agent's wrong accusation is what the
evidence supported; the atlas shows such episodes as "the solver was misled too" rather than as an agent failure.

**Next:** full run on all 153 episodes with gemini-4-carbon discovery (running), validation sheet, commit results.

**Blockers:** none. **Spend so far:** ~$0.5 (probes + smoke).
