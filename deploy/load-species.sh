#!/usr/bin/env bash
# Unattended deployment + species load, intended to be run under nohup on the
# server so it survives an SSH disconnect:
#
#   nohup ./deploy/load-species.sh > ~/runner.log 2>&1 &
#
# Stages: wait for image build -> compose up -> smoke test -> hsa -> mmu.
# Each stage stops the chain on failure and names the log to look at.
#
# The KEGG and Reactome downloads are rate-limited and take hours. They are
# restartable: downloaded files are validated and cached, so a re-run skips what
# is already present rather than starting over.
set -uo pipefail

REPO="${REPO:-$HOME/paintomics4}"
COMPOSE="sudo docker compose -f ${REPO}/deploy/compose.yaml"
LOG="${LOG:-$HOME/stage.log}"
BUILD_LOG="${BUILD_LOG:-$HOME/build.log}"

cd "${REPO}" || exit 1

say() { printf '\n===== [%s] %s =====\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "${LOG}"; }
die() { printf '\nFAILED: %s\n' "$*" | tee -a "${LOG}"; exit 1; }

# ---------------------------------------------------------------------------
# Wait for the image build, if one is in flight.
# ---------------------------------------------------------------------------
if [ -f "${BUILD_LOG}" ]; then
    say "waiting for image build"
    # BuildKit writes progress as "#13 ERROR: ..." -- mid-line, so an ^ERROR
    # anchor never matches and the wait spins forever on a failed build.
    until grep -qE "naming to|ERROR:|failed to solve" "${BUILD_LOG}" 2>/dev/null; do
        sleep 20
    done
    if grep -qE "ERROR:|failed to solve" "${BUILD_LOG}"; then
        die "image build failed; see ${BUILD_LOG}"
    fi
    say "build complete"
fi

# ---------------------------------------------------------------------------
# Preflight: Docker MTU must not exceed the host interface MTU.
# ---------------------------------------------------------------------------
# On OpenStack the VXLAN overlay gives the host a 1450 MTU while Docker defaults
# its bridges to 1500. Oversized packets are dropped with path-MTU discovery
# blackholed, so small HTTP responses succeed and large transfers hang. That
# would strand the multi-hour KEGG and Reactome downloads with no clear cause,
# so fail here instead.
HOST_MTU=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'dev \K\S+' \
           | head -1 | xargs -r -I{} ip link show {} 2>/dev/null \
           | grep -oP 'mtu \K[0-9]+' | head -1)
DOCKER_MTU=$(ip link show docker0 2>/dev/null | grep -oP 'mtu \K[0-9]+' | head -1)
if [ -n "${HOST_MTU}" ] && [ -n "${DOCKER_MTU}" ] && [ "${DOCKER_MTU}" -gt "${HOST_MTU}" ]; then
    die "docker0 MTU ${DOCKER_MTU} exceeds host MTU ${HOST_MTU}. Large downloads will hang.
