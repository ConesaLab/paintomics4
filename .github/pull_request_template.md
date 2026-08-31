## What changed, and why

<!-- The reason matters more than the diff. If it fixes a bug, say what the bug
     did and how it was reproduced. Link the issue if there is one. -->

## How it was verified

<!-- Name what you drove and what you saw: the page, the job, the request, the
     dataset. Passing tests is not verification on its own — a UI or server
     change has to be exercised in a running instance (CLAUDE.md, section 5),
     against a restarted server. Screenshots or console output welcome. -->

- [ ] Exercised in a running instance, not only in tests

## Things that are easy to miss

- [ ] Any hand-versioned asset I edited in `PaintomicsClient/public_html/index.html`
      got its `?v=` bumped
      (`cd PaintomicsServer && python -m src.tests.test_versioned_assets_are_bumped`)
- [ ] `tests/baseline/` is unchanged, **or** the diff is explained below

<!-- If a baseline moved, say which datasets and why the new numbers are the
     correct ones. A regenerated baseline that hides a behavioural change is the
     failure mode this question exists to catch. -->

**Needs a species reinstall?** <!-- yes / no. If yes: which species, and which
DBManager.py step (download, install). -->

**Needs a new or changed config setting?** <!-- yes / no. If yes: name the
variable and say what happens on a deployment that does not set it — it has to
reach `example_serverconf.py` and `deploy/env.example` too. -->
