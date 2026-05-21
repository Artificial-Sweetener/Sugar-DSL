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
"""Intermediate representation (SpawnPlan) for the Sugar compiler."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class CubeEntry(TypedDict):
    """A cube instance entry in the spawn plan."""

    cube_id: str
    alias: str
    version_pin: NotRequired[str]
    requested_version: NotRequired[str]
    resolved_version: NotRequired[str]
    flavor: NotRequired[str]
    flavor_id: NotRequired[str]
    flavor_scope: NotRequired[str]
    metadata: dict[str, Any]


class ConnectionEndpoint(TypedDict):
    """An endpoint in a spawn plan connection."""

    alias: str
    output: str


class ConnectionTarget(TypedDict):
    """The target for a spawn plan connection."""

    alias: str
    input: str
    input_key: NotRequired[str]


ConnectionEntry = TypedDict(
    "ConnectionEntry",
    {
        "from": ConnectionEndpoint,
        "to": ConnectionTarget,
        "metadata": dict[str, Any],
    },
)


class NodeLinkEndpoint(TypedDict):
    """An endpoint in a spawn plan whole-node link."""

    alias: str
    node: str


NodeLinkEntry = TypedDict(
    "NodeLinkEntry",
    {
        "from": NodeLinkEndpoint,
        "to": NodeLinkEndpoint,
        "metadata": dict[str, Any],
    },
)


class SetEntry(TypedDict):
    """A set entry in the spawn plan."""

    alias: str
    node: str
    input: str
    value: Any
    metadata: dict[str, Any]


class DisabledEntry(TypedDict):
    """A disabled node entry in the spawn plan."""

    alias: str
    node: str
    metadata: dict[str, Any]


class EnabledEntry(TypedDict):
    """An enabled node override entry in the spawn plan."""

    alias: str
    node: str
    metadata: dict[str, Any]


class SpawnPlan(TypedDict):
    """The compiler intermediate representation for executing a script."""

    schema_version: int
    cube_root: str
    order: list[str]
    cubes: list[CubeEntry]
    connections: list[ConnectionEntry]
    node_links: list[NodeLinkEntry]
    sets: list[SetEntry]
    enabled: list[EnabledEntry]
    disabled: list[DisabledEntry]
    warnings: list[str]
    errors: list[str]


def create_spawn_plan(cube_root: str) -> SpawnPlan:
    """Create an empty spawn plan for a cube root."""

    return {
        "schema_version": 1,
        "cube_root": str(cube_root),
        "order": [],
        "cubes": [],
        "connections": [],
        "node_links": [],
        "sets": [],
        "enabled": [],
        "disabled": [],
        "warnings": [],
        "errors": [],
    }


def _normalize_node_name(node_key: str, alias: str) -> str:
    """Store node names without the alias prefix inside persisted plan entries."""

    prefix = f"{alias}."
    if node_key.startswith(prefix):
        return node_key[len(prefix) :]
    return node_key


def add_cube(
    plan: SpawnPlan,
    cube_id: str,
    alias: str,
    source_line: int,
    version_pin: str | None,
    requested_version: str | None = None,
    resolved_version: str | None = None,
    flavor: str | None = None,
    flavor_id: str | None = None,
    flavor_scope: str | None = None,
) -> None:
    """Append a cube entry to the spawn plan."""

    entry: CubeEntry = {
        "cube_id": cube_id,
        "alias": alias,
        "metadata": {"source_line": source_line},
    }
    if version_pin is not None:
        entry["version_pin"] = version_pin
    if requested_version is not None:
        entry["requested_version"] = requested_version
    if resolved_version:
        entry["resolved_version"] = resolved_version
    if flavor is not None:
        entry["flavor"] = flavor
    if flavor_id is not None:
        entry["flavor_id"] = flavor_id
    if flavor_scope is not None:
        entry["flavor_scope"] = flavor_scope
    plan["cubes"].append(entry)
    plan["order"].append(alias)


def add_connection(
    plan: SpawnPlan,
    from_alias: str,
    from_output: str,
    to_alias: str,
    to_input: str,
    input_key: str | None,
    source_line: int,
) -> None:
    """Append a connection entry to the spawn plan."""

    to_entry: ConnectionTarget = {"alias": to_alias, "input": to_input}
    if input_key:
        to_entry["input_key"] = input_key
    entry: ConnectionEntry = {
        "from": {"alias": from_alias, "output": from_output},
        "to": to_entry,
        "metadata": {"source_line": source_line},
    }
    plan["connections"].append(entry)


def add_node_link(
    plan: SpawnPlan,
    from_alias: str,
    from_node_key: str,
    to_alias: str,
    to_node_key: str,
    source_line: int,
) -> None:
    """Append a whole-node link entry to the spawn plan."""

    entry: NodeLinkEntry = {
        "from": {
            "alias": from_alias,
            "node": _normalize_node_name(from_node_key, from_alias),
        },
        "to": {
            "alias": to_alias,
            "node": _normalize_node_name(to_node_key, to_alias),
        },
        "metadata": {
            "source_line": source_line,
            "from_node_key": from_node_key,
            "to_node_key": to_node_key,
        },
    }
    plan["node_links"].append(entry)


def add_set(
    plan: SpawnPlan,
    alias: str,
    node_key: str,
    input_key: str,
    value: Any,
    source_line: int | None,
    kind: str,
) -> None:
    """Append a set entry to the spawn plan."""

    entry: SetEntry = {
        "alias": alias,
        "node": _normalize_node_name(node_key, alias),
        "input": input_key,
        "value": value,
        "metadata": {"kind": kind, "node_key": node_key},
    }
    if source_line is not None:
        entry["metadata"]["source_line"] = source_line
    plan["sets"].append(entry)


def add_enabled(plan: SpawnPlan, alias: str, node_key: str, source_line: int) -> None:
    """Append an enabled override entry to the spawn plan."""

    entry: EnabledEntry = {
        "alias": alias,
        "node": _normalize_node_name(node_key, alias),
        "metadata": {"node_key": node_key, "source_line": source_line},
    }
    plan["enabled"].append(entry)


def add_disabled(
    plan: SpawnPlan,
    alias: str,
    node_key: str,
    source_line: int | None,
    *,
    reason: str,
) -> None:
    """Append a disabled entry to the spawn plan."""

    entry: DisabledEntry = {
        "alias": alias,
        "node": _normalize_node_name(node_key, alias),
        "metadata": {"node_key": node_key, "reason": reason},
    }
    if source_line is not None:
        entry["metadata"]["source_line"] = source_line
    plan["disabled"].append(entry)
