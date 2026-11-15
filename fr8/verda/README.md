# Verda GPU queue (owner: FR8 session; the only session that creates or deletes Verda instances)

**Access** (local Claude sessions on Silas's Mac): `ssh -i ~/.ssh/verda_fr8_ed25519 root@<IP>`. Use `${IP}` in zsh (`$IP:a` is a zsh modifier).
Work in `/root/<your-session-name>/` only. Never kill processes by pattern; never touch `/root/v3`, `/root/self_reaper*.py`, or another session's directory.
No HF_TOKEN on the boxes and none in `.env`: gated weights (PaliGemma, Gemma) need Silas to add `HF_TOKEN` to `.env`, then FR8 copies it.
Each instance runs an on-instance reaper that deletes it at its deadline; ask FR8 to extend it.

## Ledger (€; price from the API at creation)
| instance | type | region | €/h | start | planned stop | owner / workload | status |
|---|---|---|---|---|---|---|---|
| 3bb74f5a-ae5f-492d-b805-daf2de7d9ebd | 1H100.80S.32V on-demand | FIN-02 | 4.7421 | 14 Nov 22:46 | reaper 15 Nov 07:30 | FR8: v3-4k s0 → v3-8k s0 (R1); shared from 00:35 with Meta glasses CEO YOLOv8n (/root/meta-glasses, ≤30 GB GPU, ≤8 CPU) | running |
| ac58df04-428c-45f8-ba69-7d62c3d64aec | 1A100.22V (80 GB) spot | FIN-01 | 1.0794 | 15 Nov 00:00 | reaper 07:30 | FR8: v3-8k s1 (R2) | **deleted 03:50** (3.83 h ≈ €4.1); adapter pulled to data/fr8/verda/a100-ac58 |
| dbd083ca-c87a-4c5f-9acf-f1ce4f6144bd | 1H100.80S.30V spot | FIN-01 | 2.3711 | 15 Nov 00:24 | reaper 07:30 | FR8: v3-8k s2 (fill order #2) | running |
| 924e81d8-e82b-4980-9e51-632241b3357d | 1A100.22V (80 GB) spot | FIN-03 | 1.0794 | 15 Nov 00:49 | reaper 07:30 | Gemini J1-lite: vLLM Qwen3-14B bf16 + canary.agents.play, 10 hard + 10 medium dev seeds (fr8/verda/j1_run.sh) | running |
| 68bbe201-dc0e-4591-83d5-cc1332ead40c | 1A100.22V (80 GB) on-demand | FIN-03 | 2.1589 | 15 Nov 01:01 | reaper 07:30 | FR8: extra held-out eval n: v2 then v3-4k s0, seeds 30-59/tier (done 03:30) → from 03:35 X2 DAgger box 1 | running |
| f4378173-9608-4361-bc6c-8f2b9e482819 | 1A100.22V (80 GB) on-demand | FIN-03 | 2.1589 | 15 Nov 01:08 | reaper 07:30 | FR8: v3-8k s3 (4th replicate; no other job ready: HF_TOKEN missing, 8k adapters not yet trained) | running |
| 18acfa5d-b5f9-4e64-a652-0de05a9f4c15 | 1A100.22V (80 GB) on-demand | FIN-01 | 2.1589 | 15 Nov 02:17 | reaper 07:30 | FR8: backup base eval, held-out seeds 6-35/tier, 150 min (FR8 44584 unreachable: FR8 SSH down) | running |
| 714d8144-c036-4814-999d-a38ed192a48f | 1A100.22V (80 GB) spot | FIN-01 | 1.0794 | 15 Nov 02:39 | reaper 07:30 | FR8: v3-4k s1 (replicate of the 4k row) | **PREEMPTED** (spot; gone from the instance list by 03:08, ~30 min into training; no result) |
| e9ea8b2e-ed28-4325-b2c7-0345f6af3bd1 | 1A100.40S.22V (40 GB) on-demand | FIN-02 | 1.5373 | 15 Nov 03:02 | reaper 08:00 | X2 DAgger box 2: x2-dagger-a6 (vLLM rollouts of v3-4k s0 → solver relabel → LoRA SFT 8k → held-out eval) | running |

Balance: €200.00 at start → €191.71 at 00:20 (account shows €200 of credit; Silas mentions €400 total, so a teammate's credit is in another account).
Capacity: Verda A100/A6000/L40S on-demand and spot have been near zero all night; FR8 polls and launches queued workloads as capacity appears.

00:35: a V100 16 GB for Meta YOLOv8n failed (no capacity, spot and on-demand); Meta shares the H100 instead (no extra cost).
Arena CEO decision 00:25: keep R2 (v3-8k second seed); S7's 7B gets A100s only as capacity appears (or FR8 V100s if Momin releases fleet GPUs).

00:24: cap raised to **€300** (Silas, confirmed to the Arena CEO directly). An H100 spot appeared at 00:23 → v3-8k seed 2. Burn now €8.19/h (H100 4.74 + A100 spot 1.08 + H100 spot 2.37) → projected ≈ €66 total by 07:30.

00:40: Meta glasses CEO finished on 3bb74f5a: YOLOv8n fine-tune in /root/meta-glasses, train 22:16:13Z → ~22:25Z (80 epochs, 513 s), eval + ONNX export ~22:30Z; 5.6 GB GPU memory, ≤8 workers, ≈0.15 GPU-h, no extra cost (shared H100). Results copied off by Meta; nothing of theirs is still running. It slowed v3 s0 by ~12% for ~10 min.

00:49: Gemini J1-lite (fill order #3, Arena CEO approved per Gemini CEO) on A100 spot 924e81d8; model in /dev/shm (48 GB disk too small). Burn now €9.27/h → projected ≈ €73 by 07:30.

01:01: extra-n eval box (fill order: v3 eval n) on A100 on-demand 68bbe201 (RTXPRO6000 skipped: Blackwell needs a newer torch than our pinned 2.5.1). Burn now €11.43/h → projected ≈ €88 by 07:30.

01:08: v3-8k seed 3 on A100 on-demand f4378173. Burn €13.59/h → projected ≈ €98 by 07:30.

01:15: Meta PaliGemma re-queued after Gemini J1 (Silas via the compute session): 1 GPU ≥40 GB (RTX PRO 6000 OK: Meta uses its own venv with a current torch), 1–2 h, --time 2.5 h equivalent (reaper), est. €3–6. Launches when HF_TOKEN appears in .env (watcher running) and a GPU is free.

01:30: v3-4k s0 (H100 3bb74f5a) training DONE: 609 GRPO steps in 2.0 h (seed 1 on the FR8 V100 gets ~250 in 4 h). Its held-out eval (seeds 0–29/tier) is running on the H100; the adapter was relayed to eval box 68bbe201 for seeds 30–59 after v2 (v2 at ~11/tier after 26 min).

01:37: Meta PaliGemma: no free GPU (RTX PRO 6000 + A100, spot and on-demand, all full) → Meta SHARES A100 f4378173 (v3-8k s3, the bonus replicate; 8.8/80 GB used). HF token copied to /root/.hf_token (root-only). Meta limits: ≤50 GB GPU, ≤10 workers, done by ~04:30. No extra cost; s3 will lose some steps.

02:12: v2 extra-n pulled (n=90; pooled v2 n=172 −0.457 ± 0.086). 02:17: backup base eval on A100 18acfa5d. Burn €15.75/h → projected ≈ €108 by 07:30 (cap €300).

02:39: v3-4k s0 eval pulled (−0.103 ± 0.081, n=90; vs v2 +0.306 ± 0.136; vs base −0.062 ± 0.122). v3-8k s0 started on the H100 at 02:20 (chain). v3-4k s1 replicate on A100 spot 714d8144. Burn €16.83/h → projected ≈ €112 by 07:30.

02:45: Meta PaliGemma 2 3B LoRA DONE on shared A100 f4378173: train 23:35:34Z → 00:12:18Z incl. eval (1,766 s training, 2 epochs), peak ~15.5 GB (capped at 0.58 of the card); an earlier batch-8 attempt OOM-exited (~69 GB) without affecting v3-8k s3. Results copied off by Meta; nothing of theirs is running. No extra cost.

02:58: X1 (causal hint test) hosted on 18acfa5d in /root/x1 (no CPU instances free in any region; the box has 22 vCPU, base eval uses ~1): node 22 + opencode 1.19.5 + uv, repo justSilas @a54f4223, only GEMINI_API_KEY in root-only /root/x1/.env. X2: v3-8k s3 (f4378173) yields to X2 when x2 sends a ready spec (CEO YES); box 2 = new capacity or 68bbe201 after ~04:15. v3-4k s0 adapter for X2: data/fr8/verda/v3-4k-s0-lora/ (weights gitignored) and on 68bbe201:/root/v3s0-lora.

03:02: X2 box 2 = A100-40G e9ea8b2e (FIN-02). Burn €18.37/h → projected ≈ €120 by 07:30.

03:08 status (CLI capture data/fr8/verda/instances-0308.txt): balance €153.98 → **€46.02 spent** so far.
- v3-4k s1 spot 714d8144 was PREEMPTED (instance gone by 03:08, SSH timeout); the 4k replicate is lost.
- Gemini J1-lite FAILED to start: the installed vLLM rejected `--rope-scaling` (unrecognised argument), and the runner waited 30 min then exited at ~01:20; the A100 sat idle ~01:20–03:10 (my watcher didn't catch it). Fixed with `--hf-overrides '{"rope_scaling":…,"max_position_embeddings":131072}'` and restarted at 03:10; the runner now exits immediately if vLLM dies.
- Steps @03:08: 8k s0 167 (H100), 8k s1 370 (A100 spot), 8k s2 619 (H100 spot), 8k s3 211 (A100, shared with Meta earlier).

03:22: X1 Gemini quota fix: GEMINI_API_KEY_2 (second GCP project, added by Silas) copied root-only to 18acfa5d:/root/x1/.env (replacing key 1) and /root/x1/.env2; verified by hash, never printed. Key 1 is reserved for the 05:45 judge rehearsal.

03:40: CORRECTION: there was no second key change. GEMINI_API_KEY_2 has had ONE value since agent-arena/.env was modified at 03:20:07 (sha256[:10] 6229d7bdd9, len 39); the 03:40 rewrite put the same value back. A reported "replacement" came from a hashing mix-up (confirmed by the Arena CEO and Gemini session). X1 runs on key 2 since 01:21:56Z.

03:30: v3-4k s0 seeds 30-59 pulled (n=90, −0.192 ± 0.096). Pooled v3-4k s0 n=180 −0.147 ± 0.063 (below base 0; vs v2 +0.315 ± 0.096, n=172). Eval box 68bbe201 now free → offered to X2.

03:35: X2 box 1 = 68bbe201 (freed after its evals; CEO OK). v3-8k s3 on f4378173 keeps running and is NOT stopped for X2.

03:45: X1 switched back to Gemini KEY 1 (sha256[:10] 33b86305b3) in 18acfa5d:/root/x1/.env (CEO: key 1 carbon idle, key 2 has its own low limit); root-only, verified by hash, never printed. X1 stops 05:40; key 1 then reserved for the judge rehearsal.

03:50: X2 DAgger started (session "DAgger round 1 for Canary tiebreaker"): box 1 = 68bbe201 (vLLM + v3-4k s0 rollout at 4k on TRAIN seeds as a pipeline check, then half of the DAgger held-out eval ~05:00–06:30); box 2 = e9ea8b2e (v3-4k s0 rollouts at 8k, 300 eps, TRAIN seeds 170000+, then relabel + SFT). f4378173 NOT needed; v3-8k s3 keeps running. X2 copies off by 07:15.

04:05: SHARED held-out world secret (CEO): one 32-byte secret, local ~/.canary_world_secret_r15 (0600, never committed), fingerprint sha256(file)[:10]=1ca0c2a64d. Placed as data/worlds/judge/SALT on 3bb74f5a (v3-8k s0) and f4378173 (v3-8k s3) while they were still TRAINING (TRAIN seeds use the public key, so no effect until their eval starts), and as /root/x2/world_secret on X2 boxes 68bbe201 + e9ea8b2e (X2 exports CANARY_WORLD_SECRET for its evals). NOT applied: v3-8k s1 (eval already done), v3-8k s2 (eval in progress), backup base 18acfa5d (eval in progress), and all earlier runs; those stay two-sample. Shared-secret rows will be labelled in the tables.

03:49: v3-8k s1 (A100-80 spot ac58df04, 371 GRPO steps, 3.0 h, 8k ctx) eval pulled: −0.777 ± 0.118 n=90 (accused .94, correct .09). Training forced-accuse correctness at MATCHED steps (WS4 readout): steps 0–99 4k .19 ± .04 vs 8k .35 ± .05 (8k head start on WHOM from solver states); steps 271–370 4k .37 ± .05 vs 8k .41 ± .06 (overlap; 4k reaches .89 by step 609), so 8k does not learn whom faster. Held-out precision 8k 8/85 = .09 vs 4k 6/38 = .16. Also in its own full episodes it accuses ~always and early: an off-policy state gap (training states come from solver trajectories). Own per-process worlds, so Δs are two-sample.

03:50: deleted ac58df04 (v3-8k s1, results + adapter pulled). Balance €139.23 → €60.77 spent.

04:05: X2 evals use the SHARED secret (CANARY_WORLD_SECRET from /root/x2/world_secret; verified, no per-process-secret warning). Running on 68bbe201: v3-4k s0 RE-EVAL at 8k ctx (run ids v3-4k-s0-ctx8k-off{0,10,20}, seeds 0–29, 3 parallel processes); two no-secret starts (~2 min) were killed by PID and set aside in /root/x2/evals-nosecret (not used). DAgger SFT on e9ea8b2e ends ~04:40, then dagger-r1-ctx8k-off* (same secret, seeds 0–29). X2 finding from vLLM rollouts on TRAIN seeds: v3-4k s0 at 8k context accuses in 60–90% of episodes (mostly wrong) vs ~0–3% at 4k, so the 8k over-accusing is at least partly an INFERENCE-context effect; the shared-secret re-eval tests it. Shared-secret (paired) set: v3-8k s0, v3-8k s3, v3-4k s0@8k re-eval, DAgger r1.
