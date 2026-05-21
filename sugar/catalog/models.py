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
"""Type definitions and validation for current SugarCube documents."""

from __future__ import annotations

import copy
import re
from typing import Any, NotRequired, TypedDict, cast

from .subgraphs import is_uuid_class_type, node_class_type


_INPUT_BINDING_RE = re.compile(r"^input\.[a-z0-9_]+(\d+)?$")
_OUTPUT_BINDING_RE = re.compile(r"^output\.[a-z0-9_]+(\d+)?$")


class CubeNodeSpec(TypedDict, total=False):
    """Schema for a single runtime node inside a normalized cube document."""

    class_type: str
    label: str
    inputs: dict[str, Any]
    mode: int
    _meta: dict[str, Any]


class SurfaceControl(TypedDict):
    """Surface control entry used to materialize flavor values."""

    control_id: str
    symbol: str
    input_name: str
    label: str
    class_type: str
    value_type: str


class FlavorEntry(TypedDict):
    """Authored or local flavor entry."""

    id: str
    name: str
    values: dict[str, Any]


class CubeDocument(TypedDict, total=False):
    """Compiler-facing cube document normalized from the current `.cube` format."""

    cube_id: str
    version: str
    nodes: dict[str, CubeNodeSpec]
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    layout: dict[str, Any]
    definitions: dict[str, Any]
    subgraphs: list[dict[str, Any]]
    surface: dict[str, Any]
    flavors: dict[str, list[FlavorEntry]]
    queue: NotRequired[list[str]]
    description: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]
    __template__: NotRequired[str]


def validate_cube_document(payload: Any) -> CubeDocument:
    """Validate a current SugarCubes `.cube` document and normalize it for compile use.

    Args:
        payload: Raw JSON payload for a cube.

    Returns:
        A compiler-facing document with implementation fields promoted to `nodes`,
        `inputs`, `outputs`, `layout`, `definitions`, and `subgraphs`.

    Raises:
        RuntimeError: If the payload structure is invalid.
    """

    if not isinstance(payload, dict):
        raise RuntimeError("Cube document must be a JSON object.")

    cube_id = _require_string(payload, "cube_id", "Cube document")
    version = _require_string(payload, "version", "Cube document")
    implementation = _require_mapping(payload, "implementation", "Cube document")
    surface = _validate_surface(_require_mapping(payload, "surface", "Cube document"))
    flavors = _validate_flavors(_require_mapping(payload, "flavors", "Cube document"))

    nodes = _require_mapping(implementation, "nodes", "Cube implementation")
    if not nodes:
        raise RuntimeError("Cube implementation must include a non-empty 'nodes' object.")
    normalized_nodes = _validate_nodes(nodes)

    inputs = _require_mapping(implementation, "inputs", "Cube implementation")
    _validate_binding_keys(inputs, _INPUT_BINDING_RE, "input")
    _validate_input_bindings(inputs)
    outputs = _require_mapping(implementation, "outputs", "Cube implementation")
    _validate_binding_keys(outputs, _OUTPUT_BINDING_RE, "output")
    _validate_output_bindings(outputs)
    layout = _require_mapping(implementation, "layout", "Cube implementation")
    definitions = _require_mapping(implementation, "definitions", "Cube implementation")
    _validate_definitions(definitions)
    subgraphs = _validate_subgraphs(
        _require_list(implementation, "subgraphs", "Cube implementation")
    )
    _validate_wrapper_subgraphs(normalized_nodes, subgraphs)
    _validate_surface_flavor_contract(surface, flavors)

    document: CubeDocument = {
        "cube_id": cube_id,
        "version": version,
        "nodes": normalized_nodes,
        "inputs": copy.deepcopy(inputs),
        "outputs": copy.deepcopy(outputs),
        "layout": copy.deepcopy(layout),
        "definitions": copy.deepcopy(definitions),
        "subgraphs": copy.deepcopy(subgraphs),
        "surface": copy.deepcopy(surface),
        "flavors": copy.deepcopy(flavors),
    }
    description = payload.get("description")
    if isinstance(description, str):
        document["description"] = description
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        document["metadata"] = copy.deepcopy(metadata)
    return document


