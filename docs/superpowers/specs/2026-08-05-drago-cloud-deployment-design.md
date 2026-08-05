# PaintOmics 4 — Drago Cloud release deployment

**Date:** 2026-08-05
**Target:** Drago Cloud VM `tliu-vm1` (CSIC OpenStack) as the new public production instance
**Status:** Design approved for implementation

---

## 1. Decisions

| Question | Decision |
|---|---|
| Role of the Drago instance | New public production; `paintomics.uv.es` eventually retires |
| Packaging | Docker Compose (pinned images, reproducible, trivial rollback) |
| Data | Fresh install — empty `PaintomicsDB`, KEGG data re-downloaded on the VM |
| AI Interpretation | Enabled, backed by the CSIC LLM gateway |
| Hostname | Bare IP initially; DNS + Let's Encrypt as a parallel workstream |
| Security group | Opened by the operator via the Drago Cloud web console |

---

## 2. Survey of the current state

### 2.1 Git

Repository `github.com/ConesaLab/paintomics4`.

- On `dev` @ `3f70ee0c`, **3 ahead / 24 behind `master`**. Local `master` is 1 ahead of `origin/master`.
- **Zero tags** — the project has never cut a versioned release.
- Uncommitted: 5 modified tracked files + 1 untracked test.

### 2.2 The UV production server

`paintomics.uv.es` (147.156.158.21), user `tian`, app at `/home/tian/paintomics/paintomics4/`.

Stack inferred from `paintomics4.ini`: uWSGI, `processes=1 threads=4`, `lazy-apps=true`, Unix socket
`/tmp/paintomics.sock`, `harakiri=300`, secrets injected via `env-file = /etc/paintomics/paintomics.env`.

SSH port 22 times out from outside the UV network, so this could not be inspected live. It is treated
as a *reference design*, not a migration source — the fresh-install decision makes live access
non-blocking.

### 2.3 The Drago Cloud VM

Reached as `ssh dragocloud-vm` (161.111.18.82, port **25222**, user `tliu`, key `~/.ssh/id_ed25519_drago`).

| Property | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS |
| System Python | 3.12.3 |
| CPU / RAM | 8 vCPU / 30 GB |
| Root disk | 80 GB (`/dev/vda`), 74 GB free — flavor-provided, fully allocated, no unpartitioned space |
| **Data volume** | **600 GiB Cinder volume `paintomics-data`** on `/dev/vdb`, ext4, 590 GB usable, mounted at `/var/lib/docker` (provisioned 2026-08-05, see §2.3.1) |
| Installed | *Nothing relevant* — no nginx, apache, MongoDB, conda, uv, Docker, podman, R, uWSGI |
| Listening | `25222` (SSH) only |
| External reachability | 25222 open; **80, 443, 8000 closed** |
| Host firewall | `ufw` **inactive** — the block is the OpenStack **security group**, not the host |
| Privileges | `sudo` NOPASSWD confirmed |
| Outbound | `apt` and HTTPS to github.com / pypi.org all work |
| Managed agents | `fail2ban` and `sophos-spl` running (CSIC image) |

`drago.csic.es` is a *separate* CSIC SLURM HPC cluster, reachable only by ProxyJump through this VM.
It is not a web-hosting target and plays no part in this deployment.

### 2.3.1 Storage — the 80 GB root disk was never the limit

The instance's 80 GB root disk comes from its flavor and is fully allocated: no LVM, no unpartitioned
space, no unattached volumes. It reads as a hard 74 GB ceiling from inside the VM.

The OpenStack console tells a different story. Project `project-i2sysbio-geg` (domain `dragocloud`,
console `https://cloud.rstools.csic.es`) holds these quotas:

| Resource | Used | Quota |
|---|---|---|
| Instances | 1 | 10 |
| VCPUs | 8 | 20 |
| RAM | 31.2 GB | 50 GB |
| Volumes | 1 | 10 |
| Volume snapshots | 0 | 10 |
| **Block storage** | **600 GiB** | **1000 GiB** |
| Floating IPs | 1 | 50 |
| Security groups | 1 | 10 |
| Security group rules | 6 | 100 |

**A full terabyte of Cinder block storage sat unused.** 600 GiB of it was provisioned on 2026-08-05,
with the remaining 400 GiB left free on purpose:

