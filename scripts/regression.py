#!/usr/bin/env python3
"""Helper behind scripts/regression.sh: run one example dataset end to end,
normalise what the pipeline produced, and compare it with a stored baseline.

The pipeline kernel is PaintomicsServer/src/benchmarks/bench_runner.py, which
drives every job class through the same methods the servlets call and dumps
everything the client would see. This script owns the *contract* around that
dump:

  normalise  strip the tokens that legitimately differ between two runs of the
             same code (job IDs, timestamps, absolute paths, UUIDs, object
             addresses) and sort the few collections the server fills by
             iterating a set, so that the stored form is a function of the
             science and nothing else;
  compare    deep-compare two normalised dumps exactly -- floats bit for bit,
             NaN equal to NaN -- and name every path that differs.

Sub-commands (all stdlib, Python >= 3.9):

  list       print "<dataset-dir> <scenario-id> <pipeline>" per manifest entry
  run        run one scenario into a work directory and normalise it
  compare    compare a work directory with tests/baseline/<dataset>/
  write      copy a normalised work directory into tests/baseline/<dataset>/,
             refusing to touch a baseline that already exists

Baseline layout, per dataset: one <part>.json.gz per top-level artifact
(step1/step2/step3 for pathway acquisition, conversion for the regions->genes
and miRNA->genes tools, more for MORE), each holding canonical JSON (sorted
keys, no whitespace, gzip with a zeroed mtime), plus a plain summary.json with
the size and SHA-256 of every part so a git diff at least says *which* part
moved.
"""
import argparse
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.path.join(REPO, "PaintomicsServer")
MANIFEST = os.path.join(SERVER, "src", "examplefiles", "datasets", "manifest.json")
BASELINE_ROOT = os.path.join(REPO, "tests", "baseline")

PARTS_SUFFIX = ".json.gz"
SUMMARY_NAME = "summary.json"

# ---------------------------------------------------------------------------
# Volatile tokens
# ---------------------------------------------------------------------------

# bench_runner names its jobs "BM" + 10 hex digits; the servlets hand out
# 10-character alphanumerics that never reach these artifacts.
JOBID_RE = re.compile(r"\bBM[0-9a-f]{10}\b")
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
# Converter and MORE file names embed a minute- or second-resolution stamp
# (YYYYMMDDHHMM / YYYYMMDDHHMMSS) or a date_time pair; ISO timestamps appear in
# logged messages. A run of digits that is part of a decimal number is not a
# timestamp: the look-arounds refuse a neighbouring digit or '.'.
TS_RE = re.compile(
    r"(?<![\d.])(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\d{8}_\d{6}|\d{14}|\d{12})(?![\d.])")
# repr() of an object that could not be serialised carries its address.
ADDR_RE = re.compile(r"0x[0-9a-fA-F]{6,}")


def _path_roots(args):
    """(prefix, placeholder) pairs, longest prefix first, so that a path under
    the client tmp dir is not first rewritten as a path under $HOME."""
    roots = []
    checkout = os.path.abspath(args.checkout or REPO)
    roots.append((os.path.join(checkout, "PaintomicsServer") + os.sep,
                  "<checkout>/PaintomicsServer/"))
    roots.append((checkout + os.sep, "<checkout>/"))
    for value, token in ((args.client_tmp, "<client-tmp>/"),
                         (args.kegg_data, "<kegg-data>/")):
        if value:
            roots.append((os.path.abspath(value) + os.sep, token))
    home = os.path.expanduser("~")
    if home and home != os.sep:
        roots.append((home + os.sep, "<home>/"))
    roots.sort(key=lambda item: -len(item[0]))
    return roots


def scrub_string(text, roots):
    for prefix, token in roots:
        if prefix in text:
            text = text.replace(prefix, token)
    text = JOBID_RE.sub("<jobID>", text)
    text = UUID_RE.sub("<uuid>", text)
    text = TS_RE.sub("<TS>", text)
    text = ADDR_RE.sub("<addr>", text)
    return text


