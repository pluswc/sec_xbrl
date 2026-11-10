"""Run the Node frontend companion contract in the normal pytest entry point."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "posix" or shutil.which("node") is None,
                    reason="Node and POSIX fake-WSL executable are required for bridge tests")
def test_display_companion_node_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", "tests/screening/screening_display_assets.test.cjs",
         "tests/screening/screening_explorer_period_basis.test.cjs",
         "tests/screening/screening_company_trends.test.cjs",
         "tests/screening/screening_indexed_trends_usability.test.cjs",
         "tests/screening/screening_financial_growth.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
