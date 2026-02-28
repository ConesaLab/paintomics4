"""
One-time script to remove orphaned documents from pathwaysCollection and
foundFeaturesCollection whose jobID no longer exists in jobInstanceCollection.

Usage:
    python cleanup_orphaned_data.py          # dry run (default)
    python cleanup_orphaned_data.py --run    # actually delete orphaned data
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + "/../")

from pymongo import MongoClient
from conf.serverconf import MONGODB_HOST, MONGODB_PORT, MONGODB_DATABASE


def cleanup_orphaned_data(dry_run=True):
    connection = MongoClient(MONGODB_HOST, MONGODB_PORT)
    db = connection[MONGODB_DATABASE]

    # Get the set of all valid jobIDs from jobInstanceCollection
    valid_job_ids = set()
    for doc in db['jobInstanceCollection'].find({}, {"jobID": 1}):
        if "jobID" in doc:
            valid_job_ids.add(doc["jobID"])

    print("Found {} valid jobs in jobInstanceCollection.".format(len(valid_job_ids)))

    collections_to_clean = ['pathwaysCollection', 'foundFeaturesCollection', 'featuresCollection', 'visualOptionsCollection']

    for coll_name in collections_to_clean:
        if coll_name not in db.list_collection_names():
            print("Collection {} does not exist, skipping.".format(coll_name))
            continue

        # Find distinct jobIDs in this collection
        all_job_ids = set(db[coll_name].distinct("jobID"))
        orphaned_job_ids = all_job_ids - valid_job_ids

        if not orphaned_job_ids:
            print("{}: no orphaned documents found.".format(coll_name))
            continue

        # Count orphaned documents
        orphaned_count = 0
        for job_id in orphaned_job_ids:
            orphaned_count += db[coll_name].count_documents({"jobID": job_id})

        total_count = db[coll_name].count_documents({})
        print("{}: {} orphaned documents out of {} total (from {} orphaned jobs)".format(
            coll_name, orphaned_count, total_count, len(orphaned_job_ids)))

        if dry_run:
            print("  [DRY RUN] Would delete {} documents.".format(orphaned_count))
        else:
            result = db[coll_name].delete_many({"jobID": {"$in": list(orphaned_job_ids)}})
            print("  Deleted {} documents.".format(result.deleted_count))

    if dry_run:
        print("\nThis was a dry run. Re-run with --run to actually delete orphaned data.")
    else:
        print("\nDone. Run db.stats() in mongo shell to verify reduced storage after compaction.")

    connection.close()


if __name__ == "__main__":
    dry_run = "--run" not in sys.argv
    cleanup_orphaned_data(dry_run=dry_run)
