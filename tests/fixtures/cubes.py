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
"""Typed cube and snapshot helpers shared by tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

Payload = dict[str, Any]


def current_cube_payload(payload: Payload) -> Payload:
    """Build a current-format cube fixture from compact node payloads."""

    if "implementation" in payload:
        return payload
    surface = payload.get("surface", {"default_flavor_id": "default", "controls": []})
    implementation = {
        "nodes": _labeled_nodes(payload.get("nodes", {})),
        "inputs": payload.get("inputs", {}),
        "outputs": payload.get("outputs", {}),
        "definitions": payload.get("definitions", {}),
        "subgraphs": _labeled_subgraphs(payload.get("subgraphs", [])),
        "layout": payload.get("layout", {}),
    }
    document = {
        "cube_id": payload["cube_id"],
        "version": payload["version"],
        "implementation": implementation,
        "surface": _labeled_surface(surface),
        "flavors": payload.get(
            "flavors",
            {"authored": [{"id": "default", "name": "Default", "values": {}}]},
        ),
    }
    if "metadata" in payload:
        document["metadata"] = payload["metadata"]
    return document


def _labeled_surface(surface: object) -> object:
    """Add explicit labels to compact surface fixtures."""

    if not isinstance(surface, dict):
        return surface
    result = dict(surface)
    controls = result.get("controls")
    if isinstance(controls, list):
        result["controls"] = [
            {
                **control,
                "label": control.get("label") or control.get("input_name", ""),
            }
            if isinstance(control, dict)
            else control
            for control in controls
        ]
    return result


def _labeled_nodes(nodes: object) -> object:
    """Add explicit labels to compact node fixtures."""

    if not isinstance(nodes, dict):
        return nodes
    return {
        node_key: {
            **node,
            "label": node.get("label") or node_key,
        }
        if isinstance(node, dict)
        else node
        for node_key, node in nodes.items()
    }


def _labeled_subgraphs(subgraphs: object) -> object:
    """Add explicit labels to compact subgraph interface fixtures."""

    if not isinstance(subgraphs, list):
        return subgraphs
    labeled = []
    for subgraph in subgraphs:
        if not isinstance(subgraph, dict):
            labeled.append(subgraph)
            continue
        next_subgraph = dict(subgraph)
        for field_name in ("inputs", "outputs"):
            entries = next_subgraph.get(field_name)
            if not isinstance(entries, list):
                continue
            next_subgraph[field_name] = [
                {**entry, "label": entry.get("label") or entry.get("name", "")}
                if isinstance(entry, dict)
                else entry
                for entry in entries
            ]
        labeled.append(next_subgraph)
    return labeled


def write_cube(path: Path, payload: Payload) -> None:
    """Write a current-format `.cube` fixture with UTF-8 JSON."""

    path.write_text(json.dumps(current_cube_payload(payload), indent=2), encoding="utf-8")


def write_local_flavors(
    local_root: Path,
    cube_id: str,
    surface_signature: str,
    *,
    flavor_id: str = "draft",
    name: str = "Draft",
    values: Payload | None = None,
) -> None:
    """Write local flavor state using the production hashed layout."""

    by_cube = local_root / "by-cube"
    by_cube.mkdir(parents=True)
    digest = hashlib.sha256(cube_id.encode("utf-8")).hexdigest()
    payload = {
        "schema_version": 1,
        "cube_id": cube_id,
        "surfaces": {
            surface_signature: {
                "flavors": [
                    {
                        "id": flavor_id,
                        "name": name,
                        "values": values or {"tone": "draft"},
                    }
                ]
            }
        },
    }
    (by_cube / f"{digest}.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def assert_json_snapshot(
    request: pytest.FixtureRequest,
    payload: Payload,
    snapshot_name: str | None = None,
) -> None:
    """Compare a JSON payload with a stored snapshot."""

    test_file = Path(str(request.module.__file__))
    snapshot_dir = test_file.parent / "__snapshots__"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    resolved_name = snapshot_name or request.node.name
    snapshot_path = snapshot_dir / f"{resolved_name}.json"
    actual_json = json.dumps(payload, indent=2, sort_keys=True)

    if not snapshot_path.exists():
        if _snapshot_updates_enabled():
            snapshot_path.write_text(actual_json, encoding="utf-8")
            return
        pytest.fail(
            f"Missing snapshot '{snapshot_path}'. Set SUGAR_UPDATE_SNAPSHOTS=1 to create it."
        )
        return

    expected_json = snapshot_path.read_text(encoding="utf-8")
    if actual_json == expected_json:
        return
    if _snapshot_updates_enabled():
        snapshot_path.write_text(actual_json, encoding="utf-8")
        return
    assert actual_json == expected_json, f"Snapshot mismatch for {resolved_name}."


def _snapshot_updates_enabled() -> bool:
    """Return whether snapshot files may be created or updated."""

    return os.getenv("SUGAR_UPDATE_SNAPSHOTS") == "1"
