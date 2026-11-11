#!/bin/zsh
cd -- "${0:A:h}"
RUNTIME='/Users/husseinalbassam/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
if [[ -x "$RUNTIME" ]]; then
  "$RUNTIME" server.py
else
  python3 server.py
fi
