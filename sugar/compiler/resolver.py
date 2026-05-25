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
"""Node and binding resolution helpers for compiler graph operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from .graph import CubeGraph
from .live_definitions import LiveNodeDefinitionProvider

BindingKind = Literal["input", "output"]


def resolve_node_key(cube: CubeGraph, alias: str, node_name: str) -> str:
    """Resolve a node name to an alias-qualified materialized node key."""

    nodes = cube.get("nodes", {})
    if not isinstance(nodes, dict):
        raise RuntimeError(f"Cube '{alias}' has invalid nodes mapping.")
    if node_name in nodes:
        return node_name
    materialized_name = f"{alias}.{node_name}"
    if materialized_name in nodes:
        return materialized_name
    label_matches = _node_keys_by_label(nodes, alias).get(node_name, set())
    if len(label_matches) == 1:
        return next(iter(label_matches))
    if len(label_matches) > 1:
        choices = ", ".join(sorted(_local_node_name(alias, key) for key in label_matches))
        raise RuntimeError(f"Node label '{node_name}' is ambiguous in cube '{alias}': {choices}")
    raise RuntimeError(f"Node '{node_name}' not found in cube '{alias}'.")


def resolve_input_key(
    cube: CubeGraph,
    alias: str,
    node_name: str,
    input_label: str,
    *,
    live_node_definition_provider: LiveNodeDefinitionProvider | None = None,
) -> tuple[str, str]:
    """Resolve a script-facing input label to a materialized node and machine key."""

    node_key = resolve_node_key(cube, alias, node_name)
    node = require_mapping(cube, "nodes", alias).get(node_key)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{node_name}' not found in cube '{alias}'.")
    local_name = _local_node_name(alias, node_key)
    label_index = _input_labels_for_node(
        cube,
        local_name,
        node,
        live_node_definition_provider=live_node_definition_provider,
    )
    matches = label_index.get(input_label, set())
    if len(matches) == 1:
        return node_key, next(iter(matches))
    if len(matches) > 1:
        choices = ", ".join(sorted(matches))
        raise RuntimeError(
            f"Input label '{input_label}' is ambiguous on '{alias}.{node_name}': {choices}"
        )
    available = ", ".join(sorted(label_index.keys()))
    raise RuntimeError(
        f"Input label '{input_label}' not found on '{alias}.{node_name}'. Available: {available}"
    )


def resolve_input_label_for_node(
    cube: CubeGraph,
    alias: str,
    node_key: str,
    input_label: str,
    *,
    live_node_definition_provider: LiveNodeDefinitionProvider | None = None,
) -> str | None:
    """Resolve an input label against one materialized node without raising on misses."""

    node = require_mapping(cube, "nodes", alias).get(node_key)
    if not isinstance(node, dict):
        raise RuntimeError(f"Node '{node_key}' not found in cube '{alias}'.")
    local_name = _local_node_name(alias, node_key)
    label_index = _input_labels_for_node(
        cube,
        local_name,
        node,
        live_node_definition_provider=live_node_definition_provider,
    )
    matches = label_index.get(input_label, set())
    if len(matches) > 1:
        choices = ", ".join(sorted(matches))
        raise RuntimeError(
            f"Input label '{input_label}' is ambiguous on '{alias}.{local_name}': {choices}"
        )
    if len(matches) == 1:
        return next(iter(matches))
    return None


def _input_labels_for_node(
    cube: CubeGraph,
    local_node_name: str,
    node: Mapping[str, Any],
    *,
    live_node_definition_provider: LiveNodeDefinitionProvider | None,
) -> dict[str, set[str]]:
    """Build label-to-machine-input mappings for one node scope."""

    labels: dict[str, set[str]] = {}
    _add_surface_control_labels(cube, local_node_name, labels)
    class_type = node.get("class_type")
    if isinstance(class_type, str):
        _add_subgraph_input_labels(cube, class_type, labels)
        _add_definition_input_labels(cube, class_type, labels)
    inputs = node.get("inputs")
    if isinstance(inputs, Mapping):
        for input_name in inputs:
            if isinstance(input_name, str) and input_name:
                _add_label(labels, input_name, input_name)
    if isinstance(class_type, str) and live_node_definition_provider is not None:
        _add_live_input_labels(live_node_definition_provider, class_type, labels)
    return labels


def _add_live_input_labels(
    live_node_definition_provider: LiveNodeDefinitionProvider,
    class_type: str,
    labels: dict[str, set[str]],
) -> None:
    """Add current Comfy input labels supplied by a host live-definition adapter."""

    live_definition = live_node_definition_provider.definition_for(class_type)
    if live_definition is None:
        return
    for input_name, input_definition in live_definition.inputs.items():
        if not input_name:
            continue
        _add_label(labels, input_name, input_name)
        label = _first_string(input_definition.raw, ("label", "localized_name", "name"))
        if label:
            _add_label(labels, label, input_name)


def _add_surface_control_labels(
    cube: CubeGraph, local_node_name: str, labels: dict[str, set[str]]
) -> None:
    """Add persisted surface-control labels for one local node symbol."""

    surface = cube.get("surface")
    if not isinstance(surface, Mapping):
        return
    controls = surface.get("controls")
    if not isinstance(controls, list):
        return
    for control in controls:
        if not isinstance(control, Mapping) or control.get("symbol") != local_node_name:
            continue
        label = control.get("label")
        input_name = control.get("input_name")
        if isinstance(label, str) and label and isinstance(input_name, str) and input_name:
            _add_label(labels, label, input_name)


def _add_subgraph_input_labels(
    cube: CubeGraph, class_type: str, labels: dict[str, set[str]]
) -> None:
    """Add public subgraph input labels for UUID wrapper nodes."""

    subgraphs = cube.get("subgraphs")
    if not isinstance(subgraphs, list):
        return
    for subgraph in subgraphs:
        if not isinstance(subgraph, Mapping) or subgraph.get("id") != class_type:
            continue
        inputs = subgraph.get("inputs")
        if not isinstance(inputs, list):
            return
        for entry in inputs:
            if not isinstance(entry, Mapping):
                continue
            label = entry.get("label")
            name = entry.get("name")
            if isinstance(label, str) and label and isinstance(name, str) and name:
                _add_label(labels, label, name)
        return


def _add_definition_input_labels(
    cube: CubeGraph, class_type: str, labels: dict[str, set[str]]
) -> None:
    """Add definition labels for normal Comfy node inputs."""

    definitions = cube.get("definitions")
    if not isinstance(definitions, Mapping):
        return
    definition = definitions.get(class_type)
    if not isinstance(definition, Mapping):
        return
    input_payload = definition.get("input")
    if not isinstance(input_payload, Mapping):
        return
    for section_name in ("required", "optional", "hidden"):
        section = input_payload.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for input_name, spec in section.items():
            if not isinstance(input_name, str) or not input_name:
                continue
            _add_label(labels, _definition_label(spec) or input_name, input_name)


def _definition_label(spec: Any) -> str:
    """Read a script-facing label from compact Comfy definition metadata."""

    if isinstance(spec, Mapping):
        return _first_string(spec, ("label", "localized_name", "name"))
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], Mapping):
        return _first_string(spec[1], ("label", "localized_name", "name"))
    return ""


def _first_string(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string in a dynamic metadata mapping."""

    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _add_label(labels: dict[str, set[str]], label: str, input_name: str) -> None:
    """Record one script label mapping to one machine input key."""

    labels.setdefault(label, set()).add(input_name)