- Volume `paintomics-data`, **600 GiB**, type `__DEFAULT__` (the only type Drago offers — no SSD/HDD
  tiering, so there is nothing to gain from splitting the database onto a separate volume), AZ `nova`.
- Attached to `tliu-vm1` as `/dev/vdb`; ext4 with `-m 0` to reclaim the 5% root reserve (~30 GiB).
- Mounted at **`/var/lib/docker`** via `/etc/fstab` by UUID with `nofail`, so a detached volume
  cannot block boot. `findmnt --verify` passes.
- Done *before* Docker was installed, so no data migration was required.

Every Compose named volume — `kegg_data`, `client_tmp`, `mongo_data` — plus images and build cache
therefore land on this volume. **Usable space: 590 GB.** The root disk keeps its 74 GB for the OS
alone.

**400 GiB of quota is deliberately left unallocated** for other work in this tenant. That also
restores snapshot capability, since `卷快照` draws from the same pool — a pre-upgrade Cinder snapshot
is possible, though routine backups remain file-level (`mongodump`) per §10 and the runbook.

**Consequence for §7: disk is no longer a constraint on species coverage.** Full 94-species parity
(~219 GB) fits nearly three times over. The remaining limit on species count is KEGG's download
rate, not storage.

> **Cinder volumes extend but never shrink** — the Horizon action menu offers 扩展卷 with no
> counterpart. Growing this volume later is a live operation: extend in the console, then
> `sudo resize2fs /dev/vdb`. Shrinking would mean destroy-and-recreate plus a full restore, so treat
> the 600 GiB figure as a floor that is cheap to raise and expensive to lower.

### 2.3.2 Compute is already maxed — unlike storage

The 20 vCPU / 50 GB project quota looks like headroom over the instance's 8 vCPU / 32 GB. It is not.
That quota is a **project-wide ceiling across all instances**, and the flavor list available to
`project-i2sysbio-geg` is:

| Flavor | vCPU | RAM | Root disk |
|---|---|---|---|
| `small` / `medium` / `large` | — | smaller | — |
| `extralarge` | 8 | 8 GB | 80 GB |
| `extralarge_argis16G` | 8 | 16 GB | 80 GB |
| **`extralarge_argis32G`** *(current)* | **8** | **32 GB** | 80 GB |

**Every available flavor caps at 8 vCPU, and the instance already runs the one with the most RAM.**
A resize could only shrink it. The unused 12 vCPU / 19 GB is reachable only by launching additional
instances (quota permits 10), not by growing `tliu-vm1`.

Additional instances do **not** help PaintOmics scale: `PySiQ` keeps job state in process memory
(§3.2), so the application cannot be spread across machines any more than across processes without
replacing the queue with a shared broker — explicitly out of scope (§11). The legitimate use for the
spare quota is a **staging instance** for rehearsing upgrades — and with 400 GiB of volume quota now
left free (§2.3.1), such an instance could have a real data volume rather than being confined to its
80 GB root disk.

A larger custom flavor could be requested via GLPI, but it would not pay off today: with
`processes = 1` the application does not saturate the 8 vCPU it already has. RAM, not CPU, is the
resource that constrains it — it feeds the MongoDB working set and the `JOB_CACHE_MAX_SIZE` /
`KEGG_CACHE_MAX_SIZE` caches.

### 2.4 The CSIC key

The key supplied by the operator (`sk-zxHt…`, redacted — see §5.1) belongs to the **Servicio de LLMs
del CSIC** account (`llm@csic.es`), approved 10 July 2026; service evaluated with Jesús Cerquides
(IIIA-CSIC).

The service lives on **`llm.iiia.es`** (161.111.18.39) — an IIIA-CSIC domain, *not* under `csic.es`,
which is why every `*.csic.es` DNS probe returned NXDOMAIN. Recovered from the approval email of
10 July 2026 and Jesús Cerquides' introduction of 30 June 2026:

| | |
|---|---|
| Console | `https://console.llm.iiia.es` (CSIC SSO — "Usuarios CSIC" button) |
| API base | **`https://llm.iiia.es/v1`** |
| Auth | `Authorization: Bearer <token>` |
| Backend | vLLM 0.26.0 |
| Cost | **Free** for CSIC users on Área de Cálculo Científico hardware |

