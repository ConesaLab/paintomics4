#!/usr/bin/env python3
"""R is no longer on the hub path -- at install time or at run time.

What was deleted and why:

  GalaxyNetworkFunctionsv2.R   2,171 lines. Read <subtype> from a document-global
                               list indexed by relation number (28.2% of mmu
                               subtypes wrong) and reaction headers by token
                               position (14.0% of reaction rows corrupted).
  hubAnalysisInstall.R           256 lines. ~34 s per species materialising the
                               1..4 step ball of every compound into 1,865
                               .RData files plus a 34 MB JSON -- the same
                               neighbourhoods, stored twice.
  hubAnalysis.R                  333 lines. Re-read a 13 MB CSV and all 1,865
                               .RData files on every job: I/O proportional to
                               the species installed, not to the user's dataset.

The graph is derived from the KGML the installer already downloads, in 1.03 s
for the largest species measured.

The move/preservation logic in DBManager is deliberately NOT removed: an
existing current/<specie>/hubData is the fallback source for a species whose
kgml/ was not retained, so it must survive an update. It is simply never
created any more.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(ROOT))
sys.path.insert(0, os.path.dirname(ROOT))


def read(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as handle:
        return handle.read()


class RScriptsAreGoneTest(unittest.TestCase):
    def test_the_three_scripts_are_deleted(self):
        for relative in ("AdminTools/scripts/GalaxyNetworkFunctionsv2.R",
                         "AdminTools/scripts/hubAnalysisInstall.R",
                         "common/bioscripts/hubAnalysis.R"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, relative)),
                             "%s still exists" % relative)

    def test_no_code_invokes_them(self):
        """Prose may name them; executable code may not.

        A line scanner cannot tell a docstring from a path, and the historical
        note inside hub_data_is_complete legitimately explains what
        hubAnalysisInstall.R used to write. So Python files are parsed and every
        string constant that is NOT a docstring is checked -- which is exactly
        the set a subprocess call would draw its path from.
        """
        needles = ("hubAnalysisInstall.R", "GalaxyNetworkFunctionsv2.R",
                   "bioscripts/hubAnalysis.R")
        offenders = []
        for base, dirs, files in os.walk(REPO):
            # src/tests is excluded on purpose: these suites NAME the scripts in
            # order to assert they are gone, so including them would make the
            # check fail on its own assertions. The point is production code.
            if ".git" in base or "/docs" in base or "src/tests" in base:
                continue
            for name in files:
                path = os.path.join(base, name)
                if name.endswith(".py"):
                    try:
                        tree = ast.parse(read(path))
                    except SyntaxError:
                        continue
                    docstrings = set()
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.Module, ast.ClassDef,
                                             ast.FunctionDef, ast.AsyncFunctionDef)):
                            doc = ast.get_docstring(node, clean=False)
                            if doc is not None:
                                docstrings.add(doc)
                    for node in ast.walk(tree):
                        if not (isinstance(node, ast.Constant)
                                and isinstance(node.value, str)):
                            continue
                        if node.value in docstrings:
                            continue
                        for needle in needles:
                            if needle in node.value:
                                offenders.append("%s:%d" % (path, node.lineno))
                elif name.endswith((".sh", ".R", ".yml")):
                    for number, line in enumerate(read(path).splitlines(), 1):
                        if line.strip().startswith("#"):
                            continue
                        for needle in needles:
                            if needle in line:
                                offenders.append("%s:%d" % (path, number))
        self.assertEqual(offenders, [])


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.source = read(ROOT, "AdminTools", "DBManager.py")

    def test_install_no_longer_takes_a_hub_flag(self):
        self.assertIn("def install_command(inputfile=None, specie=None, "
                      "species=None, common=0, reinstall=0):", self.source)

    def test_reinstall_no_longer_takes_a_hub_flag(self):
        self.assertIn("def reinstall_command(species=None, specie=None, "
                      "inputfile=None, common=0):", self.source)

    def test_nothing_still_passes_hub_to_install_command(self):
        self.assertNotIn("hub=hub", self.source)

    def test_existing_hub_data_is_still_preserved_across_an_update(self):
        """It is the fallback source for species without kgml/. Deleting the
        BUILD must not delete the PRESERVATION."""
        self.assertIn("hub_data_is_complete", self.source)
        self.assertIn("_hubdata_hold_", self.source)

    def test_the_ci_smoke_test_does_not_pass_the_removed_flag(self):
        smoke = read(REPO, "scripts", "ci", "installer_smoke.py")
        self.assertNotIn("hub=0", smoke)


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.source = read(ROOT, "AdminTools", "DBManager.py")

    def test_hubdoctor_command_exists(self):
        self.assertIn("def hubdoctor_command(", self.source)

    def test_it_prints_rather_than_logs(self):
        """log() is logging.info, which a CLI run does not enable."""
        start = self.source.index("def hubdoctor_command(")
        body = self.source[start:start + 2500]
        self.assertIn('print("HUB DOCTOR:', body)

    def test_it_skips_directories_that_are_not_species(self):
        start = self.source.index("def hubdoctor_command(")
        body = self.source[start:start + 2500]
        self.assertIn(".bak", body)


class ImageTest(unittest.TestCase):
    """The four R packages that existed only for the hub installer."""

    def test_hub_only_packages_are_not_installed_or_asserted(self):
        for relative in (("deploy", "Dockerfile"), ("deploy", "smoke-test.sh")):
            body = read(REPO, *relative)
            for number, line in enumerate(body.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for package in ("qdapRegex", "KEGGgraph", "AnnotationDbi",
                                "visNetwork"):
                    self.assertNotIn(
                        package, line,
                        "%s still references %s at line %d"
                        % (relative[-1], package, number))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
