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
"""Spawn plan contract tests for Sugar semantic analysis."""

import json
import logging
from pathlib import Path

import pytest

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_workflow_from_text
from sugar.catalog.models import validate_cube_document
from sugar.compiler.analyzer import analyze_text
from sugar.compiler.codegen import spawn_plan_to_workflow


def test_spawn_plan_connects_and_sets(tmp_path: Path) -> None:
    """Spawn plans record cube order, connections, and explicit set entries."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "simple.cube",
        {
            "cube_id": "simple",
            "version": "1.0.0",
            "nodes": {
                "nodeA": {"class_type": "Foo", "inputs": {"x": 1}},
            },
            "inputs": {"input.value": [["nodeA", "x"]]},
            "outputs": {"output.value": "nodeA"},
        },
    )

    dsl = """use "simple" as A
use "simple" as B
connect A.output.value to B.input.value
set B.nodeA.x = 5"""

    plan = analyze_text(dsl, cube_root=cube_root)

    assert plan["order"] == ["A", "B"]
    assert len(plan["cubes"]) == 2
    assert plan["cubes"][0]["cube_id"] == "simple"
    assert plan["cubes"][0].get("version_pin") is None
    assert plan["connections"] == [
        {
            "from": {"alias": "A", "output": "output.value"},
            "to": {"alias": "B", "input": "input.value"},
            "metadata": {"source_line": 3},
        }
    ]
    assert plan["sets"][0]["alias"] == "B"
    assert plan["sets"][0]["node"] == "nodeA"
    assert plan["sets"][0]["input"] == "x"
    assert plan["sets"][0]["value"] == 5
    assert plan["sets"][0]["metadata"]["kind"] == "explicit"


def test_spawn_plan_connects_with_quoted_aliases(tmp_path: Path) -> None:
    """Spawn plans preserve quoted aliases in connection endpoints."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "simple.cube",
        {
            "cube_id": "simple",
            "version": "1.0.0",
            "nodes": {
                "nodeA": {"class_type": "Foo", "inputs": {"x": 1}},
            },
            "inputs": {"input.value": [["nodeA", "x"]]},
            "outputs": {"output.value": "nodeA"},
        },
    )

    dsl = """use "simple" as "text to image"
use "simple" as "automask detailer"
connect "text to image".output.value to "automask detailer".input.value"""

    plan = analyze_text(dsl, cube_root=cube_root)

    assert plan["order"] == ["text to image", "automask detailer"]
    assert plan["connections"] == [
        {
            "from": {"alias": "text to image", "output": "output.value"},
            "to": {"alias": "automask detailer", "input": "input.value"},
            "metadata": {"source_line": 3},
        }
    ]


def test_explicit_set_resolves_alias_case_insensitively(tmp_path: Path) -> None:
    """Explicit set aliases should resolve to the canonical authored alias."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Foo", "inputs": {"value": 1}}},
        },
    )

    plan = analyze_text(
        """
        use image as "Text to Image"
        set "text to image".node.value = 7
        """,
        cube_root=cube_root,
    )

    assert plan["sets"][0]["alias"] == "Text to Image"
    assert plan["sets"][0]["value"] == 7


def test_connect_resolves_aliases_case_insensitively(tmp_path: Path) -> None:
    """Connection endpoint aliases should resolve to canonical authored aliases."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {"x": 1}}},
            "outputs": {"output.value": "node"},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Target", "inputs": {"x": 0}}},
            "inputs": {"input.value": [["node", "x"]]},
        },
    )

    plan = analyze_text(
        """
        use source as "Text to Image"
        use target as "Diffusion Upscale"
        connect "text to image".output.value to "diffusion upscale".input.value
        """,
        cube_root=cube_root,
    )

    assert plan["connections"] == [
        {
            "from": {"alias": "Text to Image", "output": "output.value"},
            "to": {"alias": "Diffusion Upscale", "input": "input.value"},
            "metadata": {"source_line": 4},
        }
    ]


