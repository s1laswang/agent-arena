#!/bin/bash
NAME=$1
F=$HOME/momin/fleet
set -a; . $HOME/momin/.env; set +a
export OPENCODE_CONFIG=$F/opencode.json
L=/tmp/fleet-$USER/$NAME
mkdir -p $L/data $L/state $L/cache
export XDG_DATA_HOME=$L/data XDG_STATE_HOME=$L/state XDG_CACHE_HOME=$L/cache
MODEL=${FLEET_MODEL:-google/gemini-4-carbon}
cd ${2:-$F/agents/$NAME} || exit 1
while [ ! -f $F/STOP ]; do
  timeout 1800 $HOME/momin/bin/opencode run -m "$MODEL" "$(cat $F/agents/$NAME.role.md)" >> $F/logs/$NAME.log 2>&1
  sleep ${FLEET_PAUSE:-20}
done
