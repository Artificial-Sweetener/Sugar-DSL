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
"""Subgraph link and node-input mapping helpers for wrapper expansion."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from ..catalog.subgraphs import (
    coerce_int,
    definition_input_order,
    definition_input_has_serialized_control_widget,
    is_comfy_control_widget_value,
    normalize_link,
)
from .subgraph_interfaces import iter_link_ids


def index_subgraph_links(value: Any) -> dict[int, Mapping[str, Any]]:
    """Index serialized subgraph links by link id."""

    if not isinstance(value, list):
        return {}
    indexed: dict[int, Mapping[str, Any]] = {}
    for raw in value:
        link = normalize_link(raw)
        if link is None:
            continue
        indexed[link["id"]] = link
    return indexed


def extract_literal_node_inputs(
    *,
    raw_node: Mapping[str, Any],
    class_type: str,
    definitions: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract literal non-link node inputs from a serialized subgraph node."""

    literals: dict[str, Any] = {}
    raw_inputs = raw_node.get("inputs")
    if isinstance(raw_inputs, Mapping):
        for key, value in raw_inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)):
                continue
            literals[str(key)] = copy.deepcopy(value)

    widget_values = raw_node.get("widgets_values")
    if isinstance(widget_values, Mapping):
        for key, value in widget_values.items():
            key_name = str(key)
            if key_name not in literals:
                literals[key_name] = copy.deepcopy(value)
    elif isinstance(widget_values, list):
        ordered_inputs = definition_input_order(definitions, class_type)
        value_index = 0
        for input_name in ordered_inputs:
            if value_index >= len(widget_values):
                break
            if input_name not in literals:
                literals[input_name] = copy.deepcopy(widget_values[value_index])
            value_index += 1
            if (
                definition_input_has_serialized_control_widget(definitions, class_type, input_name)
                and value_index < len(widget_values)
                and is_comfy_control_widget_value(widget_values[value_index])
            ):
                value_index += 1

    return literals


def apply_linked_inputs(
    *,
    node_inputs: dict[str, Any],
    raw_node: Mapping[str, Any],
    links: Mapping[int, Mapping[str, Any]],
    id_to_symbol: Mapping[str, str],
    input_interface_ids: set[str],
    input_name_by_slot: Mapping[int, str],
    input_name_by_link_id: Mapping[int, str],
    wrapper_inputs: Mapping[str, Any],
    wrapper_key: str,
    subgraph_id: str,
) -> None:
    """Map serialized subgraph input links onto expanded node inputs."""

    raw_inputs = raw_node.get("inputs")
    if isinstance(raw_inputs, list):
        for input_entry in raw_inputs:
            if not isinstance(input_entry, Mapping):
                continue
            input_name = input_entry.get("name")
            if not isinstance(input_name, str) or not input_name.strip():
                continue
            link_id = coerce_int(input_entry.get("link"))
            if link_id is None:
                continue
            link = links.get(link_id)
            if not link:
                continue
            interface_input_name = input_name_by_link_id.get(link_id) or input_name_by_slot.get(
                int(link["origin_slot"])
            )
            if (
                str(link["origin_id"]) in input_interface_ids
                and interface_input_name not in wrapper_inputs
                and input_name in node_inputs
            ):
                continue
            mapped = map_link_source(
                link_id=link_id,
                source_node_id=str(link["origin_id"]),
                source_slot=int(link["origin_slot"]),
                id_to_symbol=id_to_symbol,
                input_interface_ids=input_interface_ids,
                input_name_by_slot=input_name_by_slot,
                input_name_by_link_id=input_name_by_link_id,
                wrapper_inputs=wrapper_inputs,
                wrapper_key=wrapper_key,
                subgraph_id=subgraph_id,
            )
            node_inputs[input_name] = mapped
        return

    if isinstance(raw_inputs, Mapping):
        for input_name, raw_value in raw_inputs.items():
            mapped = remap_prompt_style_value(
                value=raw_value,
                id_to_symbol=id_to_symbol,
                input_interface_ids=input_interface_ids,
                input_name_by_slot=input_name_by_slot,
                wrapper_inputs=wrapper_inputs,
                wrapper_key=wrapper_key,
                subgraph_id=subgraph_id,
            )
            node_inputs[str(input_name)] = mapped