def test_whole_node_link_resolves_aliases_case_insensitively(
    tmp_path: Path,
) -> None:
    """Whole-node links should record canonical aliases from case-insensitive refs."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "tone.cube",
        {
            "cube_id": "tone",
            "version": "1.0.0",
            "nodes": {
                "vectorscopecc": {
                    "class_type": "VectorscopeCC",
                    "inputs": {"brightness": 0.05},
                },
            },
        },
    )

    plan = analyze_text(
        """
        use tone as "Text to Image"
        use tone as "Diffusion Upscale"
        set "diffusion upscale".vectorscopecc = "text to image".vectorscopecc
        """,
        cube_root=cube_root,
    )

    assert plan["node_links"] == [
        {
            "from": {"alias": "Text to Image", "node": "vectorscopecc"},
            "to": {"alias": "Diffusion Upscale", "node": "vectorscopecc"},
            "metadata": {
                "source_line": 4,
                "from_node_key": "Text to Image.vectorscopecc",
                "to_node_key": "Diffusion Upscale.vectorscopecc",
            },
        }
    ]


def test_disable_resolves_alias_case_insensitively(tmp_path: Path) -> None:
    """Disable aliases should resolve to the canonical authored alias."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {
                "middle": {"class_type": "Middle", "inputs": {}},
                "final": {"class_type": "Final", "inputs": {"value": ["middle", 0]}},
            },
        },
    )

    plan = analyze_text(
        """
        use image as "Text to Image"
        disable "text to image".middle
        """,
        cube_root=cube_root,
    )

    assert plan["disabled"] == [
        {
            "alias": "Text to Image",
            "node": "middle",
            "metadata": {
                "node_key": "Text to Image.middle",
                "source_line": 3,
                "reason": "explicit",
            },
        }
    ]


def test_enable_resolves_alias_case_insensitively(tmp_path: Path) -> None:
    """Enable aliases should resolve to the canonical authored alias."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"middle": {"class_type": "Middle", "mode": 4, "inputs": {}}},
        },
    )

    plan = analyze_text(
        """
        use image as "Text to Image"
        enable "text to image".middle
        """,
        cube_root=cube_root,
    )

    assert plan["enabled"] == [
        {
            "alias": "Text to Image",
            "node": "middle",
            "metadata": {
                "node_key": "Text to Image.middle",
                "source_line": 3,
            },
        }
    ]
    assert plan["disabled"] == []


def test_enable_disable_conflict_is_fatal(tmp_path: Path) -> None:
    """Recipes must not contain conflicting activation commands for one node."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"middle": {"class_type": "Middle", "mode": 4, "inputs": {}}},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(
            """
            use image as A
            enable A.middle
            disable A.middle
            """,
            cube_root=cube_root,
        )

    assert "both enabled and disabled" in str(excinfo.value)


def test_unresolved_enable_target_is_fatal(tmp_path: Path) -> None:
    """Enable targets should fail closed when the node cannot be resolved."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"middle": {"class_type": "Middle", "inputs": {}}},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(
            """
            use image as A
            enable A.missing
            """,
            cube_root=cube_root,
        )

    assert "missing" in str(excinfo.value)


def test_dotted_reference_resolves_alias_case_insensitively(tmp_path: Path) -> None:
    """Dotted reference expressions should resolve aliases case-insensitively."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"source": {"class_type": "Source", "inputs": {"value": 42}}},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Target", "inputs": {"value": 0}}},
        },
    )

    plan = analyze_text(
        """
        use source as "Text to Image"
        use target as Target
        set Target.node.value = "text to image".source.value
        """,
        cube_root=cube_root,
    )

    assert plan["sets"][0]["alias"] == "Target"
    assert plan["sets"][0]["value"] == 42


def test_alias_collision_is_case_insensitive(tmp_path: Path) -> None:
    """Aliases that differ only by case should be rejected as duplicates."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Foo", "inputs": {"value": 1}}},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(
            """
            use image as "Text to Image"
            use image as "text to image"
            """,
            cube_root=cube_root,
        )

    message = str(excinfo.value)
    assert "text to image" in message
    assert "Text to Image" in message
    assert "case-insensitive" in message


def test_repeat_aliases_resolve_case_insensitively(tmp_path: Path) -> None:
    """Repeat-expanded aliases should resolve with canonical generated casing."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Foo", "inputs": {"value": 0}}},
        },
    )

    plan = analyze_text(
        """
        use image as Cube repeat 2
        set cube1.node.value = 1
        set CUBE2.node.value = 2
        """,
        cube_root=cube_root,
    )

    explicit_sets = [entry for entry in plan["sets"] if entry["metadata"]["kind"] == "explicit"]
    assert [entry["alias"] for entry in explicit_sets] == ["Cube1", "Cube2"]
    assert [entry["value"] for entry in explicit_sets] == [1, 2]


