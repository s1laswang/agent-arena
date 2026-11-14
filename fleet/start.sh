#!/bin/zsh
set -e
PER_TEAM=${1:-40}
D=${0:A:h}
rsync -a $D/teams.conf $D/role_lead.md $D/role_worker.md $D/agent_loop.sh $D/team_job.sh $D/opencode.json $D/setup_on_fr8.sh freighter:momin/fleet/
ssh freighter "rm -f ~/momin/fleet/STOP && bash ~/momin/fleet/setup_on_fr8.sh $PER_TEAM"
for t in $(cut -d'|' -f1 $D/teams.conf); do
  ssh freighter "cd ~/momin/fleet && sbatch -J fleet-$t team_job.sh $t"
done
ssh freighter 'squeue -u silas -o "%i %j %T %N"'
