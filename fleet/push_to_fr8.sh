#!/bin/zsh
set -e
REPOS=(s1laswang/agent-arena s1laswang/junction-aimo-agents s1laswang/junction-meta-glasses Momin010/junction26-valio)
TMP=$(mktemp -d)
ssh freighter 'mkdir -p ~/momin/fleet/repos'
for r in $REPOS; do
  n=${r:t}
  echo "== $r"
  git clone -q --mirror "https://github.com/$r.git" "$TMP/$n.git"
  ssh freighter "[ -d ~/momin/fleet/repos/$n.git ] || git init -q --bare ~/momin/fleet/repos/$n.git"
  git -C "$TMP/$n.git" push -q --mirror "freighter:momin/fleet/repos/$n.git"
  echo "   pushed $(git -C "$TMP/$n.git" branch | wc -l | tr -d ' ') branches"
done
rm -rf "$TMP"
ssh freighter 'du -sh ~/momin/fleet/repos/*.git'
