# Metabolite Hub Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive the KEGG compound–gene graph from the KGML already on disk, remove R from the metabolite hub path entirely, and give users a network view of a metabolite's 1–4 step neighbourhood.

**Architecture:** A new pure-Python package `src/common/KeggGraph/` parses KGML into an attributed edge list, builds an in-memory CSR index, and serves neighbourhood queries. Nothing is persisted — the graph is derived on first use (measured 1.03 s worst case) and cached per organism in the process. The hub statistic moves to scipy/statsmodels. A new servlet route serves induced subgraphs, which a Cytoscape view renders as concentric hop rings.

**Tech Stack:** Python 3.11, `xml.etree.ElementTree`, NumPy 1.26.4, SciPy 1.13.1, statsmodels 0.14.6 (all four already pinned in `requirements.txt` — **no dependency changes**). Client: Cytoscape.js 3.34.0 (already loaded), ExtJS 4.2.1, jQuery 3.1.0.

**Spec:** `docs/superpowers/specs/2026-08-25-metabolite-hub-graph-design.md`

## Global Constraints

- **Python is 3.11.** Type hints allowed; no `match` beyond 3.11 features.
- **No new dependencies.** `numpy==1.26.4`, `scipy==1.13.1`, `statsmodels==0.14.6`, `pandas==1.5.3` are already in the root `requirements.txt`. Adding anything else fails `src/tests/test_dependencies_declared.py`.
- **Tests are standalone unittest scripts.** No pytest in this repo. Every suite ends with:
  ```python
  def main():
      suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
      result = unittest.TextTestRunner(verbosity=2).run(suite)
      return 0 if result.wasSuccessful() else 1

  if __name__ == "__main__":
      sys.exit(main())
  ```
  Run one suite: `cd PaintomicsServer && python -m src.tests.test_NAME`
  Run everything: `cd PaintomicsServer && python -m src.tests.run_all`
- **Use the venv-py311 interpreter for regression runs**, conda only for DBManager. Baselines are interpreter-pinned.
- **JS is tested by extracting the function text and running it in node** (see `src/tests/test_neighbouring_features_button.py:66-105`), plus `node --check` for syntax. Guard with `@unittest.skipIf(shutil.which("node") is None, "node is not installed")`.
- **`PA_Step3Views.js` needs no `?v=` bump** — it is loaded by `app.js:308-316` through `$.ajax({dataType:"script"})` and jQuery forces `cache:false`. Files listed in `index.html` **do** need a bump.
- **Chrome verification is mandatory** before any task is reported done that changes UI or server behaviour (CLAUDE.md §5). Restart the server first; the debug reloader is unreliable.
- **`git commit -- <paths>`**, never bare `git commit` — the index is shared with other sessions.
- Data root: `KEGG_DATA_DIR = /Users/tianyuan/Desktop/github_dev/paintomics4_data/KEGG_DATA/`. Species with KGML locally: `mmu` (364), `ath` (162), `hsa` (372).

---

## File Structure

**Create**
| file | responsibility |
|---|---|
| `PaintomicsServer/src/common/KeggGraph/__init__.py` | package marker; re-exports `get_graph` |
| `PaintomicsServer/src/common/KeggGraph/parser.py` | KGML → `[Edge]`. The only KGML parser for hub. No graph logic. |
| `PaintomicsServer/src/common/KeggGraph/graph.py` | `KeggGraph`: CSR index, `rings()`, `subgraph()`. No I/O. |
| `PaintomicsServer/src/common/KeggGraph/store.py` | derive-or-cache per organism, legacy fallback. The only module that touches disk. |
| `PaintomicsServer/src/common/KeggGraph/scorer.py` | the hub statistic. Pure function of a graph + two id sets. |
| `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3HubNetworkView.js` | Cytoscape hop-ring view |
| `PaintomicsServer/src/tests/test_kegg_graph_parser.py` | D-1 / D-2 golden fixture |
| `PaintomicsServer/src/tests/test_kegg_graph_rings.py` | D-6 + ring properties |
| `PaintomicsServer/src/tests/test_kegg_graph_store.py` | cache key, fallback |
| `PaintomicsServer/src/tests/test_hub_scorer.py` | statistic + schema version |
| `PaintomicsServer/src/tests/test_hub_subgraph_route.py` | route contract + ownership |
| `PaintomicsServer/src/tests/test_hub_network_view.py` | node-run JS helpers |

**Modify**
| file | change |
|---|---|
| `PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py:2716-2787` | `hubAnalysis()` calls Python, not Rscript |
| `PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py:2623-2679` | `getCompoundRegulateFeatures()` uses the store |
| `PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py:113-177` | delete `_loadCompoundNeighbourMap` |
| `PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py` | new `hubSubgraph()` handler |
| `PaintomicsServer/src/paintomicsserver.py` | new route |
| `PaintomicsServer/src/AdminTools/DBManager.py:541-658, 1089-1121` | delete the hub block and `hub_data_is_complete` |
| `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js:5765-6284` | render both result shapes; open the network view |
| `PaintomicsClient/public_html/index.html:150-155` | register the new view |
| `PaintomicsClient/public_html/resources/ServerConfiguration.js:142` | new URL constant |
| `PaintomicsClient/public_html/resources/css/network-views.css:46-48` | add the new toolbar selector |

**Delete** (Task 9, after everything above is green)
`src/AdminTools/scripts/GalaxyNetworkFunctionsv2.R` (2,171), `src/AdminTools/scripts/hubAnalysisInstall.R` (256), `src/common/bioscripts/hubAnalysis.R` (333).

---

## Task 1: KGML parser — fix D-1 and D-2

**Files:**
- Create: `PaintomicsServer/src/common/KeggGraph/__init__.py`, `PaintomicsServer/src/common/KeggGraph/parser.py`
- Test: `PaintomicsServer/src/tests/test_kegg_graph_parser.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  Edge = namedtuple("Edge", "a b kind subtype pathway reversible")
  # a, b: str  entry names, KEGG prefix stripped ("100", "C00001")
  # kind: str  "PPrel"|"GErel"|"ECrel"|"PCrel"|"maplink"|"reaction"
  # subtype: str  comma-joined subtype names, or comma-joined "rn:" ids for reactions
  # pathway: str  e.g. "mmu00010"
  # reversible: bool  reactions only; False for relations
  parse_pathway(path: str) -> tuple[list[Edge], dict[str, str]]   # edges, name->entry type
  parse_directory(kgml_dir: str) -> tuple[list[Edge], dict[str, str], int]  # +files read
  ```

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_kegg_graph_parser.py`:

```python
#!/usr/bin/env python3
"""The KGML parser must attribute subtypes and reaction headers correctly.

The R parser this replaces did two things that a real XML parse makes
impossible, both measured over all 364 mmu KGML files:

  * `GalaxyNetworkFunctionsv2.R:96` collected EVERY <subtype> in the pathway
    into one list and `:121` indexed it by RELATION number. Correct only when
    every relation has exactly one subtype. 2,885 mmu relations have two and
    285 have none, so once drift starts every later relation in that pathway is
    mis-zipped: 5,963 of 21,120 subtypes wrong (28.2%), 194 of 364 pathways.
  * `:192/:234/:262` read reaction id/name/type as tokens 3/5/7 of the
    stringified node. A reaction whose name holds two ids shifts the type one
    token right, yielding the literal attribute NAME "type": 3,083 of 22,038
    reaction rows corrupted (14.0%).

FIXTURE is built so the old behaviour and the correct behaviour differ. Its
three relations carry 2, 1 and 0 subtypes. Index-zipping gives relation 2 the
SECOND subtype ("phosphorylation") when its own child says "expression" -- so
`test_subtype_is_read_from_its_own_relation` fails against the old algorithm and
passes against a correct one.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.parser import parse_pathway, parse_directory

FIXTURE = """<?xml version="1.0"?>
<pathway name="path:tst00001" org="tst" number="00001">
  <entry id="1" name="tst:100 tst:101" type="gene"/>
  <entry id="2" name="tst:200" type="gene"/>
  <entry id="3" name="cpd:C00001" type="compound"/>
  <entry id="4" name="cpd:C00002" type="compound"/>
  <entry id="5" name="undefined" type="group">
    <component id="1"/>
    <component id="2"/>
  </entry>
  <entry id="6" name="tst:300" type="gene"/>
  <entry id="7" name="path:tst00002" type="map"/>
  <entry id="8" name="tst:400" type="gene"/>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation" value="--&gt;"/>
    <subtype name="phosphorylation" value="+p"/>
  </relation>
  <relation entry1="2" entry2="6" type="GErel">
    <subtype name="expression" value="--&gt;"/>
  </relation>
  <relation entry1="6" entry2="7" type="maplink"/>
  <relation entry1="5" entry2="8" type="PPrel">
    <subtype name="inhibition" value="--|"/>
  </relation>
  <reaction id="6" name="rn:R00001 rn:R00002" type="irreversible">
    <substrate id="3" name="cpd:C00001"/>
    <product id="4" name="cpd:C00002"/>
  </reaction>
</pathway>
"""


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintomics-kgml-")
        self.path = os.path.join(self.dir, "tst00001.kgml")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(FIXTURE)
        self.edges, self.types = parse_pathway(self.path)
        self.by_pair = {(e.a, e.b): e for e in self.edges}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_subtype_is_read_from_its_own_relation(self):
        """D-1. Index-zipping would give relation 2 'phosphorylation'."""
        self.assertEqual(self.by_pair[("200", "300")].subtype, "expression")

    def test_all_subtypes_of_one_relation_are_kept(self):
        self.assertEqual(self.by_pair[("100", "200")].subtype,
                         "activation,phosphorylation")

    def test_relation_with_no_subtype_is_still_an_edge(self):
        edge = self.by_pair[("300", "tst00002")]
        self.assertEqual(edge.subtype, "")
        self.assertEqual(edge.kind, "maplink")

    def test_reaction_type_is_read_as_an_attribute(self):
        """D-2. Token-position parsing yields the literal string 'type' here."""
        edge = self.by_pair[("300", "C00001")]
        self.assertEqual(edge.kind, "reaction")
        self.assertFalse(edge.reversible)

    def test_multi_id_reaction_name_keeps_both_ids(self):
        self.assertEqual(self.by_pair[("300", "C00001")].subtype,
                         "rn:R00001,rn:R00002")

    def test_reaction_links_enzyme_to_substrate_and_product(self):
        self.assertIn(("300", "C00001"), self.by_pair)
        self.assertIn(("300", "C00002"), self.by_pair)

    def test_group_expands_to_its_components(self):
        for member in ("100", "101", "200"):
            self.assertIn((member, "400"), self.by_pair)
            self.assertEqual(self.by_pair[(member, "400")].subtype, "inhibition")

    def test_group_itself_is_never_a_node(self):
        names = {e.a for e in self.edges} | {e.b for e in self.edges}
        self.assertNotIn("undefined", names)
        self.assertNotIn("", names)

    def test_entry_types_are_recorded(self):
        self.assertEqual(self.types["100"], "gene")
        self.assertEqual(self.types["C00001"], "compound")
        self.assertEqual(self.types["tst00002"], "map")

    def test_every_edge_carries_its_pathway(self):
        self.assertTrue(all(e.pathway == "tst00001" for e in self.edges))

    def test_parse_directory_reports_the_file_count(self):
        edges, types, files = parse_directory(self.dir)
        self.assertEqual(files, 1)
        self.assertEqual(len(edges), len(self.edges))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_parser`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.common.KeggGraph'`

- [ ] **Step 3: Write the implementation**

Create `PaintomicsServer/src/common/KeggGraph/__init__.py`:

```python
"""The KEGG compound-gene graph, derived from the KGML each organism install
already ships. Nothing here is persisted: see
docs/superpowers/specs/2026-08-25-metabolite-hub-graph-design.md."""
from src.common.KeggGraph.store import get_graph  # noqa: F401
```

Create `PaintomicsServer/src/common/KeggGraph/parser.py`:

```python
"""KGML -> attributed edges.

Every attribute is read by NAME from the element that owns it. The R parser
this replaces read subtypes from a document-global list indexed by relation
number (28.2% wrong) and reaction headers by token position (14.0% corrupted);
both are unrepresentable here by construction.
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from collections import namedtuple

logger = logging.getLogger(__name__)

Edge = namedtuple("Edge", "a b kind subtype pathway reversible")


def _names(entry):
    """Concrete KEGG ids on an entry, prefix stripped. 'tst:100 tst:101' -> ['100','101'].

    A `map` entry is named `path:tst00002`; keep the id so map links stay
    visible to the caller. Filtering them is the graph's job, not the parser's.
    """
    out = []
    for token in (entry.get("name") or "").split():
        if ":" in token:
            out.append(token.split(":", 1)[1])
    return out


