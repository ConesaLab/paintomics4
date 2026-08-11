#!/usr/bin/env python3
"""Package the bundled examples as one download, with their provenance.

Why this exists
---------------
"Load example" has been manifest-driven since `ExampleDatasets` replaced the
hardcoded bundle, but the "Download example data" button beside it still served
`resources/paintomics_example_data.zip` -- a static archive built in 2017. It
held twelve files from one retired dataset and matched **none** of the eleven
scenarios the picker offers: a user who loaded `gene-single-condition` and then
downloaded "the example data" got a different experiment, with no file of the
same name. Nothing regenerated that zip when the datasets changed, because
nothing knew it existed.

So the download is built from the same manifest the picker reads. What you can
run, you can download, and the two cannot drift apart because there is only one
list.

The archive also answers a question the datasets themselves never did. Seven of
the eleven scenarios are simulated, each README said so in one word --
`simulated | yes` -- and nowhere said *how*: what "signal" means, how big it is,
why some background features are called relevant too. `HOW-THIS-DATA-WAS-MADE.md`
is generated into the archive root and says all of it, with the numbers read out
of the generator rather than retyped here (see `_simulationParameters`).

Layout
------
Members keep their manifest-relative paths -- `datasets/01-.../data/x.tab` --
rather than being re-filed under a per-scenario folder. Three reasons: the
READMEs and the manifest already refer to files by exactly those paths, one file
is genuinely shared (`stategra-mirna` reads `08-stategra-multiomics`'s gene
expression matrix, and a per-scenario layout would ship two copies that a user
has no way to know are identical), and the archive then unzips into something
that looks like the tree the server serves.

Cost
----
The complete bundle is ~41 MB of text before compression, most of it one 32 MB
miRBase mapping table. Building it costs a few seconds, so it is built once and
cached on disk under a fingerprint of everything that went into it; a request
that finds a fresh archive serves it without touching the datasets at all.
`zipfile.write` streams each member, so peak memory stays flat regardless of
how large the tree grows.

Failure policy matches `ExampleDatasets`: a scenario whose files are absent is
not offered and not shipped, and a single member too large to be worth sending
is skipped and *named in the document* rather than silently dropped.
"""
import hashlib
import json
import logging
import os
import tempfile
import threading
import zipfile

from src.common import ExampleDatasets


# Bumped when the archive's layout or the generated document changes shape, so
# a cached archive built by an older server is not served by a newer one -- the
# fingerprint would otherwise match, since no input file changed.
FORMAT_VERSION = 1

BUNDLE_STEM = "paintomics_example_data"

DOCUMENT_NAME = "HOW-THIS-DATA-WAS-MADE.md"

# A declared file larger than this is described in the document instead of
# being shipped. The one file this can reach is `GTF/sorted_mmu.gtf`, which
# `stategra-regions` needs: a sorted mouse GTF is a few hundred megabytes, a
# fresh checkout does not have it at all, and a deployment that does should not
# turn a click on "Download example data" into a half-gigabyte transfer. Every
# file actually under `datasets/` is far below this -- the largest is 32 MB.
MAX_MEMBER_BYTES = 64 * 1024 * 1024

_buildLock = threading.Lock()


def _simulationParameters():
    """The generator's own constants, or None when it is not importable.

    Read from `simulate` rather than restated here because a document that
    quotes an effect size the generator no longer uses is worse than one that
    omits it: it is confidently wrong, and nothing would catch it.
    `test_example_bundle` asserts these values reach the rendered document, so
    changing a constant and not the prose cannot pass silently.

    The import is defensive because `AdminTools` is a developer tool: it builds
    the datasets, it is not needed to serve them, and a deploy image is entitled
    to omit it. `simulate` itself imports only `math`, so when it is present
    this costs nothing worth measuring.
    """
    try:
        from src.AdminTools.scripts.exampledata import simulate
    except Exception as error:                        # pragma: no cover
        logging.info("EXAMPLE BUNDLE - generator constants unavailable (%s); "
                     "the provenance document will describe the method "
                     "without them", error)
        return None

    return {
        "effectSize": simulate.DEFAULT_EFFECT_SIZE,
        "noise": simulate.DEFAULT_NOISE,
        "signalFraction": simulate.DEFAULT_SIGNAL_FRACTION,
        "downFraction": simulate.DEFAULT_DOWN_FRACTION,
        "diffuseRate": simulate.DEFAULT_DIFFUSE_RATE,
        "diffuseEffectSize": simulate.DIFFUSE_EFFECT_SIZE,
    }


