# PaintOmics 4 application image.
#
# Two things drive the shape of this file:
#
#   1. Python must be 3.9. Flask 1.1.2 / Werkzeug 1.0.1 / Jinja2 2.11.2 /
#      MarkupSafe 1.1.1 do not import on 3.10+.
#   2. R is required, and not only for admin tasks. PathwayAcquisitionJob.py
#      shells out to generateMetaGenes.R and hubAnalysis.R on the user-facing
#      request path, so an image without R serves pages correctly and then fails
#      the moment someone runs a Hub Analysis or Metagenes job.
#
# Debian bookworm ships R 4.2 with most of what we need as prebuilt r-cran-*
# packages. Only a handful come from CRAN source, and Bioconductor supplies two.
# Building tidyverse from source here would add ~40 minutes; it is not needed --
# the scripts import specific packages, not the metapackage.

# ---------------------------------------------------------------------------
# Stage 1: Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.9-slim-bookworm AS python-builder

# Build-only toolchain. uWSGI and cffi compile C; none of this reaches the
# runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2-dev \
        libffi-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
# pip is upgraded but setuptools deliberately is not: requirements.txt pins
# setuptools<81 because APScheduler 3.6.3 imports pkg_resources, which
# setuptools 82 removed. Upgrading it here would install 82 and then let the
# pinned version win only by luck of ordering.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && /opt/venv/bin/python -c "import pkg_resources, apscheduler; print('pkg_resources OK')"

