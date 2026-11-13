#!/bin/bash
set -e
ssh freighter "cd ~/momin/sleeper && sbatch cluster/$1"
