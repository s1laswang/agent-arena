# Canary Arena: Curated Seed Catalog & Hidden-Truth Guard Contract

Canary Arena ships four playable and replayable browser modes backed by Pyodide (`game/canary_game.py`) and deterministic committed `v1.4` episode transcripts (`origin/justSilas@58716742`). Every benchmark number below is verified directly against committed `episodes.jsonl` records and `canary.solver.policy.SolverPolicy` rollouts with zero live API calls and zero pre-end hidden-truth spoilers on live playable worlds.

## 1. Mode 1: Solo Investigator (`medium`, Public Dev Seeds `3000..9999`)

Mode 1 runs live in Pyodide via `game/canary_game.py` (`TIER = "medium"`, `SEED_MIN = 3000`, `SEED_MAX = 9999`). Judge worlds, held-out worlds, and training worlds outside `3000..9999` are fail-closed refused by `check_seed(seed)` so the browser page can never be used to explore a benchmark seed.

- **Tier geometry (`medium`, `v1.4`):** `20` staff, `14` days, `300` calls global cap (`tool_call_cap`), `8` investigative actions/day (`actions_per_day`), `1` canary/day (`max_variants = 3`), `p_leak = 0.75`, `delay_choices = (1, 2, 3)`, `leak_damage = 0.04`, `canary_cost = 0.01`, `restrict_cost_per_day = 0.01`.
- **Default launch seed (`3000`):** `SolverPolicy` scores `+0.79` on Day `6` in `48` calls (`correct = true`). True mole identity stays strictly sealed (`reveal_json()` returns `{"error": "the episode is not over yet"}`) until `done === true`.
- **Curated public dev seed pack (`3000..3009`, mole identity sealed for live play):**

