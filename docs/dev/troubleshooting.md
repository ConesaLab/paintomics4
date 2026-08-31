# Troubleshooting

Each entry is a symptom somebody actually hit, what was really going on, and
what to do. Claims that come only from operator experience and are not enforced
anywhere in the code are marked as such.

## Your fix has no effect

**Symptom.** You edit something under `PaintomicsServer/src/`, exercise it
against the already-running development server, and see the old behaviour. The
fix looks wrong.

**Cause.** `launch_server.py` runs with debug mode on, but its reloader does not
reliably pick changes up. You are testing a stale process. *(From operator
experience; not enforced by code.)*

**What to do.** Restart before testing, every time:

```bash
kill $(lsof -ti:8000); sleep 3
cd PaintomicsServer && nohup python src/launch_server.py > /tmp/server.log 2>&1 &
sleep 12
```

This failure mode is dangerous because it fails in the direction of "looks
fine": a path-traversal fix once kept returning `/etc/hosts` to a tester who had
not restarted, and was correctly refused the moment the server was restarted.

## Everything says "not authorised" after a restart

**Symptom.** An action that worked a minute ago now fails with an
authorisation-shaped error, for a user who is plainly logged in.

**Cause.** `UserSessionManager` holds `logged_users` as a plain dict on its
singleton. There is no session collection in MongoDB. Restarting the process
invalidates every live session, but the browser still holds its `userID` and
`sessionToken` cookies, so the request looks authenticated to the user and fails
`isValidUser` on the server.

**What to do.** Reload and log in again after any restart. Do not diagnose it as
a permissions bug. It also means a live session cannot be borrowed from Mongo to
drive an authenticated endpoint from a script — the token exists only in the
running process.

## `ReferenceError: <function> is not defined`, for a function that exists

**Symptom.** The browser console reports a missing function that is plainly
present in the source. A hard reload makes it go away, so it never reproduces in
development.

**Cause.** Versioned client assets are served with a long max-age on purpose. If
you change a JS or CSS file and do not bump its `?v=` marker in
`PaintomicsClient/public_html/index.html`, returning browsers keep the old file
and run it against new view code. This has broken the results page and Step 4's
pathway details panel.

**What to do.** Bump the marker. Confirm the diagnosis from the page console by
comparing byte lengths:

```js
fetch(url).then(r => r.text()).then(t => console.log('cached', t.length))
fetch(url, {cache: 'no-store'}).then(r => r.text()).then(t => console.log('fresh', t.length))
```

`src/tests/test_versioned_assets_are_bumped.py` now fails the suite on this, so
it should not recur silently. Note that a file loaded through `Ext.Loader`
rather than a `<script>` tag in `index.html` is *not* cache-busted and needs no
bump — a server restart is enough for those.

## Identifier mapping hangs in production but is fast locally

**Symptom.** Every job stalls in the mapping step on the deployed instance,
while the same code is quick on a development machine.

**Cause.** The production MongoDB is 4.4. It does not use the compound index for
an `$in` against an array variable inside a `$lookup` sub-pipeline; MongoDB 8.x
does. Workers sit inside `db.xref.aggregate`, each batch scanning a
million-document collection.

**What to do.** Prefer plain indexed finds over aggregation for anything on this
path — the two-find form measured about nine times faster than the aggregation
on 4.4, with identical results and ordering. Measure query-shaped changes
against the production MongoDB version before deploying, not only locally. To
confirm a live hang, take a `py-spy dump` of the worker process.

## The regression harness fails on datasets your change cannot touch

Two different causes, and they need opposite responses.

**Last-digit float differences, spread across many datasets.** That is the
environment, not the code. `tests/baseline/` is compared exactly, so a different
NumPy/SciPy build is a different summation order. `scripts/regression.sh`
defaults `PYTHON` to plain `python3` and nothing in the harness records or
checks an interpreter version. Set `PYTHON` explicitly to the pinned 3.11
interpreter and re-run before reverting anything.

