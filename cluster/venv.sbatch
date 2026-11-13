#!/bin/bash
#SBATCH --partition=normal
#SBATCH --time=00:15:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --job-name=sleeper-venv
#SBATCH --output=logs/%x-%j.out
cd $HOME/momin/sleeper
python3 -m venv venv
venv/bin/pip install -q -r requirements.txt
venv/bin/python -c "import pydantic, mcp; print('ok', pydantic.VERSION)"
