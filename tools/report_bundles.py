from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import zipfile

from mcp.server.fastmcp import FastMCP

from tools.artifacts import ART_DIR, _safe_name


def _ensure_artifacts_dir() -> Path:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    return ART_DIR


def _select_recent_files(base: Path, limit: int, exclude: Optional[set[str]] = None) -> List[str]:
    candidates: List[tuple[float, str]] = []
    for entry in base.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if exclude and name in exclude:
            continue
        stat = entry.stat()
        candidates.append((stat.st_mtime, name))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in candidates[:limit]]


def _resolve_requested(base: Path, filenames: Iterable[str]) -> List[str]:
    resolved: List[str] = []
    for raw in filenames:
        try:
            name = _safe_name(raw)
        except ValueError:
            raise ValueError(f"Invalid artifact name: {raw!r}")
        path = base / name
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {name}")
        resolved.append(name)
    return resolved


def register_report_bundle_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def bundle_latest(name: str = "bundle.zip", include: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create an artifact bundle zip. Includes either the provided artifact filenames or, if omitted,
        the 10 most recent artifacts. The resulting zip is saved within the artifacts directory.
        """
        include = include or []
        artifacts_dir = _ensure_artifacts_dir()

        try:
            zip_name = _safe_name(name)
        except ValueError:
            return {"ok": False, "error": "Invalid bundle filename", "filename": name}

        try:
            if include:
                selected = _resolve_requested(artifacts_dir, include)
            else:
                selected = _select_recent_files(artifacts_dir, 10, exclude={zip_name})
        except (ValueError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}

        zip_path = artifacts_dir / zip_name

        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for fname in selected:
                file_path = artifacts_dir / fname
                bundle.write(file_path, arcname=fname)

        return {"ok": True, "filename": zip_name, "count": len(selected)}
