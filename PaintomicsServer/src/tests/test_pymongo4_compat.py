"""pymongo 4 compatibility.

Run from `PaintomicsServer/`:

    python -m src.tests.test_pymongo4_compat

The deployment runs MongoDB 7. pymongo 3.11 (the version both requirements
files pinned) speaks legacy wire-protocol opcodes that MongoDB removed in 5.1,
so the pin had to move to pymongo 4 and the removed APIs had to go with it.

The dangerous ones were the two Cursor.count() calls in
FeatureNamesToKeggIDsMapper: they sit inside `except Exception: return [], False`,
so under pymongo 4 the AttributeError would have been swallowed and every
feature lookup would have silently reported "not found" -- a server that starts,
serves pages, and maps nothing.

The source scan needs no database. The round-trip test is skipped when no
mongod is reachable.
"""
import os
import re
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PASSED = []
_FAILED = []

_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        print(f"ERROR {name}:\n{traceback.format_exc()}")


def _pythonSources():
    for dirPath, dirNames, fileNames in os.walk(_SRC_ROOT):
        dirNames[:] = [d for d in dirNames if d not in ("__pycache__", ".git")]
        for fileName in fileNames:
            if fileName.endswith(".py"):
                yield os.path.join(dirPath, fileName)


# APIs pymongo removed in 4.0. Anchored on a subscript or attribute access that
# looks like a collection so dict.update() and list.count() do not match.
# How a pymongo Collection is actually referred to in this codebase.
#
# `collection` is the important one and was the gap: every DAO does
#   collection = self.dbManager.getCollection(self.collectionName)
# and then calls collection.insert(...). The old patterns only recognised
# `db.<name>.` and `...Collection'].`, so all 28 DAO call sites went unnoticed
# and the server died saving its very first job with
#   'Collection' object is not callable ... no such method exists
#
# Matching every receiver instead is not the answer -- daoInstance.insert() is
# PaintOmics' own DAO wrapper, and matchedFeatures.update() is a dict. Both are
# fine. Name the receivers that really are collections.
_COLLECTION_RECEIVER = r"(?:\bcollection|\bcoll|\bdb\.\w+|Collection'\])"

_REMOVED_APIS = [
    ("Cursor.count()",             re.compile(r"\b(?:cursor\w*|acceptedIDs)\.count\(\)", re.IGNORECASE)),
    ("Collection.insert()",        re.compile(_COLLECTION_RECEIVER + r"\.insert\(")),
    ("Collection.save()",          re.compile(_COLLECTION_RECEIVER + r"\.save\(")),
    ("Collection.remove()",        re.compile(_COLLECTION_RECEIVER + r"\.remove\(")),
    ("Collection.update()",        re.compile(_COLLECTION_RECEIVER + r"\.update\(")),
    ("Collection.ensure_index()",  re.compile(r"\.ensure_index\(")),
    ("Database.authenticate()",    re.compile(r"\.authenticate\(")),
    ("Database.collection_names()", re.compile(r"\.collection_names\(")),
    ("Database.eval()",            re.compile(r"\bdb\.eval\(")),
    ("Collection.map_reduce()",    re.compile(r"\.map_reduce\(")),
    ("add_son_manipulator",        re.compile(r"add_son_manipulator")),
]


def test_no_removed_pymongo_apis_remain():
    findings = []
    for sourcePath in _pythonSources():
        if os.path.basename(sourcePath) == "test_pymongo4_compat.py":
            continue
        with open(sourcePath, "r", errors="ignore") as handle:
            content = handle.read()
        for lineNumber, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for label, pattern in _REMOVED_APIS:
                if pattern.search(line):
                    relative = os.path.relpath(sourcePath, _SRC_ROOT)
                    findings.append(f"{relative}:{lineNumber}: {label} -> {stripped[:80]}")

    assert not findings, \
        "pymongo APIs removed in 4.0 are still in use:\n  " + "\n  ".join(findings)


