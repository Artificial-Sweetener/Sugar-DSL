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
"""Resolve model, CLIP, and VAE inheritance from live provider outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from .graph import CubeGraph, CubeGraphByAlias

InheritanceSlot: TypeAlias = Literal["model", "clip", "vae"]
ProviderMap: TypeAlias = dict[InheritanceSlot, list["ProviderLink"]]
INHERITABLE_PROVIDER_INPUTS = frozenset({"model", "clip", "vae"})
_INHERITABLE_OUTPUT_TYPES: dict[str, InheritanceSlot] = {
    "model": "model",
    "clip": "clip",
    "vae": "vae",
}
_EMPTY_INPUT_VALUES: tuple[object, ...] = (None, "", [], {})


@dataclass(frozen=True)
class ProviderLink:
    """Identify one live provider output that can satisfy inheritance."""

    slot: InheritanceSlot
    node_key: str
    output_index: int

    def as_comfy_link(self) -> list[Any]:
        """Return this provider in ComfyUI link format."""

        return [self.node_key, self.output_index]


def is_inheritable_provider_input(input_name: str) -> bool:
    """Return whether an input participates in provider inheritance."""

    return input_name.lower() in INHERITABLE_PROVIDER_INPUTS


def infer_inheritance_key(node_key: str, input_key: str) -> InheritanceSlot | None:
    """Infer the inheritance slot represented by a node/input name pair."""

    tokens = []
    if input_key:
        tokens.append(input_key.lower())
    if node_key:
        tokens.append(node_key.lower())
    for token in tokens:
        if "model" in token:
            return "model"
    for token in tokens:
        if "clip" in token:
            return "clip"
    for token in tokens:
        if "vae" in token:
            return "vae"
    return None


def output_slot_type(
    cube: CubeGraph, node: Mapping[str, Any], output_index: int
) -> InheritanceSlot | str | None:
    """Return the declared output type for one node output slot."""

    class_type = node.get("class_type")
    if not isinstance(class_type, str) or output_index < 0:
        return None

    subgraph_type = _subgraph_output_slot_type(cube, class_type, output_index)
    if subgraph_type is not None:
        return subgraph_type

    definition = _definition_for_class(cube, class_type)
    output_types = _string_sequence(definition.get("output"))
    if output_index < len(output_types):
        return _normalize_output_type(output_types[output_index])

    output_names = _string_sequence(definition.get("output_name"))
    if output_index < len(output_names):
        return _normalize_output_type(output_names[output_index])

    return None


def live_output_usage(cube: CubeGraph, disabled_nodes: set[str]) -> set[tuple[str, int]]:
    """Return provider outputs that are effectively consumed inside a cube."""

    nodes = _node_map(cube)
    transparent_nodes = _transparent_selector_nodes(cube, disabled_nodes)
    used: set[tuple[str, int]] = set()

    for node_key, node in nodes.items():
        if node_key in disabled_nodes:
            continue
        inputs = _input_map(node)
        for input_name, value in inputs.items():
            source = _comfy_link_or_none(value)
            if source is None:
                continue
            source_node_key, source_output_index = source
            if not _source_node_is_live(nodes, disabled_nodes, source_node_key):
                continue
            if node_key in transparent_nodes:
                continue
            used.add((source_node_key, source_output_index))

            input_slot = _input_slot_type(cube, node, input_name)
            if input_slot is None:
                continue
            selected_provider = _resolve_provider_source(
                cube,
                source_node_key,
                source_output_index,
                input_slot,
                disabled_nodes,
                seen=set(),
            )
            if selected_provider is not None:
                used.add((selected_provider.node_key, selected_provider.output_index))

    return used


def discover_live_providers(cube: CubeGraph, disabled_nodes: set[str]) -> ProviderMap:
    """Return live origin provider outputs grouped by inheritance slot."""

    providers: ProviderMap = {"model": [], "clip": [], "vae": []}
    usage = live_output_usage(cube, disabled_nodes)
    nodes = _node_map(cube)
    for node_key in topo_sort_nodes(cube):
        if node_key in disabled_nodes:
            continue
        node = nodes.get(node_key)
        if node is None:
            continue
        for output_index in range(_output_slot_count(cube, node)):
            slot_type = output_slot_type(cube, node, output_index)
            slot = _inheritable_slot_or_none(slot_type)
            if slot is None:
                continue
            if (node_key, output_index) not in usage:
                continue
            if not _provider_output_is_inheritance_origin(
                cube,
                nodes,
                node,
                output_index,
                slot,
                disabled_nodes,
            ):
                continue
            providers[slot].append(
                ProviderLink(slot=slot, node_key=node_key, output_index=output_index)
            )
    return providers


def topo_sort_nodes(cube: CubeGraph) -> list[str]:
    """Return nodes in dependency order while preserving original order ties."""

    nodes = _node_map(cube)
    order = list(nodes.keys())
    index_map = {key: idx for idx, key in enumerate(order)}
    deps: dict[str, set[str]] = {key: set() for key in order}
    dependents: dict[str, set[str]] = {key: set() for key in order}
    for node_key, node in nodes.items():
        for val in _input_map(node).values():
            source = _comfy_link_or_none(val)
            if source is None:
                continue
            target = source[0]
            if target in nodes:
                deps[node_key].add(target)
                dependents[target].add(node_key)
    in_degree = {key: len(deps[key]) for key in order}
    ready = sorted(
        [key for key, degree in in_degree.items() if degree == 0],
        key=lambda key: index_map[key],
    )
    result = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for child in sorted(dependents[current], key=lambda key: index_map[key]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                ready.append(child)
                ready.sort(key=lambda key: index_map[key])
    if len(result) != len(order):
        result.extend(key for key in order if key not in result)
    return result


def apply_inheritance(
    cubes: CubeGraphByAlias,
    order: list[str],
    disabled_nodes: set[str],
    on_set: Callable[[str, str, str, Any], None] | None = None,
) -> None:
    """Fill missing model, CLIP, and VAE inputs from prior live providers."""

    providers_by_alias = {
        alias: discover_live_providers(cubes[alias], disabled_nodes) for alias in order
    }
    for cube_index, cube_name in enumerate(order):
        cube = cubes[cube_name]
        nodes = _node_map(cube)
        for node_key in topo_sort_nodes(cube):
            if node_key in disabled_nodes:
                continue
            node = nodes.get(node_key)
            if node is None:
                continue
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for input_key, value in list(inputs.items()):
                if value not in _EMPTY_INPUT_VALUES:
                    continue
                inherit_type = _inheritance_slot_for_input(node_key, input_key)
                if inherit_type is None:
                    continue
                provider = _find_nearest_provider(
                    providers_by_alias,
                    order,
                    cube_index,
                    inherit_type,
                )
                if provider is None:
                    continue
                comfy_link = provider.as_comfy_link()
                inputs[input_key] = comfy_link
                if on_set:
                    on_set(cube_name, node_key, input_key, comfy_link)


def _find_nearest_provider(
    providers_by_alias: Mapping[str, ProviderMap],
    order: Sequence[str],
    cube_index: int,
    slot: InheritanceSlot,
) -> ProviderLink | None:
    """Return the nearest previous live provider for one inheritance slot."""

    for previous_index in range(cube_index - 1, -1, -1):
        providers = providers_by_alias[order[previous_index]][slot]
        if providers:
            return providers[0]
    return None


def _inheritance_slot_for_input(node_key: str, input_key: str) -> InheritanceSlot | None:
    """Return the inheritance slot represented by one fillable input."""

    normalized = input_key.lower()
    direct_slot = _inheritable_slot_or_none(normalized)
    if direct_slot is not None:
        return direct_slot
    if normalized.endswith("_in"):
        wrapper_slot = _inheritable_slot_or_none(normalized[:-3])
        if wrapper_slot is not None:
            return wrapper_slot
    return infer_inheritance_key(node_key, input_key)


def _transparent_selector_nodes(cube: CubeGraph, disabled_nodes: set[str]) -> set[str]:
    """Return wildcard nodes whose outputs feed inheritable object inputs."""

    nodes = _node_map(cube)
    transparent_nodes: set[str] = set()
    for node_key, node in nodes.items():
        if node_key in disabled_nodes:
            continue
        for input_name, value in _input_map(node).items():
            if _input_slot_type(cube, node, input_name) is None:
                continue
            source = _comfy_link_or_none(value)
            if source is None:
                continue
            source_node = nodes.get(source[0])
            if source_node is None:
                continue
            if _source_output_is_transparent(cube, source_node, source[1]):
                transparent_nodes.add(source[0])
    return transparent_nodes


def _resolve_provider_source(
    cube: CubeGraph,
    node_key: str,
    output_index: int,
    slot: InheritanceSlot,
    disabled_nodes: set[str],
    seen: set[tuple[str, int]],
) -> ProviderLink | None:
    """Trace transparent selector outputs to their selected origin provider."""

    nodes = _node_map(cube)
    if not _source_node_is_live(nodes, disabled_nodes, node_key):
        return None
    if (node_key, output_index) in seen:
        return None
    seen.add((node_key, output_index))

    node = nodes[node_key]
    source_slot = _inheritable_slot_or_none(output_slot_type(cube, node, output_index))
    if source_slot == slot and _provider_output_is_inheritance_origin(
        cube,
        nodes,
        node,
        output_index,
        slot,
        disabled_nodes,
    ):
        return ProviderLink(slot=slot, node_key=node_key, output_index=output_index)
    if not _source_output_is_transparent(cube, node, output_index):
        return None

    provider_candidates = [
        provider
        for _, provider in _ordered_input_providers(
            cube,
            node,
            slot,
            disabled_nodes,
            seen,
        )
    ]
    if not provider_candidates:
        return None
    if _has_selector_like_inputs(node):
        return provider_candidates[0]
    if len(provider_candidates) == 1:
        return provider_candidates[0]
    return None


def _ordered_input_providers(
    cube: CubeGraph,
    node: Mapping[str, Any],
    slot: InheritanceSlot,
    disabled_nodes: set[str],
    seen: set[tuple[str, int]],
) -> list[tuple[str, ProviderLink]]:
    """Return linked provider inputs in authored input order."""

    providers: list[tuple[str, ProviderLink]] = []
    for input_name, value in _input_map(node).items():
        source = _comfy_link_or_none(value)
        if source is None:
            continue
        provider = _resolve_provider_source(
            cube,
            source[0],
            source[1],
            slot,
            disabled_nodes,
            seen=set(seen),
        )
        if provider is not None:
            providers.append((input_name, provider))
    return providers


def _source_output_is_transparent(
    cube: CubeGraph, node: Mapping[str, Any], output_index: int
) -> bool:
    """Return whether an output should be traced through as a selector."""

    output_type = output_slot_type(cube, node, output_index)
    return output_type in (None, "*")


def _has_selector_like_inputs(node: Mapping[str, Any]) -> bool:
    """Return whether node inputs look like ordered selector candidates."""

    linked_names = [
        input_name
        for input_name, value in _input_map(node).items()
        if _comfy_link_or_none(value) is not None
    ]
    if not linked_names:
        return False
    return all(_is_selector_input_name(input_name) for input_name in linked_names)


def _is_selector_input_name(input_name: str) -> bool:
    """Return whether an input name encodes ordered selector priority."""

    normalized = input_name.lower()
    if normalized.isdigit():
        return True
    if normalized.startswith("any_"):
        suffix = normalized.removeprefix("any_")
        return suffix.isdigit()
    return False


def _provider_output_has_required_source(
    nodes: Mapping[str, Mapping[str, Any]],
    node: Mapping[str, Any],
    slot: InheritanceSlot,
    disabled_nodes: set[str],
) -> bool:
    """Return whether wrapper-like provider outputs have a live slot input."""

    inputs = _input_map(node)
    candidate_keys = (slot, f"{slot}_in")
    present_values = [inputs[key] for key in candidate_keys if key in inputs]
    if not present_values:
        return True
    return any(
        _input_value_can_supply_provider(nodes, value, disabled_nodes) for value in present_values
    )


def _provider_output_is_inheritance_origin(
    cube: CubeGraph,
    nodes: Mapping[str, Mapping[str, Any]],
    node: Mapping[str, Any],
    output_index: int,
    slot: InheritanceSlot,
    disabled_nodes: set[str],
) -> bool:
    """Return whether an output is a live root provider for inheritance.

    Derived resource transforms also produce ``MODEL``, ``CLIP``, or ``VAE``
    outputs, but inheriting from them stacks downstream cubes on an already
    transformed resource. Inheritance follows provider origins instead.
    """

    if not _provider_output_has_required_source(nodes, node, slot, disabled_nodes):
        return False
    return not _output_derives_from_inheritable_input(cube, node, output_index)


def _output_derives_from_inheritable_input(
    cube: CubeGraph,
    node: Mapping[str, Any],
    output_index: int,
) -> bool:
    """Return whether an inheritable output is derived from resource inputs."""

    if _inheritable_slot_or_none(output_slot_type(cube, node, output_index)) is None:
        return False
    for input_name, value in _input_map(node).items():
        if _comfy_link_or_none(value) is None:
            continue
        if _input_slot_type(cube, node, input_name) is not None:
            return True
    return False


def _input_value_can_supply_provider(
    nodes: Mapping[str, Mapping[str, Any]], value: Any, disabled_nodes: set[str]
) -> bool:
    """Return whether an input value can supply object data to an output."""

    if value is None:
        return False
    source = _comfy_link_or_none(value)
    if source is None:
        return True
    return _source_node_is_live(nodes, disabled_nodes, source[0])


def _input_slot_type(
    cube: CubeGraph, node: Mapping[str, Any], input_name: str
) -> InheritanceSlot | None:
    """Return the inheritable slot expected by one node input."""

    class_type = node.get("class_type")
    if isinstance(class_type, str):
        subgraph_type = _subgraph_input_slot_type(cube, class_type, input_name)
        if subgraph_type is not None:
            return subgraph_type
        definition = _definition_for_class(cube, class_type)
        field_type = _definition_input_field_type(definition, input_name)
        if field_type is not None:
            slot = _inheritable_slot_or_none(field_type)
            if slot is not None:
                return slot
    return _inheritance_slot_for_input("", input_name)


def _subgraph_output_slot_type(
    cube: CubeGraph, class_type: str, output_index: int
) -> InheritanceSlot | str | None:
    """Return one subgraph wrapper output type."""

    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is None:
        return None
    outputs = subgraph.get("outputs")
    if not isinstance(outputs, list) or output_index >= len(outputs):
        return None
    output = outputs[output_index]
    if not isinstance(output, Mapping):
        return None
    output_type = output.get("type")
    if not isinstance(output_type, str):
        return None
    return _normalize_output_type(output_type)


def _subgraph_input_slot_type(
    cube: CubeGraph, class_type: str, input_name: str
) -> InheritanceSlot | None:
    """Return one subgraph wrapper input's inheritable type."""

    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is None:
        return None
    inputs = subgraph.get("inputs")
    if not isinstance(inputs, list):
        return None
    for input_entry in inputs:
        if not isinstance(input_entry, Mapping):
            continue
        if input_entry.get("name") != input_name:
            continue
        input_type = input_entry.get("type")
        if isinstance(input_type, str):
            return _inheritable_slot_or_none(input_type)
    return None


