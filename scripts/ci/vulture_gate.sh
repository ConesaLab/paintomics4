#!/usr/bin/env bash
#
# Dead-code ratchet, run by the PR lint job.
#
# Two checks, one direction each:
#   1. >=80% confidence: must be ZERO findings beyond the annotated
#      whitelist (scripts/ci/vulture_whitelist.py -- every row carries its
#      reason). A finding here is a hard failure.
#   2. >=60% confidence: this band contains live code vulture cannot see
#      (Flask routes, methods the ExtJS client calls by name), so zero is a
#      lie -- instead NO NEW candidates may appear beyond the committed
#      baseline (scripts/ci/vulture_baseline.txt, line numbers stripped so
#      unrelated edits do not shift it). Candidates disappearing is fine;
#      refresh the baseline in the same commit that removes the code.
#
# Usage: scripts/ci/vulture_gate.sh   (from the repository root)

set -euo pipefail

WHITELIST=scripts/ci/vulture_whitelist.py
BASELINE=scripts/ci/vulture_baseline.txt

echo "== vulture >=80% against the whitelist"
if ! vulture PaintomicsServer/src "$WHITELIST" --min-confidence 80; then
    echo "FAIL: new >=80% candidate. Delete it with evidence (grep the client"
    echo "for string call sites, coverage, git history) or whitelist it WITH"
    echo "a reason in $WHITELIST."
    exit 1
fi
echo "   clean"

echo "== vulture >=60% ratchet against $BASELINE"
current=$(mktemp)
vulture PaintomicsServer/src "$WHITELIST" --min-confidence 60 2>/dev/null \
    | sed -E 's/:[0-9]+:/:/' | sort > "$current" || true

new_lines=$(comm -13 "$BASELINE" "$current")
if [ -n "$new_lines" ]; then
    echo "FAIL: candidates not in the committed baseline:"
    echo "$new_lines"
    echo "Remove the dead code, or -- if it is live code vulture cannot see --"
    echo "add it to the baseline in this same commit and say why in the message."
    rm -f "$current"
    exit 1
fi

gone=$(comm -23 "$BASELINE" "$current" | wc -l | tr -d ' ')
total=$(wc -l < "$current" | tr -d ' ')
rm -f "$current"
echo "   clean: $total candidates, none new ($gone baseline rows no longer fire -- refresh the baseline when convenient)"
