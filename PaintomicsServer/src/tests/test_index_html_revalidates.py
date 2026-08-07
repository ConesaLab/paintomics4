#!/usr/bin/env python3
"""index.html must not be served from cache without revalidating.

Every other client asset is cache-busted by hand, with a version marker bumped
in index.html when the file changes:

    <script src="app/view/common/Util.js?v=0.7"></script>

That scheme has one requirement, and it is not written down anywhere: the file
carrying the markers must itself be fetched fresh. `send_from_directory` applies
Flask's `SEND_FILE_MAX_AGE_DEFAULT`, which is 12 hours, so index.html was served
with `Cache-Control: public, max-age=43200` like any other static file. A
browser that had loaded the site in the previous 12 hours therefore kept the old
index.html, which still asked for `Util.js?v=0.1` -- a URL it also still had
cached. The version bump changed nothing for exactly the users who had been
there before.

This is not hypothetical. The results page was observed blank after the
frontend work landed, with:

    ReferenceError: truncatableTextRenderer is not defined
        at PA_Step3HubAnalysis.initComponent (PA_Step3Views.js:4910)

`truncatableTextRenderer` is defined in Util.js and was added by that work. The
browser held index.html from before it, so it loaded the pre-change Util.js
against the post-change PA_Step3Views.js, and step 3 rendered nothing at all. A
hard reload fixed it instantly, which is the signature of this bug and also the
reason it survives testing: developers hard-reload constantly.

`no-cache` does not mean "do not store" -- the browser may still keep the file,
it just has to revalidate before using it. The ETag `send_from_directory`
already sets then makes the usual response a 304, so the cost is one
conditional request per page load, not a re-download.

Versioned assets deliberately keep their long max-age. Making them
uncacheable would defeat the point of versioning them.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_index_html_revalidates
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.paintomicsserver import revalidateEntryDocument


class FakeResponse(object):
    """Just the header mapping; that is the whole surface under test."""

    def __init__(self, headers=None):
        self.headers = dict(headers or {})


class EntryDocumentRevalidationTest(unittest.TestCase):

    def test_the_entry_document_is_marked_no_cache(self):
        response = revalidateEntryDocument(FakeResponse())

        self.assertIn("no-cache", response.headers.get("Cache-Control", ""),
                      "index.html may be served from cache without revalidating, "
                      "so a version bump cannot reach a returning browser")

    def test_a_stale_max_age_is_replaced_not_appended(self):
        """Flask has already set max-age by the time this runs."""
        response = revalidateEntryDocument(
            FakeResponse({"Cache-Control": "public, max-age=43200"}))

        cacheControl = response.headers.get("Cache-Control", "")
        self.assertNotIn("max-age=43200", cacheControl,
                         "the 12-hour max-age survived alongside no-cache; "
                         "browsers may honour whichever they see first")
        self.assertIn("no-cache", cacheControl)

    def test_an_expires_date_in_the_future_is_cleared(self):
        """Expires is the HTTP/1.0 spelling of the same instruction."""
        response = revalidateEntryDocument(
            FakeResponse({"Cache-Control": "public, max-age=43200",
                          "Expires": "Sat, 08 Aug 2026 11:09:40 GMT"}))

        self.assertIn(response.headers.get("Expires", ""), ("", "0"),
                      "Expires still names a future date, which an HTTP/1.0 "
                      "cache will honour in preference to Cache-Control")

    def test_the_response_object_is_returned(self):
        """after_request handlers must return the response, not None."""
        response = FakeResponse()

        self.assertIs(revalidateEntryDocument(response), response)


class VersionMarkerTest(unittest.TestCase):
    """The markers only work if they are actually bumped, so check they moved."""

    def _indexHtml(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "..", "..", "PaintomicsClient",
                            "public_html", "index.html")
        if not os.path.isfile(path):
            self.skipTest("client checkout not present next to the server")
        with open(path) as handle:
            return handle.read()

    def test_util_js_is_requested_with_a_version_marker(self):
        """The file whose missing function blanked the results page."""
        markup = self._indexHtml()

        self.assertIn("Util.js?v=", markup,
                      "Util.js is requested without a version marker, so a "
                      "change to it cannot be pushed to a returning browser")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