**Verified live against the gateway on 2026-08-05** with the operator's token:

| Check | Result |
|---|---|
| `GET /v1/models` | HTTP 200 |
| `POST /v1/chat/completions` | HTTP 200 on all three chat models |
| **Tool / function calling** | ✅ well-formed `tool_calls` from Qwen3.6-27B and DeepSeek-V4-Flash-0731 |
| **JSON mode** (`response_format`) | ✅ valid JSON returned |

Available models: `Qwen/Qwen3.6-27B`, `deepseek-ai/DeepSeek-V4-Flash`,
`deepseek-ai/DeepSeek-V4-Flash-0731`, `default/llm` (alias), plus embeddings
`Qwen/Qwen3-Embedding-8B` and `default/emb`.

Tool calling and JSON mode were the two capabilities that could have broken the multi-agent
`AIInterpret` pipeline. Both work, and `llm_client.py` already speaks generic
`POST {api_base}/chat/completions` — so adoption is **pure configuration, no code change**.

**Model choice is constrained by the service's own guidance:** for scientific use it requires
pinning an explicit model rather than the `default/llm` alias, for reproducibility. This design
selects **`deepseek-ai/DeepSeek-V4-Flash-0731`** — the dated snapshot is the only identifier that
cannot silently drift under a running instance, which matters for a tool whose output is cited in
publications. `Qwen/Qwen3.6-27B` is the fallback if quality testing favours it.

### 2.5 Runtime dependency profile

Established by reading the source, not by assumption:

- **No Redis, no RQ.** `Queue` resolves to the vendored `src/common/PySiQ.py`, an in-process
  thread-pool queue. This is load-bearing for the architecture (see §3.2).
- **R is required.** *(Corrected 2026-08-05. This section previously claimed nothing in `src/`
  invokes `Rscript` and that the `r-base` install in `install_paintomics.sh` was dead weight
  inherited from PaintOmics 3. Both statements were wrong: the earlier survey grepped for
  `rpy2` and for `Rscript` in Python source, and missed the `.R` files invoked by path.)*

  `PathwayAcquisitionJob.py` shells out to two R scripts on the **user-facing request path**:
  `:1358` runs `src/common/bioscripts/generateMetaGenes.R` (needs `amap`, `cluster`,
  `factoextra`, `mclust`) and `:1709` runs `src/common/bioscripts/hubAnalysis.R` (needs
  `purrr`). `common_build_database.py:1520` runs `AdminTools/scripts/processReactomeData.R`
  during the database build, and `AdminTools/scripts/hubAnalysisInstall.R` pulls in ten more
  packages including the Bioconductor pair `KEGGgraph` and `AnnotationDbi`.

  The `r-base` line in `install_paintomics.sh` is therefore load-bearing, and the deployment
  image must reproduce it. Omitting R yields an image that serves pages correctly and then
  fails only when a user requests Hub Analysis or Metagenes — a failure mode that would very
  likely have survived smoke testing and reached production.
- **Python ≤ 3.9.** Pinned `Flask 1.1.2`, `Werkzeug 1.0.1`, `Jinja2 2.11.2`, `MarkupSafe 1.1.1`
  do not import on 3.10+. The local conda env is 3.9.23.
- **Flask serves the client itself.** `paintomicsserver.py` routes `/` and `/<path:filename>` through
  `send_from_directory` into `PaintomicsClient/public_html`. There is no separate static-hosting tier
  to reproduce.
- **`requests` is imported but pinned in neither requirements file.**

---

## 3. Architecture

### 3.1 Topology

```
                    Internet
                       │
              :80/:443 │            ← security-group rules to be added
                       ▼
        ┌──────────────────────────┐
        │  nginx:alpine            │   TLS termination
        │  client_max_body_size    │   100m  (= SERVER_MAX_CONTENT_LENGTH)
        │  proxy_read_timeout 300s │   (= harakiri)
        └───────────┬──────────────┘
                    │ HTTP, internal network
                    ▼
        ┌──────────────────────────┐        ┌────────────────────┐
        │  app                     │        │  mongo:7           │
        │  python:3.9-slim + uWSGI │◄──────►│  PaintomicsDB      │
        │  processes=1 threads=6   │        │  NOT published     │
        │  lazy-apps=true          │        │  to the host       │
        └───────────┬──────────────┘        └─────────┬──────────┘
                    │                                 │
         ┌──────────┴───────────┐                     │
         ▼                      ▼                     ▼
    kegg_data (vol)      client_tmp (vol)      mongo_data (vol)
```

