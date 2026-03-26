#!/usr/bin/env python3
"""Standalone validation script for multi-condition p-value calculation.

Parses the same RF/QF files as PaintOmics, connects to MongoDB for pathway data,
and manually computes the hypergeometric p-value contingency tables to verify correctness.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_multicondition_pvalues
"""
import csv
import sys
from collections import defaultdict
from itertools import chain

from pymongo import MongoClient
from scipy.stats import hypergeom

# ─── Config ────────────────────────────────────────────────────────────────────
RF_FILE = "/Users/tianyuan/Downloads/rf_genes_genotype_wt_28.txt"
QF_FILE = "/Users/tianyuan/Downloads/qf_genes_genotype_wt_28.txt"
ORGANISM = "ath"
MONGODB_HOST = "localhost"
MONGODB_PORT = 27017


# ─── Step 1: Parse RF file (same logic as Job.parseSignificativeFeaturesFile) ─
def parse_rf_file(path):
    """Returns (relevantFeatures dict, conditionNames list)."""
    relevant = {}
    condition_names = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        n_line = 0
        n_conditions = 1
        for line in reader:
            n_line += 1
            if n_line == 1:
                if len(line) > 1:
                    n_conditions = len(line)
                    is_id = any(v.lower().startswith(("at", "cpd:", "k0", "r0")) for v in line)
                    if not is_id:
                        condition_names = [name.strip() for name in line]
                        continue
                    else:
                        condition_names = [f"Condition {i+1}" for i in range(n_conditions)]

            if n_conditions > 1:
                for col_idx, fid in enumerate(line):
                    if fid.strip():
                        fid_lower = fid.strip().lower()
                        if fid_lower not in relevant:
                            relevant[fid_lower] = [False] * n_conditions
                        relevant[fid_lower][col_idx] = True
            else:
                relevant[line[0].strip().lower()] = [True]

    return relevant, condition_names, n_conditions


# ─── Step 2: Parse QF file ────────────────────────────────────────────────────
def parse_qf_file(path, relevant_features, n_conditions):
    """Returns list of (gene_id, values, relevant_list)."""
    genes = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        for line in reader:
            gene_id = line[0].strip()
            values = [float(v) for v in line[1:]]
            rel_list = relevant_features.get(gene_id.lower(), [])
            if len(rel_list) == 0:
                rel_list = [False] * n_conditions
            genes.append((gene_id, values, rel_list))
    return genes, header


# ─── Step 3: Load pathway data from MongoDB ───────────────────────────────────
def load_pathways_from_db(organism):
    """Returns {pathway_id: {"name": str, "genes": set, "compounds": set, "source": str}}.

    Each pathway is stored as a separate document in the 'kegg' collection
    of the '<organism>-paintomics' database, with an 'ID' field.
    """
    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    db = client[organism + "-paintomics"]

    pathways = {}
    cursor = db.kegg.find()
    for doc in cursor:
        pw_id = doc.get("ID")
        if not pw_id:
            continue
        gene_ids = set()
        for g in doc.get("genes", []):
            gene_ids.add(g["id"].lower())
        compound_ids = set()
        for c in doc.get("compounds", []):
            compound_ids.add(c["id"].lower())
        pathways[pw_id] = {
            "name": doc.get("name", pw_id),
            "genes": gene_ids,
            "compounds": compound_ids,
            "source": doc.get("source", "KEGG"),
        }

    client.close()
    if not pathways:
        print(f"ERROR: No pathways found for organism '{organism}' in MongoDB.")
        sys.exit(1)
    return pathways


# ─── Step 4: Calculate total features by omic (mimics calculateTotalFeaturesByOmic)
def calculate_totals(genes, pathways):
    """
    Returns:
        total_in_any_pathway: int (n)
        total_relevant_per_condition: list[int] (C1 per condition)
        gene_to_relevance: dict mapping gene_id -> relevance list (for genes in any pathway)
    """
    # Build set of all gene IDs in any pathway
    all_pathway_genes = set()
    for pw in pathways.values():
        all_pathway_genes.update(pw["genes"])

    gene_to_relevance = {}
    for gene_id, values, rel_list in genes:
        if gene_id.lower() in all_pathway_genes:
            gene_to_relevance[gene_id.lower()] = rel_list

    n = len(gene_to_relevance)

    # Count relevant per condition
    if not gene_to_relevance:
        return 0, [], {}

    n_conditions = max(len(v) for v in gene_to_relevance.values())
    c1_per_cond = [0] * n_conditions
    for rel_list in gene_to_relevance.values():
        for i in range(min(n_conditions, len(rel_list))):
            if rel_list[i]:
                c1_per_cond[i] += 1

    return n, c1_per_cond, gene_to_relevance


