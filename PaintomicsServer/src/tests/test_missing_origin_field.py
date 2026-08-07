#!/usr/bin/env python3
"""A submission missing an *_origin field must say so, not raise TypeError.

Every uploaded file is paired with a form field naming where it came from.
saveFiles logged that value before branching on it:

    origin = formFields.get(uploadedFileName.replace("file","relevant") + "_origin")
    logging.info("STEP1 - ORIGIN FOR " + ... + " IS " + origin)

so omitting the field produced

    TypeError: can only concatenate str (not "NoneType") to str

surfaced to the caller as HTTP 400 naming neither the field nor the file.

That matters because the field names are *derived* rather than declared:
"omic0_file" yields "omic0_origin" for the data file but
"omic0_relevant_origin" for its relevant-features file. Sending omic0_origin
and assuming that covers the upload is the obvious mistake, and the old message
gave no way to discover which of the two was actually missing. Confirmed
against the deployed server, which answered HTTP 400 with exactly that
TypeError for a request carrying omic0_origin but not omic0_relevant_origin.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_missing_origin_field
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.JobInformationManager import JobInformationManager


def requiredOrigin(*args):
    """Resolve the helper at call time, not import time.

    Binding it at module scope would turn its absence into an ImportError that
    aborts the whole file, hiding which behaviour actually regressed.
    """
    helper = getattr(JobInformationManager, "_requiredOrigin", None)
    if helper is None:
        raise AssertionError(
            "JobInformationManager._requiredOrigin is gone, so saveFiles is back to "
            "concatenating a possibly-None origin into its log message -- a missing "
            "form field becomes TypeError instead of a message naming the field.")
    return helper(*args)


class MissingOriginTest(unittest.TestCase):

    def test_the_expression_that_produced_the_TypeError(self):
        """Pins the exact failure mode, so the reason for the helper is legible.

        This is what saveFiles used to do at each of the three logging sites.
        """
        formFields = {"omic0_origin": "client"}  # the relevant file's origin omitted

        with self.assertRaises(TypeError):
            "STEP1 - ORIGIN FOR omic0_relevant IS " + formFields.get("omic0_relevant_origin")

    def test_present_origin_is_returned(self):
        fields = {"omic0_origin": "client"}
        self.assertEqual(requiredOrigin(fields, "omic0_origin", "data file"), "client")

    def test_non_client_origins_pass_through_untouched(self):
        """The value drives a four-way branch; only absence is an error."""
        for value in ("client", "mydata", "inbuilt_gtf", "omic1_filelocation"):
            with self.subTest(origin=value):
                self.assertEqual(
                    requiredOrigin({"omic0_origin": value}, "omic0_origin", "data file"),
                    value)

    def test_missing_origin_raises_a_message_not_a_typeerror(self):
        with self.assertRaises(Exception) as caught:
            requiredOrigin({}, "omic0_relevant_origin", "relevant features file")

        self.assertNotIsInstance(caught.exception, TypeError)

    def test_message_names_the_missing_field(self):
        """The whole point: the caller must learn which field to add."""
        with self.assertRaises(Exception) as caught:
            requiredOrigin({}, "omic0_relevant_origin", "relevant features file")

        message = str(caught.exception)
        self.assertIn("omic0_relevant_origin", message)
        self.assertIn("relevant features file", message)

    def test_empty_string_origin_is_not_treated_as_missing(self):
        """Only None means "absent"; an empty value is a different complaint,
        handled by the existing "EMPTY FILE OR NOT PROVIDED" fall-through."""
        self.assertEqual(requiredOrigin({"omic0_origin": ""}, "omic0_origin", "data file"), "")

    def test_no_origin_is_concatenated_while_it_could_still_be_None(self):
        """The precise invariant, not merely "every lookup is guarded".

        saveFiles reads four origin fields and only some are hazardous:

          * one is compared (`if omicOrigin == 'client'`) and never
            concatenated -- None is harmless there;
          * one is fetched inside an `if ... is not None` guard;
          * three are logged as `"... IS " + origin`, and those are the ones
            that turned a missing field into a TypeError.

        So the rule enforced here is the one that actually matters: at the point
        where an origin is concatenated into a string, its most recent
        assignment must have gone through _requiredOrigin.
        """
        import inspect
        import re

        source = inspect.getsource(JobInformationManager.saveFiles)

        assignment = re.compile(r"^\s*(\w*[Oo]rigin)\s*=\s*(.*)$")
        lastAssignment = {}
        offending = []

        for lineNumber, line in enumerate(source.splitlines(), 1):
            match = assignment.match(line)
            if match:
                lastAssignment[match.group(1)] = match.group(2)
                continue
            for name, rhs in lastAssignment.items():
                if re.search(r"\+\s*%s\b" % re.escape(name), line):
                    if "_requiredOrigin" not in rhs:
                        offending.append("line %d concatenates %s assigned from: %s"
                                         % (lineNumber, name, rhs.strip()[:80]))

        self.assertEqual(
            offending, [],
            "an origin that may be None reaches a string concatenation:\n  " +
            "\n  ".join(offending))


if __name__ == "__main__":
    unittest.main(verbosity=2)
