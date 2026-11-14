#!/usr/bin/env bash
# Run the Poisoned Inbox evaluation with Harbor, the way the judges rerun it:
#   reference run, do-nothing, stop-early, a reward-hack probe, and (with MODEL) 3 agent runs per task.
#
#   harbor/run_all.sh                                        # baselines only, no API key needed
#   MODEL=<provider>/<model> harbor/run_all.sh               # plus 3 OpenCode runs per task (e.g. gemini/...)
#   QUICK=1 harbor/run_all.sh                                # one task per family (smoke test)
#
# Settings (environment variables):
#   MODEL         OpenCode model, provider/model (needs that provider's API key in the env)
#   ATTEMPTS      agent runs per task (default 3)
#   HARBOR        harbor command (default "harbor"; e.g. "python -m harbor.cli.main")
#   PYTHON        python for our scripts (default python3)
#   JOBS          job output folder (default harbor/jobs)
#   N_CONCURRENT  trials at once (default 4)
#   QUICK=1       only the first task of each family
#   INCLUDE       Harbor task-name glob(s), space separated, e.g. "ap_run-s1-*"
#   VERIFIER      separate (default) or shared (for Harbor versions without a separate verifier)
#   SKIP_BUILD=1  use the task folders as they are
#   STEPS         which runs, default "reference do-nothing stop-early cheat agent"
set -uo pipefail
cd "$(dirname "$0")/.."

read -r -a HB <<< "${HARBOR:-harbor}"
PYTHON="${PYTHON:-python3}"
JOBS="${JOBS:-harbor/jobs}"
N="${N_CONCURRENT:-4}"
ATTEMPTS="${ATTEMPTS:-3}"
TASKS="harbor/tasks"
STEPS="${STEPS:-reference do-nothing stop-early cheat agent}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ "${SKIP_BUILD:-0}" != "1" ]; then
    "$PYTHON" harbor/build_tasks.py --verifier "${VERIFIER:-separate}" || exit 1
fi

FILTER=()
if [ "${QUICK:-0}" = "1" ] && [ -z "${INCLUDE:-}" ]; then
    INCLUDE="$(ls "$TASKS" | awk -F'-s' '!seen[$1]++' | tr '\n' ' ')"
fi
for pat in ${INCLUDE:-}; do FILTER+=(-i "$pat"); done

run() {  # run NAME harbor-args...
    local name="$1"; shift
    echo
    echo "=== $name ==="
    "${HB[@]}" run -p "$TASKS" ${FILTER[@]+"${FILTER[@]}"} -y -n "$N" -o "$JOBS" --job-name "$STAMP-$name" "$@" \
        || echo "warning: harbor exited with an error for $name (see $JOBS/$STAMP-$name)"
}

for step in $STEPS; do
    case "$step" in
        reference)  run reference  -a oracle ;;                                    # must be 1.0
        do-nothing) run do-nothing -a nop ;;                                       # must be 0.0
        stop-early) run stop-early -a oracle --ae PINBOX_SOLUTION=stop_early_50 ;; # must be 0.0
        cheat)      run cheat      -a oracle --ae PINBOX_SOLUTION=cheat ;;         # must be 0.0
        agent)
            if [ -n "${MODEL:-}" ]; then
                run "opencode-${MODEL//\//_}" -a opencode -m "$MODEL" -k "$ATTEMPTS"
            else
                echo; echo "=== agent === skipped (set MODEL=provider/model to run OpenCode)"
            fi ;;
        *) echo "unknown step $step" ;;
    esac
done

echo
"$PYTHON" harbor/summarize.py "$JOBS" --prefix "$STAMP" --json "$JOBS/$STAMP-summary.json"
