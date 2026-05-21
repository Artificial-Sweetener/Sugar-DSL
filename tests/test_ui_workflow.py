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
"""Tests for Sugar's authored Comfy UI workflow artifact generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.fixtures.cubes import write_cube
from sugar.api.builder import ComfyArtifacts, build_comfy_artifacts_from_text

Payload = dict[str, Any]

UUID_WRAPPER = "94f725d5-39bf-4060-be68-f573214a2055"


def _source_cube_payload() -> Payload:
    """Return a compact SugarCube with an authored wrapper node and layout."""

    return {
        "cube_id": "source",
        "version": "1.0.0",
        "metadata": {"default_alias": "Source Cube", "target_model": "SDXL"},
        "nodes": {
            "text": {
                "class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "original"},
            },
            "wrapper": {
                "class_type": UUID_WRAPPER,
                "inputs": {"text": ["text", 0]},
            },
            "consumer": {
                "class_type": "ImageConsumer",
                "inputs": {"image": ["wrapper", 0]},
            },
        },
        "outputs": {"output.image": ["consumer", 0]},
        "definitions": {
            "PrimitiveStringMultiline": {
                "input": {"required": {"value": ["STRING"]}},
                "input_order": {"required": ["value"]},
                "output": ["STRING"],
                "output_name": ["STRING"],
                "python_module": "custom_nodes.ComfyUI-Primitive",
            },
            "ImageConsumer": {
                "input": {"required": {"image": ["IMAGE"]}},
                "input_order": {"required": ["image"]},
                "output": ["IMAGE"],
                "output_name": ["IMAGE"],
                "python_module": "custom_nodes.example",
            },
        },
        "subgraphs": [
            {
                "id": UUID_WRAPPER,
                "version": 1,
                "revision": 0,
                "state": {},
                "config": {},
                "name": "Wrapped Image",
                "inputNode": {"id": -10},
                "outputNode": {"id": -20},
                "inputs": [{"name": "text", "type": "STRING", "linkIds": [1]}],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "linkIds": [2]}],
                "widgets": [],
                "nodes": [
                    {
                        "id": 1,
                        "type": "RegexExtract",
                        "inputs": [{"name": "text", "link": 1}],
                        "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}],
                    }
                ],
                "links": [
                    [1, -10, 0, 1, "text", "STRING"],
                    [2, 1, 0, -20, 0, "IMAGE"],
                ],
                "floatingLinks": [],
                "reroutes": [],
                "extra": {},
            }
        ],
        "layout": {
            "nodes": {
                "text": {
                    "id": "10",
                    "class_type": "PrimitiveStringMultiline",
                    "pos": [40, 120],
                    "size": [220, 120],
                    "title": "text",
                    "flags": {},
                },
                "wrapper": {
                    "id": "11",
                    "class_type": UUID_WRAPPER,
                    "pos": [300, 120],
                    "size": [270, 180],
                    "title": "wrapped image",
                    "flags": {"collapsed": True},
                },
                "consumer": {
                    "id": "13",
                    "class_type": "ImageConsumer",
                    "pos": [620, 120],
                    "size": [220, 80],
                    "title": "consumer",
                    "flags": {},
                },
            },
            "markers": {
                "output.image": {
                    "id": "12",
                    "class_type": "SugarCubes.CubeOutput",
                    "kind": "output",
                    "pos": [620, 0],
                    "size": [270, 90],
                    "title": "IMAGE Output",
                    "style": {"color": "#2a363b", "bgcolor": "#3f5159"},
                }
            },
            "groups": [
                {
                    "id": 1,
                    "title": "Source Cube",
                    "bounding": [-10, -60, 920, 420],
                    "color": "#3f789e",
                    "font_size": 24,
                    "flags": {},
                    "sugarcubes": {
                        "schema": 5,
                        "managed": True,
                        "bounds": {
                            "x": -10,
                            "y": -60,
                            "w": 920,
                            "h": 420,
                            "padding": {"x": 2, "y": 2, "top_extra": 0},
                            "header": {"height": 32},
                        },
                    },
                }
            ],
        },
    }


def _sink_cube_payload() -> Payload:
    """Return a sink cube with one authored input marker target."""

    return {
        "cube_id": "sink",
        "version": "1.0.0",
        "metadata": {"default_alias": "Sink Cube", "target_model": "SDXL"},
        "nodes": {
            "save": {
                "class_type": "SaveImage",
                "inputs": {"images": None},
            }
        },
        "inputs": {"input.image": [["save", "images"]]},
        "definitions": {
            "SaveImage": {
                "input": {"required": {"images": ["IMAGE"]}},
                "input_order": {"required": ["images"]},
                "output": [],
                "output_name": [],
                "python_module": "nodes",
            }
        },
        "layout": {
            "nodes": {
                "save": {
                    "id": "20",
                    "class_type": "SaveImage",
                    "pos": [300, 120],
                    "size": [220, 80],
                    "title": "save",
                    "flags": {},
                }
            },
            "markers": {
                "input.image": {
                    "id": "21",
                    "class_type": "SugarCubes.CubeInput",
                    "kind": "input",
                    "pos": [0, 0],
                    "size": [270, 90],
                    "title": "IMAGE Input",
                    "style": {"color": "#2a363b", "bgcolor": "#3f5159"},
                }
            },
            "groups": [
                {
                    "id": 2,
                    "title": "Sink Cube",
                    "bounding": [-10, -60, 620, 320],
                    "color": "#3f789e",
                    "font_size": 24,
                    "flags": {},
                    "sugarcubes": {
                        "schema": 5,
                        "managed": True,
                        "bounds": {
                            "x": -10,
                            "y": -60,
                            "w": 620,
                            "h": 320,
                            "padding": {"x": 2, "y": 2, "top_extra": 0},
                            "header": {"height": 32},
                        },
                    },
                }
            ],
        },
    }


def _write_ui_workflow_cubes(cube_root: Path) -> None:
    """Write source and sink cubes used by UI workflow tests."""

    write_cube(cube_root / "source.cube", _source_cube_payload())
    write_cube(cube_root / "sink.cube", _sink_cube_payload())


def _build_artifacts(cube_root: Path, tmp_path: Path) -> ComfyArtifacts:
    """Build prompt and UI workflow artifacts for the connected fixture recipe."""

    return build_comfy_artifacts_from_text(
        """
        use "source" as src
        use "sink" as out
        connect src.output.image to out.input.image
        set src.text.value = "changed"
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )


