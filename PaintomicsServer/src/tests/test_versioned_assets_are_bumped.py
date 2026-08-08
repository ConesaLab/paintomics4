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
PUBLISHED = {
    "app/view/common/Util.js": (
        "0.8", "a729580e1d68dd4ba9e4955afeefbe500018de8295ffa74e1fd0438330e82b0b"),
    "app/view/common/ExtJS_extensions.js": (
        "0.6", None),
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

    def test_util_js_content_matches_its_published_version(self):
        """The file that has now broken twice, pinned by digest.

        Only Util.js carries a digest: it is the one that changes often and the
        one both incidents came from. The others are recorded so a bump
        mismatch is still caught, without churn on every unrelated edit.
        """
        version, expected = PUBLISHED["app/view/common/Util.js"]
        if expected is None:
            self.skipTest("no digest recorded")

        actual = _digest("app/view/common/Util.js")

        self.assertEqual(
            actual, expected,
            "Util.js has changed since it was published as v=%s.\n"
            "Bump the marker in index.html AND update the digest here to:\n"
            "    %s\n"
            "Updating the digest alone defeats the purpose -- returning "
            "browsers keep the old file and run new code against it, which is "
            "how getClusterColor and truncatableTextRenderer both broke."
            % (version, actual))

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
