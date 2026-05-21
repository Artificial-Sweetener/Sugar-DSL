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
"""Validation tests for connected Sugar recipe requirements."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_comfy_artifacts_from_text, build_workflow_from_text
from sugar.compiler.analyzer import analyze_text
from sugar.compiler.plan_validation import validate_connected_recipe


def _write_value_cube(cube_root: Path) -> None:
    """Write a reusable cube with one input and one output binding."""

    write_cube(
        cube_root / "value.cube",
        {
            "cube_id": "value",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "ValueNode", "inputs": {"value": 1}}},
            "outputs": {"output.value": "node"},
            "layout": {
                "origin": [0, 0],
                "nodes": {"node": {"pos": [20, 80], "size": [180, 60]}},
                "markers": {
                    "input.value": {"pos": [20, 20], "size": [140, 46]},
                    "output.value": {"pos": [240, 80], "size": [140, 46]},
                },
            },
        },
    )


def _write_target_cube(cube_root: Path) -> None:
    """Write a cube that can consume a value binding."""

    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "TargetNode", "inputs": {"value": None}}},
            "inputs": {"input.value": [["node", "value"]]},
            "layout": {
                "origin": [0, 0],
                "nodes": {"node": {"pos": [20, 80], "size": [180, 60]}},
                "markers": {"input.value": {"pos": [20, 20], "size": [140, 46]}},
            },
        },
    )


def test_single_cube_recipe_builds_workflow(tmp_path: Path) -> None:
    """A user script with one cube should compile through public builders."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)

    prompt = build_workflow_from_text(
        'use "value" as solo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    artifacts = build_comfy_artifacts_from_text(
        'use "value" as solo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    assert prompt
    assert artifacts["prompt"]
    assert artifacts["workflow"]["groups"][0]["title"] == "solo"


def test_multi_cube_recipe_with_orphan_alias_is_invalid(tmp_path: Path) -> None:
    """A declared alias that does not participate in an edge is invalid."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)
    _write_target_cube(cube_root)

    with pytest.raises(RuntimeError, match="Cube alias 'orphan' is declared"):
        build_workflow_from_text(
            """
            use "value" as a
            use "target" as b
            use "value" as orphan
            connect a.output.value to b.input.value
            """,
            output_dir=tmp_path / "out",
            cube_root=cube_root,
        )


def test_sets_disable_and_flavor_do_not_count_as_connections(tmp_path: Path) -> None:
    """Only recipe edges count toward connected alias validation."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)
    _write_target_cube(cube_root)

    with pytest.raises(RuntimeError, match="Cube alias 'a' is declared"):
        build_workflow_from_text(
            """
            use "value" as a
            use "target" as b
            set a.node.value = 2
            disable b.node
            """,
            output_dir=tmp_path / "out",
            cube_root=cube_root,
        )


def test_node_links_count_as_recipe_edges(tmp_path: Path) -> None:
    """Whole-node links connect aliases for validation purposes."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)

    plan = analyze_text(
        """
        use "value" as a
        use "value" as b
        set b.node = a.node
        """,
        cube_root=cube_root,
    )

    validate_connected_recipe(plan)


def test_comfy_artifacts_include_prompt_and_sugarcubes_workflow(tmp_path: Path) -> None:
    """The public artifact API returns executable and placed UI workflows."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)
    _write_target_cube(cube_root)

    artifacts = build_comfy_artifacts_from_text(
        """
        use "value" as a
        use "target" as b
        connect a.output.value to b.input.value
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    workflow = artifacts["workflow"]
    assert artifacts["prompt"]
    assert {node["type"] for node in workflow["nodes"]} >= {
        "SugarCubes.CubeInput",
        "SugarCubes.CubeOutput",
    }
    assert workflow["groups"][0]["sugarcubes"]["managed"] is True
    assert workflow["groups"][0]["sugarcubes"]["dsl_live"] is False
    assert workflow["groups"][0]["sugarcubes"]["implementation_dirty"] is False
    assert workflow["last_node_id"] == max(node["id"] for node in workflow["nodes"])
    assert all(isinstance(link, list) and len(link) == 6 for link in workflow["links"])


def test_ui_workflow_group_bounds_cover_fallback_placed_nodes(
    tmp_path: Path,
) -> None:
    """Managed groups should include nodes that did not have authored layout."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_value_cube(cube_root)
    write_cube(
        cube_root / "fallback_target.cube",
        {
            "cube_id": "fallback_target",
            "version": "1.0.0",
            "nodes": {
                "node": {"class_type": "TargetNode", "inputs": {"value": None}},
                "fallback": {
                    "class_type": "FallbackNode",
                    "inputs": {"value": ["node", 0]},
                },
            },
            "inputs": {"input.value": [["node", "value"]]},
            "layout": {
                "origin": [0, 0],
                "nodes": {"node": {"pos": [20, 80], "size": [180, 60]}},
                "markers": {"input.value": {"pos": [20, 20], "size": [140, 46]}},
            },
        },
    )

    workflow = build_comfy_artifacts_from_text(
        """
        use "value" as a
        use "fallback_target" as b
        connect a.output.value to b.input.value
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )["workflow"]

    fallback_node = next(node for node in workflow["nodes"] if node["type"] == "FallbackNode")
    group = next(group for group in workflow["groups"] if group["title"] == "b")
    x, y, width, height = group["bounding"]
    node_x, node_y = fallback_node["pos"]
    node_width, node_height = fallback_node["size"]
    assert x <= node_x
    assert y <= node_y
    assert x + width >= node_x + node_width
    assert y + height >= node_y + node_height
