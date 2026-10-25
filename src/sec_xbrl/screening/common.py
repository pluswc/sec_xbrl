"""Small defensive helpers shared by the screening consumer package."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

CIK_RE = re.compile(r"^\d{10}$")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^-]{0,15}$")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str = "JSON") -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc


def write_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def regular_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path.resolve()


def real_directory(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"{label} is not a real directory: {path}")
    return path.resolve()


def safe_new_destination(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    if absolute.exists():
        raise ValueError(f"{label} requires a new destination")
    return absolute


def safe_write_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    if absolute.exists() and not absolute.is_dir():
        raise ValueError(f"{label} is not a directory")
    absolute.mkdir(parents=True, exist_ok=True)
    if absolute.is_symlink() or absolute.resolve() != absolute:
        raise ValueError(f"{label} is not a real directory")
    return absolute


def contained_file(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError(f"unsafe {label} path")
    current = root.resolve()
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    if not current.is_file() or root.resolve() not in current.resolve().parents:
        raise ValueError(f"{label} is outside its publication")
    return current.resolve()


def atomic_replace(staging: Path, destination: Path) -> None:
    os.rename(staging, destination)


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def require_cik(value: Any, field: str = "cik") -> str:
    value = require_string(value, field)
    if not CIK_RE.fullmatch(value):
        raise ValueError(f"{field} must be a ten-digit CIK")
    return value


def require_ticker(value: Any, field: str = "ticker") -> str:
    value = require_string(value, field).upper()
    if not TICKER_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"{field} is unsafe")
    return value