def test_unknown_alias_still_fails_with_requested_alias(tmp_path: Path) -> None:
    """Unresolved aliases should remain fatal after case-insensitive lookup."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Foo", "inputs": {"value": 1}}},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(
            """
            use image as "Text to Image"
            set "not text to image".node.value = 7
            """,
            cube_root=cube_root,
        )

    message = str(excinfo.value)
    assert "not text to image" in message
    assert "Text to Image" in message


def test_builder_preserves_canonical_alias_after_case_insensitive_set(
    tmp_path: Path,
) -> None:
    """Workflow output should keep canonical alias casing after lookup."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "image.cube",
        {
            "cube_id": "image",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Foo", "inputs": {"value": 1}}},
            "outputs": {"output.value": "node"},
        },
    )
    write_cube(
        cube_root / "sink.cube",
        {
            "cube_id": "sink",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"value": None}}},
            "inputs": {"input.value": [["sink", "value"]]},
        },
    )

    workflow = build_workflow_from_text(
        """
        use image as "Text to Image"
        use sink as out
        connect "Text to Image".output.value to out.input.value
        set "text to image".node.value = 7
        """,
        output_dir=tmp_path / "output",
        cube_root=cube_root,
    )

    node = next(iter(workflow.values()))
    assert node["inputs"]["value"] == 7
    assert node["_meta"]["title"] == "Text to Image.node"


def test_spawn_plan_records_whole_node_link_with_quoted_aliases(
    tmp_path: Path,
) -> None:
    """Whole-node link statements should be first-class spawn-plan entries."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "tone.cube",
        {
            "cube_id": "tone",
            "version": "1.0.0",
            "nodes": {
                "vectorscopecc": {
                    "class_type": "VectorscopeCC",
                    "inputs": {
                        "model": ["provider", 0],
                        "brightness": 0.05,
                        "contrast": 0,
                    },
                },
                "provider": {"class_type": "Provider", "inputs": {}},
            },
        },
    )

    dsl = """use "tone" as "text to image"
use "tone" as "diffusion upscale"
set "diffusion upscale".vectorscopecc = "text to image".vectorscopecc"""

    plan = analyze_text(dsl, cube_root=cube_root)

    assert plan["node_links"] == [
        {
            "from": {"alias": "text to image", "node": "vectorscopecc"},
            "to": {"alias": "diffusion upscale", "node": "vectorscopecc"},
            "metadata": {
                "source_line": 3,
                "from_node_key": "text to image.vectorscopecc",
                "to_node_key": "diffusion upscale.vectorscopecc",
            },
        }
    ]


def test_whole_node_link_copies_values_without_rewriting_graph_inputs(
    tmp_path: Path,
) -> None:
    """Codegen should inherit editable values but preserve target graph links."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source_tone.cube",
        {
            "cube_id": "source_tone",
            "version": "1.0.0",
            "nodes": {
                "vectorscopecc": {
                    "class_type": "VectorscopeCC",
                    "enabled": False,
                    "inputs": {
                        "model": ["provider", 0],
                        "brightness": 0.05,
                        "contrast": 0,
                    },
                },
                "provider": {"class_type": "Provider", "inputs": {}},
            },
        },
    )
    write_cube(
        cube_root / "target_tone.cube",
        {
            "cube_id": "target_tone",
            "version": "1.0.0",
            "nodes": {
                "vectorscopecc": {
                    "class_type": "VectorscopeCC",
                    "enabled": True,
                    "inputs": {
                        "model": ["provider", 0],
                        "brightness": 0.9,
                        "contrast": 0,
                    },
                },
                "provider": {"class_type": "Provider", "inputs": {}},
            },
        },
    )

    dsl = """use "source_tone" as A
use "target_tone" as B
set A.vectorscopecc.brightness = 0.25
set B.vectorscopecc.brightness = 0.9
set B.vectorscopecc = A.vectorscopecc"""

    workflow = spawn_plan_to_workflow(analyze_text(dsl, cube_root=cube_root))
    title_by_id = {
        str(node_id): ((node or {}).get("_meta") or {}).get("title")
        for node_id, node in workflow.items()
    }
    target = next(
        node
        for node in workflow.values()
        if ((node or {}).get("_meta") or {}).get("title") == "B.vectorscopecc"
    )
    target_provider_id = str(target["inputs"]["model"][0])

    assert target["inputs"]["brightness"] == 0.25
    assert target["inputs"]["contrast"] == 0
    assert target.get("enabled") is False
    assert title_by_id[target_provider_id] == "B.provider"


