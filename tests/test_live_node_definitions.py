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
"""Regression tests for live-definition-aware Sugar compilation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_comfy_artifacts_from_text
from sugar.compiler.errors import SugarCompilerError
from sugar.compiler.live_definitions import (
    LiveNodeDefinition,
    LiveNodeInputDefinition,
)


class _Provider:
    """Serve fixed live node definitions to compiler tests."""

    def __init__(self, definitions: Mapping[str, LiveNodeDefinition]) -> None:
        """Store definitions keyed by class type."""

        self._definitions = definitions

    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        """Return a test live definition by class type."""

        return self._definitions.get(class_type)


def test_live_only_explicit_override_succeeds(tmp_path: Path) -> None:
    """Script-authored values may target inputs absent from old cube artifacts."""

    cube_root = _write_live_cube(tmp_path, node_inputs={"old_value": "authored"})

    artifacts = build_comfy_artifacts_from_text(
        """
        use "live_cube" as Demo
        set Demo.processor.new_widget = "chosen value"
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {
                "old_value": _input("old_value", default="live"),
                "new_widget": _input("new_widget", default="live default"),
            },
        ),
    )

    assert _node_inputs(artifacts["prompt"], "LiveNode")["new_widget"] == "chosen value"


def test_unknown_input_absent_from_cube_and_live_definition_fails(tmp_path: Path) -> None:
    """Live definitions extend, but do not relax, strict input validation."""

    cube_root = _write_live_cube(tmp_path, node_inputs={})

    with pytest.raises(RuntimeError, match="missing_widget"):
        build_comfy_artifacts_from_text(
            """
            use "live_cube" as Demo
            set Demo.processor.missing_widget = "chosen value"
            """,
            output_dir=tmp_path / "out",
            cube_root=cube_root,
            live_node_definition_provider=_provider(
                "LiveNode",
                {"known_widget": _input("known_widget", default="live default")},
            ),
        )


def test_missing_live_only_input_uses_live_default(tmp_path: Path) -> None:
    """Old cubes receive current Comfy defaults for newly declared widgets."""

    cube_root = _write_live_cube(tmp_path, node_inputs={})

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {"new_widget": _input("new_widget", default=42, value_type="INT")},
        ),
    )

    assert _node_inputs(artifacts["prompt"], "LiveNode")["new_widget"] == 42


def test_script_override_wins_over_cube_and_live_defaults(tmp_path: Path) -> None:
    """Explicit script values remain the highest-priority input source."""

    cube_root = _write_live_cube(tmp_path, node_inputs={"shared": "cube value"})

    artifacts = build_comfy_artifacts_from_text(
        """
        use "live_cube" as Demo
        set Demo.processor.shared = "script value"
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {"shared": _input("shared", default="live value")},
        ),
    )

    assert _node_inputs(artifacts["prompt"], "LiveNode")["shared"] == "script value"


def test_cube_authored_value_wins_over_live_default(tmp_path: Path) -> None:
    """Cube-authored defaults remain more specific than live widget defaults."""

    cube_root = _write_live_cube(tmp_path, node_inputs={"shared": "cube value"})

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {"shared": _input("shared", default="live value")},
        ),
    )

    assert _node_inputs(artifacts["prompt"], "LiveNode")["shared"] == "cube value"


def test_required_live_input_without_safe_default_fails(tmp_path: Path) -> None:
    """Required live widgets without values fail before prompt queueing."""

    cube_root = _write_live_cube(tmp_path, node_inputs={})

    with pytest.raises(SugarCompilerError) as error_info:
        build_comfy_artifacts_from_text(
            'use "live_cube" as Demo',
            output_dir=tmp_path / "out",
            cube_root=cube_root,
            live_node_definition_provider=_provider(
                "LiveNode",
                {
                    "required_widget": LiveNodeInputDefinition(
                        name="required_widget",
                        value_type="FLOAT",
                        required=True,
                        default=None,
                        has_default=False,
                    )
                },
            ),
        )

    assert error_info.value.code == "sugar-live-default-missing"
    assert error_info.value.cube_alias == "Demo"
    assert error_info.value.cube_id == "live_cube"
    assert error_info.value.input_name == "required_widget"


def test_expanded_subgraph_required_live_input_without_default_is_omitted(
    tmp_path: Path,
) -> None:
    """Expanded subgraph helper inputs are not forced into old cube bodies."""

    cube_root = _write_live_cube(
        tmp_path,
        node_key="upscale_by_factor.__sg_get_new_height_2205",
        node_inputs={"expression": "a * b"},
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {
                "expression": _input("expression", default="a * b"),
                "values": LiveNodeInputDefinition(
                    name="values",
                    value_type="FLOAT",
                    required=True,
                    default=None,
                    has_default=False,
                ),
            },
        ),
    )

    inputs = _node_inputs(artifacts["prompt"], "LiveNode")
    assert inputs == {"expression": "a * b"}


def test_grouped_subgraph_inputs_preserve_live_autogrow_socket_names(
    tmp_path: Path,
) -> None:
    """Autogrow subgraph links keep the grouped prompt names Comfy validates."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "live_cube.cube",
        {
            "cube_id": "live_cube",
            "version": "1.0.0",
            "nodes": {
                "source": {
                    "class_type": "SourceNode",
                    "inputs": {},
                },
                "upscale_by_factor.__sg_math_2205": {
                    "class_type": "ComfyMathExpression",
                    "inputs": {
                        "expression": "a * b",
                        "values.a": ["source", 0],
                        "values.b": 2.0,
                    },
                },
            },
            "outputs": {"output.value": "upscale_by_factor.__sg_math_2205"},
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "ComfyMathExpression",
            {
                "expression": _input("expression", default="a * b"),
                "values": LiveNodeInputDefinition(
                    name="values",
                    value_type="COMFY_AUTOGROW_V3",
                    required=True,
                    default=None,
                    has_default=False,
                    raw={"template": {"names": ["a", "b", "c"]}},
                ),
            },
        ),
    )

    inputs = _node_inputs(artifacts["prompt"], "ComfyMathExpression")
    assert set(inputs) == {"expression", "values.a", "values.b"}
    assert inputs["expression"] == "a * b"
    assert inputs["values.b"] == 2.0
    assert isinstance(inputs["values.a"], list)


