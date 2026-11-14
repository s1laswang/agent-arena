# Sourced by fr8/gemini/*.sh on the Mac. Paths on freighter (never ~/agent-arena, ~/agent-arena-trainer, ~/momin).
FR8_HOST=${FR8_HOST:-freighter}
GEM_CODE='$HOME/agent-arena-gemini'                # code checkout + .venv + .gateway_token + .gateway.env (0600)
GEM_DATA='$HOME/agent-arena-data/gemini'           # ledger/, gateway/ (stats+log), logs/, ladder/, ...
GW_PORT=${GW_PORT:-8787}
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
