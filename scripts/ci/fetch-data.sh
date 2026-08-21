#!/usr/bin/env bash
#
# Clone the private CI data snapshot with a read-only deploy key.
#
# This is the ONLY CI script that needs a secret, and the only workflow that
# runs it is data-cache.yml, which then stores the checkout in the Actions
# cache. pr.yml and nightly.yml restore from that cache and never see the key.
#
# Why a private repository at all: the snapshot is KEGG-derived (pathway maps,
# KGML, gene lists, cross-references), and KEGG data may not be redistributed,
# so it cannot be a public release asset or live in this repository.
#
# Usage: CI_DATA_DEPLOY_KEY="$(cat key)" scripts/ci/fetch-data.sh <dest-dir>
# Env:   CI_DATA_REPO   (default git@github.com:TianYuan-Liu/paintomics-ci-data.git)

set -euo pipefail

DEST="${1:?usage: fetch-data.sh <dest-dir>}"
REPO="${CI_DATA_REPO:-git@github.com:TianYuan-Liu/paintomics-ci-data.git}"

[ -n "${CI_DATA_DEPLOY_KEY:-}" ] || { echo "fetch-data: CI_DATA_DEPLOY_KEY is not set" >&2; exit 1; }

KEYDIR="$(mktemp -d)"
trap 'rm -rf "$KEYDIR"' EXIT
umask 077
printf '%s\n' "$CI_DATA_DEPLOY_KEY" > "$KEYDIR/key"
chmod 600 "$KEYDIR/key"

export GIT_SSH_COMMAND="ssh -i $KEYDIR/key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
rm -rf "$DEST"
echo "==> cloning the data snapshot"
git clone --quiet --depth 1 "$REPO" "$DEST"
rm -rf "$DEST/.git"

echo "==> verifying checksums"
(cd "$DEST" && shasum -a 256 -c SHA256SUMS)
du -sh "$DEST"
