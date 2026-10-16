"""Run the JavaScript checker of Promptfoo text assertions (same regex engine as Promptfoo)."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    shutil.which("node") is None or not (ROOT / "node_modules" / "js-yaml").exists(),
    reason="node or node_modules not installed",
)
def test_yaml_assertions_accept_good_and_reject_bad_outputs():
    completed = subprocess.run(
        ["node", str(ROOT / "evals" / "tests" / "check_assertions.js")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
