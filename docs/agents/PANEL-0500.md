# Judge-panel fixes (70/100 panel, ~04:30): status and prompts

| Fix | Status | Owner |
|---|---|---|
| **A. Docs honesty** | **Done** (92708834). README: the clearance rule never binds (W4). gap.md and README: seeds 0-29 are a post-hoc lock (671ed96 came 28 s after 8fd4dec), not a pre-registration; the 20+10 solver reference dirs are explained. The README already leads with the raw 65% [24, 98]; luck-adjusted comes second. The Gemini SUBMISSION.md wording was sent to the Gemini CEO. | CEO |
| **B. Real Harbor rehearsal** | **Running at the tag (~05:40):** 3 OpenCode runs × 10 hard judge tasks + oracle/do_nothing/stop_early, under a pre-registered protocol (results/harbor/rehearsal/README.md), committed whatever the result. Risk: the shared Gemini quota (2M TPM; Silas keeps orchestrators + Momin's fleet on carbon), so it may report "blocked by quota" with the infra counts. | s1-rehearsal |
| **C. Non-Gemini frontier model** | **Not possible tonight:** no OpenAI or Anthropic API key (the OpenAI key was removed by Silas's order). Closest substitute: Qwen3-14B self-hosted on Verda (open weights; Gemini J1, in-process, not Harbor), reported in the Gemini docs only. Stated in the 08:00 brief. | — |
| **D. Specific tool error messages / W1 fix** | **Declined before the tag.** Error strings are recorded tool results in every committed episode; changing them breaks step-level replay of ~1,000 episodes and makes the judged text differ from what every frontier run saw. W1 stays disclosed (docs/DIFFICULTY.md). | CEO decision |
| **E. Tiebreak** | **Running:** DAgger round 1 (on-policy states labelled by the solver), paired eval under one shared world secret. Result ~06:30–07:30; added as an addendum only if it beats 0 with a CI excluding 0. | DAgger session |

## Final verification prompt (paste into a fresh session at ~07:45 if wanted)
```
Verify Canary's submitted state (repo s1laswang/agent-arena). In /tmp: git clone -b afterquery-final https://github.com/s1laswang/agent-arena canary-check && cd canary-check && make setup && make reproduce && make accept. Expect: exit 0; the last line HEADLINE "65% [24%, 98%] ... (luck-adjusted 72% [52%, 91%])"; ANTI-CHEAT all blocked; accept PASS=20. Then `uv run --python 3.12 --extra dev python -m pytest -q` (expect ~1,055 passed). Report the results to "Arena · CEO" via SendMessage. Change nothing; never pkill by pattern.
```

## Human-only list for Silas (08:00)
1. Video: the storyboard and voice-over are in docs/VIDEO-STORYBOARD.md and docs/video/vo/. Record or assemble it, or skip it.
2. Submit on the Junction platform by 09:30:
   - AfterQuery: link to tag `afterquery-final`;
   - Gemini: docs/gemini/SUBMISSION.md at its gemini-final tag;
   - Verda: VERDA.md.
3. Optional: the human baseline (2 hard dev seeds each in `make game-serve`).
