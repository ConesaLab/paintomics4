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

# The Rust MORE port ships as a platform-specific binary beside runMORE.R, and
# it is gitignored so each deployment drops in the build it needs. Two ways that
# goes wrong without a word:
#
#   * a developer's macOS build (Mach-O arm64) gets packed into a Linux image,
#     where it fails at exec. _resolveMOREBackend then falls back to R for every
#     PLS1 job, which on a host with no MORE package means the analysis simply
#     stops working -- and the only symptom is that it got slower, or dead.
#   * `git archive` DROPS this file because it is gitignored, while the tar
#     above packs it from the working tree. The two delivery paths therefore
#     disagree about whether the binary is even present.
#
# Absent is a legitimate state -- it means every job goes to R, exactly as
# before the port existed -- so absence is reported, not punished. Present but
# built for the wrong machine is never legitimate.
MORE_RS="PaintomicsServer/src/common/bioscripts/more-rs"
if [ -e "${MORE_RS}" ]; then
    # Read the ELF header directly rather than shelling out to `file`, which is
    # not guaranteed on a build host. Bytes 0-3 are the magic, byte 4 is
    # EI_CLASS (02 = 64-bit) and bytes 18-19 are e_machine, little-endian:
    # 0x3e = x86-64, 0xb7 = aarch64.
    header="$(od -An -tx1 -N19 "${MORE_RS}" | tr -d ' \n')"
    # Match the image docker will actually build, so an arm64 laptop building
    # for itself is fine and only a genuine mismatch fails.
    case "$(docker version --format '{{.Server.Arch}}' 2>/dev/null)" in
        arm64|aarch64) want_machine="b7"; want_name="arm64" ;;
        *)             want_machine="3e"; want_name="amd64" ;;
    esac
    case "${header}" in
        7f454c4602*"${want_machine}")
            echo "  more-rs: ELF 64-bit ${want_name}, matches the image" ;;
        7f454c46*)
            echo "REFUSING TO BUILD: ${MORE_RS} is an ELF binary for the wrong" >&2
            echo "  architecture -- the image is ${want_name}. Header: ${header}" >&2
            exit 1 ;;
        *)
            echo "REFUSING TO BUILD: ${MORE_RS} is not a Linux ELF binary." >&2
            echo "  Header: ${header} (a macOS Mach-O build starts cffaedfe)" >&2
            echo "  Cross-build one with:" >&2
            echo "    cargo build --release --target x86_64-unknown-linux-musl" >&2
            exit 1 ;;
    esac
else
    echo "  more-rs: absent -- every MORE job will run on R"
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
