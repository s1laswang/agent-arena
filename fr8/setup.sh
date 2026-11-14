#!/usr/bin/env bash
# Idempotent env setup ON THE FR8 LOGIN NODE (light work only). Writes $HOME/agent-arena-data/envkind
set -uo pipefail
cd ~/agent-arena
export UV_CACHE_DIR=$HOME/agent-arena-data/cache/uv
export UV_PYTHON_INSTALL_DIR=$HOME/agent-arena-data/cache/python
mkdir -p "$UV_CACHE_DIR"
if ! command -v uv >/dev/null && [ ! -x ~/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh || true
fi
export PATH=$HOME/.local/bin:$PATH
if command -v uv >/dev/null && uv sync --python 3.12 --extra dev; then
  echo uv > $HOME/agent-arena-data/envkind
else
  echo "uv failed; falling back to module + pip --user" >&2
  module load pytorch-volta && pip install --user -e '.[dev]' && echo module > $HOME/agent-arena-data/envkind
fi
echo "env kind: $(cat $HOME/agent-arena-data/envkind)"
