"""FileSystem signal — observe files, sizes, ages, permissions."""

from __future__ import annotations

import os
import stat
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from fixit.signals.base import Signal


class FileSystemSignal(Signal):
    """Watch a directory tree for file system state."""

    name = "filesystem"

    def __init__(self, path: str, watch: list[str] | None = None, max_depth: int = 3):
        self.path = Path(path)
        self.watch = watch or ["*"]
        self.max_depth = max_depth

    def collect(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"error": f"{self.path} does not exist", "files": []}

        files = []
        now = time.time()

        for root, dirs, filenames in os.walk(self.path):
            depth = str(root).count(os.sep) - str(self.path).count(os.sep)
            if depth >= self.max_depth:
                dirs.clear()
                continue

            for fname in filenames:
                if not any(fnmatch(fname, pat) for pat in self.watch):
                    continue

                fpath = Path(root) / fname
                try:
                    st = fpath.stat()
                    files.append({
                        "path": str(fpath),
                        "size_bytes": st.st_size,
                        "age_hours": round((now - st.st_mtime) / 3600, 1),
                        "writable": os.access(fpath, os.W_OK),
                        "is_empty": st.st_size == 0,
                    })
                except (OSError, PermissionError):
                    files.append({"path": str(fpath), "error": "unreadable"})

        # Summary stats
        sizes = [f["size_bytes"] for f in files if "size_bytes" in f]
        return {
            "root": str(self.path),
            "file_count": len(files),
            "total_bytes": sum(sizes),
            "largest_file": max(files, key=lambda f: f.get("size_bytes", 0))["path"] if sizes else None,
            "files": files,
        }

    def describe(self) -> str:
        return f"Filesystem at {self.path} (patterns: {self.watch})"
