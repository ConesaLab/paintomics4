#!/usr/bin/env python3
"""The Flask 3 upgrade must keep `toBSON()` serialisation working, and the
tree must not reference APIs Flask/Werkzeug 2.x removed.

Two things made the old "Flask >= 2.3" compatibility shim worse than no shim.

1. `flask.json.JSONEncoder` was removed in Flask 2.3, so the shim fell back to
   the stdlib `json.JSONEncoder`. The import then *succeeded* -- and the
   `hasattr(self.app, 'json_encoder')` guard next to it silently skipped
   installing the encoder, because Flask 2.3 dropped that attribute too. The
   result is not a crash: it is `MyJSONEncoder` never being attached to the
   app at all, so every `jsonify()` of a Model loses its `toBSON()` and raises
   `TypeError: Object of type X is not JSON serializable` at request time.

   That matters more than it looks. `toBSON()` is also the wire serialiser --
   the whole API publishes Models through it -- so the shim converted a loud
   import error into a silent, total break of the JSON API.

   Flask 2.2 replaced the encoder with a *provider*: `app.json` is a
   `DefaultJSONProvider`, and overriding it is the supported route.

2. `send_from_directory(..., attachment_filename=)` was renamed to
   `download_name=` in Werkzeug 2.2 and the old spelling removed, so every
   file download would raise `TypeError: unexpected keyword argument`.

The second test is a static guard rather than a behavioural one on purpose:
the removed spellings fail only on the code path that uses them, and the file
download path needs a real job directory to exercise. Grepping the tree costs
nothing and catches a reintroduction anywhere, including in code no test
covers.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_flask3_compat
"""
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from flask import Flask, jsonify

from src.paintomicsserver import configureJSONSerialisation

SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Spelling -> what replaced it. Each of these raises at runtime on the pinned
# Flask/Werkzeug, and each is a rename rather than a behaviour change, so the
# replacement is a straight substitution.
REMOVED_APIS = {
    "attachment_filename": "send_from_directory/send_file download_name=",
    "json_encoder": "app.json = <DefaultJSONProvider subclass>",
    "json_decoder": "app.json = <DefaultJSONProvider subclass>",
    "flask.json.JSONEncoder": "flask.json.provider.DefaultJSONProvider",
    "BaseResponse": "werkzeug.wrappers.Response",
    "BaseRequest": "werkzeug.wrappers.Request",
    "is_xhr": "read the X-Requested-With header directly",
}


class _Serialisable(object):
    """Stands in for a Model. The real ones carry far more, but `toBSON()` is
    the entire contract the encoder relies on."""

    def toBSON(self):
        return {"identifier": "mmu00010", "score": 0.5}


class JSONSerialisationTest(unittest.TestCase):

    def setUp(self):
        # A real app and a real request: the provider is consulted by
        # `jsonify`, so calling the encoder directly would pass even when
        # nothing is wired up -- which is exactly the failure being pinned.
        self.app = Flask(__name__)
        configureJSONSerialisation(self.app)

        @self.app.route("/probe")
        def probe():                                          # noqa: ANN202
            return jsonify({"pathway": _Serialisable()})

        self.client = self.app.test_client()

    def testToBSONObjectsSurviveJsonify(self):
        response = self.client.get("/probe")

        self.assertEqual(200, response.status_code,
                         "jsonify raised instead of serialising a toBSON object; "
                         "the JSON provider is not installed on the app")
        self.assertEqual({"pathway": {"identifier": "mmu00010", "score": 0.5}},
                         response.get_json())

    def testUnserialisableObjectStillRaises(self):
        """The fallback must report the object it actually choked on.

        `MyJSONEncoder.default` ended with `super().default(object)` -- passing
        the *builtin* `object` rather than `obj`. Anything unserialisable was
        therefore reported as "Object of type type is not JSON serializable",
        naming a class nobody passed, which is a materially worse error than
        the one Flask would have raised on its own.
        """
        class Opaque(object):
            pass

        with self.app.app_context():
            with self.assertRaises(TypeError) as raised:
                self.app.json.dumps({"value": Opaque()})

        self.assertIn("Opaque", str(raised.exception),
                      "the TypeError does not name the offending class")


class RemovedAPITest(unittest.TestCase):

    @staticmethod
    def _codeIdentifiers(path):
        """Yield (lineNumber, dottedName) for identifiers in real code.

        Tokenising rather than grepping lines, because comments and docstrings
        legitimately name the removed spellings -- this file and the very
        classes that replaced them do. A line-based scan flags that prose and
        the only way to keep it quiet is to stop writing down what was
        replaced, which is the wrong trade.
        """
        with open(path, "rb") as handle:
            try:
                tokens = list(tokenize.tokenize(handle.readline))
            except (tokenize.TokenError, SyntaxError, IndentationError):
                # Python 2 leftovers and generated files are not worth failing
                # the suite over; they cannot be running under Flask 3 anyway.
                return

        # Rebuild dotted paths so `flask.json.JSONEncoder` is matched as a unit
        # while a bare `JSONEncoder` from stdlib json is left alone.
        parts, startLine = [], None
        for token in tokens:
            if token.type == tokenize.NAME and token.string.isidentifier():
                if not parts:
                    startLine = token.start[0]
                parts.append(token.string)
            elif token.type == tokenize.OP and token.string == "." and parts:
                continue
            else:
                if parts:
                    yield startLine, ".".join(parts)
                parts, startLine = [], None
        if parts:
            yield startLine, ".".join(parts)

    def testNoRemovedFlaskOrWerkzeugAPIs(self):
        offenders = []

        for directory, subdirectories, filenames in os.walk(SOURCE_ROOT):
            subdirectories[:] = [s for s in subdirectories
                                 if s not in {"__pycache__", "public_html"}]
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(directory, filename)
                for number, dotted in self._codeIdentifiers(path):
                    for spelling, replacement in REMOVED_APIS.items():
                        # Exact for dotted spellings, trailing-segment for bare
                        # ones, so `download_name` never matches on a substring.
                        segments = dotted.split(".")
                        hit = (dotted == spelling
                               or ("." not in spelling and spelling in segments))
                        if hit:
                            offenders.append(
                                "%s:%d uses %s -- use %s"
                                % (os.path.relpath(path, SOURCE_ROOT),
                                   number, spelling, replacement))

        self.assertEqual([], offenders,
                         "removed Flask/Werkzeug APIs still referenced:\n  "
                         + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
