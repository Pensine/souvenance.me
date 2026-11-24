"""The public admission demo runs offline and shows what its README says."""

import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "admission-demo" / "demo.py"


def test_demo_output():
    out = subprocess.run([sys.executable, str(DEMO)], capture_output=True, text=True,
                         timeout=60, check=True).stdout
    assert out.count("-> REFUSED  (no excerpt cited)") == 1
    assert out.count("-> REFUSED  (excerpt not found in the deposit)") == 1
    assert out.count("-> KEPT, FLAGGED") == 1 and "not in the deposit: 15" in out
    assert out.count("-> ADMITTED  (excerpt found") == 2
    assert "-> REFUSED  (excerpt_not_found)" in out
    assert "-> REFUSED  (alias_not_in_excerpt)" in out
    assert "-> ADMITTED  (excerpt)" in out