# ---------------------------------------------------------------------------
# Stage 2: R dependencies
# ---------------------------------------------------------------------------
# Separate stage so a change to requirements.txt does not rebuild R, and a
# change to the R package list does not reinstall Python.
FROM python:3.9-slim-bookworm AS r-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        r-base-core \
        r-base-dev \
        build-essential \
        libcurl4-openssl-dev \
        libssl-dev \
        libxml2-dev \
        libfontconfig1-dev \
        libharfbuzz-dev \
        libfribidi-dev \
        libfreetype6-dev \
        libpng-dev \
        libtiff5-dev \
        libjpeg-dev \
    # Prebuilt Debian binaries. Everything here would otherwise compile from
    # source, and igraph and dplyr alone take ~15 minutes.
        r-cran-purrr \
        r-cran-cluster \
        r-cran-mclust \
        r-cran-igraph \
        r-cran-ggplot2 \
        r-cran-reshape2 \
        r-cran-gridextra \
        r-cran-jsonlite \
        r-cran-stringr \
        r-cran-dplyr \
        r-cran-tidyr \
        r-cran-readr \
        r-cran-tibble \
        r-cran-rvest \
        r-cran-xml2 \
        r-cran-gtools \
        r-cran-amap \
        r-cran-matrix \
        r-cran-biocmanager \
    # The factoextra / ggpubr dependency chain. Without these, install.packages
    # drags in FactoMineR -> car -> lme4 -> nloptr and compiles the lot; nloptr
    # additionally needs CMake and fails outright without it. All of these are
    # prebuilt for bookworm, which removes ~20 minutes and the CMake dependency.
        r-cran-factominer \
        r-cran-rstatix \
        r-cran-car \
        r-cran-lme4 \
        r-cran-nloptr \
        r-cran-broom \
        r-cran-ggrepel \
    # These three are packaged for bookworm too, so only two leaves below need
    # an external repository at all.
        r-cran-factoextra \
        r-cran-ggpubr \
        r-cran-ggsignif \
    # tidyverse is genuinely required, not decorative: GalaxyNetworkFunctionsv2.R
    # (sourced by hubAnalysisInstall.R) calls library(tidyverse) directly, and
    # the hsa install aborted at "FAILED WHILE INSTALLING HUB ANALYSIS
    # INFORMATION" without it. Debian ships it prebuilt, so it is not the slow
    # source build that skipping it was meant to avoid.
        r-cran-tidyverse \
    # Still needed if any remaining leaf package falls back to a source build.
        cmake \
    && rm -rf /var/lib/apt/lists/*

# Not packaged for bookworm; these come from a package repository.
#   factoextra  -> generateMetaGenes.R
#   qdapRegex   -> hubAnalysisInstall.R
#   ggpubr/ggsignif/visNetwork -> plotting helpers sourced by the above
#
# Only qdapRegex and visNetwork are absent from bookworm. Both are stable and
# declare R >= 3.x, so plain CRAN serves versions that work on R 4.2 -- unlike
# factoextra, whose current dependencies (FactoMineR, Matrix) require R >= 4.4
# and which is therefore taken from Debian above.
#
# Keeping this to two leaf packages also means the build barely depends on any
# external R repository, which matters here: the Drago VM sits behind an
# OpenStack network where a Docker MTU mismatch silently broke exactly this
# kind of large download.
#
# options(warn = 2) is deliberate. install.packages() reports an unavailable
# dependency as a *warning* and still exits 0, so without it a missing package
# sails through the build and only surfaces when a user runs a Metagenes job.
RUN Rscript -e 'options(warn = 2, Ncpus = parallel::detectCores()); \
      install.packages(c("qdapRegex", "visNetwork"), \
                       repos = "https://cloud.r-project.org")'

# Bioconductor. KEGGgraph and AnnotationDbi are needed by hubAnalysisInstall.R
# and are not on CRAN.
RUN Rscript -e 'options(warn = 2); \
      BiocManager::install(c("KEGGgraph", "AnnotationDbi"), ask = FALSE, update = FALSE)'

# MORE, the regulatory-analysis backend behind runMORE.R. Not on CRAN or
# Bioconductor -- it is installed from GitHub.
#
# The source matters. There are two repositories called MORE:
#
#   BiostatOmics/MORE  <- CORRECT. Maintained; more() takes targetData /
#                         regulatoryData / condition / varSel / minVariation
#                         and it exports FilterRegulationPerCondition.
#   ConesaLab/MORE     <- WRONG. Superseded; more() takes GeneExpression /
#                         data.omics / edesign / min.variation, and has no
#                         FilterRegulationPerCondition at all.
#
# Installing the ConesaLab one builds and imports perfectly cleanly, then
# every MORE job dies at the model call with "unused arguments". The two are
# distinguishable only by more()'s signature, which is what
# src/tests/test_runmore_r_contract.py checks.
#
# optparse parses runMORE.R's command line and is CRAN-only.
#
# patchwork is pinned, and the pin is what makes this step build at all.
# ggplot2 here is Debian bookworm's r-cran-ggplot2, which is 3.4.1 and frozen
# by the distro. MORE pulls ComplexUpset, which pulls patchwork, and patchwork
# is unpinned from CRAN, so it resolves to whatever is current. Current
# patchwork calls ggplot2::is_ggplot(), added in ggplot2 3.5.2, and on 3.4.1 it
# fails to byte-compile:
#
#   Error: object 'is_ggplot' is not exported by 'namespace:ggplot2'
#   ERROR: lazy loading failed for package 'patchwork'
#   Failed to install 'MORE' from GitHub: Failed to install 'ComplexUpset' ...
#
# `upgrade = "never"` does not prevent this: it stops remotes upgrading what is
# already installed, and patchwork is absent, so it is a fresh install at
# latest. Installing a compatible patchwork first makes it present, and then
# `upgrade = "never"` does keep it.
#
# 1.2.0 is the last line that predates the is_ggplot switch. Raise it only
# together with ggplot2 - and ggplot2 moves only if it stops coming from the
# distro.
RUN Rscript -e 'options(warn = 2, Ncpus = parallel::detectCores()); \
      install.packages(c("optparse", "remotes"), repos = "https://cloud.r-project.org"); \
      remotes::install_version("patchwork", version = "1.2.0", \
                               repos = "https://cloud.r-project.org", upgrade = "never"); \
      remotes::install_github("BiostatOmics/MORE", upgrade = "never")'

# Fail the build now, not at 3am in production, if anything is unimportable.
#
# This list is the union of every R dependency in the repository. Deriving it by
# grepping for `library(` alone is not enough -- hubAnalysisInstall.R loads its
# packages with lapply(c(...), library, character.only = TRUE), which that
# pattern silently skips, and GalaxyNetworkFunctionsv2.R is reached only by
# being source()d. Both gaps produced install failures. When adding an R
# dependency anywhere, add it here too.
RUN Rscript -e 'pkgs <- c("purrr", "cluster", "mclust", "amap", "factoextra", \
                          "igraph", "ggplot2", "ggpubr", "ggsignif", "reshape2", \
                          "gridExtra", "visNetwork", "jsonlite", "tibble", \
                          "stringr", "dplyr", "tidyr", "readr", "rvest", "xml2", \
                          "gtools", "qdapRegex", "tidyverse", \
                          "KEGGgraph", "AnnotationDbi", \
                          "optparse", "MORE"); \
      missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; \
      if (length(missing)) stop("missing R packages: ", paste(missing, collapse = ", ")); \
      cat("all", length(pkgs), "R packages import cleanly\n")'

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM python:3.9-slim-bookworm AS runtime

# Runtime shared libraries only.
#   libcairo2       -> cairocffi, which cairosvg renders through
#   r-base-core     -> Rscript
#   curl            -> downloadReactome.py shells out to it
#   wget            -> hubAnalysisInstall.R passes method="wget" to download.file
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        r-base-core \
    # R's "Recommended" packages (cluster, MASS, Matrix, lattice, survival,
    # nlme, ...) live in /usr/lib/R/library, NOT in either site-library, so the
    # COPY below does not carry them over from the build stage. r-base-core
    # alone omits them, and generateMetaGenes.R needs cluster. The smoke test
    # caught this: the R stage's own import check passed while the runtime
    # image was missing the package.
        r-recommended \
        libcairo2 \
        libcurl4 \
        libxml2 \
        libfontconfig1 \
        libharfbuzz0b \
        libfribidi0 \
        libfreetype6 \
        libpng16-16 \
        libtiff6 \
        libjpeg62-turbo \
    # Shared libraries that COPYed R packages link against. apt pulled these in
    # automatically in the build stage, but COPYing site-library carries the R
    # packages and not the C libraries underneath them:
    #   libuv1   <- fs      <- tidyverse
    #   libnlopt <- nloptr  <- lme4 <- car <- ggpubr
    # Missing, they fail only at library() time with
    #   "unable to load shared object .../fs.so: libuv.so.1: cannot open..."
    # The ldd check at the end of this stage is what keeps this list honest.
        libuv1 \
        libnlopt0 \
        curl \
        wget \
        gnupg \
        ca-certificates \
    # setpriv, used by the entrypoint to drop privileges after fixing volume
    # ownership.
        util-linux \
    && rm -rf /var/lib/apt/lists/*

# MongoDB Database Tools, for mongoimport.
#
# common_build_database.py bulk-loads every collection with mongoimport rather
# than pymongo, so without this the install runs for hours and then dies at the
# very last step with "returned non-zero exit status 127" -- exit 127 being
# "command not found", which the shell=True call does not explain.
#
# Not in Debian: it comes from MongoDB's own repository.
RUN curl -fsSL https://pgp.mongodb.com/server-7.0.asc \
        | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg \
    && echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
        > /etc/apt/sources.list.d/mongodb-org-7.0.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends mongodb-database-tools \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user. The data volume is chowned to this uid by the
# entrypoint rather than baked in, since it is mounted at run time.
RUN useradd --create-home --shell /bin/bash --uid 1001 paintomics

# ---------------------------------------------------------------------------
# ORDERING CONSTRAINT: every COPY from the build context must appear BEFORE the
# `COPY --from=` cross-stage copies below. Do not reorder these.
#
# On the deployment host (Docker 29 / overlay2 / OpenStack VM), a COPY placed
# after the three cross-stage library copies corrupts the image rootfs. Every
# following RUN then dies with
#   runc run failed: ... exec: "/bin/sh": stat /bin/sh: no such file or directory
# and an exec-form probe shows /usr/bin/ls is missing too, so the whole
# filesystem is unreadable rather than just the shell.
#
# It is not about what is copied: a single-file COPY triggers it just as a
# 5000-file directory does, and the same COPY against the base image succeeds.
# It is purely positional -- RUN after those copies is fine, COPY is not.
# Reproduced with --no-cache and a pruned builder cache; survives switching
# from the containerd snapshotter to overlay2.
#
# Moving the context copies ahead of the cross-stage copies avoids it entirely.
# ---------------------------------------------------------------------------
COPY deploy/app.tar /tmp/app.tar
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/uwsgi.ini /app/uwsgi.ini

COPY --from=python-builder /opt/venv /opt/venv
COPY --from=r-builder /usr/local/lib/R/site-library /usr/local/lib/R/site-library
COPY --from=r-builder /usr/lib/R/site-library /usr/lib/R/site-library

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# The application tree is delivered as a tar (built by deploy/build-image.sh and
# copied above) rather than as directory COPYs. tar stores symlinks as symlinks,
# including the cyclic src/src -> ../src and the
# src/public_html -> ../../PaintomicsClient/public_html that points outside the
# tree, so they survive with no exclusion list and no `ln -s` recreation.
#
# The real serverconf.py is excluded from the archive and never baked into the
# image; the entrypoint generates it from the template so every secret arrives
# as an environment variable.
RUN set -eux; \
    mkdir -p /app; \
    tar -xf /tmp/app.tar -C /app; \
    rm -f /tmp/app.tar; \
    mkdir -p /app/PaintomicsServer/src/log; \
    test -L /app/PaintomicsServer/src/src; \
    test -L /app/PaintomicsServer/src/AdminTools/src; \
    test -L /app/PaintomicsServer/src/AdminTools/scripts/src; \
    test -e /app/PaintomicsServer/src/public_html; \
    test ! -e /app/PaintomicsServer/src/conf/serverconf.py; \
    chown -R paintomics:paintomics /app

# Application permissions and runtime verification, deliberately in ONE layer.
#
# These were three separate RUN steps. Splitting them reintroduced the rootfs
# corruption described above the COPY block -- adding layers past a threshold
# makes the next step start with an unreadable filesystem. Keep this merged.
#
# The verification runs HERE, in the runtime image, not in the r-builder. That
# stage's own import check passes by construction because apt installed every
# system library there as a dependency, so it cannot catch a runtime gap, and
# only this image ships. Two failures reached production that way:
# r-recommended (cluster/MASS/Matrix live in /usr/lib/R/library, which no COPY
# carried) and libuv1/libnlopt0 (C libraries the COPYed R packages link
# against). Both looked like a healthy server that died the moment a user ran a
# Metagenes or Hub Analysis job.
#
# library() rather than requireNamespace(): attaching is what triggers dyn.load,
# and it is what the scripts actually do. requireNamespace can succeed where
# library() fails.
RUN set -eux; \
    chmod +x /usr/local/bin/entrypoint.sh; \
    chown paintomics:paintomics /app/uwsgi.ini; \
    chmod +x /app/PaintomicsServer/src/AdminTools/scripts/*.R; \
    chmod +x /app/PaintomicsServer/src/common/bioscripts/*.R; \
    missingLibs="$(find /usr/lib/R /usr/local/lib/R -name '*.so' 2>/dev/null \
        | while read -r so; do ldd "$so" 2>/dev/null | awk '/not found/ {print $1}'; done \
        | sort -u)"; \
    if [ -n "$missingLibs" ]; then \
        echo "R packages link against missing shared libraries:"; \
        echo "$missingLibs"; \
        exit 1; \
    fi; \
    echo "every R shared object resolves"; \
    # External commands the admin tools shell out to. mongoimport was missing
    # and only surfaced as exit 127 after a multi-hour install.
    for binary in Rscript mongoimport curl wget gunzip tar; do \
        command -v "$binary" >/dev/null || { echo "missing command: $binary"; exit 1; }; \
    done; \
    echo "every external command the installer needs is present"; \
    Rscript -e 'pkgs <- c("purrr", "cluster", "mclust", "amap", "factoextra", \
                          "igraph", "ggplot2", "ggpubr", "ggsignif", "reshape2", \
                          "gridExtra", "visNetwork", "jsonlite", "tibble", \
                          "stringr", "dplyr", "tidyr", "readr", "rvest", "xml2", \
                          "gtools", "qdapRegex", "tidyverse", \
                          "KEGGgraph", "AnnotationDbi", \
                          "optparse", "MORE"); \
      failed <- character(0); \
      for (p in pkgs) { \
        ok <- tryCatch({ suppressPackageStartupMessages(library(p, character.only = TRUE)); TRUE }, \
                       error = function(e) FALSE); \
        if (!ok) failed <- c(failed, p) \
      }; \
      if (length(failed)) stop("R packages fail to LOAD in the runtime image: ", \
                               paste(failed, collapse = ", ")); \
      cat("all", length(pkgs), "R packages load in the runtime image\n")'

# DBManager.py is run as a script, so sys.path[0] is its own directory -- that
# resolves `conf.serverconf` and `scripts.downloadReactome`. But
# scripts/downloadReactome.py also imports `src.AdminTools.DBManager`, which
# needs PaintomicsServer itself on the path. Setting it here means admin
# commands work from any working directory.
ENV PYTHONPATH=/app/PaintomicsServer

RUN mkdir -p /data/KEGG_DATA /data/CLIENT_TMP \
    && chown -R paintomics:paintomics /data

# Deliberately no USER directive. A named volume mounted over /data arrives
# root-owned from the Docker daemon, so the container has to start as root to
# take ownership of it. entrypoint.sh does that and then drops to uid 1001 via
# setpriv before exec'ing the server, so no long-running process is root.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/ >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uwsgi", "--ini", "/app/uwsgi.ini"]