def _widget_control_cube_payload() -> Payload:
    """Return a cube that exercises Comfy UI seed-control widget serialization."""

    return {
        "cube_id": "widget_controls",
        "version": "1.0.0",
        "nodes": {
            "seed_node": {
                "class_type": "ImplicitSeedNode",
                "inputs": {"seed": 123, "steps": 20},
            },
            "noise_seed_node": {
                "class_type": "ImplicitNoiseSeedNode",
                "inputs": {"noise_seed": 456, "steps": 30},
            },
            "string_seed_node": {
                "class_type": "StringSeedNode",
                "inputs": {"seed": "literal-seed", "mode": "mode-value"},
            },
        },
        "outputs": {"output.value": ["seed_node", 0]},
        "definitions": {
            "ImplicitSeedNode": {
                "input": {
                    "required": {
                        "seed": ["INT", {"default": 0}],
                        "steps": ["INT", {"default": 20}],
                    }
                },
                "input_order": {"required": ["seed", "steps"]},
                "output": ["INT"],
                "output_name": ["INT"],
                "python_module": "custom_nodes.example",
            },
            "ImplicitNoiseSeedNode": {
                "input": {
                    "required": {
                        "noise_seed": ["INT", {"default": 0}],
                        "steps": ["INT", {"default": 20}],
                    }
                },
                "input_order": {"required": ["noise_seed", "steps"]},
                "output": ["INT"],
                "output_name": ["INT"],
                "python_module": "custom_nodes.example",
            },
            "StringSeedNode": {
                "input": {
                    "required": {
                        "seed": ["STRING", {"default": ""}],
                        "mode": ["STRING", {"default": ""}],
                    }
                },
                "input_order": {"required": ["seed", "mode"]},
                "output": ["STRING"],
                "output_name": ["STRING"],
                "python_module": "custom_nodes.example",
            },
        },
        "layout": {
            "nodes": {
                "seed_node": {
                    "id": "30",
                    "class_type": "ImplicitSeedNode",
                    "pos": [0, 80],
                    "size": [240, 100],
                    "title": "seed",
                    "flags": {},
                },
                "noise_seed_node": {
                    "id": "31",
                    "class_type": "ImplicitNoiseSeedNode",
                    "pos": [280, 80],
                    "size": [240, 100],
                    "title": "noise seed",
                    "flags": {},
                },
                "string_seed_node": {
                    "id": "32",
                    "class_type": "StringSeedNode",
                    "pos": [560, 80],
                    "size": [240, 100],
                    "title": "string seed",
                    "flags": {},
                },
            },
            "markers": {
                "output.value": {
                    "id": "33",
                    "class_type": "SugarCubes.CubeOutput",
                    "kind": "output",
                    "pos": [840, 0],
                    "size": [270, 90],
                    "title": "VALUE Output",
                }
            },
            "groups": [_group_payload("Widget Controls", 1140, 300)],
        },
    }


