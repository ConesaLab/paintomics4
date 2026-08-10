"""PaintOmics 4 server configuration template.

Copy to `PaintomicsServer/src/conf/serverconf.py` and edit. That path is
gitignored: the real config holds credentials and MUST NOT be committed.

    cp PaintomicsServer/src/resources/example_serverconf.py \
       PaintomicsServer/src/conf/serverconf.py

Every secret is read from the environment with an empty default. Nothing in
this file may ever carry a real key, token or password -- enforced by
`src/tests/test_release_hygiene.py`.

Defaults target the containerised deployment (see `deploy/README.md`).
"""
import os
from urllib.parse import urlparse

# ========== SERVER SETTINGS ==========
SERVER_HOST_NAME          = os.getenv("SERVER_HOST_NAME", "0.0.0.0")   # 0.0.0.0 listens on all interfaces
SERVER_PORT_NUMBER        = int(os.getenv("SERVER_PORT_NUMBER", "8000"))
SERVER_ALLOW_DEBUG        = os.getenv("SERVER_ALLOW_DEBUG", "false").lower() == "true"  # NEVER true in production
SERVER_SUBDOMAIN          = os.getenv("SERVER_SUBDOMAIN", "")          # e.g. "paintomics" if served at myserver.com/paintomics
SERVER_MAX_CONTENT_LENGTH = 100 * pow(1024, 2)                         # Must match nginx client_max_body_size
ADMIN_ACCOUNTS            = os.getenv("ADMIN_ACCOUNTS", "admin")

# ========== FILES SETTINGS ==========
ROOT_DIRECTORY            = ""                                         # Blank = auto-detect
CLIENT_TMP_DIR            = os.getenv("PAINTOMICS_CLIENT_TMP", "/data/CLIENT_TMP") + "/"
KEGG_DATA_DIR             = os.getenv("PAINTOMICS_KEGG_DATA", "/data/KEGG_DATA") + "/"
MAX_CLIENT_SPACE          = 200 * pow(1024, 2)
MAX_GUEST_DAYS            = 90
MAX_JOB_DAYS              = 365
MAX_NUMBER_FEATURES       = 1000000

# ========== MONGO DB SETTINGS ==========
# In Compose this is the service name ("mongo"), reachable only on the internal
# network. MongoDB is never published to the host.
MONGODB_HOST      = os.getenv("MONGODB_HOST", "localhost")
MONGODB_PORT      = int(os.getenv("MONGODB_PORT", "27017"))
MONGODB_DATABASE  = os.getenv("MONGODB_DATABASE", "PaintomicsDB")

# ========== MULTI-THREADING OPTIONS ==========
# Concurrency comes from threads only. src/common/PySiQ.py keeps the job queue
# in process memory, so uWSGI must run processes = 1; a second process would
# get its own empty queue and silently drop jobs.
MAX_THREADS      = int(os.getenv("MAX_THREADS", "6"))
MAX_WAIT_THREADS = 900                                                 # seconds
N_WORKERS        = int(os.getenv("N_WORKERS", "4"))

# ========== CACHE SIZES ==========
JOB_CACHE_MAX_SIZE  = 50
KEGG_CACHE_MAX_SIZE = 25

# ========== DOWNLOAD SETTINGS ==========
DOWNLOAD_DELAY_1 = 2
DOWNLOAD_DELAY_2 = 2
MAX_TRIES_1 = 3
MAX_TRIES_2 = 5

# ========== EMAIL CONFIGURATION (SMTP) ==========
# Registration and password-reset mail. With SMTP_PASSWORD unset, account
# activation email cannot be delivered and new users cannot complete signup.
EMAIL_PROVIDER      = "smtp"
EMAIL_FROM_ADDRESS  = os.getenv("EMAIL_FROM_ADDRESS", "noreply@example.org")
EMAIL_FROM_DISPLAY  = os.getenv("EMAIL_FROM_DISPLAY", "PaintOmics")
SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT           = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME       = os.getenv("SMTP_USERNAME", "apikey")             # SendGrid expects the literal "apikey"
SMTP_PASSWORD       = os.getenv("SMTP_PASSWORD", "")                   # SECRET: the SendGrid API key
SMTP_USE_TLS        = True

# Backwards compatibility for legacy SMTP-based imports
smpt_sender      = EMAIL_FROM_ADDRESS
smpt_sender_name = EMAIL_FROM_DISPLAY

# ========== WEB-FACING CONSTANTS ==========
# PAINTOMICS_BASE_URL must be the externally reachable URL; it is embedded in
# activation links sent by email, so localhost breaks registration in production.
PAINTOMICS_BASE_URL     = os.getenv("PAINTOMICS_BASE_URL", "http://localhost:8000").rstrip("/")
PAINTOMICS_LOGO_PATH    = os.getenv("PAINTOMICS_LOGO_PATH", "/resources/images/paintomics_white_300x66")
PAINTOMICS_LOGO_URL     = f"{PAINTOMICS_BASE_URL}{PAINTOMICS_LOGO_PATH}"
PAINTOMICS_LOGIN_URL    = os.getenv("PAINTOMICS_LOGIN_URL", f"{PAINTOMICS_BASE_URL}/")
PAINTOMICS_DOCS_URL     = os.getenv("PAINTOMICS_DOCS_URL", "https://paintomics.readthedocs.io/en/latest/")
PAINTOMICS_EMAIL_DOMAIN = os.getenv(
    "PAINTOMICS_EMAIL_DOMAIN",
    urlparse(PAINTOMICS_BASE_URL).netloc or "example.org"
)
EMAIL_REPORT_RECIPIENTS = [
    email.strip()
    for email in os.getenv("EMAIL_REPORT_RECIPIENTS", "").split(",")
    if email.strip()
]

