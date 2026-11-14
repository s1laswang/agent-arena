# CONTRACT v0: Canary (catch the mole)

This is what lets five departments build in parallel. Code-level truth is in `canary/rules.py` and `canary/types.py`, and the `Env` signatures are in `canary/env.py`.
- **Changing a signature or a mechanic:** the ENV head decides. Bump the version here and add a line to `docs/reports/CEO.md`.
- **Tuning numbers in `rules.py`:** allowed. Note it in your report.

## 1. The game, in one paragraph
A fictional company (tiers: easy 12 / medium 20 / hard 40 employees; hard was 30 up to v1.3) has exactly one **mole** who leaks sensitive documents to a rival. Each leak costs company value V, which starts at 1.0. The agent is the head of security. It can:
- read access logs and messages;
- interview staff;
- plant **canary documents** (different variants to different groups);
- watch the **leak feed**, where leaked docs surface after a delay carrying their variant tag;
- restrict an employee's access (costs value per day).

It must **accuse exactly one employee, exactly once.** Score = V at the moment of accusation if correct, otherwise 0. The episode lasts at most `n_days` days (easy/medium 14, hard 21 since v1.4). Doing nothing scores 0.

## 2. Mechanics (the env and the solver MUST implement the identical model)
- **World(tier, seed):** generated deterministically.
  - Employees `e00..eNN` have a synthetic name, a department (4–5 departments) and a role. In the hard tier they also have a clearance level.
  - The mole is uniform among non-decoy employees.
  - In medium and hard, the decoy is one innocent employee who writes angry messages.
- **Documents:** each day 2–4 regular sensitive docs are published to recipient lists (department-wide or cross-department). Every doc has `doc_id`, `title`, `day`, `recipients`.
- **Day loop.** `advance_day` closes day d:
  1. **Leak.** If the mole has ≥1 *leakable* doc (received in the last 3 days, not yet leaked), then with probability `p_leak` it leaks one. The choice is uniform over leakable docs. Exception, when `careful_mole` is set: a canary doc's weight is multiplied by (1 − share of staff who received *any* variant of it).
  2. **Delay.** The leak surfaces in the feed on day d + δ, with δ ~ Uniform(`delay_choices`).
  3. **Value.** V −= `leak_damage` at leak time. `status` shows the true V.
  4. **Restriction cost.** Each restricted employee costs `restrict_cost_per_day`. A restricted employee receives no new docs and cannot be given canaries; it can still leak docs it already holds.
  5. **Access logs.** Each employee accesses sensitive docs it holds at Poisson rate `log_rate_benign`; the mole at `log_rate_mole`.
     - A fraction of accesses are flagged `after_hours`. The mole's after-hours rate is higher.
     - With `framing`, the mole injects after-hours accesses attributed to other employees, preferring the decoy.
     - **Every rate is stated in `instruction.md`.**
  6. **Text.** The day's messages are rendered by the TextProvider from public facts only.
- **Canaries.** `plant_canary(doc_title, assignment={employee_id: variant_label})`:
  - at most `max_variants` distinct labels;
  - at most `canaries_per_day` per day;
  - costs `canary_cost`;
  - with `access_constraints`, recipients must have clearance.

  A canary is a new doc delivered today. Recipients are exactly the keys of `assignment`. When a canary leaks, the feed shows its variant label.
- **Interviews.** `interview(employee, topic)` returns text rendered from a signal: `evasive` with probability `p_evasive_innocent × (interview_lr if mole else 1)`, otherwise `cooperative`.
- **Caps.**
  - Investigative tools (`types.INVESTIGATIVE_TOOLS`) are limited to `actions_per_day` per day. After that they return `ok=False, error="daily action limit; call advance_day"`.
  - `status`, `list_*`, `advance_day` and `accuse` don't use daily slots.
  - Every call counts toward `tool_call_cap` (easy/medium 300, hard 420 since v1.4). Reaching it ends the episode with score 0.
