#!/usr/bin/env python3
"""Every JSON response must carry exactly one Content-Type, and it must declare
the charset.

Response.getResponse() used to return

    jsonify(self.content), self.status, self.content_type

where content_type is {'Content-Type': 'application/json; charset=utf-8'}.
Werkzeug *extends* the header list with that dict, and jsonify has already set
Content-Type, so every response went out with the header twice:

    Content-Type: application/json
    Content-Type: application/json; charset=utf-8

Confirmed against the deployed app (curl straight at uwsgi, bypassing the
proxy). Two consequences:

  * repeating Content-Type is invalid under RFC 9110, and the deployment's
    nginx logged a warning for every single JSON response;
  * nginx keeps the first value and drops the second -- the one carrying the
    charset -- so the declaration this class exists to add never reached a
    client. Responses carrying non-ASCII (unicode identifiers, compound names,
    AI report prose) were served with no explicit charset at all.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_response_headers
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from flask import Flask

from src.paintomicsserver import Response


class ResponseHeaderTest(unittest.TestCase):

    def setUp(self):
        # The duplication only materialises when Flask unpacks the value a view
        # returns: a third tuple element is *extended* onto the headers that
        # jsonify already set. Inspecting the response object directly would
        # miss it entirely, so everything here goes through a real request.
        self.app = Flask(__name__)
        self.payload = {"success": True}
        self.headerOverride = None

        test = self

        @self.app.route("/probe", methods=["GET"])
        def probe():                                          # noqa: ANN202
            response = Response()
            response.setContent(test.payload)
            if test.headerOverride is not None:
                response.setContentType(test.headerOverride)
            return response.getResponse()

        self.client = self.app.test_client()

    def _headers(self, content):
        self.payload = content
        flaskResponse = self.client.get("/probe")
        return flaskResponse.headers.get_all("Content-Type"), flaskResponse

    def test_content_type_appears_exactly_once(self):
        values, _ = self._headers({"success": True})

        self.assertEqual(
            len(values), 1,
            "Content-Type sent %d times: %s -- repeating it is invalid and the "
            "proxy discards all but the first" % (len(values), values))

    def test_charset_survives(self):
        """The header that used to be dropped is the one that matters."""
        values, _ = self._headers({"success": True})

        self.assertIn("charset=utf-8", values[0].lower())

    def test_status_is_preserved(self):
        app = Flask(__name__)

        @app.route("/failing")
        def failing():                                        # noqa: ANN202
            response = Response()
            response.setContent({"success": False})
            response.setStatus(400)
            return response.getResponse()

        self.assertEqual(app.test_client().get("/failing").status_code, 400)

    def test_body_is_still_valid_json(self):
        _, flaskResponse = self._headers({"success": True, "value": 3})

        self.assertEqual(flaskResponse.get_json(), {"success": True, "value": 3})

    def test_non_ascii_content_round_trips(self):
        """Why the charset declaration is not cosmetic."""
        payload = {"gene": "GENÉ中文", "note": "café"}
        _, flaskResponse = self._headers(payload)

        self.assertEqual(flaskResponse.get_json(), payload)

    def test_every_declared_header_is_applied_once(self):
        """Guards the loop generally, not just the Content-Type key."""
        self.headerOverride = {"Content-Type": "application/json; charset=utf-8",
                               "X-Paintomics-Test": "1"}

        _, flaskResponse = self._headers({"ok": True})

        self.assertEqual(len(flaskResponse.headers.get_all("Content-Type")), 1)
        self.assertEqual(len(flaskResponse.headers.get_all("X-Paintomics-Test")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
