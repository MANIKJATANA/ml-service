"""Pytest configuration for the backend tests.

pytest runs with ``--import-mode=importlib`` (root pyproject), which does not add
test directories to ``sys.path``. Insert this directory so the shared, test-only
doubles in ``backend_fakes.py`` are importable across the test modules. The module is
uniquely named (not ``fakes``) to avoid colliding with the ML service's ``fakes.py``
under importlib import mode.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
