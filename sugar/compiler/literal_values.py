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
"""Preserve authored literal-list identity through compiler graph lowering."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

_LITERAL_LIST_KEY = "__sugar_literal_list__"
_COMFY_LITERAL_VALUE_KEY = "__value__"


def authored_literal_list(values: Sequence[object]) -> dict[str, object]:
    """Return a JSON-safe compiler marker for one authored list literal."""

    return {_LITERAL_LIST_KEY: [_plain_literal_value(value) for value in values]}


def is_authored_literal_list(value: object) -> bool:
    """Return whether a value carries Sugar's list-literal provenance marker."""

    return (
        isinstance(value, Mapping)
        and set(value) == {_LITERAL_LIST_KEY}
        and isinstance(value.get(_LITERAL_LIST_KEY), list)
    )


def plain_literal_value(value: object) -> object:
    """Return a detached presentation value with Sugar markers removed."""

    return copy.deepcopy(_plain_literal_value(value))


def comfy_literal_list_value(value: object) -> dict[str, object]:
    """Encode one marked list using Comfy's executable prompt contract."""

    if not is_authored_literal_list(value):
        raise TypeError("Expected an authored Sugar list literal.")
    return {_COMFY_LITERAL_VALUE_KEY: plain_literal_value(value)}


def wrap_unlinked_comfy_list(value: list[object]) -> dict[str, object]:
    """Wrap an unmarked literal list using Comfy's executable prompt contract."""

    return {_COMFY_LITERAL_VALUE_KEY: copy.deepcopy(value)}


def _plain_literal_value(value: object) -> object:
    """Recursively strip internal list markers without copying the result."""

    if is_authored_literal_list(value):
        assert isinstance(value, Mapping)
        items = value[_LITERAL_LIST_KEY]
        assert isinstance(items, list)
        return [_plain_literal_value(item) for item in items]
    if isinstance(value, list):
        return [_plain_literal_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain_literal_value(item) for key, item in value.items()}
    return value


__all__ = [
    "authored_literal_list",
    "comfy_literal_list_value",
    "is_authored_literal_list",
    "plain_literal_value",
    "wrap_unlinked_comfy_list",
]
