#!/usr/bin/env python3
"""A cache-busted asset must get a new ?v= whenever its contents change.

Why this exists
---------------
Five assets in index.html are cache-busted by hand:

    <script src="app/view/common/Util.js?v=0.8"></script>

and the server deliberately gives them a long max-age -- `revalidateEntryDocument`
says so in as many words: "Versioned assets keep their long max-age -- that is
what versioning them is for." The whole scheme rests on one manual step: bump the
number when the file changes. Nothing enforced it, and it was missed.

`1fcc5b7b` added `getClusterColor` to Util.js and left the marker at v=0.7. Every
browser that had ever loaded the site kept its cached v=0.7, which has no such
function, while getting the new PA_Step4Views.js that calls it. Step 4's pathway
details panel then threw

    ReferenceError: getClusterColor is not defined
        at PA_Step4FindFeaturesView.getClusterColor (PA_Step4Views.js:3048)
        at PA_Step3PathwayDetailsView.generatePlot (PA_Step3Views.js:3328)

so opening any pathway lost its plot. Measured in the browser, same URL, one
request with the HTTP cache and one with `cache: no-store`:

    cached: 292088 bytes, contains getClusterColor: False
    fresh:  294066 bytes, contains getClusterColor: True

A hard reload hides it, which is exactly why it survives development and only
reaches people who have used the site before -- that is, everyone except the
developer testing it in a fresh profile.

This is the second time. `revalidateEntryDocument` was written for the identical
failure with `truncatableTextRenderer`, also added to Util.js, also invisible
after a hard reload. That fix made index.html itself revalidate, which was
necessary but not sufficient: the freshly-fetched index.html still asked for
?v=0.7, so the stale Util.js stayed pinned. The remaining hole is the manual bump,
and this test closes it.

How it works: the digest of each versioned file is recorded below against the
version it was published under. Change the file and the digest stops matching,
so the test fails and tells you to bump the marker and update the entry. That is
the point -- the failure is the reminder. Updating this table without bumping
index.html defeats it, so the message says so.

Everything here is read from HEAD via `git show`, not from the working tree,
and that is a correction to how this started. Comparing the working tree meant
the test went red the moment anyone opened one of these files and stayed red
until they were finished -- which, on the client, is most of a working day. It
fired that way twice in one afternoon on edits that were still in progress. A
guard that is red while you type is one that gets ignored or deleted, and it
was never the right question anyway: the failure being prevented is a *shipped*
file whose marker did not move, and what ships is what is committed. Uncommitted
work is nobody's problem yet.

When git is unavailable or a file is not tracked, the check skips rather than
inventing a verdict.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_versioned_assets_are_bumped
"""
import hashlib
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

CLIENT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../PaintomicsClient/public_html"))
INDEX_HTML = os.path.join(CLIENT_ROOT, "index.html")

