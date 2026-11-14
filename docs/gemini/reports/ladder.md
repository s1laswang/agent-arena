# G2 report: the Gemini Ladder

Branch `gemini-ladder`. Newest entry first.

## Sat 19:01 (`date`: Sat Nov 14 19:00 EET 2026): headline cells on track; compute re-prioritised

- **Headline cells (need ≥ 6 paired seeds on both tiers), finished episodes at 18:57:**
  - 3.5-flash/medium: 8 + 8.
  - 3.5-flash/high: 8 + 9, plus 3 running.
  - 3.8-flash/high: 10 + 10.
  - 3.8-flash/low: 5 (medium) + 6 (hard). The medium cell gets its 6th+ seeds next, in phase 4.
- **Carbon low/high on hard:** 2 + 2, with 2 high running. g4c (argon + carbon, carbon ≤ 5) continues.
- **Phase 4** (armed in `bin/phase4.sh`; it fires when the priority flash process exits, keeping the Mac at 16 and
  carbon ≤ 8). Both launches are recorded:
  - (a) 3.8-flash low first, then the rest of the flash grid (3.5-flash minimal/low, flash-lite) at concurrency 3;
  - (b) a second carbon-only process (low/high, hard first) at concurrency 3.
- **Headline now generated from the table** (`ladder_report.headline`). The wording is gated on the CIs, for
  example "matches" only if both CIs contain 100%. It stays correct as seeds land. At 18:47:
  - 3.5-flash medium/high on hard: 92% [76, 113] and 102% [84, 129], 16/16 correct, $0.34–0.39 per episode
    against $1.30 for carbon-high;
  - flash-lite is below 0 in 8/8 cells;
  - 3.8-flash, low → high: medium −52% → 93% [80, 112]; hard 30% → 17%.
- **Keyless:** `results/gemini/ladder_episodes.jsonl.gz` and `ladder_ledger.jsonl.gz` (0.65 MB) are committed,
  and the report regenerates from them with `--runs results/gemini/ladder_episodes.jsonl.gz --ledger
  results/gemini/ladder_ledger.jsonl.gz` (round-trip test). `bin/refresh.sh` re-exports and commits.
- **Showcase:** carbon/high/medium/0 is recorded (105 calls); the other 5 cells are running. ETA about 19:45.
  Committed as `results/gemini/replay-ladder-showcase` when `lab_replay` writes its manifest.
- **Deadlines:** final report and figures by 00:45; the grid keeps running for the 06:00 refresh.

## Sat 18:23 (`date`: Sat Nov 14 18:22:05 EET 2026): after the outage, grid relaunched on the priorities, report v1.1 with headline findings

**Outage check (verified):**
- Both processes survived as processes. The **gemini-4 process (pid 63094) was hung** from 15:31 to 18:20: no
  ledger row for 170 min, with 8 sockets stuck ESTABLISHED on a network that had changed, and the 600 s client
  timeout never fired.
- The flash process had resumed by itself.
- **No episode was scored from the outage.** 0 API errors in the ledger, 0 infra-invalid attempts, and no
  `episodes.jsonl` written after 15:31 by the hung process. An episode that ends on an API/DNS exception is
  classed `end_reason=error`, moved to `_invalid/` and re-queued (`gemini_runner.infra_reason`). The cells that
  were in flight have no episode file, and the relaunch clears and re-runs them.
- Fix: the relaunched gemini-4 process uses a 300 s per-request timeout. `bin/wait.sh` now reports how long ago
  each process last wrote a ledger row, so a hang shows within minutes.

**Relaunched (Mac total 16, carbon ≤ 8), all new launches recorded through `with_gateway --record`, priorities
from the CEO:**
- `gemini-3.5-flash` and `gemini-3.8-flash` at medium/high, medium and hard, seeds 0–9: 38 cells to go,
  concurrency 6. Store: `data/gemini/replay-ladder-full`.
- `gemini-4-argon` (low, medium, high) and `gemini-4-carbon` (low, high), seeds 0–9 in seed-pair order, so n ≥ 4
  arrives first: 92 cells to go, concurrency 8, carbon ≤ 5. Store: `data/gemini/replay-ladder-full-g4`.
