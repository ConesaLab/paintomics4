#!/usr/bin/env bash
#
# Profile and time the large input: py-spy recordings and un-profiled wall
# clocks, every run cold (a fresh interpreter; see perf_run.py).
#
#   runs 1..N   python scripts/perf/perf_run.py        -> timings/run-N.json
#   runs 1..N   py-spy record -- perf_run.py            -> profiles/run-N.raw
#               (sampling at RATE Hz, child processes included: the mapper
#               workers are forked)
#
# then writes <out>/profile.txt: the top functions by cumulative time from
# the profiles (scripts/perf/topfuncs.py), the per-run wall clocks and their
# median, and the environment. py-spy needs root on macOS, so it is run
# through sudo when not already root -- the GitHub runners allow that
# without a password; a laptop will not, which is why this runs in CI.
#
# Usage: scripts/perf/profile.sh <out-dir> [runs=3] [rate=200]
# Env:   PYTHON, PAINTOMICS_KEGG_DATA, PAINTOMICS_CLIENT_TMP, PYTHONHASHSEED

set -euo pipefail

OUT="${1:?usage: profile.sh <out-dir> [runs] [rate]}"
RUNS="${2:-3}"
RATE="${3:-200}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"

mkdir -p "$OUT/timings" "$OUT/profiles"
cd "$ROOT"

SUDO=""
if [ "$(id -u)" != "0" ]; then
    SUDO="sudo -E env PATH=$PATH"
fi
PYSPY="$(command -v py-spy || true)"
[ -n "$PYSPY" ] || { echo "profile: py-spy is not on PATH (pip install py-spy)" >&2; exit 1; }

echo "==> timing runs"
for i in $(seq 1 "$RUNS"); do
    "$PYTHON" scripts/perf/perf_run.py --out "$OUT/timings/run-$i.json" > /dev/null
    echo "    run $i: $("$PYTHON" -c "import json;print(json.load(open('$OUT/timings/run-$i.json'))['total'])") s"
done

echo "==> profiled runs (py-spy, ${RATE} Hz, subprocesses included)"
for i in $(seq 1 "$RUNS"); do
    $SUDO "$PYSPY" record --rate "$RATE" --subprocesses --format raw \
        --output "$OUT/profiles/run-$i.raw" -- \
        "$PYTHON" scripts/perf/perf_run.py --out "$OUT/profiles/run-$i.json" > "$OUT/profiles/run-$i.log" 2>&1 \
        || { echo "profile: py-spy failed on run $i; log follows" >&2; tail -20 "$OUT/profiles/run-$i.log" >&2; exit 1; }
    # sudo leaves the output owned by root
    $SUDO chown "$(id -u)" "$OUT/profiles/run-$i.raw" 2>/dev/null || true
    echo "    run $i: $(wc -l < "$OUT/profiles/run-$i.raw") stacks"
done

"$PYTHON" scripts/perf/report.py "$OUT" --runs "$RUNS" --rate "$RATE" > "$OUT/profile.txt"
cat "$OUT/profile.txt"
