#!/bin/zsh
ssh freighter 'touch ~/momin/fleet/STOP; scancel -u silas -n fleet-afterquery,fleet-gemini,fleet-valio,fleet-meta; squeue -u silas -o "%i %j %T"'
