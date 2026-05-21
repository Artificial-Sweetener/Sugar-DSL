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
"""Typed compiler graph primitives used between analysis and code generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from ..catalog.models import CubeDocument

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
FlavorScope: TypeAlias = Literal["authored", "local"]
NodeMap: TypeAlias = dict[str, dict[str, Any]]
CubeGraph: TypeAlias = dict[str, Any]
CubeGraphByAlias: TypeAlias = dict[str, CubeGraph]


@dataclass(frozen=True)
class NodeRef:
    """Reference one materialized node inside an aliased cube instance."""

    alias: str
    node_key: str


@dataclass(frozen=True)
class BindingRef:
    """Reference a cube input or output binding from compiler operations."""

    alias: str
    binding_name: str
    input_key: str | None = None


@dataclass(frozen=True)
class ResolvedCubeInstance:
    """Materialized cube instance with alias and flavor metadata resolved."""

    cube_id: str
    alias: str
    version_pin: str | None
    requested_version: str | None
    resolved_version: str
    flavor_name: str | None
    flavor_id: str
    flavor_scope: FlavorScope
    flavor_values: dict[str, Any]
    raw_cube: CubeDocument
    cube: CubeGraph