def test_whole_node_link_rejects_incompatible_class_types(tmp_path: Path) -> None:
    """Whole-node links should fail closed when node class types differ."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "SourceType", "inputs": {"x": 1}}},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "TargetType", "inputs": {"x": 2}}},
        },
    )

    with pytest.raises(RuntimeError, match="Node link class types differ"):
        analyze_text(
            """
            use "source" as A
            use "target" as B
            set B.node = A.node
            """,
            cube_root=cube_root,
        )


def test_whole_node_link_rejects_different_graph_input_shapes(tmp_path: Path) -> None:
    """Whole-node links should reject literal-vs-graph and graph topology mismatches."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {
                "node": {"class_type": "Tone", "inputs": {"red": ["provider", 0]}},
                "provider": {"class_type": "Provider", "inputs": {}},
            },
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Tone", "inputs": {"red": 0.5}}},
        },
    )

    with pytest.raises(RuntimeError, match="editable input keys differ"):
        analyze_text(
            """
            use "source" as A
            use "target" as B
            set B.node = A.node
            """,
            cube_root=cube_root,
        )


def test_spawn_plan_includes_input_key_for_direct_mapping(tmp_path: Path) -> None:
    """Direct input bindings preserve the selected target input key."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "direct.cube",
        {
            "cube_id": "direct",
            "version": "1.0.0",
            "nodes": {
                "nodeA": {"class_type": "Foo", "inputs": {"x": None}},
            },
            "inputs": {"input.value": "nodeA"},
            "outputs": {"output.value": "nodeA"},
        },
    )

    dsl = """use "direct" as A
use "direct" as B
connect A.output.value to B.input.value.x"""

    plan = analyze_text(dsl, cube_root=cube_root)

    assert plan["connections"] == [
        {
            "from": {"alias": "A", "output": "output.value"},
            "to": {"alias": "B", "input": "input.value", "input_key": "x"},
            "metadata": {"source_line": 3},
        }
    ]


def test_spawn_plan_rejects_invalid_binding_keys(tmp_path: Path) -> None:
    """Catalog validation rejects invalid input binding keys."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "invalid.cube",
        {
            "cube_id": "invalid",
            "version": "1.0.0",
            "nodes": {"nodeA": {"class_type": "Foo", "inputs": {"x": 1}}},
            "inputs": {"cube.input.value": [["nodeA", "x"]]},
            "outputs": {"output.value": "nodeA"},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        validate_cube_document(json.loads((cube_root / "invalid.cube").read_text()))

    assert "invalid input binding key" in str(excinfo.value)


def test_spawn_plan_rejects_invalid_output_binding_keys(tmp_path: Path) -> None:
    """Catalog validation rejects invalid output binding keys."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "invalid_output.cube",
        {
            "cube_id": "invalid_output",
            "version": "1.0.0",
            "nodes": {"nodeA": {"class_type": "Foo", "inputs": {"x": 1}}},
            "inputs": {"input.value": [["nodeA", "x"]]},
            "outputs": {"cube.output.value": "nodeA"},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        validate_cube_document(json.loads((cube_root / "invalid_output.cube").read_text()))

    assert "invalid output binding key" in str(excinfo.value)


def test_spawn_plan_enforces_version_pin(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Version pin mismatches fail and emit analysis context."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "pinned.cube",
        {
            "cube_id": "pinned",
            "version": "1.0.0",
            "nodes": {"nodeA": {"class_type": "Foo", "inputs": {"x": 1}}},
        },
    )

    dsl = 'use "pinned"@2.0.0 as A'
    caplog.set_level(logging.ERROR, logger="sugar.compiler.analyzer")
    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(dsl, cube_root=cube_root)

    assert "version mismatch" in str(excinfo.value)
    assert caplog.records
    assert caplog.records[-1].__dict__["cube_id"] == "pinned"
    assert caplog.records[-1].__dict__["alias"] == "A"
    assert caplog.records[-1].__dict__["source_line"] == 1


def test_spawn_plan_rejects_alias_collision(tmp_path: Path) -> None:
    """Analyzer rejects duplicate aliases in one script."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "alpha.cube",
        {
            "cube_id": "alpha",
            "version": "1.0.0",
            "nodes": {"nodeA": {"class_type": "Foo", "inputs": {"x": 1}}},
        },
    )

    dsl = """use \"alpha\" as A
use \"alpha\" as A"""

    with pytest.raises(RuntimeError) as excinfo:
        analyze_text(dsl, cube_root=cube_root)

    assert "Alias 'A' already used" in str(excinfo.value)