# path in index.html -> (version it is published under, sha256 of that content)
#
# A digest is carried for the application scripts, which change and are what
# break each other. The vendor libraries carry None: they change perhaps once a
# year, and recording a digest for a 300KB minified bundle only creates churn.
PUBLISHED = {
    # The upload format checker and the AI conversion agent. Recorded like any
    # other shipped script: a returning browser holds the old copy until the
    # marker changes, and a checker running against a stale validator would
    # disagree with the server it is supposed to mirror.
    "app/view/PathwayAcquisitionViews/InputFormat/format-reader.js": (
        "0.1", "0e455d115c4fc2ffe478c941ab49a757e9270a170382fd07c6896f42e8e477f1"),
    "app/view/PathwayAcquisitionViews/InputFormat/format-validator.js": (
        "0.2", "10700289348a691f3efa5743dff60de793adc97095372250ec7d179e229567d5"),
    "app/view/PathwayAcquisitionViews/InputFormat/format-repair.js": (
        "0.1", "944c929f1496258aba56f026e7c30e4affb7052dcbc127b06982eaadff205cd2"),
    "app/view/PathwayAcquisitionViews/InputFormat/format-panel.js": (
        "1.9", "7198efa3a416c7527ab58602339f97df0e81a9f532c65b19f81c23c42dc56b2f"),
    "app/view/PathwayAcquisitionViews/InputFormat/format-roles.js": (
        "0.2", "4c5afdf4f9c59d167756516db823cc1fa01179f3cd7b967d137c38a78c0508dd"),
    "app/view/PathwayAcquisitionViews/InputFormat/convert-profiler.js": (
        "0.3", "d7f2846c58226fdfe334fefc68c8d6519cc4eae393265e15dd047e5babded4f3"),
    "app/view/PathwayAcquisitionViews/InputFormat/convert-agent.js": (
        "0.6", "d884a0d8344fccf966aab1219c9c70f9e29ca93a4a42e7ddf8f0852189f5ecdd"),
    "app/view/PathwayAcquisitionViews/InputFormat/convert-drawer.js": (
        "0.7", "241e9a48b99f6ca40f3f9d3b5dd29f27513ca38c181fb902075a0149af9ca4b3"),
    "app/view/common/Util.js": (
        "2.1", "12359b8bf746394f63a7e0a15513a4f9ac82de1a25bbaa0e91e6b2fdd7e0050e"),
    "app/view/common/OrganismSearch.js": (
        "1.0", "7903626835e7703bdb6a1e31b78e3ca00539eee23b8fa67a37524cd9cc4d2e7f"),
    "app/view/common/ExtJS_extensions.js": (
        "0.7", "f1e68f670cc56064fc15649d259004ccbd96f49181ced049cffbe62c29bf1d80"),
    "app/view/common/CookieConsent.js": (
        "1.0", "e170c539dea089b0d88e090becd968d43a699aa319dbd02e681b75384a57f403"),
    "app/view/common/upload/Panel.js": (
        "0.2", "34264cdec6faef81e46d28982f348003180b2e06d0af696f815f1b5b2a7a7458"),
    # A development overlay, inert until ctrl+alt+G, and still recorded here:
    # it ships to every visitor as a script tag like any other, so a change to
    # it with an unbumped marker leaves returning browsers running the old
    # copy exactly as it would for view code.
    "app/view/common/AlignmentGuides.js": (
        "4.2", "ce2ba85063e8059eb2cc4c8e1992744854a14ad0db6f866213b8df1136650a59"),
    # v=1.3: the report fetch retries instead of dead-ending, and a job that no
    # longer exists is named as such rather than reported as "still in
    # progress".
    # v=1.5: activity-feed labels for the seven tools the agent gained
    # (figures, gene sets, differential, ordination, set comparison, gene
    # lists and measurements).
    # v=0.1: the Paper agent's tab -- consent, one progress lane per
    # specialist, the manuscript with the gate's verdict, Markdown export.
    "app/view/PathwayAcquisitionViews/PA_PaperView.js": (
        "0.2", "c6f009e3130a4fd52a00910221e29b6b5d40cdb2121d3e22d7dde7c4561d2071"),
    "app/view/PathwayAcquisitionViews/PA_AIInterpretView.js": (
        "1.5", "42b823a635ee930a9ad6aa4f6685c2c8dd0281a546e88ea896341065c74abcf7"),
    "app/view/PathwayAcquisitionViews/PA_Step3RegTargetNetworkView.js": (
        "0.7", "b135712a9564f8ae0eac94daf9c567ef275c4c748dbc270fdbdeb7d25fc79e34"),
    # OmniPath ships no diagram, so its pathways render as an interactive graph
    # rather than as boxes painted over a raster; this is that view.
    "app/view/PathwayAcquisitionViews/PA_Step4OmniPathNetworkView.js": (
        "0.1", "fbcdaeb4087e5edb65c09fa347ac22f0d001331c502fedfbd973ba9893d50e15"),
    # v=0.9 adds SERVER_URL_PA_PATHWAY_EVIDENCE. The endpoint was added at
    # v=0.8 WITHOUT a bump, which this guard caught: a returning browser keeps
    # this file for up to 12 hours, so the evidence overlay would have POSTed
    # to `undefined` for everyone who had already loaded the site.
    # v=1.0 adds AI_POLL_MAX_FAILURES. A browser keeping the old copy would
    # read it as undefined, and `failures >= undefined` is false for ever --
    # which is precisely the endless poll this release exists to stop.
    "resources/ServerConfiguration.js": (
        "1.1", "4b59bc9e2de5b92016b1c6c40b7bba8b1f5cea2be883637db78aca8e8545067c"),
    # The evidence layer itself: MORE relationships drawn on the diagram and
    # classified against KEGG, Reactome and OmniPath.
    "app/view/PathwayAcquisitionViews/PA_Step4EvidenceOverlay.js": (
        "1.6", "8d59f773c20e2b81e998c5512cba525e9d65003bd88b6c8a90086c3da1545f63"),
    "js/libs/linkurious/sigma.min.js": ("0.1", None),
    "js/libs/linkurious/plugins.js": ("0.2", None),
    # Versioned by its release rather than by a counter. A vendored library is
    # replaced wholesale at a known version, never edited in place, so the
    # upstream number is both the more informative marker and the one that
    # cannot drift from what is on disk.
    "js/libs/cytoscape/cytoscape.min.js": ("3.34.0", None),
    "app.js": ("0.3", None),
}

