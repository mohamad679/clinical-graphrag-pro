#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GITKEEP_PATHS = (
    Path("backend/uploads/images/.gitkeep"),
    Path("backend/uploads/thumbnails/.gitkeep"),
    Path("backend/data/vector_store/.gitkeep"),
    Path("backend/data/bm25_store/.gitkeep"),
    Path("uploads/documents/.gitkeep"),
    Path("uploads/images/.gitkeep"),
    Path("uploads/thumbnails/.gitkeep"),
)


def ensure_gitkeep(relative_path: Path) -> None:
    target_path = REPO_ROOT / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.touch(exist_ok=True)


def main() -> int:
    for relative_path in GITKEEP_PATHS:
        ensure_gitkeep(relative_path)
        print(relative_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
