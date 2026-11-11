#!/bin/zsh
cd -- "${0:A:h}"
RUNTIME='/Users/husseinalbassam/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
if [[ -x "$RUNTIME" ]]; then
  "$RUNTIME" team_lan.py
else
  python3 team_lan.py
fi
