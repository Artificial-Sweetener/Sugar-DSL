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
"""Runtime providers for current ComfyUI node definitions."""

from __future__ import annotations

import copy
import importlib
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from sugar.compiler.errors import SugarCompilerError
from sugar.compiler.live_definitions import (
    LiveNodeDefinition,
    LiveNodeInputDefinition,
)
from sugar.runtime.executor import (
    DEFAULT_SERVER,
    DEFAULT_TIMEOUT_SECONDS,
    _decode_json_object,
    _normalize_server,
    _read_http_error_body,
)

_LOGGER = logging.getLogger(__name__)


class ComfyNodeClass(Protocol):
    """Describe the Comfy node class method needed for live definitions."""

    @classmethod
    def INPUT_TYPES(cls) -> object:
        """Return Comfy's raw input metadata for the node class."""


RegistrySource = Callable[[], Mapping[str, ComfyNodeClass]]


class StaticLiveNodeDefinitionProvider:
    """Serve normalized live node definitions from an in-memory snapshot."""

    def __init__(self, definitions: Mapping[str, LiveNodeDefinition]) -> None:
        """Store definitions keyed by Comfy class type."""

        self._definitions = dict(definitions)

    @classmethod
    def from_object_info_payload(
        cls,
        payload: Mapping[str, object],
    ) -> StaticLiveNodeDefinitionProvider:
        """Build a static provider from a Comfy ``/object_info`` response."""

        return cls(normalize_object_info_payload(payload))

    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        """Return the configured definition for ``class_type`` when present."""

        return self._definitions.get(class_type)


class ComfyObjectInfoLiveNodeDefinitionProvider:
    """Fetch live node definitions from ComfyUI's ``/object_info`` endpoint."""

    def __init__(
        self,
        *,
        server: str = DEFAULT_SERVER,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Configure the Comfy server used for standalone live-safe compilation."""

        self._server = _normalize_server(server)
        self._timeout = timeout
        self._logger = logger or _LOGGER
        self._definitions: dict[str, LiveNodeDefinition] | None = None

    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        """Return a live definition fetched from ComfyUI object-info metadata."""

        if self._definitions is None:
            self._definitions = self._fetch_definitions()
        return self._definitions.get(class_type)

    def _fetch_definitions(self) -> dict[str, LiveNodeDefinition]:
        """Fetch and normalize Comfy object-info metadata once per provider."""

        url = f"http://{self._server}/object_info"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _read_http_error_body(exc)
            message = (
                f"Failed to fetch ComfyUI object_info from '{self._server}': "
                f"HTTP {exc.code} {exc.reason}: {detail or exc}"
            )
            self._logger.error(
                message,
                extra={
                    "operation": "fetch_comfy_object_info",
                    "server": self._server,
                    "error": str(exc),
                },
            )
            raise SugarCompilerError(
                message,
                code="sugar-live-definition-missing",
            ) from exc
        except OSError as exc:
            message = f"Failed to fetch ComfyUI object_info from '{self._server}': {exc}"
            self._logger.error(
                message,
                extra={
                    "operation": "fetch_comfy_object_info",
                    "server": self._server,
                    "error": str(exc),
                },
            )
            raise SugarCompilerError(
                message,
                code="sugar-live-definition-missing",
            ) from exc

        payload = _decode_json_object(
            response_body,
            operation="fetch_comfy_object_info",
            message_prefix="object_info response",
            context={"server": self._server},
        )
        return normalize_object_info_payload(payload)


class ComfyRegistryLiveNodeDefinitionProvider:
    """Read live node definitions from ComfyUI's in-process node registry."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        registry_source: RegistrySource | None = None,
    ) -> None:
        """Configure the registry source used by an in-process Comfy host."""

        self._logger = logger or _LOGGER
        self._registry_source = registry_source or _comfy_registry
        self._memo: dict[str, LiveNodeDefinition | None] = {}

    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        """Return a normalized definition for one active Comfy node class."""

        if class_type in self._memo:
            return self._memo[class_type]
        registry = self._registry_source()
        node_class = registry.get(class_type)
        if node_class is None:
            self._memo[class_type] = None
            return None
        try:
            raw_input_types = node_class.INPUT_TYPES()
        except Exception as exc:
            self._logger.warning(
                "Comfy node INPUT_TYPES failed during Sugar compile.",
                extra={
                    "operation": "sugar-live-node-definition",
                    "node_class_type": class_type,
                    "error": repr(exc),
                },
            )
            raise SugarCompilerError(
                f"Live definition lookup failed for node class '{class_type}': {exc}",
                code="sugar-live-definition-missing",
                node_class_type=class_type,
            ) from exc
        definition = normalize_input_types_definition(class_type, raw_input_types)
        self._memo[class_type] = definition
        return definition