def test_ui_workflow_preserves_authored_wrapper_and_subgraph_definition(
    tmp_path: Path,
) -> None:
    """UI workflows keep wrapper nodes while API prompts still expand them."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_ui_workflow_cubes(cube_root)

    artifacts = _build_artifacts(cube_root, tmp_path)
    prompt_types = {node["class_type"] for node in artifacts["prompt"].values()}
    workflow_types = {node["type"] for node in artifacts["workflow"]["nodes"]}

    assert UUID_WRAPPER not in prompt_types
    assert "RegexExtract" in prompt_types
    assert UUID_WRAPPER in workflow_types
    assert "RegexExtract" not in workflow_types
    assert artifacts["workflow"]["definitions"]["subgraphs"][0]["id"] == UUID_WRAPPER


def test_ui_workflow_emits_sugarcubes_markers_groups_and_typed_slots(
    tmp_path: Path,
) -> None:
    """UI workflows use SugarCubes marker shape, group metadata, and slot types."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_ui_workflow_cubes(cube_root)

    workflow = _build_artifacts(cube_root, tmp_path)["workflow"]
    output_marker = next(
        node for node in workflow["nodes"] if node["type"] == "SugarCubes.CubeOutput"
    )
    input_marker = next(
        node for node in workflow["nodes"] if node["type"] == "SugarCubes.CubeInput"
    )
    wrapper_node = next(node for node in workflow["nodes"] if node["type"] == UUID_WRAPPER)
    text_node = next(
        node for node in workflow["nodes"] if node["type"] == "PrimitiveStringMultiline"
    )

    assert [slot["name"] for slot in output_marker["inputs"]] == ["value"]
    assert [slot["name"] for slot in output_marker["outputs"]] == ["value"]
    assert output_marker["inputs"][0]["type"] == "IMAGE"
    assert output_marker["outputs"][0]["type"] == "IMAGE"
    assert output_marker["widgets_values"][:3] == ["source", "Source Cube", "src"]
    assert input_marker["inputs"][0]["type"] == "IMAGE"
    assert input_marker["outputs"][0]["type"] == "IMAGE"

    assert wrapper_node["inputs"][0]["name"] == "text"
    assert wrapper_node["inputs"][0]["type"] == "STRING"
    assert wrapper_node["outputs"][0]["name"] == "IMAGE"
    assert wrapper_node["outputs"][0]["type"] == "IMAGE"
    assert text_node["widgets_values"] == ["changed"]

    [source_group, sink_group] = workflow["groups"]
    assert source_group["bounding"] == [150.0, 320.0, 920.0, 420.0]
    assert source_group["sugarcubes"]["bounds"]["padding"] == {
        "x": 2,
        "y": 2,
        "top_extra": 0,
    }
    assert source_group["sugarcubes"]["bounds"]["header"] == {"height": 32}
    assert source_group["sugarcubes"]["managed"] is True
    assert sink_group["sugarcubes"]["markers"]["inputs"] == [str(input_marker["id"])]


