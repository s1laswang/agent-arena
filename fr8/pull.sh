#!/usr/bin/env bash
# Pull results: fr8/pull.sh <job>  ->  data/fr8/<job>/   (big files stay out of git; see .gitignore)
set -euo pipefail
job=${1:?usage: fr8/pull.sh <job>}
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
mkdir -p "data/fr8/$job"
rsync -az --exclude 'parts/' --exclude '*.jsonl' "freighter:~/agent-arena-data/$job/" "data/fr8/$job/"
echo "pulled -> data/fr8/$job"; du -sh "data/fr8/$job"
