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
"""Compiler-side live ComfyUI node definition contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LiveNodeInputDefinition:
    """Describe one current ComfyUI input visible to the compiler."""

    name: str
    value_type: str
    required: bool
    default: object | None
    has_default: bool
    choices: tuple[object, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveNodeDefinition:
    """Describe the current ComfyUI definition for one node class."""

    class_type: str
    inputs: Mapping[str, LiveNodeInputDefinition]


class LiveNodeDefinitionProvider(Protocol):
    """Return current ComfyUI node definitions by class type."""

    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        """Return the live definition for ``class_type`` when the host knows it."""


__all__ = [
    "LiveNodeDefinition",
    "LiveNodeDefinitionProvider",
    "LiveNodeInputDefinition",
]
