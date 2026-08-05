# PaintOmics 4 Drago Cloud Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship PaintOmics 4 as a versioned public release running under Docker Compose on the CSIC Drago Cloud VM `tliu-vm1`.

**Architecture:** Three containers — `nginx` (TLS + reverse proxy), `app` (Python 3.9 + uWSGI running the Flask application, which also serves the client statics), and `mongo:7` — wired by a single Compose file with three named volumes. All secrets and per-host settings arrive through one root-owned env file; nothing host-specific is committed to git.

**Tech Stack:** Docker Compose, Python 3.9, uWSGI, Flask 1.1.2, pymongo 4.x, MongoDB 7, nginx (alpine), OpenSSL, pytest.

**Spec:** `docs/superpowers/specs/2026-08-05-drago-cloud-deployment-design.md`

## Global Constraints

- **Python must be 3.9.** `Flask 1.1.2`, `Werkzeug 1.0.1`, `Jinja2 2.11.2`, `MarkupSafe 1.1.1` do not import on 3.10+. Never bump the base image past `python:3.9-slim`.
- **uWSGI must run `processes = 1`.** `src/common/PySiQ.py` holds job state in process memory; multiple processes fragment the queue. Concurrency comes from `threads` only.
- **No Redis, no RQ.** `Queue` is the vendored `src/common/PySiQ`.
- **R IS required — both at runtime and at install time.** (Corrected 2026-08-05; this
  constraint previously read "no R", which was wrong and would have produced an image that
  fails the moment a user runs a Hub Analysis or Metagenes job.)
  - Runtime, invoked by `PathwayAcquisitionJob.py`:
    - `:1358` → `src/common/bioscripts/generateMetaGenes.R` — needs `amap`, `cluster`,
      `factoextra`, `mclust`
    - `:1709` → `src/common/bioscripts/hubAnalysis.R` — needs `purrr`, and sources
      `GalaxyNetworkFunctionsv2.R`
  - Database build, invoked by `common_build_database.py:1520` →
    `AdminTools/scripts/processReactomeData.R` — base R only (its `stringr` import was
    removed 2026-08-05)
  - Hub-analysis data install → `AdminTools/scripts/hubAnalysisInstall.R` — needs `readr`,
    `tidyr`, `rvest`, `dplyr`, `xml2`, `stringr`, `qdapRegex`, `gtools`, `jsonlite`, plus
    **two Bioconductor packages, `KEGGgraph` and `AnnotationDbi`**, which need
    `BiocManager` rather than plain `install.packages`.
  - Prefer Debian `r-cran-*` binaries where they exist; only `factoextra`, `ggpubr`,
    `ggsignif`, `visNetwork` and `qdapRegex` need a CRAN source build. Building
    `tidyverse` from source in the image is the slow path — avoid it.
- **MongoDB is never published to the host.** It is reachable only on the internal Compose network.
- **No secret may be committed.** No API key literal may appear as a default value anywhere in tracked files.
- `SERVER_MAX_CONTENT_LENGTH` is 100 MB → nginx `client_max_body_size 100m`.
- `harakiri = 300` → nginx `proxy_read_timeout 300s`.
- VM access: `ssh dragocloud-vm` (161.111.18.82, port 25222, user `tliu`, key `~/.ssh/id_ed25519_drago`).
- Container data paths are `/data/KEGG_DATA` and `/data/CLIENT_TMP` — these already match the defaults in `src/resources/example_serverconf.py`.
- Run all commands from the repo root `/Users/tianyuan/Desktop/github_dev/paintomics4` unless stated otherwise.
- The Python interpreter for local test runs is `/Users/tianyuan/miniforge3/envs/paintomics4/bin/python` (3.9.23).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `PaintomicsServer/src/conf/serverconf.py` | untracked (was tracked) | Live per-host config. Leaves git entirely. |
| `PaintomicsServer/src/resources/example_serverconf.py` | modify | The only tracked config template. Must list every setting with safe defaults. |
| `PaintomicsServer/src/tests/test_release_hygiene.py` | create | Guards against secret literals and template drift regressing. |
| `requirements.txt` | modify | Single authoritative dependency list. |
| `PaintomicsServer/src/requirements.txt` | delete | Duplicate that disagrees with the root file. |
| `PaintomicsServer/src/AdminTools/scripts/clean_databases.py` | modify | pymongo 4 API. |
| `PaintomicsServer/src/AdminTools/DBManager.py` | modify | pymongo 4 API. |
| `deploy/mongo-init.js` | create | Idempotent MongoDB bootstrap, run once by the Mongo entrypoint. |
| `deploy/Dockerfile` | create | Reproducible Python 3.9 app image with Cairo native deps. |
| `deploy/uwsgi.ini` | create | Container uWSGI config (HTTP socket, single process). |
| `deploy/nginx.conf` | create | TLS termination, body-size ceiling, timeouts, proxy. |
| `deploy/compose.yaml` | create | Service wiring, volumes, env injection, restart policy. |
| `deploy/paintomics.env.example` | create | Documented, secret-free template for `/etc/paintomics/paintomics.env`. |
| `deploy/README.md` | create | Operator runbook. |
| `docs/0_install.md` | modify | Replace the obsolete Python 2 procedure. |
| `PaintomicsServer/src/conf/install_paintomics.sh` | delete | Superseded by `deploy/mongo-init.js` + Compose. |

---

## Task 1: Remove the committed API key and untrack the live config

Fixes spec defect **B1**. `PaintomicsServer/src/conf/serverconf.py` is tracked and line 100 carries a live Dashscope key as a hardcoded default.

**Files:**
- Modify: `.gitignore`
- Modify: `PaintomicsServer/src/conf/serverconf.py:96-107`
- Test: `PaintomicsServer/src/tests/test_release_hygiene.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AI_PROVIDERS` dict gains a `"csic"` entry with keys `api_base`, `api_key`, `model`, all sourced from env with `""` defaults. Task 2 mirrors this into the template; Task 8 supplies the values.