# ---------------------------------------------------------------------------
# What goes in
# ---------------------------------------------------------------------------

def _scenarioFolders(scenario):
    """The `datasets/<NN-folder>` prefixes a scenario draws files from.

    Usually one. `stategra-mirna` has two, because it reads its target matrix
    out of `08-stategra-multiomics`, and shipping that scenario without the
    folder its data came from would produce an archive whose own README refers
    to a path that is not in it.
    """
    folders = []
    for path in ExampleDatasets.declaredFiles(scenario):
        parts = str(path).split("/")
        if len(parts) < 3:
            continue
        prefix = "/".join(parts[:2])
        if prefix not in folders:
            folders.append(prefix)
    return folders


def _companionFiles(exampleFilesDir, folder):
    """A folder's README and its `expected/` files, as manifest-relative paths.

    `expected/` is included deliberately. It is small -- 0.1 MB across all
    eleven scenarios -- and it is the part that makes a simulated dataset
    checkable rather than merely described: `signal_features.txt` is the list of
    features the generator planted, so a reader can confirm that what the
    document claims about the signal is what the files contain.
    """
    found = []
    for relative in (folder + "/README.md",):
        if os.path.isfile(ExampleDatasets.absolutePath(exampleFilesDir, relative)):
            found.append(relative)

    expectedDir = ExampleDatasets.absolutePath(exampleFilesDir, folder + "/expected")
    if os.path.isdir(expectedDir):
        for name in sorted(os.listdir(expectedDir)):
            relative = folder + "/expected/" + name
            if os.path.isfile(ExampleDatasets.absolutePath(exampleFilesDir, relative)):
                found.append(relative)
    return found


def collectMembers(exampleFilesDir, scenarios):
    """`(members, skipped)` for a set of scenarios.

    `members` is a sorted list of manifest-relative paths, deduplicated so a
    file two scenarios share is stored once. `skipped` pairs a path with the
    reason it was left out, which the document prints -- an archive that
    silently omits a declared file teaches the wrong thing about the dataset.
    """
    wanted = []
    seen = set()

    def offer(relative):
        if relative not in seen:
            seen.add(relative)
            wanted.append(relative)

    offer(ExampleDatasets.MANIFEST_NAME.replace(os.sep, "/"))

    for scenario in scenarios:
        for relative in ExampleDatasets.declaredFiles(scenario):
            offer(relative)
        for folder in _scenarioFolders(scenario):
            for relative in _companionFiles(exampleFilesDir, folder):
                offer(relative)

    members, skipped = [], []
    for relative in sorted(wanted):
        try:
            absolute = ExampleDatasets.absolutePath(exampleFilesDir, relative)
        except ExampleDatasets.UnknownScenario as error:
            skipped.append((relative, str(error)))
            continue

        if not os.path.isfile(absolute):
            skipped.append((relative, "not present on this server"))
            continue

        size = os.path.getsize(absolute)
        if size > MAX_MEMBER_BYTES:
            skipped.append((relative, "%.0f MB, too large to bundle; fetch it "
                                      "from the server it was installed from"
                                      % (size / 1e6)))
            continue

        members.append((relative, absolute, size))
    return members, skipped


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

def _formatExpected(expected):
    lines = []
    for key in sorted(expected):
        value = expected[key]
        if isinstance(value, dict):
            value = ", ".join("%s: %s" % (k, value[k]) for k in sorted(value))
        elif isinstance(value, list):
            value = "[%s]" % ", ".join(str(item) for item in value)
        lines.append("* **%s** — %s" % (key, value))
    return lines


