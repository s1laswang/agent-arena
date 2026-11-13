#!/bin/bash
exec python3 -c 'import sys;from kaggle.cli import main;sys.argv[0]="kaggle";main()' "$@"
