#!/usr/bin/env python3
"""Rasterising the exported pathway image must not resolve external references.

`pathwayAcquisitionSaveImage` rasterises `request.form.get("svgCode")` -- markup
supplied verbatim by the caller -- and passed it to CairoSVG with
`unsafe=True`. That flag is not a performance hint. In cairosvg/parser.py it
turns off three protections at once:

    tree = ElementTree.fromstring(
        bytestring, forbid_entities=not unsafe,
        forbid_external=not unsafe)
    ...
    if 'url_fetcher' not in kwargs and not unsafe:
        self.url_fetcher = (
            lambda *args, **kwargs: b'<svg width="1" height="1"></svg>')

With it set, the parser accepts entity definitions and the *real* URL fetcher
is installed in place of the stub that otherwise answers every reference with a
blank 1x1 image. `cairosvg.url.read_url` normalises a bare path to
`file://<abspath>`, so `<image xlink:href="/etc/passwd">` reads a local file
and an `http://` href is a request from inside the deployment network.

The endpoint is behind a session cookie, so this is reachable by any registered
user, and the render is written into the job output directory and served back
over `/get_cluster_image/`.

Nothing legitimate needs it. PathwayController.js draws the pathway background
into a canvas, takes `forcedImageCode = canvas.toDataURL()` and substitutes
that data: URI for the PNG's URL before posting; the one branch that cannot
produce the data URI shows an error and returns rather than falling back to a
URL. What arrives is self-contained.

ON WHAT THESE TESTS ASSERT
--------------------------
The first version of this file asserted that the secret's bytes did not appear
in the output PNG. That can never fail: the output is compressed raster data,
so text drawn into it is not present as text and the assertion passes whether
or not the file was read. Both observables below were checked against
`unsafe=True` and do fail there:

    bare path   unsafe=False -> colours=[(0,0,0)]        LEAKED=False
    bare path   unsafe=True  -> colours=[(255,0,255)]    LEAKED=True
    file:// URL unsafe=False -> colours=[(0,0,0)]        LEAKED=False
    file:// URL unsafe=True  -> colours=[(255,0,255)]    LEAKED=True
    internal entity unsafe=False -> RAISED EntitiesForbidden
    internal entity unsafe=True  -> rendered, 222 bytes

One thing this does NOT claim: XXE via `<!ENTITY x SYSTEM "file://...">` was
not exploitable even with the flag set, because ElementTree's parser does not
resolve external entities regardless -- it fails with `undefined entity`. The
reachable primitive is the href fetch, and that is what testLocalFile covers.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_svg_export_is_sandboxed
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from PIL import Image

from src.servlets.PathwayAcquisitionServlet import renderSvgToPng

# Chosen because nothing else in the render is anywhere near it: the canvas
# defaults to black and the legitimate fixture below is red.
CANARY_COLOUR = (255, 0, 255)

IMAGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" width="32" height="32">'
    '<image xlink:href="%s" x="0" y="0" width="32" height="32"/>'
    '</svg>')

# A 1x1 red PNG, inline. This is the shape of every legitimate request: the
# client has already substituted a data: URI for the pathway background.
RED_PIXEL_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class SvgExportSandboxTest(unittest.TestCase):

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="paintomics-svg-export-")
        # A real, decodable image rather than a text file. A text file makes
        # the unsafe path raise UnidentifiedImageError, which would let the
        # test pass for the wrong reason -- an exception, not a blocked fetch.
        # A valid PNG means the only thing distinguishing the two cases is
        # whether its pixels reach the output.
        self.canaryPath = os.path.join(self.workspace, "canary.png")
        Image.new("RGB", (32, 32), CANARY_COLOUR).save(self.canaryPath)
        self.destination = os.path.join(self.workspace, "out.png")

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _renderedColours(self):
        with Image.open(self.destination) as rendered:
            return {colour for _, colour in
                    (rendered.convert("RGB").getcolors(1 << 16) or [])}

    def testLegitimateExportStillRenders(self):
        """The feature this endpoint exists for has to keep working."""
        legitimate = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" width="8" height="8">'
            '<image xlink:href="%s" x="0" y="0" width="8" height="8"/>'
            '<text x="1" y="7" font-size="4">P4</text>'
            '</svg>' % RED_PIXEL_DATA_URI)

        renderSvgToPng(legitimate, self.destination)

        with open(self.destination, "rb") as handle:
            self.assertTrue(handle.read(8) == b"\x89PNG\r\n\x1a\n",
                            "output is not a PNG")
        self.assertIn((255, 0, 0), self._renderedColours(),
                      "the inlined data: URI image was not drawn -- blocking "
                      "external references must not block embedded ones")

    def testLocalFileIsNotReadIntoTheRender(self):
        """The reachable primitive: an href naming a path on the server.

        `read_url` turns a bare path into file://<abspath>, so both spellings
        are the same attack and both are checked.
        """
        for href in (self.canaryPath, "file://" + self.canaryPath):
            with self.subTest(href=href):
                renderSvgToPng(IMAGE_SVG % href, self.destination)

                self.assertNotIn(
                    CANARY_COLOUR, self._renderedColours(),
                    "a local file was fetched and drawn into the render; "
                    "the URL fetcher is not stubbed")

    def testEntityDefinitionsAreRefused(self):
        """Entity expansion must be refused outright, not merely survived.

        Deliberately a small expansion. The assertion is that the parser
        refuses entity definitions at all, so a bomb big enough to exhaust
        memory is unnecessary -- and would turn a failure of this test into a
        hung suite rather than a clear result.
        """
        hostile = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE svg ['
            '<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            ']>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40">'
            '<text x="0" y="20" font-size="6">&b;</text>'
            '</svg>')

        with self.assertRaises(Exception) as raised:
            renderSvgToPng(hostile, self.destination)

        # defusedxml raises EntitiesForbidden. Matching on the name rather than
        # importing the class keeps this from depending on which XML backend
        # CairoSVG happens to use, while still being specific enough to fail if
        # the document merely renders (which is what unsafe=True does).
        self.assertIn("Forbidden", type(raised.exception).__name__,
                      "expected the parser to refuse the entity definition, "
                      "got %r" % raised.exception)


if __name__ == "__main__":
    unittest.main(verbosity=2)
