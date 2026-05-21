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
"""Cube instance materialization for compiler analysis and workflow generation."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any, Iterable, cast

from ..catalog.artifacts import CubeArtifactResolver, FilesystemCubeArtifactResolver
from ..catalog.local_flavors import LocalFlavorCatalog
from ..catalog.models import CubeDocument
from ..catalog.registry import CubeRegistry
from .flavors import (
    apply_default_flavor,
    apply_flavor_values,
    compute_surface_signature,
    resolve_flavor,
    validate_flavor_values_against_surface,
)
from .graph import CubeGraph, ResolvedCubeInstance
from .links import is_comfy_node_link

CUBE_OUTPUT_NODE_CLASS = "SugarCubes.CubeOutput"
_CUBE_OUTPUT_NODE_PREFIX = "cube_output"


class CubeMaterializer:
    """Load, flavor, alias, and title cube instances through one compiler owner."""

    def __init__(
        self,
        artifact_resolver: CubeArtifactResolver,
        local_flavors: LocalFlavorCatalog | None = None,
    ) -> None:
        """Create a materializer backed by catalog registries."""

        self._artifact_resolver = artifact_resolver
        self._local_flavors = local_flavors

    @classmethod
    def from_registry(
        cls,
        registry: CubeRegistry,
        local_flavors: LocalFlavorCatalog | None = None,
    ) -> "CubeMaterializer":
        """Create a materializer backed by the default filesystem resolver."""

        return cls(FilesystemCubeArtifactResolver(registry), local_flavors)

    def materialize_resolved(
        self,
        *,
        cube_id: str,
        alias: str,
        version_pin: str | None,
        flavor_name: str | None,
    ) -> ResolvedCubeInstance:
        """Materialize a cube after resolving authored or local flavor choice."""

        artifact = self._artifact_resolver.resolve(
            alias=alias,
            cube_id=cube_id,
            requested_version=version_pin,
        )
        raw_cube = artifact.cube
        surface_signature = compute_surface_signature(raw_cube)
        local_entries = (
            self._local_flavors.load_flavors(cube_id, surface_signature)
            if self._local_flavors is not None
            else []
        )
        validate_flavor_values_against_surface(raw_cube, local_entries, scope="local")
        resolved_flavor = resolve_flavor(raw_cube, flavor_name, local_entries)
        flavored_cube = apply_default_flavor(raw_cube)
        default_id = str(raw_cube.get("surface", {}).get("default_flavor_id") or "default")
        if resolved_flavor.id != default_id or resolved_flavor.scope == "local":
            flavored_cube = apply_flavor_values(
                flavored_cube,
                {
                    "id": resolved_flavor.id,
                    "name": resolved_flavor.name,
                    "values": resolved_flavor.values,
                },
            )
        return ResolvedCubeInstance(
            cube_id=cube_id,
            alias=alias,
            version_pin=version_pin,
            requested_version=artifact.identity.requested_version,
            resolved_version=artifact.identity.resolved_version,
            flavor_name=flavor_name,
            flavor_id=resolved_flavor.id,
            flavor_scope=resolved_flavor.scope,
            flavor_values=copy.deepcopy(resolved_flavor.values),
            raw_cube=raw_cube,
            cube=materialize_cube_graph(flavored_cube, alias),
        )

    def materialize_default_resolved(
        self, *, cube_id: str, alias: str, version_pin: str | None
    ) -> ResolvedCubeInstance:
        """Materialize a cube with only its default authored flavor applied."""

        artifact = self._artifact_resolver.resolve(
            alias=alias,
            cube_id=cube_id,
            requested_version=version_pin,
        )
        raw_cube = artifact.cube
        return ResolvedCubeInstance(
            cube_id=cube_id,
            alias=alias,
            version_pin=version_pin,
            requested_version=artifact.identity.requested_version,
            resolved_version=artifact.identity.resolved_version,
            flavor_name=None,
            flavor_id="default",
            flavor_scope="authored",
            flavor_values={},
            raw_cube=raw_cube,
            cube=materialize_cube_graph(apply_default_flavor(raw_cube), alias),
        )


def materialize_cube_graph(cube: CubeDocument, alias: str) -> CubeGraph:
    """Return an alias-qualified mutable graph for one cube document."""

    graph, _queue = rename_cube_nodes(cube, alias)
    add_cube_output_boundary_nodes(graph, alias)
    apply_cube_meta_titles(graph, alias)
    return graph


def add_cube_output_boundary_nodes(cube: CubeGraph, alias: str) -> None:
    """Lower canonical cube outputs into executable SugarCubes output nodes."""

    outputs = _require_mapping(cube, "outputs")
    if not outputs:
        return

    nodes = _require_nodes(cube)
    cube_id = str(cube.get("cube_id") or "")
    default_alias = _default_alias(cube, alias)
    for binding_name, output_ref in outputs.items():
        if not isinstance(binding_name, str):
            raise RuntimeError(f"Cube '{cube_id}' has invalid output binding name.")
        node_key = _unique_output_node_key(binding_name, alias, nodes)
        nodes[node_key] = {
            "class_type": CUBE_OUTPUT_NODE_CLASS,
            "inputs": {
                "value": list(_output_link_from_binding(output_ref, alias)),
                "cube_id": cube_id,
                "default_alias": default_alias,
                "instance_alias": alias,
                "instance_id": alias,
            },
        }


def apply_cube_meta_titles(cube: CubeGraph, alias: str) -> None:
    """Apply deterministic display titles to every materialized node."""

    nodes = _require_nodes(cube)
    for node_key, node in nodes.items():
        node_key_no_prefix = node_key
        if node_key.startswith(f"{alias}."):
            node_key_no_prefix = node_key[len(f"{alias}.") :]
        metadata = node.setdefault("_meta", {})
        if not isinstance(metadata, dict):
            raise RuntimeError(f"Node '{node_key}' has invalid '_meta' metadata.")
        metadata["title"] = f"{alias}.{node_key_no_prefix}"
        metadata["substitute"] = {
            "cube_alias": alias,
            "node_name": node_key_no_prefix,
        }


def rename_cube_nodes(cube: CubeDocument, alias: str) -> tuple[CubeGraph, list[str]]:
    """Return a mutable cube graph with node keys qualified by alias."""

    nodes = cube.get("nodes")
    if not isinstance(nodes, dict):
        raise RuntimeError(f"Cube '{cube.get('cube_id')}' has invalid nodes mapping.")

    renamed_nodes: dict[str, dict[str, Any]] = {}
    node_map: dict[str, str] = {}
    for old_name, node in nodes.items():
        new_name = _materialized_node_key(alias, old_name)
        if new_name in renamed_nodes:
            raise RuntimeError(
                f"Cube '{cube.get('cube_id')}' has duplicate materialized node key "
                f"'{new_name}' for alias '{alias}'."
            )
        renamed_nodes[new_name] = cast(dict[str, Any], copy.deepcopy(node))
        node_map[old_name] = new_name

    for node_payload in renamed_nodes.values():
        new_inputs: dict[str, Any] = {}
        raw_inputs = node_payload.get("inputs", {})
        if not isinstance(raw_inputs, dict):
            raise RuntimeError("Cube node inputs must be mappings after validation.")
        for key, val in raw_inputs.items():
            if is_comfy_node_link(val):
                ref = val[0]
                new_inputs[key] = [
                    _resolve_materialized_node_ref(str(ref), cube, alias, node_map),
                    val[1],
                ]
            else:
                new_inputs[key] = copy.deepcopy(val)
        node_payload["inputs"] = new_inputs

    materialized: CubeGraph = {"nodes": renamed_nodes, "outputs": {}, "inputs": {}}
    cube_data = cast(dict[str, Any], cube)
    for key in (
        "layout",
        "definitions",
        "subgraphs",
        "surface",
        "metadata",
        "cube_id",
        "version",
    ):
        if key in cube:
            materialized[key] = copy.deepcopy(cube_data[key])

    _copy_outputs(cube, materialized, alias, node_map)
    _copy_inputs(cube, materialized, alias, renamed_nodes, node_map)
    queue = _resolve_queue(cube, alias, node_map)
    if "description" in cube:
        materialized["description"] = cube["description"]
    return materialized, queue


def _materialized_node_key(alias: str, node_key: str) -> str:
    """Return the alias-qualified node key used inside compiler graphs."""

    return f"{alias}.{node_key}"


def _copy_outputs(
    cube: CubeDocument,
    materialized: CubeGraph,
    alias: str,
    node_map: dict[str, str],
) -> None:
    """Copy and alias cube output bindings."""

    outputs = cube.get("outputs", {})
    if not isinstance(outputs, dict):
        raise RuntimeError(f"Cube '{cube.get('cube_id')}' has invalid outputs mapping.")
    materialized_outputs = _require_mapping(materialized, "outputs")
    for key, ref in outputs.items():
        if isinstance(ref, str):
            materialized_outputs[key] = _resolve_materialized_node_ref(ref, cube, alias, node_map)
        elif is_comfy_node_link(ref):
            materialized_outputs[key] = [
                _resolve_materialized_node_ref(str(ref[0]), cube, alias, node_map),
                ref[1],
            ]
        else:
            materialized_outputs[key] = copy.deepcopy(ref)


def _copy_inputs(
    cube: CubeDocument,
    materialized: CubeGraph,
    alias: str,
    renamed_nodes: dict[str, dict[str, Any]],
    node_map: dict[str, str],
) -> None:
    """Copy and alias cube input bindings."""

    materialized_inputs = _require_mapping(materialized, "inputs")
    inputs = cube.get("inputs", {})
    if not isinstance(inputs, dict):
        raise RuntimeError(f"Cube '{cube.get('cube_id')}' has invalid inputs mapping.")
    for input_key, raw in inputs.items():
        if isinstance(raw, str):
            materialized_inputs[input_key] = _resolve_materialized_node_ref(
                raw, cube, alias, node_map
            )
        elif isinstance(raw, list):
            materialized_inputs[input_key] = _map_input_targets(
                raw, input_key, cube, alias, renamed_nodes, node_map
            )
        elif isinstance(raw, dict):
            targets = raw.get("targets")
            if isinstance(targets, list):
                materialized_inputs[input_key] = _map_input_targets(
                    targets, input_key, cube, alias, renamed_nodes, node_map
                )
            else:
                materialized_inputs[input_key] = copy.deepcopy(raw)
        else:
            materialized_inputs[input_key] = copy.deepcopy(raw)


def _map_input_targets(
    targets: Iterable[Any],
    input_key: str,
    cube: CubeDocument,
    alias: str,
    renamed_nodes: dict[str, dict[str, Any]],
    node_map: dict[str, str],
) -> list[list[str]]:
    """Map cube input target declarations to alias-qualified node keys."""

    mapped: list[list[str]] = []
    for item in targets:
        try:
            node_id, input_name = item
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid input mapping in cube '{cube.get('__template__', '')}' "
                f"for key '{input_key}': {item} ({exc})."
            ) from exc
        if not isinstance(node_id, str) or not isinstance(input_name, str):
            raise RuntimeError(
                f"Input mapping for cube '{cube.get('__template__', '')}' "
                f"key '{input_key}' must contain string node and input names."
            )
        full_node = node_map.get(node_id)
        if full_node is None:
            raise RuntimeError(
                f"Could not resolve input target '{node_id}' in cube "
                f"'{cube.get('__template__', '')}'."
            )
        renamed_nodes[full_node].setdefault("inputs", {})[input_name] = [
            "EXTERNAL_INPUT",
            0,
        ]
        mapped.append([full_node, input_name])
    return mapped


def _resolve_queue(cube: CubeDocument, alias: str, node_map: dict[str, str]) -> list[str]:
    """Resolve optional queue entries to alias-qualified node keys."""

    resolved_queue: list[str] = []
    queue = cube.get("queue", [])
    if not isinstance(queue, list):
        return resolved_queue
    for entry in queue:
        if not isinstance(entry, str):
            raise RuntimeError(f"Cube '{cube.get('cube_id')}' has invalid queue entry.")
        if entry in node_map:
            resolved_queue.append(node_map[entry])
            continue
        raise RuntimeError(
            f"Could not resolve queue entry '{entry}' in cube '{cube.get('__template__', '')}'."
        )
    return resolved_queue


def _default_alias(cube: CubeGraph, fallback: str) -> str:
    """Return authored display alias metadata for runtime output nodes."""

    metadata = cube.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("default_alias")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _unique_output_node_key(
    binding_name: str,
    alias: str,
    nodes: dict[str, dict[str, Any]],
) -> str:
    """Return a collision-free materialized node key for one output boundary."""

    suffix = binding_name
    if suffix.startswith("output."):
        suffix = suffix[len("output.") :]
    sanitized = "".join(character if character.isalnum() else "_" for character in suffix).strip(
        "_"
    )
    base = _materialized_node_key(alias, f"{_CUBE_OUTPUT_NODE_PREFIX}_{sanitized or 'value'}")
    candidate = base
    counter = 2
    while candidate in nodes:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _output_link_from_binding(value: Any, alias: str) -> tuple[str, int]:
    """Normalize one materialized cube output binding into a node input link."""

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
        raise RuntimeError(f"Output binding on cube '{alias}' has invalid slot: {value}.")
    raise RuntimeError(f"Output binding on cube '{alias}' is invalid: {value}.")


def _resolve_materialized_node_ref(
    node_id: str, cube: CubeDocument, alias: str, node_map: dict[str, str]
) -> str:
    """Resolve one cube-local node reference to its materialized key."""

    resolved = node_map.get(node_id)
    if resolved is None:
        raise RuntimeError(
            f"Could not resolve node reference '{node_id}' in cube "
            f"'{cube.get('__template__') or cube.get('cube_id')}' for alias '{alias}'."
        )
    return resolved


def _require_nodes(cube: CubeGraph) -> dict[str, dict[str, Any]]:
    """Return a materialized cube node map or fail closed."""

    nodes = cube.get("nodes")
    if not isinstance(nodes, dict):
        raise RuntimeError("Materialized cube graph is missing a nodes mapping.")
    return nodes


def _require_mapping(cube: CubeGraph, key: str) -> dict[str, Any]:
    """Return a required mapping from a mutable cube graph."""

    value = cube.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Materialized cube graph is missing '{key}' mapping.")
    return value
