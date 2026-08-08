#!/usr/bin/env bash
# Build the PaintOmics application image.
#
#   ./deploy/build-image.sh [extra docker compose build args...]
#
# Packs the application tree into deploy/app.tar first, because the Dockerfile
# copies that single archive rather than the directories. See the comment above
# `COPY deploy/app.tar` in deploy/Dockerfile for why: a directory COPY of
# PaintomicsServer corrupts the image rootfs on the deployment host.
#
# tar also preserves the repository's symlinks natively -- including the cyclic
# src/src -> ../src and src/public_html, which points outside the tree -- so
# they need no special handling.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

ARCHIVE="deploy/app.tar"

for required in PaintomicsServer PaintomicsClient; do
    [ -d "${required}" ] || { echo "missing ${required}/ -- run from a full checkout" >&2; exit 1; }
done

echo "packing ${ARCHIVE}"
rm -f "${ARCHIVE}"

# --exclude runs before archiving, so nothing sensitive or generated is packed.
# serverconf.py in particular holds live credentials and must never be baked
# into an image; the container generates it from the template at start-up.
tar -cf "${ARCHIVE}" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.DS_Store' \
    --exclude='PaintomicsServer/src/conf/serverconf.py' \
    --exclude='PaintomicsServer/src/conf/local_serverconf.py' \
    --exclude='node_modules' \
    PaintomicsServer PaintomicsClient

echo "  $(du -h "${ARCHIVE}" | cut -f1), $(tar -tf "${ARCHIVE}" | wc -l | tr -d ' ') entries"

# Fail loudly if a credential slipped in, rather than shipping it.
if tar -tf "${ARCHIVE}" | grep -qE 'conf/(local_)?serverconf\.py$'; then
    echo "REFUSING TO BUILD: serverconf.py is inside ${ARCHIVE}" >&2
    exit 1
fi

# The symlinks are load-bearing; verify tar kept them as links.
#
# Listed once into a variable rather than piped per link, for two reasons. The
# archive is ~290 MB, so this walked it three times. And `tar ... | grep -q`
# cannot work under the `set -o pipefail` above: grep -q exits at the first
# match, tar takes SIGPIPE on the closed pipe and exits non-zero, and pipefail
# reports the pipeline as failed. A miss is equally fatal, because then grep
# itself exits 1. So the check warned on every build whatever the archive
# contained - it announced all three links missing on a build where all three
# were present and correct, which is the same as having no check at all.
listing="$(tar -tvf "${ARCHIVE}")"
missing=0
for link in PaintomicsServer/src/src \
            PaintomicsServer/src/AdminTools/src \
            PaintomicsServer/src/AdminTools/scripts/src; do
    case "${listing}" in
        *" ${link} -> "*) ;;
        *) echo "  WARNING: ${link} not stored as a symlink" >&2; missing=1 ;;
    esac
done
[ "${missing}" -eq 0 ] && echo "  symlinks preserved"

echo "building image"
docker compose -f deploy/compose.yaml build "$@"

echo "done"
