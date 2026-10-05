"""Exclusive publication on local and non-hard-link filesystems; stdlib only."""

from __future__ import annotations
import errno
import os
from pathlib import Path
import shutil
import tempfile


def publish(staged: Path, output: Path):
    """Never overwrite. Copy fallback is exclusive but visible before completion."""
    try:
        os.link(staged, output)
        return "atomic_hard_link"
    except OSError as exc:
        if exc.errno not in {
            errno.EXDEV,
            errno.EPERM,
            errno.EACCES,
            errno.ENOSYS,
            errno.EOPNOTSUPP,
            errno.ENOTSUP,
        }:
            raise
    owned = None
    try:
        with output.open("xb") as destination:
            owned = os.fstat(destination.fileno())
            with staged.open("rb") as source:
                shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        return "exclusive_copy"
    except BaseException:
        if owned is not None:
            try:
                actual = output.stat()
                if (actual.st_dev, actual.st_ino) == (owned.st_dev, owned.st_ino):
                    output.unlink()
            except OSError:
                pass
        raise


def check_report_path(output):
    if not output.is_absolute() or output.suffix.lower() != ".json":
        raise ValueError("Report must use an absolute new .json path")
    if output.exists() or output.is_symlink():
        raise ValueError("Report already exists; choose a new path")


def write_json(report, output):
    import json

    if not output.is_absolute() or output.suffix.lower() != ".json":
        raise ValueError("Report must use an absolute new .json path")
    if output.exists() or output.is_symlink():
        raise ValueError("Report already exists; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".sdk-report-", dir=output.parent
    ) as directory:
        staged = Path(directory) / "report.json"
        staged.write_text(
            json.dumps(report, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        publish(staged, output)