- **End of episode.**
  - `accuse` ends it: score = V if correct, else 0.
  - Passing day `n_days` without an accusation ends it with score 0.
  - After the end, every call returns `ok=False` and changes nothing.

## 3. Tools (MCP mirrors `Env.tools_spec()` 1:1)
| Tool | Args | Returns |
|---|---|---|
| `status` | none | day, V, actions_left_today, tool_calls_left, restricted[], canaries_planted[] |
| `list_employees` | none | [{id, name, dept, role, clearance?}] |
| `list_documents` | `day_from?`, `day_to?` | [{doc_id, title, day, recipients[], is_canary, variants?}] |
| `read_access_logs` | `day_from`, `day_to`, `employee?` | [{day, employee, doc_id, after_hours}] |
| `search_messages` | `query`, `day_from?`, `day_to?` | [{id, day, channel, sender, subject, snippet}] (max 20) |
| `read_message` | `id` | full message |
| `interview` | `employee`, `topic ∈ {recent_documents, contacts_outside, workload, access_needs}` | answer text |
| `plant_canary` | `doc_title`, `assignment{employee: variant}` | canary_id (`c<day>`; a 2nd canary the same day is `c<day>-2`) |
| `check_leak_feed` | none | [{surfaced_day, doc_id, title, variant?}] |
| `restrict_access` / `unrestrict_access` | `employee` | ok |
| `advance_day` | none | new day summary |
| `accuse` | `employee` | final: {accused, episode_over: true}. **Correctness is NOT revealed to the agent.** |

Validation is strict: one employee id per call (no lists, no `*`, no names in place of ids), integers in range, and unknown args rejected.

## 4. Reward and integrity
- The reward is computed from the server-side ledger only and never from agent text.
- The MCP server process owns the Env. The grader reads `GET /ledger?token=…` (not an MCP tool) and writes `/logs/verifier/reward.txt`.
- The truth (the mole id, the seed→world mapping for judge seeds) never enters the agent's container or filesystem.
- Seeds:
  - dev: 0–9,999
  - judge: 900,000–900,029 per tier (frozen; text committed in `data/worlds/judge/`)
  - train: 100,000–199,999
  - held-out: 800,000–800,199

## 5. Shared artifacts
- **Episodes:** `data/runs/<run_id>/episodes.jsonl`, one `types.EpisodeResult` per line. `run_id = <agent>-<tier>-<YYYYmmdd-HHMM>`.
- **Run metadata:** `data/runs/<run_id>/meta.json` holds agent, model, provider, git sha and seeds.
- **Regret:** `canary.solver.regret.attribute(episode) -> list[{t, action, regret, tags[]}]`.
- **Policies:** each implements `types.Policy`. Runner: `canary.eval.run_episode(env, policy) -> EpisodeResult`.
- **LLM clients:** `canary.llm.get_client(spec)`. Text: `canary.text` TextProvider (no mole identity in its input).

## 6. Reporting metrics (every table uses these)
- mean score ± 95% CI over seeds;
- accuracy (correct accusation rate);
- mean day of accusation;
- solver-normalised score (agent / solver on the same seed);
- pass^k over repeated runs;
- baselines: do-nothing, stop-early (random accusation on day 1), random, restrict-all.

---

## 7. v0.1 additions (01:55, additive only): Mole DSL + Mole Forge
**Why:** Gemini *evolves the mole* (AlphaEvolve/FunSearch-style). Evolved moles form the hard judge tier. This makes Gemini essential and builds the gap by design.

