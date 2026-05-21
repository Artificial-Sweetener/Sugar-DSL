#    Compose human-readable ComfyUI workflows with SugarCubes
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Catalog registry for cube assets."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import CubeDocument, validate_cube_document

logger = logging.getLogger(__name__)


class CubeRegistry:
    """Index and load cube assets from a root directory."""

    _SKIP_DIRS = {"old", "backup", "_old", "_history"}

    def __init__(self, root: Path) -> None:
        """Create and scan a registry rooted at a cube directory."""

        self.root = Path(root).resolve()
        self._index: dict[str, Path] = {}
        self._versions: dict[str, str] = {}
        self.scan()

    @property
    def index(self) -> dict[str, Path]:
        """Return a copy of the cube index."""

        return dict(self._index)

    @property
    def versions(self) -> dict[str, str]:
        """Return a copy of the cube version map."""

        return dict(self._versions)

    def scan(self) -> None:
        """Scan the root for .cube files and build the index."""

        if not self.root.exists():
            logger.error(
                "Cube root does not exist.",
                extra={"operation": "scan_cube_registry", "cube_root": str(self.root)},
            )
            raise RuntimeError(f"Cube root '{self.root}' does not exist.")

        self._index.clear()
        self._versions.clear()
        for path in self.root.rglob("*.cube"):
            if self._should_skip_path(path):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(
                    "Failed to read cube during registry scan.",
                    extra={
                        "operation": "scan_cube_registry",
                        "cube_root": str(self.root),
                        "cube_path": str(path),
                        "error": str(exc),
                    },
                )
                raise RuntimeError(f"Failed to read cube '{path}': {exc}") from exc

            cube = validate_cube_document(payload)
            cube_id = cube.get("cube_id")
            version = cube.get("version")
            if not cube_id or not version:
                raise RuntimeError(f"Cube '{path}' is missing required metadata (cube_id/version).")
            if cube_id in self._index:
                existing = self._index[cube_id]
                logger.error(
                    "Duplicate cube id found during registry scan.",
                    extra={
                        "operation": "scan_cube_registry",
                        "cube_root": str(self.root),
                        "cube_id": cube_id,
                        "existing_path": str(existing),
                        "cube_path": str(path),
                    },
                )
                raise RuntimeError(
                    f"Duplicate cube id '{cube_id}' found at '{existing}' and '{path}'."
                )
            self._index[cube_id] = path.resolve()
            self._versions[cube_id] = str(version)

    def _should_skip_path(self, path: Path) -> bool:
        """Return whether a discovered cube path is under a skipped directory."""

        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        for part in relative.parts:
            if part.lower() in self._SKIP_DIRS:
                return True
        return False

    def get_path(self, cube_id: str) -> Path:
        """Resolve the filesystem path for a cube id."""

        try:
            return self._index[cube_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._index.keys()))
            raise RuntimeError(f"Cube '{cube_id}' not found. Available: {available}") from exc

    def get_version(self, cube_id: str) -> str:
        """Return the catalog version for a cube id."""

        try:
            return self._versions[cube_id]
        except KeyError as exc:
            raise RuntimeError(f"Cube '{cube_id}' not found in catalog.") from exc

    def load_cube(self, cube_id: str, version_pin: str | None = None) -> CubeDocument:
        """Load and validate a cube document by id."""

        path = self.get_path(cube_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Failed to load cube.",
                extra={
                    "operation": "load_cube",
                    "cube_root": str(self.root),
                    "cube_id": cube_id,
                    "cube_path": str(path),
                    "error": str(exc),
                },
            )
            raise RuntimeError(
                f"Failed to load or parse cube '{cube_id}' from '{path}': {exc}"
            ) from exc

        cube = validate_cube_document(payload)
        doc_id = cube.get("cube_id")
        if doc_id != cube_id:
            logger.error(
                "Cube id mismatch.",
                extra={
                    "operation": "load_cube",
                    "cube_root": str(self.root),
                    "cube_id": cube_id,
                    "declared_cube_id": doc_id,
                    "cube_path": str(path),
                },
            )
            raise RuntimeError(f"Cube id mismatch for '{cube_id}': file declares '{doc_id}'.")
        if version_pin is not None:
            actual_version = cube.get("version")
            if actual_version != version_pin:
                logger.error(
                    "Cube version mismatch.",
                    extra={
                        "operation": "load_cube",
                        "cube_root": str(self.root),
                        "cube_id": cube_id,
                        "version_pin": version_pin,
                        "actual_version": actual_version,
                    },
                )
                raise RuntimeError(
                    f"Cube '{cube_id}' version mismatch: expected '{version_pin}', got '{actual_version}'."
                )
        cube["__template__"] = cube_id
        return cube
