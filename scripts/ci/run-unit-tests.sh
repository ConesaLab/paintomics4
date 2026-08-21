#!/usr/bin/env bash
#
# Run every test suite under PaintomicsServer/src/tests with the repository's
# own runner (src/tests/run_all.py), offline.
#
# Offline means: scripts/ci/no_network/sitecustomize.py is first on PYTHONPATH,
# so any suite that tries to reach KEGG, Reactome, PubMed, Europe PMC or the
# LLM gateway fails with a named OSError instead of quietly using the
# network. The AI interpretation path stays ENABLED -- its handler tests
# check the refusals that happen before any model call -- but the gateway is
# a closed loopback port and the key a placeholder: the client constructs,
# nothing answers, and the suites that talk to a model do so through the
# stubs they install themselves. No secret is read or needed.
#
# Suites run several at a time (scripts/ci/run_suites.py) with the
# classification of src/tests/run_all.py; sequential takes ~9.5 minutes.
#
# Usage: scripts/ci/run-unit-tests.sh [run_suites.py arguments]
# Env:   PYTHON (default python3), PAINTOMICS_KEGG_DATA, PAINTOMICS_CLIENT_TMP

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"

export PYTHONPATH="$ROOT/scripts/ci/no_network${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export AI_LLM_PROVIDER=csic
export AI_CSIC_API_BASE=http://127.0.0.1:1/v1
export AI_CSIC_API_KEY=ci-stub-not-a-real-key
export AI_PUBMED_API_KEY=""
export SMTP_PASSWORD=""

[ -n "${PAINTOMICS_KEGG_DATA:-}" ] || { echo "run-unit-tests: PAINTOMICS_KEGG_DATA must be set" >&2; exit 64; }
export PAINTOMICS_CLIENT_TMP="${PAINTOMICS_CLIENT_TMP:-$(mktemp -d)}"
mkdir -p "$PAINTOMICS_CLIENT_TMP"

SERVER="$ROOT/PaintomicsServer"
if [ ! -f "$SERVER/src/conf/serverconf.py" ]; then
    cp "$SERVER/src/resources/example_serverconf.py" "$SERVER/src/conf/serverconf.py"
fi
mkdir -p "$SERVER/src/log"

cd "$SERVER"
exec "$PYTHON" "$ROOT/scripts/ci/run_suites.py" "$@"
