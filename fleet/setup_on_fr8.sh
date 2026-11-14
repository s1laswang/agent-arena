#!/bin/bash
set -e
PER_TEAM=${1:-40}
F=$HOME/momin/fleet
B=$F/board
mkdir -p $F/agents $F/logs $B
[ -f $B/CHIEF.md ] || printf '# Chief instructions\n\nWork toward your team goal. Deadline Sun 15 Nov 10:00 Helsinki.\n' > $B/CHIEF.md
for repo in $F/repos/*.git; do
  git -C $repo remote get-url origin >/dev/null 2>&1 || git -C $repo remote add origin $repo
  for wt in $(git -C $repo worktree list --porcelain | awk '/^worktree /{print $2}' | grep "$F/agents/" || true); do
    git -C $repo worktree remove --force $wt || true
  done
  git -C $repo worktree prune
done
while IFS='|' read -r TEAM REPO BASE GOAL; do
  [ -z "$TEAM" ] && continue
  R=$F/repos/$REPO.git
  mkdir -p $B/$TEAM/inbox $B/$TEAM/outbox
  LEAD=$TEAM-lead
  WORKERS=""
  for n in $(seq -w 1 $((PER_TEAM - 1))); do WORKERS="$WORKERS $TEAM-w$n"; done
  echo "$TEAM|$REPO|$LEAD $WORKERS" > $F/agents/$TEAM.members
  for a in $LEAD $WORKERS; do
    [ "$a" = "$LEAD" ] && br=fr8/$TEAM/main || br=fr8/$TEAM/${a}
    git -C $R show-ref --verify -q refs/heads/$br || git -C $R branch $br $BASE
    [ "$a" = "$LEAD" ] && tpl=$F/role_lead.md || tpl=$F/role_worker.md
    sed -e "s|{NAME}|$a|g" -e "s|{TEAM}|$TEAM|g" -e "s|{REPO}|$REPO|g" -e "s|{BOARD}|$B|g" -e "s|{LEAD}|$LEAD|g" -e "s|{WORKERS}|$WORKERS|g" -e "s|{GOAL}|$GOAL|g" $tpl > $F/agents/$a.role.md
    touch $B/$TEAM/inbox/$a.md $B/$TEAM/outbox/$a.md
  done
  echo "$TEAM: $PER_TEAM agents on $REPO from $BASE"
done < $F/teams.conf
