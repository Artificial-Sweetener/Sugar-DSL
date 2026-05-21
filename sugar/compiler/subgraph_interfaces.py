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
"""Subgraph interface normalization helpers for wrapper expansion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..catalog.subgraphs import coerce_int, normalize_node_id


def coerce_mapping_list(value: Any) -> list[Mapping[str, Any]]:
    """Return mapping entries from a serialized subgraph array."""

    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def require_interface_entries(
    *,
    definition: Mapping[str, Any],
    field_name: str,
    wrapper_key: str,
) -> list[Mapping[str, Any]]:
    """Return validated subgraph interface entries for a wrapper."""

    raw_value = definition.get(field_name)
    if not isinstance(raw_value, list):
        raise RuntimeError(
            f"Subgraph '{definition.get('id')}' for wrapper '{wrapper_key}' must include an '{field_name}' array."
        )

    entries: list[Mapping[str, Any]] = []
    for idx, entry in enumerate(raw_value):
        if not isinstance(entry, Mapping):
            raise RuntimeError(
                f"Subgraph '{definition.get('id')}' for wrapper '{wrapper_key}' has non-object '{field_name}' entry at index {idx}."
            )
        entries.append(entry)
    return entries


def build_input_name_by_slot(
    *,
    input_entries: Sequence[Mapping[str, Any]],
    wrapper_key: str,
    subgraph_id: str,
) -> dict[int, str]:
    """Build wrapper input-name mapping by interface slot index."""

    input_name_by_slot: dict[int, str] = {}
    for idx, entry in enumerate(input_entries):
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' has input entry {idx} without a non-empty 'name'."
            )
        input_name_by_slot[idx] = name.strip()
    return input_name_by_slot


def build_input_name_by_link_id(
    *,
    input_entries: Sequence[Mapping[str, Any]],
    wrapper_key: str,
    subgraph_id: str,
) -> dict[int, str]:
    """Build wrapper input-name mapping by link id using interface metadata."""

    input_name_by_link_id: dict[int, str] = {}
    for entry in input_entries:
        input_name = str(entry["name"]).strip()
        link_ids = list(iter_link_ids(entry.get("linkIds")))
        if not link_ids:
            continue
        for link_id in link_ids:
            existing_name = input_name_by_link_id.get(link_id)
            if existing_name and existing_name != input_name:
                raise RuntimeError(
                    f"Subgraph '{subgraph_id}' for wrapper '{wrapper_key}' link id {link_id} maps multiple inputs ('{existing_name}', '{input_name}')."
                )
            input_name_by_link_id[link_id] = input_name
    return input_name_by_link_id


def collect_interface_ids(value: Any, *, default: str) -> set[str]:
    """Return normalized node ids for a subgraph interface node declaration."""

    ids: set[str] = set()
    if isinstance(value, Mapping):
        node_id = normalize_node_id(value.get("id"))
        if node_id is not None:
            ids.add(node_id)
    if not ids:
        ids.add(default)
    return ids


def iter_link_ids(value: Any) -> Sequence[int]:
    """Yield integer link ids from a serialized interface link id array."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    link_ids: list[int] = []
    for item in value:
        parsed = coerce_int(item)
        if parsed is not None:
            link_ids.append(parsed)
    return link_ids
