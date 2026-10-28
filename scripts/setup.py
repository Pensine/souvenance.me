#!/usr/bin/env python3
"""Setup wizard: python3 scripts/setup.py (--help for the options).

Standard library only — it runs before any installation, with the Python
provided by the system (3.9 and later).
"""

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or later is required for the wizard.")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine.setup_wizard import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