def parse_pathway(path):
    """(edges, entry_types) for one KGML file. Never raises on a bad file."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        logger.warning("[keggraph] unreadable KGML %s: %s", path, exc)
        return [], {}

    pathway = (root.get("name") or "").replace("path:", "")
    entries, groups, types = {}, {}, {}

    for entry in root.findall("entry"):
        eid = entry.get("id")
        etype = entry.get("type")
        names = _names(entry)
        if etype == "group":
            groups[eid] = [c.get("id") for c in entry.findall("component")]
        entries[eid] = names
        for name in names:
            types[name] = etype

    def expand(eid):
        """A group resolves to its components' names; anything else to its own.

        No component cap. The R side silently truncated at 50 via
        `seq(2, 100, by = 2)`; the largest real group observed on mmu is 13.
        """
        if eid in groups:
            out = []
            for component in groups[eid]:
                out.extend(entries.get(component, []))
            return out
        return entries.get(eid, [])

    edges = {}

    def add(a, b, kind, subtype, reversible):
        # An unnamed endpoint is never a real biological entity. The R pipeline
        # let one through as a node called "" that reached degree 1,381.
        if not a or not b or a == b:
            return
        edges.setdefault((a, b), Edge(a, b, kind, subtype, pathway, reversible))

    for relation in root.findall("relation"):
        kind = relation.get("type") or "?"
        # D-1: this relation's OWN subtype children, in document order.
        subtype = ",".join(s.get("name") or "" for s in relation.findall("subtype"))
        for a in expand(relation.get("entry1")):
            for b in expand(relation.get("entry2")):
                add(a, b, kind, subtype, False)

    for reaction in root.findall("reaction"):
        # D-2: attributes by name. `name` may hold several ids.
        reversible = reaction.get("type") == "reversible"
        ids = ",".join((reaction.get("name") or "").split())
        compounds = [c.get("name", "").split(":")[-1]
                     for c in list(reaction.findall("substrate"))
                     + list(reaction.findall("product"))]
        for enzyme in expand(reaction.get("id")):
            for compound in compounds:
                add(enzyme, compound, "reaction", ids, reversible)

    return list(edges.values()), types


def parse_directory(kgml_dir):
    """(edges, entry_types, files_read) over every *.kgml in a directory."""
    edges, types, read = {}, {}, 0
    try:
        listing = sorted(os.listdir(kgml_dir))
    except OSError as exc:
        logger.warning("[keggraph] cannot list %s: %s", kgml_dir, exc)
        return [], {}, 0
    for name in listing:
        if not name.endswith(".kgml"):
            continue
        found, found_types = parse_pathway(os.path.join(kgml_dir, name))
        if not found and not found_types:
            continue
        read += 1
        types.update(found_types)
        for edge in found:
            edges.setdefault((edge.a, edge.b), edge)
    return list(edges.values()), types, read
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_parser`
Expected: `Ran 11 tests ... OK`

- [ ] **Step 5: Prove the fix on real data**

Run:
```bash
cd PaintomicsServer && python -c "
from src.common.KeggGraph.parser import parse_directory
e,t,n = parse_directory('/Users/tianyuan/Desktop/github_dev/paintomics4_data/KEGG_DATA/current/mmu/kgml')
print('files', n, 'edges', len(e), 'nodes', len(t))
print('blank endpoints', sum(1 for x in e if not x.a or not x.b))
print('literal type   ', sum(1 for x in e if x.kind == 'type' or x.subtype == 'type'))
"
```
Expected: `files 364`, edges on the order of 96,000, **`blank endpoints 0`** and **`literal type 0`**. Record the exact numbers in the commit message.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsServer/src/common/KeggGraph/__init__.py \
        PaintomicsServer/src/common/KeggGraph/parser.py \
        PaintomicsServer/src/tests/test_kegg_graph_parser.py
git commit -m "Read KGML attributes by name, not by position" -- \
        PaintomicsServer/src/common/KeggGraph/__init__.py \
        PaintomicsServer/src/common/KeggGraph/parser.py \
        PaintomicsServer/src/tests/test_kegg_graph_parser.py
```

---

## Task 2: CSR index and hop rings — fix D-6

**Files:**
- Create: `PaintomicsServer/src/common/KeggGraph/graph.py`
- Test: `PaintomicsServer/src/tests/test_kegg_graph_rings.py`

**Interfaces:**
- Consumes: `Edge`, `parse_directory` from Task 1.
- Produces:
  ```python
  class KeggGraph:
      names: list[str]                      # int code -> name
      node_type: dict[str, str]
      def __init__(self, edges: list[Edge], types: dict[str, str], source: str)
      def rings(self, seed: str, k: int = 4) -> list[list[str]]   # EXCLUSIVE, seed never present
      def subgraph(self, seed: str, k: int, budget: int) -> dict  # see Task 7
      def compounds(self) -> list[str]
      def genes(self) -> list[str]
      source: str                           # "kgml" or "legacy-json"
  ```
  Map-typed nodes are excluded at construction.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_kegg_graph_rings.py`:

```python
#!/usr/bin/env python3
"""Hop rings must exclude the seed and be disjoint and nested.

`hubAnalysisInstall.R:204` subtracted the seed only from the frontier:

    unique(c(susinteracciones, setdiff(unique(t3$Var2), elcompound)))

The carried-forward set was unioned unchanged, so a compound with a self-loop
never left its own neighbourhood. Nine mmu compounds are affected in the shipped
data -- C00011, C00024, C00046, C00080, C00154, C00288, C00698, C22533, C22539.
C00024 is one of them, which is why every worked example hid the defect.

Radius 1 is also an OPEN neighbourhood N(v), not a closed ball, so
`igraph::ego(order=k)` is not a drop-in: it includes the seed unconditionally.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.parser import Edge
from src.common.KeggGraph.graph import KeggGraph


def edge(a, b, kind="PPrel"):
    return Edge(a, b, kind, "", "tst00001", False)


class RingTest(unittest.TestCase):
    def setUp(self):
        #  SELF <-> SELF (self-loop),  SELF - A - B - C - D
        #  M is a map node and must never appear.
        self.graph = KeggGraph(
            [edge("SELF", "SELF"), edge("SELF", "A"), edge("A", "B"),
             edge("B", "C"), edge("C", "D"), edge("SELF", "M")],
            {"SELF": "compound", "A": "gene", "B": "gene", "C": "gene",
             "D": "gene", "M": "map"},
            source="test")

    def test_seed_is_never_in_its_own_rings(self):
        """D-6, with the exact topology that produced it."""
        for ring in self.graph.rings("SELF", 4):
            self.assertNotIn("SELF", ring)

    def test_rings_are_exclusive_and_ordered_by_distance(self):
        self.assertEqual([sorted(r) for r in self.graph.rings("SELF", 4)],
                         [["A"], ["B"], ["C"], ["D"]])

    def test_rings_are_pairwise_disjoint(self):
        rings = self.graph.rings("SELF", 4)
        seen = set()
        for ring in rings:
            self.assertFalse(seen & set(ring))
            seen |= set(ring)

    def test_map_nodes_are_excluded(self):
        flat = {n for ring in self.graph.rings("SELF", 4) for n in ring}
        self.assertNotIn("M", flat)

    def test_exhausted_graph_yields_empty_rings_not_an_error(self):
        self.assertEqual(self.graph.rings("D", 4)[3], [])

    def test_unknown_seed_returns_empty_rings(self):
        self.assertEqual(self.graph.rings("NOPE", 4), [[], [], [], []])

    def test_compounds_and_genes_partition_by_type(self):
        self.assertEqual(self.graph.compounds(), ["SELF"])
        self.assertEqual(sorted(self.graph.genes()), ["A", "B", "C", "D"])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_rings`
Expected: FAIL — `No module named 'src.common.KeggGraph.graph'`

- [ ] **Step 3: Write the implementation**

Create `PaintomicsServer/src/common/KeggGraph/graph.py`:

```python
"""CSR adjacency over integer-coded node names, plus hop-ring traversal.

"Store nothing" means no persisted artifact, not no index: this index is built
on every cold start and is what makes traversal possible at all. It is also
nearly free -- 0.03 s of mmu's 1.03 s, the other 0.99 s being XML parsing.
"""
from __future__ import annotations

import numpy as np

MAP_TYPE = "map"


