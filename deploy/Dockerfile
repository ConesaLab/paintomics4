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

# Fail the build now, not at 3am in production, if anything is unimportable.
RUN Rscript -e 'pkgs <- c("purrr", "cluster", "mclust", "amap", "factoextra", \
                          "igraph", "ggplot2", "reshape2", "gridExtra", "jsonlite", \
                          "stringr", "dplyr", "tidyr", "readr", "rvest", "xml2", \
                          "gtools", "qdapRegex", "KEGGgraph", "AnnotationDbi"); \
      for (p in pkgs) { \
        if (!requireNamespace(p, quietly = TRUE)) stop("missing R package: ", p) \
      }; \
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
        curl \
        wget \
        ca-certificates \
    # setpriv, used by the entrypoint to drop privileges after fixing volume
    # ownership.
        util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /opt/venv /opt/venv
COPY --from=r-builder /usr/local/lib/R/site-library /usr/local/lib/R/site-library
COPY --from=r-builder /usr/lib/R/site-library /usr/lib/R/site-library

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user. The data volume is chowned to this uid by the
# entrypoint rather than baked in, since it is mounted at run time.
RUN useradd --create-home --shell /bin/bash --uid 1001 paintomics

WORKDIR /app
COPY --chown=paintomics:paintomics PaintomicsServer /app/PaintomicsServer
COPY --chown=paintomics:paintomics PaintomicsClient /app/PaintomicsClient

# The real config is gitignored and never baked into the image; it is generated
# from the template at start-up so every secret arrives as an environment
# variable. See deploy/entrypoint.sh.
COPY --chown=paintomics:paintomics deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=paintomics:paintomics deploy/uwsgi.ini /app/uwsgi.ini
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chmod +x /app/PaintomicsServer/src/AdminTools/scripts/*.R \
    && chmod +x /app/PaintomicsServer/src/common/bioscripts/*.R

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