- **`canary/mole/dsl.py` (ENV).** A JSON rule language plus a deterministic interpreter.
  - `MoleStrategy.from_json(obj)`, then `.decide(view: MoleView) -> {"leak": doc_id | None, "frame": employee_id | None}`.
  - **`MoleView` holds only what the mole can see:**
    - the docs it holds, with their `recipient_count`, `age_days` and `title`;
    - `days_since_last_leak` and `i_am_restricted`;
    - `n_restricted_colleagues` and `recent_low_recipient_docs` (a "this looks like a trap" feature);
    - today's day number.

    The mole never sees which docs are canaries, or anything about the investigator except restrictions.
  - **Rules:** an ordered list of `{"if": [<feature> <op> <number>, ...], "then": {"leak": "<selector>"|null, "frame": "<selector>"|null}}`.
    - Selectors: `newest`, `oldest`, `most_recipients`, `fewest_recipients`, `random_seeded`, `none`.
    - Frame selectors: `decoy`, `most_restricted_peer`, `random_peer`, `none`.
    - The first matching rule wins. There's a default rule. `p_leak` still gates leaking.
    - Max 12 rules. The interpreter rejects anything else; there's no code execution.
  - **`DEFAULT_STRATEGY`** reproduces the v0 mechanics exactly (§2), so existing tests keep passing.
  - **`instruction.md` documents the language**: what a mole may condition on and do. The investigator knows the space of attacker behaviour, so nothing is hidden.
- **`World.mole_strategy`** holds the default, or a frozen evolved strategy per judge seed in `data/worlds/judge/<tier>/<seed>.mole.json`.
- **`canary/forge/` (AGENTS; FR8 runs it).**
  - `evolve.py`: a population of strategies. Mutation and crossover come from the LLM: `stub` makes random edits tonight; `gemini:<model>` in the morning gets the parent strategies, their fitness and the failure tags of the investigators they beat.
  - **Fitness** = mean regret (solver score − investigator score) over K dev seeds, **subject to solver score ≥ 0.5 × its score on the default mole and solver accuracy ≥ 85%.** Every evolved mole stays provably catchable.
  - Outputs: `data/forge/<run>/hall_of_fame.jsonl` and a per-generation `log.jsonl` (for the "500 generations" chart).
  - The investigator population: the heuristic policy, the hinted heuristic, and (when available) the LLM policies.