def normalize_object_info_payload(
    payload: Mapping[str, object],
) -> dict[str, LiveNodeDefinition]:
    """Normalize a Comfy ``/object_info`` response into live definitions."""

    definitions: dict[str, LiveNodeDefinition] = {}
    for class_type, raw_definition in payload.items():
        if not isinstance(class_type, str) or not class_type:
            continue
        definition_payload = _mapping_or_none(raw_definition)
        if definition_payload is None:
            raise SugarCompilerError(
                f"Comfy object_info entry for '{class_type}' must be an object.",
                code="sugar-live-input-invalid",
                node_class_type=class_type,
            )
        definitions[class_type] = normalize_object_info_definition(
            class_type,
            definition_payload,
        )
    return definitions


def normalize_object_info_definition(
    class_type: str,
    payload: Mapping[object, object],
) -> LiveNodeDefinition:
    """Normalize one Comfy object-info entry into a live definition."""

    input_payload = payload.get("input")
    if isinstance(input_payload, Mapping):
        return normalize_input_types_definition(class_type, input_payload)
    return normalize_input_types_definition(class_type, payload)


def normalize_input_types_definition(
    class_type: str,
    raw_input_types: object,
) -> LiveNodeDefinition:
    """Normalize Comfy ``INPUT_TYPES()`` metadata into a live definition."""

    input_types = _mapping_or_empty(raw_input_types)
    inputs: dict[str, LiveNodeInputDefinition] = {}
    for section_name, required in (
        ("required", True),
        ("optional", False),
        ("hidden", False),
    ):
        section = _mapping_or_empty(input_types.get(section_name))
        for input_name, field_spec in section.items():
            if not isinstance(input_name, str) or not input_name:
                continue
            inputs[input_name] = normalize_input_definition(
                input_name=input_name,
                field_spec=field_spec,
                required=required,
            )
    return LiveNodeDefinition(class_type=class_type, inputs=inputs)


def normalize_input_definition(
    *,
    input_name: str,
    field_spec: object,
    required: bool,
) -> LiveNodeInputDefinition:
    """Normalize one Comfy field spec into a live input definition."""

    value_type = _value_type(field_spec)
    choices = _choices(field_spec)
    metadata = _metadata(field_spec)
    has_default = "default" in metadata
    default = copy.deepcopy(metadata.get("default"))
    return LiveNodeInputDefinition(
        name=input_name,
        value_type=value_type,
        required=required,
        default=default,
        has_default=has_default,
        choices=choices,
        raw=dict(metadata),
    )


def _comfy_registry() -> Mapping[str, ComfyNodeClass]:
    """Read ComfyUI's active node class registry lazily."""

    nodes_module = importlib.import_module("nodes")
    registry = getattr(nodes_module, "NODE_CLASS_MAPPINGS", None)
    if not isinstance(registry, Mapping):
        return {}
    return cast(Mapping[str, ComfyNodeClass], registry)


def _value_type(field_spec: object) -> str:
    """Return a stable scalar value type name from Comfy metadata."""

    if isinstance(field_spec, str):
        return field_spec
    if isinstance(field_spec, (list, tuple)) and field_spec:
        head = field_spec[0]
        if isinstance(head, str):
            return head
        if isinstance(head, (list, tuple)):
            return "COMBO"
    return "UNKNOWN"


def _choices(field_spec: object) -> tuple[object, ...]:
    """Return combo choices from Comfy metadata when present."""

    if not isinstance(field_spec, (list, tuple)) or not field_spec:
        return ()
    head = field_spec[0]
    if not isinstance(head, (list, tuple)):
        return ()
    return tuple(copy.deepcopy(list(head)))


def _metadata(field_spec: object) -> Mapping[str, object]:
    """Return input metadata from Comfy field specs."""

    if isinstance(field_spec, (list, tuple)) and len(field_spec) > 1:
        metadata = field_spec[1]
        if isinstance(metadata, Mapping):
            return cast(Mapping[str, object], metadata)
    return {}


def _mapping_or_none(value: object) -> Mapping[object, object] | None:
    """Return a mapping value after runtime narrowing."""

    if isinstance(value, Mapping):
        return value
    return None


def _mapping_or_empty(value: object) -> Mapping[object, object]:
    """Return mapping payloads while treating malformed optional sections as empty."""

    if isinstance(value, Mapping):
        return value
    return {}


__all__ = [
    "ComfyNodeClass",
    "ComfyObjectInfoLiveNodeDefinitionProvider",
    "ComfyRegistryLiveNodeDefinitionProvider",
    "RegistrySource",
    "StaticLiveNodeDefinitionProvider",
    "normalize_input_definition",
    "normalize_input_types_definition",
    "normalize_object_info_definition",
    "normalize_object_info_payload",
]