### 3.2 Why `processes = 1` is mandatory

`PySiQ.Queue` holds job state in Python memory inside the worker process. Running uWSGI with
`processes > 1` gives each worker a private queue: a job enqueued by worker A is invisible to
worker B, so status polls hit the wrong worker and appear to hang or report a job that does not
exist. Concurrency must come from **threads** (`MAX_THREADS=6`, `N_WORKERS=4` in `serverconf.py`),
never from processes. This matches what the UV production `paintomics4.ini` already does and is not
a limitation introduced here.

Horizontal scaling would require replacing `PySiQ` with a shared broker. That is explicitly out of
scope for this release.

### 3.3 Components

| Unit | Responsibility | Interface | Depends on |
|---|---|---|---|
| `nginx.conf` | TLS, body-size ceiling, timeouts, proxy | `:80`, `:443` → `app:8000` | app |
| `Dockerfile` | Reproducible Python 3.9 runtime + Cairo native libs | image | requirements lock |
| `compose.yaml` | Service wiring, volumes, env injection, restart policy | `docker compose` CLI | all |
| `mongo-init.js` | Idempotent DB + collections + indexes + admin user | `docker-entrypoint-initdb.d` | mongo |
| `/etc/paintomics/paintomics.env` | All secrets and per-host config | `env_file` | operator |

---

## 4. Release-blocking defects

These are pre-existing problems that a public release cannot ship with. Each must be resolved in
Phase 0, before the VM is touched.

### B1 — A live API key is committed to git

`PaintomicsServer/src/conf/serverconf.py` is **tracked**, and line 100 carries

```python
"api_key": os.getenv("AI_DASHSCOPE_API_KEY", "sk-sp-26f8…"),   # full key redacted here
```

as a hardcoded fallback default, introduced in commit `24dc08f1`. The full value is recoverable from
`git show 24dc08f1` — this document deliberately does not restate it. Two distinct faults: a secret is in
public history, and per-host configuration is version-controlled at all — `docs/0_install.md`
documents `serverconf.py` as a *local copy* of `example_serverconf.py`.

**Fix:** rotate the Dashscope key; `git rm --cached` the file; add it to `.gitignore`; delete every
hardcoded key default so a missing env var fails loudly instead of silently using someone else's
quota. `launch_server.py:7` already auto-creates the file from the template on first launch, so
nothing breaks operationally.

History rewriting is *not* proposed — the key is rotated, and rewriting shared history on a
multi-contributor lab repository costs more than it buys.

### B2 — The config template is stale

`example_serverconf.py` is missing all **23 `AI_*`** and **4 `EMAIL_*`** settings present in the live
config. A fresh install — which is exactly what this deployment is — would boot with no AI
configuration at all. Must be regenerated from the live file with secrets replaced by empty defaults.

### B3 — Two requirements files disagree

| Package | root `requirements.txt` | `PaintomicsServer/src/requirements.txt` |
|---|---|---|
| `Pillow` | 10.3.0 | **8.0.1** (known CVEs) |
| `CairoSVG` | 2.7.0 | 2.4.2 |
| `patsy` | unpinned | 0.5.1 |
| `statsmodels` | unpinned | 0.12.0 |

Plus `requests` is used by `DBManager.py` and `downloadReactome.py` but pinned in neither.

**Fix:** collapse to a single authoritative lock file; take the newer of each pair; pin `requests`.

### B4 — MongoDB version is capped by an old driver

`pymongo==3.11.0` supports MongoDB up to 4.4, which reached end-of-life in February 2024. Shipping an
EOL database on a public instance is not acceptable.

The bump is cheap. An audit of every call site shows the **entire request path already uses the
modern API** (`insert_one`, `update_one`, `count_documents`). Only two admin scripts use removed
pymongo 3 methods:

- `src/AdminTools/scripts/clean_databases.py` — `.remove()` at lines 169, 171, 173 → `delete_many()`
- `src/AdminTools/DBManager.py:1029` — `acceptedIDs.count()` → `count_documents()`