def renderDocument(exampleFilesDir, scenarios, members, skipped):
    """`HOW-THIS-DATA-WAS-MADE.md`, generated from the manifest.

    Written at build time rather than committed as a file so it cannot describe
    a dataset the server is not actually shipping: it lists the scenarios that
    passed the same availability check the picker uses, on this host.
    """
    manifest = ExampleDatasets.loadManifest(exampleFilesDir)
    parameters = _simulationParameters()
    simulated = [s for s in scenarios if s.get("simulated")]
    real = [s for s in scenarios if not s.get("simulated")]
    totalBytes = sum(size for _, _, size in members)

    out = []
    add = out.append

    add("# PaintOmics example data")
    add("")
    add("Every example this server can run, exactly as it ships them: "
        "**%d dataset%s, %d file%s, %.1f MB** uncompressed."
        % (len(scenarios), "" if len(scenarios) == 1 else "s",
           len(members), "" if len(members) == 1 else "s", totalBytes / 1e6))
    add("")
    add("This archive is generated from `datasets/manifest.json`, which is the "
        "same list \"Load example\" reads. If a dataset is in the picker it is "
        "in here, and the files are the ones the job would have used.")
    add("")
    add("## How to use it")
    add("")
    add("Each dataset lives in its own numbered folder. The files you upload "
        "are the ones under `data/`; each folder's `README.md` says which file "
        "is which omic, and `expected/` records what the analysis should "
        "produce. `manifest.json` is the machine-readable version of all of it.")
    add("")
    add("You do not need this archive to try PaintOmics -- **Load example** "
        "runs any of these without a download. It is here for reading the "
        "files, re-uploading them as your own, and checking what the numbers "
        "are before you trust them.")
    add("")

    # -- the question the datasets never answered -------------------------
    add("## Which of these are simulated")
    add("")
    add("| dataset | data | pipeline | organism |")
    add("| --- | --- | --- | --- |")
    for scenario in scenarios:
        add("| `%s` | %s | %s | %s |"
            % (scenario.get("id"),
               "simulated" if scenario.get("simulated") else "real measurements",
               scenario.get("pipeline", "?"), scenario.get("organism", "?")))
    add("")

    if real:
        add("The %d real dataset%s carr%s no planted signal of any kind. %s "
            "come from the published STATegra mouse Ikaros time course "
            "(GEO GSE75417); they are the reference the simulated ones are "
            "shaped against, and nothing in this project rewrites a byte of "
            "them."
            % (len(real), "" if len(real) == 1 else "s",
               "ies" if len(real) == 1 else "y",
               "It" if len(real) == 1 else "They"))
        add("")

    # -- how the simulation works -----------------------------------------
    if simulated:
        add("## How the simulated data was made")
        add("")
        add("Generated by `%s`, seeded with `%s`. Every scenario draws from its "
            "own random stream, seeded from that number and a checksum of the "
            "scenario id, so regenerating at the same seed reproduces the files "
            "byte for byte -- an empty diff is a real result, not a "
            "coincidence."
            % (manifest.get("generator", "src/AdminTools/scripts/exampledata"),
               manifest.get("seed", "?")))
        add("")
        add("The model is **a planted pathway signal against a quiet "
            "background**:")
        add("")
        if parameters:
            add("1. A handful of KEGG pathways are chosen as *targets*. They are "
                "drawn from the pathways whose genes are mostly not also "
                "somebody else's, because planting a signal in a hub pathway "
                "marks a large slice of every pathway that shares genes with "
                "it -- measured, that made 57% of all pathways come back "
                "significant, which is a fixture that cannot discriminate.")
            add("2. **%.0f%%** of each target pathway's members carry the "
                "signal. Not all of them: a relevant-features list identical to "
                "the pathway definition is a test that cannot fail."
                % (parameters["signalFraction"] * 100))
            add("3. A signal feature moves by **%s log2 units** at the last "
                "condition and half that at the first, so a time course shows "
                "a gradient rather than a flat block. **%.0f%%** of them move "
                "down, because real perturbations do both."
                % (parameters["effectSize"], parameters["downFraction"] * 100))
            add("4. Everything else is background: Gaussian noise with standard "
                "deviation **%s**, centred on zero."
                % (parameters["noise"],))
            add("5. **%.0f%%** of background features are *also* called "
                "relevant, moving by **%s** log2 units in no shared direction. "
                "This is the least obvious part and the most important: without "
                "it the only relevant features in the submission are the "
                "planted ones, the enrichment background becomes the planted "
                "signal itself, and every pathway sharing a gene with a target "
                "looks enriched. Real differential expression is never confined "
                "to one program."
                % (parameters["diffuseRate"] * 100,
                   parameters["diffuseEffectSize"]))
        else:
            add("1. A handful of peripheral KEGG pathways are chosen as targets.")
            add("2. A fraction of each target's members carry the signal.")
            add("3. Signal features ramp across conditions, in both directions.")
            add("4. Everything else is Gaussian background noise centred on zero.")
            add("5. A small fraction of background features are also called "
                "relevant, so the enrichment background is not the planted "
                "signal itself.")
            add("")
            add("(The generator was not importable on this server, so the "
                "exact constants are not quoted here. They are the module "
                "constants in `%s/simulate.py`.)"
                % manifest.get("generator", "src/AdminTools/scripts/exampledata"))
        add("")
        add("MORE's simulated scenario is built differently, because MORE reads "
            "per-sample matrices rather than ratios: each regulator gets an "
            "independent mean per experimental group, and each target is a "
            "noisy linear function of one regulator. The pairing is therefore "
            "known, which is what lets `expected/` record which regulator "
            "really drives which target. Regulators drawn from a shared profile "
            "would be near-collinear and the true driver would be "
            "indistinguishable from its decoys.")
        add("")
        add("No cell is ever blank. PaintOmics rejects `NA`, `NaN` and empty "
            "cells at upload, so an example containing them would teach a "
            "format the application refuses.")
        add("")

    # -- per dataset -------------------------------------------------------
    add("## The datasets")
    add("")
    for scenario in scenarios:
        add("### %s" % scenario.get("title", scenario.get("id")))
        add("")
        add("`%s` — %s" % (scenario.get("id"),
                           "simulated" if scenario.get("simulated")
                           else "real measurements"))
        add("")
        if scenario.get("summary"):
            add(scenario["summary"])
            add("")
        files = ExampleDatasets.declaredFiles(scenario)
        if files:
            add("Files:")
            for path in files:
                add("* `%s`" % path)
            add("")
        expected = scenario.get("expected") or {}
        if expected:
            add("Expected result:")
            out.extend(_formatExpected(expected))
            add("")

    if skipped:
        add("## Not included")
        add("")
        add("These files are part of a dataset above but are not in this "
            "archive:")
        add("")
        for path, reason in skipped:
            add("* `%s` — %s" % (path, reason))
        add("")

    add("---")
    add("")
    add("Generated by the server that served it, from "
        "`datasets/manifest.json` (version %s, KEGG snapshot `%s`). Do not edit "
        "by hand -- it is rebuilt whenever the datasets change."
        % (manifest.get("version"), manifest.get("keggVersion", "unknown")))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Building and caching
