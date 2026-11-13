#!/bin/bash
set -e
cd "$(dirname "$0")/.."
ssh freighter 'mkdir -p ~/momin/sleeper/logs ~/momin/sleeper/results'
[ -d train ] && rsync -az --delete --exclude __pycache__ --exclude '*.pyc' train/ freighter:momin/sleeper/train/
rsync -az cluster/ freighter:momin/sleeper/cluster/