def _require_string(payload: dict[str, Any], key: str, owner: str) -> str:
    """Read one required non-empty string field."""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{owner} must include a non-empty '{key}'.")
    return value.strip()


def _require_mapping(payload: dict[str, Any], key: str, owner: str) -> dict[str, Any]:
    """Read one required object-valued field."""

    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"{owner} must include a '{key}' object.")
    return value


def _require_list(payload: dict[str, Any], key: str, owner: str) -> list[Any]:
    """Read one required array-valued field."""

    value = payload.get(key)
    if not isinstance(value, list):
        raise RuntimeError(f"{owner} must include a '{key}' array.")
    return value


def _validate_nodes(nodes: dict[str, Any]) -> dict[str, CubeNodeSpec]:
    """Validate implementation nodes and return a deep-copied node map."""

    normalized_nodes: dict[str, CubeNodeSpec] = {}
    labels: dict[str, str] = {}
    for node_key, node in nodes.items():
        if not isinstance(node_key, str) or not node_key:
            raise RuntimeError("Cube node keys must be non-empty strings.")
        if not isinstance(node, dict):
            raise RuntimeError(f"Cube node '{node_key}' must be an object.")
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            raise RuntimeError(f"Cube node '{node_key}' must include a non-empty 'class_type'.")
        inputs = node.get("inputs")
        if inputs is not None and not isinstance(inputs, dict):
            raise RuntimeError(
                f"Cube node '{node_key}' has invalid 'inputs' mapping (must be object)."
            )
        node_label = _node_label(node_key, node)
        previous = labels.get(node_label)
        if previous is not None:
            raise RuntimeError(
                "Cube implementation has duplicate node label "
                f"'{node_label}' for node keys '{previous}' and '{node_key}'."
            )
        labels[node_label] = node_key
        normalized_node = copy.deepcopy(node)
        normalized_node["label"] = node_label
        normalized_nodes[node_key] = cast(CubeNodeSpec, normalized_node)
    return normalized_nodes


def _node_label(node_key: str, node: dict[str, Any]) -> str:
    """Return the script-facing label stored for one implementation node."""

    label = node.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return node_key


def _validate_surface(surface: dict[str, Any]) -> dict[str, Any]:
    """Validate the current cube surface contract."""

    _require_string(surface, "default_flavor_id", "Cube surface")
    controls = _require_list(surface, "controls", "Cube surface")
    seen_control_ids: set[str] = set()
    normalized_controls: list[SurfaceControl] = []
    for index, control in enumerate(controls):
        if not isinstance(control, dict):
            raise RuntimeError(f"Cube surface control #{index + 1} must be an object.")
        normalized: SurfaceControl = {
            "control_id": _require_string(control, "control_id", "Cube surface control"),
            "symbol": _require_string(control, "symbol", "Cube surface control"),
            "input_name": _require_string(control, "input_name", "Cube surface control"),
            "label": _require_string(control, "label", "Cube surface control"),
            "class_type": _require_string(control, "class_type", "Cube surface control"),
            "value_type": _require_string(control, "value_type", "Cube surface control"),
        }
        if normalized["control_id"] in seen_control_ids:
            raise RuntimeError(
                f"Cube surface has duplicate control id '{normalized['control_id']}'."
            )
        seen_control_ids.add(normalized["control_id"])
        normalized_controls.append(normalized)
    _validate_surface_control_labels(normalized_controls)
    return {
        "default_flavor_id": surface["default_flavor_id"],
        "controls": normalized_controls,
    }


def _validate_surface_control_labels(controls: list[SurfaceControl]) -> None:
    """Reject duplicate surface labels within one script-addressable node scope."""

    labels_by_symbol: dict[str, dict[str, str]] = {}
    for control in controls:
        symbol_labels = labels_by_symbol.setdefault(control["symbol"], {})
        previous = symbol_labels.get(control["label"])
        if previous is not None:
            raise RuntimeError(
                "Cube surface has duplicate label "
                f"'{control['label']}' for symbol '{control['symbol']}' "
                f"on inputs '{previous}' and '{control['input_name']}'."
            )
        symbol_labels[control["label"]] = control["input_name"]


