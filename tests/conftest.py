from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TEST_DATA_ROOT = Path(__file__).parent / "data" / "sample_repo"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "sample_repo"
    shutil.copytree(_TEST_DATA_ROOT, dest)
    return dest


@pytest.fixture
def repo_with_ir(sample_repo: Path, project_root: Path) -> Path:
    cmd = [sys.executable, "-m", "neurocode.cli", "ir", str(sample_repo)]
    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to build IR for sample repo:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return sample_repo
