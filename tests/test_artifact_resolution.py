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
"""Tests for alias-aware cube artifact resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar.api.builder import build_comfy_artifacts_from_text
from sugar.catalog.artifacts import (
    InMemoryCubeArtifactResolver,
    artifact_from_cube_payload,
)
from sugar.compiler.analyzer import analyze_text
from tests.fixtures.cubes import current_cube_payload, write_cube


def _cube_payload(*, version: str, value: int) -> dict[str, object]:
    """Return a small current-format cube payload for resolver tests."""

    return current_cube_payload(
        {
            "cube_id": "Owner/Repo/shared.cube",
            "version": version,
            "nodes": {
                "node": {"class_type": "TestNode", "inputs": {"value": value}},
                "marker": {
                    "class_type": "MarkerNode",
                    "inputs": {"value": value * 10},
                },
            },
            "outputs": {"output.value": "node"},
        }
    )


def test_in_memory_resolver_materializes_two_versions_of_same_cube_id(
    tmp_path: Path,
) -> None:
    """Alias-specific artifacts keep same-cube versions separate in one compile."""

    resolver = InMemoryCubeArtifactResolver(
        {
            "Old": artifact_from_cube_payload(
                cube=_cube_payload(version="1.0.0", value=1),
            ),
            "New": artifact_from_cube_payload(
                cube=_cube_payload(version="2.0.0", value=2),
            ),
        }
    )

    artifacts = build_comfy_artifacts_from_text(
        """
        use "Owner/Repo/shared.cube" as Old
        use "Owner/Repo/shared.cube" as New
        set New.node = Old.node
        """,
        output_dir=tmp_path / "output",
        cube_artifact_resolver=resolver,
    )

    marker_values_by_title = {
        node["_meta"]["title"]: node["inputs"]["value"]
        for node in artifacts["prompt"].values()
        if node["class_type"] == "MarkerNode"
    }
    assert marker_values_by_title == {"Old.marker": 10, "New.marker": 20}

    groups = artifacts["workflow"]["groups"]
    metadata_by_alias = {group["title"]: group["properties"]["sugarcubes"] for group in groups}
    assert metadata_by_alias["Old"]["cube_version"] == "1.0.0"
    assert metadata_by_alias["Old"]["cube_resolved_version"] == "1.0.0"
    assert metadata_by_alias["New"]["cube_version"] == "2.0.0"
    assert metadata_by_alias["New"]["cube_resolved_version"] == "2.0.0"
    assert "cube_revision_ref" not in metadata_by_alias["Old"]
    assert "cube_content_hash" not in metadata_by_alias["Old"]


def test_in_memory_resolver_accepts_two_pinned_versions_of_same_cube_id(
    tmp_path: Path,
) -> None:
    """Alias-specific artifacts satisfy matching Sugar version pins."""

    resolver = InMemoryCubeArtifactResolver(
        {
            "Old": artifact_from_cube_payload(
                cube=_cube_payload(version="1.0.0", value=1),
            ),
            "New": artifact_from_cube_payload(
                cube=_cube_payload(version="2.0.0", value=2),
            ),
        }
    )

    artifacts = build_comfy_artifacts_from_text(
        """
        use "Owner/Repo/shared.cube"@1.0.0 as Old
        use "Owner/Repo/shared.cube"@2.0.0 as New
        set New.node = Old.node
        """,
        output_dir=tmp_path / "output",
        cube_artifact_resolver=resolver,
    )

    marker_values_by_title = {
        node["_meta"]["title"]: node["inputs"]["value"]
        for node in artifacts["prompt"].values()
        if node["class_type"] == "MarkerNode"
    }
    assert marker_values_by_title == {"Old.marker": 10, "New.marker": 20}


def test_in_memory_resolver_reports_version_mismatch_with_alias_and_cube() -> None:
    """Version guards fail closed against backend-provided exact artifacts."""

    resolver = InMemoryCubeArtifactResolver(
        {
            "Demo": artifact_from_cube_payload(
                cube=_cube_payload(version="1.0.0", value=1),
            )
        }
    )

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(
            'use "Owner/Repo/shared.cube"@2.0.0 as Demo',
            cube_artifact_resolver=resolver,
        )

    message = str(excinfo.value)
    assert "Demo" in message
    assert "Owner/Repo/shared.cube" in message
    assert "version mismatch" in message


def test_spawn_plan_records_resolved_definition_identity() -> None:
    """Spawn plans carry requested and resolved artifact identity."""

    resolver = InMemoryCubeArtifactResolver(
        {
            "Demo": artifact_from_cube_payload(
                cube=_cube_payload(version="1.0.0", value=1),
            )
        }
    )

    plan = analyze_text(
        'use "Owner/Repo/shared.cube" as Demo',
        cube_artifact_resolver=resolver,
    )

    assert plan["cubes"][0]["resolved_version"] == "1.0.0"
    assert "content_hash" not in plan["cubes"][0]
    assert "revision_ref" not in plan["cubes"][0]
    assert "source" not in plan["cubes"][0]


def test_filesystem_resolver_preserves_standalone_compile(tmp_path: Path) -> None:
    """Versionless filesystem Sugar still resolves the current indexed cube."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "shared.cube", _cube_payload(version="1.0.0", value=7))

    plan = analyze_text(
        'use "Owner/Repo/shared.cube" as Demo',
        cube_root=cube_root,
    )

    assert plan["cubes"][0]["resolved_version"] == "1.0.0"
    assert "revision_ref" not in plan["cubes"][0]
