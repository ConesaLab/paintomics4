#!/usr/bin/env bash
#
# A/B profile: the same measurements as profile.sh, for two checkouts of the
# repository on the same machine, interleaved -- before, after, before, after
# -- so that whatever speed the host happens to have applies to both sides
# alike. Two separate CI runs of profile.sh landed on VMs 30% apart in every
# phase, including phases nothing had touched; only a paired comparison can
# say what a change did.
#
# Writes <out>/before and <out>/after, each in profile.sh's layout
# (timings/run-N.json, profiles/run-N.raw, profile.txt), and <out>/compare.txt
# from scripts/perf/compare.py.
#
# Usage: scripts/perf/ab.sh <before-checkout> <after-checkout> <out-dir> [runs=3] [rate=200]
# Env:   PYTHON, PAINTOMICS_KEGG_DATA, PAINTOMICS_CLIENT_TMP, PYTHONHASHSEED
#
# Both checkouts need PaintomicsServer/src/conf/serverconf.py (copied from the
# template when missing) and scripts/perf/perf_run.py.

set -euo pipefail

BEFORE="${1:?usage: ab.sh <before-checkout> <after-checkout> <out-dir> [runs] [rate]}"
AFTER="${2:?}"
OUT="${3:?}"
RUNS="${4:-3}"
RATE="${5:-200}"
PYTHON="${PYTHON:-python3}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SUDO=""
if [ "$(id -u)" != "0" ]; then
    SUDO="sudo -E env PATH=$PATH"
fi
PYSPY="$(command -v py-spy || true)"
[ -n "$PYSPY" ] || { echo "ab: py-spy is not on PATH" >&2; exit 1; }

for side in before after; do
    checkout="$BEFORE"; [ "$side" = after ] && checkout="$AFTER"
    server="$checkout/PaintomicsServer"
    [ -f "$checkout/scripts/perf/perf_run.py" ] || { echo "ab: $checkout has no scripts/perf/perf_run.py" >&2; exit 1; }
    [ -f "$server/src/conf/serverconf.py" ] || cp "$server/src/resources/example_serverconf.py" "$server/src/conf/serverconf.py"
    mkdir -p "$server/src/log" "$OUT/$side/timings" "$OUT/$side/profiles"
    echo "==> $side: $(git -C "$checkout" rev-parse --short HEAD) $(git -C "$checkout" log -1 --format=%s | cut -c1-60)"
done

echo "==> timing runs, interleaved"
for i in $(seq 1 "$RUNS"); do
    for side in before after; do
        checkout="$BEFORE"; [ "$side" = after ] && checkout="$AFTER"
        (cd "$checkout" && "$PYTHON" scripts/perf/perf_run.py --out "$OUT/$side/timings/run-$i.json" > /dev/null)
        echo "    run $i $side: $("$PYTHON" -c "import json;print(json.load(open('$OUT/$side/timings/run-$i.json'))['total'])") s"
    done
done

echo "==> profiled runs, interleaved (py-spy, ${RATE} Hz, subprocesses included)"
for i in $(seq 1 "$RUNS"); do
    for side in before after; do
        checkout="$BEFORE"; [ "$side" = after ] && checkout="$AFTER"
        (cd "$checkout" && $SUDO "$PYSPY" record --rate "$RATE" --subprocesses --format raw \
            --output "$OUT/$side/profiles/run-$i.raw" -- \
            "$PYTHON" scripts/perf/perf_run.py --out "$OUT/$side/profiles/run-$i.json" > "$OUT/$side/profiles/run-$i.log" 2>&1) \
            || { echo "ab: py-spy failed ($side, run $i); log follows" >&2; tail -20 "$OUT/$side/profiles/run-$i.log" >&2; exit 1; }
        $SUDO chown "$(id -u)" "$OUT/$side/profiles/run-$i.raw" 2>/dev/null || true
        echo "    run $i $side: $(wc -l < "$OUT/$side/profiles/run-$i.raw") stacks"
    done
done

for side in before after; do
    "$PYTHON" "$HERE/report.py" "$OUT/$side" --runs "$RUNS" --rate "$RATE" > "$OUT/$side/profile.txt"
done
"$PYTHON" "$HERE/compare.py" "$OUT/before" "$OUT/after" --runs "$RUNS" --rate "$RATE" > "$OUT/compare.txt"
cat "$OUT/compare.txt"
