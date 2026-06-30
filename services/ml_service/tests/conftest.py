"""Pytest configuration for the ML service tests.

pytest runs with ``--import-mode=importlib`` (root pyproject), which does not add
test directories to ``sys.path``. Insert this directory so the shared, test-only
doubles in ``fakes.py`` are importable from ``tests/unit/``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
