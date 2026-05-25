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
"""Materialize schema-backed node inputs before Comfy API prompt lowering."""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, MutableMapping
import logging
from typing import cast

from ..shared.seed import SeedProvider
from .errors import SugarCompilerError
from .graph import CubeGraph
from .live_definitions import LiveNodeDefinitionProvider, LiveNodeInputDefinition

logger = logging.getLogger(__name__)

_MISSING = object()
_ACTIONABLE_WIDGET_TYPES = frozenset({"BOOLEAN", "BOOL", "FLOAT", "INT", "STRING", "COMBO"})


def materialize_node_inputs(
    cube: CubeGraph,
    *,
    seed_provider: SeedProvider,
    live_node_definition_provider: LiveNodeDefinitionProvider | None = None,
    cube_alias: str | None = None,
    cube_id: str | None = None,
) -> None:
    """Fill safe schema-backed inputs on one materialized cube graph."""

    nodes = _mapping_or_none(cube.get("nodes"))
    if nodes is None:
        raise RuntimeError("Materialized cube graph is missing a nodes mapping.")
    definitions = _mapping_or_none(cube.get("definitions"))

    for node_key, node_payload in nodes.items():
        if not isinstance(node_key, str):
            raise RuntimeError("Materialized cube graph has a non-string node key.")
        node = _mutable_mapping_or_none(node_payload)
        if node is None:
            raise RuntimeError(f"Materialized node '{node_key}' must be an object.")
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue
        inputs = _node_inputs(node, node_key)
        if definitions is not None:
            definition = _string_mapping_or_none(definitions.get(class_type))
            if definition is not None:
                _materialize_definition_inputs(
                    inputs,
                    node_key=node_key,
                    definition=definition,
                    seed_provider=seed_provider,
                )
        if live_node_definition_provider is not None:
            _materialize_live_inputs(
                inputs,
                node_key=node_key,
                class_type=class_type,
                cube_alias=cube_alias,
                cube_id=cube_id,
                live_node_definition_provider=live_node_definition_provider,
                seed_provider=seed_provider,
            )


def _materialize_definition_inputs(
    inputs: MutableMapping[object, object],
    *,
    node_key: str,
    definition: Mapping[str, object],
    seed_provider: SeedProvider,
) -> None:
    """Apply safe defaults from cube-embedded node definitions."""

    for input_name, field_spec in iter_definition_input_fields(definition):
        if input_name in inputs and inputs[input_name] is not None:
            continue
        materialized = _materialized_input_value(
            node_key=node_key,
            input_name=input_name,
            field_spec=field_spec,
            seed_provider=seed_provider,
        )
        if materialized is not _MISSING:
            inputs[input_name] = materialized


def _materialize_live_inputs(
    inputs: MutableMapping[object, object],
    *,
    node_key: str,
    class_type: str,
    cube_alias: str | None,
    cube_id: str | None,
    live_node_definition_provider: LiveNodeDefinitionProvider,
    seed_provider: SeedProvider,
) -> None:
    """Apply safe defaults from host-supplied live Comfy definitions."""

    try:
        live_definition = live_node_definition_provider.definition_for(class_type)
    except Exception as exc:
        logger.error(
            "Live node definition provider failed during input materialization.",
            extra={
                "operation": "materialize_live_inputs",
                "cube_alias": cube_alias or "",
                "cube_id": cube_id or "",
                "node_key": node_key,
                "node_class_type": class_type,
                "error": str(exc),
            },
        )
        raise SugarCompilerError(
            f"Live definition lookup failed for node class '{class_type}': {exc}",
            code="sugar-live-definition-missing",
            cube_alias=cube_alias,
            cube_id=cube_id,
            node_key=node_key,
            node_class_type=class_type,
        ) from exc
    if live_definition is None:
        return
    for input_name, live_input in live_definition.inputs.items():
        if input_name in inputs and inputs[input_name] is not None:
            continue
        field_spec = field_spec_from_live_input(live_input)
        materialized = _materialized_input_value(
            node_key=node_key,
            input_name=input_name,
            field_spec=field_spec,
            seed_provider=seed_provider,
        )
        if materialized is not _MISSING:
            inputs[input_name] = materialized
            continue
        if live_input.required and _should_fail_missing_live_input(node_key, live_input):
            raise SugarCompilerError(
                "Required live input has no authored value, script override, "
                f"or Comfy default: {node_key}.{input_name}",
                code="sugar-live-default-missing",
                cube_alias=cube_alias,
                cube_id=cube_id,
                node_key=node_key,
                node_class_type=class_type,
                input_name=input_name,
            )
        if live_input.required:
            logger.debug(
                "Required live input was omitted because Sugar cannot safely materialize it.",
                extra={
                    "operation": "omit_unmaterialized_live_input",
                    "cube_alias": cube_alias or "",
                    "cube_id": cube_id or "",
                    "node_key": node_key,
                    "node_class_type": class_type,
                    "input_name": input_name,
                    "input_type": live_input.value_type,
                },
            )


