# Canary V1.6 Social Layer: Architecture, Cognitive Biases, and Replayability

## 1. Motivation and Lessons from V1.5 Gate B

Real corporate leak investigations unfold inside noisy internal communication channels where senior opinions, urgent post-meeting alerts, interpersonal grudges, and accidental document forwards compete with hard forensic evidence (`plant_canary`, `check_leak_feed`, `read_access_logs`).

In the earlier `v1.5-candidate` experiment (`origin/justSilas-v15`), seeded workplace rumours inadvertently carried negative mutual information with the hidden mole: because rumours targeted non-mole employees, `gemini-4-carbon` treated being rumoured as an exoneration signal and rose from `61%` to `108%` of the reference solver on paired hard seeds `0-9` (`docs/reports/gap.md`). `v1.5-candidate` was dropped at Gate B.

Canary V1.6 (`canary/social/`, `social-v2`) redesigns biased employee behaviour inside the `TextProvider` boundary (`canary/text/gemini.py`) with zero edits to `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, or `harbor/`:

1. **Zero mole information (`LR = 1`):** `V16SocialProvider.day_messages(facts: PublicDayFacts)` receives only `PublicDayFacts` (`tier`, `seed`, `day`, `company`, `employees`, `docs`, `decoy`, `decoy_mood`, `restricted`). Focal suspects (`primary_suspect`, `secondary_suspect`), `authority_speakers`, and `grudge_pairs` are seeded deterministically from `(variant, tier, seed)` and Day 1 regular document recipient lists excluding `facts.decoy`.
2. **Exact solver calibration:** Conditional on public observables, every V1.6 social message is identically distributed regardless of which non-decoy employee is the true mole. Its Bayesian likelihood ratio on mole identity is identically `1.0`, so the unmodified `v1.4` `SolverPolicy` achieves `solver_calibration_diff = 0.0` (`+0.576` on hard seeds `0-9` under both `template` and `v16:<variant>`), while `do_nothing` (`0.000`) and `stop_early` (`0.000`) remain invariant.
3. **Decoy firewall:** `SolverPolicy` queries `search_messages` only on `ANGER_WORDS` (`promotion`, `raise`, `deserve`, `burn out`, `recruiter`, `goalposts`, `nobody asks`, `updating my cv`) to identify the innocent disgruntled decoy. `validate_social_message` and `sanitize_non_decoy_base_message` scrub `DECOY_VOCAB` from all non-decoy messages and forbid `facts.decoy` as a social speaker or target.

---

## 2. Research-Grounded Cognitive Bias Taxonomy (`canary/social/biases.py`)

V1.6 implements nine workplace cognitive biases (`BIAS_TYPES`) plus multi-employee Sleeper social-engineering chains (`canary/social/sleeper_chains.py`), multi-day phase arcs (`canary/social/multiday_memory.py`), and full 21-day horizon escalation (`canary/social/horizon_escalation.py`):

| Bias / Chain | Generator | Organizational Mechanism (`PublicDayFacts` Only) | Targeted Investigative Failure Mode and Literature Grounding |
|---|---|---|---|
| `authority` | `gen_authority` | Senior roles (`manager`, `lead`, `controller`, `counsel`) state confident but unverified suspicion toward a focal colleague. | Over-weighting high-status cheap talk relative to watermarked canary splits (Milgram, 1963). |
| `recency` | `gen_recency` | Late-horizon urgent post-meeting messages naming a colleague near the stopping window. | Availability and recency weighting near horizon accusations (Tversky & Kahneman, 1973). |
| `confirmation` | `gen_confirmation` | Follow-up messages interpreting routine document circulation as confirming an earlier suspicion thread. | Selective evidence assimilation and confirmatory hypothesis testing (Nickerson, 1998). |
| `bandwagon` | `gen_bandwagon` | Cross-department sync summaries claiming multiple teams independently converged on the same suspect. | Correlated cheap-talk cascades mistaken for independent signals (Asch, 1951; Bikhchandani et al., 1992). |
| `anchoring` | `gen_anchoring` | Day 1-2 suspicion threads tied to initial regular document recipients revisited on later days. | Insufficient Bayesian adjustment away from initial focal hypotheses (Tversky & Kahneman, 1974). |
| `grudge` | `gen_grudge` | Persistent dyadic disputes (`grudge_pairs`) escalating across days over mishandled drafts. | Mistaking interpersonal friction and rival blame for insider-threat motive (Hewstone et al., 2002). |
| `misforward` | `gen_misforward` | Accidental cc and forwarded-thread chatter placing a colleague adjacent to a document handoff. | Over-relying on weak routing and demeanour cues instead of diagnostic canary traps (Hartwig & Bond, 2011). |
| `false_memory` | `gen_false_memory` | Confident but unverified recollections of who requested offline copies on an earlier day. | Source-monitoring and post-event misinformation errors (Loftus, 2005). |
| `sycophancy` | `gen_sycophancy` | Peer replies explicitly endorsing an earlier `authority` speaker's theory. | Double-counting echoed authority opinions as independent peer corroboration (Milgram, 1963; Asch, 1951). |
| `sleeper_social_chains` | `build_sleeper_chain_events` | Four ported Sleeper traps (`cosign_urgency_chain`, `accomplice_alibi_ring`, `out_of_band_chat_claim`, `slowburn_framing_echo`). | Dual-control urgency bypass, collusive peer alibis, `"confirmed in chat"` verification skipping, and illusory-truth repetition (Pennycook et al., 2018). |
| `sleeper_multiday_arc` | `build_multiday_memory_events` | Four-phase Day 1-18 schedule (`seeding`, `authority_callbacks`, `cross_dept_escalation`, `stopping_window`). | Multi-week narrative accumulation and illusory-truth familiarity across Days 1-18 (Pennycook et al., 2018). |
| `v6_horizon_escalation` | `build_horizon_escalation_events` | Five-phase Day 1-21 full stopping-window continuity (`3` msgs/day, `63` msgs/episode, `96.7%` post-Day-1 causal callbacks). | Sustains authority, bandwagon, Day 1 anchoring callbacks, and stage-6 dyadic grudges through Days 19-21 without altering `v5` cache keys (Pennycook et al., 2018; Tversky & Kahneman, 1973, 1974). |

### Literature Grounding Notes

- **Obedience, conformity, and informational cascades (Milgram, 1963; Asch, 1951; Bikhchandani et al., 1992):** `authority`, `sycophancy`, and `bandwagon` test whether an investigator treats repeated hierarchical or cross-department endorsements as independent likelihood updates rather than zero-information cheap talk (`LR = 1`).
- **Heuristics, anchoring, and confirmatory assimilation (Tversky & Kahneman, 1973, 1974; Nickerson, 1998):** `anchoring`, `confirmation`, and `recency` seed early Day 1-2 focal hypotheses from public regular-document circulation and revisit them near the accusation boundary.
- **Post-event misinformation, illusory truth, interpersonal conflict, and cue miscalibration (Loftus, 2005; Pennycook et al., 2018; Hartwig & Bond, 2011; Hewstone et al., 2002):** `false_memory` models retroactive memory distortion; `sleeper_social_chains`, `sleeper_multiday_arc`, and `v6_horizon_escalation` model illusory-truth repetition across multi-week threads; `misforward` models weak non-diagnostic routing cues; and `grudge` models persistent dyadic blame between rival colleagues.

### Variant Matrix (`canary/social/variants.py` and Opt-In Plugins)

- `v0_v14_control`: exact `v1.4` `TemplateProvider` control (`0` social events).
- `v1_anchoring_authority_confirmation`: early anchoring reinforced by senior authority and confirmation follow-ups.
- `v2_recency_bandwagon_sycophancy`: social consensus, sycophantic agreement, and late-horizon recency bursts.
- `v3_grudge_falsemem_misforward`: interpersonal grudges paired with routing confusion and false memories.
- `v4_triad_authority_recency_grudge`: five-bias escalation triad (`anchoring`, `confirmation`, `authority`, `recency`, `grudge`).
- `v5_full9_cocktail` (aliased as `social-v2` / `v16`): full nine-bias schedule across Days 1-18.
- `v6_horizon_escalation` (`canary/social/horizon_escalation.py`): opt-in five-phase Days 1-21 full stopping-window continuity (`63` social messages per `hard` episode, including `9` late-window messages on Days 19-21, `solver_calibration_diff = 0.0`).
- `sleeper_social_chains` (`canary/social/sleeper_chains.py`) and `sleeper_multiday_arc` (`canary/social/multiday_memory.py`): opt-in Sleeper social-engineering chains and Day 1-18 multi-day memory arc.
- `b_<bias>`: nine single-bias ablation schedules isolating each `bias` in `BIAS_TYPES`.

---

## 3. Cached `gemini-4-carbon` Rendering and Canary-Invariant Replay

`canary/social/gemini_chatter.py` and `canary/text/llm_cache.py` provide natural workplace prose generated with `gemini-4-carbon` while guaranteeing deterministic offline replay:

1. **Content-addressed SHA-256 cache and provenance priority (`data/gemini_cache/`):** Every `cached_chat` call hashes `(model, system, messages, tools, temperature, seed)` into `<sha256>.json` with provenance metadata (`label="REAL"` vs `"stub"`). `data/gemini_cache/` holds `256` committed `REAL` `gemini-4-carbon` cached prompts (`0` `stub` entries). When `label == "REAL"` and no custom `CANARY_GEMINI_CACHE_DIR` override is set, `cached_chat` checks `REPO_COMMITTED_CACHE_DIR` (`data/gemini_cache/`) ahead of `DEFAULT_SHARED_CACHE_DIR` (`/tmp/fleet-silas/shared/v16_gemini_cache`) and ignores shared `stub` entries so stub warmups can never shadow committed `REAL` responses. Setting `CANARY_OFFLINE=1` enforces zero network calls and raises `OfflineCacheMiss` on any uncached real-LLM miss.
2. **Audited `hard` seeds `0-9` coverage and canary-planting SHA-256 invariance (`_regular_docs` + `_clean_doc_titles`):** Investigator `plant_canary` documents (`doc_id` starting with `"c"`) are excluded from social state initialization and Gemini prompt construction, guaranteeing `100%` SHA-256 prompt invariance under any runtime `plant_canary` split. On `v16-gemini:v5_full9_cocktail` across `hard` seeds `0-9` (`CANARY_OFFLINE=1 CANARY_GEMINI_CACHE_DIR=data/gemini_cache`, `180` day-prompts across `10` seeds x `18` active social days), `158/180` day-prompts hit `REAL` `gemini-4-carbon` cache (`18/18 = 100%` on `hard` seeds `0, 1, 2, 3, 5, 6`; `16/18` on seed `4`; `17/18` on seeds `7, 8`; `0/18` on seed `9`), with deterministic template fallback on the remaining `22` day-prompts (`0` validator rejects on the `158` cached prompts).
3. **Per-message validator and deterministic fallback:** Every Gemini-rewritten body must pass `validate_social_body` and `validate_social_message` (`lint_text` clean, `<= 350` chars, target label preserved in prefix, required workplace salience term present, zero `DECOY_VOCAB` hits, zero out-of-scope employee IDs). Any uncached or rejected item falls back deterministically to the validated template draft.

---

## 4. Fairness, Rules Disclosure, and Gate B Status

To uphold Canary's fairness rule ("Every rule and number of the game is written on this page. Nothing is hidden except who the mole is"), `docs/v16-readme-and-rules.md` specifies the exact plain-English agent rule disclosure stating that V1.6 workplace speculation is generated strictly from public roles and regular document recipient lists with zero access to mole identity (`LR = 1`).

### Honest Gate B Outcome (Off by Default; `v1.4` Ships Unchanged)

Under the Gate B evaluation protocol (`docs/v16-readme-and-rules.md` and `docs/reports/v16_social_gate.md`):
- `CANARY_PROVIDER` defaults to `template` (`v1.4`), leaving all judged tasks, `README.md` headline tables (where committed `v1.4` `hard` dev seeds `0-29`, `n = 30`, are a **post-hoc lock** - `671ed96` came 28 s after `8fd4dec` - at raw `65% [24%, 98%]` of the solver, luck-adjusted `72% [52%, 91%]`), and `make reproduce` completely unchanged.
- On the paired `gemini-4-carbon` evaluation checkpoints collected before the Gemini quota stand-down (see `docs/reports/v16_social_gate.md`), `gemini-4-carbon` scored higher under `v1.6` (`v5_full9_cocktail` mean `+0.617` on shared hard seeds `30-32`, `n = 3`) than on the paired `v1.4` control (`v0_v14_control` mean `+0.523`, `n = 3`), and the OpenCode `hard` `0-9` shard sweep did not complete below `v1.4` (`0/10` valid OpenCode v1.6 episodes landed).
- **Gate B is NOT met.** `v1.4` remains the sole judged environment, and `canary/social/` is retained strictly on the `fr8/canary/staffai` research branch with full offline verification (`scripts/build_v16_paired_table.py`, `canary/social/office_replay.py`, `canary/social/horizon_escalation.py`, and `pytest`).