**Out-of-band prerequisite (start now, does not block these steps):** rotate the Dashscope key (`sk-sp-26f8…`, recover the full value with `git show 24dc08f1`) in the Alibaba console — it is in public git history. Do not paste the full key into any tracked file.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
"""Release hygiene guards.

These tests fail the build if a secret literal or a stale config template
regresses into the repository. They intentionally scan tracked files only,
so untracked local configuration is never inspected.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Matches the vendor key shapes we actually use: OpenAI/LiteLLM style (sk-...),
# Dashscope service-plan keys (sk-sp-...), and SendGrid (SG....).
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|SG\.[A-Za-z0-9_\-]{20,})")

# Vendored third-party assets are not ours to police.
SKIP_DIRS = ("node_modules/", "/libs/", "/vendor/", ".min.js")


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    for rel in out.stdout.splitlines():
        if any(skip in rel for skip in SKIP_DIRS):
            continue
        yield rel


def test_no_secret_literals_in_tracked_files():
    offenders = []
    for rel in tracked_files():
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for match in SECRET_RE.finditer(text):
            offenders.append(f"{rel}: {match.group(0)[:12]}...")
    assert offenders == [], "Secret literals found in tracked files: " + "; ".join(offenders)


def test_live_serverconf_is_not_tracked():
    tracked = set(tracked_files())
    assert "PaintomicsServer/src/conf/serverconf.py" not in tracked, (
        "serverconf.py is per-host configuration and must not be tracked; "
        "the tracked template is src/resources/example_serverconf.py"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py -v
```

Expected: both tests FAIL — `test_no_secret_literals_in_tracked_files` reports
`PaintomicsServer/src/conf/serverconf.py: sk-sp-26f8a5...`, and
`test_live_serverconf_is_not_tracked` reports the file is tracked.

- [ ] **Step 3: Strip every hardcoded key default**

In `PaintomicsServer/src/conf/serverconf.py`, replace the `AI_LLM_PROVIDER` / `AI_PROVIDERS` block (lines 95–107) with:

```python
# LLM Provider: "csic" (Servicio de LLMs del CSIC), "dashscope", or "openrouter"
AI_LLM_PROVIDER = os.getenv("AI_LLM_PROVIDER", "csic")
AI_PROVIDERS = {
    "csic": {
        "api_base": os.getenv("AI_CSIC_API_BASE", ""),
        "api_key": os.getenv("AI_CSIC_API_KEY", ""),
        "model": os.getenv("AI_CSIC_MODEL", ""),
    },
    "dashscope": {
        "api_base": os.getenv("AI_DASHSCOPE_API_BASE", "https://coding-intl.dashscope.aliyuncs.com/v1"),
        "api_key": os.getenv("AI_DASHSCOPE_API_KEY", ""),
        "model": os.getenv("AI_DASHSCOPE_MODEL", "qwen3.5-plus"),
    },
    "openrouter": {
        "api_base": os.getenv("AI_OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"),
        "api_key": os.getenv("AI_OPENROUTER_API_KEY", ""),
        "model": os.getenv("AI_OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
    },
}
```

An empty default is deliberate: a missing env var must fail loudly rather than silently spend someone else's quota.

- [ ] **Step 4: Untrack the live config and ignore it**

```bash
git rm --cached PaintomicsServer/src/conf/serverconf.py
git rm --cached PaintomicsServer/src/conf/logging.cfg
```

Append to `.gitignore`:

```gitignore
# Per-host configuration generated from src/resources/example_serverconf.py
# on first launch (see src/launch_server.py). Never commit — it holds secrets.
PaintomicsServer/src/conf/serverconf.py
PaintomicsServer/src/conf/logging.cfg
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Verify the app still boots with the file untracked**

`launch_server.py:7` recreates `serverconf.py` from the template when absent. Prove it:

```bash
mv PaintomicsServer/src/conf/serverconf.py /tmp/serverconf.backup.py
cd PaintomicsServer && timeout 25 /Users/tianyuan/miniforge3/envs/paintomics4/bin/python src/launch_server.py 2>&1 | head -5; cd ..
```

Expected: prints `Configuration not found, creating new settings file`, then starts. Restore your working copy:

```bash
mv /tmp/serverconf.backup.py PaintomicsServer/src/conf/serverconf.py
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore PaintomicsServer/src/tests/test_release_hygiene.py
git commit -m "fix: untrack per-host serverconf and remove hardcoded API key defaults

serverconf.py was tracked with a live Dashscope key as a fallback default.
Untrack it (launch_server.py regenerates it from the template), drop every
hardcoded key default, and add a test that fails the build if either
regresses. Adds a 'csic' provider for the CSIC LLM gateway."
```

---

## Task 2: Regenerate the config template

Fixes spec defect **B2**. `example_serverconf.py` is missing all 23 `AI_*` and 4 `EMAIL_*` settings, so a fresh install — which this deployment is — would boot with no AI configuration.

**Files:**
- Modify: `PaintomicsServer/src/resources/example_serverconf.py`
- Test: `PaintomicsServer/src/tests/test_release_hygiene.py`

**Interfaces:**
- Consumes: the `AI_PROVIDERS` shape from Task 1.
- Produces: a template whose top-level setting names are a superset of every name the application imports.

- [ ] **Step 1: Write the failing test**

Append to `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
CONF_DIR = REPO_ROOT / "PaintomicsServer" / "src" / "conf"
TEMPLATE = REPO_ROOT / "PaintomicsServer" / "src" / "resources" / "example_serverconf.py"

SETTING_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


def _settings(path: Path) -> set:
    return set(SETTING_RE.findall(path.read_text(encoding="utf-8")))


def test_template_covers_every_imported_setting():
    """Every `from conf.serverconf import X` must exist in the template.

    Otherwise a fresh install crashes on first import of the missing name.
    """
    imported = set()
    import_re = re.compile(r"from (?:src\.)?conf\.serverconf import ([^\n(]+|\([^)]*\))")
    for rel in tracked_files():
        if not rel.endswith(".py"):
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for match in import_re.finditer(text):
            names = match.group(1).strip().strip("()")
            for name in names.split(","):
                name = name.split(" as ")[0].strip()
                if name and name.isupper():
                    imported.add(name)

    missing = sorted(imported - _settings(TEMPLATE))
    assert missing == [], f"Template is missing settings the code imports: {missing}"


def test_template_holds_no_real_credentials():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert not SECRET_RE.search(text), "Template must ship with empty credential defaults"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py::test_template_covers_every_imported_setting -v
```

Expected: FAIL listing the missing `AI_*` and `EMAIL_*` names.

- [ ] **Step 3: Rewrite the template**

Replace the entire `#SMTP CONFIGURATION` block at the end of `PaintomicsServer/src/resources/example_serverconf.py` (from the line `#SMTP CONFIGURATION` to end of file) with:

```python
#EMAIL CONFIGURATION (SMTP)
import os
from urllib.parse import urlparse

EMAIL_PROVIDER      = "smtp"
EMAIL_FROM_ADDRESS  = os.getenv("EMAIL_FROM_ADDRESS", "notifications@mydomain.com")
EMAIL_FROM_DISPLAY  = os.getenv("EMAIL_FROM_DISPLAY", "PaintOmics")
SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT           = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME       = os.getenv("SMTP_USERNAME", "apikey")
SMTP_PASSWORD       = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS        = True

#WEB-FACING CONSTANTS
PAINTOMICS_BASE_URL     = os.getenv("PAINTOMICS_BASE_URL", "http://localhost:8000").rstrip("/")
PAINTOMICS_LOGO_PATH    = os.getenv("PAINTOMICS_LOGO_PATH", "/resources/images/paintomics_white_300x66")
PAINTOMICS_LOGO_URL     = f"{PAINTOMICS_BASE_URL}{PAINTOMICS_LOGO_PATH}"
PAINTOMICS_LOGIN_URL    = os.getenv("PAINTOMICS_LOGIN_URL", f"{PAINTOMICS_BASE_URL}/")
PAINTOMICS_DOCS_URL     = os.getenv("PAINTOMICS_DOCS_URL", "https://paintomics.readthedocs.io/en/latest/")
PAINTOMICS_EMAIL_DOMAIN = os.getenv("PAINTOMICS_EMAIL_DOMAIN", urlparse(PAINTOMICS_BASE_URL).netloc or "localhost")
EMAIL_REPORT_RECIPIENTS = [e.strip() for e in os.getenv("EMAIL_REPORT_RECIPIENTS", "").split(",") if e.strip()]

#BACKWARDS COMPATIBILITY FOR LEGACY SMTP IMPORTS
smpt_sender      = EMAIL_FROM_ADDRESS
smpt_sender_name = EMAIL_FROM_DISPLAY

#AI INTERPRETATION
AI_INTERPRETATION_ENABLED = os.getenv("AI_INTERPRETATION_ENABLED", "true").lower() == "true"

# Provider: "csic" (Servicio de LLMs del CSIC), "dashscope", or "openrouter".
# All credentials come from the environment; there are no built-in defaults.
AI_LLM_PROVIDER = os.getenv("AI_LLM_PROVIDER", "csic")
AI_PROVIDERS = {
    "csic": {
        "api_base": os.getenv("AI_CSIC_API_BASE", ""),
        "api_key": os.getenv("AI_CSIC_API_KEY", ""),
        "model": os.getenv("AI_CSIC_MODEL", ""),
    },
    "dashscope": {
        "api_base": os.getenv("AI_DASHSCOPE_API_BASE", "https://coding-intl.dashscope.aliyuncs.com/v1"),
        "api_key": os.getenv("AI_DASHSCOPE_API_KEY", ""),
        "model": os.getenv("AI_DASHSCOPE_MODEL", "qwen3.5-plus"),
    },
    "openrouter": {
        "api_base": os.getenv("AI_OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"),
        "api_key": os.getenv("AI_OPENROUTER_API_KEY", ""),
        "model": os.getenv("AI_OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
    },
}

#PUBMED (NCBI E-UTILITIES) — without a key you are throttled to 3 req/s
AI_PUBMED_EMAIL   = os.getenv("AI_PUBMED_EMAIL", "")
AI_PUBMED_API_KEY = os.getenv("AI_PUBMED_API_KEY", "")

#AI PIPELINE TUNING
AI_MAX_PATHWAYS             = 15
AI_PATHWAYS_PER_BATCH       = 5
AI_PAPERS_PER_PATHWAY       = 5
AI_TEMPERATURE              = 0.3
AI_MAX_CONCURRENT_PIPELINES = 2

AI_MAX_SECTION_CHARS            = int(os.getenv("AI_MAX_SECTION_CHARS", "12000"))
AI_MAX_VERIFICATION_ITERATIONS  = int(os.getenv("AI_MAX_VERIFICATION_ITERATIONS", "3"))
AI_VERIFICATION_FUZZY_THRESHOLD = float(os.getenv("AI_VERIFICATION_FUZZY_THRESHOLD", "0.75"))
AI_VERIFICATION_PROVIDER        = os.getenv("AI_VERIFICATION_PROVIDER", "")
AI_EUROPEPMC_DELAY              = float(os.getenv("AI_EUROPEPMC_DELAY", "0.2"))

AI_MAJOR_PATHWAY_MIN_OMICS = int(os.getenv("AI_MAJOR_PATHWAY_MIN_OMICS", "2"))
AI_MAJOR_PATHWAY_MAX_PVAL  = float(os.getenv("AI_MAJOR_PATHWAY_MAX_PVAL", "0.05"))

AI_MAX_SEARCH_TASKS            = int(os.getenv("AI_MAX_SEARCH_TASKS", "12"))
AI_SEARCH_SUBAGENT_WORKERS     = int(os.getenv("AI_SEARCH_SUBAGENT_WORKERS", "4"))
AI_PAPERS_PER_SEARCH_TASK      = int(os.getenv("AI_PAPERS_PER_SEARCH_TASK", "5"))
AI_PAPERS_KEPT_PER_TASK        = int(os.getenv("AI_PAPERS_KEPT_PER_TASK", "3"))
AI_SEARCH_PLANNER_TEMPERATURE  = float(os.getenv("AI_SEARCH_PLANNER_TEMPERATURE", "0.4"))
AI_SEARCH_SUBAGENT_TEMPERATURE = float(os.getenv("AI_SEARCH_SUBAGENT_TEMPERATURE", "0.2"))
```

Also, in the same file, make the container data paths overridable — replace the two `CLIENT_TMP_DIR` / `KEGG_DATA_DIR` lines with:

```python
CLIENT_TMP_DIR            = os.environ.get("PAINTOMICS_CLIENT_TMP", "/data/CLIENT_TMP") + "/"
KEGG_DATA_DIR             = os.environ.get("PAINTOMICS_KEGG_DATA", "/data/KEGG_DATA") + "/"
```

This requires moving `import os` to the top of the file. Add it as the first line.

Note one deliberate deletion: the old template's `smpt_pass = "09bf93aae…"` example hash is removed, not carried over. Shipping any credential-shaped literal in a template teaches the wrong habit.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Verify a template-generated config actually imports**

```bash
cd /tmp && rm -rf conftest_probe && mkdir conftest_probe && \
cp /Users/tianyuan/Desktop/github_dev/paintomics4/PaintomicsServer/src/resources/example_serverconf.py conftest_probe/serverconf.py && \
cd conftest_probe && /Users/tianyuan/miniforge3/envs/paintomics4/bin/python -c \
"import serverconf; print('OK', len([k for k in dir(serverconf) if k.isupper()]), 'settings')"
```

Expected: `OK <n> settings` with no traceback.

- [ ] **Step 6: Commit**

```bash
cd /Users/tianyuan/Desktop/github_dev/paintomics4
git add PaintomicsServer/src/resources/example_serverconf.py PaintomicsServer/src/tests/test_release_hygiene.py
git commit -m "fix: bring example_serverconf up to date with AI and email settings

The template was missing all 23 AI_* and 4 EMAIL_* settings, so a fresh
install booted without AI configuration. Regenerate it from the live config
with empty credential defaults, and add a test asserting the template covers
every setting the code imports."
```

---

## Task 3: Collapse the two conflicting requirements files

Fixes spec defect **B3**. The root and server requirements files disagree on four packages, and `requests` is pinned in neither despite being imported.

**Files:**
- Modify: `requirements.txt`
- Delete: `PaintomicsServer/src/requirements.txt`
- Test: `PaintomicsServer/src/tests/test_release_hygiene.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a single `requirements.txt` at the repo root; Task 6's Dockerfile installs from exactly this path.

- [ ] **Step 1: Write the failing test**

Append to `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
def test_single_requirements_file():
    found = sorted(r for r in tracked_files() if Path(r).name == "requirements.txt")
    assert found == ["requirements.txt"], (
        f"Expected exactly one tracked requirements.txt at the repo root, found: {found}"
    )


def test_every_third_party_import_is_pinned():
    """Guards the specific packages that were previously unpinned."""
    pinned = REPO_ROOT.joinpath("requirements.txt").read_text(encoding="utf-8").lower()
    for package in ("requests", "pymongo", "flask", "uwsgi"):
        assert re.search(rf"^{package}[=><]", pinned, re.MULTILINE), (
            f"{package} is imported or required at runtime but not pinned"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py::test_single_requirements_file \
  PaintomicsServer/src/tests/test_release_hygiene.py::test_every_third_party_import_is_pinned -v
```

Expected: both FAIL — two requirements files exist, and `requests`/`uwsgi` are unpinned.

- [ ] **Step 3: Write the unified requirements file**

Replace the whole of `requirements.txt` with:

```
# PaintOmics 4 runtime dependencies.
# Python 3.9 only: Flask 1.1.2 / Werkzeug 1.0.1 / Jinja2 2.11.2 / MarkupSafe 1.1.1
# do not import on 3.10+. Do not bump the Python base image without upgrading
# the whole Flask stack first.

# --- Web stack (pinned together; these versions are interdependent) ---
Flask==1.1.2
Werkzeug==1.0.1
Jinja2==2.11.2
MarkupSafe==1.1.1
itsdangerous==1.1.0
click==7.1.2
uWSGI==2.0.23

# --- Database ---
# pymongo 4.x is required for MongoDB 7; 3.11 caps at the EOL MongoDB 4.4.
pymongo==4.6.3

# --- Scientific stack ---
numpy==1.26.4
pandas==2.2.2
scipy==1.13.1
statsmodels==0.14.2
patsy==0.5.6

# --- Rendering (Cairo bindings need libcairo2 + pkg-config at build time) ---
cairocffi==1.1.0
CairoSVG==2.7.0
pycairo==1.20.0
Pillow==10.3.0
tinycss2==1.0.2
cssselect2==0.3.0
defusedxml==0.6.0
webencodings==0.5.1

# --- HTTP (used by DBManager.py and downloadReactome.py) ---
requests==2.32.3

# --- Runtime utilities ---
APScheduler==3.6.3
psutil==5.7.2
python-dateutil==2.8.1
pytz==2020.1
tzlocal==2.1
six==1.15.0
wrapt==1.12.1
cffi==1.14.3
pycparser==2.20
scriptinep3==0.3.1
```

- [ ] **Step 4: Delete the duplicate**

```bash
git rm PaintomicsServer/src/requirements.txt
```

- [ ] **Step 5: Verify the set resolves on Python 3.9**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pip install \
  --dry-run --ignore-installed -r requirements.txt 2>&1 | tail -20
```

Expected: pip reports a complete resolution with no `ResolutionImpossible`. If `pycairo==1.20.0` fails to build, that is expected on macOS without Cairo headers — the authoritative check is Task 6's container build. Note any such failure and continue.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt PaintomicsServer/src/tests/test_release_hygiene.py
git commit -m "build: unify requirements into one pinned file

The root and server requirements disagreed on Pillow (10.3.0 vs 8.0.1, the
latter carrying known CVEs), CairoSVG, patsy and statsmodels, and neither
pinned requests despite DBManager importing it. Collapse to one file, take
the newer of each pair, pin requests and uWSGI, and move pymongo to 4.x so
MongoDB 7 is usable."
```

---

## Task 4: pymongo 4 compatibility

Fixes spec defect **B4**. `pymongo==3.11.0` caps MongoDB at the EOL 4.4. The request path already uses the modern API; only two admin scripts block the bump.

**Files:**
- Modify: `PaintomicsServer/src/AdminTools/scripts/clean_databases.py:169-176`
- Modify: `PaintomicsServer/src/AdminTools/DBManager.py:1029`
- Test: `PaintomicsServer/src/tests/test_release_hygiene.py`

**Interfaces:**
- Consumes: `pymongo==4.6.3` from Task 3.
- Produces: no public API change. Behaviour is identical; only removed driver methods are replaced.

- [ ] **Step 1: Write the failing test**

Append to `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
# Methods removed in pymongo 4.x, mapped to their replacements.
REMOVED_PYMONGO_API = {
    ".remove(": ".delete_many(",
    ".insert(": ".insert_one(",
    ".save(": ".replace_one(",
    ".ensureIndex(": ".create_index(",
    ".find_and_modify(": ".find_one_and_update(",
}


def test_no_removed_pymongo_methods_on_collections():
    """Collection.remove/insert/save/ensureIndex were deleted in pymongo 4."""
    # Only flag calls on a Mongo collection subscript, e.g. db['x'].remove(...)
    collection_call = re.compile(r"\]\s*\.\s*(remove|insert|save|ensureIndex|find_and_modify)\(")
    offenders = []
    for rel in tracked_files():
        if not rel.endswith(".py"):
            continue
        for lineno, line in enumerate(
            (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if collection_call.search(line):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "Removed pymongo 3 collection methods still in use: "
        + "; ".join(offenders)
        + f". Replacements: {REMOVED_PYMONGO_API}"
    )


def test_no_cursor_count_calls():
    """Cursor.count() was removed in pymongo 4; use count_documents()."""
    offenders = []
    for rel in tracked_files():
        if not rel.endswith(".py"):
            continue
        for lineno, line in enumerate(
            (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if re.search(r"\b\w*[Ii][Dd]s?\s*\.count\(\)|find\([^)]*\)\.count\(\)", line):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], "Cursor.count() still in use: " + "; ".join(offenders)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py::test_no_removed_pymongo_methods_on_collections \
  PaintomicsServer/src/tests/test_release_hygiene.py::test_no_cursor_count_calls -v
```

Expected: FAIL listing `clean_databases.py:169`, `:171`, `:173`, `:175` and `DBManager.py:1029`.

- [ ] **Step 3: Fix `clean_databases.py`**

In `removeJobByJobID`, replace the four `.remove(` calls with `.delete_many(`:

```python
def removeJobByJobID(connection, user_id, job_id):
    log("Removing job " + job_id)
    #STEP 1. REMOVE ALL THE FEATURES ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['featuresCollection'].delete_many({"jobID": job_id})
    #STEP 2. REMOVE ALL THE VISUAL OPTIONS ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['visualOptionsCollection'].delete_many({"jobID": job_id})
    #STEP 3. REMOVE ALL THE PATHWAYS ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['pathwaysCollection'].delete_many({"jobID": job_id})
    #STEP 4. REMOVE ALL THE FOUND FEATURES ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['foundFeaturesCollection'].delete_many({"jobID": job_id})
```

Then scan the rest of the file for any further `.remove(` on a collection subscript and convert each the same way:

```bash
grep -n "\]\.remove(\|\]\.insert(\|\]\.save(" PaintomicsServer/src/AdminTools/scripts/clean_databases.py
```

Convert every hit: `.remove(` → `.delete_many(`, `.insert(` → `.insert_one(`, `.save(` → `.replace_one(`.

- [ ] **Step 4: Fix `DBManager.py:1029`**

`Cursor.count()` no longer exists. Replace the block at lines 1026–1032 with a version that counts on the collection:

```python
            acceptedIDs = db.versions.find({"name": "ACCEPTED_IDS"})

            try:
                if db.versions.count_documents({"name": "ACCEPTED_IDS"}) > 0:
                    acceptedIDs = acceptedIDs[0].get("ids")
                else:
                    acceptedIDs = ""
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_release_hygiene.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Run the existing regression suite**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest \
  PaintomicsServer/src/tests/test_bug_fixes.py \
  PaintomicsServer/src/tests/test_multicondition_pvalues.py -v
```

Expected: all pass. These do not touch Mongo, so they should be unaffected — record the result as the pre-container baseline.

- [ ] **Step 7: Commit**

```bash
git add PaintomicsServer/src/AdminTools/scripts/clean_databases.py \
        PaintomicsServer/src/AdminTools/DBManager.py \
        PaintomicsServer/src/tests/test_release_hygiene.py
git commit -m "fix: replace pymongo 3 APIs removed in pymongo 4

Collection.remove() and Cursor.count() were deleted in pymongo 4, which is
required for MongoDB 7. The request path already used the modern API; only
clean_databases.py and DBManager.py needed changes. Adds tests that fail if
a removed method reappears."
```

---

## Task 5: MongoDB bootstrap as a container init script

Fixes spec defect **B5**. `install_paintomics.sh` uses the legacy `mongo` shell (removed in MongoDB 6) and `ensureIndex()` (removed in MongoDB 5), and pulls an unverified tarball from a host that now 302-redirects.

**Files:**
- Create: `deploy/mongo-init.js`
- Delete: `PaintomicsServer/src/conf/install_paintomics.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: a database named by `MONGO_INITDB_DATABASE` containing collections `featuresCollection`, `foundFeaturesCollection`, `jobInstanceCollection`, `pathwaysCollection`, `visualOptionsCollection`, `userCollection`, `fileCollection`, `messageCollection`, `counters`; an admin user document with `userID: "0"`; and a `counters` document `{_id: "userID", sequence_value: 1}`. Task 8 mounts this into `docker-entrypoint-initdb.d/`.

Note the old script indexed `visualOptionsCollection` without ever creating it. This version creates it explicitly.

- [ ] **Step 1: Write the init script**

Create `deploy/mongo-init.js`:

```javascript
// PaintOmics 4 database bootstrap.
//
// The mongo:7 entrypoint runs every .js in /docker-entrypoint-initdb.d exactly
// once, against an empty data directory, in the database named by
// MONGO_INITDB_DATABASE. Re-running against an existing volume is a no-op
// because the entrypoint skips initialisation entirely when data is present.
//
// Every operation below is nonetheless written to be idempotent, so this file
// stays safe to apply by hand during recovery.

const COLLECTIONS = [
  "featuresCollection",
  "foundFeaturesCollection",
  "jobInstanceCollection",
  "pathwaysCollection",
  "visualOptionsCollection",  // indexed but never created by the legacy script
  "userCollection",
  "fileCollection",
  "messageCollection",
  "counters",
];

const existing = new Set(db.getCollectionNames());
for (const name of COLLECTIONS) {
  if (!existing.has(name)) {
    db.createCollection(name);
    print("created collection: " + name);
  }
}

// createIndex replaces ensureIndex, which was removed in MongoDB 5.
db.userCollection.createIndex({ userID: 1 });
db.jobInstanceCollection.createIndex({ jobID: 1, userID: 1 });
db.featuresCollection.createIndex({ jobID: 1, featureType: 1 });
db.foundFeaturesCollection.createIndex({ jobID: 1, featureType: 1 });
db.pathwaysCollection.createIndex({ jobID: 1, ID: 1 });
db.visualOptionsCollection.createIndex({ jobID: 1 });
db.fileCollection.createIndex({ userID: 1 });
print("indexes ensured");

// Seed the admin account. Credentials come from the environment so no password
// — not even a placeholder hash — is ever committed.
const adminUser = process.env.PAINTOMICS_ADMIN_USER || "admin";
const adminEmail = process.env.PAINTOMICS_ADMIN_EMAIL || "admin@paintomics.org";
const adminPassSha1 = process.env.PAINTOMICS_ADMIN_PASS_SHA1;
const adminAffiliation = process.env.PAINTOMICS_ADMIN_AFFILIATION || "CSIC";

if (!adminPassSha1) {
  throw new Error(
    "PAINTOMICS_ADMIN_PASS_SHA1 is required. Generate it with:\n" +
    "  printf '%s' 'your-password' | shasum -a 1 | cut -d' ' -f1"
  );
}

if (db.userCollection.countDocuments({ userID: "0" }) === 0) {
  db.userCollection.insertOne({
    userID: "0",
    userName: adminUser,
    email: adminEmail,
    password: adminPassSha1,
    affiliation: adminAffiliation,
    activated: "True",
  });
  print("seeded admin user: " + adminUser);
}

if (db.counters.countDocuments({ _id: "userID" }) === 0) {
  db.counters.insertOne({ _id: "userID", sequence_value: 1 });
  print("seeded userID counter");
}

print("PaintOmics bootstrap complete");
```

- [ ] **Step 2: Verify the script runs against a throwaway MongoDB 7**

```bash
docker run -d --name pm-mongo-probe \
  -e MONGO_INITDB_DATABASE=PaintomicsDB \
  -e PAINTOMICS_ADMIN_PASS_SHA1=40bd001563085fc35165329ea1ff5c5ecbdbbeef \
  -v "$PWD/deploy/mongo-init.js:/docker-entrypoint-initdb.d/mongo-init.js:ro" \
  mongo:7
sleep 12
docker logs pm-mongo-probe 2>&1 | grep -E "created collection|indexes ensured|seeded|bootstrap complete"
```

Expected: 9 `created collection` lines, `indexes ensured`, `seeded admin user: admin`, `seeded userID counter`, `PaintOmics bootstrap complete`.

- [ ] **Step 3: Verify the resulting schema**

```bash
docker exec pm-mongo-probe mongosh PaintomicsDB --quiet --eval \
  'printjson({collections: db.getCollectionNames().sort(), admins: db.userCollection.countDocuments({userID:"0"}), counter: db.counters.findOne({_id:"userID"})})'
```

Expected: all 9 collections listed, `admins: 1`, `counter: { _id: 'userID', sequence_value: 1 }`.

- [ ] **Step 4: Verify the missing-password guard fires**

```bash
docker rm -f pm-mongo-probe
docker run --rm --name pm-mongo-guard \
  -e MONGO_INITDB_DATABASE=PaintomicsDB \
  -v "$PWD/deploy/mongo-init.js:/docker-entrypoint-initdb.d/mongo-init.js:ro" \
  mongo:7 2>&1 | grep -c "PAINTOMICS_ADMIN_PASS_SHA1 is required"
```

Expected: `1` — the container refuses to seed a passwordless admin.

- [ ] **Step 5: Clean up the probe**

```bash
docker rm -f pm-mongo-probe pm-mongo-guard 2>/dev/null; true
```

- [ ] **Step 6: Delete the obsolete installer**

```bash
git rm PaintomicsServer/src/conf/install_paintomics.sh
```

- [ ] **Step 7: Commit**

```bash
git add deploy/mongo-init.js
git commit -m "feat: add MongoDB 7 bootstrap as a container init script

Replaces install_paintomics.sh, which used the legacy mongo shell (removed in
MongoDB 6) and ensureIndex (removed in MongoDB 5), and fetched an unverified
tarball from a host that now redirects. The Mongo entrypoint runs this once on
an empty volume, so manual bootstrap disappears. Also creates
visualOptionsCollection, which the old script indexed without creating, and
takes the admin password from the environment instead of a committed hash."
```

---

## Task 6: Application container image

**Files:**
- Create: `deploy/Dockerfile`
- Create: `deploy/uwsgi.ini`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt` from Task 3.
- Produces: an image exposing HTTP on port `8000`, reading config from environment variables, with data volumes at `/data/KEGG_DATA` and `/data/CLIENT_TMP`. Task 8 wires it into Compose.

- [ ] **Step 1: Write `.dockerignore`**

Create `.dockerignore` at the repo root — without this, the 235 MB `.git` directory lands in the build context:

```
.git
.gitignore
.autoresearch
.pytest_cache
**/__pycache__
**/*.pyc
.DS_Store
**/.DS_Store
.idea
**/.idea
docs/
site/
mongodb_data/
PaintomicsServer/tmp/
PaintomicsServer/tmptest_user/
PaintomicsServer/tmpperf_user/
PaintomicsServer/src/conf/serverconf.py
PaintomicsServer/src/conf/logging.cfg
```

`serverconf.py` is excluded deliberately: the image must generate it from the template so no developer's local config is ever baked in.

- [ ] **Step 2: Write the uWSGI config**

Create `deploy/uwsgi.ini`:

```ini
[uwsgi]
# ---------------------------------------------------------------------------
# processes = 1 is REQUIRED, not a tuning choice.
#
# src/common/PySiQ.py keeps the job queue in process memory. With more than one
# process, a job enqueued by worker A is invisible to worker B, so status polls
# hit the wrong worker and jobs appear to hang. Scale with threads only.
# ---------------------------------------------------------------------------
processes = 1
threads = 6
master = true
lazy-apps = true

# nginx terminates TLS and proxies over plain HTTP on the internal network.
http-socket = 0.0.0.0:8000
wsgi-file = /app/PaintomicsServer/src/launch_server.py
callable = app
chdir = /app/PaintomicsServer

# Matches serverconf MAX_WAIT_THREADS and the nginx proxy_read_timeout.
harakiri = 300
socket-timeout = 300
http-timeout = 300

# 100 MB uploads (SERVER_MAX_CONTENT_LENGTH) need headroom in the buffer.
buffer-size = 65535
listen = 500

die-on-term = true
vacuum = true
log-5xx = true
disable-logging = false
```

- [ ] **Step 3: Write the Dockerfile**

Create `deploy/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Python 3.9 is a hard requirement. Flask 1.1.2 / Werkzeug 1.0.1 / Jinja2 2.11.2
# / MarkupSafe 1.1.1 do not import on 3.10+. Do not bump this tag without first
# upgrading the whole Flask stack.
# ---------------------------------------------------------------------------
FROM python:3.9-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# pycairo and cairocffi compile against Cairo headers; uWSGI needs a C toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libcairo2-dev \
        libjpeg-dev \
        libfreetype6-dev \
        zlib1g-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r /tmp/requirements.txt


FROM python:3.9-slim-bookworm AS runtime

# Runtime shared objects only — no compilers in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libjpeg62-turbo \
        libfreetype6 \
        zlib1g \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 paintomics

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAINTOMICS_KEGG_DATA=/data/KEGG_DATA \
    PAINTOMICS_CLIENT_TMP=/data/CLIENT_TMP

WORKDIR /app
COPY --chown=paintomics:paintomics PaintomicsServer /app/PaintomicsServer
COPY --chown=paintomics:paintomics PaintomicsClient /app/PaintomicsClient
COPY --chown=paintomics:paintomics deploy/uwsgi.ini /app/uwsgi.ini

# launch_server.py generates conf/serverconf.py from the template on first run,
# so the conf directory must be writable by the app user.
RUN mkdir -p /data/KEGG_DATA /data/CLIENT_TMP /app/PaintomicsServer/src/log \
    && chown -R paintomics:paintomics /data /app/PaintomicsServer/src/conf /app/PaintomicsServer/src/log

USER paintomics
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ >/dev/null || exit 1

CMD ["uwsgi", "--ini", "/app/uwsgi.ini"]
```

- [ ] **Step 4: Build the image**

```bash
docker build -f deploy/Dockerfile -t paintomics4:dev .
```

Expected: build succeeds. If `pycairo==1.20.0` fails to compile against Debian bookworm's Cairo, bump only that pin to `pycairo==1.26.0` in `requirements.txt` and rebuild — it is the one dependency whose old pin is most likely to be incompatible with modern headers.

- [ ] **Step 5: Verify the image starts and answers**

```bash
docker run -d --name pm-app-probe -p 8001:8000 paintomics4:dev
sleep 20
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8001/
docker logs pm-app-probe 2>&1 | tail -20
```

Expected: `HTTP 200`, and the logs show `Configuration not found, creating new settings file` followed by uWSGI spawning **1 worker with 6 threads**. Mongo is absent, so data-backed routes will error — serving `index.html` is the success criterion here.

- [ ] **Step 6: Verify the single-process constraint holds**

```bash
docker exec pm-app-probe sh -c 'ps -o pid,args | grep -c "[u]wsgi"'
```

Expected: `2` — one master plus exactly one worker. Any higher number means `processes` was overridden and the job queue will fragment.

- [ ] **Step 7: Clean up**

```bash
docker rm -f pm-app-probe
```

- [ ] **Step 8: Commit**

```bash
git add .dockerignore deploy/Dockerfile deploy/uwsgi.ini
git commit -m "feat: add Python 3.9 application container image

Multi-stage build: Cairo and compiler toolchain in the builder, runtime shared
objects only in the final image, non-root user, healthcheck. uWSGI is pinned to
processes=1 because PySiQ holds job state in process memory."
```

---

## Task 7: nginx reverse proxy with TLS

**Files:**
- Create: `deploy/nginx.conf`
- Create: `deploy/gen-selfsigned-cert.sh`

**Interfaces:**
- Consumes: the `app` service on port 8000 from Task 6.
- Produces: listeners on 80 (redirecting to HTTPS) and 443. Expects certificate and key at `/etc/nginx/certs/paintomics.crt` and `/etc/nginx/certs/paintomics.key`.

- [ ] **Step 1: Write the certificate generator**

Create `deploy/gen-selfsigned-cert.sh`:

```bash
#!/usr/bin/env bash
# Generate a self-signed certificate for the bare-IP deployment.
#
# This encrypts the transport so logins and uploaded datasets are not sent in
# cleartext. Browsers will still warn, because nobody vouches for the identity
# of an IP address. Replace with Let's Encrypt as soon as a DNS name resolves
# to this host — see deploy/README.md.
set -euo pipefail

CERT_DIR="${1:-./certs}"
HOST="${2:-161.111.18.82}"

mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -newkey rsa:4096 \
    -days 825 \
    -keyout "$CERT_DIR/paintomics.key" \
    -out "$CERT_DIR/paintomics.crt" \
    -subj "/C=ES/O=CSIC/CN=${HOST}" \
    -addext "subjectAltName=IP:${HOST}" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth"

chmod 600 "$CERT_DIR/paintomics.key"
chmod 644 "$CERT_DIR/paintomics.crt"

echo "Wrote $CERT_DIR/paintomics.{crt,key} for ${HOST}"
openssl x509 -in "$CERT_DIR/paintomics.crt" -noout -subject -dates -ext subjectAltName
```

Make it executable:

```bash
chmod +x deploy/gen-selfsigned-cert.sh
```

- [ ] **Step 2: Write the nginx config**

Create `deploy/nginx.conf`:

```nginx
# PaintOmics 4 reverse proxy.
#
# The Flask application serves both the API and the client statics through
# send_from_directory, so there is no separate static tier: everything proxies
# to the app container.

upstream paintomics_app {
    server app:8000;
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name _;

    # Reserved for Let's Encrypt HTTP-01 once a DNS name exists.
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name _;

    ssl_certificate     /etc/nginx/certs/paintomics.crt;
    ssl_certificate_key /etc/nginx/certs/paintomics.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # No HSTS while the certificate is self-signed: pinning HTTPS-only before a
    # trusted cert exists makes the site hard to reach if TLS needs rolling back.
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # Must match SERVER_MAX_CONTENT_LENGTH (100 MB) in serverconf.py.
    client_max_body_size 100m;
    client_body_timeout  300s;

    access_log /var/log/nginx/paintomics.access.log;
    error_log  /var/log/nginx/paintomics.error.log warn;

    location / {
        proxy_pass         http://paintomics_app;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Connection        "";

        # Matches uWSGI harakiri = 300. Pathway acquisition is long-running.
        proxy_connect_timeout 30s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;

        proxy_buffering off;
    }
}
```

- [ ] **Step 3: Generate a local test certificate**

```bash
./deploy/gen-selfsigned-cert.sh ./deploy/certs 127.0.0.1
```

Expected: prints the subject, validity dates, and `IP Address:127.0.0.1`.

- [ ] **Step 4: Verify the config parses**

```bash
docker run --rm \
  -v "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$PWD/deploy/certs:/etc/nginx/certs:ro" \
  nginx:alpine nginx -t
```

Expected: `syntax is ok` and `test is successful`. The `upstream app` name does not resolve outside Compose, but `nginx -t` does not resolve upstreams, so this is a valid syntax gate.

- [ ] **Step 5: Keep certificates out of git**

Append to `.gitignore`:

```gitignore
# TLS material — generated per host, never committed
deploy/certs/
```

- [ ] **Step 6: Commit**

```bash
git add deploy/nginx.conf deploy/gen-selfsigned-cert.sh .gitignore
git commit -m "feat: add nginx TLS reverse proxy

Terminates TLS, redirects 80 to 443, and proxies everything to the app (Flask
serves the client statics itself). Body size and timeouts mirror
SERVER_MAX_CONTENT_LENGTH and uWSGI harakiri. Ships a self-signed certificate
generator so the bare-IP deployment is still encrypted, with an ACME challenge
location reserved for the Let's Encrypt switch."
```

---

## Task 8: Compose wiring and the environment template

**Files:**
- Create: `deploy/compose.yaml`
- Create: `deploy/paintomics.env.example`

**Interfaces:**
- Consumes: the image from Task 6, the nginx config from Task 7, the init script from Task 5.
- Produces: a runnable three-service stack. `deploy/paintomics.env.example` documents every variable that `/etc/paintomics/paintomics.env` must define.

- [ ] **Step 1: Write the environment template**

Create `deploy/paintomics.env.example`:

```ini
# PaintOmics 4 deployment environment.
#
# Copy to /etc/paintomics/paintomics.env on the host, fill in the real values,
# then lock it down:
#     sudo chown root:root /etc/paintomics/paintomics.env
#     sudo chmod 600      /etc/paintomics/paintomics.env
#
# This file is read by docker compose (env_file). It must NEVER be committed.

# --- Web ---------------------------------------------------------------
# Used to build links in outgoing email. Must match how users reach the site.
PAINTOMICS_BASE_URL=https://161.111.18.82
PAINTOMICS_EMAIL_DOMAIN=paintomics.csic.es

# --- MongoDB -----------------------------------------------------------
# 'mongo' is the Compose service name on the internal network.
MONGODB_HOST=mongo
MONGODB_PORT=27017
MONGODB_DATABASE=PaintomicsDB
MONGO_INITDB_DATABASE=PaintomicsDB

# --- Admin seed (consumed once, by deploy/mongo-init.js) ---------------
PAINTOMICS_ADMIN_USER=admin
PAINTOMICS_ADMIN_EMAIL=paintomics4@gmail.com
PAINTOMICS_ADMIN_AFFILIATION=CSIC
# Generate with:  printf '%s' 'your-password' | shasum -a 1 | cut -d' ' -f1
PAINTOMICS_ADMIN_PASS_SHA1=

# --- Data paths (inside the container) ---------------------------------
PAINTOMICS_CLIENT_TMP=/data/CLIENT_TMP
PAINTOMICS_KEGG_DATA=/data/KEGG_DATA

# --- Email (SendGrid over SMTP) ----------------------------------------
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=
EMAIL_FROM_ADDRESS=paintomics4@gmail.com
EMAIL_FROM_DISPLAY=PaintOmics
EMAIL_REPORT_RECIPIENTS=paintomics4@gmail.com

# --- AI interpretation -------------------------------------------------
AI_INTERPRETATION_ENABLED=true
AI_LLM_PROVIDER=csic

# Servicio de LLMs del CSIC. Console: https://console.llm.iiia.es (CSIC SSO).
# Verified live 2026-08-05: /v1/models, chat completions, tool calling and JSON
# mode all return 200. Backend is vLLM 0.26.0. Free for CSIC users.
AI_CSIC_API_BASE=https://llm.iiia.es/v1
AI_CSIC_API_KEY=
# Pin an EXPLICIT model — never the `default/llm` alias. The service requires
# this for scientific reproducibility, and PaintOmics output gets cited.
# The dated snapshot is chosen because it cannot drift under a running instance.
# Alternatives: Qwen/Qwen3.6-27B, deepseek-ai/DeepSeek-V4-Flash
AI_CSIC_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731

# NCBI E-utilities. Without a key you are throttled to 3 req/s, and
# AI_SEARCH_SUBAGENT_WORKERS=4 will contend for that budget.
AI_PUBMED_EMAIL=paintomics4@gmail.com
AI_PUBMED_API_KEY=
```

- [ ] **Step 2: Write the Compose file**

Create `deploy/compose.yaml`:

```yaml
# PaintOmics 4 production stack.
#
#   docker compose -f deploy/compose.yaml up -d
#
# Secrets and per-host settings come from /etc/paintomics/paintomics.env
# (root:root, 0600). Nothing host-specific lives in this file.

name: paintomics4

services:
  mongo:
    image: mongo:7
    restart: unless-stopped
    # Deliberately NO ports: — Mongo is reachable only on the internal network.
    env_file: [/etc/paintomics/paintomics.env]
    volumes:
      - mongo_data:/data/db
      - ./mongo-init.js:/docker-entrypoint-initdb.d/mongo-init.js:ro
    networks: [backend]
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s

  app:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    image: paintomics4:${PAINTOMICS_VERSION:-latest}
    restart: unless-stopped
    env_file: [/etc/paintomics/paintomics.env]
    volumes:
      - kegg_data:/data/KEGG_DATA
      - client_tmp:/data/CLIENT_TMP
    networks: [backend, frontend]
    depends_on:
      mongo:
        condition: service_healthy
    # 8 vCPU / 30 GB host; leave headroom for mongo and nginx.
    deploy:
      resources:
        limits:
          cpus: "6.0"
          memory: 20G

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
      - certbot_webroot:/var/www/certbot
      - nginx_logs:/var/log/nginx
    networks: [frontend]
    depends_on:
      app:
        condition: service_started

networks:
  # app <-> mongo. Not reachable from nginx.
  backend:
    internal: true
  # nginx <-> app.
  frontend:

volumes:
  mongo_data:
  kegg_data:
  client_tmp:
  certbot_webroot:
  nginx_logs:
```

- [ ] **Step 3: Verify the Compose file is valid**

```bash
sudo mkdir -p /etc/paintomics
sudo cp deploy/paintomics.env.example /etc/paintomics/paintomics.env
sudo chmod 600 /etc/paintomics/paintomics.env
docker compose -f deploy/compose.yaml config >/dev/null && echo "compose config OK"
```

Expected: `compose config OK`.

- [ ] **Step 4: Set a local admin password hash for testing**

```bash
printf '%s' 'localtest' | shasum -a 1 | cut -d' ' -f1
```

Put the result into `PAINTOMICS_ADMIN_PASS_SHA1` in `/etc/paintomics/paintomics.env`.

- [ ] **Step 5: Commit**

```bash
git add deploy/compose.yaml deploy/paintomics.env.example
git commit -m "feat: add Compose stack and environment template

Three services on two networks: mongo is on an internal-only network with no
published ports, nginx is the sole ingress. All secrets arrive via
/etc/paintomics/paintomics.env, mirroring the env-file pattern already used on
the UV production host."
```

---

## Task 9: Local end-to-end verification

Proves the stack works before any VM is touched. This is the gate for Phase 2.

**Files:**
- Create: `deploy/smoke-test.sh`

**Interfaces:**
- Consumes: the full stack from Task 8.
- Produces: a reusable script that Task 13 re-runs against production.

- [ ] **Step 1: Write the smoke test**

Create `deploy/smoke-test.sh`:

```bash
#!/usr/bin/env bash
# PaintOmics 4 deployment smoke test.
#
#   ./deploy/smoke-test.sh https://127.0.0.1
#
# -k is used throughout because the bare-IP deployment carries a self-signed
# certificate. Drop it once a trusted certificate is installed.
set -uo pipefail

BASE="${1:-https://127.0.0.1}"
PASS=0
FAIL=0

check() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        printf '  \033[32mPASS\033[0m  %-46s %s\n' "$name" "$actual"
        PASS=$((PASS + 1))
    else
        printf '  \033[31mFAIL\033[0m  %-46s got %s, want %s\n' "$name" "$actual" "$expected"
        FAIL=$((FAIL + 1))
    fi
}

code() { curl -sk -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }

echo "Smoke testing ${BASE}"
echo

check "client index served"        200 "$(code "${BASE}/")"
check "admin console served"       200 "$(code "${BASE}/admin/")"
check "species list endpoint"      200 "$(code "${BASE}/kegg_data/species.json")"

# The redirect is issued by nginx on :80.
HTTP_BASE="${BASE/https:/http:}"
check "http redirects to https"    301 "$(code "${HTTP_BASE}/")"

# Signing in exercises the full path: nginx -> uWSGI -> Flask -> MongoDB.
LOGIN=$(curl -sk --max-time 30 -X POST "${BASE}/um_signin" \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        -d 'userName=admin&password=wrong-on-purpose' -o /dev/null -w '%{http_code}')
check "auth endpoint reaches mongo" 200 "$LOGIN"

# Mongo must not be reachable from outside the compose network.
MONGO_HOST="${BASE#*://}"
if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${MONGO_HOST%%:*}/27017" 2>/dev/null; then
    check "mongo NOT publicly exposed" "closed" "OPEN"
else
    check "mongo NOT publicly exposed" "closed" "closed"
fi

# The app port must not be reachable either.
if timeout 5 bash -c "cat < /dev/null > /dev/tcp/${MONGO_HOST%%:*}/8000" 2>/dev/null; then
    check "app port NOT publicly exposed" "closed" "OPEN"
else
    check "app port NOT publicly exposed" "closed" "closed"
fi

echo
echo "  ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
```

```bash
chmod +x deploy/smoke-test.sh
```

- [ ] **Step 2: Bring the stack up locally**

```bash
docker compose -f deploy/compose.yaml up -d --build
sleep 45
docker compose -f deploy/compose.yaml ps
```

Expected: all three services `running`; `mongo` reports `healthy`.

- [ ] **Step 3: Confirm the database bootstrapped**

```bash
docker compose -f deploy/compose.yaml exec -T mongo \
  mongosh PaintomicsDB --quiet --eval \
  'printjson({collections: db.getCollectionNames().length, admin: db.userCollection.countDocuments({userID:"0"})})'
```

Expected: `{ collections: 9, admin: 1 }`.

- [ ] **Step 4: Run the smoke test**

```bash
./deploy/smoke-test.sh https://127.0.0.1
```

Expected: `7 passed, 0 failed`.

- [ ] **Step 5: Run the regression suite inside the app container**

```bash
docker compose -f deploy/compose.yaml exec -T app \
  python -m pytest PaintomicsServer/src/tests/ -v
```

Expected: all tests pass, matching the Task 4 Step 6 baseline. This is the real proof that the pymongo 4 bump and the pinned dependency set work together.

- [ ] **Step 6: Confirm the single-process constraint survived Compose**

```bash
docker compose -f deploy/compose.yaml exec -T app sh -c 'ps -o pid,args | grep -c "[u]wsgi"'
```

Expected: `2` (master + one worker).

- [ ] **Step 7: Tear down and commit**

```bash
docker compose -f deploy/compose.yaml down -v
git add deploy/smoke-test.sh
git commit -m "test: add deployment smoke test

Covers the client, admin console, species endpoint, the HTTP-to-HTTPS
redirect, and an auth round trip that exercises nginx -> uWSGI -> Flask ->
MongoDB. Also asserts the negative cases: neither MongoDB nor the app port is
reachable from outside."
```

---

## Task 10: Reconcile branches and cut the first release tag

Fixes spec defect **B6**. `dev` is 24 commits behind `master` and the repository has never been tagged.

**Files:** none — git operations only.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: tag `v4.0.0` on the release commit. Task 12 deploys this exact tag.

- [ ] **Step 1: Record the current divergence**

```bash
git fetch origin
git rev-list --left-right --count origin/master...origin/dev
git log --oneline origin/dev..origin/master
```

Record the output — it is the list of work that must land in the release.

- [ ] **Step 2: Merge master into dev**

```bash
git checkout dev
git merge origin/master
```

If conflicts arise, resolve them favouring `master` for anything outside the files this plan changed, and favouring `dev` for `deploy/`, `requirements.txt`, `example_serverconf.py` and the AdminTools pymongo fixes.

- [ ] **Step 3: Verify the merged tree still passes**

```bash
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python -m pytest PaintomicsServer/src/tests/ -v
docker compose -f deploy/compose.yaml up -d --build && sleep 45
./deploy/smoke-test.sh https://127.0.0.1
docker compose -f deploy/compose.yaml down -v
```

Expected: all tests pass and `7 passed, 0 failed`. Do not proceed past a failure here.

- [ ] **Step 4: Tag the release**

```bash
git tag -a v4.0.0 -m "PaintOmics 4.0.0 — first tagged release

Containerised deployment (Docker Compose: nginx + uWSGI/Flask + MongoDB 7).
Config and secrets moved fully out of version control. MongoDB driver
modernised to pymongo 4. AI interpretation backed by the CSIC LLM gateway."
git tag -l -n9
```

- [ ] **Step 5: Push branch and tag**

Confirm with the repository owner before pushing — this is the project's first tag and it is visible to every contributor.

```bash
git push origin dev
git push origin v4.0.0
```

---

## Task 11: Provision the Drago Cloud VM

First task that touches the VM. `tliu-vm1` is a bare Ubuntu 24.04 host: no Docker, no web server, no database.

**Files:**
- Create: `deploy/provision-vm.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a VM with Docker Engine, `/etc/paintomics/paintomics.env`, and `/opt/paintomics` ready for Task 12.

**Out-of-band prerequisite:** open the security group. In the Drago Cloud console add two ingress rules — TCP 80 from `0.0.0.0/0` and TCP 443 from `0.0.0.0/0`. Leave the existing TCP 25222 SSH rule alone. Do **not** open 8000 or 27017.

- [ ] **Step 1: Write the provisioning script**

Create `deploy/provision-vm.sh`:

```bash
#!/usr/bin/env bash
# Provision a bare Ubuntu 24.04 host for the PaintOmics 4 stack.
# Idempotent: safe to re-run.
#
#   scp deploy/provision-vm.sh dragocloud-vm:/tmp/
#   ssh dragocloud-vm 'sudo bash /tmp/provision-vm.sh'
set -euo pipefail

APP_DIR=/opt/paintomics
ENV_DIR=/etc/paintomics

echo "==> Installing Docker Engine from the official repository"
apt-get update
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
fi

cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable
EOF

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
                   docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

echo "==> Granting the deploy user Docker access"
usermod -aG docker "${SUDO_USER:-tliu}"

echo "==> Creating directories"
mkdir -p "$APP_DIR" "$ENV_DIR"
chown "${SUDO_USER:-tliu}":"${SUDO_USER:-tliu}" "$APP_DIR"
chmod 700 "$ENV_DIR"

echo "==> Leaving ufw inactive"
# The OpenStack security group is the single enforcement point. Two overlapping
# firewalls is a reliable way to produce a confusing outage.
ufw status | head -1

echo "==> Configuring log rotation for container logs"
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
EOF
systemctl restart docker

echo "==> Versions"
docker --version
docker compose version

echo
echo "Provisioning complete."
echo "Next: create ${ENV_DIR}/paintomics.env (root:root, 0600) from"
echo "      deploy/paintomics.env.example, then run Task 12."
```

```bash
chmod +x deploy/provision-vm.sh
```

- [ ] **Step 2: Confirm the VM is reachable, and that the 1 TB data volume is mounted**

The `paintomics-data` Cinder volume was provisioned on 2026-08-05 — created (600 GiB), attached as
`/dev/vdb`, formatted ext4 with `-m 0`, and mounted at `/var/lib/docker` via fstab by UUID with
`nofail`. This step verifies it survived, because everything Docker writes depends on it.

```bash
ssh dragocloud-vm 'hostname; . /etc/os-release && echo "$PRETTY_NAME"; nproc; free -g | head -2
echo "--- storage ---"; df -h / /var/lib/docker; lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT
echo "--- fstab survives reboot? ---"; sudo findmnt --verify 2>&1 | tail -2'
```

Expected: `tliu-vm1`, `Ubuntu 24.04.4 LTS`, `8`, ~30 GB RAM, ~74 GB free on `/`, and **`/dev/vdb`
ext4 mounted on `/var/lib/docker` with ~590 GB available**, `findmnt --verify` reporting
`Success, no errors or warnings detected`.

If `/var/lib/docker` is *not* on `/dev/vdb`, stop — Docker would fill the 80 GB root disk instead.
Re-attach the volume in the console (`https://cloud.rstools.csic.es` → 卷 → paintomics-data →
管理连接) and `sudo mount -a` before continuing.

- [ ] **Step 3: Run provisioning**

```bash
scp deploy/provision-vm.sh dragocloud-vm:/tmp/
ssh dragocloud-vm 'sudo bash /tmp/provision-vm.sh'
```

Expected: ends with `Provisioning complete.` and prints Docker and Compose versions.

- [ ] **Step 4: Verify Docker works without sudo**

Group membership needs a fresh session:

```bash
ssh dragocloud-vm 'docker run --rm hello-world | head -3'
```

Expected: `Hello from Docker!`. If it reports a permission error, reconnect (the `docker` group is only applied to new sessions) and retry.

- [ ] **Step 5: Verify the security group rules took effect**

From your workstation:

```bash
for p in 80 443 8000 27017; do
  printf '%-6s ' "$p"
  nc -z -G 6 161.111.18.82 "$p" 2>&1 && echo OPEN || echo "closed/filtered"
done
```

Expected: **80 and 443 OPEN**; **8000 and 27017 closed**. Nothing is listening on 80/443 yet, so `OPEN` here means the security group forwards and the host refuses — either way the rule is live. If 80/443 still show closed, the console change has not applied; do not continue to Task 12.

- [ ] **Step 6: Install the environment file**

```bash
scp deploy/paintomics.env.example dragocloud-vm:/tmp/
ssh dragocloud-vm 'sudo install -o root -g root -m 600 /tmp/paintomics.env.example /etc/paintomics/paintomics.env && rm /tmp/paintomics.env.example'
```

Then edit it in place and fill in every blank value:

```bash
ssh -t dragocloud-vm 'sudo nano /etc/paintomics/paintomics.env'
```

Required before Task 12: `PAINTOMICS_ADMIN_PASS_SHA1`, `SMTP_PASSWORD`, `AI_CSIC_API_BASE`, `AI_CSIC_API_KEY`, `AI_CSIC_MODEL`.

- [ ] **Step 7: Verify the env file permissions**

```bash
ssh dragocloud-vm 'sudo stat -c "%a %U:%G %n" /etc/paintomics/paintomics.env'
```

Expected: `600 root:root /etc/paintomics/paintomics.env`.

- [ ] **Step 8: Commit**

```bash
git add deploy/provision-vm.sh
git commit -m "feat: add VM provisioning script

Installs Docker Engine from the official repository, creates /opt/paintomics
and a 0700 /etc/paintomics, caps container log growth, and deliberately leaves
ufw inactive so the OpenStack security group stays the single enforcement
point."
```

---

## Task 12: Deploy and bootstrap KEGG data

**Files:** none — deployment operations only.

**Interfaces:**
- Consumes: the provisioned VM (Task 11) and tag `v4.0.0` (Task 10).
- Produces: a running stack with KEGG data for the chosen launch species.

- [ ] **Step 1: Clone the release tag onto the VM**

```bash
ssh dragocloud-vm 'git clone --branch v4.0.0 --depth 1 https://github.com/ConesaLab/paintomics4.git /opt/paintomics/app && git -C /opt/paintomics/app describe --tags'
```

Expected: `v4.0.0`.

- [ ] **Step 2: Generate the production certificate**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && ./deploy/gen-selfsigned-cert.sh ./deploy/certs 161.111.18.82'
```

Expected: prints `CN=161.111.18.82` and `IP Address:161.111.18.82`.

- [ ] **Step 3: Build and start**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml up -d --build'
```

The first build compiles pycairo and uWSGI; allow 5–10 minutes.

- [ ] **Step 4: Verify all services are healthy**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml ps'
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml logs --tail=30 app'
```

Expected: three services `running`, `mongo` `healthy`, and the app log showing uWSGI with **1 worker, 6 threads**.

- [ ] **Step 5: Confirm the database bootstrapped**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml exec -T mongo mongosh PaintomicsDB --quiet --eval "printjson({collections: db.getCollectionNames().length, admin: db.userCollection.countDocuments({userID:\"0\"})})"'
```

Expected: `{ collections: 9, admin: 1 }`.

- [ ] **Step 6: Confirm the site answers from the public internet**

From your workstation:

```bash
curl -sk -o /dev/null -w 'https: %{http_code}\n' https://161.111.18.82/
curl -s  -o /dev/null -w 'http:  %{http_code}\n' http://161.111.18.82/
```

Expected: `https: 200` and `http: 301`.

- [ ] **Step 7: Start the KEGG download under tmux**

⚠️ `DBManager` fetches one KGML *and* one PNG per pathway, serialised behind a 2-second delay (`DOWNLOAD_DELAY_1`). At roughly 350 pathways per organism this is **hours per species**. Never run it in a foreground SSH session.

Decide the launch species list before starting. For a single species (`mmu` shown):

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && tmux new-session -d -s kegg \
  "docker compose -f deploy/compose.yaml exec -T app python /app/PaintomicsServer/src/AdminTools/DBManager.py download --specie=mmu --kegg=1 --mapping=1 --common=0 --reactome=1 2>&1 | tee /data/CLIENT_TMP/kegg-mmu.log"'
```

- [ ] **Step 8: Monitor progress**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml exec -T app tail -5 /data/CLIENT_TMP/kegg-mmu.log'
ssh dragocloud-vm 'df -h /var/lib/docker | tail -1'
```

Re-run periodically. If the download is interrupted, `DBManager` leaves a `DOWNLOADING` sentinel and re-running the same command resumes.

- [ ] **Step 9: Verify the species is registered**

```bash
curl -sk https://161.111.18.82/kegg_data/species.json | head -20
```

Expected: JSON containing the downloaded species. Reference footprint: roughly 4.7 GB for the local species set — check `df -h` leaves comfortable headroom on the 74 GB volume.

---

## Task 13: Production verification

**Files:** none.

**Interfaces:**
- Consumes: the deployed stack (Task 12) and `deploy/smoke-test.sh` (Task 9).

- [ ] **Step 1: Run the smoke test against production**

```bash
./deploy/smoke-test.sh https://161.111.18.82
```

Expected: `7 passed, 0 failed`. The two negative checks confirm neither MongoDB nor port 8000 is publicly reachable.

- [ ] **Step 2: Verify the AI provider configuration resolved**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml exec -T app python -c "
import sys; sys.path.insert(0, \"PaintomicsServer/src\")
from conf.serverconf import AI_LLM_PROVIDER, AI_PROVIDERS, AI_INTERPRETATION_ENABLED
p = AI_PROVIDERS[AI_LLM_PROVIDER]
print(\"enabled:\", AI_INTERPRETATION_ENABLED)
print(\"provider:\", AI_LLM_PROVIDER)
print(\"api_base:\", p[\"api_base\"] or \"<<EMPTY>>\")
print(\"model:\", p[\"model\"] or \"<<EMPTY>>\")
print(\"key set:\", bool(p[\"api_key\"]))
"'
```

Expected: `enabled: True`, `provider: csic`, a real `api_base` and `model`, `key set: True`. Any `<<EMPTY>>` means the env file is incomplete.

- [ ] **Step 3: Verify the CSIC gateway answers**

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml exec -T app python -c "
import sys; sys.path.insert(0, \"PaintomicsServer/src\")
from conf.serverconf import AI_LLM_PROVIDER, AI_PROVIDERS
from classes.AIInterpret.llm_client import LLMClient
c = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
print(c.chat([{\"role\": \"user\", \"content\": \"Reply with the single word: ok\"}]))
"'
```

Expected: a short completion containing `ok`. A 401 means the token needs rotating or was mistyped; a 404 means `AI_CSIC_API_BASE` lost its `/v1` suffix.

- [ ] **Step 3b: Confirm the pinned model is still offered**

The gateway is a prototype on shared CSIC hardware; models can be withdrawn between releases.

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml exec -T app python -c "
import os, requests
base = os.environ[\"AI_CSIC_API_BASE\"]; key = os.environ[\"AI_CSIC_API_KEY\"]; want = os.environ[\"AI_CSIC_MODEL\"]
ids = [m[\"id\"] for m in requests.get(base + \"/models\", headers={\"Authorization\": \"Bearer \" + key}, timeout=30).json()[\"data\"]]
print(\"available:\", ids)
assert want in ids, \"PINNED MODEL %s IS GONE — pick another from the list above\" % want
print(\"pinned model present:\", want)
"'
```

Expected: the list includes `deepseek-ai/DeepSeek-V4-Flash-0731` and the assertion passes. If it fails, choose another explicit model — **never fall back to the `default/llm` alias**, which breaks reproducibility of published results.

If the gateway is unreachable, set `AI_INTERPRETATION_ENABLED=false` in the env file, `docker compose restart app`, and follow up. It does not block the core platform.

- [ ] **Step 4: Manual browser journey**

Open `https://161.111.18.82/` and, accepting the certificate warning:

1. Register a new user; confirm the activation email arrives (validates SendGrid).
2. Sign in as `admin`.
3. Upload the example dataset and start a pathway acquisition job.
4. Confirm the job completes, KEGG pathway images render, and the pathway network loads.
5. Trigger an AI interpretation and confirm it produces cited output.

Record any failure with the relevant container log before changing anything:

```bash
ssh dragocloud-vm 'cd /opt/paintomics/app && docker compose -f deploy/compose.yaml logs --tail=100 app'
```

- [ ] **Step 5: Confirm restart resilience**

```bash
ssh dragocloud-vm 'sudo reboot' || true
sleep 90
curl -sk -o /dev/null -w 'after reboot: %{http_code}\n' https://161.111.18.82/
```

Expected: `after reboot: 200` — `restart: unless-stopped` brings the whole stack back without intervention.

---

## Task 14: Operator runbook and installation docs

Fixes spec defect **B7**. `docs/0_install.md` documents a Python 2 era procedure against packages that no longer exist in Ubuntu 24.04, and clones the wrong repository.

**Files:**
- Create: `deploy/README.md`
- Modify: `docs/0_install.md`

**Interfaces:**
- Consumes: every preceding task.

- [ ] **Step 1: Write the operator runbook**

Create `deploy/README.md`:

````markdown
# PaintOmics 4 — deployment runbook

Production runs under Docker Compose: `nginx` (TLS, ingress) → `app`
(uWSGI + Flask, which also serves the client) → `mongo:7`.

## Layout

| Path | Purpose |
|---|---|
| `/opt/paintomics/app` | Checkout of the deployed tag |
| `/etc/paintomics/paintomics.env` | All secrets and per-host config (root:root, 0600) |
| `deploy/certs/` | TLS certificate and key (never committed) |

Named volumes: `mongo_data`, `kegg_data`, `client_tmp`, `nginx_logs`, `certbot_webroot`.

## Everyday operations

```bash
cd /opt/paintomics/app

docker compose -f deploy/compose.yaml ps                  # status
docker compose -f deploy/compose.yaml logs -f app         # follow app logs
docker compose -f deploy/compose.yaml restart app         # apply an env change
docker compose -f deploy/compose.yaml down                # stop (volumes kept)
```

`down -v` **destroys every volume**, including the database and the KEGG data.
Never run it in production.

## Deploying a new version

```bash
cd /opt/paintomics/app
git fetch --tags && git checkout v4.0.1
docker compose -f deploy/compose.yaml up -d --build
./deploy/smoke-test.sh https://161.111.18.82
```

Rollback is `git checkout` of the previous tag plus the same `up -d --build`.

## Two constraints that must not be relaxed

1. **`processes = 1` in `deploy/uwsgi.ini`.** `src/common/PySiQ.py` keeps the
   job queue in process memory. A second process gets its own queue, so status
   polls hit the wrong worker and jobs appear to hang. Scale with `threads`.
2. **MongoDB is never published to the host.** It lives on an `internal: true`
   Compose network. Adding a `ports:` entry exposes an unauthenticated database.

## Backups

```bash
docker compose -f deploy/compose.yaml exec -T mongo \
  mongodump --db PaintomicsDB --archive | gzip > "paintomics-$(date +%F).archive.gz"
```

Restore:

```bash
gunzip -c paintomics-YYYY-MM-DD.archive.gz | \
  docker compose -f deploy/compose.yaml exec -T mongo mongorestore --archive
```

`kegg_data` is reproducible from KEGG and need not be backed up. `client_tmp`
holds user uploads and should be included in host-level backups.

## Switching to a trusted certificate

The bare-IP deployment uses a self-signed certificate: the transport is
encrypted, but browsers warn because nobody vouches for an IP address. Once a
DNS name resolves to this host:

1. Set `server_name` in `deploy/nginx.conf` to the hostname.
2. Run certbot against the `certbot_webroot` volume (the ACME challenge
   location is already configured on port 80).
3. Point `ssl_certificate` / `ssl_certificate_key` at the issued files.
4. Update `PAINTOMICS_BASE_URL` in `/etc/paintomics/paintomics.env`.
5. Enable HSTS in `deploy/nginx.conf` — deliberately omitted while the
   certificate is self-signed, because pinning HTTPS-only before a trusted
   certificate exists makes the site hard to recover if TLS needs rolling back.
6. `docker compose -f deploy/compose.yaml restart nginx app`

**Do not announce the instance publicly until this is done.**

## Adding a KEGG species

Hours per species — always use tmux.

```bash
tmux new-session -d -s kegg \
  "docker compose -f deploy/compose.yaml exec -T app \
   python PaintomicsServer/src/AdminTools/DBManager.py \
   --specie=hsa --kegg=1 --mapping=1 --common=1 --reactome=1"
```

Interrupted downloads resume: `DBManager` leaves a `DOWNLOADING` sentinel and
re-running the same command picks up where it stopped.

## Housekeeping

`client_tmp` grows with usage — 200 MB quota per user, 90-day guest retention,
365-day job retention. Schedule the existing cleanup scripts:

```bash
docker compose -f deploy/compose.yaml exec -T app \
  python PaintomicsServer/src/AdminTools/scripts/clean_databases.py
docker compose -f deploy/compose.yaml exec -T app \
  python PaintomicsServer/src/AdminTools/scripts/cleanup_orphaned_data.py
```
````

- [ ] **Step 2: Rewrite the installation documentation**

Replace everything in `docs/0_install.md` from `## Requirements` to the end of file with:

````markdown
## Requirements

* Linux host with Docker Engine 24+ and the Compose plugin
* 4+ CPU cores, 8 GB RAM minimum (8 cores / 30 GB recommended)
* 100 GB disk — KEGG data alone is several GB per species set
* Outbound HTTPS to `rest.kegg.jp`, `reactome.org` and PyPI

No local Python, MongoDB, R or web server installation is needed: every
component runs in a container.

## Install

```bash
git clone --branch v4.0.0 https://github.com/ConesaLab/paintomics4.git
cd paintomics4
```

## Configure

All settings and secrets live in one file outside the repository.

```bash
sudo mkdir -p /etc/paintomics
sudo install -m 600 -o root -g root deploy/paintomics.env.example /etc/paintomics/paintomics.env
sudo nano /etc/paintomics/paintomics.env
```

At minimum set `PAINTOMICS_BASE_URL`, `PAINTOMICS_ADMIN_PASS_SHA1` (generate
with `printf '%s' 'your-password' | sha1sum | cut -d' ' -f1`) and, if you want
email, `SMTP_PASSWORD`. Every variable is documented inline.

`PaintomicsServer/src/conf/serverconf.py` is **not** tracked in git. It is
generated automatically from `src/resources/example_serverconf.py` on first
launch and reads its values from the environment, so you should not need to
edit it by hand.

## TLS

```bash
./deploy/gen-selfsigned-cert.sh ./deploy/certs your.hostname.example
```

For a public instance, replace this with a certificate from a real authority —
see `deploy/README.md`.

## Run

```bash
docker compose -f deploy/compose.yaml up -d --build
./deploy/smoke-test.sh https://your.hostname.example
```

The database schema and the admin account are created automatically on first
start.

## Load pathway data

Nothing is preloaded. Download one species at a time — each takes hours,
because KEGG's REST API is rate limited.

```bash
docker compose -f deploy/compose.yaml exec app \
  python PaintomicsServer/src/AdminTools/DBManager.py \
  --specie=mmu --kegg=1 --mapping=1 --common=1
```

Use `tmux` or `nohup`; interrupted downloads resume on re-run.

## Operating the instance

Upgrades, backups, adding species and certificate renewal are covered in
[`deploy/README.md`](https://github.com/ConesaLab/paintomics4/blob/master/deploy/README.md).
````

- [ ] **Step 3: Verify no stale references survive**

```bash
grep -n "paintomics3\|apt-get install mongodb\|sudo pip install\|python-cairosvg" docs/0_install.md || echo "clean"
```

Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
git add deploy/README.md docs/0_install.md
git commit -m "docs: replace obsolete install guide with the container runbook

docs/0_install.md documented a Python 2 era apt/pip procedure against packages
that no longer exist on Ubuntu 24.04, and cloned fikipollo/paintomics3. Adds an
operator runbook covering upgrades, backups, KEGG species loading, the
Let's Encrypt cutover, and the two constraints that must not be relaxed
(single uWSGI process, unpublished MongoDB)."
```

---

## Outstanding external inputs

None of these block Tasks 1–11.

| Input | Source | Needed by |
|---|---|---|
| ~~CSIC LLM `api_base` + model ID~~ | ✅ **Resolved** — `https://llm.iiia.es/v1`, `deepseek-ai/DeepSeek-V4-Flash-0731`, verified live 2026-08-05 | — |
| Rotated CSIC token | `https://console.llm.iiia.es` (self-service, CSIC SSO) | Task 11 Step 6 |
| Rotated Dashscope key | Alibaba console | Task 1 (out of band) |
| SendGrid key | SendGrid console | Task 11 Step 6 |
| NCBI PubMed API key | NCBI account | Optional — raises 3 req/s to 10 req/s |
| Launch species list | Project decision | Task 12 Step 7 |
| Security group 80/443 | Drago Cloud console | Task 11 Step 5 |
| DNS name | CSIC IT | Task 14 Step 1 (Let's Encrypt cutover) |

## Fallback: GLPI request for the security-group change

Task 11 assumes the Drago Cloud console can be reached. GLPI **#0007968** records that this failed
before — the CSIC VPN does not route to the Drago network. If the console is unreachable again,
raise a ticket rather than losing time: `soporteaic@csic.es` is the established channel for this
tenant (prior tickets #0007335, #0007425, #0007588; técnicos Fernando Royo and Daniel Rodríguez
López). Cloud documentation: `https://docaic.rstools.csic.es/es/home`.

> Asunto: Solicitud de reglas de grupo de seguridad (puertos 80/443) — VM tliu-vm1 en Drago Cloud
>
> Buenos días,
>
> Solicito la apertura de dos reglas de entrada en el grupo de seguridad de mi
> instancia de Drago Cloud `tliu-vm1` (161.111.18.82):
>
> - TCP 80 desde 0.0.0.0/0
> - TCP 443 desde 0.0.0.0/0
>
> La regla existente de SSH (TCP 25222) debe mantenerse sin cambios. No es
> necesario abrir ningún otro puerto: la base de datos y el servidor de
> aplicación quedan accesibles únicamente dentro de la máquina.
>
> El motivo es el despliegue de PaintOmics 4, la plataforma de análisis
> multi-ómico del grupo de Ana Conesa (I2SysBio, CSIC-UV), continuación del
> proyecto "Paintomics 4 in Drago" iniciado en la reunión del 12 de mayo de 2026
> (tickets #0007335 y #0007425).
>
> Aprovecho para confirmar que la cuota del tenant cubre tres contenedores en
> ejecución continua y unos 5 GB de datos de KEGG.
>
> Muchas gracias,
> Tianyuan Liu — I2SysBio (CSIC-UV)

## Token rotation

The CSIC LLM token is self-service: sign in at `https://console.llm.iiia.es` with CSIC SSO
("Usuarios CSIC" button) and issue a replacement. No email to `llm@csic.es` is needed.

Note from the earlier support thread: the SSO login once looped back to the `/register` form for
this account. Jesús Cerquides (`j.cerquides@csic.es`) resolved it by deleting and recreating the
user. If the loop recurs, contact him rather than re-registering.
