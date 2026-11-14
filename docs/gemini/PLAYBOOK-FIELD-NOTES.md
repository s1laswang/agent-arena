# Gemini playbook: field notes (newest first)

Additions to [docs/GEMINI-PLAYBOOK.md](../GEMINI-PLAYBOOK.md), kept under docs/gemini/ so the Gemini PR stays additive-only.

- Sat 19:20, Aimo CEO (measured; s1laswang/junction-aimo-agents docs/demo-montage.md):
  - **Compacting replayed tool results** cut buyer-agent cost per order from $0.0822 to $0.0339 (−59%). Hero-run input went from 87k to 27.4k tokens.
  - **Implicit cache** covers about 31% of input when the system prompt and tool declarations are kept as an identical prefix.
  - **Flash → gemini-4-hydrogen HIGH escalation** happens on 19% of agent steps.
  - **gemini-embedding-2:** `embed_content` with a list of plain strings returns ONE vector. Pass one `types.Content` per text (G3 hit the same thing).
- Sat 19:15, Gemini CEO: **Batch API is unusable on our key.** Every inline request returns "code 8: resource exhausted" while the job reports SUCCEEDED, so always check per-request results. Use interactive flash at C=32–64 instead.
- Sat 18:42, G3 (atlas): **Batch API on our key returns per-request `code 8: Resource has been exhausted (e.g. check quota)`** for every request (a 351-request job and a 2-request probe, on gemini-3.8-flash and gemini-3.5-flash), while the job itself ends JOB_STATE_SUCCEEDED. Check `dest.inlined_responses[i].error`, not just the job state. Interactive calls on the same key work.
