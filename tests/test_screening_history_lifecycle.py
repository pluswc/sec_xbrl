"""Focused Node history lifecycle and bridge checks, using fake workers only."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "posix" or shutil.which("node") is None,
                    reason="Node and POSIX fake-WSL executable are required")
def test_history_lifecycle_node_contract() -> None:
    result = subprocess.run(
        ["node", "--test", "tests/screening/screening_history_lifecycle.test.cjs"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=55, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
