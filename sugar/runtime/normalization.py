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
"""Runtime workflow normalization utilities."""

from __future__ import annotations

from typing import Any

Workflow = dict[str, Any]

INT_FIELDS = {"steps", "width", "height", "seed", "batch_size", "feather"}


def sanitize_inputs(workflow: Workflow) -> Workflow:
    """Coerce known integer-only ComfyUI inputs from whole floats to integers."""

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if key in INT_FIELDS and isinstance(value, float) and value.is_integer():
                inputs[key] = int(value)
    return workflow
