#!/usr/bin/env bash
# Wait for an in-flight species download to finish, move onto a rebuilt image,
# then run the install.
#
#   nohup ./deploy/swap-and-install.sh > ~/swap-runner.log 2>&1 &
#
# Why this exists: the download runs through `docker compose exec app`, so
# recreating the app container to pick up a new image would kill it partway
# through. With --common=1 that is expensive to redo, because DBManager
# shutil.rmtree()s both the common and species directories before starting.
#
# VERSION is DBManager's own completion marker, written as the final step of a
# successful download, so it is the correct thing to gate on.
set -uo pipefail

REPO="${REPO:-$HOME/paintomics4}"
COMPOSE="sudo docker compose -f ${REPO}/deploy/compose.yaml"
LOG="${LOG:-$HOME/swap.log}"
SPECIE="${SPECIE:-hsa}"

cd "${REPO}" || exit 1

say() { printf '\n===== [%s] %s =====\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "${LOG}"; }

downloadComplete() {
    ${COMPOSE} exec -T app test -f "/data/KEGG_DATA/download/${SPECIE}/VERSION" 2>/dev/null
}

say "waiting for the ${SPECIE} download to write VERSION"
while ! downloadComplete; do
    # If the runner is gone and VERSION never appeared, the download failed --
    # stop rather than waiting forever.
    if ! pgrep -f 'bash ./deploy/load-species.sh' >/dev/null 2>&1; then
        sleep 10
        if ! downloadComplete; then
            say "runner exited before VERSION appeared; download did not complete"
            exit 1
        fi
    fi
    sleep 30
done
say "download complete"

say "stopping the old runner"
pkill -f 'bash ./deploy/load-species.sh' 2>/dev/null
sleep 5

say "recreating app on the rebuilt image"
${COMPOSE} up -d app >>"${LOG}" 2>&1 || { say "compose up failed"; exit 1; }
sleep 30

# The whole point of the swap. If this fails the new image is not what we think
# it is, and running the install would just reproduce the same failure.
say "confirming tidyverse loads in the running container"
if ! ${COMPOSE} exec -T app Rscript -e 'library(tidyverse); cat("tidyverse OK\n")' >>"${LOG}" 2>&1; then
    say "tidyverse still does not load - aborting before the install"
    exit 1
fi

say "relaunching load-species (the completed download will be skipped)"
rm -f "$HOME/stage.log"
exec ./deploy/load-species.sh
