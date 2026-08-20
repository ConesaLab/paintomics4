#!/bin/sh
# Runs the client-side JavaScript tests.
#
# Node's --test flag treats a bare directory argument as a module path rather
# than globbing it, so the files are expanded here instead. No dependencies and
# no package.json: the suite uses node:test and node:assert only.
#
#   sh PaintomicsClient/tests/run.sh
cd "$(dirname "$0")/../.." || exit 1
exec node --test PaintomicsClient/tests/*/*.test.js
