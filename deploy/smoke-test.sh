#!/usr/bin/env bash
# Post-deployment smoke test.
#
#   ./deploy/smoke-test.sh [compose-file]
#
# Checks the things that are cheap to verify and expensive to discover in
# production. Exits non-zero on the first hard failure.
#
# It deliberately does NOT check that pathway data is installed -- a fresh
# deployment legitimately has none. Run it after `up -d`, before loading data.
set -uo pipefail

COMPOSE_FILE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/compose.yaml}"
COMPOSE=(docker compose -f "${COMPOSE_FILE}")

PASS=0
FAIL=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
note() { printf '  \033[33mNOTE\033[0m  %s\n' "$1"; }

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
section "Containers"
# ---------------------------------------------------------------------------
for service in mongo app nginx; do
    state=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
            | awk -v s="${service}" '$1==s {print $2}')
    if [ "${state}" = "running" ]; then
        ok "${service} is running"
    else
        bad "${service} is '${state:-absent}', expected running"
    fi
done

# ---------------------------------------------------------------------------
section "Python runtime"
# ---------------------------------------------------------------------------
if "${COMPOSE[@]}" exec -T app python -c "
import flask, pymongo, numpy, pandas, scipy, statsmodels, cairosvg, PIL, requests, agents
assert pymongo.version.split('.')[0] == '4', 'pymongo must be 4.x, got ' + pymongo.version
print('ok')
" >/dev/null 2>&1; then
    ok "all Python imports resolve, pymongo is 4.x"
else
    bad "Python imports failed:"
    "${COMPOSE[@]}" exec -T app python -c "
import flask, pymongo, numpy, pandas, scipy, statsmodels, cairosvg, PIL, requests, agents" 2>&1 | tail -5
fi

# ---------------------------------------------------------------------------
section "R runtime"
# ---------------------------------------------------------------------------
# These are on the user-facing request path: generateMetaGenes.R and
# hubAnalysis.R run when a user asks for Metagenes or Hub Analysis. Missing
# packages here produce a server that works until someone clicks the button.
if "${COMPOSE[@]}" exec -T app Rscript -e '
pkgs <- c("purrr", "cluster", "mclust", "amap", "factoextra", "igraph",
          "ggplot2", "jsonlite", "stringr", "dplyr")
missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) { cat("MISSING:", paste(missing, collapse=", "), "\n"); quit(status=1) }
cat("ok\n")' >/dev/null 2>&1; then
    ok "all R packages import (Metagenes and Hub Analysis paths)"
else
    bad "R packages missing:"
    "${COMPOSE[@]}" exec -T app Rscript -e '
pkgs <- c("purrr","cluster","mclust","amap","factoextra","igraph","ggplot2",
          "jsonlite","stringr","dplyr")
missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]
cat("MISSING:", paste(missing, collapse=", "), "\n")' 2>&1 | tail -3
fi

# ---------------------------------------------------------------------------
section "Database"
# ---------------------------------------------------------------------------
if "${COMPOSE[@]}" exec -T app python -c "
from pymongo import MongoClient
import os
c = MongoClient(os.getenv('MONGODB_HOST','mongo'), int(os.getenv('MONGODB_PORT','27017')),
                serverSelectionTimeoutMS=5000)
c.admin.command('ping')
print('ok')" >/dev/null 2>&1; then
    ok "app reaches MongoDB"
else
    bad "app cannot reach MongoDB"
fi

# MongoDB must not be published to the host.
if docker compose -f "${COMPOSE_FILE}" ps --format '{{.Service}} {{.Ports}}' 2>/dev/null \
        | awk '$1=="mongo"' | grep -q '27017->'; then
    bad "MongoDB is published to the host — it has no authentication configured"
else
    ok "MongoDB is not published to the host"
fi

# ---------------------------------------------------------------------------
section "HTTP"
# ---------------------------------------------------------------------------
if curl -fsS -o /dev/null http://localhost/healthz 2>/dev/null; then
    ok "nginx answers on port 80"
else
    bad "nginx does not answer on port 80"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null)
if [ "${code}" = "301" ] || [ "${code}" = "302" ]; then
    ok "HTTP redirects to HTTPS (${code})"
else
    bad "expected a redirect on port 80, got ${code}"
fi

# -k because the certificate is self-signed until a real one is installed.
if curl -fsSk -o /dev/null https://localhost/ 2>/dev/null; then
    ok "application responds over HTTPS"
else
    bad "application does not respond over HTTPS"
fi

# ---------------------------------------------------------------------------
section "Configuration"
# ---------------------------------------------------------------------------
if "${COMPOSE[@]}" exec -T app python -c "
import sys; sys.path.insert(0, '/app/PaintomicsServer')
from src.conf.serverconf import SERVER_ALLOW_DEBUG, PAINTOMICS_BASE_URL
assert SERVER_ALLOW_DEBUG is False, 'debug mode is enabled'
assert 'localhost' not in PAINTOMICS_BASE_URL, 'BASE_URL is localhost: activation emails will break'
print('ok')" >/dev/null 2>&1; then
    ok "debug is off and PAINTOMICS_BASE_URL is externally valid"
else
    note "config check failed — debug may be on, or PAINTOMICS_BASE_URL points at localhost"
    note "(expected on a local test deployment; must not be true on Drago)"
fi

# uWSGI must run exactly one process; see deploy/README.md.
workers=$("${COMPOSE[@]}" exec -T app sh -c \
    "grep -E '^processes' /app/uwsgi.ini | tr -d ' ' | cut -d= -f2" 2>/dev/null | tr -d '\r')
if [ "${workers}" = "1" ]; then
    ok "uWSGI runs a single process (required by the in-process job queue)"
else
    bad "uWSGI processes = '${workers}', must be 1 or jobs are silently lost"
fi

# ---------------------------------------------------------------------------
section "Bundled example data"
# ---------------------------------------------------------------------------
# Same reasoning as the R packages above: a server that works until someone
# clicks the button. Bed2GenesServlet hardcodes this path for its example, so
# without the file "Load example" then "Run Regions2Genes" fails with
#     Reference file not found. Looked for '...' and '...'
# and nothing else is affected -- which is exactly why it survives a release
# unnoticed. fetch-example-gtf.sh builds it, and that script is referenced only
# from deploy/README.md; no automated step runs it.
#
# A note rather than a failure, on the same principle as the header: this is
# data, and a deployment that has not loaded data yet is legitimate.
gtf="/app/PaintomicsServer/src/examplefiles/GTF/sorted_mmu.gtf"
gtfsize=$("${COMPOSE[@]}" exec -T app sh -c \
    "wc -c < '${gtf}' 2>/dev/null || echo 0" 2>/dev/null | tr -d '\r[:space:]')
if [ "${gtfsize:-0}" -gt 1000000 ]; then
    ok "Regions2Genes example annotations present ($((gtfsize / 1048576)) MB)"
else
    note "Regions2Genes example GTF missing or truncated (${gtfsize:-0} bytes)"
    note "run deploy/fetch-example-gtf.sh, or that example fails for every user"
fi

# ---------------------------------------------------------------------------
printf '\n\033[1mPassed: %d   Failed: %d\033[0m\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ] || exit 1
