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
"""Catalog-owned normalization helpers for serialized ComfyUI subgraphs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

_UUID_CLASS_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_CONTROL_WIDGET_VALUES = frozenset(
    {"fixed", "increment", "decrement", "randomize", "increment-wrap"}
)
_IMPLICIT_CONTROL_WIDGET_INT_INPUTS = frozenset({"seed", "noise_seed"})


class NormalizedLink(TypedDict):
    """Normalized link entry from a serialized subgraph."""

    id: int
    origin_id: str
    origin_slot: int
    target_id: str
    target_port: Any


def is_uuid_class_type(value: Any) -> bool:
    """Return whether a class type string is a UUID wrapper type."""

    return isinstance(value, str) and _UUID_CLASS_RE.match(value) is not None


def node_class_type(raw_node: Mapping[str, Any]) -> str | None:
    """Return a normalized class type from a serialized subgraph node."""

    class_type = raw_node.get("type")
    if not isinstance(class_type, str):
        class_type = raw_node.get("class_type")
    if isinstance(class_type, str):
        class_type = class_type.strip()
    return class_type or None


def normalize_node_id(value: Any) -> str | None:
    """Normalize serialized numeric or string node ids to non-empty strings."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(int(value))
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value)


def normalize_link(raw: Any) -> NormalizedLink | None:
    """Normalize list-style or mapping-style subgraph links."""

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = list(raw)
        if len(values) < 5:
            return None
        link_id = coerce_int(values[0])
        origin_id = normalize_node_id(values[1])
        origin_slot = coerce_int(values[2], default=0)
        target_id = normalize_node_id(values[3])
        target_port = values[4]
        if link_id is None or origin_id is None or origin_slot is None or target_id is None:
            return None
        return {
            "id": link_id,
            "origin_id": origin_id,
            "origin_slot": origin_slot,
            "target_id": target_id,
            "target_port": target_port,
        }
    if isinstance(raw, Mapping):
        link_id = coerce_int(raw.get("id"))
        origin_id = normalize_node_id(raw.get("origin_id") or raw.get("originId"))
        origin_slot = coerce_int(raw.get("origin_slot") or raw.get("originSlot"), default=0)
        target_id = normalize_node_id(raw.get("target_id") or raw.get("targetId"))
        target_port = raw.get("target_port") or raw.get("targetPort") or raw.get("target_slot")
        if link_id is None or origin_id is None or origin_slot is None or target_id is None:
            return None
        return {
            "id": link_id,
            "origin_id": origin_id,
            "origin_slot": origin_slot,
            "target_id": target_id,
            "target_port": target_port,
        }
    return None


def definition_input_order(definitions: Mapping[str, Any], class_type: str) -> list[str]:
    """Resolve widget value order from a node definition payload."""

    definition = definitions.get(class_type)
    if not isinstance(definition, Mapping):
        return []
    order_payload = definition.get("input_order")
    ordered: list[str] = []
    if isinstance(order_payload, Sequence) and not isinstance(order_payload, (str, bytes)):
        ordered.extend(str(name) for name in order_payload if name)
    elif isinstance(order_payload, Mapping):
        for section in ("required", "optional", "hidden"):
            section_items = order_payload.get(section)
            if isinstance(section_items, Sequence) and not isinstance(section_items, (str, bytes)):
                ordered.extend(str(name) for name in section_items if name)

    if ordered:
        return _filter_widget_value_names(ordered, definition)

    input_payload = definition.get("input")
    if isinstance(input_payload, Mapping):
        for section in ("required", "optional", "hidden"):
            section_items = input_payload.get(section)
            if isinstance(section_items, Mapping):
                ordered.extend(str(name) for name in section_items.keys())
    return ordered


def definition_input_has_serialized_control_widget(
    definitions: Mapping[str, Any],
    class_type: str,
    input_name: str,
) -> bool:
    """Return whether Comfy serializes a UI-only control widget after an input."""

    definition = definitions.get(class_type)
    if not isinstance(definition, Mapping):
        return False
    return definition_field_has_serialized_control_widget(definition, input_name)


def definition_field_has_serialized_control_widget(
    definition: Mapping[str, Any],
    input_name: str,
) -> bool:
    """Return whether one Comfy definition field has a value-control companion."""

    field_spec = _definition_field(definition, input_name)
    metadata = _field_metadata(field_spec)
    if metadata.get("control_after_generate") is True:
        return True
    return (
        input_name in _IMPLICIT_CONTROL_WIDGET_INT_INPUTS and _field_type_name(field_spec) == "INT"
    )


def is_comfy_control_widget_value(value: object) -> bool:
    """Return whether a value is one of Comfy's serialized control modes."""

    return isinstance(value, str) and value in _CONTROL_WIDGET_VALUES


def _filter_widget_value_names(
    ordered: Sequence[str],
    definition: Mapping[str, Any],
) -> list[str]:
    """Remove known non-widget sockets from Comfy ``widgets_values`` order."""

    return [name for name in ordered if _definition_field_accepts_widget_value(definition, name)]


def _definition_field_accepts_widget_value(
    definition: Mapping[str, Any],
    input_name: str,
) -> bool:
    """Return whether an input can consume an entry from ``widgets_values``."""

    field_spec = _definition_field(definition, input_name)
    if field_spec is None:
        return True
    type_name = _field_type_name(field_spec)
    if type_name is None:
        return True
    return type_name in {"BOOLEAN", "COMBO", "FLOAT", "INT", "LIST", "STRING"}


def _definition_field(definition: Mapping[str, Any], input_name: str) -> Any:
    """Return a raw input field definition by name."""

    input_payload = definition.get("input")
    if not isinstance(input_payload, Mapping):
        return None
    for section in ("required", "optional", "hidden"):
        section_items = input_payload.get(section)
        if isinstance(section_items, Mapping) and input_name in section_items:
            return section_items[input_name]
    return None


def _field_type_name(field_spec: Any) -> str | None:
    """Return the normalized Comfy field type name for a raw field spec."""

    if isinstance(field_spec, str):
        return field_spec
    if not isinstance(field_spec, Sequence) or isinstance(field_spec, (str, bytes)):
        return None
    if not field_spec:
        return None
    first_item = field_spec[0]
    if isinstance(first_item, str):
        return "COMBO" if first_item == "LIST" else first_item
    if isinstance(first_item, Sequence) and not isinstance(first_item, (str, bytes)):
        return "COMBO"
    return None


def _field_metadata(field_spec: Any) -> Mapping[str, Any]:
    """Return the metadata object from a raw field spec."""

    if (
        isinstance(field_spec, Sequence)
        and not isinstance(field_spec, (str, bytes))
        and len(field_spec) > 1
        and isinstance(field_spec[1], Mapping)
    ):
        return field_spec[1]
    return {}


def coerce_int(value: Any, default: int | None = None) -> int | None:
    """Coerce a serialized integer-like value into an integer."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            try:
                return int(float(stripped))
            except ValueError:
                return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