def test_ui_workflow_emits_implicit_seed_control_widget_values(
    tmp_path: Path,
) -> None:
    """UI workflow widgets should mirror Comfy's implicit INT seed controls."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "widget_controls.cube", _widget_control_cube_payload())

    artifacts = build_comfy_artifacts_from_text(
        """
        use "widget_controls" as controls
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    workflow = artifacts["workflow"]
    seed_node = next(node for node in workflow["nodes"] if node["type"] == "ImplicitSeedNode")
    noise_seed_node = next(
        node for node in workflow["nodes"] if node["type"] == "ImplicitNoiseSeedNode"
    )
    string_seed_node = next(node for node in workflow["nodes"] if node["type"] == "StringSeedNode")

    assert seed_node["widgets_values"] == [123, "randomize", 20]
    assert noise_seed_node["widgets_values"] == [456, "randomize", 30]
    assert string_seed_node["widgets_values"] == ["literal-seed", "mode-value"]


def test_ui_workflow_preserves_authored_node_mode(tmp_path: Path) -> None:
    """UI projection should preserve LiteGraph mode stored on implementation nodes."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "mode_cube.cube",
        {
            "cube_id": "mode_cube",
            "version": "1.0.0",
            "nodes": {
                "vae_override": {
                    "class_type": "VAELoader",
                    "mode": 4,
                    "inputs": {"vae_name": "override.vae.safetensors"},
                }
            },
            "outputs": {"output.vae": ["vae_override", 0]},
            "definitions": {
                "VAELoader": {
                    "input": {"required": {"vae_name": ["LIST"]}},
                    "input_order": {"required": ["vae_name"]},
                    "output": ["VAE"],
                    "output_name": ["VAE"],
                }
            },
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "mode_cube" as m',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    node = next(node for node in artifacts["workflow"]["nodes"] if node["type"] == "VAELoader")

    assert node["mode"] == 4
    assert node["widgets_values"] == ["override.vae.safetensors"]


def test_ui_workflow_generated_disabled_mode_overrides_authored_mode(
    tmp_path: Path,
) -> None:
    """DSL-generated UI mode should take priority over cube-authored node mode."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "mode_cube.cube",
        {
            "cube_id": "mode_cube",
            "version": "1.0.0",
            "nodes": {
                "middle": {
                    "class_type": "MiddleNode",
                    "mode": 2,
                    "inputs": {"image": None},
                }
            },
            "outputs": {"output.image": "middle"},
            "definitions": {
                "MiddleNode": {
                    "input": {"required": {"image": ["IMAGE"]}},
                    "output": ["IMAGE"],
                    "output_name": ["IMAGE"],
                }
            },
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        """
        use "mode_cube" as m
        disable m.middle
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    node = next(node for node in artifacts["workflow"]["nodes"] if node["type"] == "MiddleNode")

    assert node["mode"] == 4


def test_ui_workflow_enable_overrides_authored_bypass_mode(
    tmp_path: Path,
) -> None:
    """Explicit enable should display authored bypass nodes as active."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "mode_cube.cube",
        {
            "cube_id": "mode_cube",
            "version": "1.0.0",
            "nodes": {
                "middle": {
                    "class_type": "MiddleNode",
                    "mode": 4,
                    "inputs": {"image": None},
                }
            },
            "outputs": {"output.image": "middle"},
            "definitions": {
                "MiddleNode": {
                    "input": {"required": {"image": ["IMAGE"]}},
                    "output": ["IMAGE"],
                    "output_name": ["IMAGE"],
                }
            },
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        """
        use "mode_cube" as m
        enable m.middle
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    node = next(node for node in artifacts["workflow"]["nodes"] if node["type"] == "MiddleNode")

    assert node["mode"] == 0


def test_ui_workflow_invalid_authored_mode_falls_back_to_layout_mode(
    tmp_path: Path,
) -> None:
    """Invalid authored mode values should not replace valid layout metadata."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "mode_cube.cube",
        {
            "cube_id": "mode_cube",
            "version": "1.0.0",
            "nodes": {
                "node": {
                    "class_type": "ModeNode",
                    "mode": "bad",
                    "inputs": {},
                }
            },
            "outputs": {"output.value": "node"},
            "definitions": {
                "ModeNode": {
                    "output": ["VALUE"],
                    "output_name": ["VALUE"],
                }
            },
            "layout": {
                "nodes": {
                    "node": {
                        "id": "1",
                        "class_type": "ModeNode",
                        "mode": 2,
                    }
                }
            },
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "mode_cube" as m',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    node = next(node for node in artifacts["workflow"]["nodes"] if node["type"] == "ModeNode")

    assert node["mode"] == 2


def test_ui_workflow_copies_inherited_checkpoint_values_without_cross_cube_links(
    tmp_path: Path,
) -> None:
    """Inherited disabled checkpoints stay local and display the provider model."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_inherited_checkpoint_cubes(cube_root)

    artifacts = build_comfy_artifacts_from_text(
        """
        use "stage_one" as A
        use "stage_two" as B
        connect A.output.image to B.input.image
        disable B.checkpoint
        disable B.optional_passthrough
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    workflow = artifacts["workflow"]
    b_checkpoint = next(
        node
        for node in workflow["nodes"]
        if node["type"] == "CheckpointLoaderSimple" and node["title"] == "B checkpoint"
    )
    b_wrapper = next(
        node
        for node in workflow["nodes"]
        if node["type"] == "WrapperNode" and node["title"] == "B wrapper"
    )
    optional = next(node for node in workflow["nodes"] if node["type"] == "OptionalPassthrough")

    assert b_checkpoint["widgets_values"] == ["model-a.safetensors"]
    assert b_checkpoint["mode"] == 0
    assert optional["mode"] == 4

    wrapper_input_links = {
        slot["name"]: slot["link"] for slot in b_wrapper["inputs"] if slot["link"]
    }
    link_by_id = {link[0]: link for link in workflow["links"]}
    model_link = link_by_id[wrapper_input_links["model_in"]]
    clip_link = link_by_id[wrapper_input_links["clip_in"]]
    assert model_link[1] == b_checkpoint["id"]
    assert clip_link[1] == b_checkpoint["id"]


def _write_inherited_checkpoint_cubes(cube_root: Path) -> None:
    """Write cubes that exercise UI-only inheritance projection."""

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
                    "class_type": "WrapperNode",
                    "inputs": {
                        "model_in": ["checkpoint", 0],
                        "clip_in": ["checkpoint", 1],
                    },
                },
                "image": {
                    "class_type": "ImageSource",
                    "inputs": {"model": ["wrapper", 0]},
                },
            },
            "outputs": {"output.image": ["image", 0]},
            "definitions": _inherited_checkpoint_definitions(),
            "layout": {
                "nodes": {
                    "checkpoint": {
                        "id": "1",
                        "class_type": "CheckpointLoaderSimple",
                        "pos": [0, 80],
                        "size": [320, 110],
                        "title": "A checkpoint",
                        "flags": {},
                    },
                    "wrapper": {
                        "id": "4",
                        "class_type": "WrapperNode",
                        "pos": [360, 80],
                        "size": [260, 140],
                        "title": "A wrapper",
                        "flags": {},
                    },
                    "image": {
                        "id": "5",
                        "class_type": "ImageSource",
                        "pos": [660, 80],
                        "size": [220, 80],
                        "title": "image",
                        "flags": {},
                    },
                },
                "markers": {
                    "output.image": {
                        "id": "2",
                        "class_type": "SugarCubes.CubeOutput",
                        "kind": "output",
                        "pos": [920, 0],
                        "size": [270, 90],
                        "title": "IMAGE Output",
                    },
                },
                "groups": [_group_payload("Stage One", 1220, 360)],
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
                "wrapper": {
                    "class_type": "WrapperNode",
                    "inputs": {
                        "model_in": ["checkpoint", 0],
                        "clip_in": ["checkpoint", 1],
                    },
                },
                "optional_passthrough": {
                    "class_type": "OptionalPassthrough",
                    "inputs": {"value": ["checkpoint", 0]},
                },
                "image_sink": {
                    "class_type": "ImageSink",
                    "inputs": {"image": None},
                },
            },
            "inputs": {"input.image": [["image_sink", "image"]]},
            "definitions": {
                **_inherited_checkpoint_definitions(),
                "OptionalPassthrough": {
                    "input": {"required": {"value": ["MODEL"]}},
                    "input_order": {"required": ["value"]},
                    "output": ["MODEL"],
                    "output_name": ["MODEL"],
                    "python_module": "custom_nodes.example",
                },
                "ImageSink": {
                    "input": {"required": {"image": ["IMAGE"]}},
                    "input_order": {"required": ["image"]},
                    "output": [],
                    "output_name": [],
                    "python_module": "custom_nodes.example",
                },
            },
            "layout": {
                "nodes": {
                    "checkpoint": {
                        "id": "10",
                        "class_type": "CheckpointLoaderSimple",
                        "pos": [0, 100],
                        "size": [320, 110],
                        "title": "B checkpoint",
                        "flags": {},
                    },
                    "wrapper": {
                        "id": "11",
                        "class_type": "WrapperNode",
                        "pos": [360, 100],
                        "size": [260, 140],
                        "title": "B wrapper",
                        "flags": {},
                    },
                    "optional_passthrough": {
                        "id": "12",
                        "class_type": "OptionalPassthrough",
                        "pos": [360, 280],
                        "size": [220, 80],
                        "title": "optional",
                        "flags": {},
                    },
                    "image_sink": {
                        "id": "15",
                        "class_type": "ImageSink",
                        "pos": [660, 100],
                        "size": [220, 80],
                        "title": "image sink",
                        "flags": {},
                    },
                },
                "markers": {
                    "input.image": {
                        "id": "13",
                        "class_type": "SugarCubes.CubeInput",
                        "kind": "input",
                        "pos": [0, 0],
                        "size": [270, 90],
                        "title": "IMAGE Input",
                    },
                },
                "groups": [_group_payload("Stage Two", 920, 560)],
            },
        },
    )