Set /etc/docker/daemon.json to {\"mtu\": ${HOST_MTU}} and restart docker."
fi
say "MTU preflight ok (host ${HOST_MTU:-?}, docker ${DOCKER_MTU:-?})"

# ---------------------------------------------------------------------------
say "starting stack"
# ---------------------------------------------------------------------------
${COMPOSE} up -d >>"${LOG}" 2>&1 || die "compose up"
sleep 40
${COMPOSE} ps >>"${LOG}" 2>&1

say "smoke test"
sudo "${REPO}/deploy/smoke-test.sh" >>"${LOG}" 2>&1
SMOKE=$?
echo "smoke exit=${SMOKE}" >>"${LOG}"
[ ${SMOKE} -eq 0 ] || say "smoke test reported failures (continuing; see ${LOG})"

# Verify the container itself can pull a large payload, now that it is running.
say "container egress check"
${COMPOSE} exec -T app python -c "
import urllib.request
data = urllib.request.urlopen('https://rest.kegg.jp/list/pathway', timeout=60).read()
assert len(data) > 10000, 'short read: %d bytes' % len(data)
print('KEGG reachable from the container, %d bytes' % len(data))
" >>"${LOG}" 2>&1 || die "container cannot reach KEGG; check MTU and egress"

DBM="python /app/PaintomicsServer/src/AdminTools/DBManager.py"

# ---------------------------------------------------------------------------
# Every step below is skipped when its work is already done, because this
# script gets re-run repeatedly while debugging a later stage and each redundant
# download costs hours.
#
# The completion markers are subtle, and getting them wrong has cost real time:
#
#   * download/<specie>/VERSION marks a finished download -- but a successful
#     install MOVES that directory into current/, so its absence does not mean
#     the download is missing. current/<specie>/VERSION must be checked too, or
#     a rerun re-downloads a species that is already installed.
#   * current/common/pathways_classification.list appears as soon as the common
#     data is moved, which is well before createGlobalDatabase() registers the
#     COMMON version document. Gate on the document, not the file.
#   * MongoDB is the authority on whether a species is installed. The filesystem
#     only says what was downloaded.
# ---------------------------------------------------------------------------

mongoQuery() {
    ${COMPOSE} exec -T app python -c "$1" 2>/dev/null | tr -d '\r\n '
}

speciesInstalled() {
    [ "$(mongoQuery "
from pymongo import MongoClient
try:
    c = MongoClient('mongo', 27017, serverSelectionTimeoutMS=8000)
    print(c['$1-paintomics'].kegg.count_documents({}))
except Exception:
    print(0)
")" -gt 0 ] 2>/dev/null
}

commonRegistered() {
    [ "$(mongoQuery "
from pymongo import MongoClient
try:
    c = MongoClient('mongo', 27017, serverSelectionTimeoutMS=8000)
    print('yes' if c['global-paintomics'].versions.find_one({'name': 'COMMON'}) else 'no')
except Exception:
    print('no')
")" = "yes" ]
}

downloadIfNeeded() {
    specie="$1"; shift
    if ${COMPOSE} exec -T app test -f "/data/KEGG_DATA/download/${specie}/VERSION" 2>/dev/null; then
        say "DOWNLOAD ${specie} already complete - skipping"
        return 0
    fi
    if ${COMPOSE} exec -T app test -f "/data/KEGG_DATA/current/${specie}/VERSION" 2>/dev/null; then
        say "DOWNLOAD ${specie} already installed into current/ - skipping"
        return 0
    fi
    say "DOWNLOAD ${specie} (KEGG + Reactome) - hours"
    ${COMPOSE} exec -T app ${DBM} download --specie="${specie}" "$@" \
        >"$HOME/${specie}-download.log" 2>&1 \
        || die "${specie} download (see ~/${specie}-download.log)"
}

# Register the shared KEGG data in global-paintomics if that has not happened.
#
# Done directly rather than through `install --common=1` because that flag also
# reinstalls a species, and it *moves* download/common, so it cannot be re-run
# once the move has succeeded. installCommonData() is just a call to
# processKEGGCommonData(), so invoking it against current/common achieves the
# registration on its own.
ensureCommonRegistered() {
    if commonRegistered; then
        say "COMMON already registered in global-paintomics - skipping"
        return 0
    fi
    say "REGISTER common KEGG data in global-paintomics"
    ${COMPOSE} exec -T app python -c "
import sys
sys.path.insert(0, '/app/PaintomicsServer/src')
sys.path.insert(0, '/app/PaintomicsServer/src/AdminTools')
import imp
tools = imp.load_source('common_build_database',
                        '/app/PaintomicsServer/src/AdminTools/scripts/common_build_database.py')
tools.processKEGGCommonData('/data/KEGG_DATA/current/common/',
                            '/app/PaintomicsServer/src/')
print('common data registered')
" >"$HOME/common-install.log" 2>&1 || die "common registration (see ~/common-install.log)"

    commonRegistered || die "common registration ran but COMMON is still absent"
    say "COMMON registered"
}

installIfNeeded() {
    specie="$1"; shift
    if speciesInstalled "${specie}"; then
        say "INSTALL ${specie} already present in MongoDB - skipping"
        return 0
    fi
    say "INSTALL ${specie}"
    ${COMPOSE} exec -T app ${DBM} install --specie="${specie}" --common=0 \
        >"$HOME/${specie}-install.log" 2>&1 \
        || die "${specie} install (see ~/${specie}-install.log)"
    speciesInstalled "${specie}" || die "${specie} install reported success but MongoDB has no pathways"
}

downloadIfNeeded hsa --kegg=1 --mapping=1 --common=1 --reactome=1
ensureCommonRegistered
installIfNeeded hsa

# --common=0 throughout: the shared data is registered once, above.
downloadIfNeeded mmu --kegg=1 --mapping=1 --common=0 --reactome=1
installIfNeeded mmu

# ---------------------------------------------------------------------------
say "VERIFY enrichment (both species, Reactome required)"
# ---------------------------------------------------------------------------
for specie in hsa mmu; do
    ${COMPOSE} exec -T -w /app/PaintomicsServer app \
        python -m src.tests.test_enrichment_e2e --specie "${specie}" --require-reactome \
        >>"${LOG}" 2>&1 || say "enrichment verification FAILED for ${specie}"
done

say "ALL STAGES COMPLETE"
