# G3 Failure Atlas: report (newest first)

## Sat 14:50

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

**Finding for ENV (not an atlas bug):** in `g4carbon.in.v14.h6` (v1.4 hard seed 6) the reference solver's own
posterior, replayed from the agent's observations, puts ~0 on the true mole e34 from t≈65 and ~0.65 on the innocent
e18, so the agent's wrong accusation is what the solver would also have done. Worth a look at the solver's leak
model on that seed.

**Next:** full run on all 153 episodes with gemini-4-carbon discovery (running), validation sheet, commit results.

**Blockers:** none. **Spend so far:** ~$0.5 (probes + smoke).