def scrub(obj, roots):
    """Recursively rewrite volatile tokens in every string, keys included."""
    if isinstance(obj, str):
        return scrub_string(obj, roots)
    if isinstance(obj, list):
        return [scrub(item, roots) for item in obj]
    if isinstance(obj, dict):
        return {scrub_string(str(key), roots) if isinstance(key, str) else key:
                scrub(value, roots) for key, value in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Set-derived collections: compared as multisets, stored sorted
# ---------------------------------------------------------------------------

def _canonical(value):
    return json.dumps(value, sort_keys=True, default=str)


def sort_unordered(artifacts):
    """Sort the collections the server builds by iterating a set or by the
    arrival order of parallel workers. The client reads each of them as a set
    (membership, length, search blob), so their order carries no information
    and must not decide a PASS/FAIL.

      omicsValuesID        Job.getValueIdTable joins a *set* of names with '|'
      matchedGenes /       pathway and class members, filled from a set of IDs
      matchedCompounds
      classificationDict   per-category compound lists, from a set
      omicsValues          a feature's per-omic values, in mapper-worker order

    Everything else keeps its order: lists that reach the client in a defined
    order (matchedMetabolites, selectedPathways, graphical boxes, file lines)
    are part of the contract.
    """
    for step in artifacts.values():
        if not isinstance(step, dict):
            continue
        table = step.get("omicsValuesID")
        if isinstance(table, dict):
            step["omicsValuesID"] = {
                key: "|".join(sorted(value.split("|"))) if isinstance(value, str) else value
                for key, value in table.items()}
        for key in ("pathwaysInfo", "classInfo"):
            table = step.get(key)
            if isinstance(table, dict):
                entries = table.values()
            elif isinstance(table, list):
                entries = table
            else:
                entries = []
            for entry in entries:
                if isinstance(entry, dict):
                    for field in ("matchedGenes", "matchedCompounds"):
                        if isinstance(entry.get(field), list):
                            entry[field] = sorted(entry[field], key=str)
        classification = step.get("classificationDict")
        if isinstance(classification, dict):
            step["classificationDict"] = {
                key: sorted(value, key=str) if isinstance(value, list) else value
                for key, value in classification.items()}
        features = step.get("omicsValues")
        if isinstance(features, dict):
            for feature in features.values():
                values = feature.get("omicsValues") if isinstance(feature, dict) else None
                if isinstance(values, list):
                    feature["omicsValues"] = sorted(values, key=_canonical)
    return artifacts


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def canonical_bytes(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=True)
    return text.encode("ascii")


def write_part(directory, name, value):
    payload = canonical_bytes(value)
    buffer = io.BytesIO()
    # mtime=0 so the same content is the same file, byte for byte.
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write(payload)
    path = os.path.join(directory, name + PARTS_SUFFIX)
    with open(path, "wb") as handle:
        handle.write(buffer.getvalue())
    return {"bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def read_part(directory, name):
    path = os.path.join(directory, name + PARTS_SUFFIX)
    with gzip.open(path, "rt", encoding="ascii") as handle:
        return json.load(handle)


def list_parts(directory):
    return sorted(name[:-len(PARTS_SUFFIX)] for name in os.listdir(directory)
                  if name.endswith(PARTS_SUFFIX))


def headline(value):
    """A few human-readable numbers per part for summary.json: the length of
    every top-level collection, and the step-2 summary list verbatim."""
    if not isinstance(value, dict):
        return {}
    numbers = {}
    for key, item in value.items():
        if isinstance(item, (list, dict, str)):
            numbers[key] = len(item)
        elif item is None or isinstance(item, (bool, int, float)):
            numbers[key] = item
    if isinstance(value.get("summary"), list):
        numbers["summary"] = value["summary"]
    return numbers


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

class Differences(object):
    def __init__(self, limit):
        self.limit = limit
        self.count = 0
        self.shown = []

    def add(self, path, detail):
        self.count += 1
        if len(self.shown) < self.limit:
            self.shown.append("%s: %s" % (path or "<root>", detail))


def _short(value, limit=100):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def deep_compare(expected, actual, diffs, path=""):
    if isinstance(expected, float) or isinstance(actual, float):
        both_numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in (expected, actual))
        if not both_numbers:
            diffs.add(path, "type %s vs %s" % (type(expected).__name__,
                                               type(actual).__name__))
            return
        if math.isnan(expected) and math.isnan(actual):
            return
        if float(expected) != float(actual):
            diffs.add(path, "%r != %r" % (expected, actual))
        return
    if isinstance(expected, dict) and isinstance(actual, dict):
        missing = sorted(set(expected) - set(actual), key=str)
        extra = sorted(set(actual) - set(expected), key=str)
        if missing or extra:
            diffs.add(path, "keys missing=%s extra=%s" % (missing[:6], extra[:6]))
        for key in expected:
            if key in actual:
                deep_compare(expected[key], actual[key], diffs,
                             "%s.%s" % (path, key))
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            diffs.add(path, "list length %d vs %d" % (len(expected), len(actual)))
        for index, (left, right) in enumerate(zip(expected, actual)):
            deep_compare(left, right, diffs, "%s[%d]" % (path, index))
        return
    if type(expected) is not type(actual):
        diffs.add(path, "type %s vs %s (%s vs %s)" % (
            type(expected).__name__, type(actual).__name__,
            _short(expected), _short(actual)))
        return
    if expected != actual:
        diffs.add(path, "%s != %s" % (_short(expected), _short(actual)))


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_scenarios():
    with open(MANIFEST, encoding="utf-8") as handle:
        manifest = json.load(handle)
    scenarios = sorted(manifest.get("scenarios", []),
                       key=lambda s: (s.get("order", 0), s.get("id", "")))
    rows = []
    for scenario in scenarios:
        files = [omic.get("dataFile") for omic in scenario.get("omics", [])]
        if scenario.get("target", {}).get("dataFile"):
            files.append(scenario["target"]["dataFile"])
        files = [f for f in files if f]
        if not files:
            raise SystemExit("regression: scenario %r declares no files"
                             % scenario.get("id"))
        # datasets/<NN-name>/data/<file> -> <NN-name>
        dataset = files[0].split("/")[1]
        rows.append((dataset, scenario["id"], scenario.get("pipeline", "")))
    return rows


def dataset_row(name):
    for row in load_scenarios():
        if name in (row[0], row[1]):
            return row
    raise SystemExit("regression: unknown dataset %r" % name)


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    for dataset, scenario, pipeline in load_scenarios():
        print(dataset, scenario, pipeline)
    return 0


def cmd_run(args):
    dataset, scenario, pipeline = dataset_row(args.dataset)
    work = os.path.abspath(args.work)
    raw = os.path.join(work, "raw")
    os.makedirs(raw, exist_ok=True)

    env = dict(os.environ)
    # Set iteration order must not masquerade as a result difference.
    env.setdefault("PYTHONHASHSEED", "0")
    command = [args.python, "-m", "src.benchmarks.bench_runner",
               "--scenario", scenario, "--out", raw]
    with open(os.path.join(work, "bench.log"), "w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(command, cwd=SERVER, env=env,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       timeout=args.timeout)
        except subprocess.TimeoutExpired:
            log.write("\nregression: bench_runner exceeded %d s\n" % args.timeout)
            return 2
    if completed.returncode != 0:
        return 2

    with gzip.open(os.path.join(raw, "artifacts.json.gz"), "rt",
                   encoding="utf-8") as handle:
        artifacts = json.load(handle)
    artifacts = sort_unordered(scrub(artifacts, _path_roots(args)))

    parts = {}
    for name in sorted(artifacts):
        info = write_part(work, name, artifacts[name])
        info["headline"] = headline(artifacts[name])
        parts[name] = info
    summary = {"dataset": dataset, "scenario": scenario, "pipeline": pipeline,
               "parts": parts}
    with open(os.path.join(work, SUMMARY_NAME), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0


def cmd_compare(args):
    dataset = dataset_row(args.dataset)[0]
    baseline = os.path.join(args.baseline_root, dataset)
    work = os.path.abspath(args.work)
    if not os.path.isdir(baseline):
        print("no baseline at %s" % baseline)
        return 1
    expected_parts = list_parts(baseline)
    actual_parts = list_parts(work)
    diffs = Differences(args.max_report)
    if expected_parts != actual_parts:
        diffs.add("", "parts %s vs %s" % (expected_parts, actual_parts))
    for name in expected_parts:
        if name not in actual_parts:
            continue
        deep_compare(read_part(baseline, name), read_part(work, name), diffs, name)
    if diffs.count:
        print("%d difference(s) against %s" % (diffs.count, baseline))
        for line in diffs.shown:
            print("  " + line)
        if diffs.count > len(diffs.shown):
            print("  ... and %d more" % (diffs.count - len(diffs.shown)))
        return 1
    return 0


def cmd_write(args):
    dataset = dataset_row(args.dataset)[0]
    baseline = os.path.join(args.baseline_root, dataset)
    work = os.path.abspath(args.work)
    if os.path.isdir(baseline) and os.listdir(baseline):
        print("refusing to overwrite existing baseline %s" % baseline)
        return 1
    os.makedirs(baseline, exist_ok=True)
    for name in list_parts(work):
        with open(os.path.join(work, name + PARTS_SUFFIX), "rb") as source, \
                open(os.path.join(baseline, name + PARTS_SUFFIX), "wb") as target:
            target.write(source.read())
    with open(os.path.join(work, SUMMARY_NAME), "rb") as source, \
            open(os.path.join(baseline, SUMMARY_NAME), "wb") as target:
        target.write(source.read())
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    run = sub.add_parser("run")
    run.add_argument("dataset")
    run.add_argument("--work", required=True)
    run.add_argument("--python", default=sys.executable)
    run.add_argument("--timeout", type=int, default=3600)
    run.add_argument("--checkout", default=REPO)
    run.add_argument("--client-tmp", default=os.environ.get("PAINTOMICS_CLIENT_TMP"))
    run.add_argument("--kegg-data", default=os.environ.get("PAINTOMICS_KEGG_DATA"))
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare")
    compare.add_argument("dataset")
    compare.add_argument("--work", required=True)
    compare.add_argument("--baseline-root", default=BASELINE_ROOT)
    compare.add_argument("--max-report", type=int, default=25)
    compare.set_defaults(func=cmd_compare)

    write = sub.add_parser("write")
    write.add_argument("dataset")
    write.add_argument("--work", required=True)
    write.add_argument("--baseline-root", default=BASELINE_ROOT)
    write.set_defaults(func=cmd_write)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
