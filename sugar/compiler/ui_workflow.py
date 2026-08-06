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
"""Emit placed ComfyUI UI workflow graphs from materialized Sugar recipes."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..catalog.subgraphs import (
    definition_field_has_serialized_control_widget,
    definition_input_has_serialized_control_widget,
    definition_input_order,
    is_comfy_control_widget_value,
    node_class_type,
    normalize_link,
    normalize_node_id,
)
from .graph import CubeGraph
from .ir import ConnectionEntry
from .links import is_comfy_node_link
from .literal_values import plain_literal_value
from .recipe import MaterializedCubeInstance, MaterializedRecipe
from .resolver import require_mapping
from .subgraph_interfaces import (
    build_input_name_by_link_id,
    build_input_name_by_slot,
    collect_interface_ids,
    require_interface_entries,
)

_CUBE_INPUT_CLASS = "SugarCubes.CubeInput"
_CUBE_OUTPUT_CLASS = "SugarCubes.CubeOutput"
_EXTERNAL_INPUT = "EXTERNAL_INPUT"
_DEFAULT_NODE_SIZE = [180.0, 60.0]
_DEFAULT_MARKER_SIZE = [270.0, 90.0]
_DEFAULT_GROUP_WIDTH = 900.0
_DEFAULT_GROUP_HEIGHT = 600.0
_INITIAL_GROUP_X = 150.0
_INITIAL_GROUP_Y = 320.0
_GROUP_GAP_X = 10.0
_GROUP_GAP_Y = 120.0
_VALUE_WIDGET_TYPES = {"BOOLEAN", "COMBO", "FLOAT", "INT", "LIST", "STRING"}


@dataclass(frozen=True)
class _PlacedCube:
    """Track generated workflow ids for one placed Sugar cube instance."""

    instance: MaterializedCubeInstance
    origin: tuple[float, float]
    node_ids_by_key: dict[str, int] = field(default_factory=dict)
    input_marker_ids_by_binding: dict[str, int] = field(default_factory=dict)
    output_marker_ids_by_binding: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _SubgraphInputTarget:
    """Describe one body node input fed by a subgraph interface input."""

    node_id: str
    input_name: str


@dataclass
class _WorkflowBuildContext:
    """Own mutable state while emitting a Comfy UI workflow."""

    next_node_id: int = 1
    next_link_id: int = 1
    nodes: list[dict[str, Any]] = field(default_factory=list)
    links: list[list[Any]] = field(default_factory=list)
    subgraph_definitions_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_links_by_node_slot: dict[tuple[int, int], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def allocate_node_id(self) -> int:
        """Return the next deterministic LiteGraph node id."""

        node_id = self.next_node_id
        self.next_node_id += 1
        return node_id

    def add_link(
        self,
        *,
        origin_id: int,
        origin_slot: int,
        target_id: int,
        target_slot: int,
        link_type: str,
    ) -> int:
        """Append a LiteGraph link row and return its id."""

        link_id = self.next_link_id
        self.next_link_id += 1
        self.links.append([link_id, origin_id, origin_slot, target_id, target_slot, link_type])
        self.output_links_by_node_slot[(origin_id, origin_slot)].append(link_id)
        return link_id


def recipe_to_ui_workflow(recipe: MaterializedRecipe) -> dict[str, Any]:
    """Build a SugarCubes-shaped Comfy UI workflow from the authored graph view."""

    context = _WorkflowBuildContext()
    origins = _compute_cube_origins(recipe)
    placed_cubes: dict[str, _PlacedCube] = {}

    for alias in recipe.order:
        instance = recipe.cubes_by_alias[alias]
        placed = _PlacedCube(instance=instance, origin=origins[alias])
        _add_cube_nodes(context, placed)
        placed_cubes[alias] = placed

    for connection in recipe.connections:
        _add_recipe_connection(context, placed_cubes, connection)

    _apply_output_link_ids(context.nodes, context.output_links_by_node_slot)
    groups = [_build_group(placed, context.nodes) for placed in placed_cubes.values()]

    return {
        "id": _workflow_id(recipe),
        "revision": 0,
        "last_node_id": context.next_node_id - 1,
        "last_link_id": context.next_link_id - 1,
        "nodes": context.nodes,
        "links": context.links,
        "groups": groups,
        "config": {},
        "extra": {
            "workflowRendererVersion": "LG",
            "sugar": {"warnings": list(recipe.warnings)},
        },
        "version": 0.4,
        "definitions": _merge_subgraph_definitions(recipe, context),
    }


def _add_cube_nodes(context: _WorkflowBuildContext, placed: _PlacedCube) -> None:
    """Append marker and authored implementation nodes for one cube instance."""

    cube = placed.instance.ui_graph
    binding_targets = _input_target_bindings(cube, placed.instance.alias)

    for binding_name, _input_spec in _ordered_bindings(cube, "inputs"):
        marker_id = context.allocate_node_id()
        placed.input_marker_ids_by_binding[binding_name] = marker_id
        context.nodes.append(
            _build_marker_node(
                node_id=marker_id,
                class_type=_CUBE_INPUT_CLASS,
                binding_name=binding_name,
                placed=placed,
                order=len(context.nodes),
                marker_type=_input_binding_type(cube, binding_name),
            )
        )

    nodes = require_mapping(cube, "nodes", placed.instance.alias)
    for node_key, node_payload in nodes.items():
        if node_payload.get("class_type") == _CUBE_OUTPUT_CLASS:
            continue
        node_id = context.allocate_node_id()
        placed.node_ids_by_key[node_key] = node_id
        context.nodes.append(
            _build_internal_node(
                context=context,
                node_id=node_id,
                node_key=node_key,
                node_payload=node_payload,
                placed=placed,
                order=len(context.nodes),
            )
        )

    for binding_name, source_ref in _ordered_bindings(cube, "outputs"):
        marker_id = context.allocate_node_id()
        placed.output_marker_ids_by_binding[binding_name] = marker_id
        marker_type = _output_binding_type(cube, source_ref, placed.instance.alias)
        context.nodes.append(
            _build_marker_node(
                node_id=marker_id,
                class_type=_CUBE_OUTPUT_CLASS,
                binding_name=binding_name,
                placed=placed,
                order=len(context.nodes),
                marker_type=marker_type,
            )
        )
        _link_output_marker(
            context=context,
            placed=placed,
            binding_name=binding_name,
            source_ref=source_ref,
            marker_id=marker_id,
            marker_type=marker_type,
        )

    _add_internal_links(context, placed, binding_targets)


def _link_output_marker(
    *,
    context: _WorkflowBuildContext,
    placed: _PlacedCube,
    binding_name: str,
    source_ref: Any,
    marker_id: int,
    marker_type: str,
) -> None:
    """Connect a cube output marker to its authored internal source node."""

    source_node_key, source_slot = _normalize_source_ref(source_ref, placed.instance.alias)
    source_node_id = placed.node_ids_by_key.get(source_node_key)
    if source_node_id is None:
        raise RuntimeError(
            f"Unable to resolve UI output source for {placed.instance.alias}.{binding_name}."
        )
    target_node = _find_workflow_node(context.nodes, marker_id)
    link_id = context.add_link(
        origin_id=source_node_id,
        origin_slot=source_slot,
        target_id=marker_id,
        target_slot=0,
        link_type=marker_type,
    )
    _set_input_link(target_node, "value", link_id)


def _add_internal_links(
    context: _WorkflowBuildContext,
    placed: _PlacedCube,
    binding_targets: Mapping[tuple[str, str], str],
) -> None:
    """Create internal UI links while preserving marker boundary links."""

    nodes = require_mapping(placed.instance.ui_graph, "nodes", placed.instance.alias)
    for node_key, node_payload in nodes.items():
        if node_payload.get("class_type") == _CUBE_OUTPUT_CLASS:
            continue
        target_id = placed.node_ids_by_key[node_key]
        workflow_node = _find_workflow_node(context.nodes, target_id)
        for input_name, value in _node_inputs(node_payload).items():
            if not is_comfy_node_link(value):
                continue
            target_slot = _find_input_slot(workflow_node, input_name)
            target_type = _input_slot_type(workflow_node, target_slot)
            input_marker_binding = binding_targets.get((node_key, input_name))
            if input_marker_binding is not None:
                origin_id = placed.input_marker_ids_by_binding.get(input_marker_binding)
                if origin_id is None:
                    continue
                link_id = context.add_link(
                    origin_id=origin_id,
                    origin_slot=0,
                    target_id=target_id,
                    target_slot=target_slot,
                    link_type=target_type,
                )
                _set_input_link(workflow_node, input_name, link_id)
                continue
            source_node_key = str(value[0])
            origin_id = placed.node_ids_by_key.get(source_node_key)
            if origin_id is None:
                continue
            origin_slot = _coerce_slot(value[1])
            link_id = context.add_link(
                origin_id=origin_id,
                origin_slot=origin_slot,
                target_id=target_id,
                target_slot=target_slot,
                link_type=_output_slot_type(
                    _find_workflow_node(context.nodes, origin_id), origin_slot
                )
                or target_type,
            )
            _set_input_link(workflow_node, input_name, link_id)


def _add_recipe_connection(
    context: _WorkflowBuildContext,
    placed_cubes: Mapping[str, _PlacedCube],
    connection: ConnectionEntry,
) -> None:
    """Add the visible SugarCubes marker-to-marker edge for one recipe connection."""

    from_entry = connection.get("from", {})
    to_entry = connection.get("to", {})
    from_alias = from_entry.get("alias")
    output_binding = from_entry.get("output")
    to_alias = to_entry.get("alias")
    input_binding = to_entry.get("input")
    if not from_alias or not output_binding or not to_alias or not input_binding:
        raise RuntimeError("Spawn plan connection entry missing required fields.")

    from_cube = placed_cubes[from_alias]
    to_cube = placed_cubes[to_alias]
    origin_id = from_cube.output_marker_ids_by_binding.get(output_binding)
    target_id = to_cube.input_marker_ids_by_binding.get(input_binding)
    if origin_id is None or target_id is None:
        raise RuntimeError(
            f"Unable to resolve UI marker connection {from_alias}.{output_binding} "
            f"to {to_alias}.{input_binding}."
        )
    target_node = _find_workflow_node(context.nodes, target_id)
    link_type = _output_slot_type(_find_workflow_node(context.nodes, origin_id), 0)
    link_id = context.add_link(
        origin_id=origin_id,
        origin_slot=0,
        target_id=target_id,
        target_slot=0,
        link_type=link_type or _input_slot_type(target_node, 0),
    )
    _set_input_link(target_node, "value", link_id)


def _build_internal_node(
    *,
    context: _WorkflowBuildContext,
    node_id: int,
    node_key: str,
    node_payload: Mapping[str, Any],
    placed: _PlacedCube,
    order: int,
) -> dict[str, Any]:
    """Build one authored cube implementation node in LiteGraph workflow shape."""

    cube = placed.instance.ui_graph
    local_name = _local_node_name(placed.instance.alias, node_key)
    authored_class_type = str(node_payload.get("class_type") or "")
    emitted_class_type = _materialize_ui_subgraph_definition(
        context=context,
        placed=placed,
        node_key=node_key,
        node_payload=node_payload,
        class_type=authored_class_type,
    )
    layout = _layout_entry(cube, "nodes", local_name)
    properties = _node_properties(cube, authored_class_type, local_name, node_payload)
    if emitted_class_type != authored_class_type:
        properties["sugarcubes_original_subgraph_id"] = authored_class_type
    workflow_node: dict[str, Any] = {
        "id": node_id,
        "type": emitted_class_type,
        "pos": _shifted_vec2(layout.get("pos"), placed.origin)
        or _grid_position(placed.origin, len(placed.node_ids_by_key)),
        "size": _layout_size(layout, _DEFAULT_NODE_SIZE),
        "flags": _layout_flags(layout),
        "order": order,
        "mode": _node_mode(node_payload, layout),
        "inputs": _build_input_slots(cube, authored_class_type, node_payload),
        "outputs": _build_output_slots(cube, authored_class_type),
        "properties": properties,
        "widgets_values": _widget_values(cube, authored_class_type, node_payload),
    }
    title = layout.get("title")
    if isinstance(title, str) and title:
        workflow_node["title"] = title
    for style_key in ("color", "bgcolor"):
        style_value = layout.get(style_key)
        if isinstance(style_value, str):
            workflow_node[style_key] = style_value
    return workflow_node


def _materialize_ui_subgraph_definition(
    *,
    context: _WorkflowBuildContext,
    placed: _PlacedCube,
    node_key: str,
    node_payload: Mapping[str, Any],
    class_type: str,
) -> str:
    """Clone subgraph definitions per wrapper instance for accurate UI faces."""

    cube = placed.instance.ui_graph
    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is None:
        return class_type

    cloned_id = _ui_subgraph_instance_id(
        original_id=class_type,
        alias=placed.instance.alias,
        node_key=node_key,
    )
    if cloned_id not in context.subgraph_definitions_by_id:
        context.subgraph_definitions_by_id[cloned_id] = _clone_subgraph_for_ui_wrapper(
            cube=cube,
            subgraph=subgraph,
            wrapper_node=node_payload,
            cloned_id=cloned_id,
            original_id=class_type,
        )
    return cloned_id


def _ui_subgraph_instance_id(*, original_id: str, alias: str, node_key: str) -> str:
    """Return a deterministic Comfy-safe subgraph id for one wrapper instance."""

    seed = json.dumps(
        {
            "alias": alias,
            "node_key": node_key,
            "original_id": original_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sugar-dsl-ui-subgraph:{seed}"))


def _clone_subgraph_for_ui_wrapper(
    *,
    cube: CubeGraph,
    subgraph: Mapping[str, Any],
    wrapper_node: Mapping[str, Any],
    cloned_id: str,
    original_id: str,
) -> dict[str, Any]:
    """Return a subgraph clone whose body widgets reflect wrapper literals."""

    cloned = copy.deepcopy(dict(subgraph))
    cloned["id"] = cloned_id
    extra = cloned.get("extra")
    if not isinstance(extra, dict):
        extra = {}
        cloned["extra"] = extra
    sugar_extra = extra.get("sugar")
    if not isinstance(sugar_extra, dict):
        sugar_extra = {}
        extra["sugar"] = sugar_extra
    sugar_extra["original_subgraph_id"] = original_id
    _apply_wrapper_literals_to_subgraph_clone(
        cube=cube,
        cloned_subgraph=cloned,
        wrapper_node=wrapper_node,
    )
    return cloned


def _apply_wrapper_literals_to_subgraph_clone(
    *,
    cube: CubeGraph,
    cloned_subgraph: MutableMapping[str, Any],
    wrapper_node: Mapping[str, Any],
) -> None:
    """Apply authored wrapper literal inputs to cloned subgraph body widgets."""

    wrapper_literals = _wrapper_literal_inputs(wrapper_node, cloned_subgraph)
    if not wrapper_literals:
        return

    targets_by_input = _subgraph_input_links_by_wrapper_input(cloned_subgraph)
    nodes_by_id = _subgraph_nodes_by_id(cloned_subgraph)
    definitions = cube.get("definitions")
    if not isinstance(definitions, Mapping):
        definitions = {}

    for wrapper_input, value in wrapper_literals.items():
        for target in targets_by_input.get(wrapper_input, ()):
            body_node = nodes_by_id.get(target.node_id)
            if body_node is None:
                continue
            class_type = node_class_type(body_node)
            if class_type is None:
                continue
            _set_subgraph_node_literal_value(
                definitions=definitions,
                body_node=body_node,
                class_type=class_type,
                input_name=target.input_name,
                value=value,
            )


def _wrapper_literal_inputs(
    wrapper_node: Mapping[str, Any],
    subgraph: Mapping[str, Any],
) -> dict[str, Any]:
    """Return non-link wrapper values keyed by subgraph interface input name."""

    literals: dict[str, Any] = {}
    inputs = wrapper_node.get("inputs")
    if isinstance(inputs, Mapping):
        for input_name, value in inputs.items():
            if value is None or is_comfy_node_link(value):
                continue
            literals[str(input_name)] = plain_literal_value(value)

    explicit = wrapper_node.get("widgets_values")
    if isinstance(explicit, Mapping):
        for input_name, value in explicit.items():
            if value is not None and str(input_name) not in literals:
                literals[str(input_name)] = copy.deepcopy(value)
    elif isinstance(explicit, list):
        for index, input_entry in enumerate(_subgraph_input_entries(subgraph)):
            if index >= len(explicit):
                break
            input_name = input_entry.get("name")
            if isinstance(input_name, str) and input_name not in literals:
                literals[input_name] = copy.deepcopy(explicit[index])
    return literals


def _subgraph_input_links_by_wrapper_input(
    subgraph: Mapping[str, Any],
) -> dict[str, list[_SubgraphInputTarget]]:
    """Return body node targets reached from each wrapper interface input."""

    input_entries = require_interface_entries(
        definition=subgraph,
        field_name="inputs",
        wrapper_key=str(subgraph.get("id") or "<ui-subgraph>"),
    )
    input_name_by_slot = build_input_name_by_slot(
        input_entries=input_entries,
        wrapper_key=str(subgraph.get("id") or "<ui-subgraph>"),
        subgraph_id=str(subgraph.get("id") or ""),
    )
    input_name_by_link_id = build_input_name_by_link_id(
        input_entries=input_entries,
        wrapper_key=str(subgraph.get("id") or "<ui-subgraph>"),
        subgraph_id=str(subgraph.get("id") or ""),
    )
    input_interface_ids = collect_interface_ids(subgraph.get("inputNode"), default="-10")
    body_nodes_by_id = _subgraph_nodes_by_id(subgraph)

    targets: dict[str, list[_SubgraphInputTarget]] = {}
    raw_links = subgraph.get("links")
    if not isinstance(raw_links, list):
        return targets
    for raw_link in raw_links:
        link = normalize_link(raw_link)
        if link is None or link["origin_id"] not in input_interface_ids:
            continue
        wrapper_input_name = input_name_by_link_id.get(link["id"]) or input_name_by_slot.get(
            link["origin_slot"]
        )
        if wrapper_input_name is None:
            continue
        body_node = body_nodes_by_id.get(link["target_id"])
        if body_node is None:
            continue
        target_input_name = _subgraph_target_input_name(body_node, link)
        if target_input_name is None:
            continue
        targets.setdefault(wrapper_input_name, []).append(
            _SubgraphInputTarget(
                node_id=link["target_id"],
                input_name=target_input_name,
            )
        )
    return targets


def _subgraph_input_entries(subgraph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return mapping entries from a subgraph input interface array."""

    raw_inputs = subgraph.get("inputs")
    if not isinstance(raw_inputs, list):
        return []
    return [entry for entry in raw_inputs if isinstance(entry, Mapping)]


