"""The KEGG compound-gene graph, derived from the KGML each organism install
already ships.

Nothing here is persisted. Deriving the graph costs 1.03 s for the largest
species measured (mmu: 364 KGML files, 96,618 edges, 32 MB peak) against ~65 s
for the R installer it replaces, so no storage backend earns its migration.
See docs/superpowers/specs/2026-08-25-metabolite-hub-graph-design.md.

Import the submodules directly -- `from src.common.KeggGraph import store`.
There is deliberately no re-export here: an eager `from .store import get_graph`
makes the package unimportable whenever a submodule is mid-edit, and store pulls
in numpy and serverconf that parser and graph do not need.
"""