def test_grouped_subgraph_inputs_preserve_embedded_autogrow_socket_names_without_live_provider(
    tmp_path: Path,
) -> None:
    """Standalone compiles preserve grouped prompt names from authored cubes."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "live_cube.cube",
        {
            "cube_id": "live_cube",
            "version": "1.0.0",
            "definitions": {
                "ComfyMathExpression": {
                    "input": {
                        "required": {
                            "expression": ["STRING", {"default": "a + b"}],
                            "values": [
                                "COMFY_AUTOGROW_V3",
                                {"names": ["a", "b", "c"], "min": 1},
                            ],
                        }
                    }
                }
            },
            "nodes": {
                "source": {
                    "class_type": "SourceNode",
                    "inputs": {},
                },
                "upscale_by_factor.__sg_math_2205": {
                    "class_type": "ComfyMathExpression",
                    "inputs": {
                        "expression": "a * b",
                        "values.a": ["source", 0],
                        "values.b": 2.0,
                    },
                },
            },
            "outputs": {"output.value": "upscale_by_factor.__sg_math_2205"},
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    inputs = _node_inputs(artifacts["prompt"], "ComfyMathExpression")
    assert set(inputs) == {"expression", "values.a", "values.b"}
    assert inputs["expression"] == "a * b"
    assert inputs["values.b"] == 2.0
    assert isinstance(inputs["values.a"], list)


def test_required_graph_socket_without_default_is_omitted(tmp_path: Path) -> None:
    """Live graph sockets are omitted when Sugar has no connection to author."""

    cube_root = _write_live_cube(tmp_path, node_inputs={})

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {
                "image": LiveNodeInputDefinition(
                    name="image",
                    value_type="IMAGE",
                    required=True,
                    default=None,
                    has_default=False,
                )
            },
        ),
    )

    assert "image" not in _node_inputs(artifacts["prompt"], "LiveNode")


def test_optional_live_input_without_default_is_omitted(tmp_path: Path) -> None:
    """Optional live widgets can remain absent when Comfy accepts omission."""

    cube_root = _write_live_cube(tmp_path, node_inputs={})

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {
                "optional_widget": LiveNodeInputDefinition(
                    name="optional_widget",
                    value_type="STRING",
                    required=False,
                    default=None,
                    has_default=False,
                )
            },
        ),
    )

    assert "optional_widget" not in _node_inputs(artifacts["prompt"], "LiveNode")


def test_stale_cube_input_is_pruned_from_api_prompt(tmp_path: Path) -> None:
    """Inputs absent from a current live definition are removed before API output."""

    cube_root = _write_live_cube(
        tmp_path,
        node_inputs={"current": "keep", "removed": "drop"},
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=_provider(
            "LiveNode",
            {"current": _input("current", default="live")},
        ),
    )

    inputs = _node_inputs(artifacts["prompt"], "LiveNode")
    assert inputs == {"current": "keep"}


def test_existing_behavior_is_unchanged_without_live_provider(tmp_path: Path) -> None:
    """Standalone Sugar compilation keeps authored inputs when no provider exists."""

    cube_root = _write_live_cube(
        tmp_path,
        node_inputs={"current": "keep", "removed": "still present"},
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    inputs = _node_inputs(artifacts["prompt"], "LiveNode")
    assert inputs["removed"] == "still present"


def _write_live_cube(
    tmp_path: Path,
    *,
    node_inputs: dict[str, Any],
    node_key: str = "processor",
) -> Path:
    """Write a single-node cube fixture with intentionally stale definitions."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "live_cube.cube",
        {
            "cube_id": "live_cube",
            "version": "1.0.0",
            "nodes": {
                node_key: {
                    "class_type": "LiveNode",
                    "inputs": dict(node_inputs),
                }
            },
            "outputs": {"output.image": node_key},
        },
    )
    return cube_root


def _provider(
    class_type: str,
    inputs: Mapping[str, LiveNodeInputDefinition],
) -> _Provider:
    """Build a test provider for one class type."""

    return _Provider({class_type: LiveNodeDefinition(class_type=class_type, inputs=inputs)})


def _input(
    name: str,
    *,
    default: object,
    value_type: str = "STRING",
    required: bool = True,
) -> LiveNodeInputDefinition:
    """Return a live input with an explicit default."""

    return LiveNodeInputDefinition(
        name=name,
        value_type=value_type,
        required=required,
        default=default,
        has_default=True,
    )


def _node_inputs(prompt: Mapping[str, Any], class_type: str) -> Mapping[str, Any]:
    """Return inputs for the only prompt node with the requested class type."""

    nodes = [node for node in prompt.values() if node.get("class_type") == class_type]
    assert len(nodes) == 1
    inputs = nodes[0].get("inputs")
    assert isinstance(inputs, Mapping)
    return inputs