# ========== AI INTERPRETATION ==========
AI_INTERPRETATION_ENABLED = os.getenv("AI_INTERPRETATION_ENABLED", "true").lower() == "true"

# Provider used by src/classes/AIInterpret/. "csic" is the deployment default:
# a free OpenAI-compatible vLLM gateway run by IIIA-CSIC. Tokens are
# self-service from https://console.llm.iiia.es (CSIC SSO).
AI_LLM_PROVIDER = os.getenv("AI_LLM_PROVIDER", "csic")
AI_PROVIDERS = {
    "csic": {
        "api_base": os.getenv("AI_CSIC_API_BASE", "https://llm.iiia.es/v1"),
        "api_key": os.getenv("AI_CSIC_API_KEY", ""),                   # SECRET
        # Pin a dated snapshot rather than the "default/llm" alias: the service
        # asks scientific users to name an explicit model for reproducibility,
        # and an alias can be repointed under a running deployment.
        "model": os.getenv("AI_CSIC_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731"),
    },
    "dashscope": {
        "api_base": os.getenv("AI_DASHSCOPE_API_BASE", "https://coding-intl.dashscope.aliyuncs.com/v1"),
        "api_key": os.getenv("AI_DASHSCOPE_API_KEY", ""),              # SECRET
        "model": os.getenv("AI_DASHSCOPE_MODEL", "qwen3.5-plus"),
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("AI_OPENROUTER_API_KEY", ""),             # SECRET
        "model": os.getenv("AI_OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
    },
}

# PubMed (NCBI E-utilities): 10 req/s with a key, 3 without.
AI_PUBMED_EMAIL   = os.getenv("AI_PUBMED_EMAIL", "")
AI_PUBMED_API_KEY = os.getenv("AI_PUBMED_API_KEY", "")                 # SECRET

# Pipeline
AI_MAX_PATHWAYS = 15
AI_PATHWAYS_PER_BATCH = 5
AI_PAPERS_PER_PATHWAY = 5
AI_TEMPERATURE = 0.3
AI_MAX_CONCURRENT_PIPELINES = 2

# Full-text fetching & verification
AI_MAX_SECTION_CHARS = int(os.getenv("AI_MAX_SECTION_CHARS", "12000"))
AI_MAX_VERIFICATION_ITERATIONS = int(os.getenv("AI_MAX_VERIFICATION_ITERATIONS", "3"))
AI_VERIFICATION_FUZZY_THRESHOLD = float(os.getenv("AI_VERIFICATION_FUZZY_THRESHOLD", "0.75"))
AI_VERIFICATION_PROVIDER = os.getenv("AI_VERIFICATION_PROVIDER", "")
AI_EUROPEPMC_DELAY = float(os.getenv("AI_EUROPEPMC_DELAY", "0.2"))

# Phase 1: Triage
AI_MAJOR_PATHWAY_MIN_OMICS = int(os.getenv("AI_MAJOR_PATHWAY_MIN_OMICS", "2"))
AI_MAJOR_PATHWAY_MAX_PVAL = float(os.getenv("AI_MAJOR_PATHWAY_MAX_PVAL", "0.05"))

# Phase 2: Search Planner
AI_MAX_SEARCH_TASKS = int(os.getenv("AI_MAX_SEARCH_TASKS", "12"))
AI_SEARCH_SUBAGENT_WORKERS = int(os.getenv("AI_SEARCH_SUBAGENT_WORKERS", "4"))
# Citations are verified one sub-agent call each and are independent, so they
# run concurrently. Same default as the search workers, so the pipeline never
# issues more parallel LLM calls than it already did.
AI_VERIFICATION_WORKERS = int(os.getenv("AI_VERIFICATION_WORKERS", "4"))
AI_PAPERS_PER_SEARCH_TASK = int(os.getenv("AI_PAPERS_PER_SEARCH_TASK", "5"))
AI_PAPERS_KEPT_PER_TASK = int(os.getenv("AI_PAPERS_KEPT_PER_TASK", "3"))
AI_SEARCH_PLANNER_TEMPERATURE = float(os.getenv("AI_SEARCH_PLANNER_TEMPERATURE", "0.4"))
AI_SEARCH_SUBAGENT_TEMPERATURE = float(os.getenv("AI_SEARCH_SUBAGENT_TEMPERATURE", "0.2"))

# ========== MORE BACKEND ==========
# Absolute path to `more-rs`, the Rust port of MORE's PLS1 kernel. It takes the
# same arguments as runMORE.R and was measured against it on the bundled
# 06-regulatory-more example: six of the seven output files byte-identical, the
# seventh (the rpc table) holding the same rows in a different order.
#
# Blank -- the default -- sends every job to `Rscript runMORE.R`. The image
# carries no binary at this path unless one is mounted in, and the port covers
# PLS1 only, so MLR jobs go to R regardless. See MOREServlet._resolveMOREBackend.
MORE_RS_BINARY = os.getenv("PAINTOMICS_MORE_RS", "")