**Fix:** bump to `pymongo>=4.6`, patch those two files, run `mongo:7`.

### B5 — The bootstrap script cannot run on modern MongoDB

`src/conf/install_paintomics.sh` invokes the legacy `mongo` shell (removed in MongoDB 6) and
`ensureIndex()` (removed in MongoDB 5). It also assumes a `paintomics3-mongo` host and pulls a
prebuilt tarball from `bioinfo.cipf.es` (now a 302 redirect of unverified content).

**Fix:** replace with a `mongo-init.js` mounted into `docker-entrypoint-initdb.d/`, using
`createIndex()`. The Mongo entrypoint runs it exactly once on an empty data directory, which removes
the manual bootstrap step entirely.

### B6 — No release branch, no tags

`dev` is 24 commits behind `master`. The repository has never been tagged.

**Fix:** merge `master` → `dev`, resolve, verify the test suite, then cut `v4.0.0` — the project's
first version tag.

### B7 — Install documentation is obsolete

`docs/0_install.md` documents a Python 2 era `apt-get` + `sudo pip install` procedure against
packages that no longer exist in Ubuntu 24.04, and clones `fikipollo/paintomics3`. It must be
rewritten around the Compose deployment.

---

## 5. Configuration and secrets

A single root-owned `0600` file at `/etc/paintomics/paintomics.env`, injected by Compose `env_file`.
This mirrors the pattern `paintomics4.ini` already uses on UV, so it is a known-good shape for this
codebase.

```ini
# --- Web ---
PAINTOMICS_BASE_URL=https://161.111.18.82
PAINTOMICS_EMAIL_DOMAIN=paintomics.csic.es

# --- Mongo ---
MONGODB_HOST=mongo
MONGODB_PORT=27017
MONGODB_DATABASE=PaintomicsDB

# --- Data ---
PAINTOMICS_CLIENT_TMP=/data/CLIENT_TMP
PAINTOMICS_KEGG_DATA=/data/KEGG_DATA

# --- Email ---
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=<rotated SendGrid key>

# --- AI Interpretation ---
AI_INTERPRETATION_ENABLED=true
AI_LLM_PROVIDER=csic
AI_CSIC_API_BASE=https://llm.iiia.es/v1
AI_CSIC_API_KEY=<rotated CSIC token>
# Explicit model, never the default/llm alias — the service requires pinning
# for scientific reproducibility. Dated snapshot cannot drift under us.
AI_CSIC_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731
AI_PUBMED_EMAIL=paintomics4@gmail.com
AI_PUBMED_API_KEY=<NCBI key — raises PubMed 3/s to 10/s>
```

`serverconf.py` gains a third provider entry:

```python
"csic": {
    "api_base": os.getenv("AI_CSIC_API_BASE", ""),
    "api_key":  os.getenv("AI_CSIC_API_KEY", ""),
    "model":    os.getenv("AI_CSIC_MODEL", ""),
},
```

### 5.1 Key rotation

Both keys must be rotated as part of this release:

- **Dashscope `sk-sp-26f8…`** — present in public git history (`git show 24dc08f1`).
- **CSIC `sk-zxHt…`** — has passed through a chat transcript and the operator's shell history.
  Request a replacement from `llm@csic.es` in the same message that asks for the endpoint.

Neither key is written out in full anywhere in this repository, including this document. Retrieve
them from the operator's password manager or from git history when performing the rotation.

An `AI_PUBMED_API_KEY` should also be obtained; without it the pipeline is throttled to 3 requests/s
against NCBI, and `AI_SEARCH_SUBAGENT_WORKERS=4` will contend for that budget.

---

## 6. Network and TLS

### 6.1 Security group

Two ingress rules to add in the Drago Cloud console, and one existing rule to preserve:

| Direction | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| Ingress | TCP | 80 | 0.0.0.0/0 | HTTP → redirect to HTTPS; ACME HTTP-01 later |
| Ingress | TCP | 443 | 0.0.0.0/0 | HTTPS |
| Ingress | TCP | 25222 | *(existing)* | SSH — do not remove |

Port 8000 stays closed; the app is only reachable through nginx. MongoDB is never published to the
host at all, so no rule and no host-level exposure.