def test_spawn_plan_inherits_disabled_checkpoint_wrapper_inputs_from_upstream_cube(
    tmp_path: Path,
) -> None:
    """Disabled checkpoint wrappers inherit model and clip from upstream cubes."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()

    write_cube(
        cube_root / "stage_one.cube",
        {
            "cube_id": "stage_one",
            "version": "1.0.0",
            "nodes": {
                "checkpoint": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "model-a.safetensors"},
                },
                "wrapper": {
                    "class_type": "Wrapper",
                    "inputs": {
                        "model_in": ["checkpoint", 0],
                        "clip_in": ["checkpoint", 1],
                    },
                },
            },
            "outputs": {
                "output.model": ["checkpoint", 0],
                "output.clip": ["checkpoint", 1],
            },
        },
    )

    write_cube(
        cube_root / "stage_two.cube",
        {
            "cube_id": "stage_two",
            "version": "1.0.0",
            "nodes": {
                "checkpoint": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "model-b.safetensors"},
                },
                "constant_model": {
                    "class_type": "PrimitiveModel",
                    "inputs": {"value": "local-model"},
                },
                "internal_model": {
                    "class_type": "ModelCarrier",
                    "inputs": {"model": ["constant_model", 0]},
                },
                "constant_clip": {
                    "class_type": "PrimitiveClip",
                    "inputs": {"value": "local-clip"},
                },
                "internal_clip": {
                    "class_type": "ClipCarrier",
                    "inputs": {"clip": ["constant_clip", 0]},
                },
                "wrapper": {
                    "class_type": "Wrapper",
                    "inputs": {
                        "model_in": ["checkpoint", 0],
                        "clip_in": ["checkpoint", 1],
                    },
                },
            },
            "inputs": {
                "input.model": [["wrapper", "model_in"]],
                "input.clip": [["wrapper", "clip_in"]],
            },
        },
    )

    dsl = """use "stage_one" as A
use "stage_two" as B
connect A.output.model to B.input.model
connect A.output.clip to B.input.clip
disable B.checkpoint"""

    plan = analyze_text(dsl, cube_root=cube_root)
    assert [entry["to"]["input"] for entry in plan["connections"]] == [
        "input.model",
        "input.clip",
    ]

    workflow = spawn_plan_to_workflow(plan, cube_root=cube_root)
    title_by_id = {
        str(node_id): ((node or {}).get("_meta") or {}).get("title")
        for node_id, node in workflow.items()
    }
    wrapper_id = next(
        node_id
        for node_id, node in workflow.items()
        if ((node or {}).get("_meta") or {}).get("title") == "B.wrapper"
    )
    wrapper_inputs = workflow[wrapper_id]["inputs"]
    assert title_by_id[str(wrapper_inputs["model_in"][0])] == "A.checkpoint"
    assert title_by_id[str(wrapper_inputs["clip_in"][0])] == "A.checkpoint"