class KeggGraph(object):
    def __init__(self, edges, types, source):
        self.source = source
        # Map entries are pathway cross-links, not biological entities. The R
        # pipeline filtered them twice, at install AND at scoring; do it once.
        kept = [e for e in edges
                if types.get(e.a) != MAP_TYPE and types.get(e.b) != MAP_TYPE]

        self.names = sorted({e.a for e in kept} | {e.b for e in kept})
        self._code = {name: index for index, name in enumerate(self.names)}
        self.node_type = {name: types.get(name) for name in self.names}

        count = len(kept)
        src = np.fromiter((self._code[e.a] for e in kept), np.int32, count)
        dst = np.fromiter((self._code[e.b] for e in kept), np.int32, count)
        self.edge_kind = [e.kind for e in kept]
        self.edge_subtype = [e.subtype for e in kept]
        self.edge_pathway = [e.pathway for e in kept]
        self.edge_reversible = np.fromiter(
            (bool(e.reversible) for e in kept), bool, count)
        self.edge_src, self.edge_dst = src, dst

        # Symmetric CSR. `edge_id` lets subgraph() recover an edge's attributes.
        u = np.concatenate([src, dst])
        v = np.concatenate([dst, src])
        eid = np.concatenate([np.arange(count), np.arange(count)]).astype(np.int32)
        order = np.argsort(u, kind="stable")
        self._indices = v[order]
        self._edge_id = eid[order]
        counts = np.zeros(len(self.names) + 1, np.int64)
        np.add.at(counts, u[order].astype(np.int64) + 1, 1)
        self._indptr = np.cumsum(counts)

    def _neighbours(self, code):
        return self._indices[self._indptr[code]:self._indptr[code + 1]]

    def rings(self, seed, k=4):
        """Exclusive hop rings. `rings(v)[0]` is N(v); the seed is never in any.

        Seeding `seen` with the seed is the whole of the D-6 fix: a self-loop
        can no longer put a node back inside its own neighbourhood.
        """
        code = self._code.get(seed)
        if code is None:
            return [[] for _ in range(k)]
        seen = np.zeros(len(self.names), dtype=bool)
        seen[code] = True
        frontier = np.array([code], dtype=np.int64)
        out = []
        for _ in range(k):
            if frontier.size == 0:
                out.append([])
                continue
            found = np.unique(np.concatenate(
                [self._neighbours(int(x)) for x in frontier]))
            found = found[~seen[found]]
            seen[found] = True
            frontier = found
            out.append([self.names[int(x)] for x in found])
        return out

    def compounds(self):
        return [n for n in self.names if self.node_type.get(n) == "compound"]

    def genes(self):
        return [n for n in self.names if self.node_type.get(n) == "gene"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_rings`
Expected: `Ran 7 tests ... OK`

- [ ] **Step 5: Confirm the nine mmu compounds are fixed**

Run:
```bash
cd PaintomicsServer && python -c "
from src.common.KeggGraph.parser import parse_directory
from src.common.KeggGraph.graph import KeggGraph
e,t,n = parse_directory('/Users/tianyuan/Desktop/github_dev/paintomics4_data/KEGG_DATA/current/mmu/kgml')
g = KeggGraph(e,t,'kgml')
bad = [c for c in ('C00011','C00024','C00046','C00080','C00154','C00288','C00698','C22533','C22539')
       if any(c in r for r in g.rings(c,4))]
print('compounds still inside their own rings:', bad)
"
```
Expected: `compounds still inside their own rings: []`

- [ ] **Step 6: Commit**

```bash
git add PaintomicsServer/src/common/KeggGraph/graph.py \
        PaintomicsServer/src/tests/test_kegg_graph_rings.py
git commit -m "Exclude the seed from its own hop rings" -- \
        PaintomicsServer/src/common/KeggGraph/graph.py \
        PaintomicsServer/src/tests/test_kegg_graph_rings.py
```

---

## Task 3: The store — derive, cache, fall back

**Files:**
- Create: `PaintomicsServer/src/common/KeggGraph/store.py`
- Test: `PaintomicsServer/src/tests/test_kegg_graph_store.py`

**Interfaces:**
- Consumes: `KeggGraph` (Task 2), `parse_directory` (Task 1).
- Produces: `get_graph(organism: str) -> KeggGraph | None`, `clear_cache() -> None`, `CACHE_SIZE: int = 4`.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_kegg_graph_store.py`:

```python
#!/usr/bin/env python3
"""The graph is derived on demand, cached per organism, and self-invalidating.

Today `_loadCompoundNeighbourMap` (PathwayAcquisitionJob.py:113-177) parses a
34 MB JSON and peaks at 360-420 MB RSS -- reproduced this session at 393 MB --
into a cache with ONE slot, so a second organism evicts the first. Deriving from
KGML instead was measured at 1.03 s and 32 MB for the largest species.

The cache key is (organism, file count, max mtime) so reinstalling a species
invalidates it without anyone having to remember to.

The legacy fallback is not optional: KGML retention on production is unverified,
and every species that has hub data today has a kegg_interaction.json.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph import store

KGML = """<?xml version="1.0"?>
<pathway name="path:tst00001" org="tst" number="00001">
  <entry id="1" name="cpd:C00001" type="compound"/>
  <entry id="2" name="tst:100" type="gene"/>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation" value="--&gt;"/>
  </relation>
</pathway>
"""


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="paintomics-store-")
        self.kgml = os.path.join(self.root, "current", "tst", "kgml")
        self.hub = os.path.join(self.root, "current", "tst", "hubData")
        os.makedirs(self.kgml)
        os.makedirs(self.hub)
        with open(os.path.join(self.kgml, "tst00001.kgml"), "w") as handle:
            handle.write(KGML)
        self._old = store.KEGG_DATA_DIR
        store.KEGG_DATA_DIR = self.root + os.sep
        store.clear_cache()

    def tearDown(self):
        store.KEGG_DATA_DIR = self._old
        store.clear_cache()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_derives_from_kgml(self):
        graph = store.get_graph("tst")
        self.assertEqual(graph.source, "kgml")
        self.assertEqual(graph.rings("C00001", 1)[0], ["100"])

    def test_second_call_returns_the_same_object(self):
        self.assertIs(store.get_graph("tst"), store.get_graph("tst"))

    def test_touching_a_kgml_file_invalidates_the_cache(self):
        first = store.get_graph("tst")
        path = os.path.join(self.kgml, "tst00001.kgml")
        os.utime(path, (os.path.getatime(path), os.path.getmtime(path) + 60))
        self.assertIsNot(store.get_graph("tst"), first)

    def test_adding_a_kgml_file_invalidates_the_cache(self):
        first = store.get_graph("tst")
        with open(os.path.join(self.kgml, "tst00002.kgml"), "w") as handle:
            handle.write(KGML.replace("tst00001", "tst00002"))
        self.assertIsNot(store.get_graph("tst"), first)

    def test_falls_back_to_the_legacy_json_when_kgml_is_absent(self):
        shutil.rmtree(self.kgml)
        with open(os.path.join(self.hub, "kegg_interaction.json"), "w") as handle:
            json.dump({"C00001": [["100"], ["100", "200"], [], []]}, handle)
        graph = store.get_graph("tst")
        self.assertEqual(graph.source, "legacy-json")
        self.assertEqual(graph.rings("C00001", 1)[0], ["100"])

    def test_returns_none_when_the_species_has_neither(self):
        shutil.rmtree(self.kgml)
        self.assertIsNone(store.get_graph("tst"))

    def test_unknown_organism_returns_none(self):
        self.assertIsNone(store.get_graph("nope"))

    def test_cache_is_bounded(self):
        for index in range(store.CACHE_SIZE + 2):
            code = "sp%d" % index
            directory = os.path.join(self.root, "current", code, "kgml")
            os.makedirs(directory)
            with open(os.path.join(directory, "a.kgml"), "w") as handle:
                handle.write(KGML)
            store.get_graph(code)
        self.assertLessEqual(len(store._CACHE), store.CACHE_SIZE)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_store`
Expected: FAIL — `No module named 'src.common.KeggGraph.store'`

- [ ] **Step 3: Write the implementation**

Create `PaintomicsServer/src/common/KeggGraph/store.py`:

```python
"""Derive-or-cache. The only module in this package that touches disk.

The graph is a pure function of the KGML the organism install already ships, and
deriving it costs 1.03 s for the largest species measured (mmu, 364 files,
96,618 edges, 32 MB peak). Persisting it would save ~0.9 s once per process and
cost an install step, a schema, a migration across 87 species, and the
download/->current/->old/ staging bug class. So nothing is persisted.

If a future measurement says otherwise, this module is the only one that changes:
`get_graph` is the seam.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge, parse_directory

try:
    from src.conf.serverconf import KEGG_DATA_DIR
except Exception:                                     # pragma: no cover
    KEGG_DATA_DIR = ""

logger = logging.getLogger(__name__)

CACHE_SIZE = 4
_CACHE = OrderedDict()          # key -> KeggGraph
_LOCK = threading.Lock()


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def _kgml_signature(kgml_dir):
    """(file count, max mtime) -- changes whenever the species is reinstalled."""
    count, newest = 0, 0.0
    try:
        entries = os.listdir(kgml_dir)
    except OSError:
        return None
    for name in entries:
        if not name.endswith(".kgml"):
            continue
        count += 1
        try:
            newest = max(newest, os.path.getmtime(os.path.join(kgml_dir, name)))
        except OSError:
            continue
    return (count, newest) if count else None


def _legacy_edges(path):
    """Rebuild edges from hubData/kegg_interaction.json.

    That file holds each compound's cumulative 1..4-step BALLS, not pairs, so
    the only honest reconstruction is compound -> radius-1 members. It is a
    safety net for species whose KGML was not retained, and it inherits the old
    parse: no subtypes, no reaction direction. `graph.source` says so.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("[keggraph] unreadable %s: %s", path, exc)
        return [], {}
    for _ in range(4):                       # tolerate the old double encoding
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
    if not isinstance(payload, dict):
        return [], {}

    edges, types = [], {}
    for compound, radii in payload.items():
        types[compound] = "compound"
        first = radii[0] if isinstance(radii, list) and radii else []
        if isinstance(first, str):
            first = [first]
        for neighbour in first or []:
            neighbour = str(neighbour)
            types.setdefault(neighbour,
                             "compound" if neighbour[:1] in "CGD" else "gene")
            edges.append(Edge(compound, neighbour, "legacy", "", "", False))
    return edges, types


def get_graph(organism):
    """The organism's KeggGraph, or None if neither source is available."""
    if not organism or not KEGG_DATA_DIR:
        return None
    organism = str(organism)
    base = os.path.join(KEGG_DATA_DIR, "current", organism)
    kgml_dir = os.path.join(base, "kgml")
    signature = _kgml_signature(kgml_dir)
    key = (organism, signature)

    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

    if signature is not None:
        edges, types, files = parse_directory(kgml_dir)
        source = "kgml"
        logger.info("[keggraph] %s derived from %d KGML files: %d edges",
                    organism, files, len(edges))
    else:
        legacy = os.path.join(base, "hubData", "kegg_interaction.json")
        if not os.path.exists(legacy):
            logger.warning("[keggraph] %s has neither kgml/ nor hubData/"
                           "kegg_interaction.json; hub features unavailable",
                           organism)
            return None
        edges, types = _legacy_edges(legacy)
        source = "legacy-json"
        logger.warning("[keggraph] %s has no KGML; falling back to %s "
                       "(no subtypes, no direction)", organism, legacy)

    if not edges:
        return None
    graph = KeggGraph(edges, types, source)

    with _LOCK:
        _CACHE[key] = graph
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return graph
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_kegg_graph_store`
Expected: `Ran 8 tests ... OK`

- [ ] **Step 5: Measure the real cold start**

Run:
```bash
cd PaintomicsServer && python -c "
import time
from src.common.KeggGraph import store
for sp in ('mmu','ath','hsa'):
    store.clear_cache(); t=time.perf_counter(); g=store.get_graph(sp)
    print(sp, 'None' if g is None else ('%.2fs %d edges %d nodes %s' % (
        time.perf_counter()-t, len(g.edge_kind), len(g.names), g.source)))
"
```
Expected: mmu and hsa near 1.0 s, ath near 0.6 s, all `source=kgml`. If any exceeds 3 s, stop and report before continuing.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsServer/src/common/KeggGraph/store.py \
        PaintomicsServer/src/tests/test_kegg_graph_store.py
git commit -m "Derive the KEGG graph on demand, cache it, fall back to the legacy file" -- \
        PaintomicsServer/src/common/KeggGraph/store.py \
        PaintomicsServer/src/tests/test_kegg_graph_store.py
```

---

## Task 4: The scorer

**Files:**
- Create: `PaintomicsServer/src/common/KeggGraph/scorer.py`
- Test: `PaintomicsServer/src/tests/test_hub_scorer.py`

**Interfaces:**
- Consumes: `KeggGraph.rings`, `KeggGraph.compounds`, `KeggGraph.genes`.
- Produces:
  ```python
  HUB_SCHEMA_VERSION = 2
  def score(graph, measured: set[str], relevant: set[str], steps: int = 4) -> list[dict]
  # each row: {"schema": 2, "name", "step", "density", "percentile",
  #            "pvalue", "pvalue_adjust", "DEN", "noDEN", "ball_size",
  #            "ball_fraction"}
  ```

**Statistical decisions, from spec §6 and §6.1:**
1. `binomtest(DEN, DEN+noDEN, p=global_rate, alternative="greater")` — unchanged.
2. **One BH family across all four steps** (D-4). The R code ran four families over nested, near-perfectly dependent tests.
3. **Percentile background stratified by ball size** (spec §6.1 option 3): a compound's density is ranked against background compounds in the same ball-size quintile, not against all compounds. This is the agreed answer to the size–power confound. `ball_fraction` is reported so a reader can see when a radius covers most of the network.
4. `schema` on every row so a reopened old job cannot silently disagree with a re-run.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_hub_scorer.py`:

```python
#!/usr/bin/env python3
"""The hub statistic, in Python.

Two defects in the R scorer were fixed in 93637565 and are re-asserted here so
they cannot come back: step 3 took step 2's successes against step 3's total,
and `p.adjust` was called per-row on a SCALAR, which for length 1 reduces to
min(1, p*n) -- Bonferroni shipped under a "BH" label for four years.

Two changes are new:
  * one BH family across all four steps, not four families over nested tests;
  * the percentile background is stratified by ball size, so a compound is
    ranked against similarly-connected compounds. Radius 4 covers 46.9% of the
    mmu network for C00024, where the unstratified rank is close to meaningless.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge
from src.common.KeggGraph.scorer import HUB_SCHEMA_VERSION, score


def edge(a, b):
    return Edge(a, b, "PPrel", "", "tst00001", False)


def build():
    """C1 sits next to three DE genes; C2 next to three measured, none DE."""
    edges = [edge("C1", "g1"), edge("C1", "g2"), edge("C1", "g3"),
             edge("C2", "g4"), edge("C2", "g5"), edge("C2", "g6"),
             edge("g3", "g7"), edge("g6", "g8")]
    types = {"C1": "compound", "C2": "compound"}
    for name in ("g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"):
        types[name] = "gene"
    return KeggGraph(edges, types, "test")


class ScorerTest(unittest.TestCase):
    def setUp(self):
        self.graph = build()
        self.measured = {"g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8",
                         "C1", "C2"}
        self.relevant = {"g1", "g2", "g3", "C1", "C2"}
        self.rows = score(self.graph, self.measured, self.relevant, steps=4)
        self.step1 = {r["name"]: r for r in self.rows if r["step"] == 1}

    def test_every_row_carries_the_schema_version(self):
        self.assertTrue(all(r["schema"] == HUB_SCHEMA_VERSION for r in self.rows))

    def test_counts_are_right_for_the_enriched_compound(self):
        row = self.step1["C1"]
        self.assertEqual((row["DEN"], row["noDEN"]), (3, 0))
        self.assertAlmostEqual(row["density"], 1.0)

    def test_counts_are_right_for_the_depleted_compound(self):
        row = self.step1["C2"]
        self.assertEqual((row["DEN"], row["noDEN"]), (0, 3))
        self.assertAlmostEqual(row["density"], 0.0)

    def test_enriched_compound_has_the_smaller_pvalue(self):
        self.assertLess(self.step1["C1"]["pvalue"], self.step1["C2"]["pvalue"])

    def test_zero_measured_neighbours_scores_p_equals_one(self):
        rows = score(self.graph, {"C1"}, {"C1"}, steps=4)
        self.assertTrue(all(r["pvalue"] == 1.0 for r in rows))

    def test_bh_is_one_family_across_all_four_steps(self):
        """D-4. Four separate families would make each step's max adjust to its
        own step count, not to the total row count."""
        raw = sorted(r["pvalue"] for r in self.rows)
        adjusted = [r["pvalue_adjust"] for r in
                    sorted(self.rows, key=lambda r: r["pvalue"])]
        n = len(raw)
        expected = min(1.0, raw[0] * n / 1)
        self.assertAlmostEqual(adjusted[0], expected, places=9)

    def test_adjusted_is_never_below_raw(self):
        for row in self.rows:
            self.assertGreaterEqual(row["pvalue_adjust"] + 1e-12, row["pvalue"])

    def test_ball_fraction_is_reported(self):
        for row in self.rows:
            self.assertGreaterEqual(row["ball_fraction"], 0.0)
            self.assertLessEqual(row["ball_fraction"], 1.0)

    def test_percentile_is_within_range(self):
        for row in self.rows:
            self.assertGreaterEqual(row["percentile"], 0.0)
            self.assertLessEqual(row["percentile"], 1.0)

    def test_no_relevant_compounds_scores_every_measured_one(self):
        rows = score(self.graph, self.measured, {"g1"}, steps=4)
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"C1", "C2"})

    def test_rows_cover_every_step(self):
        self.assertEqual(sorted({r["step"] for r in self.rows}), [1, 2, 3, 4])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_scorer`
Expected: FAIL — `No module named 'src.common.KeggGraph.scorer'`

- [ ] **Step 3: Write the implementation**

Create `PaintomicsServer/src/common/KeggGraph/scorer.py`:

```python
"""Is the transcriptional response concentrated around this metabolite?

For each measured compound, the genes within k = 1..4 steps are tested for
enrichment in differentially expressed genes against the DE rate among all
measured KEGG genes. This is not topological hubness: no centrality is computed.

Replaces hubAnalysis.R (333 lines) with three library calls. The R version
re-read a 13 MB CSV and 1,865 .RData files on every job -- I/O proportional to
the species, not to the user's dataset -- for a measured 2.7-3.0 s per job.
"""
from __future__ import annotations

import logging

import numpy as np
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests

logger = logging.getLogger(__name__)

HUB_SCHEMA_VERSION = 2
_QUINTILES = 5


def _percentile_stratified_by_size(densities, sizes, background_mask):
    """Rank each density against background compounds of similar ball size.

    An unstratified ECDF ranks a hub metabolite whose radius-4 ball covers half
    the network against compounds with a handful of neighbours. Power scales
    with ball size, so that comparison mostly measures connectivity. Quintiles
    of ball size make the comparison like-for-like; a stratum with no background
    member falls back to the global background rather than returning nothing.
    """
    out = np.zeros(len(densities))
    if not background_mask.any():
        return out
    edges = np.quantile(sizes, np.linspace(0, 1, _QUINTILES + 1)[1:-1])
    stratum = np.searchsorted(edges, sizes, side="right")
    global_bg = np.sort(densities[background_mask])
    for index in range(len(densities)):
        local = background_mask & (stratum == stratum[index])
        pool = np.sort(densities[local]) if local.sum() >= 2 else global_bg
        if pool.size == 0:
            continue
        out[index] = np.searchsorted(pool, densities[index], side="right") / pool.size
    return out


def score(graph, measured, relevant, steps=4):
    """One row per (compound, radius). See HUB_SCHEMA_VERSION for the contract."""
    measured, relevant = set(measured), set(relevant)
    kegg_genes = [g for g in graph.genes() if g in measured]
    if not kegg_genes:
        logger.info("[hub] no measured gene is in the KEGG graph; no hub rows")
        return []
    de_genes = {g for g in kegg_genes if g in relevant}
    global_rate = len(de_genes) / float(len(kegg_genes))

    all_compounds = graph.compounds()
    measured_compounds = [c for c in all_compounds if c in measured]
    focus = [c for c in measured_compounds if c in relevant]
    if not focus:
        # Same fallback the R code had: with no relevant metabolite, treat every
        # measured one as of interest rather than returning an empty table.
        focus = measured_compounds
    if not focus:
        return []

    gene_index = {g: i for i, g in enumerate(kegg_genes)}
    is_de = np.zeros(len(kegg_genes), dtype=bool)
    for gene in de_genes:
        is_de[gene_index[gene]] = True
    node_total = float(len(graph.names)) or 1.0

    # Rings for every compound: the background needs all of them, and at
    # ~1.3 ms/seed the whole of mmu is ~2.4 s.
    rings = {c: graph.rings(c, steps) for c in all_compounds}

    rows, focus_set = [], set(focus)
    for step in range(1, steps + 1):
        names, density, den, no_den, ball = [], [], [], [], []
        for compound in all_compounds:
            cumulative = [n for r in rings[compound][:step] for n in r]
            codes = [gene_index[n] for n in cumulative if n in gene_index]
            unique = np.unique(codes) if codes else np.array([], dtype=int)
            hits = int(is_de[unique].sum()) if unique.size else 0
            total = int(unique.size)
            names.append(compound)
            den.append(hits)
            no_den.append(total - hits)
            density.append(hits / float(total) if total else 0.0)
            ball.append(len(cumulative))
        density = np.asarray(density)
        sizes = np.asarray(ball, dtype=float)
        background = np.array([n not in focus_set for n in names])
        percentile = _percentile_stratified_by_size(density, sizes, background)
        for index, compound in enumerate(names):
            if compound not in focus_set:
                continue
            total = den[index] + no_den[index]
            pvalue = (binomtest(den[index], total, global_rate,
                                alternative="greater").pvalue
                      if total else 1.0)
            rows.append({
                "schema": HUB_SCHEMA_VERSION,
                "name": compound,
                "step": step,
                "density": round(float(density[index]), 4),
                "percentile": float(percentile[index]),
                "pvalue": float(pvalue),
                "pvalue_adjust": None,          # filled below, one family
                "DEN": den[index],
                "noDEN": no_den[index],
                "ball_size": ball[index],
                "ball_fraction": round(ball[index] / node_total, 4),
            })

    # D-4: ONE BH family over all four radii. The R code adjusted inside
    # processData(), which ran once per step, so four nested and near-perfectly
    # dependent tests became four families and were then shown in one grid.
    if rows:
        adjusted = multipletests([r["pvalue"] for r in rows], method="fdr_bh")[1]
        for row, value in zip(rows, adjusted):
            row["pvalue_adjust"] = float(value)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_scorer`
Expected: `Ran 11 tests ... OK`

- [ ] **Step 5: Time it against a real organism**

Run:
```bash
cd PaintomicsServer && python -c "
import random, time
from src.common.KeggGraph import store
from src.common.KeggGraph.scorer import score
g = store.get_graph('mmu')
random.seed(7)
genes = g.genes(); comps = g.compounds()
measured = set(random.sample(genes, 6000)) | set(random.sample(comps, 120))
relevant = set(random.sample(sorted(measured), 900))
t = time.perf_counter(); rows = score(g, measured, relevant)
print('%d rows in %.2fs' % (len(rows), time.perf_counter()-t))
"
```
Expected: well under the 2.7–3.0 s the R scorer took. Record the number.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsServer/src/common/KeggGraph/scorer.py \
        PaintomicsServer/src/tests/test_hub_scorer.py
git commit -m "Score metabolite hubs in Python, one BH family, size-stratified rank" -- \
        PaintomicsServer/src/common/KeggGraph/scorer.py \
        PaintomicsServer/src/tests/test_hub_scorer.py
```

---

## Task 5: Wire the job to Python, delete the Rscript call

**Files:**
- Modify: `PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py` — `hubAnalysis()` at `:2716-2787`, `getCompoundRegulateFeatures()` at `:2623-2679`, `_loadCompoundNeighbourMap` at `:113-177`, the guard at `:134-144`
- Test: `PaintomicsServer/src/tests/test_hub_analysis_survives_reopen.py` (extend)

**Interfaces:**
- Consumes: `store.get_graph`, `scorer.score`, `HUB_SCHEMA_VERSION`.
- Produces: `hubAnalysisResult` stays `{int_index: row}` so `toBSON`/`parseBSON` and `PAINTOMICS4_DICT_FIELDS` are untouched — but each row is now the **dict** from Task 4 rather than an 8-element list. `getCompoundRegulateFeatures()` keeps returning `{compoundID: {"1": [...], ..., "4": [...]}}` (cumulative balls, as today).

- [ ] **Step 1: Write the failing test**

Append to `PaintomicsServer/src/tests/test_hub_analysis_survives_reopen.py`, before `def main()`:

```python
class HubAnalysisUsesPythonTest(unittest.TestCase):
    """No Rscript, and the stored rows carry a schema version."""

    def test_no_rscript_is_invoked_for_hub(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "classes", "JobInstances",
            "PathwayAcquisitionJob.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("hubAnalysis.R", source)
        self.assertIn("KeggGraph", source)

    def test_rows_are_dicts_carrying_the_schema(self):
        from src.common.KeggGraph.scorer import HUB_SCHEMA_VERSION
        from src.common.KeggGraph.graph import KeggGraph
        from src.common.KeggGraph.parser import Edge
        from src.common.KeggGraph.scorer import score
        graph = KeggGraph(
            [Edge("C1", "g1", "PPrel", "", "p", False),
             Edge("C1", "g2", "PPrel", "", "p", False)],
            {"C1": "compound", "g1": "gene", "g2": "gene"}, "test")
        rows = score(graph, {"C1", "g1", "g2"}, {"C1", "g1"})
        self.assertTrue(rows)
        self.assertEqual(rows[0]["schema"], HUB_SCHEMA_VERSION)
        self.assertIn("ball_fraction", rows[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_analysis_survives_reopen`
Expected: FAIL — `test_no_rscript_is_invoked_for_hub`, because `hubAnalysis.R` is still referenced.

- [ ] **Step 3: Replace `hubAnalysis()`**

In `PathwayAcquisitionJob.py`, replace the whole body of `hubAnalysis` (`:2716-2787`) with:

```python
    def hubAnalysis(self, ROOT_DIRECTORY):
        """Metabolite hub analysis. Pure Python since 2026-08.

        Was: write two CSVs, fork Rscript hubAnalysis.R, read a headerless
        8-column TSV back. The R side re-read a 13 MB CSV and 1,865 .RData
        files on every job -- I/O proportional to the species, not to the
        dataset. ROOT_DIRECTORY is kept in the signature for callers.
        """
        from src.common.KeggGraph import store
        from src.common.KeggGraph.scorer import score

        measured, relevant = set(), set()
        for geneID in self.inputGenesData:
            for values in self.inputGenesData[geneID].omicsValues:
                if values.omicName != 'Gene expression':
                    continue
                if values.relevant or values.relevantAssociation:
                    relevant.add(geneID)
                measured.add(geneID)
        for compoundID in self.inputCompoundsData:
            if self.inputCompoundsData[compoundID].omicsValues[0].relevant:
                relevant.add(compoundID)
            measured.add(compoundID)

        if not relevant:
            return False

        graph = store.get_graph(self.organism)
        if graph is None:
            logging.warning("HUB ANALYSIS - no graph available for %s; "
                            "skipping hub analysis.", self.organism)
            return False

        try:
            rows = score(graph, measured, relevant)
        except Exception as ex:
            # An enhancement panel must not take down the pathway results that
            # step 2 exists to produce.
            logging.warning("HUB ANALYSIS - failed for %s (%s); continuing "
                            "without hub results.", self.organism, str(ex))
            return False

        if not rows:
            return False
        self.hubAnalysisResult = {index: row for index, row in enumerate(rows)}
        return self.hubAnalysisResult
```

- [ ] **Step 4: Point `getCompoundRegulateFeatures()` at the store**

Replace the body of `getCompoundRegulateFeatures` (`:2623-2679`) from `inputCompoundIDs = ...` onwards with:

```python
        inputCompoundIDs = set((self.inputCompoundsData or {}).keys())
        if not inputCompoundIDs:
            return {}

        from src.common.KeggGraph import store
        graph = store.get_graph(self.organism)
        if graph is None:
            return {}

        # Cumulative balls, keyed by radius as a string -- the shape the Step 3
        # Paint handler and the Step 4 Neighbouring-features panel already read.
        result = {}
        for compoundID in inputCompoundIDs:
            rings = graph.rings(compoundID, 4)
            if not any(rings):
                continue
            cumulative, seen = {}, []
            for radius, ring in enumerate(rings, start=1):
                seen = seen + ring
                cumulative[str(radius)] = list(seen)
            result[compoundID] = cumulative

        if not result:
            logging.warning("HUB ANALYSIS - none of the %d input compounds "
                            "appear in the %s graph; check that both use KEGG "
                            "compound IDs.", len(inputCompoundIDs), self.organism)
        self.compoundRegulateFeatures = result
        return self.compoundRegulateFeatures
```

Then delete `_loadCompoundNeighbourMap` (`:113-177`) and its module-level cache, and the now-unused `_json` import if nothing else uses it. Keep the `isinstance(self.compoundRegulateFeatures, dict)` guard at `:2655` — `adaptBSON` still turns a reopened `None` into the string `"None"`.

- [ ] **Step 5: Run the suites**

Run:
```bash
cd PaintomicsServer && python -m src.tests.test_hub_analysis_survives_reopen \
  && python -m src.tests.test_neighbouring_features_survive_reopen \
  && python -m src.tests.test_cached_job_model_restore
```
Expected: all OK.

- [ ] **Step 6: Verify in Chrome (mandatory)**

1. `kill $(lsof -ti:8000)` then `cd PaintomicsServer && /Users/tianyuan/miniforge3/envs/paintomics4/bin/python src/launch_server.py`
2. Open `http://localhost:8000/`, run the STATegra multi-omic example through Step 2 into Step 3.
3. Confirm the **Metabolite hub analysis** grid has rows, and that `read_console_messages` shows no errors.
4. Screenshot it. Never trigger `alert`/`confirm`/`prompt`.

- [ ] **Step 7: Commit**

```bash
git add PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py \
        PaintomicsServer/src/tests/test_hub_analysis_survives_reopen.py
git commit -m "Run the hub analysis in Python instead of forking Rscript" -- \
        PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py \
        PaintomicsServer/src/tests/test_hub_analysis_survives_reopen.py
```

---

## Task 6: Client reads named fields — one code path

**Files:**
- Modify: `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js:5782-5797`
- Test: `PaintomicsServer/src/tests/test_hub_network_view.py`

**Interfaces:**
- Consumes: `hubAnalysisResult` rows — **always** dicts with `schema >= 2`. The client never sees a legacy array.
- Produces: `paHubRow(raw)` — a global helper (so the node harness can extract it) mapping one row to `{Metabolite, ID, Step, Percentage, Percentile, DEN, noDEN, pvalue, padjust, ballFraction}`.

**Why there is no compatibility branch here.** Jobs are deleted after **7 days for guests and 14 days for registered users** (`resources/example_serverconf.py:98`, pinned by `src/tests/test_retention_matches_the_promise.py`), so legacy rows are a two-week problem and a permanent client branch is the wrong shape for it. Recovery reads the stored value at `PathwayAcquisitionServlet.py:868` without recomputing, so the fix belongs there: **if the stored rows are not schema 2, re-score instead of translating.** Scoring is milliseconds once the graph is cached, the recomputed numbers are the *corrected* ones rather than stale wrong ones, and the client keeps exactly one code path — one server-side `if` replaces a dual-shape reader.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_hub_network_view.py`:

```python
#!/usr/bin/env python3
"""A stored job must keep rendering after the result shape changes.

hub_result.csv was a headerless 8-column TSV read POSITIONALLY at
PA_Step3Views.js:5786-5794 -- the column order stated in exactly one place on
each side and versioned nowhere. Rows are dicts with a schema now, but jobs
stored before the change still hold arrays, so the client must accept both.

The helper is run in node, the same way test_neighbouring_features_button.py
runs paNeighbourRequest: extract the real function text, evaluate it, assert on
its JSON output.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

CLIENT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))),
    "PaintomicsClient", "public_html")
STEP3_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step3Views.js")
HUB_NETWORK_VIEW = os.path.join(CLIENT, "app", "view",
                                "PathwayAcquisitionViews",
                                "PA_Step3HubNetworkView.js")


def extract(source, name):
    match = re.search(r"var\s+%s\s*=\s*function" % re.escape(name), source)
    if match is None:
        raise AssertionError("%s() is not defined" % name)
    opening = source.index("{", match.end())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1] + ";"
    raise AssertionError("unbalanced braces in %s()" % name)


def run_in_node(body):
    with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
        source = handle.read()
    script = extract(source, "paHubRow") + "\n" + body
    directory = tempfile.mkdtemp(prefix="paintomics-hub-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True, text=True,
                              timeout=60)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class RecomputesStaleRowsTest(unittest.TestCase):
    """Legacy rows are re-scored on the server, never translated on the client."""

    def test_recovery_rescores_when_the_schema_is_stale(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "servlets",
            "PathwayAcquisitionServlet.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("safe_hubAnalysisResult")
        self.assertIn("HUB_SCHEMA_VERSION", source[max(0, start - 1500):start + 500])

    def test_client_has_no_legacy_branch(self):
        client = os.path.join(CLIENT, "app", "view",
                              "PathwayAcquisitionViews", "PA_Step3Views.js")
        with open(client, "r", encoding="utf-8") as handle:
            body = handle.read()
        start = body.index("var paHubRow")
        self.assertNotIn("Array.isArray", body[start:start + 1200])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HubRowTest(unittest.TestCase):
    def test_schema_2_dict_row_is_normalised(self):
        out = run_in_node(
            'console.log(JSON.stringify(paHubRow({schema:2,name:"C00042",'
            'step:1,density:0.25,percentile:0.5425,pvalue:0.9393,'
            'pvalue_adjust:1,DEN:1,noDEN:3,ball_size:4,ball_fraction:0.01})));')
        self.assertEqual(out["ID"], "C00042")
        self.assertEqual(out["Step"], 1)
        self.assertEqual(out["DEN"], 1)
        self.assertEqual(out["ballFraction"], 0.01)

@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class SyntaxTest(unittest.TestCase):
    def test_new_view_parses(self):
        if not os.path.exists(HUB_NETWORK_VIEW):
            self.skipTest("view not written yet (Task 8)")
        done = subprocess.run(["node", "--check", HUB_NETWORK_VIEW],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_network_view`
Expected: FAIL — `paHubRow() is not defined`

- [ ] **Step 3: Add `paHubRow` and use it**

In `PA_Step3Views.js`, immediately above `function PA_Step3HubAnalysis ()` (`:5765`), insert:

```javascript
/**
 * Map one hub-analysis row to the grid's field names.
 *
 * Rows used to arrive as a headerless 8-element array whose column order was
 * stated in exactly one place on each side and versioned nowhere: reordering
 * the R frame silently relabelled the whole grid with no error anywhere.
 * Since schema 2 they are named dicts, and this is the only place the names
 * are read.
 *
 * There is deliberately NO legacy branch. A job stored before schema 2 is
 * re-scored on the server rather than translated here -- the rows expire in at
 * most 14 days, and a re-score returns the corrected numbers instead of
 * faithfully preserving the wrong ones.
 */
var paHubRow = function (raw) {
	return {
		ID: raw.name,
		Step: raw.step,
		Percentage: raw.density,
		Percentile: raw.percentile,
		DEN: raw.DEN,
		noDEN: raw.noDEN,
		pvalue: raw.pvalue,
		padjust: raw.pvalue_adjust,
		ballFraction: raw.ball_fraction
	};
};
```

Then replace the push loop at `:5782-5797` with:

```javascript
		const hubAnalysisResult = this.model.getHubAnalysisResult();
		hubTable.length = 0;   // loadModel runs on every model load; appending
		                       // to the instance array showed job A's rows for job B
		for (let key in hubAnalysisResult) {
			let row = paHubRow(hubAnalysisResult[key]);
			row.Metabolite = this.model.mappingComp[row.ID] || row.ID;
			hubTable.push(row);
		}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_network_view`
Expected: `HubRowTest` 3 tests OK; `SyntaxTest` skipped.

- [ ] **Step 4b: Re-score stale rows on the server**

In `PathwayAcquisitionServlet.py`, immediately before `safe_hubAnalysisResult = _as_dict(jobInstance.hubAnalysisResult)` (`:868`):

```python
        # Rows stored before schema 2 came from the R scorer, computed on a
        # graph with mis-attributed subtypes and balls that could contain their
        # own seed. Re-score rather than render them: it costs milliseconds once
        # the organism's graph is cached, and it leaves the client exactly one
        # row shape to read. Jobs expire in at most 14 days, so this branch is
        # deletable then.
        from src.common.KeggGraph.scorer import HUB_SCHEMA_VERSION
        stored = jobInstance.hubAnalysisResult
        if isinstance(stored, dict) and stored:
            sample = next(iter(stored.values()))
            if not (isinstance(sample, dict)
                    and sample.get("schema") == HUB_SCHEMA_VERSION):
                logging.info("RECOVER_JOB - re-scoring stale hub rows for %s", jobID)
                jobInstance.hubAnalysis(ROOT_DIRECTORY)
```

- [ ] **Step 5: Verify in Chrome**

Restart the server. Load a job created **before** Task 5 (e.g. `M3Vpu1rdZH`, whose stored rows are the old 8-element arrays) and confirm the grid renders with **re-scored** values and the log shows `re-scoring stale hub rows`. Then run a fresh job and confirm it renders too. Screenshot both.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js \
        PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py \
        PaintomicsServer/src/tests/test_hub_network_view.py
git commit -m "Read hub rows by name; re-score stale rows instead of translating" -- \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js \
        PaintomicsServer/src/tests/test_hub_network_view.py
```

---

## Task 7: The subgraph route

**Files:**
- Modify: `PaintomicsServer/src/common/KeggGraph/graph.py` (add `subgraph`), `PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py`, `PaintomicsServer/src/paintomicsserver.py`, `PaintomicsClient/public_html/resources/ServerConfiguration.js`
- Test: `PaintomicsServer/src/tests/test_hub_subgraph_route.py`

**Interfaces:**
- Consumes: `KeggGraph`, `store.get_graph`.
- Produces:
  ```python
  KeggGraph.subgraph(seed, k, budget) -> {
      "seed": str, "source": str, "truncated": bool,
      "nodes": [{"id","type","step"}],           # step 0 is the seed
      "edges": [{"source","target","kind","subtype","pathway","reversible"}],
  }
  ```
  Route `POST /pa_hub_subgraph` with form fields `jobID`, `compoundID`, `level`.

- [ ] **Step 1: Write the failing test**

Create `PaintomicsServer/src/tests/test_hub_subgraph_route.py`:

```python
#!/usr/bin/env python3
"""The induced subgraph a network view draws, and who is allowed to ask for it.

The graph has always existed on the server and never reached the browser:
`compoundRegulateFeatures` ships node SETS with no pairs, no direction, no edge
types and no intermediate hops, so a client cannot tell whether a radius-3 gene
reaches the metabolite via gene X or gene Y. That is why no network was ever
drawn.

Two things the route must get right:
  * a cap must never read as "this is all there is" -- hence `truncated`;
  * `/check_job_status` ships hub payloads with NO session and NO ownership
    check (paintomicsserver.py:589-591). The new route does not repeat that.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge


def build():
    edges = [Edge("C1", "g1", "PPrel", "activation", "p1", False),
             Edge("C1", "g2", "reaction", "rn:R1", "p1", True),
             Edge("g1", "g3", "PPrel", "inhibition", "p2", False),
             Edge("g3", "g4", "PPrel", "", "p2", False)]
    types = {"C1": "compound", "g1": "gene", "g2": "gene",
             "g3": "gene", "g4": "gene"}
    return KeggGraph(edges, types, "test")


class SubgraphTest(unittest.TestCase):
    def setUp(self):
        self.graph = build()

    def test_seed_is_present_at_step_zero(self):
        out = self.graph.subgraph("C1", 2, 100)
        seed = [n for n in out["nodes"] if n["id"] == "C1"]
        self.assertEqual(len(seed), 1)
        self.assertEqual(seed[0]["step"], 0)

    def test_every_node_carries_its_hop_distance(self):
        steps = {n["id"]: n["step"] for n in self.graph.subgraph("C1", 3, 100)["nodes"]}
        self.assertEqual(steps["g1"], 1)
        self.assertEqual(steps["g2"], 1)
        self.assertEqual(steps["g3"], 2)
        self.assertEqual(steps["g4"], 3)

    def test_level_bounds_the_subgraph(self):
        ids = {n["id"] for n in self.graph.subgraph("C1", 1, 100)["nodes"]}
        self.assertEqual(ids, {"C1", "g1", "g2"})

    def test_edges_are_induced_on_the_returned_nodes(self):
        out = self.graph.subgraph("C1", 1, 100)
        ids = {n["id"] for n in out["nodes"]}
        for edge in out["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)

    def test_edge_attributes_survive(self):
        out = self.graph.subgraph("C1", 1, 100)
        found = {(e["source"], e["target"]): e for e in out["edges"]}
        pair = found.get(("C1", "g2")) or found.get(("g2", "C1"))
        self.assertEqual(pair["kind"], "reaction")
        self.assertTrue(pair["reversible"])

    def test_budget_truncates_and_says_so(self):
        out = self.graph.subgraph("C1", 3, 2)
        self.assertTrue(out["truncated"])
        self.assertLessEqual(len(out["edges"]), 2)

    def test_untruncated_result_says_so(self):
        self.assertFalse(self.graph.subgraph("C1", 1, 100)["truncated"])

    def test_unknown_seed_returns_an_empty_subgraph_not_an_error(self):
        out = self.graph.subgraph("NOPE", 2, 100)
        self.assertEqual(out["nodes"], [])
        self.assertEqual(out["edges"], [])

    def test_source_is_reported(self):
        self.assertEqual(self.graph.subgraph("C1", 1, 100)["source"], "test")


class RouteWiringTest(unittest.TestCase):
    """The route exists and is guarded. Read from source, like the two
    field-list tests in test_hub_analysis_survives_reopen.py."""

    def _read(self, *parts):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), *parts)
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_route_is_registered(self):
        self.assertIn("/pa_hub_subgraph", self._read("paintomicsserver.py"))

    def test_handler_checks_ownership(self):
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def hubSubgraph")
        body = source[start:start + 3000]
        self.assertIn("getUserID", body)
        self.assertIn("getAllowSharing", body)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_subgraph_route`
Expected: FAIL — `KeggGraph has no attribute 'subgraph'`

- [ ] **Step 3: Add `subgraph()` to `graph.py`**

Append to `class KeggGraph`:

```python
    def subgraph(self, seed, k, budget):
        """The induced subgraph of the seed's k-step ball, ranked and capped.

        Ranking is by hop distance then by endpoint degree, so a cap keeps the
        edges nearest the seed and drops the periphery -- the same rank-then-cap
        discipline the OmniPath and RegTarget views use. `truncated` exists so a
        cap can never read as "this is all there is".
        """
        empty = {"seed": seed, "source": self.source, "truncated": False,
                 "nodes": [], "edges": []}
        code = self._code.get(seed)
        if code is None:
            return empty

        step_of = {seed: 0}
        for radius, ring in enumerate(self.rings(seed, k), start=1):
            for name in ring:
                step_of.setdefault(name, radius)

        codes = {self._code[n] for n in step_of}
        picked = []
        for edge_id in range(len(self.edge_kind)):
            a = int(self.edge_src[edge_id])
            b = int(self.edge_dst[edge_id])
            if a in codes and b in codes:
                near = min(step_of[self.names[a]], step_of[self.names[b]])
                degree = ((self._indptr[a + 1] - self._indptr[a]) +
                          (self._indptr[b + 1] - self._indptr[b]))
                picked.append((near, -int(degree), edge_id))
        picked.sort()
        truncated = len(picked) > budget
        picked = picked[:budget]

        kept = set()
        edges = []
        for _near, _degree, edge_id in picked:
            a = self.names[int(self.edge_src[edge_id])]
            b = self.names[int(self.edge_dst[edge_id])]
            kept.add(a)
            kept.add(b)
            edges.append({
                "source": a, "target": b,
                "kind": self.edge_kind[edge_id],
                "subtype": self.edge_subtype[edge_id],
                "pathway": self.edge_pathway[edge_id],
                "reversible": bool(self.edge_reversible[edge_id]),
            })
        kept.add(seed)
        nodes = [{"id": name, "type": self.node_type.get(name),
                  "step": step_of.get(name, k)}
                 for name in sorted(kept)]
        return {"seed": seed, "source": self.source, "truncated": truncated,
                "nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Add the servlet handler**

In `PathwayAcquisitionServlet.py`, add:

```python
def hubSubgraph(request, response, QUEUE_INSTANCE):
    """The induced subgraph behind one row of the hub-analysis table.

    Ownership is checked the same way pa_recover_job does at :836-839. The
    endpoint that ships hubAnalysisResult today, /check_job_status, checks
    nothing at all -- that is a separate, broader fix; this route does not
    inherit it.
    """
    try:
        jobID = request.form.get("jobID")
        compoundID = request.form.get("compoundID")
        level = max(1, min(4, int(request.form.get("level", 1))))
        budget = max(1, min(2000, int(request.form.get("maxEdges", 400))))

        userID = request.cookies.get('userID')
        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            response.setContent({"success": False,
                                 "errorMessage": "Job " + str(jobID) + " not found."})
            return response
        if (str(jobInstance.getUserID()) != 'None'
                and jobInstance.getUserID() != userID
                and not jobInstance.getAllowSharing()):
            logging.info("HUB_SUBGRAPH - JOB %s DOES NOT BELONG TO USER %s",
                         jobID, str(userID))
            response.setContent({"success": False,
                                 "errorMessage": "Invalid Job ID for current user."})
            return response

        from src.common.KeggGraph import store
        graph = store.get_graph(jobInstance.getOrganism())
        if graph is None:
            response.setContent({"success": False,
                                 "errorMessage": "No interaction network is "
                                                 "installed for this organism."})
            return response
        payload = graph.subgraph(compoundID, level, budget)
        payload["success"] = True
        response.setContent(payload)
    except Exception as ex:
        logging.error("HUB_SUBGRAPH - %s", str(ex))
        response.setContent({"success": False, "errorMessage": str(ex)})
    return response
```

- [ ] **Step 5: Register the route and the client constant**

In `paintomicsserver.py`, beside the other STEP 3 handlers:

```python
        @self.app.route(SERVER_SUBDOMAIN + '/pa_hub_subgraph', methods=['OPTIONS', 'POST'])
        def hubSubgraphHandler():
            return hubSubgraph(request, Response(), self.queue).getResponse()
```

Add `hubSubgraph` to the existing `from src.servlets.PathwayAcquisitionServlet import ...` list.

In `resources/ServerConfiguration.js`, after line 142:

```javascript
SERVER_URL_PA_HUB_SUBGRAPH = SERVER_URL + "pa_hub_subgraph";
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_subgraph_route`
Expected: `Ran 11 tests ... OK`

- [ ] **Step 7: Exercise the route against the running server**

Restart the server, then:
```bash
curl -s -X POST http://localhost:8000/pa_hub_subgraph \
  -d "jobID=<a real jobID>" -d "compoundID=C00024" -d "level=2" \
  | python3 -m json.tool | head -30
```
Expected: `"success": true`, nodes carrying `step`, edges carrying `kind`/`subtype`/`pathway`. Then repeat with a `jobID` owned by another user and confirm the ownership refusal.

- [ ] **Step 8: Commit**

```bash
git add PaintomicsServer/src/common/KeggGraph/graph.py \
        PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py \
        PaintomicsServer/src/paintomicsserver.py \
        PaintomicsClient/public_html/resources/ServerConfiguration.js \
        PaintomicsServer/src/tests/test_hub_subgraph_route.py
git commit -m "Serve the induced subgraph behind a hub row, with an ownership check" -- \
        PaintomicsServer/src/common/KeggGraph/graph.py \
        PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py \
        PaintomicsServer/src/paintomicsserver.py \
        PaintomicsClient/public_html/resources/ServerConfiguration.js \
        PaintomicsServer/src/tests/test_hub_subgraph_route.py
```

---

## Task 8: The hop-ring network view

**Files:**
- Create: `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3HubNetworkView.js`
- Modify: `PaintomicsClient/public_html/index.html:150-155`, `PaintomicsClient/public_html/resources/css/network-views.css:46-48`, `PA_Step3Views.js` (row action + mount)
- Test: `PaintomicsServer/src/tests/test_hub_network_view.py` (the `SyntaxTest` stops skipping)

**Interfaces:**
- Consumes: `SERVER_URL_PA_HUB_SUBGRAPH`, the subgraph payload from Task 7, `paHubRow` from Task 6.
- Produces: `PA_Step3HubNetworkView` with `setController`, `setParent`, `loadModel`, `getComponent`, and `showCompound(compoundID, level)`.

**Design constraints, all learned the hard way in this codebase:**
- `concentric` layout with `concentric: node => 5 - node.data('step')` so step 1 is the innermost ring and the seed is the centre.
- All four rings are drawn; the step control **lights one and dims the rest**, it does not add nodes. Use `cy.batch()` and class toggles — hide-don't-remove, as `PA_Step3RegTargetNetworkView.js:535-580` does.
- **`paDeferFrame` on `afterrender`, not `requestAnimationFrame`** — rAF never fires in a background tab and the panel comes up permanently blank.
- Resolve the container height to pixels **before** constructing Cytoscape; it measures its container once.
- `beforedestroy -> cy.destroy()`; `expand -> cy.resize()` then `fit`.
- Draw arrowheads **only** when `edge.subtype` is a known effect vocabulary term and `graph.source === "kgml"`. The legacy fallback carries no subtypes, and drawing direction from it would be inventing biology.
- Announce truncation whenever `payload.truncated` is true.

- [ ] **Step 1: Write the failing test**

The `SyntaxTest.test_new_view_parses` case already exists in `test_hub_network_view.py` from Task 6 and currently skips. Add to that file:

```python
@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HubNetworkViewContractTest(unittest.TestCase):
    def source(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_uses_defer_frame_not_raf(self):
        """rAF never fires in a background tab; the panel came up blank."""
        body = self.source()
        self.assertIn("paDeferFrame", body)
        self.assertNotIn("requestAnimationFrame", body)

    def test_destroys_cytoscape_on_teardown(self):
        self.assertIn("beforedestroy", self.source())
        self.assertIn("destroy()", self.source())

    def test_announces_truncation(self):
        self.assertIn("truncated", self.source())

    def test_does_not_draw_arrows_from_the_legacy_source(self):
        self.assertIn("legacy-json", self.source())

    def test_hop_distance_is_not_encoded_as_colour(self):
        """Rings already carry distance; spending hue on it too would leave
        nothing for DE direction, which is what the panel exists to show."""
        body = self.source()
        self.assertNotIn('"background-color": "data(step)"', body)
        self.assertIn("node[state = 'up']", body)
        self.assertIn("node[state = 'down']", body)

    def test_labels_are_selective(self):
        """Radius 4 can reach thousands of nodes; a label on each is unreadable."""
        self.assertIn("showLabel", self.source())

    def test_has_a_legend_and_a_hover_layer(self):
        body = self.source()
        self.assertIn("pa-hub-legend", body)
        self.assertIn("mouseover", body)

    def test_ring_guides_use_createElementNS(self):
        """svg.js 2.0.5's .path() reads pathSegList, removed in Chrome 48."""
        body = self.source()
        self.assertIn("createElementNS", body)
        self.assertNotIn(".path(", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_network_view`
Expected: FAIL — `HUB_NETWORK_VIEW` does not exist.

- [ ] **Step 3: Write the view**

**Encoding decisions** (run through the dataviz method; color chosen last):

| channel | carries | why |
|---|---|---|
| **position** (ring) | hop distance 1-4 | the concentric layout already encodes it — so distance must **not** also take color |
| **fill colour** | DE direction: down / up | the scientific payload, and the only thing left worth a hue |
| **filled vs hollow** | DE vs measured-not-DE | secondary encoding, so identity is never colour-alone |
| **stroke dash** | measured vs never measured | absence shown as absence, not as another colour |
| **shape** | compound (diamond) vs gene (ellipse) | node kind, independent of signal |
| **size** | seed only (28px vs 13px) | one emphasis, not a second magnitude scale |

Palette, **validated, not eyeballed** — `node scripts/validate_palette.js "#2a78d6,#e34948" --mode light`
returns ALL CHECKS PASS: CVD ΔE **21.6** light / **19.2** dark against a ≥8 target,
normal-vision ΔE **32.3 / 29.0** against a ≥15 floor, both poles ≥3:1 on the surface.
The near-white diverging midpoint `#f0efec` was **rejected** — the validator scored it
1.12:1, and "measured but not DE" is most of the graph, so those nodes would have been
invisible. They are hollow instead: surface fill, and the *stroke* carries the contrast.

Create `PA_Step3HubNetworkView.js`:

```javascript
function PA_Step3HubNetworkView() {
	this.name = "PA_Step3HubNetworkView";
	// Randomised ids: Step 3 can hold more than one network panel and Ext
	// reuses component ids across job loads.
	var salt = Math.floor(Math.random() * 1e9);
	this.canvasID = "hubNetCanvas" + salt;
	this.ringsID  = "hubNetRings" + salt;
	this.noticeID = "hubNetNotice" + salt;
	this.tipID    = "hubNetTip" + salt;
	this.cy = null;
	this.level = 1;
	this.payload = null;

	this.loadModel = function (model) { this.model = model; };

	this.showCompound = function (compoundID, level) {
		var me = this;
		me.level = Math.max(1, Math.min(4, parseInt(level, 10) || 1));
		$("#" + me.noticeID).text("Loading the neighbourhood of " + compoundID + "…");
		$.post(SERVER_URL_PA_HUB_SUBGRAPH, {
			jobID: me.model.getJobID(),
			compoundID: compoundID,
			level: 4,                  // fetch all four; the control dims, never refetches
			maxEdges: 400
		}).done(function (payload) {
			if (!payload || !payload.success) {
				$("#" + me.noticeID).text(
					(payload && payload.errorMessage) || "No network available.");
				return;
			}
			if (!payload.nodes.length) {
				$("#" + me.noticeID).text(
					compoundID + " has no neighbours in the KEGG network for this organism.");
				return;
			}
			me.payload = payload;
			me.render(payload);
		}).fail(function () {
			$("#" + me.noticeID).text("Could not reach the server.");
		});
	};

	/** DE state for one feature, from the expression data the job already ships. */
	this.stateOf = function (id) {
		var data = this.model.getGlobalExpressionData ?
			this.model.getGlobalExpressionData() : null;
		var entry = data && ((data.inputGene && data.inputGene[id]) ||
		                     (data.inputCompound && data.inputCompound[id]));
		if (!entry) { return "absent"; }              // never measured
		if (!(entry.relevant || entry.relevantAssociation)) { return "quiet"; }
		var first = (entry.values && entry.values.length) ? entry.values[0] : 0;
		return first < 0 ? "down" : "up";
	};

	this.elements = function (payload) {
		var me = this, out = [];
		payload.nodes.forEach(function (n) {
			var state = n.step === 0 ? "seed" : me.stateOf(n.id);
			out.push({ group: "nodes", data: {
				id: n.id,
				label: (n.id === payload.seed) ? (me.model.mappingComp[n.id] || n.id) : n.id,
				step: n.step, kind: n.type, state: state,
				seed: n.step === 0 ? 1 : 0,
				// Only the seed and the DE nodes are labelled. A label on every
				// node is unreadable past ~40 and radius 4 can reach thousands.
				showLabel: (n.step === 0 || state === "up" || state === "down") ? 1 : 0
			}});
		});
		payload.edges.forEach(function (e, i) {
			out.push({ group: "edges", data: {
				id: "e" + i, source: e.source, target: e.target,
				kind: e.kind, subtype: e.subtype, pathway: e.pathway,
				// Arrowheads ONLY from a real subtype on a real KGML parse. The
				// legacy-json fallback carries none, and drawing direction from
				// it would be inventing biology.
				directed: (payload.source !== "legacy-json" && e.subtype) ? 1 : 0,
				inhibits: /inhibition|repression/.test(e.subtype || "") ? 1 : 0
			}});
		});
		return out;
	};

	this.render = function (payload) {
		var me = this;
		$("#" + me.noticeID).text(payload.truncated
			? ("Showing the 400 edges closest to " + payload.seed +
			   " — the full neighbourhood is larger.")
			: "");

		var host = document.getElementById(me.canvasID);
		if (!host) { return; }
		// Cytoscape measures its container once, so the height must be real
		// BEFORE construction or the graph lays out into a zero-height box.
		// Height normally comes from --pa-net-canvas-height (720px) via
		// .pa-net-canvas in network-views.css:309-319 -- do not hardcode over
		// it; only force a value if the class produced nothing, which happens
		// while the panel is still collapsed.
		if (host.getBoundingClientRect().height === 0) { host.style.height = "520px"; }

		if (me.cy) { me.cy.destroy(); me.cy = null; }
		me.cy = cytoscape({
			container: host,
			elements: me.elements(payload),
			minZoom: 0.2, maxZoom: 3,
			layout: {
				name: "concentric",
				concentric: function (n) { return 5 - n.data("step"); },
				levelWidth: function () { return 1; },
				minNodeSpacing: 22, avoidOverlap: true, animate: false,
				padding: 28
			},
			style: [
				{ selector: "node", style: {
					"width": 13, "height": 13,
					"background-color": "var(--hub-quiet)",
					// 2px surface ring so overlapping marks stay separable
					"border-width": 1.5, "border-color": "var(--hub-quiet-ink)",
					"label": "", "font-size": 10, "font-family": "inherit",
					"color": "var(--hub-ink)",
					"text-margin-y": -3, "text-background-color": "var(--hub-surface)",
					"text-background-opacity": 0.85, "text-background-padding": 2,
					"transition-property": "opacity", "transition-duration": "120ms" }},
				{ selector: "node[kind = 'compound']", style: { "shape": "diamond",
					"width": 15, "height": 15 }},
				{ selector: "node[state = 'up']", style: {
					"background-color": "var(--hub-up)", "border-color": "var(--hub-up)" }},
				{ selector: "node[state = 'down']", style: {
					"background-color": "var(--hub-down)", "border-color": "var(--hub-down)" }},
				{ selector: "node[state = 'absent']", style: {
					"border-style": "dashed", "border-color": "var(--hub-absent)" }},
				{ selector: "node[seed = 1]", style: {
					"shape": "diamond", "width": 28, "height": 28,
					"background-color": "var(--hub-surface)",
					"border-width": 3, "border-color": "var(--hub-ink)",
					"font-size": 12, "font-weight": "bold" }},
				{ selector: "node[showLabel = 1]", style: { "label": "data(label)" }},
				{ selector: "edge", style: {
					"width": 1, "line-color": "var(--hub-edge)",
					"curve-style": "bezier", "opacity": 0.75 }},
				{ selector: "edge[directed = 1]", style: {
					"target-arrow-shape": "triangle", "arrow-scale": 0.6,
					"target-arrow-color": "var(--hub-edge)" }},
				{ selector: "edge[inhibits = 1]", style: {
					"target-arrow-shape": "tee" }},
				{ selector: ".dim", style: { "opacity": 0.08 }},
				{ selector: ".lit", style: { "opacity": 1 }},
				{ selector: ".hover", style: {
					"border-width": 3, "border-color": "var(--hub-ink)" }}
			]
		});

		me.cy.one("layoutstop", function () { me.drawRings(); });
		me.cy.on("pan zoom resize", function () { me.drawRings(); });
		me.bindHover();
		me.setLevel(me.level);
	};

	/** Faint guide circles + a "step N" label, so the rings READ as steps
	 *  rather than as an accident of the layout. Built with createElementNS:
	 *  svg.js 2.0.5's .path() reads pathSegList, removed in Chrome 48, which is
	 *  why no diagram in this application had ever carried a vector. */
	this.drawRings = function () {
		var me = this, cy = me.cy;
		var svg = document.getElementById(me.ringsID);
		if (!cy || !svg) { return; }
		while (svg.firstChild) { svg.removeChild(svg.firstChild); }
		var seed = cy.nodes("[seed = 1]");
		if (!seed.length) { return; }
		var origin = seed.position(), pan = cy.pan(), zoom = cy.zoom();
		var radii = {};
		cy.nodes().forEach(function (n) {
			var step = n.data("step");
			if (!step) { return; }
			var dx = n.position("x") - origin.x, dy = n.position("y") - origin.y;
			(radii[step] = radii[step] || []).push(Math.sqrt(dx * dx + dy * dy));
		});
		var cx = origin.x * zoom + pan.x, cy0 = origin.y * zoom + pan.y;
		Object.keys(radii).sort().forEach(function (step) {
			var list = radii[step];
			var mean = list.reduce(function (a, b) { return a + b; }, 0) / list.length;
			var r = mean * zoom;
			var circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
			circle.setAttribute("cx", cx); circle.setAttribute("cy", cy0);
			circle.setAttribute("r", r);
			circle.setAttribute("class", "pa-hub-ring" +
				(String(step) === String(me.level) ? " is-current" : ""));
			svg.appendChild(circle);
			var text = document.createElementNS("http://www.w3.org/2000/svg", "text");
			text.setAttribute("x", cx); text.setAttribute("y", cy0 - r - 5);
			text.setAttribute("text-anchor", "middle");
			text.setAttribute("class", "pa-hub-ring-label" +
				(String(step) === String(me.level) ? " is-current" : ""));
			text.textContent = "step " + step;
			svg.appendChild(text);
		});
	};

	this.bindHover = function () {
		var me = this, tip = document.getElementById(me.tipID);
		me.cy.on("mouseover", "node", function (event) {
			var n = event.target;
			n.addClass("hover");
			var state = { up: "up", down: "down", quiet: "measured, not DE",
			              absent: "not measured", seed: "this metabolite" }[n.data("state")];
			tip.innerHTML = "<b>" + n.data("label") + "</b><br>" +
				n.data("kind") + " · " + state +
				(n.data("step") ? "<br>" + n.data("step") + " step" +
				 (n.data("step") === 1 ? "" : "s") + " away" : "");
			tip.style.display = "block";
		});
		me.cy.on("mouseout", "node", function (event) {
			event.target.removeClass("hover");
			tip.style.display = "none";
		});
		me.cy.on("mousemove", function (event) {
			tip.style.left = (event.renderedPosition.x + 14) + "px";
			tip.style.top = (event.renderedPosition.y + 14) + "px";
		});
		me.cy.on("mouseover", "edge", function (event) {
			var e = event.target;
			tip.innerHTML = "<b>" + e.data("source") + " — " + e.data("target") + "</b><br>" +
				e.data("kind") + (e.data("subtype") ? " · " + e.data("subtype") : "") +
				"<br>" + e.data("pathway");
			tip.style.display = "block";
		});
		me.cy.on("mouseout", "edge", function () { tip.style.display = "none"; });
	};

	/** Light one ring, dim the rest. Hide-don't-remove: removing elements
	 *  forces a relayout and the rings jump between steps. */
	this.setLevel = function (level) {
		var me = this;
		me.level = level;
		if (!me.cy) { return; }
		me.cy.batch(function () {
			me.cy.nodes().forEach(function (n) {
				var step = n.data("step");
				n.toggleClass("dim", !(step === 0 || step <= level));
				n.toggleClass("lit", step === level || step === 0);
			});
			me.cy.edges().forEach(function (e) {
				e.toggleClass("dim",
					e.source().hasClass("dim") || e.target().hasClass("dim"));
			});
		});
		me.drawRings();
	};

	this.getComponent = function () {
		var me = this;
		var steps = [1, 2, 3, 4].map(function (n) {
			return { xtype: "button", text: String(n), enableToggle: true,
			         toggleGroup: "hubNetStep" + me.canvasID, pressed: n === 1,
			         handler: function () { me.setLevel(n); } };
		});
		var legend =
			'<div class="pa-hub-legend">' +
			  '<span><i class="sw up"></i>up</span>' +
			  '<span><i class="sw down"></i>down</span>' +
			  '<span><i class="sw quiet"></i>measured, not DE</span>' +
			  '<span><i class="sw absent"></i>not measured</span>' +
			  '<span><i class="sw seed"></i>this metabolite</span>' +
			'</div>';
		this.component = Ext.create("Ext.panel.Panel", {
			title: "Metabolite neighbourhood", cls: "pa-hub-net-toolbar pa-hub-net",
			hidden: true, collapsible: true,
			html: '<div id="' + me.noticeID + '" class="pa-net-notice"></div>' +
			      legend +
			      '<div class="pa-hub-stage">' +
			        '<svg id="' + me.ringsID + '" class="pa-hub-rings"></svg>' +
			        '<div id="' + me.canvasID + '" class="pa-net-canvas"></div>' +
			        '<div id="' + me.tipID + '" class="pa-hub-tip"></div>' +
			      '</div>',
			bbar: [{ xtype: "tbtext", text: "Steps from the metabolite:" }].concat(steps),
			listeners: {
				// paDeferFrame, NOT requestAnimationFrame: rAF never runs in a
				// background tab and the panel came up permanently blank.
				afterrender: function () { paDeferFrame(function () {
					if (me.cy) { me.cy.resize(); me.cy.fit(); me.drawRings(); } }); },
				expand: function () {
					if (me.cy) { me.cy.resize(); me.cy.fit(); me.drawRings(); } },
				beforedestroy: function () {
					if (me.cy) { me.cy.destroy(); me.cy = null; } }
			}
		});
		return this.component;
	};
}
PA_Step3HubNetworkView.prototype = new View();
```

The **Network** row action added in Step 4 calls `showCompound(row.ID, row.Step)` and
then `me.hubNetworkView.getComponent().show()` so the panel appears on first use.

- [ ] **Step 4: Register it**

`index.html`, after line 155:
```html
	<!--METABOLITE HUB NETWORK (hop rings around one metabolite) -->
	<script type="text/javascript" src="app/view/PathwayAcquisitionViews/PA_Step3HubNetworkView.js?v=0.1"></script>
```

`resources/css/network-views.css`: add `.pa-hub-net-toolbar` to the shared selector
list at `:46-48` — do not create a private stylesheet; the header comment at `:1-32`
states the one-design-system position. `.pa-net-canvas` already exists at `:312`/`:319`
and carries `--pa-net-canvas-height: 720px` from `:309`, so the view inherits its
height from there and must not hardcode over it.

Everything below is **new** — none of these classes exist in the tree today. Append:

```css
/* ---- Metabolite hop-ring network ------------------------------------- */
/* Colours are validated, not chosen by eye: the two poles clear CVD ΔE 21.6
   (target ≥8) and normal-vision ΔE 32.3 (floor ≥15) against the light surface.
   Hop distance is carried by RING POSITION, so it deliberately takes no colour;
   the hue is spent on DE direction, which is what the panel exists to show.
   NOTE: this application ships light-only — there is no prefers-color-scheme
   rule anywhere in resources/css. The validated dark steps are recorded here
   for whenever a theme lands: --hub-up #e66767, --hub-down #3987e5,
   surface #1a1a19 (CVD ΔE 19.2, normal-vision 29.0). Do not add a dark block
   for this component alone; it would be the only one in the app. */
.pa-hub-net {
	--hub-up:        #e34948;
	--hub-down:      #2a78d6;
	--hub-quiet:     #ffffff;   /* hollow: the STROKE carries the contrast.   */
	--hub-quiet-ink: #595959;   /* #f0efec was rejected at 1.12:1 on white.   */
	--hub-absent:    #a1a1aa;
	--hub-edge:      #d4d4d8;
	--hub-ring:      #e7e7e4;
	--hub-ink:       var(--pa-ink, #18181b);
	--hub-muted:     var(--pa-ink-muted, #595959);
	--hub-surface:   var(--pa-surface, #ffffff);
}

/* Truncation and empty-state text above a network canvas. A cap must never
   read as "this is all there is" (PA_Step4OmniPathNetworkView.js:292-298). */
.pa-net-notice {
	min-height: 1.2em;
	margin: 0 0 6px 0;
	font-size: 12px;
	color: var(--hub-muted);
}
.pa-net-notice:empty { display: none; }

/* Legend is always present: identity must never be colour-alone. */
.pa-hub-legend {
	display: flex;
	flex-wrap: wrap;
	gap: 14px;
	margin: 0 0 8px 0;
	font-size: 12px;
	color: var(--hub-muted);
}
.pa-hub-legend span { display: inline-flex; align-items: center; gap: 5px; }
.pa-hub-legend .sw {
	width: 11px; height: 11px; border-radius: 50%;
	border: 1.5px solid var(--hub-quiet-ink); background: var(--hub-quiet);
}
.pa-hub-legend .sw.up     { background: var(--hub-up);   border-color: var(--hub-up); }
.pa-hub-legend .sw.down   { background: var(--hub-down); border-color: var(--hub-down); }
.pa-hub-legend .sw.absent { border-style: dashed; border-color: var(--hub-absent); }
.pa-hub-legend .sw.seed   {
	border-radius: 2px; transform: rotate(45deg);
	border-width: 2px; border-color: var(--hub-ink);
}

/* The SVG ring guides sit UNDER the Cytoscape canvas and never take pointer
   events, so hover and drag reach the graph unchanged. */
.pa-hub-stage { position: relative; }
.pa-hub-rings {
	position: absolute; inset: 0;
	width: 100%; height: 100%;
	pointer-events: none; z-index: 0;
}
.pa-hub-stage .pa-net-canvas { position: relative; z-index: 1; background: transparent; }
.pa-hub-ring {
	fill: none;
	stroke: var(--hub-ring);
	stroke-width: 1;
	stroke-dasharray: 3 4;
}
.pa-hub-ring.is-current { stroke: var(--hub-muted); stroke-dasharray: none; }
.pa-hub-ring-label {
	font-size: 10px;
	fill: var(--hub-muted);
	opacity: 0.75;
}
.pa-hub-ring-label.is-current { opacity: 1; font-weight: 600; }

.pa-hub-tip {
	position: absolute; z-index: 2; display: none;
	max-width: 260px; padding: 6px 8px;
	font-size: 12px; line-height: 1.35;
	color: var(--hub-ink);
	background: var(--hub-surface);
	border: 1px solid var(--hub-ring);
	border-radius: 4px;
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
	pointer-events: none;
}
```

`PA_Step3Views.js`: add `this.hubNetworkView = null;` beside `:71`, instantiate it beside the hub view at `:350-355`, mount `me.hubNetworkView.getComponent()` in the items array at `:1274`, and add a **Network** row action to the hub grid next to Paint (`:5864`) that calls `showCompound(row.ID, row.Step)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_hub_network_view`
Expected: all classes OK, none skipped (with node present).

- [ ] **Step 6: Verify in Chrome (mandatory)**

Restart the server. Bump `?v=` on the new view whenever you edit it. Run a compound-bearing job to Step 3, click **Network** on a hub row, and confirm: the metabolite is centred; rings correspond to steps; the step control dims rather than removes; truncation is announced when it happens; `read_console_messages` is clean. Screenshot it.

Then run the redline pass per CLAUDE.md §6: open with `?guides=1`, screenshot, fix every off-rail element until the HUD shows 0.

- [ ] **Step 7: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3HubNetworkView.js \
        PaintomicsClient/public_html/index.html \
        PaintomicsClient/public_html/resources/css/network-views.css \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js \
        PaintomicsServer/src/tests/test_hub_network_view.py
git commit -m "Draw a metabolite's neighbourhood as concentric hop rings" -- \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3HubNetworkView.js \
        PaintomicsClient/public_html/index.html \
        PaintomicsClient/public_html/resources/css/network-views.css \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js \
        PaintomicsServer/src/tests/test_hub_network_view.py
```

---

## Task 9: Delete R from the hub path

**Files:**
- Delete: `PaintomicsServer/src/AdminTools/scripts/GalaxyNetworkFunctionsv2.R`, `PaintomicsServer/src/AdminTools/scripts/hubAnalysisInstall.R`, `PaintomicsServer/src/common/bioscripts/hubAnalysis.R`
- Modify: `PaintomicsServer/src/AdminTools/DBManager.py` (`:387` signature, `:541-658`, `:1089-1121`, `:732-765`), `PaintomicsServer/src/AdminTools/customSpeciesInstaller.py`, `deploy/Dockerfile`, `deploy/smoke-test.sh`, `scripts/ci/installer_smoke.py:149`

**Interfaces:**
- Consumes: nothing new.
- Produces: `install_command(inputfile=None, specie=None, species=None, common=0, reinstall=0)` — the `hub` parameter is gone.

- [ ] **Step 1: Write the failing test**

Add to `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
class NoHubRTest(unittest.TestCase):
    """The hub path is pure Python. These three scripts and the install block
    they served must be gone, not merely unused."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_r_scripts_are_deleted(self):
        for relative in ("AdminTools/scripts/GalaxyNetworkFunctionsv2.R",
                         "AdminTools/scripts/hubAnalysisInstall.R",
                         "common/bioscripts/hubAnalysis.R"):
            self.assertFalse(os.path.exists(os.path.join(self.ROOT, relative)),
                             "%s still exists" % relative)

    def test_dbmanager_has_no_hub_block(self):
        with open(os.path.join(self.ROOT, "AdminTools", "DBManager.py"),
                  "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("hubAnalysisInstall.R", source)
        self.assertNotIn("hub_data_is_complete", source)

    def test_nothing_references_the_deleted_scripts(self):
        hits = []
        for base, _dirs, files in os.walk(self.ROOT):
            for name in files:
                if not name.endswith((".py", ".sh", ".R")):
                    continue
                path = os.path.join(base, name)
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    body = handle.read()
                for needle in ("hubAnalysis.R", "hubAnalysisInstall.R",
                               "GalaxyNetworkFunctionsv2.R"):
                    if needle in body:
                        hits.append("%s -> %s" % (path, needle))
        self.assertEqual(hits, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_release_hygiene`
Expected: FAIL on all three.

- [ ] **Step 3: Delete and unwire**

```bash
git rm PaintomicsServer/src/AdminTools/scripts/GalaxyNetworkFunctionsv2.R \
       PaintomicsServer/src/AdminTools/scripts/hubAnalysisInstall.R \
       PaintomicsServer/src/common/bioscripts/hubAnalysis.R
```
Then remove from `DBManager.py`: the `hub` parameter at `:387` and its help text at `:401`; the whole `try/except` hub block at `:541-658`; `hub_data_is_complete` at `:1089-1121` and all seven call sites (`:553, 555, 614, 635, 639, 732, 741`); the hubData move/rmtree at `:732-765`. Remove `hub=0` from `scripts/ci/installer_smoke.py:149` and `reinstall_command`'s `hub` parameter at `:1138-1139`.

From `deploy/Dockerfile`, drop the ten hub-only R packages from `:81-89`, `:114`, `:137-144`, and their assertions at `:227-232` and `:418-423`; drop the same names from `deploy/smoke-test.sh:59-65`. Keep every package MORE and metagenes need — `cluster`, `amap`, `mclust`, `factoextra`, `FactoMineR`, `car`, `lme4`, `glmnet`, `purrr`. **Verify with a build before claiming this works.**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_release_hygiene && python -m src.tests.run_all`
Expected: `test_release_hygiene` OK, and `run_all` reporting no new failures against BASELINE.

- [ ] **Step 5: Prove the installer still works**

Run a real install for a small species into a scratch data root and confirm it completes with no hub step and no `hubData` directory. Then run a compound-bearing job end to end in Chrome.

- [ ] **Step 6: Commit**

```bash
git add -A PaintomicsServer/src/AdminTools PaintomicsServer/src/common/bioscripts \
        PaintomicsServer/src/tests/test_release_hygiene.py deploy scripts/ci
git commit -m "Delete the hub R scripts and the install step that fed them" -- \
        PaintomicsServer/src/AdminTools PaintomicsServer/src/common/bioscripts \
        PaintomicsServer/src/tests/test_release_hygiene.py deploy scripts/ci
```

---

## Task 10: `hub doctor`

**Files:**
- Modify: `PaintomicsServer/src/AdminTools/DBManager.py` (new `hubdoctor_command`)
- Test: covered by Task 3's store suite; add one CLI smoke assertion here.

**Interfaces:**
- Consumes: `store.get_graph`.
- Produces: `python DBManager.py hubdoctor [--species=mmu,ath]` — exit 0 if every installed species yields a graph, 1 otherwise.

**Rationale:** deriving moves parse failures from install time to runtime. This puts install-time validation back within reach — by choice rather than by mandate.

- [ ] **Step 1: Write the failing test**

Add to `PaintomicsServer/src/tests/test_release_hygiene.py`:

```python
    def test_hubdoctor_command_exists(self):
        with open(os.path.join(self.ROOT, "AdminTools", "DBManager.py"),
                  "r", encoding="utf-8") as handle:
            self.assertIn("def hubdoctor_command", handle.read())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd PaintomicsServer && python -m src.tests.test_release_hygiene`
Expected: FAIL — `hubdoctor_command` not found.

- [ ] **Step 3: Add the command**

```python
def hubdoctor_command(species=None):
    """Check that every installed species yields a usable interaction graph.

    Deriving the graph on demand moved parse failures from install time to
    runtime. This is how you get the install-time check back when you want it.

        python DBManager.py hubdoctor
        python DBManager.py hubdoctor --species=mmu,ath
    """
    from src.common.KeggGraph import store

    codes = ([c.strip() for c in species.split(",")] if species
             else sorted(d for d in os.listdir(os.path.join(KEGG_DATA_DIR, "current"))
                         if os.path.isdir(os.path.join(KEGG_DATA_DIR, "current", d))))
    failures = 0
    for code in codes:
        store.clear_cache()
        started = time()   # DBManager does `from time import ... time`, so this is the function
        graph = store.get_graph(code)
        if graph is None:
            log("HUB DOCTOR: %-8s NO GRAPH" % code)
            failures += 1
            continue
        log("HUB DOCTOR: %-8s %6d edges  %5d nodes  %5d compounds  %s  %.2fs"
            % (code, len(graph.edge_kind), len(graph.names),
               len(graph.compounds()), graph.source, time() - started))
    log("HUB DOCTOR: %d of %d species have no graph" % (failures, len(codes)))
    return 1 if failures else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd PaintomicsServer && python -m src.tests.test_release_hygiene`
Expected: OK.

- [ ] **Step 5: Run it for real**

Run: `cd PaintomicsServer/src/AdminTools && /Users/tianyuan/miniforge3/envs/paintomics4/bin/python DBManager.py hubdoctor`
Expected: a line per installed species; mmu/ath/hsa with `kgml`. Record the output.

- [ ] **Step 6: Commit**

```bash
git commit -m "Add hub doctor so graph validation stays available by choice" -- \
        PaintomicsServer/src/AdminTools/DBManager.py \
        PaintomicsServer/src/tests/test_release_hygiene.py
```

---

## Task 11: Re-baseline and put hub in CI

**Files:**
- Modify: `PaintomicsServer/src/tests/baseline/04-multiomics-integration/*`, `.../08-stategra-multiomics/*`, `.github/workflows/pr.yml:83-88`, `reports/quality.md`

**Rationale:** these two baselines are the only pin on hub science, and the numbers **will** change — the graph is different (D-1/D-2), the balls are different (D-6), and BH is one family now (D-4). Re-baselining is the deliverable, not an accident.

- [ ] **Step 1: Capture the current baselines before changing anything**

```bash
cd PaintomicsServer && cp -r src/tests/baseline/04-multiomics-integration \
   /tmp/hub-baseline-04-before && cp -r src/tests/baseline/08-stategra-multiomics \
   /tmp/hub-baseline-08-before
```

- [ ] **Step 2: Run the regression with the pinned interpreter**

Run: `PYTHON=venv-py311 ./scripts/regression.sh`
Expected: the two compound-bearing scenarios differ; everything else matches. **If any non-compound scenario differs, stop and report — that is a bug, not a re-baseline.**

- [ ] **Step 3: Record what moved**

Diff old against new and write a short table into `reports/quality.md`: how many hub rows changed, how many metabolites changed significance at FDR 0.05, and how much of that is attributable to each of D-1/D-2 (graph), D-6 (balls) and D-4 (one BH family). Attribute by re-running with each fix individually disabled if the split is not obvious.

- [ ] **Step 4: Accept the new baselines**

Run: `PYTHON=venv-py311 ./scripts/regression.sh --write-baseline` (the flag is `--write-baseline`, `scripts/regression.sh:60`), then confirm a clean second run.

- [ ] **Step 5: Make CI build hub**

In `.github/workflows/pr.yml:83-88`, add `04-multiomics-integration` to the scenario list so the PR gate exercises a compound-bearing job. Confirm the species cache carries what the scenario needs.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsServer/src/tests/baseline reports/quality.md .github/workflows/pr.yml
git commit -m "Re-baseline hub against the corrected graph, and gate it in CI" -- \
        PaintomicsServer/src/tests/baseline reports/quality.md .github/workflows/pr.yml
```

---

## Final verification

- [ ] `cd PaintomicsServer && python -m src.tests.run_all` — no new failures against BASELINE
- [ ] `python DBManager.py hubdoctor` — every installed species yields a graph
- [ ] Chrome: a fresh compound-bearing job renders the hub grid **and** the network view
- [ ] Chrome: a job stored before Task 5 still renders its grid
- [ ] `?guides=1` HUD shows 0 off-rail elements
- [ ] `grep -rn "hubAnalysis.R\|hubData" PaintomicsServer/src` returns only the legacy-fallback path in `store.py`
- [ ] Clean-checkout import gate: `git archive` the branch and import it before pushing
