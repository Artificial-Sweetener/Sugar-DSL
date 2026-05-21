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
"""Workflow graph mutation operations used by analysis and code generation."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Callable, cast

from .graph import CubeGraph, CubeGraphByAlias
from .inheritance import apply_inheritance, is_inheritable_provider_input
from .ir import SpawnPlan
from .links import is_comfy_node_link
from .resolver import require_mapping, resolve_binding, resolve_node_key


def apply_plan_connections(cubes: CubeGraphByAlias, plan: SpawnPlan) -> None:
    """Apply spawn-plan connection entries to materialized cube graphs."""

    for entry in plan.get("connections", []):
        from_entry = entry.get("from", {})
        to_entry = entry.get("to", {})
        from_alias = from_entry.get("alias")
        to_alias = to_entry.get("alias")
        output_binding = from_entry.get("output")
        input_binding = to_entry.get("input")
        input_key = to_entry.get("input_key")
        if not from_alias or not to_alias or not output_binding or not input_binding:
            raise RuntimeError("Spawn plan connection entry missing required fields.")
        from_cube = cubes.get(from_alias)
        to_cube = cubes.get(to_alias)
        if not from_cube or not to_cube:
            raise RuntimeError("Spawn plan connection references unknown cube alias.")
        from_node = resolve_binding(
            require_mapping(from_cube, "outputs", from_alias),
            output_binding,
            from_alias,
            "output",
        )
        to_targets = resolve_binding(
            require_mapping(to_cube, "inputs", to_alias),
            input_binding,
            to_alias,
            "input",
        )
        connect_binding_target(
            to_cube,
            to_alias,
            to_targets,
            input_key,
            from_node,
            source_alias=from_alias,
        )


def apply_plan_node_links(cubes: CubeGraphByAlias, plan: SpawnPlan) -> None:
    """Apply whole-node link entries to materialized cube graphs."""

    for entry in plan.get("node_links", []):
        from_entry = entry.get("from", {})
        to_entry = entry.get("to", {})
        from_alias = from_entry.get("alias")
        from_node = from_entry.get("node")
        to_alias = to_entry.get("alias")
        to_node = to_entry.get("node")
        if not from_alias or not from_node or not to_alias or not to_node:
            raise RuntimeError("Spawn plan node-link entry missing required fields.")
        source_cube = cubes.get(from_alias)
        target_cube = cubes.get(to_alias)
        if not source_cube or not target_cube:
            raise RuntimeError("Spawn plan node-link references unknown cube alias.")
        apply_node_link(
            source_cube=source_cube,
            source_alias=from_alias,
            source_node_name=from_node,
            target_cube=target_cube,
            target_alias=to_alias,
            target_node_name=to_node,
        )


def apply_plan_ui_inherited_provider_values(cubes: CubeGraphByAlias, plan: SpawnPlan) -> None:
    """Copy inherited provider values into local UI provider nodes.

    The execution graph should rewire inherited model/clip/vae inputs to the
    actual upstream provider. The UI workflow needs a runnable local graph, so
    disabled checkpoint loaders that inherit from an upstream checkpoint are
    displayed as local copies with the same literal model selection.
    """

    for set_entry in plan.get("sets", []):
        metadata = set_entry.get("metadata") or {}
        if metadata.get("kind") != "inferred":
            continue
        inherited_value = set_entry.get("value")
        if not is_comfy_node_link(inherited_value):
            continue
        alias = set_entry.get("alias")
        target_input = set_entry.get("input")
        if not alias or not target_input:
            raise RuntimeError("Inferred set entry missing alias or input.")
        target_cube = cubes.get(alias)
        if not target_cube:
            raise RuntimeError(f"Inferred set references unknown cube alias '{alias}'.")
        target_node_key = _set_node_key(set_entry, alias, target_cube)
        target_node = _require_node(target_cube, alias, target_node_key)
        current_value = _node_inputs(target_node, alias, target_node_key).get(target_input)
        if not _is_string_node_link(current_value):
            continue
        current_link = cast(Sequence[Any], current_value)
        local_provider_key = str(current_link[0])
        local_provider = _node_or_none(target_cube, local_provider_key)
        if local_provider is None:
            continue
        source_provider = _find_node_by_key(cubes, str(inherited_value[0]))
        if source_provider is None:
            continue
        if not _can_copy_inherited_provider(local_provider, source_provider):
            continue
        _copy_literal_inputs(source_provider, local_provider)
        ui_metadata = local_provider.setdefault("_sugar_ui", {})
        if isinstance(ui_metadata, dict):
            ui_metadata["inherited_provider_clone"] = True
    for connection in plan.get("connections", []):
        from_entry = connection.get("from", {})
        to_entry = connection.get("to", {})
        from_alias = from_entry.get("alias")
        to_alias = to_entry.get("alias")
        output_binding = from_entry.get("output")
        input_binding = to_entry.get("input")
        if not from_alias or not to_alias or not output_binding or not input_binding:
            raise RuntimeError("Spawn plan connection entry missing required fields.")
        from_cube = cubes.get(from_alias)
        to_cube = cubes.get(to_alias)
        if not from_cube or not to_cube:
            raise RuntimeError("Spawn plan connection references unknown cube alias.")
        source_ref = resolve_binding(
            require_mapping(from_cube, "outputs", from_alias),
            output_binding,
            from_alias,
            "output",
        )
        target_refs = resolve_binding(
            require_mapping(to_cube, "inputs", to_alias),
            input_binding,
            to_alias,
            "input",
        )
        for target_node_key, target_input in _iter_ui_binding_targets(target_refs):
            _copy_ui_provider_for_target(
                cubes=cubes,
                target_cube=to_cube,
                target_alias=to_alias,
                target_node_key=target_node_key,
                target_input=target_input,
                source_ref=source_ref,
            )


def apply_plan_ui_disabled_modes(cubes: CubeGraphByAlias, plan: SpawnPlan) -> None:
    """Mark disabled UI nodes as bypass unless they are inherited provider clones."""

    for entry in plan.get("disabled", []):
        alias = entry.get("alias")
        node_name = entry.get("node")
        if not alias or not node_name:
            raise RuntimeError("Spawn plan disabled entry missing alias or node.")
        cube = cubes.get(alias)
        if not cube:
            raise RuntimeError(f"Disable references unknown cube alias '{alias}'.")
        node_key = resolve_node_key(cube, alias, node_name)
        node = _require_node(cube, alias, node_key)
        ui_metadata = node.setdefault("_sugar_ui", {})
        if not isinstance(ui_metadata, dict):
            ui_metadata = {}
            node["_sugar_ui"] = ui_metadata
        ui_metadata["disabled"] = True
        if ui_metadata.get("inherited_provider_clone") is True:
            ui_metadata["mode"] = 0
        else:
            ui_metadata["mode"] = 4


def apply_plan_ui_enabled_modes(cubes: CubeGraphByAlias, plan: SpawnPlan) -> None:
    """Mark explicitly enabled UI nodes as active despite authored bypass."""

    for entry in plan.get("enabled", []):
        alias = entry.get("alias")
        node_name = entry.get("node")
        if not alias or not node_name:
            raise RuntimeError("Spawn plan enabled entry missing alias or node.")
        cube = cubes.get(alias)
        if not cube:
            raise RuntimeError(f"Enable references unknown cube alias '{alias}'.")
        node_key = resolve_node_key(cube, alias, node_name)
        node = _require_node(cube, alias, node_key)
        ui_metadata = node.setdefault("_sugar_ui", {})
        if not isinstance(ui_metadata, dict):
            ui_metadata = {}
            node["_sugar_ui"] = ui_metadata
        ui_metadata["disabled"] = False
        ui_metadata["mode"] = 0


def apply_node_link(
    *,
    source_cube: CubeGraph,
    source_alias: str,
    source_node_name: str,
    target_cube: CubeGraph,
    target_alias: str,
    target_node_name: str,
) -> None:
    """Copy eligible editable values from one compatible source node to a target."""

    source_node_key = resolve_node_key(source_cube, source_alias, source_node_name)
    target_node_key = resolve_node_key(target_cube, target_alias, target_node_name)
    source_nodes = require_mapping(source_cube, "nodes", source_alias)
    target_nodes = require_mapping(target_cube, "nodes", target_alias)
    source_node = source_nodes.get(source_node_key)
    target_node = target_nodes.get(target_node_key)
    if not isinstance(source_node, dict) or not isinstance(target_node, dict):
        raise RuntimeError(
            f"Node link references invalid node '{source_alias}.{source_node_name}' "
            f"or '{target_alias}.{target_node_name}'."
        )
    validate_node_link_compatibility(
        source_node=source_node,
        source_alias=source_alias,
        source_node_key=source_node_key,
        target_node=target_node,
        target_alias=target_alias,
        target_node_key=target_node_key,
    )
    source_inputs = _node_inputs(source_node, source_alias, source_node_key)
    target_inputs = _node_inputs(target_node, target_alias, target_node_key)
    for input_key, value in source_inputs.items():
        if is_comfy_node_link(value):
            continue
        target_inputs[input_key] = copy.deepcopy(value)
    if "enabled" in source_node:
        target_node["enabled"] = copy.deepcopy(source_node["enabled"])
    else:
        target_node.pop("enabled", None)


def validate_node_link_compatibility(
    *,
    source_node: dict[str, Any],
    source_alias: str,
    source_node_key: str,
    target_node: dict[str, Any],
    target_alias: str,
    target_node_key: str,
) -> None:
    """Fail closed when two nodes cannot share whole-node value state."""

    source_type = source_node.get("class_type")
    target_type = target_node.get("class_type")
    if source_type != target_type:
        raise RuntimeError(
            "Node link class types differ: "
            f"'{source_alias}.{_local_node_name(source_alias, source_node_key)}' "
            f"is '{source_type}', "
            f"'{target_alias}.{_local_node_name(target_alias, target_node_key)}' "
            f"is '{target_type}'."
        )

    source_inputs = _node_inputs(source_node, source_alias, source_node_key)
    target_inputs = _node_inputs(target_node, target_alias, target_node_key)
    source_value_keys = {
        key for key, value in source_inputs.items() if not is_comfy_node_link(value)
    }
    target_value_keys = {
        key for key, value in target_inputs.items() if not is_comfy_node_link(value)
    }
    if source_value_keys != target_value_keys:
        raise RuntimeError(
            "Node link editable input keys differ for "
            f"'{source_alias}.{_local_node_name(source_alias, source_node_key)}' "
            f"and '{target_alias}.{_local_node_name(target_alias, target_node_key)}'."
        )

    source_graph_signature = _graph_connection_signature(source_inputs, source_alias)
    target_graph_signature = _graph_connection_signature(target_inputs, target_alias)
    if source_graph_signature != target_graph_signature:
        raise RuntimeError(
            "Node link graph inputs differ for "
            f"'{source_alias}.{_local_node_name(source_alias, source_node_key)}' "
            f"and '{target_alias}.{_local_node_name(target_alias, target_node_key)}'."
        )


def connect_binding_target(
    cube: CubeGraph,
    alias: str,
    to_targets: Any,
    input_key: str | None,
    from_node: Any,
    *,
    source_alias: str | None = None,
) -> None:
    """Connect one resolved output node to one resolved input binding target."""

    nodes = require_mapping(cube, "nodes", alias)
    source_link = _output_link_from_binding(from_node, source_alias or alias)
    if isinstance(to_targets, list):
        if input_key:
            raise RuntimeError(f"Input binding on cube '{alias}' does not accept input keys.")
        for target in to_targets:
            if not isinstance(target, list) or len(target) != 2:
                raise RuntimeError(
                    f"Input binding on cube '{alias}' contains invalid target {target}."
                )
            node_key, target_input = target
            if not isinstance(node_key, str) or not isinstance(target_input, str):
                raise RuntimeError(
                    f"Input binding on cube '{alias}' must target string node inputs."
                )
            node = nodes.get(node_key)
            if not isinstance(node, dict):
                raise RuntimeError(f"Node '{node_key}' not found in cube '{alias}'.")
            node.setdefault("inputs", {})[target_input] = list(source_link)
        return
    if not isinstance(to_targets, str):
        raise RuntimeError(f"Input binding on cube '{alias}' must resolve to a node key.")
    if not input_key:
        raise RuntimeError(f"Connection to '{alias}' requires an input key.")
    node = nodes.get(to_targets)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{to_targets}' not found in cube '{alias}'.")
    node.setdefault("inputs", {})[input_key] = list(source_link)


def apply_plan_sets(cubes: CubeGraphByAlias, plan: SpawnPlan, kind: str) -> None:
    """Apply set entries of one kind to materialized cube graphs."""

    for set_entry in plan.get("sets", []):
        metadata = set_entry.get("metadata") or {}
        if metadata.get("kind") != kind:
            continue
        alias = set_entry.get("alias")
        node_name = set_entry.get("node")
        input_key = set_entry.get("input")
        value = set_entry.get("value")
        if not alias or not node_name or not input_key:
            raise RuntimeError("Spawn plan set entry missing alias, node, or input.")
        cube = cubes.get(alias)
        if not cube:
            raise RuntimeError(f"Set references unknown cube alias '{alias}'.")
        apply_set(cube, alias, node_name, input_key, value)


def apply_set(cube: CubeGraph, alias: str, node_name: str, input_key: str, value: Any) -> str:
    """Apply one input value to a resolved materialized node."""

    nodes = require_mapping(cube, "nodes", alias)
    node_key = resolve_node_key(cube, alias, node_name)
    node = nodes.get(node_key)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{node_name}' not found in cube '{alias}'.")
    node.setdefault("inputs", {})[input_key] = value
    return node_key


def _set_node_key(set_entry: Mapping[str, Any], alias: str, cube: CubeGraph) -> str:
    """Resolve a set entry node key, preferring analyzer-qualified metadata."""

    metadata = set_entry.get("metadata") or {}
    node_key = metadata.get("node_key")
    if isinstance(node_key, str) and node_key in require_mapping(cube, "nodes", alias):
        return node_key
    node_name = set_entry.get("node")
    if not isinstance(node_name, str) or not node_name:
        raise RuntimeError("Set entry missing node.")
    return resolve_node_key(cube, alias, node_name)


def _require_node(cube: CubeGraph, alias: str, node_key: str) -> dict[str, Any]:
    """Return a mutable node payload or fail with cube context."""

    node = require_mapping(cube, "nodes", alias).get(node_key)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{node_key}' not found in cube '{alias}'.")
    return node


def _node_or_none(cube: CubeGraph, node_key: str) -> dict[str, Any] | None:
    """Return a node payload when the key exists in one cube."""

    nodes = cube.get("nodes")
    if not isinstance(nodes, dict):
        return None
    node = nodes.get(node_key)
    return node if isinstance(node, dict) else None


def _find_node_by_key(cubes: CubeGraphByAlias, node_key: str) -> dict[str, Any] | None:
    """Find a node by materialized key across all cube aliases."""

    for cube in cubes.values():
        node = _node_or_none(cube, node_key)
        if node is not None:
            return node
    return None


def _iter_ui_binding_targets(targets: Any) -> Iterable[tuple[str, str]]:
    """Yield materialized node/input targets from a UI binding payload."""

    if isinstance(targets, str):
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


def _copy_ui_provider_for_target(
    *,
    cubes: CubeGraphByAlias,
    target_cube: CubeGraph,
    target_alias: str,
    target_node_key: str,
    target_input: str,
    source_ref: Any,
) -> None:
    """Copy a connected upstream provider into a local UI provider when possible."""

    target_node = _require_node(target_cube, target_alias, target_node_key)
    current_value = _node_inputs(target_node, target_alias, target_node_key).get(target_input)
    if not _is_string_node_link(current_value):
        return
    current_link = cast(Sequence[Any], current_value)
    local_provider = _node_or_none(target_cube, str(current_link[0]))
    source_link = _output_link_from_binding(source_ref, target_alias)
    source_provider = _find_node_by_key(cubes, source_link[0])
    if local_provider is None or source_provider is None:
        return
    if not _can_copy_inherited_provider(local_provider, source_provider):
        return
    _copy_literal_inputs(source_provider, local_provider)
    ui_metadata = local_provider.setdefault("_sugar_ui", {})
    if isinstance(ui_metadata, dict):
        ui_metadata["inherited_provider_clone"] = True


def _is_string_node_link(value: Any) -> bool:
    """Return whether a value is an indexable node link with a string node key."""

    return is_comfy_node_link(value) and len(value) >= 2 and isinstance(value[0], str)


def _can_copy_inherited_provider(
    local_provider: dict[str, Any], source_provider: dict[str, Any]
) -> bool:
    """Return whether two provider nodes can share visible literal values."""

    local_class = local_provider.get("class_type")
    source_class = source_provider.get("class_type")
    if local_class != source_class or not isinstance(local_class, str):
        return False
    return "CheckpointLoader" in local_class


def _copy_literal_inputs(source_node: dict[str, Any], target_node: dict[str, Any]) -> None:
    """Copy non-link inputs from a source provider into a local UI provider."""

    source_inputs = source_node.get("inputs")
    if not isinstance(source_inputs, dict):
        return
    target_inputs = target_node.setdefault("inputs", {})
    if not isinstance(target_inputs, dict):
        raise RuntimeError("Target UI provider node has invalid inputs.")
    for input_key, value in source_inputs.items():
        if is_comfy_node_link(value):
            continue
        target_inputs[input_key] = copy.deepcopy(value)


def _node_inputs(
    node: dict[str, Any],
    alias: str,
    node_key: str,
) -> dict[str, Any]:
    """Return the mutable node input mapping or fail with node context."""

    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        raise RuntimeError(f"Node '{node_key}' in cube '{alias}' has invalid inputs.")
    return inputs


def _graph_connection_signature(
    inputs: dict[str, Any],
    alias: str,
) -> tuple[tuple[str, tuple[str, int]], ...]:
    """Return graph-input shape normalized relative to the owning cube alias."""

    signature: list[tuple[str, tuple[str, int]]] = []
    for input_key, value in inputs.items():
        if not is_comfy_node_link(value):
            continue
        source_node, slot = value
        normalized_source = _relative_source_node(alias, source_node)
        signature.append((input_key, (normalized_source, slot)))
    return tuple(sorted(signature))


def _relative_source_node(alias: str, source_node: str) -> str:
    """Return local graph references without the cube alias prefix."""

    prefix = f"{alias}."
    if source_node.startswith(prefix):
        return source_node[len(prefix) :]
    return source_node


def _local_node_name(alias: str, node_key: str) -> str:
    """Return a materialized node key without its owning alias prefix."""

    return _relative_source_node(alias, node_key)


def apply_plan_disabled(cubes: CubeGraphByAlias, plan: SpawnPlan) -> set[str]:
    """Disable all nodes listed in a spawn plan and return disabled node keys."""

    disabled_nodes: set[str] = set()
    for entry in plan.get("disabled", []):
        alias = entry.get("alias")
        node_name = entry.get("node")
        if not alias or not node_name:
            raise RuntimeError("Spawn plan disabled entry missing alias or node.")
        cube = cubes.get(alias)
        if not cube:
            raise RuntimeError(f"Disable references unknown cube alias '{alias}'.")
        node_key = disable_node_passthrough(cube, alias, node_name)
        disabled_nodes.add(node_key)
    return disabled_nodes


def disable_node_passthrough(cube: CubeGraph, alias: str, node_name: str) -> str:
    """Remove one node and transparently rewire same-named downstream inputs."""

    nodes = require_mapping(cube, "nodes", alias)
    node_key = resolve_node_key(cube, alias, node_name)
    node = nodes.get(node_key)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{node_name}' not found in cube '{alias}'.")
    passthrough_map = node.get("inputs", {})
    if not isinstance(passthrough_map, dict):
        raise RuntimeError(f"Node '{node_key}' has invalid inputs for disable.")
    del nodes[node_key]

    for other_node_key, other_node in nodes.items():
        if not isinstance(other_node, dict):
            raise RuntimeError(f"Node '{other_node_key}' in cube '{alias}' is invalid.")
        original_inputs = other_node.get("inputs")
        if not isinstance(original_inputs, dict):
            raise RuntimeError(f"Node '{other_node_key}' in cube '{alias}' has invalid inputs.")
        rewired_inputs: dict[str, Any] = {}
        for input_name, value in original_inputs.items():
            if _references_node(value, node_key):
                rewired_inputs[input_name] = _disabled_passthrough_value(
                    input_name,
                    passthrough_map,
                )
            else:
                rewired_inputs[input_name] = value
        other_node["inputs"] = rewired_inputs
    return node_key


def _disabled_passthrough_value(
    input_name: str,
    passthrough_map: Mapping[str, Any],
) -> Any:
    """Return a value that can safely replace a disabled node reference."""

    passthrough_value = passthrough_map.get(input_name)
    if not is_inheritable_provider_input(input_name):
        return passthrough_value
    if is_comfy_node_link(passthrough_value):
        return passthrough_value
    return None


def apply_plan_inheritance(
    cubes: CubeGraphByAlias,
    order: list[str],
    disabled_nodes: set[str],
    on_set: Callable[[str, str, str, Any], None] | None = None,
) -> None:
    """Apply model/clip/vae inheritance to materialized cube graphs."""

    apply_inheritance(cubes, order, disabled_nodes, on_set=on_set)


def _references_node(value: Any, node_key: str) -> bool:
    """Return whether a ComfyUI input link references the given node key."""

    return isinstance(value, list) and bool(value) and value[0] == node_key


def _output_link_from_binding(value: Any, alias: str) -> tuple[str, int]:
    """Normalize a cube output binding into a concrete ComfyUI node link."""

    if isinstance(value, str):
        return value, 0
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) < 2:
            raise RuntimeError(f"Output binding on cube '{alias}' is invalid: {value}.")
        node_key = value[0]
        slot = value[1]
        if not isinstance(node_key, str):
            raise RuntimeError(
                f"Output binding on cube '{alias}' must reference a string node key: {value}."
            )
        if isinstance(slot, bool):
            raise RuntimeError(
                f"Output binding on cube '{alias}' has invalid boolean slot: {value}."
            )
        if isinstance(slot, int):
            return node_key, slot
        if isinstance(slot, float) and slot.is_integer():
            return node_key, int(slot)
        if isinstance(slot, str):
            try:
                return node_key, int(slot)
            except ValueError as exc:
                raise RuntimeError(
                    f"Output binding on cube '{alias}' has invalid slot: {value}."
                ) from exc
        raise RuntimeError(f"Output binding on cube '{alias}' has invalid slot: {value}.")
    raise RuntimeError(f"Output binding on cube '{alias}' is invalid: {value}.")
