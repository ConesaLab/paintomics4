#!/usr/bin/env python3
"""The supporting tools must name a missing name_prefix, not raise TypeError.

Both conversion tools read every one of their parameters by concatenating the
name_prefix form field:

    namePrefix = formFields.get("name_prefix")
    jobInstance.omicName = formFields.get(namePrefix + "_omic_name", "DNase-seq")

so a request without it died on the first lookup with

    TypeError: can only concatenate str (not "NoneType") to str

Probed against the deployed server: /dm_fromBEDtoGenes and /dm_fromMiRNAtoGenes
both failed this way, and both did so in **example mode** as well -- the mode
"Load example" uses -- so the failure is not confined to hand-built API calls.

Rejecting rather than falling back to the per-parameter defaults is deliberate:
without a prefix there is no way to locate the user's settings, and running a
conversion with silently substituted parameters is worse than refusing it.

Same defect class as the missing *_origin field (test_missing_origin_field.py)
and the unvalidated jobID (test_job_endpoint_validation.py).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_name_prefix_validation
"""
import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import Bed2GenesServlet, MiRNA2GenesServlet

TOOLS = [
    (Bed2GenesServlet, "fromBEDtoGenes_STEP1", "regions-to-genes"),
    (MiRNA2GenesServlet, "fromMiRNAtoGenes_STEP1", "miRNA-to-genes"),
]


class NamePrefixGuardTest(unittest.TestCase):

    def _source(self, module, functionName):
        function = getattr(module, functionName, None)
        self.assertIsNotNone(function, "%s no longer exists" % functionName)
        return inspect.getsource(function)

    def _code(self, module, functionName):
        """Source with comments stripped.

        The comments explaining these guards necessarily quote the very
        expressions the assertions look for, so searching raw source finds the
        prose instead of the code and the test silently measures nothing.
        """
        lines = []
        for line in self._source(module, functionName).splitlines():
            stripped = line.split("#", 1)[0]
            if stripped.strip():
                lines.append(stripped)
        return "\n".join(lines)

    def test_prefix_is_checked_before_it_is_concatenated(self):
        for module, functionName, label in TOOLS:
            with self.subTest(tool=label):
                source = self._code(module, functionName)

                assignment = source.index('namePrefix = formFields.get("name_prefix")')
                # Search from the assignment onwards so the explanatory comment
                # above it cannot satisfy the check.
                firstUse = source.index('namePrefix + "', assignment)
                between = source[assignment:firstUse]

                self.assertIn(
                    "if not namePrefix", between,
                    "%s concatenates name_prefix before checking it; a request "
                    "omitting the field raises TypeError instead of naming it"
                    % label)

    def test_guard_raises_something_other_than_TypeError(self):
        """The guard must produce a reportable error, not another crash."""
        for module, functionName, label in TOOLS:
            with self.subTest(tool=label):
                source = self._code(module, functionName)
                guard = source[source.index("if not namePrefix"):]

                self.assertRegex(
                    guard[:400], r"raise\s+UserWarning",
                    "%s should reject a missing name_prefix with a UserWarning, "
                    "which the servlet layer renders as a message" % label)

    def test_message_names_the_missing_field(self):
        for module, functionName, label in TOOLS:
            with self.subTest(tool=label):
                source = self._code(module, functionName)
                guard = source[source.index("if not namePrefix"):][:400]

                self.assertIn("name_prefix", guard,
                              "%s must name the field the caller has to add" % label)

    def test_the_expression_that_produced_the_TypeError(self):
        """Pins the failure mode so the guard's purpose stays legible."""
        namePrefix = None

        with self.assertRaises(TypeError):
            namePrefix + "_omic_name"

    def test_defaults_are_not_used_as_a_silent_fallback(self):
        """A missing prefix must not quietly run with substituted parameters.

        Each lookup carries a default, so simply guarding the concatenation
        would have produced a job configured with values the user never chose.
        """
        for module, functionName, label in TOOLS:
            with self.subTest(tool=label):
                source = self._code(module, functionName)
                guard = source[source.index("if not namePrefix"):][:400]

                self.assertNotRegex(
                    guard, r'namePrefix\s*=\s*["\']',
                    "%s substitutes a default prefix instead of refusing" % label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