`ufw` is inactive and should stay that way — the security group is the single enforcement point, and
two overlapping firewalls is a reliable way to produce a confusing outage.

### 6.2 TLS on a bare IP — accepted risk and mitigation

Serving public production over plain HTTP on `http://161.111.18.82` would put every login password
and every uploaded omics dataset on the wire in cleartext. Registration, password reset and job data
are all in scope.

The deployment therefore ships nginx **TLS-ready with a self-signed certificate**, so the transport
is encrypted from day one. Browsers will show an interstitial warning; that is a usability cost, not
a confidentiality one.

A DNS name is a prerequisite for a trusted certificate and should be pursued in parallel, starting
now rather than after launch. Once a hostname resolves to 161.111.18.82, switching to Let's Encrypt
is a certbot invocation plus a `server_name` change — the nginx layer is structured so nothing else
moves. **Recommendation: do not publicly announce the instance until a trusted certificate is in
place.**

---

## 7. Data bootstrap

Fresh install, no migration from UV.

1. `mongo-init.js` runs automatically on first `mongo:7` start: creates `PaintomicsDB`, the eight
   collections, the indexes, the counter document, and the `admin` user.
2. KEGG data is fetched **on the VM** with `DBManager.py download --specie=<code> --kegg=1 --mapping=1`.

`rest.kegg.jp` was verified reachable (HTTP 200). `bioinfo.cipf.es` — the source of the legacy
prebuilt tarball — now answers 302 and is not trusted as a bootstrap source.

**Timing.** `DBManager` fetches one KGML *and* one PNG per pathway, serialised behind
`DOWNLOAD_DELAY_1 = 2` seconds. At ~350 pathways per organism this is **hours per species**, not
minutes. Consequences for the plan:

- Choose the launch species list deliberately; do not download everything.
- Run the download under `tmux`/`nohup`, never in a foreground SSH session.
- Budget it as its own phase with its own elapsed-time expectation.

**Sizing.** Measured from the local reference copy: shared data (`common` 1.4 GB + `reactome` 856 MB
+ `mapman` 1.3 MB) ≈ 2.3 GB, plus **≈2.3 GB per species** (for `mmu`: 2.0 GB of `mapping/` tables,
181 MB Reactome, 109 MB hub data, 18 MB across 364 KGML files).

| Species served | Disk |
|---|---|
| 1 | 4.6 GB |
| 10 | 25 GB |
| 94 (full parity) | ~219 GB |

Against the 590 GB volume (§2.3.1), even full parity uses just over a third. **Storage does not
constrain the species list; download time does.**

Note the local `species.json` advertises **94 species while only `mmu` is actually present** on the
workstation — the manifest is decoupled from the data. Whatever list the release ships must be
matched by real downloads, or the UI will offer species that 404.

`CLIENT_TMP` grows with usage — 200 MB quota per user, 90-day guest retention, 365-day job
retention. Disk alerting remains a post-launch operational task, but with 590 GB the urgency is low.

---

## 8. Rollout phases

| Phase | Work | Touches VM |
|---|---|---|
| **0** | Repo hygiene: B1–B7 | No |
| **1** | Author `Dockerfile`, `compose.yaml`, `nginx.conf`, `mongo-init.js`; verify the whole stack locally | No |
| **2** | Provision: Docker Engine, `/etc/paintomics/`, volumes; operator opens 80/443 | Yes |
| **3** | Deploy stack; KEGG bootstrap for the chosen species (long-running) | Yes |
| **4** | End-to-end smoke test: register → upload → pathway acquisition → AI interpretation | Yes |
| **5** | Tag `v4.0.0`; rewrite `docs/0_install.md`; DNS + Let's Encrypt cutover | Yes |

Phases 0 and 1 are the critical path and require no Drago access, so they can begin immediately.
The security-group request (Phase 2) and the `llm@csic.es` enquiry (§5.1) both have external
lead time and should be initiated on day one, in parallel with Phase 0.

---

## 9. Testing and verification

- **Phase 1 (local).** Full stack under Compose on the workstation. Register a user, upload the
  existing example dataset, run pathway acquisition, confirm KEGG images render and the job queue
  completes. This validates the container topology before any VM work.
- **Regression.** The repo already carries a synthetic 3-condition end-to-end pipeline test
  (commit `85fcd921`) and a `--assert-baseline` count harness (`991bcc77`). Both run inside the app
  container in Phase 1 and gate the release.