def _validate_flavors(flavors: dict[str, Any]) -> dict[str, list[FlavorEntry]]:
    """Validate authored flavors from the current cube document."""

    authored_payload = _require_list(flavors, "authored", "Cube flavors")
    if not authored_payload:
        raise RuntimeError("Cube flavors must include at least one authored flavor.")
    authored: list[FlavorEntry] = []
    seen_ids: set[str] = set()
    for index, flavor in enumerate(authored_payload):
        if not isinstance(flavor, dict):
            raise RuntimeError(f"Authored flavor #{index + 1} must be an object.")
        flavor_id = _require_string(flavor, "id", "Authored flavor")
        if flavor_id in seen_ids:
            raise RuntimeError(f"Cube flavors have duplicate authored id '{flavor_id}'.")
        seen_ids.add(flavor_id)
        values = flavor.get("values")
        if not isinstance(values, dict):
            raise RuntimeError("Authored flavor values must be an object.")
        authored.append(
            {
                "id": flavor_id,
                "name": _require_string(flavor, "name", "Authored flavor"),
                "values": copy.deepcopy(values),
            }
        )
    if authored[0]["id"] != "default":
        raise RuntimeError("Default authored flavor must be stored first.")
    return {"authored": authored}


def _validate_surface_flavor_contract(
    surface: dict[str, Any], flavors: dict[str, list[FlavorEntry]]
) -> None:
    """Validate the relationship between surface controls and authored flavors."""

    authored_ids = {flavor["id"] for flavor in flavors["authored"]}
    default_flavor_id = surface.get("default_flavor_id")
    if default_flavor_id not in authored_ids:
        raise RuntimeError("surface.default_flavor_id must reference an authored flavor.")
    control_ids = {control["control_id"] for control in surface["controls"]}
    for flavor in flavors["authored"]:
        unknown = sorted(set(flavor["values"].keys()) - control_ids)
        if unknown:
            raise RuntimeError(
                f"Authored flavor '{flavor['id']}' references unknown surface control(s): {', '.join(unknown)}."
            )


def _validate_binding_keys(bindings: dict[str, Any], pattern: re.Pattern[str], kind: str) -> None:
    """Validate cube binding keys against the expected schema."""

    for key in bindings.keys():
        if not isinstance(key, str) or not pattern.match(key):
            raise RuntimeError(f"Cube document has invalid {kind} binding key '{key}'.")


def _validate_input_bindings(bindings: dict[str, Any]) -> None:
    """Validate input binding target shapes that materialization consumes."""

    for binding_name, value in bindings.items():
        if isinstance(value, list):
            _validate_input_targets(binding_name, value)
            continue
        if isinstance(value, dict) and "targets" in value:
            targets = value["targets"]
            if not isinstance(targets, list):
                raise RuntimeError(
                    f"Cube input binding '{binding_name}' has invalid 'targets' payload."
                )
            _validate_input_targets(binding_name, targets)


def _validate_input_targets(binding_name: str, targets: list[Any]) -> None:
    """Validate node/input target entries for one cube input binding."""

    for index, target in enumerate(targets):
        if not isinstance(target, list) or len(target) != 2:
            raise RuntimeError(
                f"Cube input binding '{binding_name}' target #{index + 1} must be [node, input]."
            )
        node_id, input_name = target
        if not isinstance(node_id, str) or not node_id:
            raise RuntimeError(
                f"Cube input binding '{binding_name}' target #{index + 1} must include a non-empty node name."
            )
        if not isinstance(input_name, str) or not input_name:
            raise RuntimeError(
                f"Cube input binding '{binding_name}' target #{index + 1} must include a non-empty input name."
            )


