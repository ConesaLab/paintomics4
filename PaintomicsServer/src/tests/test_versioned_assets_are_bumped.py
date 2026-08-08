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
    "app/view/common/Util.js": (
        "0.9", "74aad1f469002e0156982c36a543cc00028220b3495816c0e4ed5658c2b0eea3"),
    "app/view/common/ExtJS_extensions.js": (
        "0.6", "61a72e40803dd468f8b4af54c58a41cfc84224bf1a678a4dfee9666065a9eb1e"),
    "app/view/common/upload/Panel.js": (
        "0.1", "a8ae097ac622998d42c020fa8045fc4b15900ce17da065f80971bd0349daf93b"),
    "app/view/PathwayAcquisitionViews/PA_AIInterpretView.js": (
        "0.1", "083079e3da1338e0fed065f544d6136cdf73392255fd6b45ef6f1c3b18f82308"),
    "app/view/PathwayAcquisitionViews/PA_Step3RegTargetNetworkView.js": (
        "0.1", "f9b31d697a708f72074f605350ea488efe4faa3d610d90d8a0dfec18d271070c"),
    "js/libs/linkurious/sigma.min.js": ("0.1", None),
    "js/libs/linkurious/plugins.js": ("0.2", None),
    "app.js": ("0.1", None),
}

_SRC = re.compile(r'src="([^"]+?)\?v=([0-9.]+)"')


def _digest(relativePath):
    with open(os.path.join(CLIENT_ROOT, relativePath), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _markersInIndex():
    with open(INDEX_HTML, "r", encoding="utf-8", errors="replace") as handle:
        return dict(_SRC.findall(handle.read()))


class VersionedAssetTest(unittest.TestCase):

    def setUp(self):
        if not os.path.isfile(INDEX_HTML):
            self.skipTest("client tree not present at %s" % CLIENT_ROOT)
        self.markers = _markersInIndex()

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
        with open(os.path.join(CLIENT_ROOT, "app/view/common/Util.js"),
                  "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()

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