- Showcase: one cell per model (6 models) at high thinking, medium, seed 0, through
  `lab_replay --record ladder-showcase`, concurrency 2. It lands in `results/gemini/replay-ladder-showcase`
  with a manifest.
- Deferred: the rest of flash-lite and the 3.5/3.8-flash minimal/low cells beyond seed 5, plus gemini-4-hydrogen.
  They run only if slots free up.

**Report v1.1 (commit 8fa04b3):** 125 episodes, 29 cells. The headline block at the top of
`results/gemini/ladder.md` comes from `results/gemini/ladder_headline.md`; every number is in the table, with
its CI.
- 3.5-flash at medium/high on hard: 91% [71, 120] and 102% [73, 150] of the solver, 5/5 correct, $0.36–0.44
  per episode.
- flash-lite is below 0 in all 8 cells.
- 3.8-flash, low → high: medium −52% → 92%; hard 30% → 28%.
- Thinking cuts premature-accusation regret, not canary-design regret.

**Spend so far:** $44 at list price (ledger, feature=ladder).

## Sat 15:28 (`date`: Sat Nov 14 15:28:32 EET 2026): report v1 committed, provenance on every cell, subset tool

**Done (verified how)**
- **Ladder report v1:** `results/gemini/ladder.{md,json}` and 4 figures from 119 valid episodes in 29 cells
  (commit b3f7dba). Every flash cell has 4–6 seeds per tier; the first gemini-4 cells have 1–2 seeds. Ledger:
  6,547 calls, 0 errors, 0 infra-invalid episodes, $41 at list price.
- **Labelled real runs:** every cell's `meta.json` and `episode.meta.ladder` record `model_id`, `thinking_level`,
  `tiers_version` (v1.4), `launch_git_sha`, and a `code_fingerprint`. The fingerprint is a sha256 of the
  env/rules/world/harness/Gemini-client files. Because play.py's `git_sha` is HEAD at write time, it can move
  during a long run; the fingerprint pins the actual code. The two Mac processes predate this (they launched at
  2786c00 and 107c485). Their cells were backfilled with `--backfill-sha`, which first checks that
  `git diff <sha> -- <code files>` is empty, so the code is byte-identical (all 104 cells now carry fingerprint
  06ea9b6a0f68d1dc), and marks them `provenance_backfilled`. New launches record the API-served
  `model_version` too.
- **Showcase tooling:** `canary/gemini/ladder_subset.py` cuts a committable store out of a big recording. It
  replays the chosen cells through a proxy that computes the gateway's replay key (tag + request) and copies the
  matching responses, then writes a `lab_replay` manifest, so `make lab-replay` checks it. Tested by cutting 1
  episode out of G1's 4-episode store: `REPLAY OK`, and the manifest is identical to G1's. My pre-tag store and
  test are removed; G1's `lab_replay` is the one replay path.
- Merged gemini-track 8f0e028. Ladder tests: 10 passed in 1.9 s.

**First findings (small n: 4–6 paired seeds per flash cell; CIs are wide; read them as directions)**
- **gemini-3.1-flash-lite cannot do the task at any thinking level.** At minimal it accuses wrongly in 8/8
  episodes (−1.0). At low, medium and high it is right in 25–50% of episodes, so its mean is below 0, the score
  of doing nothing.
- **gemini-3.5-flash (served as 3.6-flash) is the surprise.** At medium it scores 126% [98, 179] of the solver
  on medium and 99% [72, 139] on hard, for about $0.20–0.47 per episode. That puts it on the cost frontier next
  to gemini-4-argon/high.
- **gemini-3.8-flash** needs high thinking on medium (92% [76, 121], 6/6 correct), but on hard it stays at
  17–30%.
- **Which mistakes does thinking fix?** Pooled over the three flash models, low → high cuts
  `premature_accusation` regret per episode by 0.19 on medium and 0.12 on hard, and cuts wrong accusations on
  hard (`other:accuse`) by 0.06. Canary design does not improve: `uninformative_canary` regret on hard rises
  from 0.002 to 0.038, with 54% of high-thinking episodes affected. So thinking buys better commit timing, not
  better experiments.
- The first gemini-4 cells (n = 1–2) are at about the solver on hard (carbon/high 102%, carbon/low 97%,
  argon/high 99%). The imported carbon-default cell is 66% [5, 117] with n = 10.