def _validate_output_bindings(bindings: dict[str, Any]) -> None:
    """Validate output binding node-link shapes that compiler graph ops consume."""

    for binding_name, value in bindings.items():
        if isinstance(value, str):
            if not value:
                raise RuntimeError(
                    f"Cube output binding '{binding_name}' must reference a non-empty node name."
                )
            continue
        if not isinstance(value, list) or len(value) != 2:
            raise RuntimeError(
                f"Cube output binding '{binding_name}' must be a node name or [node, slot]."
            )
        node_id, slot = value
        if not isinstance(node_id, str) or not node_id:
            raise RuntimeError(
                f"Cube output binding '{binding_name}' must include a non-empty node name."
            )
        if isinstance(slot, bool):
            raise RuntimeError(f"Cube output binding '{binding_name}' has invalid boolean slot.")
        if not isinstance(slot, int):
            raise RuntimeError(
                f"Cube output binding '{binding_name}' must include an integer slot."
            )


def _validate_definitions(definitions: dict[str, Any]) -> None:
    """Validate compact node-definition metadata consumed by catalog and compiler paths."""

    for class_type, definition in definitions.items():
        if not isinstance(class_type, str) or not class_type:
            raise RuntimeError("Cube definitions must use non-empty string class types.")
        if not isinstance(definition, dict):
            raise RuntimeError(f"Cube definition '{class_type}' must be an object.")
        input_payload = definition.get("input")
        if input_payload is not None:
            if not isinstance(input_payload, dict):
                raise RuntimeError(f"Cube definition '{class_type}' has invalid 'input' metadata.")
            _validate_definition_inputs(class_type, input_payload)


def _validate_definition_inputs(class_type: str, input_payload: dict[str, Any]) -> None:
    """Validate definition input sections without requiring full Comfy inventories."""

    for section_name, fields in input_payload.items():
        if section_name not in {"required", "optional", "hidden"}:
            continue
        if not isinstance(fields, dict):
            raise RuntimeError(
                f"Cube definition '{class_type}' input section '{section_name}' must be an object."
            )
        for field_name, field_spec in fields.items():
            if not isinstance(field_name, str) or not field_name:
                raise RuntimeError(
                    f"Cube definition '{class_type}' has an invalid input field name."
                )
            _validate_definition_field_spec(class_type, section_name, field_name, field_spec)


def _validate_definition_field_spec(
    class_type: str,
    section_name: str,
    field_name: str,
    field_spec: Any,
) -> None:
    """Validate one scalar, fixed enum, or compact list field spec."""

    owner = f"Cube definition '{class_type}' field '{section_name}.{field_name}'"
    if isinstance(field_spec, str):
        if not field_spec:
            raise RuntimeError(f"{owner} must include a non-empty type name.")
        return
    if not isinstance(field_spec, list) or not field_spec:
        raise RuntimeError(f"{owner} must be a non-empty array.")
    head = field_spec[0]
    metadata = field_spec[1] if len(field_spec) > 1 else None
    if len(field_spec) > 2:
        raise RuntimeError(f"{owner} must not contain more than two entries.")
    if isinstance(head, str):
        if not head:
            raise RuntimeError(f"{owner} must include a non-empty type name.")
        if metadata is not None and not isinstance(metadata, dict):
            raise RuntimeError(f"{owner} scalar metadata must be an object.")
        return
    if isinstance(head, list):
        if not all(isinstance(option, str) for option in head):
            raise RuntimeError(f"{owner} fixed enum choices must be strings.")
        if metadata is not None and not isinstance(metadata, dict):
            raise RuntimeError(f"{owner} fixed enum metadata must be an object.")
        return
    raise RuntimeError(f"{owner} has an invalid field type declaration.")


