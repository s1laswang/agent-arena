# Sleeper Surface-Tells Audit on Canary v1.4 (`scripts/sleeper_surface_tells.py`)

*Reproduce offline with zero API keys: `python scripts/sleeper_surface_tells.py --check`. Every figure below comes directly from deterministic sweeps over `200` public dev worlds (`0..199`) and `40` secret-salted judge worlds (`900000..900039`, `--world-secret canary-anticheat-public-test-v1`, matching `results/anticheat/exploits.md`).*

## 1. Why This Port Exists: Sleeper Issue 38 (`vaishnav/sleeper-tells`) -> Canary v1.4

In the earlier multi-seat Sleeper environment (`origin/vaishnav/sleeper-tells`, commits `2b474dcf`, `8e3b534a`, and `e08b62ff`), red-team hunts uncovered non-evidential generator and scripted-actor surface tells across four lenses (`H2` through `H5`): distinct attack-ticket wording templates plus extra per-day ticket counts and fixed arrival ticks (`template_clf.py` / `tmplagent.py` / `swap_in`, scoring `0.95..1.00` without security checks), integer payment amounts, `XX` IBAN prefixes, and `V04..V07` vendor pools (`tell_scan.py` / `intfilter`), a literal `'Handled per request.'` audit note and off-poll close ticks (`tell_study.py` / `legal_study.py`, naming the sleeper on `83/83` sleeper days), and skewed seat priors plus tick-0 ticket-count error probes (`prior.py` / `count_probe.py`).

This audit ports all five Sleeper surface-tell lenses onto Canary v1.4's one-agent investigation game without touching protected environment files (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`), verifying zero surface tells across world rosters/docs, inbox messages/interviews, access logs, and Panel Fix D (`1bc3e281`) tool-error details, paired with four planted-tell positive controls.

| Lens | Sleeper Origin (`vaishnav/sleeper-tells`) | Canary v1.4 Surface Audited | Verdict |
|---|---|---|---|
| `H2` | `redteam/hunt/template_clf.py + tmplagent.py + sleeper/detell.py` | Inbox day_messages (templates, sender volume, slot order, length, lexical LOSO) and interview_answer across TemplateProvider, MinimalProvider, and GeminiWorldText | **PASS (0 tells)** |
| `H3` | `redteam/hunt/tell_scan.py + policies.py (intfilter) + fraud V04..V07` | World list_employees, list_documents (incl. v1.4 multi-canary c1/c1-2), and check_leak_feed schemas, key ordering, ID patterns, name/role pools, and clearance fields | **PASS (0 tells)** |
| `H4` | `redteam/hunt/tell_study.py + tellagent.py + legal_study.py + swap_in` | read_access_logs row ordering under framing, status/advance_day visible V under leak delay, and MoleView canary blindness | **PASS (0 tells)** |
| `H5` | `redteam/hunt/prior.py + count_probe.py + Panel Fix D (1bc3e281)` | Mole/decoy seat, department, and clearance priors across dev and salted judge seeds; day-1 doc counts; tool error constants and data.detail target parity | **PASS (0 tells)** |
| `BENCH` | `redteam/hunt/seat_eval.py (tmplonly, intfilter, telltrust vs reference, do_nothing)` | Five zero-canary surface-tell policies evaluated through Env.call on salted JUDGE_SEEDS against do_nothing and SolverPolicy | **PASS (0 tells)** |

## 2. Lens H2: Inbox Message & Interview Wording, Volume, and Slot-Order Parity (`template_clf` + `e08b62ff` Port)

