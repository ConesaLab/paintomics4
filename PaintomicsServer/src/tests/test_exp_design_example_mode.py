"""The "Draft this for me" button must work for a loaded example.

The example flow disables the file pickers -- its files live on the server --
so the client cannot read their header rows the way it does for an upload
(collectPickedOmicFiles finds no File objects and the button dead-ends in
"Choose your data files first"). The servlet therefore reads the headers
itself when the request names an example scenario.

Run:  PYTHONPATH=PaintomicsServer python3 PaintomicsServer/src/tests/test_exp_design_example_mode.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from src.servlets.AIInterpretServlet import _exampleHeaderOmics

EXAMPLE_FILES_DIR = os.path.abspath(os.path.join(HERE, "..", "examplefiles")) + os.sep

failures = []


def check(label, condition, detail=""):
    if condition:
        print("PASS  " + label)
    else:
        failures.append(label)
        print("FAIL  " + label + ("  -- " + detail if detail else ""))


# The default multi-omics scenario: every declared data file WITH a header
# contributes its header row, under the omic name the manifest declares.
omics = _exampleHeaderOmics(EXAMPLE_FILES_DIR, "stategra-multiomics")
names = [entry["omicName"] for entry in omics]
check("stategra-multiomics yields several omics", len(omics) >= 3, repr(names))
check("Gene expression is among them", "Gene expression" in names, repr(names))

# mirna_values.tab has NO header row -- its first line is a gene id plus six
# measured values. That file must be skipped, not shipped: sending its first
# line as "column names" put measurement values into the LLM prompt while the
# UI asserted no values were sent.
check("headerless miRNA-seq file is skipped", "miRNA-seq" not in names, repr(names))

def columnsLeakValues(columns):
    numeric = 0
    for cell in columns[1:]:
        try:
            float(cell)
            numeric += 1
        except ValueError:
            pass
    return numeric > 0

for entry in omics:
    check("%s has multiple columns" % entry["omicName"], len(entry["columns"]) >= 2,
          repr(entry["columns"][:5]))
    check("%s header has no leading #" % entry["omicName"],
          not entry["columns"][0].startswith("#"), repr(entry["columns"][0]))
    check("%s columns carry no numeric values" % entry["omicName"],
          not columnsLeakValues(entry["columns"]), repr(entry["columns"][:5]))

# A falsy scenario id means the server's default scenario, same as /pa_step1/example.
default_omics = _exampleHeaderOmics(EXAMPLE_FILES_DIR, None)
check("default scenario resolves", len(default_omics) >= 1)

# An unknown id must raise the readable UserWarning the interface shows.
try:
    _exampleHeaderOmics(EXAMPLE_FILES_DIR, "no-such-scenario")
    check("unknown scenario raises", False)
except UserWarning:
    check("unknown scenario raises", True)

print()
if failures:
    print("%d FAILURE(S): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("ALL PASS")
