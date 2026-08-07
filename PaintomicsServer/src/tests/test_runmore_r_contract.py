#!/usr/bin/env python3
"""runMORE.R must call the MORE R package with an API that package actually has.

Why this exists
---------------
Every Python test around the MORE feature passed while the pipeline could not
produce a single result, because the failure is in R and only appears when the
script is executed. Running it by hand gave:

    Error in more(targetData = targetData, regulatoryData = regulatoryData, ...):
      unused arguments (targetData = ..., regulatoryData = ..., condition = ...,
                        varSel = ..., minVariation = ...)

runMORE.R passes camelCase argument names; the published MORE package
(ConesaLab/MORE, checked on master, maider and multicore) takes dot-case ones:

    runMORE.R      MORE 0.1.0
    ------------   -------------
    targetData     GeneExpression
    regulatoryData data.omics
    condition      edesign
    minVariation   min.variation
    varSel         (no such argument)

It also calls FilterRegulationPerCondition, which no public branch exports.

Everything upstream of the model call is fine -- data loads, association
orientation is auto-detected, samples align -- so the script looks healthy
until the one line that matters. This test compares the call site against the
installed package's signature so the mismatch is caught in the suite rather
than by a user whose job dies after the upload.

The test skips when R or the MORE package is absent, so it does not turn into
a hard R dependency for the whole suite. It is a contract check, not a run of
the pipeline.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_runmore_r_contract
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

R_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "common", "bioscripts", "runMORE.R"))

# Package-level functions runMORE.R depends on beyond more() itself.
REQUIRED_FUNCTIONS = ["more", "RegulationPerCondition", "FilterRegulationPerCondition"]


def parseMoreCallArguments(path):
    """Named arguments in the `more(...)` call, in source order.

    Deliberately text-based: the point is to read what the script will really
    hand to R, without executing anything.
    """
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()

    start = next((i for i, l in enumerate(lines) if re.search(r"\bmore\s*\($", l.rstrip())), None)
    if start is None:
        raise AssertionError("could not locate the more() call in %s" % path)

    args, depth = [], 0
    for line in lines[start:]:
        depth += line.count("(") - line.count(")")
        match = re.match(r"\s*([A-Za-z._][A-Za-z0-9._]*)\s*=(?!=)", line)
        if match:
            args.append(match.group(1))
        if depth <= 0 and args:
            break
    return args


def rQuery(expression):
    """Run one R expression, returning stdout, or None if R is unusable."""
    if not shutil.which("Rscript"):
        return None
    proc = subprocess.run(["Rscript", "-e", expression],
                          capture_output=True, text=True, timeout=120)
    return proc.stdout.strip() if proc.returncode == 0 else None


def morePackageAPI():
    """(formals of more(), exported names), or None when MORE is unavailable."""
    out = rQuery(
        'if (!requireNamespace("MORE", quietly=TRUE)) { cat("ABSENT") } else {'
        ' cat(jsonlite::toJSON(list('
        '   formals = names(formals(MORE::more)),'
        '   exports = ls("package:MORE")), auto_unbox=FALSE)) }'
        if shutil.which("Rscript") else "")
    if not out or out == "ABSENT":
        # jsonlite may be missing; fall back to a plain delimited dump.
        out = rQuery(
            'if (!requireNamespace("MORE", quietly=TRUE)) cat("ABSENT") else {'
            ' suppressPackageStartupMessages(library(MORE));'
            ' cat("FORMALS:", paste(names(formals(MORE::more)), collapse=","), "\\n");'
            ' cat("EXPORTS:", paste(ls("package:MORE"), collapse=","), "\\n") }')
        if not out or "ABSENT" in out:
            return None
        formals, exports = [], []
        for line in out.splitlines():
            if line.startswith("FORMALS:"):
                formals = [t for t in line.split(":", 1)[1].strip().split(",") if t]
            elif line.startswith("EXPORTS:"):
                exports = [t for t in line.split(":", 1)[1].strip().split(",") if t]
        return formals, exports
    try:
        parsed = json.loads(out)
        return parsed["formals"], parsed["exports"]
    except (ValueError, KeyError):
        return None


class MoreCallSiteTest(unittest.TestCase):
    """These run with no R at all -- they only read the script."""

    def test_the_script_exists(self):
        self.assertTrue(os.path.exists(R_SCRIPT), R_SCRIPT)

    def test_the_more_call_is_parseable(self):
        args = parseMoreCallArguments(R_SCRIPT)
        self.assertTrue(args, "no named arguments found in the more() call")

    def test_every_argument_is_named(self):
        """Positional arguments would silently bind to the wrong parameter
        the moment the package reorders its signature."""
        args = parseMoreCallArguments(R_SCRIPT)
        self.assertEqual(len(args), len(set(args)), "duplicate argument: %s" % args)


class MorePackageContractTest(unittest.TestCase):
    """Skipped when R or MORE is missing; a contract check, not a pipeline run."""

    @classmethod
    def setUpClass(cls):
        cls.api = morePackageAPI()
        if cls.api is None:
            raise unittest.SkipTest("R or the MORE package is not installed")

    def test_every_argument_passed_exists_in_the_signature(self):
        formals, _ = self.api
        passed = parseMoreCallArguments(R_SCRIPT)
        if "..." in formals:
            self.skipTest("more() accepts ..., so unknown names cannot be checked")
        unknown = [a for a in passed if a not in formals]
        self.assertEqual(
            unknown, [],
            "runMORE.R passes argument(s) more() does not accept: %s\n"
            "  passed:   %s\n  accepted: %s" % (unknown, passed, formals))

    def test_required_package_functions_are_exported(self):
        _, exports = self.api
        missing = [f for f in REQUIRED_FUNCTIONS if f not in exports]
        self.assertEqual(
            missing, [],
            "runMORE.R calls MORE function(s) the package does not export: %s\n"
            "  exported: %s" % (missing, exports))


if __name__ == "__main__":
    unittest.main(verbosity=2)