- **Structural mole-blindness:** `PublicDayFacts` contains `mole` field = `False`; mole-swap invariance diffs across `TemplateProvider`, `MinimalProvider`, `GeminiWorldText`, and `Env.advance_day` inbox = **`0`**; `canary.text.lint` failures = **`0`**; `world_builder` truth-key/truth-word leaks = **`0`** (note: `assert_no_truth`'s `tones[0] in others` check raised `5` small-roster coupon-collector flags across `75` worlds because i.i.d. uniform draws over `7` tones give any employee a `(6/7)^(N-1)` unique-tone chance identically for mole and innocents).
- **Angry-chatter surface outlier (`_ANGRY`):** In `medium` and `hard` (`decoy=True`), `100%` of angry messages belong to the innocent `decoy` (`0` from the mole, `0` from other innocents). Treating angry surface text as a mole tell yields **`0.0%` mole accuracy** (`-1.000` score), whereas eliminating the documented decoy yields only the stated `1/(N-1)` prior (`5.26%` medium, `2.56%` hard).

| Tier | Worlds | Mole msgs (`doc_mail`/`chatter`/`angry`/`unmatched`) | Innocent non-decoy msgs (`doc_mail`/`chatter`/`angry`/`unmatched`) | Msgs/emp/ep (`mole` vs `inn`) | Mean slot pos (`mole` vs `inn`) | Doc recip rate (`mole` vs `inn`) | LOSO hits/N (acc, `p`) | Interview `chi2` (`df`, `p`) |
|---|---|---|---|---|---|---|---|---|
| `easy` | `200` | `239/384/0/0` | `2448/3856/0/0` | `3.12` vs `2.87` | `0.498` vs `0.500` | `49.9%` vs `49.5%` | `18/200` (`9.00%`, `p=0.4024`) | `32.39` (`24`, `p=0.1174`) |
| `medium` | `200` | `128/151/0/0` | `2369/2586/0/0` | `1.40` vs `1.38` | `0.500` vs `0.488` | `49.3%` vs `49.9%` | `11/200` (`5.50%`, `p=0.4843`) | `31.40` (`24`, `p=0.1423`) |
| `hard` | `200` | `61/65/0/0` | `2539/2687/0/0` | `0.63` vs `0.69` | `0.493` vs `0.485` | `40.2%` vs `40.1%` | `6/200` (`3.00%`, `p=0.4068`) | `27.75` (`24`, `p=0.2704`) |

## 3. Lens H3 & H4: World Schema/Vocab Parity, Canonical Log Sorting, and Known-V Timing

| Track | Roster key/ID/vocab mismatches (`n=200`) | Doc/canary schema mismatches | Leak-feed schema/unknown mismatches (`n=60`) | Closed log days (`n=60`) | Unsorted log days (AH inversions) | Counterfactual framed-tail days prevented | Hidden-leak states (`known_V` leaks) |
|---|---|---|---|---|---|---|---|
| `easy` | `0/0/0` | `0/0` | `0/0` (`700` items) | `780` (`9364` rows) | **`0`** (`0`) | `0` | `0` (**`0`** leaks) |
| `medium` | `0/0/0` | `0/0` | `0/0` (`524` items) | `780` (`16797` rows) | **`0`** (`0`) | `755` | `473` (**`0`** leaks) |
| `hard` | `0/0/0` | `0/0` | `0/0` (`648` items) | `1200` (`49708` rows) | **`0`** (`0`) | `1198` | `884` (**`0`** leaks) |
| `hard_forge` | `0/0/0` | `0/0` | `0/0` (`217` items) | `1200` (`49771` rows) | **`0`** (`0`) | `1198` | `340` (**`0`** leaks) |

- **Why `logs.sort(...)` is load-bearing (H4 parallel):** In `Env._t_advance_day`, genuine accesses are generated in employee order `e00..e{N-1}` and framed `after_hours` accesses (`p.framing` and Mole DSL `frame`) are appended afterwards, then canonically sorted by `(employee, doc_id, after_hours)`. Without that canonical sort, framed rows would sit out of employee order at the tail of each day's access log across hundreds of days per sweep (an exact analog of Sleeper's off-poll close timing tell). With canonical sorting, **`0`** days violate sort order and **`0`** `(employee, doc_id)` pairs invert `after_hours` ordering.
- **MoleView canary-blindness:** `MoleDoc` exposes only (`doc_id`, `title`, `recipient_count`, `age_days`) (`is_canary` hidden = `True`, Mole DSL numeric-only features = `True`).

