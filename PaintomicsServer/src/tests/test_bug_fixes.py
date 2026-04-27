"""Unit tests for the multi-condition bug fixes (autoresearch loop).

Run from `PaintomicsServer/`:

    python -m src.tests.test_bug_fixes

Each test prints PASS/FAIL and exits non-zero on any failure.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.classes.Pathway import Pathway

_PASSED = []
_FAILED = []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        _FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print(f"ERROR {name}")
        traceback.print_exc()


# -------------------- Bug A: addSignificanceValues totalMatched inflation --------------------
def test_bug_a_scalar_unchanged():
    """Single-condition behavior must be bit-identical to pre-fix."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [False])
    p.addSignificanceValues("o", [True])
    sv = p.getSignificanceValues()["o"]
    assert sv == [[3, 2, -1.0]], f"expected [[3,2,-1.0]], got {sv}"


def test_bug_a_mixed_lengths_no_inflation():
    """Mixed-length inputs must not double-count totalMatched in later conditions."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [False, True, True])
    sv = p.getSignificanceValues()["o"]
    # cond 0: both features contribute → matched=2, relevant=1 (only first is True)
    # cond 1: only the 3-cond feature contributes → matched=1, relevant=1
    # cond 2: only the 3-cond feature contributes → matched=1, relevant=1
    assert sv == [[2, 1, -1.0], [1, 1, -1.0], [1, 1, -1.0]], f"got {sv}"


def test_bug_a_uniform_multicond():
    """Uniform-length multi-cond inputs accumulate per condition correctly."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True, False, True])
    p.addSignificanceValues("o", [True, True, False])
    p.addSignificanceValues("o", [False, False, False])
    sv = p.getSignificanceValues()["o"]
    assert sv == [[3, 2, -1.0], [3, 1, -1.0], [3, 1, -1.0]], f"got {sv}"


def test_bug_a_late_arriving_longer():
    """Feature arriving later with MORE conditions than seen so far must extend."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [True])
    # Now extend
    p.addSignificanceValues("o", [True, True, False])
    sv = p.getSignificanceValues()["o"]
    # cond 0: 3 contributors, all True → [3,3]
    # cond 1: 1 contributor, True → [1,1]
    # cond 2: 1 contributor, False → [1,0]
    assert sv == [[3, 3, -1.0], [1, 1, -1.0], [1, 0, -1.0]], f"got {sv}"


# -------------------- Run all --------------------
def main():
    tests = [
        test_bug_a_scalar_unchanged,
        test_bug_a_mixed_lengths_no_inflation,
        test_bug_a_uniform_multicond,
        test_bug_a_late_arriving_longer,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
