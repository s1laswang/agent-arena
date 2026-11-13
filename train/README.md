Smoke (CPU, python3.12 venv with torch 2.2.2 transformers 4.44.2 peft 0.12.0):
python -m train.sft --model sshleifer/tiny-gpt2 --data train/data/train.jsonl --out /tmp/ad --epochs 2 --accum 3 --max_len 512
python -m train.eval --model M --adapter A --out O --day-ids 1000-1019   (omit --adapter for base)
python -m train.metrics <run_dir> controller