## 4. Lens H5: Day-1 Priors, Salted Judge Separation, and Panel Fix D (`1bc3e281`) Error-Detail Parity

| Track | Dev mole-ID `chi2` (`df`, `p`) | Max single-ID share (uniform `1/N`) | Dept `chi2` (`p`) | Day-1 docs `(2, 3, 4)` (`p`) | Salted judge `chi2` (`p`) | Public-key roster collisions (`n=40`) | Error parity / mole-ID leak mismatches |
|---|---|---|---|---|---|---|---|
| `easy` | `8.80` (`11`, `0.6414`) | `e01: 10.5%` (`8.3%`) | `1.00` (`0.8036`) | `64/65/71` (`0.8077`) | `8.60` (`0.6599`) | **`0`** | **`0 / 0`** |
| `medium` | `23.20` (`19`, `0.2282`) | `e11: 9.5%` (`5.0%`) | `1.16` (`0.7659`) | `66/73/61` (`0.5856`) | `17.00` (`0.5903`) | **`0`** | **`0 / 0`** |
| `hard` | `36.00` (`39`, `0.6077`) | `e37: 4.5%` (`2.5%`) | `4.45` (`0.3486`) | `61/71/68` (`0.6792`) | `62.00` (`0.0110`) | **`0`** | **`0 / 0`** |
| `hard_forge` | `54.40` (`39`, `0.0516`) | `e30: 6.0%` (`2.5%`) | `1.40` (`0.8454`) | `83/60/57` (`0.0468`) | `44.00` (`0.2680`) | **`0`** | **`0 / 0`** |

## 5. Surface-Tell Policy Benchmark on Salted Judge Seeds (`seat_eval` Port, `n=40` per Track)

In Sleeper v1, `tmplonly` and `intfilter` scored `1.000` on judged seats without reading policy docs or verifying evidence. Below are their direct Canary v1.4 ports (trained on `120` dev worlds, evaluated through `Env.call` with zero canaries on the `40` salted judge seeds `900000..900039` under `canary-anticheat-public-test-v1`) paired against `do_nothing` and `SolverPolicy`:

| Policy | `easy` mean +- CI95 (acc) | `medium` mean +- CI95 (acc) | `hard` mean +- CI95 (acc) | `hard_forge` mean +- CI95 (acc) | Blocked |
|---|---|---|---|---|---|
| `do_nothing` | `+0.000 +- 0.000` (`0.0%`) | `+0.000 +- 0.000` (`0.0%`) | `+0.000 +- 0.000` (`0.0%`) | `+0.000 +- 0.000` (`0.0%`) | **yes** |
| `surface_roster_prior` | `-0.900 +- 0.137` (`5.0%`) | `-0.900 +- 0.137` (`5.0%`) | `-0.900 +- 0.137` (`5.0%`) | `-0.950 +- 0.098` (`2.5%`) | **yes** |
| `surface_angry_tell` | `-0.856 +- 0.159` (`7.5%`) | `-1.000 +- 0.000` (`0.0%`) | `-1.000 +- 0.000` (`0.0%`) | `-1.000 +- 0.000` (`0.0%`) | **yes** |
| `surface_msg_template_clf` | `-0.814 +- 0.175` (`10.0%`) | `-0.954 +- 0.090` (`2.5%`) | `-0.905 +- 0.130` (`5.0%`) | `-0.951 +- 0.096` (`2.5%`) | **yes** |
| `surface_iv_subtemplate` | `-0.854 +- 0.161` (`7.5%`) | `-0.852 +- 0.163` (`7.5%`) | `-0.904 +- 0.132` (`5.0%`) | `-0.902 +- 0.133` (`5.0%`) | **yes** |
| `surface_log_tail_probe` | `-0.586 +- 0.241` (`22.5%`) | `-0.904 +- 0.131` (`5.0%`) | `-0.954 +- 0.091` (`2.5%`) | `-0.855 +- 0.160` (`7.5%`) | **yes** |
| `solver` | `+0.765 +- 0.051` (`97.5%`) | `+0.671 +- 0.068` (`92.5%`) | `+0.545 +- 0.098` (`92.5%`) | `+0.456 +- 0.127` (`87.5%`) | **ref** |

