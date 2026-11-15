# Verda evidence collected for VERDA.md (Compute Track)

## Meta glasses: FieldSpotter (reported by the Meta glasses CEO, Sun 15 Nov ~01:10)
Full write-up: s1laswang/junction-meta-glasses main, docs/evidence/verda-fieldspotter.md.
- **What:** a YOLOv8n label-field detector (product / strength / expiry / allergens), fine-tuned on HoldUp's 1,740 Gemini-generated, ground-truthed label images.
- **Where:** the Verda H100 80GB, shared with the Canary tiebreaker via the FR8 queue (instance 3bb74f5a). Training 22:16→22:25 UTC, 80 epochs, ≈ 0.15 GPU-h, 5.6 GB VRAM. Eval and ONNX export ran on the same box; data prep ran on the laptop.
- **Results** (held-out by label, n = 348 images):
  - strength-visible precision 96.8% (Wilson 92.1–98.8), recall 65.6% (58.5–72.0);
  - mAP@0.5 0.572 (strength 0.607, expiry 0.616, product 0.663, allergens 0.401);
  - ONNX 12.8 MB, p50 34.5 ms on CPU (≈ 29 fps).
- **Status:** committed (web/public/models/fieldspotter.onnx); not yet wired into the live coaching loop. PaliGemma 2 was NOT done (no A100 capacity, no HF token).
- **Honest note:** it slowed the co-tenant v3 training by ~12% while running; stopped after one run.

## Canary (AfterQuery) small-model tiebreaker
See docs/reports/fr8.md, section "Verda", and fr8/verda/README.md (ledger), both on branch justSilas-fr8. Instances:
- H100 3bb74f5a (v3-4k s0, then v3-8k s0);
- A100-80G spot ac58df04 (v3-8k s1);
- H100 spot dbd083ca (v3-8k s2).

## Meta glasses: PaliGemma 2 3B label-field detector (reported ~03:00)
Details: GEMMA.md on junction-meta-glasses main (136f18d).
- **What:** `google/paligemma2-3b-pt-448`, LoRA r16, on the same 1,740 Gemini-generated images (split by label: 1,392 train / 348 held out).
- **Where:** Verda A100-SXM4-80GB, instance f4378173 (FIN-03), shared via FR8 with v3-8k seed 3. Training 23:35:34Z → 00:12:18Z, 2 epochs, ~29 min, peak 15.5 GB.
- **Results** (n=348):
  - "strength visible" recall 91.4% (86.5–94.6) vs YOLOv8n 65.6%;
  - precision 89.9% (84.8–93.5) vs YOLO 96.8%;
  - 1.43 s/image vs YOLO 34.5 ms on CPU.
- **Framing:** complementary (Gemma for high-recall "dose in view", YOLO for real-time boxes); not yet wired into the live product.
- **Total HoldUp Verda use:** ~0.15 GPU-h on H100 (YOLO) + ~0.65 GPU-h on A100 (PaliGemma, including one OOM'd attempt).