# ---------------------------------------------------------------------------

def _fingerprint(scenarioId, members):
    """A digest of everything that decides the archive's bytes.

    Size and mtime rather than content: hashing 41 MB on every request to
    discover that nothing changed would cost more than serving the file.
    """
    digest = hashlib.sha256()
    digest.update(("v%d|%s|" % (FORMAT_VERSION, scenarioId or "")).encode("utf-8"))
    for relative, absolute, size in members:
        try:
            mtime = os.stat(absolute).st_mtime_ns
        except OSError:
            mtime = 0
        digest.update(("%s|%d|%d|" % (relative, size, mtime)).encode("utf-8"))
    return digest.hexdigest()[:16]


def _cacheDirectory():
    return tempfile.gettempdir()


def _archiveName(selector, fingerprint):
    """`<stem>-<selector>-<fingerprint>.zip`, with a literal selector for "all".

    The selector is in the name rather than folded into the digest so that
    `_discardStaleArchives` can tell "an older build of this same selection"
    from "a different selection, still current". Without that distinction the
    four selections in use -- everything, plus one per converter page -- would
    each delete the other three on build and rebuild on every request.
    """
    return "%s-%s-%s.zip" % (BUNDLE_STEM, selector or "all", fingerprint)


def _discardStaleArchives(keep):
    """Drop earlier builds *of the same selection*; a regeneration orphans one.

    Matched on the selector prefix, so the complete bundle and a pipeline's
    bundle coexist and only a superseded fingerprint is removed.
    """
    directory = _cacheDirectory()
    basename = os.path.basename(keep)
    prefix = basename.rsplit("-", 1)[0] + "-"
    try:
        names = os.listdir(directory)
    except OSError:                                    # pragma: no cover
        return
    for name in names:
        if not name.startswith(prefix) or not name.endswith(".zip"):
            continue
        if name == basename:
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError:                                # pragma: no cover
            pass