## 6. Committed v1.4 Frontier Transcript Audit & Planted-Tell Positive Controls

### Committed v1.4 Frontier Cohorts (`152` Episodes, Zero Live API Calls)

| Committed v1.4 Cohort | Episodes | Day-1 Accusations | Zero-Canary Accusations | Planted Canaries | Checked Leak Feed | Mean Canaries | Mean Final Day |
|---|---|---|---|---|---|---|---|
| `opencode:google/gemini-4-carbon (medium, 0..29)` | `30` | **`0`** | **`0`** | `30/30` | `30/30` | `5.83` | `7.97` |
| `opencode:google/gemini-4-carbon (hard, 0..29)` | `30` | **`0`** | **`0`** | `30/30` | `30/30` | `8.47` | `13.43` |
| `opencode:google/gemini-4-carbon-ext (hard, 30..59)` | `2` | **`0`** | **`0`** | `2/2` | `2/2` | `5.50` | `5.50` |
| `opencode:google/gemini-3.5-flash (hard, 0..29)` | `30` | **`0`** | **`0`** | `30/30` | `30/30` | `12.43` | `12.70` |
| `inproc:google/gemini-4-carbon (medium, 0..29)` | `30` | **`0`** | **`0`** | `30/30` | `30/30` | `6.93` | `9.70` |
| `inproc:google/gemini-4-carbon (hard, 0..29)` | `30` | **`0`** | **`0`** | `30/30` | `30/30` | `8.57` | `12.97` |

### Planted-Tell Positive Controls (Proving Every Scanner Has Teeth)

| Synthetic Sleeper-v1 Bug Planted | Target Lens | Triggered / Caught | Measured Diagnostic |
|---|---|---|---|
| `planted_h2_mole_wording_tell` (mole sends `'Handled per request...'` chatter) | `H2` | **`True`** | LOSO message-only accuracy jumps to `100.0%`, `200` unmatched non-decoy msgs |
| `planted_h3_mole_key_order_tell` (`name` before `id` on mole roster dict) | `H3` | **`True`** | `20/20` worlds flagged for key-order drift |
| `planted_h4_unsorted_framed_logs` (decoy framed `after_hours` left at day tail) | `H4` | **`True`** | `107` closed log days flagged for tail ordering tell |
| `planted_h5_error_parity_leak` (mole-specific `data.detail` leak on invalid call) | `H5` | **`True`** | `120` tool-error parity mismatches flagged |

## 7. Known Limits & Honest Distinction Between Documented Signals and Tells

1. **Documented weak behavioral signals are intentional, not surface tells:** `instruction.md` explicitly gives the agent `interview_lr` (`1.5 / 1.3 / 1.2`), `p_after_hours_mole` (`0.15 / 0.15 / 0.30` vs `0.10`), and the angry `decoy` rule (`1/(N-1)` non-decoy prior). None of those alone reaches positive expected score on `medium`, `hard`, or `hard_forge`; winning requires active canary group-testing.
2. **Leak-feed arrival order (`check_leak_feed`):** Because `self._feed` appends leaks in leak-day order while `delay_choices` spans `(1, 2, 3)` on `medium` and `(2, 3)` on `hard`, consecutive leaks can surface with `surfaced_day[i] > surfaced_day[i+1]`. That ordering only constrains when an already-public `doc_id` leaked inside `leak_window_days` and never exposes any employee ID beyond `list_documents` recipients.
3. **Scope of text-provider audit:** This offline suite audits `TemplateProvider`, `MinimalProvider`, `GeminiWorldText` deterministic rendering, Panel Fix D (`1bc3e281`) error details, and all `152` committed v1.4 transcripts. Any future live-generated `GeminiProvider` world caches should run `canary.text.lint` plus `scan_template_wording_tells` before freezing.
