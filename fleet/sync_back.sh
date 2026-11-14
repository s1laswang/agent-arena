#!/bin/zsh
set -e
TMP=$(mktemp -d)
for r in s1laswang/agent-arena s1laswang/junction-aimo-agents s1laswang/junction-meta-glasses Momin010/junction26-valio; do
  n=${r:t}
  git clone -q --bare "freighter:momin/fleet/repos/$n.git" "$TMP/$n.git"
  refs=$(git -C "$TMP/$n.git" for-each-ref --format='%(refname:short)' 'refs/heads/fr8/*')
  [ -z "$refs" ] && continue
  for b in ${(f)refs}; do git -C "$TMP/$n.git" push -q "https://github.com/$r.git" "refs/heads/$b:refs/heads/$b"; done
  echo "$r: pushed $(echo $refs | wc -l | tr -d ' ') fr8/* branches"
done
rm -rf "$TMP"
