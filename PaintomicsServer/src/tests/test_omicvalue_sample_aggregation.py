"""
Round-trip tests for the OmicValue replicate-aggregation fields.

Pinned behaviour:
- ``sampleValues`` and ``sampleRelevant`` default to ``None``.
- They survive ``toBSON`` → ``parseBSON`` round-trips with values intact.
- BSON documents that *lack* the new fields (i.e. legacy jobs persisted before
  this feature shipped) deserialize cleanly with ``None`` defaults — no
  AttributeError, no migration script needed.
- ``hasSampleAggregation()`` flips correctly.

Run from PaintomicsServer/:
    python -m src.tests.test_omicvalue_sample_aggregation
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.classes.Feature import OmicValue, Gene  # noqa: E402

_PASS, _FAIL = [], []


def _check(name, fn):
    try:
        fn()
        _PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as e:
        _FAIL.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")
    except Exception:
        _FAIL.append((name, traceback.format_exc()))
        print(f"  ERROR {name}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_defaults_are_none():
    """A freshly constructed OmicValue has no sample-aggregation set."""
    ov = OmicValue("AT1G12345")
    assert ov.getSampleValues() is None
    assert ov.getSampleRelevant() is None
    assert ov.hasSampleAggregation() is False


def test_setters_and_getters():
    ov = OmicValue("AT1G12345")
    ov.setSampleValues([1.0, 2.5, -0.4])
    ov.setSampleRelevant([True, False, True])
    assert ov.getSampleValues() == [1.0, 2.5, -0.4]
    assert ov.getSampleRelevant() == [True, False, True]
    assert ov.hasSampleAggregation() is True


# ---------------------------------------------------------------------------
# BSON round-trip
# ---------------------------------------------------------------------------

def test_round_trip_with_aggregation_populated():
    """toBSON → parseBSON preserves both new fields verbatim."""
    ov = OmicValue("AT1G12345")
    ov.setOmicName("Gene Expression")
    ov.setValues([0.1, 0.2, 0.5, 0.6])              # 4 replicates
    ov.setRelevant([True, True, False, False])       # per-replicate
    ov.setSampleValues([0.15, 0.55])                 # 2 samples
    ov.setSampleRelevant([True, False])              # per-sample

    bson = ov.toBSON()
    rehydrated = OmicValue("").parseBSON(dict(bson))  # fresh instance

    assert rehydrated.getInputName()      == "AT1G12345"
    assert rehydrated.getOmicName()       == "Gene Expression"
    assert rehydrated.getValues()         == [0.1, 0.2, 0.5, 0.6]
    assert rehydrated.isRelevant()        == True       # any() → True
    assert rehydrated.getSampleValues()   == [0.15, 0.55]
    assert rehydrated.getSampleRelevant() == [True, False]
    assert rehydrated.hasSampleAggregation() is True


def test_round_trip_legacy_document_without_new_fields():
    """A BSON dict written before this feature shipped must rehydrate safely."""
    legacy = {
        "_id":                "ignored-by-feature-parsebson",
        "inputName":          "AT1G12345",
        "originalName":       "AT1G12345",
        "omicName":           "Gene Expression",
        "relevant":           [True, False],
        "relevantAssociation": False,
        "values":             [0.1, 0.2],
        # Note: NO sampleValues / sampleRelevant keys.
    }

    rehydrated = OmicValue("").parseBSON(dict(legacy))
    # Defaults must hold — no AttributeError.
    assert rehydrated.getSampleValues() is None
    assert rehydrated.getSampleRelevant() is None
    assert rehydrated.hasSampleAggregation() is False
    # And the original fields still load correctly.
    assert rehydrated.getValues() == [0.1, 0.2]
    assert rehydrated.isRelevant() == True


def test_round_trip_explicit_none_aggregation():
    """A document with explicit None values rehydrates as None."""
    ov = OmicValue("AT1G12345")
    ov.setValues([0.1, 0.2])
    ov.setRelevant([True, False])
    # sampleValues/sampleRelevant left as their default None.

    bson = ov.toBSON()
    assert bson["sampleValues"] is None
    assert bson["sampleRelevant"] is None

    rehydrated = OmicValue("").parseBSON(dict(bson))
    assert rehydrated.getSampleValues() is None
    assert rehydrated.getSampleRelevant() is None


def test_relevant_string_coercion_extends_to_sample_relevant():
    """Some serializers stringify booleans — sampleRelevant must coerce too."""
    legacy_with_strings = {
        "_id":                "x",
        "inputName":          "G",
        "originalName":       "G",
        "omicName":           "Gene Expression",
        "relevant":           ["True", "False"],
        "relevantAssociation": "False",
        "values":             [1.0, 2.0],
        "sampleRelevant":     ["True", "False"],
        "sampleValues":       [1.5],
    }
    rehydrated = OmicValue("").parseBSON(dict(legacy_with_strings))
    assert rehydrated.getSampleRelevant() == [True, False], (
        "sampleRelevant must coerce '\"True\"'/'\"False\"' strings just like "
        "the legacy `relevant` field does."
    )


# ---------------------------------------------------------------------------
# Feature → OmicValue containment
# ---------------------------------------------------------------------------

def test_feature_tobson_recursively_serializes_aggregation():
    """Gene/Compound.toBSON must include the new OmicValue fields."""
    g = Gene("AT1G12345")
    ov = OmicValue("AT1G12345")
    ov.setOmicName("Gene Expression")
    ov.setValues([0.1, 0.2, 0.5, 0.6])
    ov.setRelevant([True, True, False, False])
    ov.setSampleValues([0.15, 0.55])
    ov.setSampleRelevant([True, False])
    g.addOmicValue(ov)

    bson = g.toBSON()
    assert len(bson["omicsValues"]) == 1
    assert bson["omicsValues"][0]["sampleValues"]   == [0.15, 0.55]
    assert bson["omicsValues"][0]["sampleRelevant"] == [True, False]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

print("\n── OmicValue sample-aggregation fields ──────────────────────")
_check("Defaults: sampleValues/sampleRelevant are None",   test_defaults_are_none)
_check("Setters and getters round-trip in memory",         test_setters_and_getters)
_check("BSON round-trip preserves populated aggregation",  test_round_trip_with_aggregation_populated)
_check("Legacy BSON (no new fields) → None defaults",      test_round_trip_legacy_document_without_new_fields)
_check("Explicit None aggregation round-trips as None",    test_round_trip_explicit_none_aggregation)
_check("sampleRelevant coerces stringified booleans",      test_relevant_string_coercion_extends_to_sample_relevant)
_check("Feature.toBSON recurses into OmicValue aggregation", test_feature_tobson_recursively_serializes_aggregation)

print(f"\n{'─'*55}")
print(f"  Results: {len(_PASS)} passed, {len(_FAIL)} failed")
if _FAIL:
    print("\nFailed tests:")
    for name, msg in _FAIL:
        print(f"  ✗ {name}")
        first_line = msg.splitlines()[0] if msg else ""
        if first_line:
            print(f"    {first_line}")

sys.exit(1 if _FAIL else 0)
