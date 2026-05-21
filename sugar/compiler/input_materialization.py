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
from .graph import CubeGraph

logger = logging.getLogger(__name__)

_MISSING = object()


def materialize_node_inputs(
    cube: CubeGraph,
    *,
    seed_provider: SeedProvider,
) -> None:
    """Fill safe schema-backed inputs on one materialized cube graph."""

    nodes = _mapping_or_none(cube.get("nodes"))
    if nodes is None:
        raise RuntimeError("Materialized cube graph is missing a nodes mapping.")
    definitions = _mapping_or_none(cube.get("definitions"))
    if definitions is None:
        return

    for node_key, node_payload in nodes.items():
        if not isinstance(node_key, str):
            raise RuntimeError("Materialized cube graph has a non-string node key.")
        node = _mutable_mapping_or_none(node_payload)
        if node is None:
            raise RuntimeError(f"Materialized node '{node_key}' must be an object.")
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue
        definition = _string_mapping_or_none(definitions.get(class_type))
        if definition is None:
            continue
        inputs = _node_inputs(node, node_key)
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
    "input_type_name",
    "is_randomizable_seed_input",
    "iter_definition_input_fields",
    "materialize_node_inputs",
]