def _local_node_name(alias: str, node_key: str) -> str:
    """Return a materialized node key without its alias prefix."""

    prefix = f"{alias}."
    if node_key.startswith(prefix):
        return node_key[len(prefix) :]
    return node_key


def _node_keys_by_label(
    nodes: Mapping[str, Any],
    alias: str,
) -> dict[str, set[str]]:
    """Index materialized node keys by their stored script-facing labels."""

    labels: dict[str, set[str]] = {}
    for node_key, node in nodes.items():
        if not isinstance(node_key, str) or not isinstance(node, Mapping):
            continue
        label = node.get("label")
        if not isinstance(label, str) or not label.strip():
            label = _local_node_name(alias, node_key)
        labels.setdefault(label.strip(), set()).add(node_key)
    return labels


def resolve_binding(
    mapping: dict[str, Any], binding_name: str, alias: str, kind: BindingKind
) -> Any:
    """Resolve an exact input or output binding by name."""

    if binding_name in mapping:
        return mapping[binding_name]
    available = ", ".join(str(k) for k in mapping.keys())
    raise RuntimeError(
        f"Could not resolve {kind} '{binding_name}' for cube '{alias}'. Available: {available}"
    )


def resolve_connection_mapping(
    mapping: dict[str, Any],
    alias: str,
    parts: list[str],
    kind: BindingKind,
) -> tuple[str, Any, str | None]:
    """Resolve a DSL connection path to a binding target and optional input key."""

    if not parts:
        raise RuntimeError(f"Connect {kind} missing descriptor for cube '{alias}'")
    remainder = ".".join(parts)
    if remainder in mapping:
        return remainder, mapping[remainder], None
    if kind == "input" and len(parts) > 1:
        prefix = ".".join(parts[:-1])
        if prefix in mapping:
            return prefix, mapping[prefix], parts[-1]
    available = ", ".join(str(k) for k in mapping.keys())
    raise RuntimeError(
        f"Could not resolve {kind} '{remainder}' for cube '{alias}'. Available: {available}"
    )


def require_mapping(cube: CubeGraph, key: str, alias: str) -> dict[str, Any]:
    """Return a named mapping from a materialized cube graph."""

    value = cube.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Cube '{alias}' has invalid '{key}' mapping.")
    return value
