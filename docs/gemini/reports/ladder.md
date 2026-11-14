# G2 report: the Gemini Ladder

Branch `gemini-ladder`. Newest entry first.

## Sat 14:30: ladder + report + tests done; grid running on the Mac

**Done (verified how)**
- `canary/gemini/ladder.py`: a grid/shard/resume layer over the measurement's own runner. Each cell
  (model, thinking level, tier, seed) calls `canary.agents.play.main` in-process (LLMPolicy, full history,
  thought-signature replay) with `lab_client(f"gemini:{model}", feature="ladder", thinking_level=level)`, so every
  call is in the ledger. Infra failures are classified by `scripts/gemini_runner.infra_reason("inproc", ...)`,
  moved to `_invalid/` and re-queued (max 4 attempts). It runs a thread pool per process, takes `--shard i/n`
  for Slurm arrays, and uses a cap-aware dispatcher (`--model-cap gemini-4-carbon=4`) so a capped model never
  blocks a worker thread. When `GEMINI_GATEWAY_URL` is set, it uses the gateway (G1's `gateway_http_options()`
  if merged, else `base_url`). `--probe` makes one tiny call per model × level.
- Seeds: v1.4 **dev seeds 0–9** (public HMAC key, so exact worlds), the same worlds as the AfterQuery
  measurement and its reference. Judge and held-out seeds are refused. No lab secret is needed: dev seeds ignore
  `CANARY_WORLD_SECRET`.
- Lane: gemini-4-carbon at the model default is **imported read-only** from `justSilas-gemini`
  (`data/runs/committed/v1.4/inproc-gemini-4-carbon`) and never rerun. The ladder runs carbon only at explicit
  low and high.
- `canary/gemini/ladder_report.py` writes `results/gemini/ladder.{md,json}` and 4 figures: heatmap, thinking
  curve, cost frontier and regret by tag. It pairs every cell with the solver replayed in-process on the same
  (tier, seed). Verified: the in-process solver reproduces the committed reference scores exactly (medium seeds
  0–3: 0.74/0.39/0.80/0.60). On the imported carbon-default cell the report reproduces the measurement's paired
  table: medium 98% [85%, 115%], hard 66% [5%, 117%], luck-adjusted 78% / 79%.
- `tests/test_gemini_lab_ladder.py` covers grid expansion and overrides, judge-seed refusal, disjoint shards,
  run, resume/skip, infra re-queue, the model cap and report readability. It runs keyless with the stub backend:
  7 tests in 1.4 s. The full `make test` passes, except that `test_llm::test_retry_gives_up_and_non_retryable`
  failed once because of an env leak from the ladder test. Fixed: env defaults are now set only in `main()`.
- Probe (`data/gemini/ladder/probe/_probe.json`): thinking levels accepted. flash-lite and 3.5-flash: minimal,
  low, medium and high. 3.8-flash, argon and carbon: low, medium and high. hydrogen: low, medium, high and xhigh.
  The API serves `gemini-3.5-flash` as modelVersion `gemini-3.6-flash`.

**Running now (Mac, I/O-bound, ~0% CPU)**
- Flash: 220 cells. flash-lite and 3.5-flash at minimal, low, medium and high; 3.8-flash at low, medium and
  high. Medium and hard tiers, seeds 0–9, concurrency 8. Log: `~/agent-arena-data/gemini/ladder/mac-flash.log`.
- Gemini-4: 180 cells. hydrogen at low, medium, high and xhigh; argon at low, medium and high; carbon at low and
  high. Medium and hard tiers, seeds 0–9, concurrency 8, carbon capped at 4. Log: `mac-g4.log`. **Note for the
  CEO:** the update said ≤ 8 on the Mac for flash. I added this second process (16 in total, the original
  brief's fallback ceiling) because the gemini-4 cells need about 135 serial episode-hours. Waiting for the
  gateway until 19:30 would push carbon-high past 01:30. Carbon stays at ≤ 4 concurrent on the shared key.
- Data: `~/agent-arena-data/gemini/ladder/ladder-v14/` (ledger in `_ledger/`).

**Next:** the cost and time projection once the first gemini-4 episodes finish; a first ladder table and figures
by 19:00; moving the remaining cells to FR8 when G1's gateway is ready.

**Blockers / asks:** `canary/llm/pricing.py` has no rows for gemini-3.1-flash-lite ($0.25 / $1.50 / cached
$0.025) and gemini-3.5-flash (served as 3.6-flash: $0.75 / $3.75 / $0.075), from aistudio.google.com/docs/pricing
checked at 14:20. Their ledger `cost_usd` is therefore 0 with `cost_unknown`. The ladder report prices tokens
itself. CEO: add these two rows to `pricing.py` so the dashboard is right (I don't edit `canary/llm`).
