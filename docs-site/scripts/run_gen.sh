#!/usr/bin/env bash
# Wrapper that runs gen_reference.py with the *right* Python.
#
# Order of preference:
#   1. ../.venv/bin/python                 — local dev (has mnexus deps installed)
#   2. python3 (with mnexus deps importable)
#   3. python3 (without mnexus — gen still runs, falls back to existing
#              reference files where import fails)
#
# We never `pip install` here; build environments handle that elsewhere.
# The point is to maximise the chance the regenerated reference is fresh
# without breaking the docs build when it isn't.

set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

# Prefer the project venv if it exists — that's where `pip install -e .`
# put pydantic, click, fastapi, etc.
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "✕ no python interpreter found; skipping reference regen" >&2
  exit 0
fi

echo "→ using $PY for reference gen"
exec "$PY" "$HERE/gen_reference.py"
