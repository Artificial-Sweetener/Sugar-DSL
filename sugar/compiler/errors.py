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
"""Typed compiler errors for actionable Sugar-DSL failures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SugarCompilerError(RuntimeError):
    """Expose stable compiler failure metadata while preserving RuntimeError API."""

    message: str
    code: str = "sugar-compile-failed"
    cube_alias: str | None = None
    cube_id: str | None = None
    node_key: str | None = None
    node_class_type: str | None = None
    input_name: str | None = None

    def __post_init__(self) -> None:
        """Initialize the RuntimeError message payload."""

        RuntimeError.__init__(self, self.message)


__all__ = ["SugarCompilerError"]
