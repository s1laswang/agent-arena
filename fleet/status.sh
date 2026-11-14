#!/bin/zsh
ssh freighter 'squeue -u silas -o "%i %j %T %M %N"; cd ~/momin/fleet/board; for t in */; do echo "== ${t%/} STATUS"; head -15 $t/STATUS.md 2>/dev/null; echo "   idle workers: $(grep -l IDLE $t/outbox/*.md 2>/dev/null | wc -l)"; done'
