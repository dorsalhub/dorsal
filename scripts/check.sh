#!/bin/sh
# exit immediately if any command fails.
set -e

FAST=false
COV=false

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    fast) FAST=true ;;
    cov)  COV=true ;;
    *)
      echo "Error: Unknown argument '$arg'" >&2
      echo "Usage: $0 [fast] [cov]" >&2
      exit 1
      ;;
  esac
done

if [ "$FAST" = true ]; then
  PYTHON_VERSIONS="3.14"
else
  PYTHON_VERSIONS="3.11 3.12 3.13 3.14"
fi

PYTEST_ARGS=""
if [ "$COV" = true ]; then
  PYTEST_ARGS="--cov=src/dorsal --cov-report=term-missing"
fi

echo "--- formatting with ruff ---"
uv run --python=3.14 --group dev -- ruff format src/dorsal tests

echo "--- linting with ruff ---"
uv run --python=3.14 --group dev -- ruff check src/dorsal tests

echo "--- type checking with mypy ---"
uv run --python=3.14 --group dev -- mypy src/dorsal

for version in $PYTHON_VERSIONS; do
  echo ""
  echo "--- running tests with pytest on Python $version ---"
  uv run --python="$version" pytest $PYTEST_ARGS
done

echo ""
echo "--- all checks passed! ---"