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
"""Graph rewrite helpers for expanded subgraph wrapper outputs."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ..catalog.subgraphs import coerce_int


def collect_required_output_slots(cube: Mapping[str, Any], wrapper_key: str) -> set[int]:
    """Return wrapper output slots consumed by nodes or cube output bindings."""

    required: set[int] = set()
    nodes = cube.get("nodes")
    if isinstance(nodes, Mapping):
        for node in nodes.values():
            if not isinstance(node, Mapping):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, Mapping):
                continue
            for value in inputs.values():
                if (
                    isinstance(value, list)
                    and len(value) >= 2
                    and isinstance(value[0], str)
                    and value[0] == wrapper_key
                ):
                    slot = coerce_int(value[1], default=0)
                    if slot is not None:
                        required.add(slot)

    outputs = cube.get("outputs")
    if isinstance(outputs, Mapping):
        for value in outputs.values():
            if isinstance(value, str) and value == wrapper_key:
                required.add(0)
            elif (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] == wrapper_key
            ):
                slot = coerce_int(value[1], default=0)
                if slot is not None:
                    required.add(slot)
    return required


def rewire_wrapper_consumers(
    cube: dict[str, Any], wrapper_key: str, output_map: Mapping[int, list[Any]]
) -> None:
    """Replace wrapper output references with expanded subgraph output links."""

    nodes = cube.get("nodes")
    if isinstance(nodes, Mapping):
        for node in nodes.values():
            if not isinstance(node, Mapping):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            for input_key, value in list(inputs.items()):
                if (
                    isinstance(value, list)
                    and len(value) >= 2
                    and isinstance(value[0], str)
                    and value[0] == wrapper_key
                ):
                    slot = coerce_int(value[1], default=0)
                    if slot is None:
                        raise RuntimeError(
                            f"Wrapper consumer for '{wrapper_key}' has invalid output slot."
                        )
                    inputs[input_key] = copy.deepcopy(output_map[slot])

    outputs = cube.get("outputs")
    if isinstance(outputs, dict):
        for binding, value in list(outputs.items()):
            if isinstance(value, str) and value == wrapper_key:
                mapped = output_map[0]
                outputs[binding] = mapped[0]
            elif (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] == wrapper_key
            ):
                slot = coerce_int(value[1], default=0)
                if slot is None:
                    raise RuntimeError(
                        f"Wrapper output binding for '{wrapper_key}' has invalid output slot."
                    )
                mapped = output_map[slot]
                outputs[binding] = [mapped[0], mapped[1]] if int(mapped[1]) != 0 else mapped[0]
