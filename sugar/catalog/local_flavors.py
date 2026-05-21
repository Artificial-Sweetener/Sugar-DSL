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
"""Catalog access for disk-backed SugarCubes local flavors."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from .models import FlavorEntry


_WHITESPACE_RE = re.compile(r"\s+")
logger = logging.getLogger(__name__)


def normalize_flavor_name_key(value: str) -> str:
    """Return the shared case-insensitive flavor name collision key."""

    return _WHITESPACE_RE.sub(" ", value.strip()).casefold()


class LocalFlavorCatalog:
    """Read local flavor JSON files from an explicit SugarCubes flavor root."""

    def __init__(self, root: Path | None) -> None:
        """Initialize the local flavor catalog with an optional root."""

        self.root = Path(root).resolve() if root is not None else None

    def load_flavors(self, cube_id: str, surface_signature: str) -> list[FlavorEntry]:
        """Return local flavors for one cube surface."""

        if self.root is None:
            return []
        path = self._path_for_cube_id(cube_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error(
                "Local flavor file is not valid JSON.",
                extra={
                    "operation": "load_local_flavors",
                    "cube_id": cube_id,
                    "surface_signature": surface_signature,
                    "flavor_path": str(path),
                    "error": str(exc),
                },
            )
            raise RuntimeError(
                f"Local flavor file for cube '{cube_id}' is not valid JSON."
            ) from exc
        except OSError as exc:
            logger.error(
                "Failed to read local flavor file.",
                extra={
                    "operation": "load_local_flavors",
                    "cube_id": cube_id,
                    "surface_signature": surface_signature,
                    "flavor_path": str(path),
                    "error": str(exc),
                },
            )
            raise RuntimeError(
                f"Failed to read local flavor file for cube '{cube_id}': {exc}"
            ) from exc
        try:
            return self._validate_payload(payload, cube_id, surface_signature)
        except RuntimeError as exc:
            logger.error(
                "Local flavor state validation failed.",
                extra={
                    "operation": "load_local_flavors",
                    "cube_id": cube_id,
                    "surface_signature": surface_signature,
                    "flavor_path": str(path),
                    "error": str(exc),
                },
            )
            raise

    def _path_for_cube_id(self, cube_id: str) -> Path:
        """Return the hashed local flavor state path for one cube id."""

        if self.root is None:
            raise RuntimeError("Local flavor root is not configured.")
        digest = hashlib.sha256(cube_id.encode("utf-8")).hexdigest()
        return self.root / "by-cube" / f"{digest}.json"

    def _validate_payload(
        self, payload: Any, cube_id: str, surface_signature: str
    ) -> list[FlavorEntry]:
        """Validate a local flavor JSON payload and return matching entries."""

        if not isinstance(payload, dict):
            raise RuntimeError("Local flavor state must be a JSON object.")
        if payload.get("schema_version") != 1:
            raise RuntimeError("Local flavor state uses an unsupported schema version.")
        if payload.get("cube_id") != cube_id:
            raise RuntimeError(
                f"Local flavor file cube id mismatch: expected '{cube_id}', got '{payload.get('cube_id')}'."
            )
        surfaces = payload.get("surfaces")
        if not isinstance(surfaces, dict):
            raise RuntimeError("Local flavor state must include a 'surfaces' object.")
        surface_state = surfaces.get(surface_signature)
        if surface_state is None:
            return []
        if not isinstance(surface_state, dict):
            raise RuntimeError("Local flavor surface state must be an object.")
        flavors = surface_state.get("flavors")
        if not isinstance(flavors, list):
            raise RuntimeError("Local flavor surface state must include a 'flavors' array.")
        return [self._validate_flavor(entry) for entry in flavors]

    def _validate_flavor(self, payload: Any) -> FlavorEntry:
        """Validate one local flavor entry."""

        if not isinstance(payload, dict):
            raise RuntimeError("Local flavor entry must be an object.")
        flavor_id = payload.get("id")
        name = payload.get("name")
        values = payload.get("values")
        if not isinstance(flavor_id, str) or not flavor_id.strip():
            raise RuntimeError("Local flavor entry must include a non-empty 'id'.")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("Local flavor entry must include a non-empty 'name'.")
        if not isinstance(values, dict):
            raise RuntimeError("Local flavor entry must include a 'values' object.")
        return {
            "id": flavor_id.strip(),
            "name": name.strip(),
            "values": copy.deepcopy(values),
        }
