#!/usr/bin/env bash
#
# Unpack the CI data snapshot into the places the server reads from.
#
#   MongoDB         mmu-paintomics + global-paintomics, restored only if absent
#   KEGG_DATA       the runtime subset of current/, untarred into
#                   $PAINTOMICS_KEGG_DATA
#   example GTF     PaintomicsServer/src/examplefiles/GTF/sorted_mmu.gtf, which
#                   the region->gene datasets need and the repository does not
#                   carry
#
# The snapshot directory is the checkout of the private data repository that
# scripts/ci/fetch-data.sh makes and the workflows cache; see its README for
# what each file is. Every file is checksummed before use.
#
# Usage: scripts/ci/restore-data.sh <snapshot-dir>
# Env:   PAINTOMICS_CI_HOME     (default ~/paintomics-ci)
#        PAINTOMICS_KEGG_DATA   (default $PAINTOMICS_CI_HOME/KEGG_DATA)

set -euo pipefail

SNAPSHOT="${1:?usage: restore-data.sh <snapshot-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CI_HOME="${PAINTOMICS_CI_HOME:-$HOME/paintomics-ci}"
KEGG_DATA="${PAINTOMICS_KEGG_DATA:-$CI_HOME/KEGG_DATA}"
GTF="$ROOT/PaintomicsServer/src/examplefiles/GTF/sorted_mmu.gtf"
MONGODB_HOST="${MONGODB_HOST:-localhost}"
MONGODB_PORT="${MONGODB_PORT:-27017}"
PYTHON="${PYTHON:-python3}"

[ -f "$SNAPSHOT/SHA256SUMS" ] || { echo "restore-data: $SNAPSHOT has no SHA256SUMS; is the data cache populated?" >&2; exit 1; }
echo "==> verifying checksums"
(cd "$SNAPSHOT" && shasum -a 256 -c SHA256SUMS)

hasDatabase() {
    "$PYTHON" - "$1" "$MONGODB_HOST" "$MONGODB_PORT" <<'EOF'
import sys
from pymongo import MongoClient
client = MongoClient(sys.argv[2], int(sys.argv[3]), serverSelectionTimeoutMS=10000)
sys.exit(0 if client[sys.argv[1]].list_collection_names() else 1)
EOF
}

for database in mmu-paintomics global-paintomics; do
    if hasDatabase "$database"; then
        echo "==> $database already present"
    else
        echo "==> restoring $database"
        mongorestore --quiet --host "$MONGODB_HOST" --port "$MONGODB_PORT" \
            --archive="$SNAPSHOT/$database.archive.gz" --gzip
    fi
done

if [ -f "$KEGG_DATA/current/mmu/VERSION" ]; then
    echo "==> KEGG_DATA already unpacked at $KEGG_DATA"
else
    echo "==> unpacking KEGG_DATA into $KEGG_DATA"
    mkdir -p "$KEGG_DATA"
    cat "$SNAPSHOT"/kegg-data-mmu-runtime.tar.gz.part-* | tar -xzf - -C "$KEGG_DATA"
fi

if [ -s "$GTF" ]; then
    echo "==> example GTF already present"
else
    echo "==> installing the example GTF"
    gunzip -c "$SNAPSHOT/sorted_mmu.gtf.gz" > "$GTF"
fi

mkdir -p "$CI_HOME/CLIENT_TMP"
if [ -n "${GITHUB_ENV:-}" ]; then
    {
        echo "PAINTOMICS_KEGG_DATA=$KEGG_DATA"
        echo "PAINTOMICS_CLIENT_TMP=$CI_HOME/CLIENT_TMP"
    } >> "$GITHUB_ENV"
fi
echo "==> data ready: KEGG_DATA=$KEGG_DATA"