def _inherited_checkpoint_definitions() -> dict[str, Any]:
    """Return compact definitions for inherited-checkpoint fixture nodes."""

    return {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": ["LIST"]}},
            "input_order": {"required": ["ckpt_name"]},
            "output": ["MODEL", "CLIP", "VAE"],
            "output_name": ["MODEL", "CLIP", "VAE"],
            "python_module": "nodes",
        },
        "WrapperNode": {
            "input": {
                "required": {
                    "model_in": ["MODEL"],
                    "clip_in": ["CLIP"],
                }
            },
            "input_order": {"required": ["model_in", "clip_in"]},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
            "python_module": "custom_nodes.example",
        },
        "ImageSource": {
            "input": {"required": {"model": ["MODEL"]}},
            "input_order": {"required": ["model"]},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
            "python_module": "custom_nodes.example",
        },
    }


def _group_payload(title: str, width: int, height: int) -> dict[str, Any]:
    """Return authored SugarCubes group chrome for UI tests."""

    return {
        "id": 1,
        "title": title,
        "bounding": [-10, -60, width, height],
        "color": "#3f789e",
        "font_size": 24,
        "flags": {},
        "sugarcubes": {
            "schema": 5,
            "managed": True,
            "bounds": {
                "x": -10,
                "y": -60,
                "w": width,
                "h": height,
                "padding": {"x": 2, "y": 2, "top_extra": 0},
                "header": {"height": 32},
            },
        },
    }