def _definition_input_field_type(definition: Mapping[str, Any], input_name: str) -> str | None:
    """Return a definition input field's declared type."""

    input_payload = definition.get("input")
    if not isinstance(input_payload, Mapping):
        return None
    for section_name in ("required", "optional", "hidden"):
        section = input_payload.get(section_name)
        if not isinstance(section, Mapping) or input_name not in section:
            continue
        return _field_spec_type(section[input_name])
    return None


def _field_spec_type(field_spec: Any) -> str | None:
    """Return a compact Comfy field spec's declared type."""

    if isinstance(field_spec, str):
        return field_spec
    if (
        isinstance(field_spec, Sequence)
        and not isinstance(field_spec, (str, bytes))
        and field_spec
        and isinstance(field_spec[0], str)
    ):
        return field_spec[0]
    return None


def _output_slot_count(cube: CubeGraph, node: Mapping[str, Any]) -> int:
    """Return the number of declared output slots for one node."""

    class_type = node.get("class_type")
    if not isinstance(class_type, str):
        return 0
    subgraph = _subgraph_by_id(cube, class_type)
    if subgraph is not None:
        outputs = subgraph.get("outputs")
        if isinstance(outputs, list):
            return len(outputs)

    definition = _definition_for_class(cube, class_type)
    output_types = _string_sequence(definition.get("output"))
    output_names = _string_sequence(definition.get("output_name"))
    return max(len(output_types), len(output_names))