def _validate_subgraphs(subgraphs: list[Any]) -> list[dict[str, Any]]:
    """Validate subgraph definitions and return copied dictionaries."""

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, subgraph in enumerate(subgraphs):
        if not isinstance(subgraph, dict):
            raise RuntimeError(f"Cube subgraph #{index + 1} must be a JSON object.")
        sub_id = subgraph.get("id")
        if not isinstance(sub_id, str) or not sub_id.strip():
            raise RuntimeError(f"Cube subgraph #{index + 1} must include a non-empty 'id'.")
        normalized_id = sub_id.strip()
        if normalized_id in seen_ids:
            raise RuntimeError(f"Cube document has duplicate subgraph id '{normalized_id}'.")
        seen_ids.add(normalized_id)
        nodes_payload = subgraph.get("nodes")
        if nodes_payload is not None and not isinstance(nodes_payload, list):
            raise RuntimeError(f"Cube subgraph '{normalized_id}' has invalid 'nodes' payload.")
        _validate_subgraph_interface_labels(normalized_id, subgraph)
        normalized.append(copy.deepcopy(subgraph))
    return normalized


def _validate_subgraph_interface_labels(subgraph_id: str, subgraph: dict[str, Any]) -> None:
    """Require unique labels on public subgraph interface entries."""

    for field_name in ("inputs", "outputs"):
        entries = subgraph.get(field_name)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise RuntimeError(f"Cube subgraph '{subgraph_id}' has invalid '{field_name}' payload.")
        labels: dict[str, str] = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise RuntimeError(
                    f"Cube subgraph '{subgraph_id}' {field_name} entry #{index + 1} must be an object."
                )
            name = _require_string(entry, "name", "Cube subgraph interface")
            label = _require_string(entry, "label", "Cube subgraph interface")
            previous = labels.get(label)
            if previous is not None:
                raise RuntimeError(
                    "Cube subgraph "
                    f"'{subgraph_id}' has duplicate {field_name} label '{label}' "
                    f"for names '{previous}' and '{name}'."
                )
            labels[label] = name


def _validate_wrapper_subgraphs(
    nodes: dict[str, CubeNodeSpec], subgraphs: list[dict[str, Any]]
) -> None:
    """Validate UUID wrapper nodes against embedded subgraph definitions."""

    wrapper_classes = {
        str(node.get("class_type"))
        for node in nodes.values()
        if is_uuid_class_type(node.get("class_type"))
    }
    if not wrapper_classes:
        return
    subgraph_index = {subgraph["id"]: subgraph for subgraph in subgraphs}
    missing = sorted(wrapper_classes - set(subgraph_index.keys()))
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(
            f"Cube document is missing subgraph definitions for wrapper class_type(s): {missing_text}."
        )
    missing_inputs = sorted(
        sub_id
        for sub_id in wrapper_classes
        if not _has_subgraph_interface_array(subgraph_index[sub_id], "inputs")
    )
    if missing_inputs:
        missing_inputs_text = ", ".join(missing_inputs)
        raise RuntimeError(
            "Cube document subgraph definition(s) for wrapper class_type(s) "
            f"{missing_inputs_text} must include an 'inputs' array."
        )
    missing_outputs = sorted(
        sub_id
        for sub_id in wrapper_classes
        if not _has_subgraph_interface_array(subgraph_index[sub_id], "outputs")
    )
    if missing_outputs:
        missing_outputs_text = ", ".join(missing_outputs)
        raise RuntimeError(
            "Cube document subgraph definition(s) for wrapper class_type(s) "
            f"{missing_outputs_text} must include an 'outputs' array."
        )
    empty = sorted(
        sub_id
        for sub_id in wrapper_classes
        if not _has_executable_subgraph_body(subgraph_index[sub_id])
    )
    if empty:
        empty_text = ", ".join(empty)
        raise RuntimeError(
            f"Cube document subgraph body is empty for wrapper class_type(s): {empty_text}."
        )


def _has_executable_subgraph_body(subgraph: dict[str, Any]) -> bool:
    """Return whether a serialized subgraph has concrete executable nodes."""

    nodes = subgraph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        class_type = node_class_type(node)
        if class_type:
            return True
    return False


def _has_subgraph_interface_array(subgraph: dict[str, Any], field_name: str) -> bool:
    """Return whether a subgraph exposes a concrete interface array field."""

    return field_name in subgraph and isinstance(subgraph.get(field_name), list)
