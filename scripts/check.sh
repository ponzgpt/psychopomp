#!/usr/bin/env bash
# The one check: core tests, Python syntax, Desktop half parses as ESM, and Hermes' own validator when present.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m unittest discover -s tests
python3 -m py_compile __init__.py psychopomp_core.py psychopomp_store.py dashboard/plugin_api.py

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cp desktop/plugin.js "$tmp/plugin.mjs" && node --check "$tmp/plugin.mjs"
python3 - <<'EOF'
import re, sys
bad = [m for m in re.findall(r"""from\s+['"]([^'"]+)['"]""", open("desktop/plugin.js").read())
       if m not in ("@hermes/plugin-sdk", "react", "react/jsx-runtime")]
sys.exit(f"desktop/plugin.js may only import the SDK and react: {bad}" if bad else 0)
EOF

if command -v hermes >/dev/null && hermes plugins validate --help >/dev/null 2>&1; then
  hermes plugins validate . --install-deps
else
  echo "(hermes not installed here: skipped 'hermes plugins validate')"
fi
echo "check: ok"
