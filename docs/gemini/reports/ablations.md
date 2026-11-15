# gemini-ablations report

## Sun Nov 15 02:46:56 EET 2026
- Added opt-in `LedgeredClient(drop_signatures=True)` / `lab_client(..., drop_signatures=True)` and `ladder --no-thought-signatures` (recorded in meta.json as `thought_signatures: false`, provider_settings `thought_signature_replay: false`). Off by default; tests/test_gemini_lab_ablations.py.
- Sig-OFF arm (gemini-3.8-flash medium hard seeds 0-9, run ablation-sig-off): 10/10 episodes infra-invalid. Every first call OK, every second call (first function-call replay) 400 INVALID_ARGUMENT "Function call is missing a thought_signature in functionCall parts". Concurrency 8 launched all 10 seeds before the stop; stopped after attempt 1 (20 calls total, own PID only). Evidence: results/gemini/ablations_sig_off/.
- ON arm = committed ladder cell (n=10): 0/628 API errors, 0 invalid tool calls, accuracy 70% [40,89], 14% of solver [-71,85].
- Cache: atlas 62.9% saved ($58.56 -> $21.72); gallery used no cache (0%); programme 75.9% ($893 -> $215). Storage cost not ledgered.
- Sweep: 34 cells, 17 with CI excluding 100%.
- Outputs: results/gemini/ablations.{json,md}, generator canary/gemini/ablations.py.
