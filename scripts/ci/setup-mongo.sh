#!/usr/bin/env bash
#
# Start a throwaway MongoDB for a CI job on a macOS arm64 runner.
#
# The server tarball and the database tools (mongorestore) are downloaded from
# fastdl.mongodb.org into $PAINTOMICS_CI_HOME/mongodb-dist, which the workflow
# caches, so a warm run downloads nothing. mongod listens on 127.0.0.1:27017
# -- the serverconf defaults -- with its data under $PAINTOMICS_CI_HOME/mongo.
#
# Usage: scripts/ci/setup-mongo.sh
# Env:   PAINTOMICS_CI_HOME   (default ~/paintomics-ci)
#        MONGODB_VERSION      (default 8.2.9, the version the baseline ran on)
#        MONGODB_TOOLS_VERSION (default 100.16.1)
#        MONGODB_PORT         (default 27017; serverconf reads the same variable)

set -euo pipefail

CI_HOME="${PAINTOMICS_CI_HOME:-$HOME/paintomics-ci}"
MONGODB_VERSION="${MONGODB_VERSION:-8.2.9}"
MONGODB_TOOLS_VERSION="${MONGODB_TOOLS_VERSION:-100.16.1}"
MONGODB_PORT="${MONGODB_PORT:-27017}"
DIST="$CI_HOME/mongodb-dist"
DBPATH="$CI_HOME/mongo/db"
LOG="$CI_HOME/mongo/mongod.log"

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) ;;
    *) echo "setup-mongo: only macOS arm64 runners are supported (got $(uname -s)-$(uname -m))" >&2; exit 1 ;;
esac

mkdir -p "$DIST" "$DBPATH"

SERVER_TGZ="$DIST/mongodb-macos-arm64-$MONGODB_VERSION.tgz"
TOOLS_ZIP="$DIST/mongodb-database-tools-macos-arm64-$MONGODB_TOOLS_VERSION.zip"

fetch() {
    # -S so a failure says why even though -s keeps the progress meter quiet;
    # --retry for the transient 5xx/connection resets a CDN hands out.
    local url="$1" dest="$2"
    echo "==> downloading $url"
    if ! curl -fsSL --retry 3 --retry-all-errors --retry-delay 2 -o "$dest.part" "$url"; then
        echo "setup-mongo: download failed: $url" >&2
        rm -f "$dest.part"
        exit 1
    fi
    mv "$dest.part" "$dest"
    echo "    $(du -h "$dest" | cut -f1) $(basename "$dest")"
}
[ -s "$SERVER_TGZ" ] || fetch "https://fastdl.mongodb.org/osx/mongodb-macos-arm64-$MONGODB_VERSION.tgz" "$SERVER_TGZ"
[ -s "$TOOLS_ZIP" ] || fetch "https://fastdl.mongodb.org/tools/db/mongodb-database-tools-macos-arm64-$MONGODB_TOOLS_VERSION.zip" "$TOOLS_ZIP"

# The tarball's top-level directory is not the tarball's name (8.2.9 unpacks
# as mongodb-macos-aarch64--8.2.9), so find mongod rather than guess the path.
findServerDir() { ls -d "$DIST"/mongodb-macos-*"$MONGODB_VERSION" 2>/dev/null | head -1 || true; }
SERVER_DIR="$(findServerDir)"
if [ -z "$SERVER_DIR" ] || [ ! -x "$SERVER_DIR/bin/mongod" ]; then
    echo "==> unpacking $(basename "$SERVER_TGZ")"
    tar -xzf "$SERVER_TGZ" -C "$DIST" || { echo "setup-mongo: tar failed on $SERVER_TGZ" >&2; exit 1; }
    SERVER_DIR="$(findServerDir)"
fi
if [ -z "$SERVER_DIR" ] || [ ! -x "$SERVER_DIR/bin/mongod" ]; then
    echo "setup-mongo: mongod not found under $DIST after unpacking $SERVER_TGZ" >&2
    ls -la "$DIST" >&2
    exit 1
fi
TOOLS_DIR="$DIST/mongodb-database-tools-macos-arm64-$MONGODB_TOOLS_VERSION"
if [ ! -x "$TOOLS_DIR/bin/mongorestore" ]; then
    echo "==> unpacking $(basename "$TOOLS_ZIP")"
    unzip -q -o "$TOOLS_ZIP" -d "$DIST" || { echo "setup-mongo: unzip failed on $TOOLS_ZIP" >&2; exit 1; }
fi
[ -x "$TOOLS_DIR/bin/mongorestore" ] || { echo "setup-mongo: mongorestore not found under $TOOLS_DIR" >&2; ls -la "$DIST" >&2; exit 1; }
# macOS quarantines downloaded binaries; strip the attribute or Gatekeeper
# refuses to exec them.
xattr -dr com.apple.quarantine "$SERVER_DIR" "$TOOLS_DIR" 2>/dev/null || true
echo "==> mongod: $SERVER_DIR/bin/mongod"
echo "==> tools:  $TOOLS_DIR/bin"

echo "==> starting mongod $MONGODB_VERSION on 127.0.0.1:$MONGODB_PORT"
# --fork is refused on macOS ("incompatible with macOS" since 8.x), so the
# daemon is detached here instead; it outlives this script for the job.
nohup "$SERVER_DIR/bin/mongod" --dbpath "$DBPATH" --logpath "$LOG" --bind_ip 127.0.0.1 \
    --port "$MONGODB_PORT" >/dev/null 2>&1 < /dev/null &
disown

for _ in $(seq 1 60); do
    if nc -z 127.0.0.1 "$MONGODB_PORT" 2>/dev/null; then
        echo "==> mongod is listening"
        break
    fi
    sleep 1
done
nc -z 127.0.0.1 "$MONGODB_PORT" || { echo "setup-mongo: mongod did not come up; log follows" >&2; tail -50 "$LOG" >&2; exit 1; }

# Put mongorestore/mongodump on the PATH of the following workflow steps.
if [ -n "${GITHUB_PATH:-}" ]; then
    echo "$TOOLS_DIR/bin" >> "$GITHUB_PATH"
    echo "$SERVER_DIR/bin" >> "$GITHUB_PATH"
fi