_SRC = re.compile(r'src="([^"]+?)\?v=([0-9.]+)"')


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_TRACKED_PREFIX = "PaintomicsClient/public_html/"


def _committed(relativePath):
    """The file as HEAD has it, or None when that cannot be determined.

    Deliberately not the working tree. This check compares content against a
    recorded digest, and a working-tree comparison fails continuously for as
    long as someone is editing one of these files -- which is most of a working
    day on the client. A guard that is red while you type is a guard that gets
    ignored, and the thing it is actually protecting against is a *shipped*
    change with an unbumped marker. What ships is what is committed.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["git", "show", "HEAD:" + _TRACKED_PREFIX + relativePath],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ImportError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _digest(relativePath):
    content = _committed(relativePath)
    if content is None:
        return None
    return hashlib.sha256(content).hexdigest()


def _markersInIndex():
    content = _committed("index.html")
    if content is None:
        return None
    return dict(_SRC.findall(content.decode("utf-8", "replace")))


class VersionedAssetTest(unittest.TestCase):

    def setUp(self):
        if not os.path.isfile(INDEX_HTML):
            self.skipTest("client tree not present at %s" % CLIENT_ROOT)
        self.markers = _markersInIndex()
        if self.markers is None:
            self.skipTest("index.html could not be read from HEAD (no git?)")

    def test_every_versioned_asset_is_recorded(self):
        """A new ?v= asset must be added to PUBLISHED or it is unguarded."""
        missing = sorted(set(self.markers) - set(PUBLISHED))

        self.assertEqual(missing, [],
                         "index.html cache-busts %s, but they are not recorded "
                         "in PUBLISHED, so a forgotten bump would go unnoticed"
                         % missing)

    def test_recorded_versions_match_index_html(self):
        for path, (version, _) in PUBLISHED.items():
            if path not in self.markers:
                continue
            self.assertEqual(
                self.markers[path], version,
                "index.html serves %s at v=%s but this test records v=%s. If "
                "you bumped the marker, update PUBLISHED (version and digest) "
                "to match." % (path, self.markers[path], version))

    def test_content_matches_the_published_version(self):
        """Every application script, pinned by digest."""
        for path, (version, expected) in sorted(PUBLISHED.items()):
            if expected is None:
                continue

            actual = _digest(path)
            if actual is None:
                continue

            self.assertEqual(
                actual, expected,
                "%s has changed since it was published as v=%s.\n"
                "Bump the marker in index.html AND update the digest here to:\n"
                "    %s\n"
                "Updating the digest alone defeats the purpose -- returning "
                "browsers keep the old file for up to 12 hours and run new "
                "code against it, which is how getClusterColor and "
                "truncatableTextRenderer both broke."
                % (path, version, actual))

    def test_every_script_tag_asset_can_be_cache_busted(self):
        """A plain <script src> with no ?v= has no lever to pull.

        Files reached through `Application.loadModule` are exempt: that is
        `$.ajax({dataType: "script"})`, and jQuery defaults `cache: false` for
        script requests, so it appends its own `?_=<epoch>` and those are always
        fresh. Confirmed in the browser -- PA_Step4Views.js arrives as
        `?_=1786198859735` while the tags below arrive as written.

        That asymmetry is the whole bug: always-fresh view code running against
        a cached script-tag file. So every script tag needs a marker, or a
        change to it is unbustable and returning users get up to 12 hours of
        the old copy.
        """
        unbustable = []
        with open(INDEX_HTML, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.search(r'src="(app/[^"?]+\.js)"', line)
                if match:
                    unbustable.append(match.group(1))

        self.assertEqual(unbustable, [],
                         "these are loaded as plain script tags with no ?v= "
                         "marker, so a change to them cannot be pushed to a "
                         "returning browser: %s" % unbustable)

    def test_the_functions_that_broke_are_present(self):
        """Cheap check that Util.js still defines what other views call.

        Independent of caching: if either disappears, the same ReferenceError
        returns for everyone, cache or no cache.
        """
        committed = _committed("app/view/common/Util.js")
        if committed is None:
            self.skipTest("Util.js could not be read from HEAD")
        source = committed.decode("utf-8", "replace")

        for name in ("getClusterColor", "truncatableTextRenderer"):
            self.assertIn("function %s" % name, source,
                          "Util.js no longer defines %s, which other views "
                          "call as a global" % name)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