# ─── Step 5: Per-pathway contingency table and p-value ────────────────────────
def calculate_pathway_pvalues(pathway_genes, gene_to_relevance, n, c1_per_cond):
    """
    For a specific pathway, compute R1 (matched), a per condition, and p-value per condition.

    Returns:
        r1: int (total matched)
        a_per_cond: list[int] (relevant matched per condition)
        pvalues: list[float]
    """
    n_conditions = len(c1_per_cond)
    r1 = 0
    a_per_cond = [0] * n_conditions

    for gene_id in pathway_genes:
        gene_lower = gene_id.lower()
        if gene_lower in gene_to_relevance:
            r1 += 1
            rel_list = gene_to_relevance[gene_lower]
            for i in range(min(n_conditions, len(rel_list))):
                if rel_list[i]:
                    a_per_cond[i] += 1

    pvalues = []
    for i in range(n_conditions):
        a = a_per_cond[i]
        c1 = c1_per_cond[i]
        if a == 0:
            pvalues.append(1.0)
        else:
            p = hypergeom.sf(a - 1, n, c1, r1)
            pvalues.append(max(p, 1e-300))

    return r1, a_per_cond, pvalues


# ─── Step 6: Also test the BUGGY version of nConditions derivation ─────────────
def calculate_totals_buggy(genes, pathways):
    """Reproduces the bug where nConditions = len(all_vals[0])."""
    all_pathway_genes = set()
    for pw in pathways.values():
        all_pathway_genes.update(pw["genes"])

    # Simulate counterNames with the BUG: empty relevant -> [False] (length 1)
    gene_to_relevance_buggy = {}
    for gene_id, values, rel_list in genes:
        if gene_id.lower() in all_pathway_genes:
            if len(rel_list) == 0:
                rel_list_buggy = [False]  # THE BUG
            else:
                rel_list_buggy = list(rel_list)
            gene_to_relevance_buggy[gene_id.lower()] = rel_list_buggy

    n = len(gene_to_relevance_buggy)

    if not gene_to_relevance_buggy:
        return 0, [], {}

    all_vals = list(gene_to_relevance_buggy.values())
    # BUGGY: derive nConditions from first element
    n_conditions_buggy = len(all_vals[0]) if isinstance(all_vals[0], list) else 1
    # FIXED: derive from max
    n_conditions_fixed = max(len(v) for v in all_vals if isinstance(v, list)) if all_vals else 1

    print(f"\n  BUGGY nConditions (from first element): {n_conditions_buggy}")
    print(f"  FIXED nConditions (from max):           {n_conditions_fixed}")
    print(f"  First element: {all_vals[0]}")
    print(f"  Sample elements: {all_vals[:5]}")

    c1_buggy = [0] * n_conditions_buggy
    for rel_val in all_vals:
        if isinstance(rel_val, list):
            for i in range(min(n_conditions_buggy, len(rel_val))):
                if rel_val[i]:
                    c1_buggy[i] += 1

    c1_fixed = [0] * n_conditions_fixed
    for rel_val in all_vals:
        if isinstance(rel_val, list):
            for i in range(min(n_conditions_fixed, len(rel_val))):
                if rel_val[i]:
                    c1_fixed[i] += 1

    print(f"  BUGGY C1 per condition: {c1_buggy}")
    print(f"  FIXED C1 per condition: {c1_fixed}")

    return n, c1_fixed, gene_to_relevance_buggy


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("MULTI-CONDITION P-VALUE VALIDATION")
    print("=" * 80)

    # Step 1: Parse RF
    print("\n--- Step 1: Parse RF file ---")
    relevant_features, condition_names, n_conditions = parse_rf_file(RF_FILE)
    print(f"  Conditions: {condition_names} (n={n_conditions})")
    print(f"  Unique relevant gene IDs: {len(relevant_features)}")

    # Count relevant per condition in RF file
    rf_counts = [0] * n_conditions
    for rel in relevant_features.values():
        for i in range(n_conditions):
            if i < len(rel) and rel[i]:
                rf_counts[i] += 1
    print(f"  Relevant genes per condition (RF file): {dict(zip(condition_names, rf_counts))}")

    # Step 2: Parse QF
    print("\n--- Step 2: Parse QF file ---")
    genes, header = parse_qf_file(QF_FILE, relevant_features, n_conditions)
    print(f"  Total genes in QF: {len(genes)}")
    print(f"  Header: {header}")

    # Show relevance assignment for first 5 genes
    print("  Sample gene relevance assignments:")
    for gene_id, vals, rel in genes[:5]:
        print(f"    {gene_id}: relevant={rel}")

    # Count how many QF genes have relevance for each condition
    qf_rel_counts = [0] * n_conditions
    qf_no_relevance = 0
    for gene_id, vals, rel in genes:
        if all(not r for r in rel):
            qf_no_relevance += 1
        for i in range(n_conditions):
            if i < len(rel) and rel[i]:
                qf_rel_counts[i] += 1
    print(f"  QF genes relevant per condition: {dict(zip(condition_names, qf_rel_counts))}")
    print(f"  QF genes with NO relevance in any condition: {qf_no_relevance}")

    # Step 3: Load pathways
    print("\n--- Step 3: Load pathways from MongoDB ---")
    pathways = load_pathways_from_db(ORGANISM)
    print(f"  Total pathways loaded: {len(pathways)}")

    # Step 4: Calculate totals (FIXED version)
    print("\n--- Step 4: Calculate totals ---")
    n_total, c1_per_cond, gene_to_rel = calculate_totals(genes, pathways)
    print(f"  n (total input genes in any pathway): {n_total}")
    print(f"  C1 per condition (total relevant in any pathway): {dict(zip(condition_names, c1_per_cond))}")

    # Step 4b: Show buggy version
    print("\n--- Step 4b: Buggy vs Fixed comparison ---")
    _, _, _ = calculate_totals_buggy(genes, pathways)

    # Step 5: Per-pathway p-values for pathways with matched genes
    print("\n--- Step 5: Per-pathway p-values ---")
    print(f"{'Pathway':<50} {'R1':>4} | ", end="")
    for cname in condition_names:
        print(f"  a_{cname:>6} C1_{cname:>6} p_{cname:>10}", end="")
    print()
    print("-" * (50 + 6 + n_conditions * 30))

    matched_pathways = []
    for pw_id, pw_data in pathways.items():
        r1, a_per_cond, pvalues = calculate_pathway_pvalues(
            pw_data["genes"], gene_to_rel, n_total, c1_per_cond
        )
        if r1 > 0:
            matched_pathways.append((pw_id, pw_data["name"], r1, a_per_cond, pvalues))

    # Sort by min p-value across conditions
    matched_pathways.sort(key=lambda x: min(x[4]))

    for pw_id, pw_name, r1, a_per_cond, pvalues in matched_pathways[:30]:
        display_name = pw_name[:48] if len(pw_name) > 48 else pw_name
        line = f"{display_name:<50} {r1:>4} | "
        for i in range(n_conditions):
            line += f"  {a_per_cond[i]:>8} {c1_per_cond[i]:>8} {pvalues[i]:>12.4e}"
        print(line)

    # Step 6: Detailed breakdown for top 3 pathways
    print("\n\n--- Step 6: Detailed breakdown for top pathways ---")
    for pw_id, pw_name, r1, a_per_cond, pvalues in matched_pathways[:3]:
        print(f"\n  Pathway: {pw_name} [{pw_id}]")
        print(f"  R1 (matched features in pathway): {r1}")
        print(f"  n (total features in universe): {n_total}")
        for i, cname in enumerate(condition_names):
            a = a_per_cond[i]
            c1 = c1_per_cond[i]
            c2 = n_total - c1
            p = pvalues[i]
            print(f"  Condition '{cname}':")
            print(f"    a (found & relevant):     {a}")
            print(f"    C1 (total relevant):      {c1}")
            print(f"    C2 (total not relevant):  {c2}")
            print(f"    Formula: sum_{{i={a}}}^{{min({r1},{c1})}} C({c1},i)*C({c2},{r1}-i) / C({n_total},{r1})")
            print(f"    hypergeom.sf({a-1}, {n_total}, {c1}, {r1}) = {p:.6e}")

            # Verify manually with the sum formula
            from scipy.special import comb
            manual_p = sum(
                comb(c1, j, exact=True) * comb(c2, r1 - j, exact=True) / comb(n_total, r1, exact=True)
                for j in range(a, min(r1, c1) + 1)
            )
            print(f"    Manual sum formula:       {manual_p:.6e}")
            match = abs(p - manual_p) < 1e-10 or (p > 0 and abs(p - manual_p) / p < 1e-6)
            print(f"    Match: {'YES' if match else 'NO *** MISMATCH ***'}")

    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
