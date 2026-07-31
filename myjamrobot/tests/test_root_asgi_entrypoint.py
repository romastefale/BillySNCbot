from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = REPOSITORY_ROOT / "myjamrobot"


def _test_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    env["MYJAM_DATA_DIR"] = str(data_dir)
    env["MYJAM_DATABASE_URL"] = f"sqlite:///{data_dir / 'app.db'}"
    return env


def _run_import_check(*, cwd: Path, code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_root_main_exports_the_canonical_asgi_app(tmp_path: Path) -> None:
    result = _run_import_check(
        cwd=REPOSITORY_ROOT,
        env=_test_env(tmp_path),
        code=(
            "import main; "
            "from app.main import app as canonical; "
            "assert main.app is canonical; "
            "assert callable(main.app)"
        ),
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_application_package_still_exports_the_canonical_asgi_app(tmp_path: Path) -> None:
    result = _run_import_check(
        cwd=APPLICATION_ROOT,
        env=_test_env(tmp_path),
        code="from app.main import app; assert callable(app)",
    )

    assert result.returncode == 0, result.stderr or result.stdout
