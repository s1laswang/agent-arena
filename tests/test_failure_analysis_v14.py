"""docs/reports/failure_analysis_v1.4.md must be exactly what scripts/failure_analysis_v14.py computes from the
committed v1.4 episodes (every number in the report is code-computed; no hand-edited figures)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_failure_analysis_v14_reproduces():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/failure_analysis_v14.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr


def test_approx_equal_float_tolerance():
    sys.path.insert(0, str(ROOT / "scripts"))
    from failure_analysis_v14 import approx_equal

    assert approx_equal({"x": [0.2621565392513171]}, {"x": [0.26215653925131843]})
    assert not approx_equal({"x": [0.2621565]}, {"x": [0.2621580]})
    assert not approx_equal({"flag": True}, {"flag": 1})
    assert not approx_equal({"seed": 3}, {"seed": 4})