def _definition_for_class(cube: CubeGraph, class_type: str) -> Mapping[str, Any]:
    """Return definition metadata for one class type."""

    definitions = cube.get("definitions")
    if not isinstance(definitions, Mapping):
        return {}
    definition = definitions.get(class_type)
    if not isinstance(definition, Mapping):
        return {}
    return definition


def _subgraph_by_id(cube: CubeGraph, class_type: str) -> Mapping[str, Any] | None:
    """Return subgraph metadata for one wrapper class type."""

    subgraphs = cube.get("subgraphs")
    if not isinstance(subgraphs, list):
        return None
    for subgraph in subgraphs:
        if isinstance(subgraph, Mapping) and subgraph.get("id") == class_type:
            return subgraph
    return None


def _normalize_output_type(value: str) -> InheritanceSlot | str | None:
    """Normalize a declared Comfy output type."""

    normalized = value.strip().lower()
    if not normalized:
        return None
    return _INHERITABLE_OUTPUT_TYPES.get(normalized, value.strip())


def _inheritable_slot_or_none(value: object) -> InheritanceSlot | None:
    """Return an inheritance slot for a normalized object type."""

    if not isinstance(value, str):
        return None
    return _INHERITABLE_OUTPUT_TYPES.get(value.strip().lower())


def _node_map(cube: CubeGraph) -> dict[str, dict[str, Any]]:
    """Return a cube's node mapping when it is well-formed."""

    nodes = cube.get("nodes")
    if not isinstance(nodes, Mapping):
        return {}
    return {
        str(key): value
        for key, value in nodes.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _input_map(node: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return one node's input mapping when it is well-formed."""

    inputs = node.get("inputs")
    if not isinstance(inputs, Mapping):
        return {}
    return {str(key): value for key, value in inputs.items() if isinstance(key, str)}


def _string_sequence(value: Any) -> list[str]:
    """Return string items from a JSON sequence."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str)]


def _comfy_link_or_none(value: Any) -> tuple[str, int] | None:
    """Return a ComfyUI link when a value has valid link shape."""

    if (
        not isinstance(value, list)
        or len(value) < 2
        or not isinstance(value[0], str)
        or value[0] == "EXTERNAL_INPUT"
        or not isinstance(value[1], int)
        or isinstance(value[1], bool)
    ):
        return None
    return value[0], value[1]


def _source_node_is_live(
    nodes: Mapping[str, Mapping[str, Any]], disabled_nodes: set[str], node_key: str
) -> bool:
    """Return whether a linked source node can execute inside this cube."""

    return node_key in nodes and node_key not in disabled_nodes
