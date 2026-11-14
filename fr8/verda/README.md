# Verda GPU queue (owner: FR8 session; the only session that creates or deletes Verda instances)

**Access** (local Claude sessions on Silas's Mac): `ssh -i ~/.ssh/verda_fr8_ed25519 root@<IP>`. Use `${IP}` in zsh (`$IP:a` is a zsh modifier).
Work in `/root/<your-session-name>/` only. Never kill processes by pattern; never touch `/root/v3`, `/root/self_reaper*.py`, or another session's directory.
No HF_TOKEN on the boxes and none in `.env`: gated weights (PaliGemma, Gemma) need Silas to add `HF_TOKEN` to `.env`, then FR8 copies it.
Each instance runs an on-instance reaper that deletes it at its deadline; ask FR8 to extend it.

## Ledger (€; price from the API at creation)
| instance | type | region | €/h | start | planned stop | owner / workload | status |
|---|---|---|---|---|---|---|---|
| 3bb74f5a-ae5f-492d-b805-daf2de7d9ebd | 1H100.80S.32V on-demand | FIN-02 | 4.7421 | 14 Nov 22:46 | reaper 15 Nov 07:30 | FR8: v3-4k s0 → v3-8k s0 (R1); shared from 00:35 with Meta glasses CEO YOLOv8n (/root/meta-glasses, ≤30 GB GPU, ≤8 CPU) | running |
| ac58df04-428c-45f8-ba69-7d62c3d64aec | 1A100.22V (80 GB) spot | FIN-01 | 1.0794 | 15 Nov 00:00 | reaper 07:30 | FR8: v3-8k s1 (R2) | running |
| dbd083ca-c87a-4c5f-9acf-f1ce4f6144bd | 1H100.80S.30V spot | FIN-01 | 2.3711 | 15 Nov 00:24 | reaper 07:30 | FR8: v3-8k s2 (fill order #2) | running |

Balance: €200.00 at start → €191.71 at 00:20 (account shows €200 of credit; Silas mentions €400 total, so a teammate's credit is in another account).
Capacity: Verda A100/A6000/L40S on-demand and spot have been near zero all night; FR8 polls and launches queued workloads as capacity appears.

00:35: a V100 16 GB for Meta YOLOv8n failed (no capacity, spot and on-demand); Meta shares the H100 instead (no extra cost).
Arena CEO decision 00:25: keep R2 (v3-8k second seed); S7's 7B gets A100s only as capacity appears (or FR8 V100s if Momin releases fleet GPUs).

00:24: cap raised to **€300** (Silas, confirmed to the Arena CEO directly). An H100 spot appeared at 00:23 → v3-8k seed 2. Burn now €8.19/h (H100 4.74 + A100 spot 1.08 + H100 spot 2.37) → projected ≈ €66 total by 07:30.

00:40: Meta glasses CEO finished on 3bb74f5a: YOLOv8n fine-tune in /root/meta-glasses, train 22:16:13Z → ~22:25Z (80 epochs, 513 s), eval + ONNX export ~22:30Z; 5.6 GB GPU memory, ≤8 workers, ≈0.15 GPU-h, no extra cost (shared H100). Results copied off by Meta; nothing of theirs is still running. It slowed v3 s0 by ~12% for ~10 min.
