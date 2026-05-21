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
"""Link-shape predicates for compiler graph values."""

from __future__ import annotations

from typing import Any

BINDING_SENTINEL = "@binding"


def is_comfy_node_link(value: Any) -> bool:
    """Return whether a value is a serialized ComfyUI node link."""

    if not isinstance(value, list) or len(value) != 2:
        return False
    node_id, slot = value
    return isinstance(node_id, str) and type(slot) is int


def is_binding_link(value: Any) -> bool:
    """Return whether a value is a serialized SugarCube input binding link."""

    if not isinstance(value, list) or len(value) != 2:
        return False
    source, binding_name = value
    return source == BINDING_SENTINEL and isinstance(binding_name, str) and bool(binding_name)
