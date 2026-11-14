#!/usr/bin/env bash
# J5 Mole Forge on the Mac, stub LLM, <=3 workers. Gate: canary/forge must exist.
# CLI: canary.forge.evolve --mutator stub|gemini:<model> --tier --pop --gens --seeds --workers --out
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
[ -d canary/forge ] || { echo "canary/forge not merged yet" >&2; exit 1; }
out=data/fr8/j5/run-$(date +%Y%m%d-%H%M); mkdir -p "$out"
OMP_NUM_THREADS=1 uv run --python 3.12 --extra dev python -m canary.forge.evolve --mutator stub --seed 0 --workers 3 --out "$out" "$@"
