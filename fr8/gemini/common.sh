# Sourced by fr8/gemini/*.sh on the Mac. Paths on freighter (never ~/agent-arena, ~/agent-arena-trainer, ~/momin).
FR8_HOST=${FR8_HOST:-freighter}
GEM_CODE='$HOME/agent-arena-gemini'                # code checkout + .venv + .gateway_token + .gateway.env (0600)
GEM_DATA='$HOME/agent-arena-data/gemini'           # ledger/, gateway/ (stats+log), logs/, ladder/, ...
GW_PORT=${GW_PORT:-8787}
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
# One multiplexed TCP session to FR8 (many fresh connections get rate-limited): every ssh/rsync below reuses it.
FR8_SSH_OPTS=(-o ControlMaster=auto -o ControlPersist=10m -o "ControlPath=$HOME/.ssh/cm-%r@%h:%p"
              -o ConnectTimeout=20 -o ServerAliveInterval=30)
ssh() { command ssh "${FR8_SSH_OPTS[@]}" "$@"; }
FR8_RSYNC_RSH="ssh -o ControlMaster=auto -o ControlPersist=10m -o ControlPath=$HOME/.ssh/cm-%r@%h:%p -o ConnectTimeout=20"
