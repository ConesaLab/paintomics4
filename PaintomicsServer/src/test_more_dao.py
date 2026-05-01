
import sys
import os

# Add the project root to sys.path
sys.path.append("/home/leyls/github/paintomics4/PaintomicsServer/src")

try:
    from src.classes.JobInstances.MOREJob import MOREJob
    from src.common.DAO.MOREJobDAO import MOREJobDAO
    from src.conf.serverconf import CLIENT_TMP_DIR
    import logging

    # Configure basic logging to see what's happening
    logging.basicConfig(level=logging.INFO)

    print("Testing MOREJobDAO instantiation...")
    dao = MOREJobDAO()
    
    print(f"DAO initialized. Collection name: {dao.collectionName}")
    print(f"DB Manager: {dao.dbManager}")

    # Create a mock job
    mock_job = MOREJob("test_job_123", "test_user", CLIENT_TMP_DIR)
    mock_job.method = "PLS1"
    mock_job.addRegulatoryOmic("TF", "fake_path.txt", "Regulatory Data")

    print("Attempting to insert mock job...")
    # We might not have a real DB connection in this environment, but we can check if it fails before the DB call
    try:
        dao.insert(mock_job)
        print("Insert call completed successfully (or at least didn't raise NotImplemented/AttributeError)!")
    except Exception as db_err:
        print(f"Caught database error (expected if DB is down, but shouldn't be AttributeError): {type(db_err).__name__}: {db_err}")

except Exception as e:
    print(f"CRITICAL TEST FAILURE: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