**Next:** when the flash grid finishes (≈ 16:35), its 8 Mac slots go to (a) a second gemini-4 process wrapped in
`with_gateway --record data/gemini/replay-ladder-full --model-limit gemini-4-carbon=8`, run-name ladder-v14, and
(b) a recorded showcase: one cell per model at high thinking, medium, seed 0 (6 episodes, ≈ 3 MB). That goes to
`results/gemini/replay-ladder-showcase` by 18:30, using `lab_replay --record` directly. The two running processes
are not restarted. The Mac stays at ≤ 16 concurrent episodes, carbon ≤ 8.

**Spend so far:** $41 at list price (ledger rows for feature=ladder).

## Sat 14:50: M1 met; projection; keyless record/replay of a ladder episode works

**Done (verified how)**
- **Smoke grid and more.** 60 valid episodes so far: every flash model at every level has seeds 0–1 on medium
  and hard. 0 infra failures and 0 API errors in 2,837 ledgered calls. `results/gemini/ladder.{md,json}` and the
  4 figures are committed as v0 (partial).
- **Record/replay showcase, proven on one cell.** I ran G1's gateway (`origin/gemini-gateway`, copied read-only
  to a scratch dir) on the Mac with `--record`, then ran the ladder cell gemini-3.1-flash-lite / high / medium /
  seed 0 through it: 70 calls, 280 KB of gzip. I replayed it with `--replay`, no key on either side
  (`GEMINI_API_KEY=` empty, gateway `--key-file /dev/null`). The episode reproduced exactly: 70/70 identical
  tool calls and results, score −1.0, 1 s wall. A scan of the recordings found no key and no token. Stored in
  `~/agent-arena-data/gemini/ladder/showcase/`. The other showcase cells (one per model, high, medium seed 0)
  will be recorded once the flash grid frees Mac slots.
- `ladder.py` now identifies the machine by `uuid.getnode()`: the Mac's hostname flips between
  "Silass-MacBook-Pro" and "Mac" with the network. Cells are claimed when a worker takes them, so extra processes
  can join the same output dir without running a cell twice.
- `canary/gemini/clash.py` (stretch): Gemini detective × Gemini mole in arena mode, both sides ledgered, with a
  stub test. It has not been run on the API yet.

**Projection for the full grid (400 Gemini episodes + imported carbon-default)**

| block | episodes | measured / estimated per episode | $ | episode-hours |
|---|---|---|---|---|
| flash: flash-lite (4 levels), 3.5-flash (4), 3.8-flash (3) × 2 tiers × 10 seeds | 220 | $0.05–0.6, 0.5–10 min (measured) | ≈ 70 | ≈ 18 |
| gemini-4-hydrogen (low, medium, high, xhigh) × 2 × 10 | 80 | ≈ $1, ≈ 25 min (est.) | ≈ 80 | ≈ 32 |
| gemini-4-argon (low, medium, high) × 2 × 10 | 60 | ≈ $1.8, ≈ 60 min (calls 22–38 s, measured) | ≈ 110 | ≈ 60 |
| gemini-4-carbon (low, high) × 2 × 10 | 40 | ≈ $2, ≈ 65 min (calls 23–41 s, measured) | ≈ 80 | ≈ 45 |
| showcase recordings + clash matrix (45 detective episodes) | ~50 | | ≈ 30 | ≈ 15 |
| **total** | | | **≈ $370 (< $800, so 10 seeds kept for gemini-4)** | ≈ 170 |

Time: the Mac runs 16 episodes at once (8 flash + 8 gemini-4, carbon ≤ 4), I/O-bound at ~0% CPU. Flash
finishes ≈ 17:00, and its 8 slots then go to gemini-4. At 16 slots the gemini-4 block finishes ≈ 01:00–03:00.
Cells are ordered seed-pair-major (seeds 0–1 for every model and level, then 2–3, ...), so a cut at 01:30 still
leaves ≥ 6 seeds per gemini-4 cell. FR8 through the gateway would add capacity: ssh to FR8 works again from this
Mac (14:31; G1's report still says it is blocked), but the gateway is not deployed there yet. **Ask (CEO):** the
FR8 gateway or permission to go above 16 on the Mac (I/O-bound) would finish 10 seeds well before 01:30.

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
