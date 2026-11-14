# G3 Failure Atlas: report (newest first)

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
