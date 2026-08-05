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
say "DOWNLOAD hsa (KEGG + Reactome) - hours"
# ---------------------------------------------------------------------------
${COMPOSE} exec -T app ${DBM} download \
    --specie=hsa --kegg=1 --mapping=1 --common=1 --reactome=1 \
    >"$HOME/hsa-download.log" 2>&1 || die "hsa download (see ~/hsa-download.log)"

say "INSTALL hsa"
${COMPOSE} exec -T app ${DBM} install --specie=hsa \
    >"$HOME/hsa-install.log" 2>&1 || die "hsa install (see ~/hsa-install.log)"

# ---------------------------------------------------------------------------
# --common=0: the shared KEGG reference data is already present from hsa and is
# by far the slowest part of the download.
say "DOWNLOAD mmu (KEGG + Reactome, reusing common)"
# ---------------------------------------------------------------------------
${COMPOSE} exec -T app ${DBM} download \
    --specie=mmu --kegg=1 --mapping=1 --common=0 --reactome=1 \
    >"$HOME/mmu-download.log" 2>&1 || die "mmu download (see ~/mmu-download.log)"

say "INSTALL mmu"
${COMPOSE} exec -T app ${DBM} install --specie=mmu \
    >"$HOME/mmu-install.log" 2>&1 || die "mmu install (see ~/mmu-install.log)"

# ---------------------------------------------------------------------------
say "VERIFY enrichment (both species, Reactome required)"
# ---------------------------------------------------------------------------
for specie in hsa mmu; do
    ${COMPOSE} exec -T -w /app/PaintomicsServer app \
        python -m src.tests.test_enrichment_e2e --specie "${specie}" --require-reactome \
        >>"${LOG}" 2>&1 || say "enrichment verification FAILED for ${specie}"
done

say "ALL STAGES COMPLETE"