| Seed | Tier | `SolverPolicy` Score | Final Day | Tool Calls | Solver Outcome | Live Mole Identity |
|---:|---|---:|---:|---:|---|---|
| `3000` | `medium` | `+0.79` | `6` | `48` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3001` | `medium` | `+0.68` | `9` | `69` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3002` | `medium` | `+0.83` | `6` | `48` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3003` | `medium` | `0.00` | `14` | `106` | Strategic abstention | `"[SEALED]"` until `done === true` |
| `3004` | `medium` | `+0.59` | `10` | `76` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3005` | `medium` | `+0.88` | `5` | `41` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3006` | `medium` | `+0.79` | `6` | `48` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3007` | `medium` | `+0.78` | `7` | `55` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3008` | `medium` | `+0.78` | `7` | `53` | Correct accusation | `"[SEALED]"` until `done === true` |
| `3009` | `medium` | `+0.79` | `6` | `46` | Correct accusation | `"[SEALED]"` until `done === true` |

## 2. Mode 2: Human vs AI Split-Screen Duel (`AiDuelPanel`)

Mode 2 pairs a live human investigator on the left pane against committed `v1.4` `gemini-4-carbon` (OpenCode over MCP, the judges' harness) and `SolverPolicy` transcripts on the right pane using the `AiDuelPanel` payload schema `{seed, tier, agent, steps, final}` (`data/runs/committed/v1.4/`, post-hoc locked paired dev seeds `0-29`). On `hard` (`40` staff, `21` days, `420` calls cap, `8` actions/day, `2` canaries/day, `fingerprint_accuracy = 0.95`), `gemini-4-carbon` keeps `65% [24%, 98%]` raw and `72% [52%, 91%]` luck-adjusted of `SolverPolicy` value across `n = 30` paired seeds.

### 2.1 Headline Showcase Seeds (`hard` Seeds `6`, `26`, and `4`)

- **`hard` Seed `6` (Caught):**
  - `SolverPolicy`: `+0.71` (Day `6`, `52` calls, `9` canaries, `0` interviews, correct accusation).
  - `gemini-4-carbon` OpenCode: `+0.73` (Day `6`, `57` calls, `7` canaries, `25` interviews, correct accusation).
  - Dramatic arc: Fast head-to-head race where `gemini-4-carbon` matches Day `6` isolation while spending `0.02` less canary overhead (`7` vs `9` traps). Post-game culprit (revealed only when `humanDone === true`): `e34`.
- **`hard` Seed `26` (Fooled):**
  - `SolverPolicy`: `+0.69` (Day `7`, `60` calls, `11` canaries, `0` interviews, correct accusation).
  - `gemini-4-carbon` OpenCode: `-1.00` (Day `10`, `91` calls, `0` canaries Days `1-3`, `8` total canaries, `43` interviews, wrong accusation).
  - Dramatic arc: Under-planting (`0` canaries on Days `1-3`, `43` weak interviews) leaves `gemini-4-carbon` vulnerable on Day `10` when a `1`-in-`20` noisy `S1` canary readout (`fingerprint_accuracy = 0.95`) drops `P(mole)` `0.48 -> 0.03` and shifts posterior concentration onto innocent `e04`, triggering a `-1.00` wrongful accusation (`SolverPolicy` planted `11` orthogonal canaries by Day `6`, immunizing against single-readout noise). Post-game true mole (revealed only when `humanDone === true`): `e08` (accused innocent: `e04`).
- **`hard` Seed `4` (Slow Moment):**
  - `SolverPolicy`: `+0.73` (Day `5`, `44` calls, `7` canaries, `0` interviews, correct accusation).
  - `gemini-4-carbon` OpenCode: `+0.40` (Day `16`, `155` calls, `10` canaries, `84` interviews, `55%` of solver value, correct accusation).
  - Dramatic arc: By Day `5`, `SolverPolicy` has planted `7` canaries and reaches `P(mole) = 1.00`, whereas `gemini-4-carbon` has run `29` interviews and planted only `2` canaries (`P(mole) = 0.10`), bleeding `11` extra days of leak damage (`84` total interviews) before accusing the same culprit at `55%` of solver value. Post-game true mole (revealed only when `humanDone === true`): `e11`.

### 2.2 Additional Featured Replay Pack Seeds

| Group | Tier | Seed | `SolverPolicy` (`score`, day, calls, canaries) | `gemini-4-carbon` OpenCode (`score`, day, calls, canaries, interviews) | Post-Game Culprit (`humanDone === true`) | Diagnostic Highlight |
|---|---|---:|---|---|---|---|
| Featured Hard | `hard` | `1` | `+0.69` (Day `7`, `60` calls, `11` canaries) | `-1.00` (Day `19`, `178` calls, `15` canaries, `90` interviews, accused `e39`) | `e33` | Late horizon exhaustion and wrongful accusation after `90` interviews |
| Featured Hard | `hard` | `11` | `+0.62` (Day `9`, `74` calls, `13` canaries) | `0.00` (Day `21`, `212` calls, `12` canaries, `121` interviews, abstained) | `e09` | `121`-interview stall hitting Day `21` horizon without isolating culprit |
| Featured Hard | `hard` | `15` | `-1.00` (Day `9`, `72` calls, `11` canaries, accused `e17`) | `-1.00` (Day `12`, `123` calls, `6` canaries, `68` interviews, accused `e34`) | `e37` | Rare `5%` fingerprint-flip stress case where both agents are fooled |
| Featured Hard | `hard` | `18` | `+0.52` (Day `13`, `103` calls, `18` canaries) | `-1.00` (Day `18`, `180` calls, `14` canaries, `101` interviews, accused `e29`) | `e27` | Deep careful-mole evasion requiring `18` solver canaries; `101` AI interviews fail |
| Featured Medium | `medium` | `0` | `+0.74` (Day `7`, `53` calls, `6` canaries) | `+0.63` (Day `10`, `97` calls, `9` canaries, `48` interviews, accused `e05`) | `e05` | Clean medium duel (`3`-day solver lead over `48`-interview AI trajectory) |
| Featured Medium | `medium` | `12` | `+0.67` (Day `10`, `76` calls, `9` canaries) | `+0.81` (Day `6`, `55` calls, `3` canaries, `26` interviews, accused `e06`) | `e06` | Medium parity showcase (`111%` raw / `101%` luck-adjusted OpenCode medium cohort) |
| Tiebreak Replay | `easy`/`medium`/`hard` | `800000`, `800001`, `800002` | Pre-exported WS4 held-out comparison traces | `Qwen2.5-1.5B` (`base` `0.000`, `v2` `-0.457`, `v3-4k` `-0.147`, `v3-8k-s2` `-0.050`) | Sealed in live play (replay-only traces) | Read-only WS4 held-out trajectory inspection (`check_seed` refuses live `800000+` worlds; protocol/abstention learned, bar not met vs `0.000` base) |

## 3. Mode 3: Be the Mole (Public Dev Seeds `3000..3009`)

Mode 3 flips the asymmetric game: the human plays the insider mole on public dev seeds `3000..3009` against a live `SolverPolicy` security investigator, submitting daily decisions through `onMoleAction({type:'leak'|'hold', doc_id})`.

- **Playable seed pool:** `3000..3009` (`medium` default, optional `hard` challenge; all seeds outside `3000..9999` rejected by `check_seed`).
- **Pre-end mole-view redaction (`!episodeDone`):** While `!episodeDone`, document payloads exposed to the human mole strictly match `MoleView` observability by stripping `is_canary`, `canary_variants`, and `SolverPolicy` posteriors (`sp.belief()`). The human mole observes only `doc_id`, title, sensitivity, `recipient_count`, `recent_low_recipient_docs`, `i_am_restricted`, and `n_restricted_colleagues`, forcing genuine monitoring inference rather than ground-truth flag reading.

## 4. Mode 4: Living Office (`v1.6` Off-by-Default Preview)

Mode 4 renders multi-day workplace chatter, rumours, and grudges from pre-cached offline transcripts over the office floorplan under an explicit, off-by-default `'v1.6 preview'` badge.

- **Off-by-default status & honest Gate B readout:** Mode 4 is disabled by default in competitive runs and carries a persistent `'v1.6 preview'` badge. In our `v1.5` biased-employee ablation (rumours, grudges, authority, misforwards), `gemini-4-carbon` went `61% -> 108%` of `SolverPolicy` on `hard` seeds `0-9` (`data/runs/committed/v1.5-candidate/`) because the LLM treated workplace rumours as direct evidence against the rumoured person while the calibrated solver discounted cheap talk; `v1.5`/`v1.6` social chatter was therefore dropped at Gate B and is presented strictly as an offline visual showcase with zero live LLM calls.

## 5. Pre-End Hidden-Truth Guard Invariants

All four Canary Arena modes enforce four non-negotiable pre-end hidden-truth guard invariants verified by `scripts/verify_arena_integrity.py`:

1. **Day-Clock Causal Clamp (`day <= humanDay`):** In Mode 2 split-screen duels, the right-pane AI transcript (`AiDuelPanel` `{seed, tier, agent, steps, final}`) only reveals opponent steps satisfying `day <= humanDay` while `humanDone === false`, preventing the human player from reading future leak-feed arrivals or document intersections ahead of their own clock.
2. **Early AI Accusation Target Seal (`"[SEALED]"` until `humanDone === true`):** Whenever the opponent AI or `SolverPolicy` terminates on an earlier day than the human (`aiFinalDay <= humanDay` while `humanDone === false`), `step.args.employee`, `final.accused`, `final.correct`, and `post_game_mole` are masked to `"[SEALED]"` until `humanDone === true`.
3. **Observable Company Value (`known_v` Only) & Sprite Neutrality (`!done`):** Active HUD bars, step payloads, and office canvas frames expose only surfaced `known_v` (never unsurfaced `true_v`) and suppress `leaking_sprite_employee`, `mole`, `true_mole`, and `decoy` identifiers whenever `!done` (`done === false`).
4. **Mode 3 Canary & Posterior Redaction (`!episodeDone`):** In Mode 3 (`onMoleAction({type:'leak'|'hold', doc_id})`), every document and turn payload strips `is_canary`, `canary_variants`, and `SolverPolicy` posteriors while `!episodeDone`, and `check_seed` blocks all judge (`900000+` range) and held-out (`800000+` range) seeds from interactive instantiation.

## 6. Featured Seed Catalog Manifest (`JSON`)

```json
{
  "schema_version": "canary_arena_seeds_v1",
  "rules_version": "v1.4",
  "base_commit": "58716742",
  "hidden_truth_guards": {
    "duel_day_clamp": "day <= humanDay",
    "early_accuse_mask": "[SEALED]",
    "reveal_condition": "humanDone === true",
    "value_visibility": "known_v_only_until_done",
    "mole_mode_stripped_fields": [
      "is_canary",
      "canary_variants",
      "solver_posteriors"
    ]
  },
  "mode_1_solo_investigator": {
    "tier": "medium",
    "allowed_seed_range": [3000, 9999],
    "default_seed": 3000,
    "tier_params": {
      "n_employees": 20,
      "n_days": 14,
      "tool_call_cap": 300,
      "actions_per_day": 8
    },
    "default_seed_solver_benchmark": {
      "seed": 3000,
      "score": 0.79,
      "final_day": 6,
      "tool_calls": 48,
      "correct": true,
      "live_mole_id": "[SEALED]"
    },
    "curated_public_seeds": [3000, 3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008, 3009]
  },
  "mode_2_ai_duel": {
    "panel_schema": ["seed", "tier", "agent", "steps", "final"],
    "headline_seeds": [
      {
        "seed": 6,
        "tier": "hard",
        "label": "Caught",
        "solver": {
          "score": 0.71,
          "final_day": 6,
          "tool_calls": 52,
          "canaries": 9,
          "interviews": 0,
          "correct": true
        },
        "gemini_4_carbon_opencode": {
          "score": 0.73,
          "final_day": 6,
          "tool_calls": 57,
          "canaries": 7,
          "interviews": 25,
          "correct": true
        },
        "live_accuse_target_while_playing": "[SEALED]",
        "post_game_culprit_when_humanDone": "e34"
      },
      {
        "seed": 26,
        "tier": "hard",
        "label": "Fooled",
        "solver": {
          "score": 0.69,
          "final_day": 7,
          "tool_calls": 60,
          "canaries": 11,
          "interviews": 0,
          "correct": true
        },
        "gemini_4_carbon_opencode": {
          "score": -1.0,
          "final_day": 10,
          "tool_calls": 91,
          "canaries": 8,
          "canaries_days_1_to_3": 0,
          "interviews": 43,
          "noisy_s1_posterior_drop": [0.48, 0.03],
          "post_game_accused_innocent": "e04",
          "correct": false
        },
        "live_accuse_target_while_playing": "[SEALED]",
        "post_game_culprit_when_humanDone": "e08"
      },
      {
        "seed": 4,
        "tier": "hard",
        "label": "Slow Moment",
        "solver": {
          "score": 0.73,
          "final_day": 5,
          "tool_calls": 44,
          "canaries": 7,
          "interviews": 0,
          "correct": true
        },
        "gemini_4_carbon_opencode": {
          "score": 0.4,
          "final_day": 16,
          "tool_calls": 155,
          "canaries": 10,
          "interviews": 84,
          "share_of_solver_value": 0.55,
          "correct": true
        },
        "live_accuse_target_while_playing": "[SEALED]",
        "post_game_culprit_when_humanDone": "e11"
      }
    ],
    "featured_replay_pack": {
      "hard": [1, 11, 15, 18],
      "medium": [0, 12],
      "tiebreak_heldout_replay_only": [800000, 800001, 800002]
    }
  },
  "mode_3_be_the_mole": {
    "curated_public_seeds": [3000, 3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008, 3009],
    "action_contract": "onMoleAction({type:'leak'|'hold', doc_id})",
    "strip_while_not_episodeDone": [
      "is_canary",
      "canary_variants",
      "SolverPolicy_posteriors"
    ]
  },
  "mode_4_living_office": {
    "enabled_by_default": false,
    "badge": "v1.6 preview",
    "gate_b_note": "v1.5 biased employees went 61% -> 108% on hard seeds 0-9; dropped at Gate B"
  }
}
```
