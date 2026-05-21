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
"""Flavor resolution and materialization helpers for the Sugar compiler."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from ..catalog.local_flavors import normalize_flavor_name_key
from ..catalog.models import CubeDocument, FlavorEntry


FlavorScope = Literal["authored", "local"]


@dataclass(frozen=True)
class ResolvedFlavor:
    """Flavor selected for one cube instance."""

    id: str
    name: str
    scope: FlavorScope
    values: dict[str, Any]


def apply_flavor_values(cube: CubeDocument, flavor: FlavorEntry) -> CubeDocument:
    """Return a cube copy with surface flavor values applied to implementation nodes."""

    next_cube: CubeDocument = copy.deepcopy(cube)
    controls = _control_index(next_cube)
    for control_id, value in flavor.get("values", {}).items():
        control = controls.get(control_id)
        if control is None:
            continue
        node = next_cube["nodes"].get(control["symbol"])
        if not isinstance(node, dict):
            continue
        node.setdefault("inputs", {})[control["input_name"]] = copy.deepcopy(value)
    return next_cube


def apply_default_flavor(cube: CubeDocument) -> CubeDocument:
    """Return a cube copy with its default authored flavor materialized."""

    default_id = str(cube.get("surface", {}).get("default_flavor_id") or "default")
    flavor = _find_authored_by_id(cube, default_id) or _find_authored_by_id(cube, "default")
    if flavor is None:
        return copy.deepcopy(cube)
    return apply_flavor_values(cube, flavor)


def compute_surface_signature(cube: CubeDocument) -> str:
    """Compute the SugarCubes surface signature used by local flavor storage."""

    serialized = json.dumps(
        cube.get("surface", {}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:12]


def resolve_flavor(
    cube: CubeDocument,
    requested: str | None,
    local_flavors: list[FlavorEntry],
) -> ResolvedFlavor:
    """Resolve a DSL flavor request against authored and local flavor entries."""

    authored = list(cube.get("flavors", {}).get("authored", []))
    _raise_on_collisions(authored, local_flavors)
    if requested is None:
        default_id = str(cube.get("surface", {}).get("default_flavor_id") or "default")
        flavor = _find_flavor(authored, default_id)
        if flavor is None:
            raise RuntimeError(f"Default flavor '{default_id}' is not available.")
        return ResolvedFlavor(
            id=flavor["id"],
            name=flavor["name"],
            scope="authored",
            values=copy.deepcopy(flavor["values"]),
        )
    candidate = _find_flavor(authored, requested)
    if candidate is not None:
        return ResolvedFlavor(
            id=candidate["id"],
            name=candidate["name"],
            scope="authored",
            values=copy.deepcopy(candidate["values"]),
        )
    candidate = _find_flavor(local_flavors, requested)
    if candidate is not None:
        return ResolvedFlavor(
            id=candidate["id"],
            name=candidate["name"],
            scope="local",
            values=copy.deepcopy(candidate["values"]),
        )
    available = ", ".join(
        flavor["name"] for flavor in [*authored, *local_flavors] if flavor.get("name")
    )
    raise RuntimeError(
        f"Flavor '{requested}' is not available for cube '{cube.get('cube_id')}'. Available: {available}"
    )


def validate_flavor_values_against_surface(
    cube: CubeDocument,
    flavors: list[FlavorEntry],
    *,
    scope: FlavorScope,
) -> None:
    """Reject flavor values that do not map to this cube surface."""

    control_ids = set(_control_index(cube))
    for flavor in flavors:
        unknown = sorted(set(flavor["values"]) - control_ids)
        if unknown:
            unknown_text = ", ".join(unknown)
            raise RuntimeError(
                f"{scope.title()} flavor '{flavor['name']}' for cube "
                f"'{cube.get('cube_id')}' references unknown surface control(s): "
                f"{unknown_text}."
            )


def _control_index(cube: CubeDocument) -> dict[str, dict[str, str]]:
    """Index surface controls by control id."""

    controls = cube.get("surface", {}).get("controls", [])
    return {
        control["control_id"]: control
        for control in controls
        if isinstance(control, dict)
        and isinstance(control.get("control_id"), str)
        and isinstance(control.get("symbol"), str)
        and isinstance(control.get("input_name"), str)
    }


def _find_authored_by_id(cube: CubeDocument, flavor_id: str) -> FlavorEntry | None:
    """Return an authored flavor by exact id."""

    return _find_flavor(list(cube.get("flavors", {}).get("authored", [])), flavor_id)


def _find_flavor(flavors: list[FlavorEntry], requested: str) -> FlavorEntry | None:
    """Return a flavor matching by id or normalized display name."""

    requested_id = requested.strip()
    requested_name = normalize_flavor_name_key(requested)
    for flavor in flavors:
        if flavor["id"] == requested_id:
            return flavor
        if normalize_flavor_name_key(flavor["name"]) == requested_name:
            return flavor
    return None


def _raise_on_collisions(authored: list[FlavorEntry], local_flavors: list[FlavorEntry]) -> None:
    """Reject ambiguous authored/local flavor catalogs."""

    authored_ids = {flavor["id"] for flavor in authored}
    authored_names = {normalize_flavor_name_key(flavor["name"]) for flavor in authored}
    for flavor in local_flavors:
        if flavor["id"] in authored_ids:
            raise RuntimeError(
                f"Local flavor id '{flavor['id']}' collides with an authored flavor."
            )
        if normalize_flavor_name_key(flavor["name"]) in authored_names:
            raise RuntimeError(
                f"Local flavor name '{flavor['name']}' collides with an authored flavor."
            )