**A field you added appearing everywhere.** An additive output change is still a
diff, and the pull-request gate only samples five of the twelve datasets. Before
rewriting any baseline, classify every difference — `ADDED` / `REMOVED` /
`VALUE CHANGE` / `TYPE CHANGE` / `LIST LENGTH`. Additive-only means stale;
anything else is a regression hiding behind one. Regenerate by deleting the
dataset's directory: `--write-baseline` only creates missing baselines and never
overwrites.

Two harness traps worth knowing in a fresh worktree: `regression.sh` aborts up
front if the reference GTF or the `more-rs` binary is missing, even for a
dataset that needs neither; and the GTF must be **copied**, not symlinked,
because `ExampleDatasets.absolutePath` rejects a path that resolves outside the
example directory.

## `master` is green and every pull request is red

**Cause.** `cd.yml`, which runs on push to `master`, has two jobs: build the
artifact, and bring up an ephemeral staging stack. The tests are all in
`pr.yml`, which triggers on `pull_request` only. Nothing re-runs them after a
merge.

**What to do.** Judge `master` by the last pull request's checks or by
dispatching `nightly.yml`. See [ci.md](ci.md).

## A species reinstall refuses, or silently loses data

**Symptom.** The "install must never lose files" guard refuses a reinstall,
naming a file the download does not contain. Alternatively, an install reports
SUCCESS and the species loses generated data.

**Cause.** Several files are *build products* that live only in `current/` and
that no download ever supplies — hub data, the pathway network JSON, and the
Reactome and MapMan version and mapping files. Promotion moves `download/` into
place over `current/`.

**What to do.** Do not exempt the file the guard names in order to get past it.
That turns a refusal into silent data loss: one such exemption archived the
installed tree and promoted one without hub data, losing about 1,869 files while
logging SUCCESS. Check what the guard was protecting the file *from*, and test
any change by running the promotion and counting files on the far side.

## A test's direct edit to a job document has no effect

**Cause.** `JobInformationManager.loadJobInstance` serves a bounded in-process
cache. A job document edited directly in MongoDB while the server is running
still answers from the cache, and deleting the document does not evict it
either.

**What to do.** Never edit a job in place or reuse a job ID across test runs.
Insert a clone under a fresh, never-used job ID with the flags baked in at
insert time. Real application flows mutate through the same cached instance, so
cache and database stay coherent in production — the guards this appears to
break are correct.

## A configured secret is empty in the running process

**Cause.** An ignored configuration key looks configured. uWSGI has no
`env-file` option and silently ignores unknown ini keys, so an `env-file =` line
delivered nothing for months while reading as working configuration.

**What to do.** Never trust an ini key you have not seen in `uwsgi --help`.
Check what the process actually has:

```bash
sudo cat /proc/$(pgrep -f uwsgi | head -1)/environ | tr '\0' '\n' | grep -c '^SMTP_'
```

## The whole site becomes unresponsive while AI jobs run

**Cause.** One uWSGI process with four threads serves every API request. A route
that waits inline on the LLM gateway holds one of those threads for the duration
— measured around two minutes per non-streamed attempt. Three concurrent callers
leave one thread for the entire site; four is an outage.

**What to do.** Never wait on an LLM, an external API or a long computation
inside a request. Enqueue into the shared queue, return a ticket, and let the
browser poll; poll requests are milliseconds and hold nothing. Cap how many such
jobs may be in flight, because that queue is shared with pathway analysis.

## A deploy reported success but the site runs old code

Three separate causes, all of which report success:

- The export came from a feature branch rather than `origin/master`, so files
  you did not touch stayed behind.
- The restart never happened, because the privileged command never received its
  password. `is-active` was still `active`, because it always was.
- Server code changed and no restart was attempted at all.

See [deployment.md](deployment.md) for the checks that catch each.

## Parallel work in this repository

Worktrees share one git index and one object store with every other session
working in the same repository. A commit made from one worktree while another
session has staged files can pick up work that is not yours. *(From operator
experience; not enforced by code.)*

Run `git status --branch --short` before every commit in a worktree, use a fresh
worktree per branch, and prefer reproducing a reported bug from a worktree cut
from `origin/master` rather than from whatever the main checkout happens to be
on.

A worktree also has no `.env`, so an instance launched from one runs with the AI
features disabled and looks like a build where the feature is missing rather
than one where the key is absent.
