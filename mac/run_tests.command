#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m unittest discover -s tests -v
else
  python3 -m unittest discover -s tests -v
fi