- **Solver requirement (ENV):** inference must be **robust to any DSL strategy**. Canary and leak evidence (a leaked variant implies the mole is in that variant's group) is strategy-independent and primary. Behavioural signals (logs, timing) are down-weighted and treated as optional. Solvability is verified per evolved mole.

---

## 8. v0.2 (02:30): judge-world integrity
- World seed = `int.from_bytes(HMAC-SHA256(key, f"{tier}:{seed}")[:8], "big")`; key = `b"public"` for dev/train; for judge and held-out seeds, `CANARY_WORLD_SECRET`, else `data/worlds/judge/SALT` (server image only).
- The seed is never exposed (status, tool results, text). `accuse` returns an identical payload for every valid id. All errors come from one fixed set (`env.ERRORS`) and never vary by target.
- `env._world.mole` is the server-only test accessor. `Env.call` is serialised by a lock.

## 9. v0.3 (03:00): wrong accusation = −1
- Score = V if the accusation is correct; **−1.0 (`rules.wrong_accusation_score`) if wrong**; 0 for no accusation, horizon or tool cap. Stated in `instruction()`.
- Consequence: stop-early and random have negative expected score; accusing is a decision (accuse only if P·V − (1−P) beats waiting).
- Mole DSL (§7) shipped in `canary/mole/dsl.py`; extra feature `n_leakable`; `Env(..., mole_strategy=MoleStrategy|dict)`.

## 10. v0.4 (03:40): imperfect fingerprints + speed stakes
- `fingerprint_accuracy` (default 1.0): a leaked canary shows the true variant with this probability, else uniformly one of the canary's OTHER planted variants. Stated in instruction(). No RNG draw at 1.0 (v0 determinism kept).
- Tuning targets (FR8 J1 picks values): fingerprint_accuracy easy 1.0 / medium 0.9 / hard 0.8; leak_damage medium/hard 0.06-0.08; actions_per_day 5 on medium/hard.

## 11. v0.5 (04:20): judge worlds fail closed
- Judge/held-out seeds never use the public key. With no `CANARY_WORLD_SECRET` and no `data/worlds/judge/SALT`, a fresh 32-byte secret is generated per process (memory only; logs its sha256 prefix). Keyless `make reproduce` is statistical (mean ± CI); the secret reproduces exact numbers.
- Only non-truth artifacts are committed: Forge mole strategies and truth-independent text banks. No world.json with the mole.

## 12. Tiers v1.2 FROZEN (02:55 EET 14 Nov)
- `rules.TIERS_VERSION = "v1.2"`, values pinned by `tests/test_env_frozen.py` (hash eb77b13554f366aa). Bug fixes only after this; judge set, training data v2 and frontier runs use v1.2.
- CEO pick from FR8 final co-tune: easy/medium unchanged (fingerprint 1.0); HARD fingerprint_accuracy 0.95, framing_rate 2.0; solver behaviour_weight 0.6.
- FR8 800-fresh-seed check of this cell: hard acc .841, no-accusation .126, medium−hard .070±.032. Fresh-seed table (seeds 1000-1399) in docs/reports/env.md.

## 13. v1.3: known V
**Why:** with true V in `status`, a same-day V drop revealed a leak before it surfaced, so `delay_choices` stopped mattering.

- **Shown V (`status`, `advance_day`, key `"V"`) = known V:**
  - known V = max(0, 1 − `leak_damage` × #(leaks with `surfaced_day` ≤ current day) − all costs so far);
  - the costs are canary costs and restriction costs, which the agent knows about.
- **True V** (`env.V`) includes damage from leaks that have not surfaced yet. It is used for the score (correct accusation → true V at that moment), for the ledger and for `verdict()`. The agent never sees it during the episode.
- **Toggle:** `rules.KNOWN_V_MODE = True`. Setting it to False restores the v1.2 behaviour (status shows true V). It is a module constant, not a TierParams field.
- **Version:** `TIERS_VERSION = "v1.3"`. `tests/test_env_frozen.py` pins the hash of TIERS + KNOWN_V_MODE together. The numbers are final at the re-freeze.
- `instruction.md` states: "V shown is the value you can see: damage from leaks that haven't surfaced yet is not visible until they surface. Your score uses the true V, which includes undetected damage."

- FR8 recal (03:3x): KEEP defaults. Confirmed on 800 fresh seeds/tier (5000-5799): solver .779/.632/.575, acc .996/.887/.848, no-accusation .003/.113/.114; grok_tactics .690/.459/.342 (paired solver-grok .089+-.016/.174+-.025/.233+-.040); heuristic .648/-.007/-.257; logs_only acc .278/.014/.016. Fresh 1000-1399 table: results/fresh_table_v1.3.md.

## 14. Tiers v1.4 FROZEN: long-horizon hard (14 Nov)
**Why:** in the official v1.3 measurement (docs/reports/gap.md), Codex gpt-5.5 over MCP, which is the judges' harness shape, scored **97% of the reference solver on hard** on the planned seeds 0–9 (106% with seed 10; 11/11 correct). On medium the only gap was 2 early wrong accusations, and the CI reached parity. Frontier agents are good at "reach certainty, then accuse" when the evidence is compact. v1.4 makes hard about what exact Bayesian bookkeeping does well and LLMs do badly: many concurrent, delayed, noisy tests over a long horizon, under time pressure, plus the commit decision. It is a **pure parameter change**: no new tools, no new mechanics, and the reward is unchanged (agreed with the ENV head).

- **Hard only** (easy and medium keep their v1.3 values; monotonicity holds):

  | hard | v1.3 | **v1.4** |
  |---|---|---|
  | `n_employees` | 30 | **40** |
  | `n_days` | 14 | **21** |
  | `canaries_per_day` | 1 | **2** |
  | `max_variants` | 2 | **3** |
  | `leak_damage` | 0.035 | **0.05** |
  | `tool_call_cap` | 300 | **420** (20 per day) |

  Unchanged: `KNOWN_V_MODE`, delays 2–3, careful mole, framing 2.0, decoy, fingerprint accuracy 0.95, p_leak 0.65, canary cost 0.01, 8 actions a day. Every value is stated in `instruction()` (prose plus the "Exact parameters" block). `harbor/build.py` renders each task's instruction from `Env.instruction()`. The committed `harbor/canary-task/instruction.md` is the medium tier, so it is byte-identical.
- **Canary ids:** the first canary of a day is still `c<day>`; a second one the same day is `c<day>-2`. A third call returns `canary limit for today reached`.
- **Version:** `TIERS_VERSION = "v1.4"`, and `tests/test_env_frozen.py` pins hash `a8f99c2537c91d72` (TIERS + KNOWN_V_MODE). **v1.3 stays reproducible:**
  - `rules.TIERS_V13` (`rules.TIERS_HISTORY["v1.3"]`) still hashes to `8df71cf570bb48bc`;
  - `with rules.tiers_version("v1.3"):` swaps it in;
  - the committed v1.3 reference solver runs replay step for step (`tests/test_tiers_v14.py`);
  - offline audits (`canary.analysis.accuse`, `canary.solver.regret`) choose the version from the episode's staff size (`rules.tier_params_for_episode`);
  - `make reproduce` keeps grouping committed runs by `tiers_version`;
  - `scripts/paired_table.py --tiers-version v1.3` replays v1.3 tables.
- **Solver (reference):** `SolverPolicy.plan_canaries` plans up to `canaries_per_day` canaries a day.
  - It works greedily. Each canary maximises the mutual information between the mole and the joint outcome of **all outstanding canaries**, including those still pending under delay, so new splits are orthogonal to tests already in flight. It uses careful-mole weights and models the competition for the mole's one leak a day.
  - An extra canary must add ≥ 0.1 nats, because a canary costs V.
  - The search is count-capped and never depends on wall-clock time.
  - The exact posterior and the EV accusation rule (accuse when P·E[true V] − (1−P) > 0 and P ≥ 0.85, or on the last day) are unchanged.
  - With 1 canary a day the policy is exactly v1.3.
- **Baselines** read `n_days` and `canaries_per_day` from the instruction, so neither is handicapped by v1.4:
  - `heuristic` sets its deadline to n_days − 2 and makes a second, orthogonal split;
  - `grok_tactics` plants one tiny pair canary per allowed canary.
  - Both behave exactly as before on the v1.3 tiers.
- **Calibration** (Mac, ≤6 processes, no LLM calls; `scripts/calib_v14.py`). The grid covered leak_damage {0.04, 0.05, 0.06, 0.065, 0.08} × n_employees {30, 35, 40, 45} on dev seeds 4000–4599. The cell was picked on dev seeds only and **confirmed on fresh seeds 5000–5799** (n = 800 per tier; `results/fresh_table_v1.4.md`).
  - Solver mean: easy **.779**, medium **.633**, hard **.556 ± .024**. Hard accuracy **94.9%**, no-accusation 1.2%, mean accusation day 8.8.
  - Paired solver − grok_tactics on hard: **+.195 ± .033** (grok .362, 84.2% correct, 12.0% no accusation).
  - Paired solver − heuristic on hard: **+.534 ± .046**.
  - stop_early on hard: −.945. do_nothing: 0. logs_only accuracy on hard: 1.4% (chance is 1/39 = 2.6%).
- **Honest read:**
  - The objectives are met (hard accuracy ≥ 85%, monotone easy > medium > hard, stop_early < 0, do_nothing = 0, logs_only ≈ chance) **except the grok_tactics gap, which is just under the 0.2 target** (CI .162–.228).
  - On the same seeds with the same code, v1.3 hard gives solver .575 and grok_tactics .342 (gap .233 ± .040; 35% of grok episodes had no accusation).
  - So the longer horizon helps the scripted baselines more than the solver: grok's horizon abstentions fall from 35% to 12%.
  - The v1.4 bet is about LLM bookkeeping, which a scripted policy does not need. Whether frontier agents fall behind on v1.4 hard has to be measured.
