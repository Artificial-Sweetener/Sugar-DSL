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
"""Compile-time expansion of UUID wrapper nodes into concrete subgraph nodes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Mapping

from ..catalog.subgraphs import (
    is_uuid_class_type,
    node_class_type,
    normalize_node_id,
)
from .subgraph_interfaces import (
    build_input_name_by_link_id,
    build_input_name_by_slot,
    coerce_mapping_list,
    collect_interface_ids,
    require_interface_entries,
)
from .subgraph_links import (
    apply_linked_inputs,
    compile_output_map,
    extract_literal_node_inputs,
    index_subgraph_links,
)
from .subgraph_rewrite import collect_required_output_slots, rewire_wrapper_consumers


def expand_cube_subgraph_wrappers(
    cube: dict[str, Any],
    *,
    cube_alias: str,
    cube_id: str,
    consumer_cubes: Iterable[dict[str, Any]] = (),
) -> None:
    """Inline UUID wrapper nodes using the cube's embedded subgraph definitions.

    Args:
        cube: Renamed cube payload (alias-qualified node names).
        cube_alias: Alias currently used in the spawn plan.
        cube_id: Source cube id for diagnostics.
        consumer_cubes: Additional materialized cubes whose inputs may already
            reference this cube through recipe-level connections.

    Raises:
        RuntimeError: If a wrapper cannot be expanded or unresolved wrappers remain.
    """

    nodes = cube.get("nodes")
    if not isinstance(nodes, dict):
        return

    consumer_cube_list = list(consumer_cubes)
    subgraph_index = _index_subgraphs(cube)
    guard = 0
    while True:
        wrapper_key, wrapper_node = _find_uuid_wrapper(nodes)
        if wrapper_key is None or wrapper_node is None:
            break
        guard += 1
        if guard > max(1, len(nodes) * 4):
            raise RuntimeError(
                f"Subgraph expansion exceeded safety limit for cube '{cube_alias}' ({cube_id})."
            )

        wrapper_type = str(wrapper_node.get("class_type"))
        definition = subgraph_index.get(wrapper_type)
        if definition is None:
            raise RuntimeError(
                f"Cube '{cube_alias}' ({cube_id}) is missing subgraph definition for wrapper '{wrapper_key}' ({wrapper_type})."
            )

        expanded_nodes, output_map = _compile_subgraph_wrapper(
            cube=cube,
            wrapper_key=wrapper_key,
            wrapper_node=wrapper_node,
            definition=definition,
        )
        required_slots = collect_required_output_slots(cube, wrapper_key)
        for consumer_cube in consumer_cube_list:
            required_slots.update(collect_required_output_slots(consumer_cube, wrapper_key))
        missing_slots = sorted(slot for slot in required_slots if slot not in output_map)
        if missing_slots:
            slot_text = ", ".join(str(slot) for slot in missing_slots)
            raise RuntimeError(
                f"Subgraph wrapper '{wrapper_key}' in cube '{cube_alias}' ({cube_id}) is missing output mapping for slot(s): {slot_text}."
            )

        for new_key, new_node in expanded_nodes.items():
            nodes[new_key] = new_node
        rewire_wrapper_consumers(cube, wrapper_key, output_map)
        for consumer_cube in consumer_cube_list:
            rewire_wrapper_consumers(consumer_cube, wrapper_key, output_map)
        del nodes[wrapper_key]

    remaining = [
        key
        for key, node in nodes.items()
        if isinstance(node, Mapping) and is_uuid_class_type(node.get("class_type"))
    ]
    if remaining:
        remaining_text = ", ".join(sorted(remaining))
        raise RuntimeError(
            f"Unresolved UUID wrapper nodes remain in cube '{cube_alias}' ({cube_id}): {remaining_text}."
        )


def _index_subgraphs(cube: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index embedded subgraph definitions by normalized id."""

    subgraphs = cube.get("subgraphs")
    if not isinstance(subgraphs, list):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for entry in subgraphs:
        if not isinstance(entry, Mapping):
            continue
        sub_id = entry.get("id")
        if isinstance(sub_id, str) and sub_id.strip():
            index[sub_id.strip()] = entry
    return index


def _find_uuid_wrapper(
    nodes: Mapping[str, Any],
) -> tuple[str | None, Mapping[str, Any] | None]:
    """Return the first UUID wrapper node in deterministic key order."""

    for node_key in sorted(nodes.keys()):
        node = nodes.get(node_key)
        if not isinstance(node, Mapping):
            continue
        class_type = node.get("class_type")
        if is_uuid_class_type(class_type):
            return node_key, node
    return None, None