def test_count_guard_removed_from_feature_mapper():
    """Specifically guard the two sites whose failure would have been silent."""
    mapperPath = os.path.join(_SRC_ROOT, "common", "FeatureNamesToKeggIDsMapper.py")
    with open(mapperPath) as handle:
        content = handle.read()

    assert "cursor.count()" not in content, \
        "FeatureNamesToKeggIDsMapper still calls cursor.count(); under pymongo 4 the " \
        "surrounding `except Exception` makes every feature lookup silently return no match"


def _mongoAvailable():
    try:
        import pymongo
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = pymongo.MongoClient(MONGODB_HOST, MONGODB_PORT,
                                     serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        return client
    except Exception:
        return None


def test_replacement_apis_round_trip_against_a_real_server():
    """Exercise exactly the replacements used in the migration."""
    client = _mongoAvailable()
    if client is None:
        print("      (skipped: no reachable mongod)")
        return

    import pymongo
    databaseName = "PaintomicsPymongo4CompatTest"
    try:
        db = client[databaseName]
        collection = db["jobInstanceCollection"]
        collection.delete_many({})

        collection.insert_many([
            {"jobID": "job-1", "userID": "u1", "reminderSent": 0},
            {"jobID": "job-1", "userID": "u1", "reminderSent": 0},
            {"jobID": "job-2", "userID": "u2", "reminderSent": 0},
        ])

        # update_many replaces update(..., multi-by-default) in clean_databases.
        result = collection.update_many({"jobID": "job-1"},
                                        {"$set": {"reminderSent": 1}}, upsert=False)
        assert result.modified_count == 2, \
            f"update_many touched {result.modified_count} docs, expected 2"

        # find_one replaces `find(...)` + Cursor.count() + `[0]`.
        found = collection.find_one({"jobID": "job-2"})
        assert found is not None and found["userID"] == "u2"
        assert collection.find_one({"jobID": "does-not-exist"}) is None, \
            "find_one must return None rather than raising, for the empty case"

        # count_documents replaces Cursor.count().
        assert collection.count_documents({"reminderSent": 1}) == 2

        # Iterating an empty cursor is a no-op -- the behaviour the removed
        # count() guard was standing in for.
        assert list(collection.find({"jobID": "nope"})) == []

        # delete_many replaces remove().
        deleted = collection.delete_many({"jobID": "job-1"})
        assert deleted.deleted_count == 2, \
            f"delete_many removed {deleted.deleted_count} docs, expected 2"
        assert collection.count_documents({}) == 1

        # Prove the old APIs really are gone on this pymongo, so this file is
        # not silently passing against pymongo 3.
        #
        # hasattr() is useless here: Collection.__getattr__ returns a
        # sub-collection for any unknown name, so `collection.remove` is a
        # Collection object and hasattr is always True. The failure only appears
        # when it is *called*, and it is a TypeError ("Collection object is not
        # callable"), not an AttributeError. Cursor.count() differs again --
        # that one is a plain AttributeError.
        #
        # Both are Exception subclasses, which is precisely why the old code's
        # `except Exception: return [], False` would have turned a hard API
        # removal into a server that silently matches no features.
        if int(pymongo.version.split(".")[0]) >= 4:
            for removed in ("remove", "insert", "update", "save"):
                try:
                    getattr(collection, removed)({"jobID": "job-2"})
                except TypeError:
                    pass
                else:
                    raise AssertionError(
                        f"Collection.{removed}() still executed on pymongo 4")

            try:
                collection.find({}).count()
            except AttributeError:
                pass
            else:
                raise AssertionError("Cursor.count() still executed on pymongo 4")
    finally:
        try:
            client.drop_database(databaseName)
        except Exception:
            pass


def main():
    import pymongo
    print(f"pymongo {pymongo.version}\n")

    tests = [
        test_no_removed_pymongo_apis_remain,
        test_count_guard_removed_from_feature_mapper,
        test_replacement_apis_round_trip_against_a_real_server,
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
