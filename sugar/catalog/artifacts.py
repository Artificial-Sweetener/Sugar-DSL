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
"""Cube artifact resolution contracts for compiler materialization."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .models import CubeDocument, validate_cube_document
from .registry import CubeRegistry


@dataclass(frozen=True, slots=True)
class CubeArtifactIdentity:
    """Describe the resolved definition identity for one cube artifact."""

    cube_id: str
    requested_version: str | None
    resolved_version: str


@dataclass(frozen=True, slots=True)
class ResolvedCubeArtifact:
    """Pair a normalized cube document with exact definition identity."""

    cube: CubeDocument
    identity: CubeArtifactIdentity


class CubeArtifactResolver(Protocol):
    """Resolve a Sugar use-statement to one concrete cube artifact."""

    def resolve(
        self,
        *,
        alias: str,
        cube_id: str,
        requested_version: str | None,
    ) -> ResolvedCubeArtifact:
        """Return the artifact selected for one workflow-local alias."""


class FilesystemCubeArtifactResolver:
    """Resolve cube artifacts from the standalone filesystem registry."""

    def __init__(self, registry: CubeRegistry) -> None:
        """Create a resolver backed by one scanned cube registry."""

        self._registry = registry

    def resolve(
        self,
        *,
        alias: str,
        cube_id: str,
        requested_version: str | None,
    ) -> ResolvedCubeArtifact:
        """Resolve one artifact using the registry's current cube id mapping."""

        _ = alias
        cube = self._registry.load_cube(cube_id, version_pin=requested_version)
        return ResolvedCubeArtifact(
            cube=cube,
            identity=CubeArtifactIdentity(
                cube_id=cube_id,
                requested_version=requested_version,
                resolved_version=str(cube.get("version") or ""),
            ),
        )


class InMemoryCubeArtifactResolver:
    """Resolve alias-specific artifacts supplied by an embedding application."""

    def __init__(self, artifacts_by_alias: Mapping[str, Mapping[str, object]]) -> None:
        """Store backend-provided artifacts keyed by exact Sugar alias."""

        self._artifacts_by_alias = {
            alias: dict(artifact) for alias, artifact in artifacts_by_alias.items()
        }

    def resolve(
        self,
        *,
        alias: str,
        cube_id: str,
        requested_version: str | None,
    ) -> ResolvedCubeArtifact:
        """Resolve one alias to the exact artifact supplied by the caller."""

        artifact = self._artifact_for_alias(alias)
        declared_cube_id = _required_text(artifact, "cubeId")
        if declared_cube_id != cube_id:
            raise RuntimeError(
                f"Alias '{alias}' requested cube '{cube_id}', but its artifact "
                f"declares '{declared_cube_id}'."
            )
        resolved_version = _required_text(artifact, "version")
        if requested_version is not None and resolved_version != requested_version:
            raise RuntimeError(
                f"Alias '{alias}' cube '{cube_id}' version mismatch: "
                f"expected '{requested_version}', got '{resolved_version}'."
            )
        cube_payload = artifact.get("cube")
        if not isinstance(cube_payload, Mapping):
            raise RuntimeError(
                f"Alias '{alias}' cube '{cube_id}' artifact is missing a cube payload."
            )
        cube = validate_cube_document(dict(cube_payload))
        return ResolvedCubeArtifact(
            cube=copy.deepcopy(cube),
            identity=CubeArtifactIdentity(
                cube_id=cube_id,
                requested_version=requested_version,
                resolved_version=resolved_version,
            ),
        )

    def _artifact_for_alias(self, alias: str) -> Mapping[str, object]:
        """Return the artifact for one alias or fail with context."""

        try:
            return self._artifacts_by_alias[alias]
        except KeyError as exc:
            available = ", ".join(sorted(self._artifacts_by_alias))
            raise RuntimeError(
                f"No cube artifact was provided for alias '{alias}'. Available aliases: {available}"
            ) from exc


def _required_text(payload: Mapping[str, object], key: str) -> str:
    """Read one required non-empty text field from an artifact payload."""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError(f"Cube artifact is missing required field '{key}'.")


def artifact_from_cube_payload(
    *,
    cube: Mapping[str, object],
) -> dict[str, object]:
    """Build an in-memory artifact payload from a raw cube document."""

    return {
        "schemaVersion": 1,
        "cubeId": _required_text(cube, "cube_id"),
        "version": _required_text(cube, "version"),
        "cube": dict(cube),
    }
