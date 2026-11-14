# Training (tiebreaker, stretch goal)

## What this is

The tiebreaker asks one question: can our environment teach a model?

Our plan has three steps:

1. Turn good runs into training data. We use the scripted reference agent, plus any LLM runs that scored 1.
2. Fine-tune a small open model on that data with LoRA. The default model is Qwen3-4B-Instruct.
3. Test the model before and after training on the same eval episodes. Then we compare the scores.

The training data only uses **train seeds** (1000-1999). It never uses eval seeds. The export
checks every row and stops with an error if an eval seed gets in.

## What works and what is untested

| Part | Status |
|---|---|
| `export_sft.py`: makes the data | Works. Unit tested. Stdlib only. |
| `eval_small_model.py --dry-run`: the agent loop, parser and table, with fake models | Works. Unit tested. |
| `train_lora.py --dry-run`: prints the config and data sizes | Works. Unit tested. |
| Rendering with the real Qwen3 chat template | Checked by hand on 180 rows (all 3 families). The loss mask covers only the tool calls and summary, and every call parses back. |
| `train_lora.py`: real training | Ran end to end on **CPU** with a tiny random Qwen3 model (torch 2.15 CPU, transformers 5.23, TRL 1.18, PEFT 0.21). The loss went down. The assistant-only loss equals HF's own loss, and the gradients match. **The fp16 GPU path is UNTESTED.** |
| `eval_small_model.py` with a real model | Ran on CPU with the same tiny model, adapter off and on, and its saved runs re-grade with `pinbox eval`. **Untested on a GPU and with a real 4B model.** |
| `slurm/*.sbatch` | **UNTESTED.** Change the partition and paths first. |

So we have **no trained model and no before/after numbers yet**.

## Step 1: make the data (no GPU)

```bash
python training/export_sft.py                      # every family, 200 rows each -> training/data/sft.jsonl
python training/export_sft.py --n-per-family 50 --families ap_run
python training/export_sft.py --recorded runs/gemini   # also add Gemini runs that scored 1 (non-eval seeds only)
```

Each row is one finished episode in OpenAI / Hugging Face chat format:
- `system`: the full task instruction and policy.
- `user`: "Start the task now...".
- `assistant`: one tool call (`tool_calls`).
- `tool`: the tool result, as compact JSON.
- At the end, one `assistant` summary with no tool call.

Each row also has `tools`, the tool specs. `--openai-only` keeps just `messages` and `tools`.

Recorded runs are replayed on a fresh world and graded again. We keep a run only if it still
scores 1. Runs on eval seeds are always skipped.

Most saved LLM runs are on the eval set, so they will all be skipped. To add LLM data, record
runs on train seeds (1000-1999). Example:
`python -m pinbox.agents.gemini_agent --family ap_run --seed 1234 --difficulty 2 --runs-dir runs/gemini_train`.

Load the file with Python's `json` module, one line at a time. The `datasets` JSON loader
merges the different tool schemas into one, and that fills them with nulls.

Sizes with the Qwen3 tokenizer (60 rows per family):

| Family | Median tokens | Max tokens | Rows over 16384 |
|---|---|---|---|
| ap_run | 10.9k | 23k | about 1 in 4 (the long, hard ones) |
| refunds | 7.5k | 11.4k | none |
| board_pack | 6.3k | 9.1k | none |

Only about 1k tokens per row are trained: the tool calls and the summary.

## Step 2: train (GPU, untested)

```bash
pip install -r training/requirements.txt          # in a GPU env (torch with CUDA)
python training/train_lora.py --dry-run           # check the config first
python training/train_lora.py --data training/data/sft.jsonl
```

The settings are made for **one V100**:
- fp16 base weights and fp32 LoRA weights. The V100 has no bf16.
- `sdpa` attention. The V100 has no FlashAttention-2.
- Gradient checkpointing is on.
- The loss only covers the assistant turns: the tool calls and the final summary.
- The output layer only runs on those tokens. This saves a lot of memory on 10k-token conversations.

Useful flags:
- `--model`: any HF id. Example: `Qwen/Qwen2.5-1.5B-Instruct` for a fast first try.
- `--max-len`: 16384 by default. Longer rows are dropped, or cut with `--truncate`.
- `--epochs`, `--lr`, `--lora-r`, `--grad-accum`.
- `--resume`: continue from the last checkpoint.
- `--trainer hf`: use the plain transformers Trainer if TRL causes trouble.

On a 16 GB V100, try `--max-len 8192` or a 1.5B model. On a 32 GB V100, `--max-len 20480` keeps more of
the hard ap_run rows. These memory numbers are guesses. We could not measure them.

Rough time guess: 600 rows is about 5M tokens per epoch. That is probably 1 to 2 hours per epoch for a
4B model on one V100.

If the loss turns into NaN in fp16, try these: a lower `--lr`, a smaller model, or `--precision fp32` with a small model.

The output is a LoRA adapter folder: `training/out/<model>-lora/`.

## Step 3: before / after (GPU, untested)

```bash
python training/eval_small_model.py --model Qwen/Qwen3-4B-Instruct-2507 \
    --adapter training/out/Qwen3-4B-Instruct-2507-lora --limit 10 --save-runs runs/small_model
python -m pinbox eval --include-recorded runs/small_model      # re-grade the saved runs, no GPU
```

This loads the model once. The "before" runs turn the adapter off, and the "after" runs turn it on.
It uses greedy decoding on the frozen **eval** set, `--limit` episodes per family. It prints a
table with the mean reward, pass rate, progress, calls, parse errors and per-family scores.

The model writes tool calls as JSON inside `<tool_call>...</tool_call>`. The parser is
tolerant. It also reads ```json blocks, bare JSON, trailing commas and a missing closing
brace. A call cut off inside a string is never run. If a reply looks like a broken call, the
model gets up to 2 nudges.

`--protocol` must match training. `auto` uses the model's own chat template when it supports
tools. Otherwise it puts the tools in the system text.

Plumbing check, no ML libraries needed:

```bash
python training/eval_small_model.py --dry-run --limit 3
```

"before" is a fake model that does nothing, so it scores 0. "after" is a fake model that types the
reference agent's calls as text in 3 different formats, so it scores 1.

## Slurm (FR8, 1 GPU per job, UNTESTED)

```bash
sbatch training/slurm/export_sft.sbatch
sbatch training/slurm/train_lora.sbatch          # MODEL=... EPOCHS=... MAX_LEN=... to override
sbatch training/slurm/eval_small_model.sbatch    # ADAPTER=... LIMIT=...
```

Submit from the repo root. First, edit `training/slurm/common.sh`: the modules, the venv path
(`PINBOX_VENV`) and `HF_HOME`. Also set the partition lines in the `.sbatch` files. The logs go
to `training/slurm/logs/`.

## Files

- `common.py`: the chat format, prompt rendering and tolerant tool-call parser. Training and eval share it.
- `export_sft.py`: makes the SFT data.
- `train_lora.py`: LoRA training.
- `eval_small_model.py`: the before/after eval.
- `slurm/`: the cluster job scripts.
- `requirements.txt`: the GPU-side dependencies. The export and the dry runs need none.
- Tests: `tests/test_training.py`.
