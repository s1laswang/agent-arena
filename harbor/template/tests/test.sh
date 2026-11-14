#!/bin/bash
# Poisoned Inbox verifier for Harbor. Writes /logs/verifier/reward.txt (1 or 0).
# The reward is 1 only if every check of the episode's grade passed.
# verify.py also writes grade.json and verdict.json next to the reward.
set -u
mkdir -p /logs/verifier

if [ -f /tests/admin_token ]; then
    # Shared-verifier build: we run inside the agent's container. Stop anything the agent left
    # running (for example a loop that keeps rewriting the reward file). Keep PID 1, the
    # container's own keep-alive command (the oldest child of PID 1), this script and its parents.
    # This does not protect against programs the agent replaced; see README.
    keep=" 1 $$ "
    pid=$$
    while [ "$pid" -gt 1 ] 2>/dev/null; do
        stat=$(cat "/proc/$pid/stat" 2>/dev/null) || break
        set -- ${stat##*) }            # fields after "(comm) ": state ppid ... (starttime is the 20th)
        pid=$2
        keep="$keep$pid "
    done
    oldest=""; oldest_start=""
    for dir in /proc/[0-9]*; do
        stat=$(cat "$dir/stat" 2>/dev/null) || continue
        set -- ${stat##*) }
        if [ "$2" = "1" ] && { [ -z "$oldest_start" ] || [ "${20}" -lt "$oldest_start" ]; }; then
            oldest="${dir#/proc/}"; oldest_start="${20}"
        fi
    done
    keep="$keep$oldest "
    for dir in /proc/[0-9]*; do
        p="${dir#/proc/}"
        case "$keep" in *" $p "*) ;; *) kill -9 "$p" 2>/dev/null ;; esac
    done
    rm -f /logs/verifier/reward.txt /logs/verifier/reward.json
fi

# -I -S: ignore PYTHON* variables, the user site folder and sitecustomize.
if ! python3 -I -S /tests/verify.py; then
    echo "verify.py failed; reward 0" >&2
    echo 0 > /logs/verifier/reward.txt
fi
exit 0
