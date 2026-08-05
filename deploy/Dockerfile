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
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

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
        r-cran-biocmanager \
    && rm -rf /var/lib/apt/lists/*

# Not packaged for bookworm; these must come from CRAN.
#   factoextra  -> generateMetaGenes.R
#   qdapRegex   -> hubAnalysisInstall.R
#   ggpubr/ggsignif/visNetwork -> plotting helpers sourced by the above
RUN Rscript -e 'options(warn = 2, Ncpus = parallel::detectCores()); \
      install.packages(c("factoextra", "qdapRegex", "ggpubr", "ggsignif", "visNetwork"), \
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
