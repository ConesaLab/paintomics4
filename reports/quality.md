# Code quality: refactor-base vs refactor/baseline

Both trees measured with the same tools on the same machine (ruff 0.14.13,
vulture 2.16, radon 6, Python 3.11 venv). "before" is the tag `refactor-base`
(master `10b2de8d`); "after" is `8d867bf0` (branch `refactor/baseline`, PR #79).
The numbers are reproducible from the two checkouts; nothing here is an
estimate.

## Static checks (PaintomicsServer/src unless stated)

| metric | before | after | note |
|---|---:|---:|---|
| ruff gate `E9,F63,F7,F82` (the PR lint job) | 61 | **0** | 59 were `AdminTools/scripts/cache.py`, a fragment that never imported; 1 a `NameError` in `AdminServlet.adminServletRestoreData`; 1 in `Util.py` |
| pyflakes, all `F` rules | 428 | **267** | |
| `F401` unused import | 134 | 59 | remaining ones are `keep`/`uncertain` rows in `reports/deadcode.md` (re-exports, names read by tests as `module.NAME`, star-import consumers) |
| `F841` unused local | 65 | 39 | |
| `F821` undefined name | 60 | **0** | the two latent `NameError`s are fixed, the rest left with `cache.py` |
| vulture candidates, ≥60 % confidence | 413 | 382 | every remaining candidate has a verdict row in `reports/deadcode.md` |
| vulture candidates, ≥80 % confidence | 23 | 16 | |
| radon maintainability index, mean over 202 non-test modules | 70.2 (A 192 / B 5 / C 5) | 70.3 (A 192 / B 4 / C 6) | flat — see below |
| radon cyclomatic complexity, average per block | 5.82 (1,514 blocks) | 5.99 (1,474 blocks) | 40 trivial blocks removed, one larger mapper function added |
| `git diff --numstat refactor-base..HEAD -- PaintomicsServer/src` | | 62 files, +308 / −690 | |

What moved and what did not: the pass removed code that no test, no
regression run and no reference index could reach (154 `delete` rows,
every one listed with its evidence in `reports/deadcode.md`), and fixed the
errors the gate now enforces. It did not restructure modules, so the
complexity and maintainability indices are essentially unchanged — the
slight rise in average complexity is arithmetic (the deleted blocks were
the trivial ones; `FeatureNamesToKeggIDsMapper` gained
`findIDsByFeaturesNameForDatabases`, which shares one first-hop query
across the target databases instead of repeating it).

Statement coverage of the non-test source under the unit suites plus the
full regression, measured for the dead-code report: 52.7 % (11,966 of
22,716 statements, 144 files). Deleting unreachable code can only raise
that figure, so it is not re-reported as an improvement.

## Behaviour guards that now exist and pass

| guard | result | evidence |
|---|---|---|
| `scripts/regression.sh` at `8d867bf0`, 11 example datasets, exact floats against `tests/baseline/` | **11/11 passed**, zero diffs | local run 2026-08-22; CI nightly run 32534251104 (11/11 on the runner) |
| `tests/perf/large_input` (20k Ensembl genes, 5k UniProt, 400 compounds × 6 conditions) through `refactor-base` and `HEAD`, normalised like the regression | step1 / step2 / step3 artifacts **byte-identical** (same sha256), 0 differences over 1,005 pathways, 54,172 value ids, 17,437 painted values | `scripts/perf` kernel, both checkouts, same MongoDB |
| PR workflow on the pull_request event at `8d867bf0` | lint 15 s, fixtures 2 m 56 s, 233 unit suites 8 m 21 s — **green in 8 m 25 s** | run 32554073972 |
| unit suites | 229 pass, 4 inherited failures present at `refactor-base` too, 0 introduced | `scripts/ci/run_suites.py` classification against the baseline |
| browser, branch server from this checkout on port 8011 | STATegra 5-omic example end to end: 1,007 pathways / 114 significant (KEGG 364/71, OmniPath 120/10, Reactome 523/33); painted *Cytokine-cytokine receptor interaction* shows DNase-seq 177 (41) p 0.072056, Gene expression 87 (48) p 1.7192e-8, miRNA-seq 75 (51) p 0.784963 — the stored baseline for dataset 08 holds exactly these values | 2026-08-22, job q2Z715i47E |

## Performance (unchanged output, see `profile-before.txt` / `profile-after.txt`)

Paired A/B on one macOS runner, medians of 3: `processFilesContent`
98.9 → 64.9 s, `parseGeneBasedFiles` 97.0 → 63.4 s,
`mapFeatureNamesToKeggIDs` 96.7 → 63.1 s of cumulative worker time (−34 %
each); cold wall clock 54.0 → 46.6 s (−13.7 %, the remainder is R).
MongoDB commands per run 3,944 → 973.
