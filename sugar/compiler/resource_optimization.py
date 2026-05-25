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
"""Optimize execution-only Sugar graphs before Comfy API prompt lowering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any, TypeAlias, cast

from .graph import CubeGraph
from .ir import NodeLinkEntry
from .links import is_comfy_node_link

logger = logging.getLogger(__name__)

HashableJson: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | tuple["HashableJson", ...]
    | tuple[tuple[str, "HashableJson"], ...]
)
NodeSignature: TypeAlias = tuple[Any, ...]

_PROMPT_PROVIDER_CLASSES = frozenset({"PrimitiveString", "PrimitiveStringMultiline"})
_ALLOWLISTED_PURE_CLASSES = frozenset({"PrimitiveString", "PrimitiveStringMultiline"})


@dataclass(frozen=True)
class _NodeLocation:
    """Identify one materialized node in one execution graph."""

    alias: str
    graph: CubeGraph
    node_key: str
    node: dict[str, Any]


def optimize_execution_resources(
    graphs: Sequence[CubeGraph],
    *,
    order: Sequence[str],
    node_links: Sequence[NodeLinkEntry],
) -> None:
    """Deduplicate provably equivalent execution resources in-place.

    This optimizer runs only on materialized execution graphs. UI graphs keep the
    authored SugarCube shape so image-attached workflows remain readable.
    """

    _rewire_prompt_identity_links(graphs, node_links)
    _intern_allowlisted_pure_nodes(graphs, order)


def _rewire_prompt_identity_links(
    graphs: Sequence[CubeGraph],
    node_links: Sequence[NodeLinkEntry],
) -> None:
    """Redirect prompt-node consumers according to explicit DSL identity links."""

    for entry in node_links:
        source_key = _node_link_key(entry, "from")
        target_key = _node_link_key(entry, "to")
        if source_key is None or target_key is None or source_key == target_key:
            continue
        source_location = _find_node(graphs, source_key)
        target_location = _find_node(graphs, target_key)
        if source_location is None or target_location is None:
            continue
        source_class = source_location.node.get("class_type")
        target_class = target_location.node.get("class_type")
        if (
            source_class not in _PROMPT_PROVIDER_CLASSES
            or target_class not in _PROMPT_PROVIDER_CLASSES
            or source_class != target_class
        ):
            _log_skip(
                kind="prompt_identity",
                alias=target_location.alias,
                source_node_key=source_key,
                duplicate_node_key=target_key,
                class_type=str(target_class),
                reason="node class is not a safe prompt provider",
            )
            continue
        replacements = _replace_node_links(
            graphs,
            duplicate_node_key=target_key,
            canonical_node_key=source_key,
        )
        removed = _remove_node_if_unreferenced(
            target_location.graph,
            target_key,
            graphs,
        )
        logger.debug(
            "Optimized execution prompt identity.",
            extra={
                "operation": "optimize_execution_resources",
                "optimization_kind": "prompt_identity",
                "cube_alias": target_location.alias,
                "source_node_key": source_key,
                "duplicate_node_key": target_key,
                "class_type": source_class,
                "replacement_count": replacements,
                "removed_duplicate": removed,
            },
        )


def _intern_allowlisted_pure_nodes(
    graphs: Sequence[CubeGraph],
    order: Sequence[str],
) -> None:
    """Intern allowlisted exact pure primitive prompt nodes."""

    canonical_by_signature: dict[NodeSignature, str] = {}
    for location in list(_iter_nodes(graphs, order)):
        if _find_node(graphs, location.node_key) is None:
            continue
        signature = _signature_for_node_key(graphs, location.node_key)
        if signature is None:
            continue
        canonical_key = canonical_by_signature.get(signature)
        if canonical_key is None or _find_node(graphs, canonical_key) is None:
            canonical_by_signature[signature] = location.node_key
            continue
        replacements = _replace_node_links(
            graphs,
            duplicate_node_key=location.node_key,
            canonical_node_key=canonical_key,
        )
        removed = _remove_node_if_unreferenced(location.graph, location.node_key, graphs)
        logger.debug(
            "Interned duplicate execution node.",
            extra={
                "operation": "optimize_execution_resources",
                "optimization_kind": _optimization_kind(location.node),
                "cube_alias": location.alias,
                "source_node_key": canonical_key,
                "duplicate_node_key": location.node_key,
                "class_type": location.node.get("class_type"),
                "signature_hash": _short_signature_hash(signature),
                "replacement_count": replacements,
                "removed_duplicate": removed,
            },
        )


def _signature_for_node_key(
    graphs: Sequence[CubeGraph],
    node_key: str,
) -> NodeSignature | None:
    """Return a stable signature for one node if its class is safe to intern."""

    return _signature_for_node_key_inner(graphs, node_key, memo={}, visiting=set())


def _signature_for_node_key_inner(
    graphs: Sequence[CubeGraph],
    node_key: str,
    *,
    memo: dict[str, NodeSignature | None],
    visiting: set[str],
) -> NodeSignature | None:
    """Build one recursive node signature with cycle protection."""

    if node_key in memo:
        return memo[node_key]
    if node_key in visiting:
        return None
    location = _find_node(graphs, node_key)
    if location is None:
        memo[node_key] = None
        return None
    class_type = location.node.get("class_type")
    if class_type not in _ALLOWLISTED_PURE_CLASSES or not isinstance(class_type, str):
        memo[node_key] = None
        return None

    visiting.add(node_key)
    inputs = _node_inputs(location.node)
    literal_inputs = _literal_input_signature(
        graphs=graphs,
        class_type=class_type,
        inputs=inputs,
    )
    if literal_inputs is None:
        visiting.remove(node_key)
        memo[node_key] = None
        return None
    linked_inputs = _linked_input_signature(
        graphs=graphs,
        class_type=class_type,
        inputs=inputs,
        memo=memo,
        visiting=visiting,
    )
    visiting.remove(node_key)
    signature: NodeSignature = (
        "node",
        class_type,
        ("enabled", _freeze_json(location.node.get("enabled"))),
        ("outputs", _output_slot_count(location.graph, location.node)),
        ("literals", literal_inputs),
        ("links", linked_inputs),
    )
    memo[node_key] = signature
    return signature


def _literal_input_signature(
    *,
    graphs: Sequence[CubeGraph],
    class_type: str,
    inputs: Mapping[str, Any],
) -> tuple[tuple[str, HashableJson], ...] | None:
    """Return normalized literal inputs or ``None`` when a node must not intern."""

    signature: list[tuple[str, HashableJson]] = []
    for input_name, value in inputs.items():
        if is_comfy_node_link(value):
            continue
        signature.append((input_name, _freeze_json(value)))

    _ = (graphs, class_type)
    return tuple(sorted(signature, key=lambda item: item[0]))


def _linked_input_signature(
    *,
    graphs: Sequence[CubeGraph],
    class_type: str,
    inputs: Mapping[str, Any],
    memo: dict[str, NodeSignature | None],
    visiting: set[str],
) -> tuple[tuple[str, tuple[str, Any, int]], ...]:
    """Return link signatures using upstream signatures when available."""

    signature: list[tuple[str, tuple[str, Any, int]]] = []
    for input_name, value in inputs.items():
        if not is_comfy_node_link(value):
            continue
        source_node_key, source_slot = cast(tuple[str, int], tuple(value))
        upstream_signature = _signature_for_node_key_inner(
            graphs,
            source_node_key,
            memo=memo,
            visiting=visiting,
        )
        if upstream_signature is None:
            signature.append((input_name, ("identity", source_node_key, source_slot)))
        else:
            signature.append((input_name, ("signature", upstream_signature, source_slot)))
    return tuple(sorted(signature, key=lambda item: item[0]))


def _replace_node_links(
    graphs: Sequence[CubeGraph],
    *,
    duplicate_node_key: str,
    canonical_node_key: str,
) -> int:
    """Replace all links to one duplicate node with the canonical node key."""

    replacement_count = 0
    for location in _iter_nodes(graphs, ()):
        inputs = _node_inputs(location.node)
        for input_name, value in list(inputs.items()):
            if not is_comfy_node_link(value) or value[0] != duplicate_node_key:
                continue
            inputs[input_name] = [canonical_node_key, value[1]]
            replacement_count += 1
    return replacement_count


def _remove_node_if_unreferenced(
    graph: CubeGraph,
    node_key: str,
    graphs: Sequence[CubeGraph],
) -> bool:
    """Remove a node when no execution input still references it."""

    if _has_remaining_references(graphs, node_key):
        return False
    nodes = graph.get("nodes")
    if not isinstance(nodes, dict) or node_key not in nodes:
        return False
    del nodes[node_key]
    return True


def _has_remaining_references(graphs: Sequence[CubeGraph], node_key: str) -> bool:
    """Return whether any execution node input still references one node key."""

    for location in _iter_nodes(graphs, ()):
        for value in _node_inputs(location.node).values():
            if is_comfy_node_link(value) and value[0] == node_key:
                return True
    return False


def _iter_nodes(
    graphs: Sequence[CubeGraph],
    order: Sequence[str],
) -> list[_NodeLocation]:
    """Return materialized nodes in deterministic graph and insertion order."""

    locations: list[_NodeLocation] = []
    for index, graph in enumerate(graphs):
        alias = order[index] if index < len(order) else ""
        nodes = graph.get("nodes")
        if not isinstance(nodes, dict):
            continue
        for node_key, node in nodes.items():
            if isinstance(node_key, str) and isinstance(node, dict):
                locations.append(
                    _NodeLocation(
                        alias=alias,
                        graph=graph,
                        node_key=node_key,
                        node=node,
                    )
                )
    return locations


def _find_node(graphs: Sequence[CubeGraph], node_key: str) -> _NodeLocation | None:
    """Find one materialized node by globally unique node key."""

    for location in _iter_nodes(graphs, ()):
        if location.node_key == node_key:
            return location
    return None


def _node_link_key(entry: NodeLinkEntry, side: str) -> str | None:
    """Return the materialized key stored in one node-link endpoint."""

    metadata = entry.get("metadata", {})
    if isinstance(metadata, Mapping):
        metadata_key = metadata.get(f"{side}_node_key")
        if isinstance(metadata_key, str) and metadata_key:
            return metadata_key
    if side == "from":
        endpoint = entry.get("from", {})
    elif side == "to":
        endpoint = entry.get("to", {})
    else:
        return None
    if not isinstance(endpoint, Mapping):
        return None
    alias = endpoint.get("alias")
    node = endpoint.get("node")
    if isinstance(alias, str) and alias and isinstance(node, str) and node:
        return f"{alias}.{node}"
    return None


def _node_inputs(node: dict[str, Any]) -> dict[str, Any]:
    """Return a node's mutable input mapping."""

    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        raise RuntimeError("Materialized execution node has invalid inputs.")
    return inputs


