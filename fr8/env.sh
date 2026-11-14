# Sourced by every sbatch script / srun test: activates whichever env fr8/setup.sh built.
cd ~/agent-arena
export UV_CACHE_DIR=$HOME/agent-arena-data/cache/uv PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
case "$(cat $HOME/agent-arena-data/envkind 2>/dev/null)" in
  uv) source .venv/bin/activate ;;
  module) module load pytorch-volta ;;
  *) echo "fr8/env.sh: run fr8/setup.sh first" >&2; return 1 ;;
esac
