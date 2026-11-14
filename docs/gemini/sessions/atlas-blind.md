# Session brief: ATLAS BLIND RE-RUN (worktree ~/junction-aimo-team/wt/gemini-atlas, branch gemini-atlas)
Read COMMON.md (same folder) first. Context: docs/gemini/reports/atlas.md and canary/gemini/atlas*.py (atlas v1 is committed in results/gemini/atlas.*).

**Why:** an independent review found atlas v1 is partly circular.
- `atlas_data.step_line` shows Gemini `| REGRET x [tags]` (the code's own canary/analysis/tags.py labels), plus `top=`/`mole:` beliefs, and episode headers with true_mole and total_regret.
- So "Gemini names the failure modes" and "98% verbatim" are inflated: 16 of the 27 quotes in atlas.json are code-generated REGRET lines.

**Task (due Sun 03:30, budget about $15 Gemini):**
1. Add `--blind` to `python -m canary.gemini.atlas`. The packed corpus must contain ONLY what the agent saw and did: tool calls, tool results, the agent's own text and thoughts, and the final outcome (accused, correct, score). Strip REGRET, tags, top=, mole:, true_mole, total_regret and solver scores. Add a test asserting none of those tokens appear in the blind pack.
2. Gemini discovers the failure modes blind, citing specific (episode, step) examples. Use the explicit cache on gemini-3.8-flash, streamed.
3. **Score recovery in code** against tags.py / solver regret:
   - for each code tag, the share of its high-regret steps that fall in some Gemini-cited mode (recall);
   - the share of Gemini-cited steps that are high-regret (precision);
   - the regret share covered by the Gemini modes.
   - Quote verification counts ONLY agent-authored text (exclude any line the harness or code generated).
4. Write results/gemini/atlas_blind.{json,md}: "Gemini, without seeing our labels, recovered N of M code-defined failure modes (recall/precision table), and named K modes our tags don't have." Report honestly even if recovery is poor. Keep v1 files; add a "v1 was not blind" note at the top of atlas.md.
5. Tests green, push gemini-atlas, then write DONE in the report.