def _should_fail_missing_live_input(
    node_key: str,
    live_input: LiveNodeInputDefinition,
) -> bool:
    """Return whether a missing required live input should block compilation.

    Missing scalar widgets on public cube nodes are actionable because users can
    author or override them. Expanded subgraph internals and graph socket types
    are not safe to synthesize from live metadata alone, so Sugar omits them
    instead of forcing invisible helper inputs into old cubes.
    """

    if _is_expanded_subgraph_internal_node(node_key):
        return False
    return _is_actionable_widget_input(live_input)


def _is_expanded_subgraph_internal_node(node_key: str) -> bool:
    """Return whether ``node_key`` identifies a generated subgraph body node."""

    return ".__sg_" in node_key


def _is_actionable_widget_input(live_input: LiveNodeInputDefinition) -> bool:
    """Return whether a required live input represents a literal widget field."""

    if live_input.choices:
        return True
    return live_input.value_type.upper() in _ACTIONABLE_WIDGET_TYPES


def field_spec_from_live_input(live_input: LiveNodeInputDefinition) -> object:
    """Normalize live input metadata to the compact field-spec parser shape."""

    metadata = dict(live_input.raw)
    if live_input.has_default:
        metadata["default"] = copy.deepcopy(live_input.default)
    if live_input.choices:
        return [list(live_input.choices), metadata]
    return [live_input.value_type, metadata]


def iter_definition_input_fields(
    definition: Mapping[str, object],
) -> Iterator[tuple[str, object]]:
    """Yield required and optional input fields in definition order."""

    input_definition = _string_mapping_or_none(definition.get("input"))
    if input_definition is None:
        return
    for section_name in ("required", "optional"):
        fields = _string_mapping_or_none(input_definition.get(section_name))
        if fields is None:
            continue
        for input_name, field_spec in fields.items():
            if isinstance(input_name, str) and input_name:
                yield input_name, field_spec


def input_type_name(field_spec: object) -> str | None:
    """Return the scalar Comfy input type declared by one field spec."""

    if isinstance(field_spec, str):
        return field_spec
    if isinstance(field_spec, list) and field_spec:
        field_type = field_spec[0]
        if isinstance(field_type, str):
            return field_type
    return None


def default_from_field_spec(field_spec: object) -> object:
    """Return the declared field default or a sentinel when no default exists."""

    metadata = _field_metadata(field_spec)
    if metadata is None or "default" not in metadata:
        return _MISSING
    return copy.deepcopy(metadata["default"])


def is_randomizable_seed_input(input_name: str, field_spec: object) -> bool:
    """Return whether one field should receive a generated Comfy seed."""

    return input_name == "seed" and input_type_name(field_spec) == "INT"


def _materialized_input_value(
    *,
    node_key: str,
    input_name: str,
    field_spec: object,
    seed_provider: SeedProvider,
) -> object:
    """Return a generated or default value for one missing input."""

    if is_randomizable_seed_input(input_name, field_spec):
        try:
            return seed_provider()
        except Exception as exc:
            logger.error(
                "Failed to generate seed during input materialization.",
                extra={
                    "node_key": node_key,
                    "input_name": input_name,
                    "error": str(exc),
                },
            )
            raise RuntimeError(f"Failed to generate seed for node '{node_key}': {exc}") from exc
    return default_from_field_spec(field_spec)


def _node_inputs(
    node: MutableMapping[object, object],
    node_key: str,
) -> MutableMapping[object, object]:
    """Return mutable node inputs, creating the mapping when absent."""

    raw_inputs = node.get("inputs")
    if raw_inputs is None:
        inputs: dict[object, object] = {}
        node["inputs"] = inputs
        return inputs
    existing_inputs = _mutable_mapping_or_none(raw_inputs)
    if existing_inputs is None:
        raise RuntimeError(f"Materialized node '{node_key}' has invalid inputs.")
    return existing_inputs


def _field_metadata(field_spec: object) -> Mapping[str, object] | None:
    """Return Comfy field metadata when the spec has one."""

    if not isinstance(field_spec, list) or len(field_spec) < 2:
        return None
    return _string_mapping_or_none(field_spec[1])


def _mapping_or_none(value: object) -> Mapping[object, object] | None:
    """Return a mapping value after runtime narrowing."""

    if isinstance(value, Mapping):
        return value
    return None


def _string_mapping_or_none(value: object) -> Mapping[str, object] | None:
    """Return a string-keyed mapping value after runtime narrowing."""

    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _mutable_mapping_or_none(value: object) -> MutableMapping[object, object] | None:
    """Return a mutable mapping value after runtime narrowing."""

    if isinstance(value, MutableMapping):
        return value
    return None


__all__ = [
    "default_from_field_spec",
    "field_spec_from_live_input",
    "input_type_name",
    "is_randomizable_seed_input",
    "iter_definition_input_fields",
    "materialize_node_inputs",
]
