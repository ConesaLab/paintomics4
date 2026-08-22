import sys

sys.path.insert(0, "/home/tian/paintomics4/PaintomicsServer/")

from src.launch_server import app as application  # noqa: F401 -- uWSGI reads `application` from this module's namespace; the import IS the entry point
