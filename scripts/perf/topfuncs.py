#!/usr/bin/env python3
"""Top functions by cumulative time from a py-spy `--format raw` recording.

py-spy's raw format is one collapsed stack per line -- frames from the root
to the leaf, `;`-separated, then a space and the sample count. Cumulative
(inclusive) time of a function is the number of samples whose stack contains
it, counted once per stack even when it recurses; self time is the number of
samples where it is the leaf. Line numbers are dropped so a function is one
row, and paths are shortened to what follows `PaintomicsServer/src/` (other
frames -- pandas, scipy, the standard library -- keep their file name).

    python scripts/perf/topfuncs.py profile.raw [--top 10] [--only-src]

The percentages are of all samples in the file.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

FRAME = re.compile(r"^(?P<func>.*?) \((?P<file>[^()]*?)(?::(?P<line>\d+))?\)$")


MARKER = "PaintomicsServer/src/"
# py-spy writes paths relative to the working directory when it can, so a
# product frame reads `src/classes/Job.py` in a recording made from the
# repository root and `.../PaintomicsServer/src/classes/Job.py` otherwise.
HARNESS = ("benchmarks/",)   # after the src/ prefix is stripped


def shorten(path):
    if MARKER in path:
        return path.split(MARKER, 1)[1]
    if path.startswith("src/"):
        return path[len("src/"):]
    return os.path.basename(path)


def is_product(path):
    if MARKER in path:
        path = MARKER + path.split(MARKER, 1)[1]
        path = path[len(MARKER):]
    elif path.startswith("src/"):
        path = path[len("src/"):]
    else:
        return False
    return not path.startswith(HARNESS)


def frame_key(frame):
    """(key, is_src): key is `func (file)` without the line number."""
    match = FRAME.match(frame.strip())
    if not match:
        return frame.strip(), False
    path = match.group("file")
    return "%s (%s)" % (match.group("func"), shorten(path)), is_product(path)


def on_path(frames, root):
    """True when the stack contains the pipeline's root frame -- the main
    thread and the mapper workers forked from it -- rather than one of the
    driver threads (pymongo's monitors, heartbeats) that py-spy also
    samples."""
    if not root:
        return True
    return any(f.startswith(root) for f in frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--only-src", action="store_true",
                        help="rank only functions defined under PaintomicsServer/src")
    parser.add_argument("--root", default="run (perf_run.py)",
                        help="count only stacks containing this frame (the pipeline "
                             "and its forked workers); '' counts every thread")
    args = parser.parse_args(argv)

    cumulative = defaultdict(int)
    self_time = defaultdict(int)
    in_src = {}
    total = kept = 0
    with open(args.raw, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            stack, _, count = line.rpartition(" ")
            try:
                count = int(count)
            except ValueError:
                continue
            total += count
            frames = []
            for raw_frame in stack.split(";"):
                if not raw_frame:
                    continue
                key, is_src = frame_key(raw_frame)
                frames.append(key)
                in_src[key] = is_src
            if not on_path(frames, args.root):
                continue
            kept += count
            for frame in set(frames):
                cumulative[frame] += count
            if frames:
                self_time[frames[-1]] += count

    rows = sorted(cumulative.items(), key=lambda item: -item[1])
    if args.only_src:
        rows = [(key, count) for key, count in rows if in_src.get(key)]
    total = kept
    print("samples on the pipeline path: %d" % total)
    print("%4s %9s %7s %7s  %s" % ("#", "cumul", "cum%", "self%", "function (file)"))
    for rank, (key, count) in enumerate(rows[:args.top], 1):
        print("%4d %9d %6.1f%% %6.1f%%  %s" % (
            rank, count, 100.0 * count / max(total, 1), 100.0 * self_time[key] / max(total, 1), key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