- **Phase 4 (production).** The same journey against the deployed instance, plus one AI
  interpretation run to confirm the CSIC gateway path end to end.
- **Negative checks.** From outside the CSIC network: port 8000 refuses, MongoDB is unreachable, and
  HTTP redirects to HTTPS.

---

## 10. Failure modes and handling

| Failure | Handling |
|---|---|
| CSIC gateway unavailable or model retired | The service is a *prototype* on shared CSIC hardware with no stated SLA, and `DeepSeek-V4-Flash-0731` may be withdrawn. `AI_INTERPRETATION_ENABLED=false` degrades gracefully — the core platform is unaffected. Re-check `GET /v1/models` before each release. |
| Gateway rate limits unknown | Not published, and `AI_SEARCH_SUBAGENT_WORKERS=4` issues concurrent calls. Watch for 429s during Phase 4 and lower the worker count if they appear. |
| KEGG download interrupted | `DBManager` writes a `DOWNLOADING` sentinel; re-running resumes. Run under `tmux`. |
| uWSGI `harakiri` kills a long job | `harakiri=300` matches UV. Long jobs run in PySiQ threads, not the request; only the *poll* is bounded. |
| Security group request delayed | Phases 0–1 are unblocked. Validate on the VM through an SSH tunnel to port 8000 in the meantime. |
| `mongo:7` incompatibility missed by the audit | Roll back to `mongo:4.4` by image tag; Compose makes this a one-line revert. |
| Disk exhaustion from `CLIENT_TMP` | Existing `clean_databases.py` and `cleanup_orphaned_data.py` scheduled via cron; add a disk alert. |

---

## 11. Out of scope

- Migrating users, jobs or `CLIENT_TMP` from `paintomics.uv.es`.
- Decommissioning the UV instance.
- Replacing `PySiQ` with a shared broker to allow multi-process scaling.
- Rewriting git history to expunge the leaked Dashscope key (rotation instead).
- Any use of the `drago.csic.es` HPC cluster.

---

## 12. Outstanding inputs

| Input | Source | Blocks |
|---|---|---|
| ~~CSIC LLM `api_base` + model ID~~ | ✅ **Resolved 2026-08-05** — `https://llm.iiia.es/v1`, `deepseek-ai/DeepSeek-V4-Flash-0731`, verified live | — |
| Rotated CSIC token | `console.llm.iiia.es` (self-service) or `llm@csic.es` | Phase 3 config |
| Rotated Dashscope key | Alibaba console | Phase 0 (B1) |
| NCBI PubMed API key | NCBI account | Optional; raises rate limit |
| Launch species list | Project decision | Phase 3 duration |
| DNS name | CSIC IT | Trusted TLS, Phase 5 |
| Security group 80/443 | Drago Cloud console | Phase 2 |

None of these block Phases 0–2.

## 13. Prior engagement with CSIC IT

This deployment is not a cold start. A **"Paintomics 4 in Drago"** engagement already ran with the
Área de Informática Científica: Ana Conesa initiated it on 29 April 2026, a kickoff meeting was held
**12 May 2026** with Fernando Royo and Daniel Rodríguez López (GLPI #0007335, #0007425, both
resolved), and the Drago Cloud tenant was granted through GLPI #0007588 (resolved 17 June 2026).

Consequences for this plan:

- **`soporteaic@csic.es` is the established support channel**, tracked through GLPI. Requests
  reference a ticket number and reach an assigned técnico — use it for the security-group change
  rather than an untracked email.
- **User documentation:** `https://docaic.rstools.csic.es/es/home` (Spanish; some pages require an
  account). It covers cloud operations and is the authority on security-group management.
- GLPI **#0007968** records an earlier problem reaching the Drago *user console* — the CSIC VPN does
  not route to the Drago network. Expect the same obstacle when opening ports 80/443, and budget
  time for it rather than assuming console access works first try.
- A Drago **quota** notice (`[DRAGO] tliu revise su cuota`) recurs weekly, and GLPI #0008615 (5 Aug
  2026) is an open request covering quota. Confirm the cloud tenant quota covers a long-running
  3-container workload plus ~5 GB of KEGG data before Phase 3.