def _subgraph_nodes_by_id(subgraph: Mapping[str, Any]) -> dict[str, MutableMapping[str, Any]]:
    """Return mutable subgraph body nodes by normalized serialized node id."""

    raw_nodes = subgraph.get("nodes")
    if not isinstance(raw_nodes, list):
        return {}
    nodes_by_id: dict[str, MutableMapping[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, MutableMapping):
            continue
        node_id = normalize_node_id(node.get("id"))
        if node_id is not None:
            nodes_by_id[node_id] = node
    return nodes_by_id


def _subgraph_target_input_name(
    body_node: Mapping[str, Any],
    link: Mapping[str, Any],
) -> str | None:
    """Resolve a subgraph body input name targeted by one normalized link."""

    target_port = link.get("target_port")
    if isinstance(target_port, str) and target_port:
        return target_port

    raw_inputs = body_node.get("inputs")
    if isinstance(raw_inputs, list):
        for index, entry in enumerate(raw_inputs):
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            if _coerce_slot(entry.get("link")) == link.get("id"):
                return name
            if isinstance(target_port, int) and target_port == index:
                return name
    return None


def _set_subgraph_node_literal_value(
    *,
    definitions: Mapping[str, Any],
    body_node: MutableMapping[str, Any],
    class_type: str,
    input_name: str,
    value: Any,
) -> None:
    """Set a cloned subgraph node widget/input literal without disturbing links."""

    _set_subgraph_node_widget_value(
        definitions=definitions,
        body_node=body_node,
        class_type=class_type,
        input_name=input_name,
        value=value,
    )
    raw_inputs = body_node.get("inputs")
    if isinstance(raw_inputs, MutableMapping):
        current = raw_inputs.get(input_name)
        if not is_comfy_node_link(current):
            raw_inputs[input_name] = copy.deepcopy(value)


def _set_subgraph_node_widget_value(
    *,
    definitions: Mapping[str, Any],
    body_node: MutableMapping[str, Any],
    class_type: str,
    input_name: str,
    value: Any,
) -> None:
    """Set one serialized widget value on a cloned subgraph body node."""

    widgets = body_node.get("widgets_values")
    if isinstance(widgets, MutableMapping):
        widgets[input_name] = copy.deepcopy(value)
        return
    if not isinstance(widgets, list):
        return

    widget_index = _serialized_widget_index(
        definitions=definitions,
        class_type=class_type,
        input_name=input_name,
        widgets=widgets,
    )
    if widget_index is None:
        return
    if widget_index < len(widgets):
        widgets[widget_index] = copy.deepcopy(value)
    elif widget_index == len(widgets):
        widgets.append(copy.deepcopy(value))


def _serialized_widget_index(
    *,
    definitions: Mapping[str, Any],
    class_type: str,
    input_name: str,
    widgets: Sequence[Any],
) -> int | None:
    """Return the index where one input is serialized in ``widgets_values``."""

    value_index = 0
    for candidate in definition_input_order(definitions, class_type):
        if candidate == input_name:
            return value_index
        value_index += 1
        if (
            definition_input_has_serialized_control_widget(definitions, class_type, candidate)
            and value_index < len(widgets)
            and is_comfy_control_widget_value(widgets[value_index])
        ):
            value_index += 1
    return None


def _build_marker_node(
    *,
    node_id: int,
    class_type: str,
    binding_name: str,
    placed: _PlacedCube,
    order: int,
    marker_type: str,
) -> dict[str, Any]:
    """Build one SugarCubes marker node using the authored marker layout."""

    layout = _layout_entry(placed.instance.ui_graph, "markers", binding_name)
    style_payload = layout.get("style")
    style: Mapping[str, Any] = style_payload if isinstance(style_payload, dict) else {}
    marker_node = {
        "id": node_id,
        "type": class_type,
        "pos": _shifted_vec2(layout.get("pos"), placed.origin)
        or _grid_position(placed.origin, order),
        "size": _layout_size(layout, _DEFAULT_MARKER_SIZE),
        "flags": _layout_flags(layout),
        "order": order,
        "mode": int(_number_or_none(layout.get("mode")) or 0),
        "inputs": [
            {
                "label": _slot_label(marker_type),
                "name": "value",
                "type": marker_type,
                "link": None,
            }
        ],
        "outputs": [
            {
                "label": _slot_label(marker_type),
                "name": "value",
                "type": marker_type,
                "links": [],
            }
        ],
        "title": str(layout.get("title") or _marker_title(binding_name, class_type)),
        "properties": {
            "Node name for S&R": class_type,
            "sugarcubes_symbol": binding_name,
            "sugarcubes_cube_version": str(placed.instance.ui_graph.get("version") or ""),
        },
        "widgets_values": _marker_widget_values(
            class_type=class_type,
            binding_name=binding_name,
            placed=placed,
        ),
        "color": str(style.get("color") or "#2a363b"),
        "bgcolor": str(style.get("bgcolor") or "#3f5159"),
    }
    return marker_node


def _build_input_slots(
    cube: CubeGraph, class_type: str, node_payload: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return LiteGraph input slots for linked authored node inputs."""

    linked_inputs = {
        key: value for key, value in _node_inputs(node_payload).items() if is_comfy_node_link(value)
    }
    ordered_names = _ordered_input_names(cube, class_type, linked_inputs)
    slots: list[dict[str, Any]] = []
    for input_name in ordered_names:
        if input_name not in linked_inputs:
            continue
        input_type = _definition_input_type(cube, class_type, input_name)
        slot: dict[str, Any] = {"name": input_name, "type": input_type, "link": None}
        if _definition_input_is_widget(cube, class_type, input_name):
            slot["widget"] = {"name": input_name}
        slots.append(slot)
    return slots


def _build_output_slots(cube: CubeGraph, class_type: str) -> list[dict[str, Any]]:
    """Return LiteGraph output slots from node definitions or subgraph interfaces."""

    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is not None:
        outputs = subgraph.get("outputs")
        if isinstance(outputs, list) and outputs:
            return [
                {
                    "name": str(output.get("name") or f"output_{index}"),
                    "type": str(output.get("type") or "*"),
                    "links": [],
                }
                for index, output in enumerate(outputs)
                if isinstance(output, dict)
            ]

    definition = _definition_for_class(cube, class_type)
    output_types = _string_list(definition.get("output"))
    output_names = _string_list(definition.get("output_name"))
    if not output_types and not output_names:
        return [{"name": "value", "type": "*", "links": []}]
    count = max(len(output_types), len(output_names))
    return [
        {
            "name": output_names[index] if index < len(output_names) else f"output_{index}",
            "type": output_types[index] if index < len(output_types) else "*",
            "links": [],
        }
        for index in range(count)
    ]


def _node_properties(
    cube: CubeGraph,
    class_type: str,
    local_name: str,
    node_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return Comfy properties while preserving authored SugarCubes symbol identity."""

    properties = dict(_mapping_value(node_payload.get("properties")))
    definition = _definition_for_class(cube, class_type)
    if "Node name for S&R" not in properties and not _subgraph_by_id(cube, class_type):
        properties["Node name for S&R"] = class_type
    if "cnr_id" not in properties:
        cnr_id = _cnr_id(definition)
        if cnr_id is not None:
            properties["cnr_id"] = cnr_id
    properties["sugarcubes_symbol"] = local_name
    return properties


def _widget_values(cube: CubeGraph, class_type: str, node_payload: Mapping[str, Any]) -> list[Any]:
    """Return Comfy widget values from authored literal inputs in definition order."""

    explicit = node_payload.get("widgets_values")
    if isinstance(explicit, list):
        return copy.deepcopy(explicit)

    inputs = _node_inputs(node_payload)
    values: list[Any] = []
    definition = _definition_for_class(cube, class_type)
    for input_name in _ordered_input_names(cube, class_type, inputs):
        if input_name not in inputs:
            continue
        value = inputs[input_name]
        if is_comfy_node_link(value):
            continue
        values.append(plain_literal_value(value))
        if definition_field_has_serialized_control_widget(definition, input_name):
            values.append("randomize")
    return values


def _apply_output_link_ids(
    nodes: Sequence[MutableMapping[str, Any]],
    output_links_by_node_slot: Mapping[tuple[int, int], Sequence[int]],
) -> None:
    """Populate each output slot with the generated link ids that leave it."""

    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, int):
            continue
        outputs = node.get("outputs")
        if not isinstance(outputs, list):
            continue
        for index, output in enumerate(outputs):
            if not isinstance(output, dict):
                continue
            links = list(output_links_by_node_slot.get((node_id, index), []))
            output["links"] = links or None if node.get("type") == _CUBE_OUTPUT_CLASS else links


def _build_group(placed: _PlacedCube, nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build one SugarCubes managed group from authored group chrome."""

    authored_group = _authored_group(placed.instance.ui_graph)
    bounds = _group_bounds(placed, authored_group, nodes)
    group: dict[str, Any] = dict(copy.deepcopy(authored_group)) if authored_group else {}
    group["title"] = placed.instance.alias
    group["bounding"] = [bounds["x"], bounds["y"], bounds["w"], bounds["h"]]
    group.setdefault("color", "#3f789e")
    group.setdefault("font_size", 24)
    group.setdefault("flags", {})

    metadata = _group_metadata(placed, group, bounds)
    group["sugarcubes"] = metadata
    group["properties"] = {"sugarcubes": metadata}
    return group


def _group_metadata(
    placed: _PlacedCube, group: Mapping[str, Any], bounds: Mapping[str, Any]
) -> dict[str, Any]:
    """Return SugarCubes group metadata with remapped node and marker ids."""

    authored = group.get("sugarcubes")
    metadata = copy.deepcopy(authored) if isinstance(authored, dict) else {}
    instance = placed.instance
    node_ids = [str(node_id) for node_id in placed.node_ids_by_key.values()]
    marker_ids = {
        "inputs": [str(node_id) for node_id in placed.input_marker_ids_by_binding.values()],
        "outputs": [str(node_id) for node_id in placed.output_marker_ids_by_binding.values()],
    }
    metadata.update(
        {
            "schema": metadata.get("schema", 5),
            "managed": True,
            "cube_id": instance.cube_id,
            "default_alias": _default_alias(instance.ui_graph, instance.alias),
            "target_model": _target_model(instance.ui_graph),
            "cube_version": str(instance.ui_graph.get("version") or ""),
            "cube_requested_version": instance.requested_version,
            "cube_resolved_version": instance.resolved_version,
            "cube_definition_key": _cube_definition_key(instance),
            "instance_id": _instance_id(instance),
            "instance_alias": instance.alias,
            "nodes": node_ids,
            "markers": marker_ids,
            "bounds": {
                "x": bounds["x"],
                "y": bounds["y"],
                "w": bounds["w"],
                "h": bounds["h"],
                "padding": {"x": 2, "y": 2, "top_extra": 0},
                "header": {"height": 32},
            },
            "dsl_live": False,
            "dsl_live_session_id": None,
            "flavor": instance.flavor_id or instance.flavor_name or "default",
            "flavor_scope": instance.flavor_scope or "authored",
            "implementation_dirty": False,
            "surface_values_changed": False,
            "cosmetic_dirty": False,
            "has_saveable_changes": False,
            "dirty": False,
            "dirty_at": None,
        }
    )
    return metadata


def _compute_cube_origins(recipe: MaterializedRecipe) -> dict[str, tuple[float, float]]:
    """Place connected cube components in dependency order as horizontal lanes."""

    lanes = _build_placement_lanes(recipe)
    origins: dict[str, tuple[float, float]] = {}
    cursor_y = _INITIAL_GROUP_Y
    for lane in lanes:
        cursor_x = _INITIAL_GROUP_X
        row_height = 0.0
        for alias in lane:
            instance = recipe.cubes_by_alias[alias]
            group_bounds = _authored_group_bounds(instance.ui_graph)
            origins[alias] = (
                cursor_x - group_bounds[0],
                cursor_y - group_bounds[1],
            )
            cursor_x += group_bounds[2] + _GROUP_GAP_X
            row_height = max(row_height, group_bounds[3])
        cursor_y += row_height + _GROUP_GAP_Y
    return origins


def _build_placement_lanes(recipe: MaterializedRecipe) -> list[list[str]]:
    """Return dependency-ordered rows for connected cube components."""

    aliases = list(recipe.order)
    edges = [
        (entry["from"]["alias"], entry["to"]["alias"])
        for entry in recipe.connections
        if entry["from"]["alias"] in aliases and entry["to"]["alias"] in aliases
    ]
    if not edges:
        edges = [
            (entry["from"]["alias"], entry["to"]["alias"])
            for entry in recipe.node_links
            if entry["from"]["alias"] in aliases and entry["to"]["alias"] in aliases
        ]
    if not edges:
        return [[alias] for alias in aliases]

    alias_index = {alias: index for index, alias in enumerate(aliases)}
    undirected: dict[str, set[str]] = {alias: set() for alias in aliases}
    for source, target in edges:
        undirected[source].add(target)
        undirected[target].add(source)

    lanes: list[list[str]] = []
    seen: set[str] = set()
    for alias in aliases:
        if alias in seen:
            continue
        stack = [alias]
        component: list[str] = []
        seen.add(alias)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(undirected[current], key=alias_index.__getitem__):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                stack.append(neighbor)
        component_edges = [
            (source, target)
            for source, target in edges
            if source in component and target in component
        ]
        lanes.append(_topological_component_order(component, component_edges, alias_index))
    return lanes


def _topological_component_order(
    component: Sequence[str],
    edges: Sequence[tuple[str, str]],
    alias_index: Mapping[str, int],
) -> list[str]:
    """Order one connected component left-to-right by dependency direction."""

    incoming = {alias: 0 for alias in component}
    outgoing: dict[str, set[str]] = {alias: set() for alias in component}
    for source, target in edges:
        if source not in outgoing or target not in incoming or target in outgoing[source]:
            continue
        outgoing[source].add(target)
        incoming[target] += 1
    queue = sorted(
        [alias for alias, count in incoming.items() if count == 0],
        key=alias_index.__getitem__,
    )
    ordered: list[str] = []
    while queue:
        alias = queue.pop(0)
        ordered.append(alias)
        for target in sorted(outgoing[alias], key=alias_index.__getitem__):
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
        queue.sort(key=alias_index.__getitem__)
    return (
        ordered
        if len(ordered) == len(component)
        else sorted(component, key=alias_index.__getitem__)
    )


def _merge_subgraph_definitions(
    recipe: MaterializedRecipe,
    context: _WorkflowBuildContext,
) -> dict[str, Any]:
    """Merge raw and instance-specific subgraph definitions for UI export."""

    merged_by_id: dict[str, dict[str, Any]] = {}
    for alias in recipe.order:
        cube = recipe.cubes_by_alias[alias].ui_graph
        subgraphs = cube.get("subgraphs")
        if not isinstance(subgraphs, list):
            continue
        for subgraph in subgraphs:
            if not isinstance(subgraph, dict):
                continue
            subgraph_id = subgraph.get("id")
            if not isinstance(subgraph_id, str) or not subgraph_id:
                continue
            copied = copy.deepcopy(subgraph)
            existing = merged_by_id.get(subgraph_id)
            if existing is not None and existing != copied:
                raise RuntimeError(f"Conflicting SugarCubes subgraph definition '{subgraph_id}'.")
            merged_by_id[subgraph_id] = copied
    for subgraph_id, subgraph in context.subgraph_definitions_by_id.items():
        existing = merged_by_id.get(subgraph_id)
        if existing is not None and existing != subgraph:
            raise RuntimeError(f"Conflicting SugarCubes subgraph definition '{subgraph_id}'.")
        merged_by_id[subgraph_id] = copy.deepcopy(subgraph)
    return {"subgraphs": list(merged_by_id.values())}


def _input_target_bindings(cube: CubeGraph, alias: str) -> dict[tuple[str, str], str]:
    """Map materialized node input targets to their cube input marker binding."""

    result: dict[tuple[str, str], str] = {}
    for binding_name, targets in _ordered_bindings(cube, "inputs"):
        for node_key, input_name in _iter_binding_targets(targets):
            result[(node_key, input_name)] = binding_name
    return result


def _iter_binding_targets(targets: Any) -> Iterable[tuple[str, str]]:
    """Yield node/input pairs affected by one cube input binding."""

    if isinstance(targets, str):
        return
    if isinstance(targets, dict):
        raw_targets = targets.get("targets")
        if isinstance(raw_targets, list):
            targets = raw_targets
        else:
            return
    if isinstance(targets, list):
        for target in targets:
            if (
                isinstance(target, list)
                and len(target) == 2
                and isinstance(target[0], str)
                and isinstance(target[1], str)
            ):
                yield target[0], target[1]


def _input_binding_type(cube: CubeGraph, binding_name: str) -> str:
    """Resolve a marker slot type from the first authored input binding target."""

    inputs = require_mapping(cube, "inputs", "ui")
    for node_key, input_name in _iter_binding_targets(inputs.get(binding_name)):
        nodes = require_mapping(cube, "nodes", "ui")
        node = nodes.get(node_key)
        if isinstance(node, dict):
            return _definition_input_type(cube, str(node.get("class_type") or ""), input_name)
    return "*"


def _output_binding_type(cube: CubeGraph, source_ref: Any, alias: str) -> str:
    """Resolve a marker slot type from an authored output binding source."""

    source_node_key, source_slot = _normalize_source_ref(source_ref, alias)
    nodes = require_mapping(cube, "nodes", alias)
    node = nodes.get(source_node_key)
    if not isinstance(node, dict):
        return "*"
    outputs = _build_output_slots(cube, str(node.get("class_type") or ""))
    if source_slot < len(outputs):
        return str(outputs[source_slot].get("type") or "*")
    return "*"


def _ordered_bindings(cube: CubeGraph, key: str) -> list[tuple[str, Any]]:
    """Return deterministic binding items from a cube graph section."""

    value = cube.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Materialized cube graph has invalid '{key}' mapping.")
    return [(str(name), payload) for name, payload in value.items()]


def _node_inputs(node_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return node inputs as a mapping or fail closed."""

    inputs = node_payload.get("inputs", {})
    if not isinstance(inputs, dict):
        raise RuntimeError("Materialized node has invalid inputs.")
    return inputs


def _normalize_source_ref(value: Any, alias: str) -> tuple[str, int]:
    """Normalize a materialized output reference into node key and slot."""

    if isinstance(value, str):
        return value, 0
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        node_key = value[0]
        if not isinstance(node_key, str):
            raise RuntimeError(f"Output binding on cube '{alias}' must reference a node.")
        return node_key, _coerce_slot(value[1])
    raise RuntimeError(f"Output binding on cube '{alias}' is invalid: {value}.")


def _find_workflow_node(
    nodes: Sequence[MutableMapping[str, Any]], node_id: int
) -> MutableMapping[str, Any]:
    """Return a generated workflow node or fail closed."""

    for node in nodes:
        if node.get("id") == node_id:
            return node
    raise RuntimeError(f"Generated workflow node '{node_id}' was not found.")


def _find_input_slot(node: Mapping[str, Any], input_name: str) -> int:
    """Return the slot index for one named workflow input."""

    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        raise RuntimeError(f"Generated workflow node '{node.get('id')}' has no inputs.")
    for index, slot in enumerate(inputs):
        if isinstance(slot, dict) and slot.get("name") == input_name:
            return index
    raise RuntimeError(f"Generated workflow node '{node.get('id')}' lacks input '{input_name}'.")


def _set_input_link(node: MutableMapping[str, Any], input_name: str, link_id: int) -> None:
    """Set a workflow input slot link by input name."""

    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        raise RuntimeError(f"Generated workflow node '{node.get('id')}' has no inputs.")
    for slot in inputs:
        if isinstance(slot, dict) and slot.get("name") == input_name:
            slot["link"] = link_id
            return
    raise RuntimeError(f"Generated workflow node '{node.get('id')}' lacks input '{input_name}'.")


def _input_slot_type(node: Mapping[str, Any], slot_index: int) -> str:
    """Return a generated input slot type."""

    inputs = node.get("inputs")
    if isinstance(inputs, list) and 0 <= slot_index < len(inputs):
        slot = inputs[slot_index]
        if isinstance(slot, dict):
            return str(slot.get("type") or "*")
    return "*"


def _output_slot_type(node: Mapping[str, Any], slot_index: int) -> str:
    """Return a generated output slot type."""

    outputs = node.get("outputs")
    if isinstance(outputs, list) and 0 <= slot_index < len(outputs):
        slot = outputs[slot_index]
        if isinstance(slot, dict):
            return str(slot.get("type") or "*")
    return "*"


def _definition_for_class(cube: CubeGraph, class_type: str) -> Mapping[str, Any]:
    """Return compact node definition metadata for a class type."""

    definitions = cube.get("definitions")
    if not isinstance(definitions, dict):
        return {}
    definition = definitions.get(class_type)
    return definition if isinstance(definition, dict) else {}


def _definition_input_type(cube: CubeGraph, class_type: str, input_name: str) -> str:
    """Return a Comfy input type from definitions or subgraph interfaces."""

    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is not None:
        inputs = subgraph.get("inputs")
        if isinstance(inputs, list):
            for input_spec in inputs:
                if isinstance(input_spec, dict) and input_spec.get("name") == input_name:
                    return str(input_spec.get("type") or "*")

    field_spec = _definition_input_field(cube, class_type, input_name)
    if isinstance(field_spec, str):
        return field_spec
    if isinstance(field_spec, list) and field_spec:
        first = field_spec[0]
        if isinstance(first, str):
            return "COMBO" if first == "LIST" else first
        if isinstance(first, list):
            return "COMBO"
    return "*"


def _definition_input_is_widget(cube: CubeGraph, class_type: str, input_name: str) -> bool:
    """Return whether a linked input also has widget semantics in Comfy UI."""

    input_type = _definition_input_type(cube, class_type, input_name)
    return input_type in _VALUE_WIDGET_TYPES


def _definition_input_field(cube: CubeGraph, class_type: str, input_name: str) -> Any:
    """Return the raw definition field spec for one input."""

    definition = _definition_for_class(cube, class_type)
    input_payload = definition.get("input")
    if not isinstance(input_payload, dict):
        return None
    for section in ("required", "optional", "hidden"):
        section_payload = input_payload.get(section)
        if isinstance(section_payload, dict) and input_name in section_payload:
            return section_payload[input_name]
    return None


def _ordered_input_names(cube: CubeGraph, class_type: str, inputs: Mapping[str, Any]) -> list[str]:
    """Return definition-ordered input names plus any dynamic authored inputs."""

    ordered: list[str] = []
    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is not None and isinstance(subgraph.get("inputs"), list):
        ordered.extend(
            str(item.get("name"))
            for item in subgraph["inputs"]
            if isinstance(item, dict) and item.get("name")
        )
    definition = _definition_for_class(cube, class_type)
    order_payload = definition.get("input_order")
    if isinstance(order_payload, dict):
        for section in ("required", "optional", "hidden"):
            names = order_payload.get(section)
            if isinstance(names, list):
                ordered.extend(str(name) for name in names if name)
    elif isinstance(order_payload, list):
        ordered.extend(str(name) for name in order_payload if name)
    if not ordered:
        input_payload = definition.get("input")
        if isinstance(input_payload, dict):
            for section in ("required", "optional", "hidden"):
                fields = input_payload.get(section)
                if isinstance(fields, dict):
                    ordered.extend(str(name) for name in fields)
    for input_name in inputs:
        if input_name not in ordered:
            ordered.append(input_name)
    return ordered


def _subgraph_by_id(cube: CubeGraph, class_type: str) -> Mapping[str, Any] | None:
    """Return an authored subgraph matching a wrapper class type."""

    subgraphs = cube.get("subgraphs")
    if not isinstance(subgraphs, list):
        return None
    for subgraph in subgraphs:
        if isinstance(subgraph, dict) and subgraph.get("id") == class_type:
            return subgraph
    return None


def _authored_group(cube: CubeGraph) -> Mapping[str, Any] | None:
    """Return the first authored SugarCubes group from cube layout."""

    layout = cube.get("layout")
    if not isinstance(layout, dict):
        return None
    groups = layout.get("groups")
    if not isinstance(groups, list):
        return None
    for group in groups:
        if isinstance(group, dict):
            return group
    return None


def _authored_group_bounds(cube: CubeGraph) -> tuple[float, float, float, float]:
    """Return local group bounds used for lane placement."""

    group = _authored_group(cube)
    if group is not None:
        bounding = _vec4(group.get("bounding"))
        if bounding is not None:
            return bounding
    return 0.0, 0.0, _DEFAULT_GROUP_WIDTH, _DEFAULT_GROUP_HEIGHT


def _group_bounds(
    placed: _PlacedCube,
    authored_group: Mapping[str, Any] | None,
    nodes: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Return shifted group bounds, falling back to emitted node bounds."""

    if authored_group is not None:
        bounding = _vec4(authored_group.get("bounding"))
        if bounding is not None:
            return {
                "x": _round(placed.origin[0] + bounding[0]),
                "y": _round(placed.origin[1] + bounding[1]),
                "w": _round(bounding[2]),
                "h": _round(bounding[3]),
            }
    generated = _generated_node_bounds(placed, nodes)
    if generated is not None:
        x, y, width, height = generated
        return {
            "x": _round(x - 10),
            "y": _round(y - 60),
            "w": _round(width + 20),
            "h": _round(height + 70),
        }
    return {
        "x": _round(placed.origin[0]),
        "y": _round(placed.origin[1]),
        "w": _DEFAULT_GROUP_WIDTH,
        "h": _DEFAULT_GROUP_HEIGHT,
    }


def _generated_node_bounds(
    placed: _PlacedCube, nodes: Sequence[Mapping[str, Any]]
) -> tuple[float, float, float, float] | None:
    """Compute content bounds from emitted node positions and sizes."""

    owned_ids = set(placed.node_ids_by_key.values())
    owned_ids.update(placed.input_marker_ids_by_binding.values())
    owned_ids.update(placed.output_marker_ids_by_binding.values())
    if not owned_ids:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for node in nodes:
        if node.get("id") not in owned_ids:
            continue
        pos = _vec2(node.get("pos"))
        size = _vec2(node.get("size")) or _DEFAULT_NODE_SIZE
        if pos is None:
            continue
        xs.extend([pos[0], pos[0] + size[0]])
        ys.extend([pos[1], pos[1] + size[1]])
    if not xs or not ys:
        return None
    min_x = min(xs)
    min_y = min(ys)
    return min_x, min_y, max(xs) - min_x, max(ys) - min_y


def _layout_entry(cube: CubeGraph, section: str, name: str) -> Mapping[str, Any]:
    """Return one authored layout entry when present."""

    layout = cube.get("layout")
    if not isinstance(layout, dict):
        return {}
    entries = layout.get(section)
    if not isinstance(entries, dict):
        return {}
    entry = entries.get(name)
    return entry if isinstance(entry, dict) else {}


def _layout_size(layout: Mapping[str, Any], fallback: Sequence[float]) -> list[float]:
    """Return a two-number layout size."""

    size = _vec2(layout.get("size"))
    if size is None:
        return [float(fallback[0]), float(fallback[1])]
    return [_round(size[0]), _round(size[1])]


def _layout_flags(layout: Mapping[str, Any]) -> dict[str, Any]:
    """Return persisted LiteGraph flags from authored layout."""

    flags = layout.get("flags")
    return copy.deepcopy(flags) if isinstance(flags, dict) else {}


def _node_mode(node_payload: Mapping[str, Any], layout: Mapping[str, Any]) -> int:
    """Return a node mode, preferring Sugar UI projection metadata."""

    ui_metadata = node_payload.get("_sugar_ui")
    if isinstance(ui_metadata, dict):
        mode = _number_or_none(ui_metadata.get("mode"))
        if mode is not None:
            return int(mode)
    mode = _number_or_none(node_payload.get("mode"))
    if mode is not None:
        return int(mode)
    return int(_number_or_none(layout.get("mode")) or 0)


def _grid_position(origin: tuple[float, float], order: int) -> list[float]:
    """Return a deterministic fallback node position."""

    return [
        _round(origin[0] + (order % 3) * 320),
        _round(origin[1] + (order // 3) * 260),
    ]


def _shifted_vec2(value: object, origin: tuple[float, float]) -> list[float] | None:
    """Shift a local authored coordinate by a cube instance origin."""

    pos = _vec2(value)
    if pos is None:
        return None
    return [_round(origin[0] + pos[0]), _round(origin[1] + pos[1])]


def _vec2(value: object) -> list[float] | None:
    """Coerce a two-number sequence into floats."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return None
    x = _number_or_none(value[0])
    y = _number_or_none(value[1])
    if x is None or y is None:
        return None
    return [x, y]


def _vec4(value: object) -> tuple[float, float, float, float] | None:
    """Coerce a four-number sequence into bounds."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 4:
        return None
    numbers = [_number_or_none(item) for item in value[:4]]
    if any(item is None for item in numbers):
        return None
    x, y, width, height = numbers
    if x is None or y is None or width is None or height is None:
        return None
    return (x, y, width, height)


def _number_or_none(value: object) -> float | None:
    """Coerce a numeric-like value into a float."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_slot(value: Any) -> int:
    """Coerce a Comfy link slot into an integer."""

    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _local_node_name(alias: str, node_key: str) -> str:
    """Return an alias-qualified node key without the alias prefix."""

    prefix = f"{alias}."
    return node_key[len(prefix) :] if node_key.startswith(prefix) else node_key


def _default_alias(cube: CubeGraph, fallback: str) -> str:
    """Return the authored cube display alias."""

    metadata = cube.get("metadata")
    if isinstance(metadata, dict):
        default_alias = metadata.get("default_alias")
        if isinstance(default_alias, str) and default_alias.strip():
            return default_alias.strip()
    return fallback


def _target_model(cube: CubeGraph) -> str:
    """Return authored target-model metadata when present."""

    metadata = cube.get("metadata")
    if isinstance(metadata, dict):
        target_model = metadata.get("target_model")
        if isinstance(target_model, str):
            return target_model.strip()
    return ""


def _cube_definition_key(instance: MaterializedCubeInstance) -> str:
    """Return the SugarCubes definition key for generated group metadata."""

    version = str(instance.ui_graph.get("version") or "")
    return f"{instance.cube_id}@{version}" if version else instance.cube_id


def _instance_id(instance: MaterializedCubeInstance) -> str:
    """Return a stable instance id for headless generated workflows."""

    digest = hashlib.sha256(f"{instance.cube_id}:{instance.alias}".encode()).hexdigest()
    return f"sugar:{digest[:12]}:{instance.alias}"


def _marker_widget_values(
    *,
    class_type: str,
    binding_name: str,
    placed: _PlacedCube,
) -> list[str]:
    """Return marker widget values in SugarCubes declaration order."""

    instance = placed.instance
    values = [
        instance.cube_id,
        _default_alias(instance.ui_graph, instance.alias),
        instance.alias,
        _instance_id(instance),
    ]
    return values


def _marker_title(binding_name: str, class_type: str) -> str:
    """Return a readable fallback marker title."""

    label = _slot_label(binding_name.split(".")[-1])
    if class_type == _CUBE_OUTPUT_CLASS:
        return f"{label} Output"
    return f"{label} Input"


def _slot_label(value: str) -> str:
    """Return a SugarCubes-style uppercase slot label."""

    if not value or value == "*":
        return "*"
    return value.split(",")[0].replace("_", " ").upper()


def _cnr_id(definition: Mapping[str, Any]) -> str | None:
    """Return the Comfy node registry id when it can be inferred from a definition."""

    module = definition.get("python_module")
    if module == "nodes":
        return "comfy-core"
    if isinstance(module, str) and module.startswith("custom_nodes."):
        return module.split(".", 1)[1]
    return None


def _string_list(value: object) -> list[str]:
    """Return string values from a JSON list."""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _mapping_value(value: object) -> Mapping[str, Any]:
    """Return a mapping value or an empty mapping."""

    return value if isinstance(value, dict) else {}


def _workflow_id(recipe: MaterializedRecipe) -> str:
    """Return a deterministic workflow id for stable embedded metadata."""

    payload = json.dumps(
        [(alias, recipe.cubes_by_alias[alias].cube_id) for alias in recipe.order],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sugar-workflow-{digest[:16]}"


def _round(value: float) -> float:
    """Round layout coordinates to stable precision."""

    return round(float(value), 3)
