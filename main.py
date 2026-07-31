"""Compatibility ASGI entrypoint for deployments started from the repository root.

The canonical production application lives in ``myjamrobot/`` and should be
started with ``python -m app.bootstrap``.  This module only prevents platforms
or operators that still invoke ``uvicorn main:app`` from loading the unrelated
workspace stub that previously existed at the repository root.
"""
from __future__ import annotations

from pathlib import Path
import runpy
import sys


_PROJECT_ROOT = Path(__file__).resolve().parent / "myjamrobot"
if not _PROJECT_ROOT.is_dir():
    raise RuntimeError(f"BillySNCbot application directory not found: {_PROJECT_ROOT}")

_project_root_text = str(_PROJECT_ROOT)
if _project_root_text not in sys.path:
    sys.path.insert(0, _project_root_text)

# Re-export the single canonical FastAPI instance.  No second application is
# created here, so lifecycle hooks, routers and readiness state remain shared
# with ``app.main:app``.
from app.main import app as app  # noqa: E402

__all__ = ["app"]


def main() -> None:
    """Delegate direct execution to the canonical bootstrap module."""
    runpy.run_module("app.bootstrap", run_name="__main__")


if __name__ == "__main__":
    main()