def scenariosFor(exampleFilesDir, scenarioId=None, pipeline=None):
    """The scenarios a bundle covers: one by id, one pipeline's, or all of them.

    A named scenario is resolved through `getScenario`, so an unknown id raises
    `UnknownScenario` naming the valid ones -- the same message the rest of
    example mode produces -- rather than quietly returning an empty archive.

    `pipeline` exists because the same stale-download defect appears on three
    pages, not one: the miRNA2Genes and BED-to-genes converters each have their
    own "Download example data" button beside their own "Load example", and
    what each of those should hand over is that entry point's datasets. An
    unknown pipeline name is refused for the same reason an unknown id is --
    an empty archive looks like a server with no examples installed.
    """
    if scenarioId:
        return [ExampleDatasets.getScenario(exampleFilesDir, scenarioId)]

    available = ExampleDatasets.listScenarios(exampleFilesDir, pipeline=pipeline)
    if pipeline and not available:
        known = sorted({entry.get("pipeline") for entry
                        in ExampleDatasets.listScenarios(exampleFilesDir)
                        if entry.get("pipeline")})
        raise ExampleDatasets.UnknownScenario(
            "There are no example datasets for a '%s' analysis on this server. "
            "Available: %s." % (pipeline, ", ".join(known) or "none"))
    return available


def downloadName(scenarioId=None, pipeline=None):
    if scenarioId:
        return "%s_%s.zip" % (BUNDLE_STEM, scenarioId)
    if pipeline:
        return "%s_%s.zip" % (BUNDLE_STEM, pipeline)
    return "%s.zip" % BUNDLE_STEM


def buildBundle(exampleFilesDir, destination, scenarioId=None, pipeline=None):
    """Write the archive to `destination`; returns a summary of what went in.

    Built into a temporary file beside the destination and moved into place, so
    a second request arriving mid-build either finds no archive or finds a
    complete one -- never a truncated zip, which a browser would happily save.
    """
    scenarios = scenariosFor(exampleFilesDir, scenarioId, pipeline)
    members, skipped = collectMembers(exampleFilesDir, scenarios)
    document = renderDocument(exampleFilesDir, scenarios, members, skipped)

    root = BUNDLE_STEM
    directory = os.path.dirname(os.path.abspath(destination))
    handle, temporary = tempfile.mkstemp(suffix=".zip.part", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as archive:
            archive.writestr(root + "/" + DOCUMENT_NAME, document)
            for relative, absolute, _ in members:
                archive.write(absolute, root + "/" + relative)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:                                # pragma: no cover
            pass
        raise

    logging.info("EXAMPLE BUNDLE - built %s: %d scenario(s), %d file(s), "
                 "%d skipped, %.1f MB compressed", destination, len(scenarios),
                 len(members), len(skipped), os.path.getsize(destination) / 1e6)
    return {"scenarios": [s.get("id") for s in scenarios],
            "members": len(members), "skipped": skipped,
            "bytes": os.path.getsize(destination)}


def bundleFor(exampleFilesDir, scenarioId=None, pipeline=None):
    """Path to a current archive, building it only when there is not one.

    The fingerprint is recomputed per request -- it is a `stat` per member, not
    a read -- so a developer who regenerates the datasets gets a fresh archive
    without restarting the server, which is the same promise `loadManifest`
    makes about the catalogue.
    """
    scenarios = scenariosFor(exampleFilesDir, scenarioId, pipeline)
    members, _ = collectMembers(exampleFilesDir, scenarios)
    selector = scenarioId or pipeline
    path = os.path.join(_cacheDirectory(),
                        _archiveName(selector, _fingerprint(selector, members)))
    if os.path.isfile(path):
        return path

    with _buildLock:
        # Re-checked under the lock: two requests arriving together would
        # otherwise both build the same archive.
        if not os.path.isfile(path):
            buildBundle(exampleFilesDir, path, scenarioId, pipeline)
            _discardStaleArchives(path)
    return path