def _output_slot_count(graph: CubeGraph, node: Mapping[str, Any]) -> int:
    """Return the declared output slot count for one node."""

    class_type = node.get("class_type")
    if not isinstance(class_type, str):
        return 0
    for subgraph in _list_payload(graph.get("subgraphs")):
        if subgraph.get("id") == class_type:
            outputs = subgraph.get("outputs")
            return len(outputs) if isinstance(outputs, list) else 0
    definitions = graph.get("definitions")
    if not isinstance(definitions, Mapping):
        return 0
    definition = definitions.get(class_type)
    if not isinstance(definition, Mapping):
        return 0
    output_types = _string_sequence(definition.get("output"))
    output_names = _string_sequence(definition.get("output_name"))
    return max(len(output_types), len(output_names))


def _freeze_json(value: Any) -> HashableJson:
    """Convert JSON-like values and dataclasses into hashable signature values."""

    if hasattr(value, "__dataclass_fields__"):
        return _freeze_json(value.__dict__)
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze_json(item_value)) for key, item_value in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _string_sequence(value: Any) -> tuple[str, ...]:
    """Return a tuple of strings from a dynamic sequence payload."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _list_payload(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Return mapping items from a dynamic list payload."""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _short_signature_hash(signature: NodeSignature) -> str:
    """Return a stable short hash for debug diagnostics."""

    digest = hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()
    return digest[:12]


def _optimization_kind(node: Mapping[str, Any]) -> str:
    """Return the debug optimization kind for one interned node."""

    _ = node
    return "pure_node_intern"


def _log_skip(
    *,
    kind: str,
    alias: str,
    source_node_key: str,
    duplicate_node_key: str,
    class_type: str,
    reason: str,
) -> None:
    """Emit low-noise debug context for a skipped optimization."""

    logger.debug(
        "Skipped execution resource optimization.",
        extra={
            "operation": "optimize_execution_resources",
            "optimization_kind": kind,
            "cube_alias": alias,
            "source_node_key": source_node_key,
            "duplicate_node_key": duplicate_node_key,
            "class_type": class_type,
            "skip_reason": reason,
        },
    )


__all__ = ["optimize_execution_resources"]
