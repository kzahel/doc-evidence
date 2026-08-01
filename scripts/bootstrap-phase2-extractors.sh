#!/usr/bin/env sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

uv venv --python 3.12 "$repository_dir/.extractors/docling"
uv pip install \
  --python "$repository_dir/.extractors/docling/bin/python" \
  'docling==2.117.0'

uv venv --python 3.12 "$repository_dir/.extractors/marker"
uv pip install \
  --python "$repository_dir/.extractors/marker/bin/python" \
  'marker-pdf==2.0.0'

echo "Optional extractor environments are ready."
echo "Run: uv run doc-evidence doctor"
