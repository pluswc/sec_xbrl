"""Focused Node proof/transport checks for explicit auxiliary owner dispatch."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_auxiliary_union_node_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for companion transport tests")
    root = Path(__file__).resolve().parents[2]
    subprocess.run([node, str(root / "tests/screening/screening_auxiliary_union.test.cjs")], cwd=root, check=True)
