# Canary Failure Atlas, blind

*Generated 2026-11-14T22:59:16+0200 at `aed53f2`; model `gemini-3.8-flash` (served `gemini-3.8-flash`); ledger run ids atlas-20261114-223741, atlas-20261114-224929.*

**Gemini, without seeing our labels, recovered 3 of 5 code-defined failure modes** (recall >= 30% of the tag's steps cited) **and named 2 mode(s) our tags don't have.** Its cited steps cover 21% of all solver regret; 12% of the steps it cites are high-regret (regret >= 0.01) and 61% carry a code tag.

What Gemini saw: 153 episodes, 751,088 tokens, held in one explicit context cache. Only tool calls, tool results as the agent saw them, the agent's own words and the final outcome. No regret, no tags, no solver belief, no true mole, no solver score (a test checks the pack). Gemini first named the modes with examples, then listed every step of each mode (once per mode over the whole corpus, then exhaustively per batch of 12 episodes); all scoring below is computed in code against `canary/analysis/tags.py` and the solver regret, which Gemini never saw.

## Recall per code tag

A cited step matches a tagged step in the same episode within 1 step(s).

| code tag | tagged steps | regret | recall (any Gemini mode) | recall on high-regret steps | best-matching Gemini mode |
|---|---|---|---|---|---|
| `premature_accusation` | 25 | 13.72 | 44% | 44% | `overweighting_noisy_logs_and_framing` (32%) |
| `ignored_delay` | 2 | 1.61 | 100% | 100% | `overweighting_noisy_logs_and_framing` (100%) |
| `uninformative_canary` | 67 | 1.01 | 0% | 0% | `None` (0%) |
| `over_restriction` | 5 | 0.37 | 0% | 0% | `None` (0%) |
| `budget_waste` | 152 | 0.00 | 46% | - | `invalid_tool_syntax_and_parameter_errors` (29%) |

All high-regret steps: 404; Gemini cited 4% of them.

## Gemini's modes

| mode | cited steps | precision (high-regret) | precision (tagged) | regret of cited steps | closest tag | new? |
|---|---|---|---|---|---|---|
| **Over-relying on access log framing and decoy noise** (`overweighting_noisy_logs_and_framing`) | 13 | 69% | 62% | 5.91 | `premature_accusation` (62%) |  |
| **Treating noisy canary fingerprints as infallible ground truth** (`canary_fingerprint_misattribution`) | 7 | 29% | 14% | 0.20 | `premature_accusation` (14%) | yes |
| **Action exhaustion via low-information interviews** (`over_interviewing_and_action_exhaustion`) | 29 | 14% | 83% | 0.01 | `budget_waste` (83%) |  |
| **Value bleed from excessive delay and horizon timeout** (`passive_delay_value_depletion`) | 30 | 0% | 0% | 0.00 | `None` (0%) | yes |
| **Malformed tool calls and parameter schema violations** (`invalid_tool_syntax_and_parameter_errors`) | 49 | 2% | 92% | 0.02 | `budget_waste` (92%) |  |

Analysis of canary investigation runs reveals recurring strategic and operational failure modes that cost agents substantial company value or result in incorrect accusations. Primary drivers of failure include over-relying on framed access logs and decoys, treating imperfect canary variant fingerprints as absolute ground truth, burning daily action budgets on low-signal interviews, passively waiting for delayed leaks until company value is depleted, and executing malformed tool calls that trigger validation errors.

### Over-relying on access log framing and decoy noise

Agents treat after-hours access counts and high-volume access logs as strong signals of guilt, falling victim to decoy framing mechanics and tie-breaking against innocent employees instead of relying on ground-truth document intersection or clean canary signals.

*Why:* Agents assume after-hours activity is an unambiguous indicator of mole behavior, rationalizing accusations based on small discrepancies in access frequency while failing to account for intentional framing of innocent colleagues.

> `g4carbon.in.v14.h6` t=150: "Six after-hours accesses compared to only eight daytime accesses, a staggering 42.9% after-hours rate."
> `gpt5.5.co.v12.h1` t=84: "inside that A group `e06` is the one with an after-hours access to `c4` on the very day it leaked."

### Treating noisy canary fingerprints as infallible ground truth

In tiers where canary fingerprint accuracy is 95% rather than 100%, agents treat surfaced variant labels as deterministic proof, prematurely eliminating the true mole and zeroing out their posterior probability upon a single variant misattribution.

*Why:* Agents ignore or discount the 5% error rate in canary fingerprints, calculating posterior probabilities that collapse the hypothesis space prematurely and falsely concluding guilt with purported mathematical certainty.

> `gpt5.5.co.v12.h0` t=84: "Their intersection is `e05`; allowing for the 5% fingerprint error, `e05` is now far above the accusation threshold."
> `g4carbon.op.v14.h1` t=177: "Assigned `e39` uniquely to `v1` and `e33` to `v2`; `v1` surfaced on Day 19."

### Action exhaustion via low-information interviews

Agents consume their daily action quotas by running repetitive interviews that yield minimal Bayesian leverage, hitting the daily action limit and blocking critical investigations or canary deployments.

*Why:* Agents treat interviews as free information-gathering tools, underestimating the opportunity cost of daily action caps and repeatedly encountering daily action limit errors.

> `g4carbon.in.v14.h1` t=6: "Burning a significant number of tool calls to screen 40 random in"
> `g4carbon.in.v14.h2` t=7: "it appears we have ample capacity, even if we burn actions every day on `interview`. This is huge!"

### Value bleed from excessive delay and horizon timeout

Agents repeatedly advance days without taking decisive trapping or restriction actions, allowing recurring leaks to severely degrade company value V, sometimes reaching the final day horizon without making any accusation.

*Why:* Agents over-prioritize certainty over expected value, failing to recognize that waiting multiple days for delayed leak confirmation costs far more company value than acting on high-probability posteriors.

> `g4carbon.in.v14.h5` t=182: "Time to advance to Day 19 with the `advance_day` function. This is critical. Day 19 is where the rubber meets the road."

### Malformed tool calls and parameter schema violations

Agents attempt invalid tool calls—including empty search strings, whitespace-only queries, invalid canary syntax exceeding variant limits, or calling non-existent system tools like bash—wasting opportunities and sometimes causing fatal tool execution crashes.

*Why:* Agents hallucinate tool capabilities outside the Canary environment or fail to validate arguments against schema constraints such as maximum variant limits and non-whitespace string requirements.


## Quote check (agent-authored text only)

12/16 quotes appear verbatim in the agent's own words (12 at or just before the cited step); 15 examples had no agent text to quote. Step records, headers and anything the harness or our code generated never count.

Reproduce offline: `python -m canary.gemini.atlas --blind --replay`.