def map_link_source(
    *,
    link_id: int,
    source_node_id: str,
    source_slot: int,
    id_to_symbol: Mapping[str, str],
    input_interface_ids: set[str],
    input_name_by_slot: Mapping[int, str],
    input_name_by_link_id: Mapping[int, str],
    wrapper_inputs: Mapping[str, Any],
    wrapper_key: str,
    subgraph_id: str,
) -> Any:
    """Resolve one subgraph link source to an expanded-node input value."""

    if source_node_id in id_to_symbol:
        return [id_to_symbol[source_node_id], source_slot]
    if source_node_id in input_interface_ids:
        input_name = input_name_by_link_id.get(link_id) or input_name_by_slot.get(source_slot)
        if not input_name:
            raise RuntimeError(
                f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' cannot map input link {link_id} to a declared wrapper input."
            )
        if input_name in wrapper_inputs:
            return copy.deepcopy(wrapper_inputs[input_name])
        return None
    return [source_node_id, source_slot]


def remap_prompt_style_value(
    *,
    value: Any,
    id_to_symbol: Mapping[str, str],
    input_interface_ids: set[str],
    input_name_by_slot: Mapping[int, str],
    wrapper_inputs: Mapping[str, Any],
    wrapper_key: str,
    subgraph_id: str,
) -> Any:
    """Remap prompt-style nested link values inside serialized subgraph nodes."""

    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], (str, int)):
            source = str(value[0])
            slot = coerce_int(value[1], default=0)
            if slot is None:
                raise RuntimeError(
                    f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' has invalid input slot."
                )
            if source in id_to_symbol:
                return [id_to_symbol[source], slot]
            if source in input_interface_ids:
                input_name = input_name_by_slot.get(slot)
                if not input_name:
                    raise RuntimeError(
                        f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' cannot map input slot {slot} to a declared wrapper input."
                    )
                if input_name in wrapper_inputs:
                    return copy.deepcopy(wrapper_inputs[input_name])
                return None
            return [source, slot]
        return [
            remap_prompt_style_value(
                value=item,
                id_to_symbol=id_to_symbol,
                input_interface_ids=input_interface_ids,
                input_name_by_slot=input_name_by_slot,
                wrapper_inputs=wrapper_inputs,
                wrapper_key=wrapper_key,
                subgraph_id=subgraph_id,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: remap_prompt_style_value(
                value=item,
                id_to_symbol=id_to_symbol,
                input_interface_ids=input_interface_ids,
                input_name_by_slot=input_name_by_slot,
                wrapper_inputs=wrapper_inputs,
                wrapper_key=wrapper_key,
                subgraph_id=subgraph_id,
            )
            for key, item in value.items()
        }
    return copy.deepcopy(value)


def compile_output_map(
    *,
    output_entries: Sequence[Mapping[str, Any]],
    links: Mapping[int, Mapping[str, Any]],
    id_to_symbol: Mapping[str, str],
    input_interface_ids: set[str],
    input_name_by_slot: Mapping[int, str],
    input_name_by_link_id: Mapping[int, str],
    wrapper_inputs: Mapping[str, Any],
    wrapper_key: str,
    subgraph_id: str,
) -> dict[int, list[Any]]:
    """Build wrapper output-slot mappings from subgraph output links."""

    output_map: dict[int, list[Any]] = {}
    for output_index, output_entry in enumerate(output_entries):
        if "linkIds" not in output_entry:
            raise RuntimeError(
                f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' output slot {output_index} is missing 'linkIds'."
            )
        link_ids = list(iter_link_ids(output_entry.get("linkIds")))
        if not link_ids:
            continue
        for link_id in link_ids:
            link = links.get(link_id)
            if not link:
                raise RuntimeError(
                    f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' references missing link id {link_id} in output slot {output_index}."
                )
            source_node_id = str(link["origin_id"])
            source_slot = int(link["origin_slot"])
            if source_node_id in id_to_symbol:
                output_map[output_index] = [id_to_symbol[source_node_id], source_slot]
                break
            if source_node_id in input_interface_ids:
                input_name = input_name_by_link_id.get(link_id) or input_name_by_slot.get(
                    source_slot
                )
                if not input_name:
                    raise RuntimeError(
                        f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' cannot map output slot {output_index} link {link_id} to a declared wrapper input."
                    )
                source_value = (
                    copy.deepcopy(wrapper_inputs.get(input_name))
                    if input_name and input_name in wrapper_inputs
                    else None
                )
                if (
                    isinstance(source_value, list)
                    and len(source_value) == 2
                    and isinstance(source_value[0], str)
                ):
                    output_map[output_index] = [source_value[0], int(source_value[1])]
                    break
            raise RuntimeError(
                f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' output slot {output_index} resolves to unsupported source node '{source_node_id}'."
            )
    return output_map
