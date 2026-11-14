#!/bin/bash
#SBATCH --partition=normal
#SBATCH --cpus-per-task=16
#SBATCH --mem=40G
#SBATCH --time=24:00:00
#SBATCH --output=/home/silas/momin/fleet/logs/job-%x-%j.out
TEAM=$1
F=$HOME/momin/fleet
IFS='|' read -r T REPO MEMBERS < $F/agents/$TEAM.members
R=$F/repos/$REPO.git
W=/tmp/fleet-$USER/wt
mkdir -p $W
i=0
for a in $MEMBERS; do
  [ "$a" = "$TEAM-lead" ] && br=fr8/$TEAM/main || br=fr8/$TEAM/$a
  rm -rf $W/$a
  apptainer exec /opt/containers/pytorch-volta.sif git clone -q -s -b $br $R $W/$a
  apptainer exec /opt/containers/pytorch-volta.sif git -C $W/$a config user.name "$a"
  apptainer exec /opt/containers/pytorch-volta.sif git -C $W/$a config user.email "$a@fleet.local"
  sleep $((i * 8))
  apptainer exec /opt/containers/pytorch-volta.sif bash $F/agent_loop.sh $a $W/$a &
  i=1
done
wait
