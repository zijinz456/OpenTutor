import os
import sys

os.environ.setdefault("PYTEST_VERSION", "1")
os.environ.setdefault("DISABLE_RATE_LIMIT", "1")

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
API_DIR = os.path.join(ROOT_DIR, "apps", "api")

if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)