def _compile_subgraph_wrapper(
    *,
    cube: Mapping[str, Any],
    wrapper_key: str,
    wrapper_node: Mapping[str, Any],
    definition: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[int, list[Any]]]:
    """Compile a single wrapper into concrete nodes and output mappings."""

    existing_names = set((cube.get("nodes") or {}).keys())
    wrapper_inputs = wrapper_node.get("inputs")
    if not isinstance(wrapper_inputs, Mapping):
        wrapper_inputs = {}
    definitions = cube.get("definitions")
    if not isinstance(definitions, Mapping):
        definitions = {}

    subgraph_id = str(definition.get("id") or wrapper_node.get("class_type") or "")
    input_entries = require_interface_entries(
        definition=definition,
        field_name="inputs",
        wrapper_key=wrapper_key,
    )
    output_entries = require_interface_entries(
        definition=definition,
        field_name="outputs",
        wrapper_key=wrapper_key,
    )
    input_name_by_slot = build_input_name_by_slot(
        input_entries=input_entries,
        wrapper_key=wrapper_key,
        subgraph_id=subgraph_id,
    )
    input_name_by_link_id = build_input_name_by_link_id(
        input_entries=input_entries,
        wrapper_key=wrapper_key,
        subgraph_id=subgraph_id,
    )

    links = index_subgraph_links(definition.get("links"))
    input_interface_ids = collect_interface_ids(definition.get("inputNode"), default="-10")
    output_interface_ids = collect_interface_ids(definition.get("outputNode"), default="-20")
    interface_ids = input_interface_ids | output_interface_ids
    raw_nodes = coerce_mapping_list(definition.get("nodes"))
    id_to_symbol: dict[str, str] = {}
    ordered_ids: list[str] = []
    for raw_node in raw_nodes:
        node_id = normalize_node_id(raw_node.get("id"))
        if not node_id or node_id in interface_ids:
            continue
        class_type = node_class_type(raw_node)
        if not class_type:
            continue
        symbol = _make_internal_symbol(
            wrapper_key=wrapper_key,
            raw_node=raw_node,
            node_id=node_id,
            used_names=existing_names | set(id_to_symbol.values()),
        )
        id_to_symbol[node_id] = symbol
        ordered_ids.append(node_id)

    if not id_to_symbol:
        raise RuntimeError(
            f"Subgraph '{definition.get('id')}' for wrapper '{wrapper_key}' does not include executable nodes."
        )

    raw_node_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_node in raw_nodes:
        normalized_id = normalize_node_id(raw_node.get("id"))
        if normalized_id is not None:
            raw_node_by_id[normalized_id] = raw_node

    expanded_nodes: dict[str, dict[str, Any]] = {}
    for node_id in ordered_ids:
        resolved_raw_node = raw_node_by_id.get(node_id)
        if not isinstance(resolved_raw_node, Mapping):
            continue
        class_type = node_class_type(resolved_raw_node)
        if not class_type:
            continue
        symbol = id_to_symbol[node_id]
        node_inputs = extract_literal_node_inputs(
            raw_node=resolved_raw_node, class_type=class_type, definitions=definitions
        )
        apply_linked_inputs(
            node_inputs=node_inputs,
            raw_node=resolved_raw_node,
            links=links,
            id_to_symbol=id_to_symbol,
            input_interface_ids=input_interface_ids,
            input_name_by_slot=input_name_by_slot,
            input_name_by_link_id=input_name_by_link_id,
            wrapper_inputs=wrapper_inputs,
            wrapper_key=wrapper_key,
            subgraph_id=subgraph_id,
        )

        node_payload: dict[str, Any] = {
            "class_type": class_type,
            "inputs": node_inputs,
        }
        title = resolved_raw_node.get("title")
        if isinstance(title, str) and title.strip():
            node_payload["_meta"] = {"title": f"{wrapper_key}.{title.strip()}"}
        expanded_nodes[symbol] = node_payload

    output_map = compile_output_map(
        output_entries=output_entries,
        links=links,
        id_to_symbol=id_to_symbol,
        input_interface_ids=input_interface_ids,
        input_name_by_slot=input_name_by_slot,
        input_name_by_link_id=input_name_by_link_id,
        wrapper_inputs=wrapper_inputs,
        wrapper_key=wrapper_key,
        subgraph_id=subgraph_id,
    )
    return expanded_nodes, output_map


def _make_internal_symbol(
    *,
    wrapper_key: str,
    raw_node: Mapping[str, Any],
    node_id: str,
    used_names: set[str],
) -> str:
    """Create a deterministic collision-free symbol for an expanded node."""

    title = raw_node.get("title")
    if not isinstance(title, str) or not title.strip():
        title = node_class_type(raw_node) or "node"
    base = re.sub(r"[^0-9a-zA-Z_]+", "_", title.strip()).strip("_").lower() or "node"
    node_suffix = re.sub(r"[^0-9a-zA-Z_]+", "_", str(node_id)).strip("_").lower() or "id"
    candidate = f"{wrapper_key}.__sg_{base}_{node_suffix}"
    if candidate not in used_names:
        return candidate
    idx = 2
    while True:
        next_candidate = f"{candidate}_{idx}"
        if next_candidate not in used_names:
            return next_candidate
        idx += 1
