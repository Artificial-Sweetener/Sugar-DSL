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
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.cubes import current_cube_payload, write_cube
from sugar.api.builder import build_workflow_from_text
from sugar.catalog.models import validate_cube_document
from sugar.compiler.codegen import spawn_plan_to_workflow

Payload = dict[str, Any]

UUID_A = "94f725d5-39bf-4060-be68-f573214a2055"
UUID_B = "8db2f320-4f83-4f0b-9734-91ab1ed87cb1"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _wrapper_cube_payload(wrapper_type: str = UUID_A) -> Payload:
    """Return a wrapper cube fixture with two subgraph outputs."""

    return {
        "cube_id": "wrapper_cube",
        "version": "1.0.0",
        "nodes": {
            "source": {"class_type": "SourceNode", "inputs": {"value": 1}},
            "wrapper": {
                "class_type": wrapper_type,
                "inputs": {
                    "x": ["source", 0],
                    "y": 3,
                },
            },
            "consumer": {
                "class_type": "ConsumerNode",
                "inputs": {
                    "main": ["wrapper", 0],
                    "aux": ["wrapper", 1],
                },
            },
        },
        "outputs": {"output.main": "consumer"},
        "subgraphs": [
            {
                "id": UUID_A,
                "inputNode": {"id": -10},
                "outputNode": {"id": -20},
                "inputs": [
                    {"name": "x", "linkIds": [11]},
                    {"name": "y", "linkIds": [12]},
                ],
                "outputs": [
                    {"name": "main", "linkIds": [13]},
                    {"name": "aux", "linkIds": [14]},
                ],
                "links": [
                    [11, -10, 0, 1, "in_a", "ANY"],
                    [12, -10, 1, 1, "in_b", "ANY"],
                    [13, 1, 0, -20, 0, "ANY"],
                    [14, 1, 1, -20, 1, "ANY"],
                ],
                "nodes": [
                    {
                        "id": 1,
                        "type": "DualOut",
                        "inputs": [
                            {"name": "in_a", "link": 11},
                            {"name": "in_b", "link": 12},
                        ],
                    }
                ],
            }
        ],
    }


def _nested_wrapper_cube_payload() -> Payload:
    """Return a wrapper cube fixture whose subgraph contains another wrapper."""

    payload = _wrapper_cube_payload(wrapper_type=UUID_A)
    payload["subgraphs"] = [
        {
            "id": UUID_A,
            "inputNode": {"id": -10},
            "outputNode": {"id": -20},
            "inputs": [{"name": "x", "linkIds": [21]}],
            "outputs": [{"name": "main", "linkIds": [22]}],
            "links": [
                [21, -10, 0, 1, "z", "ANY"],
                [22, 1, 0, -20, 0, "ANY"],
            ],
            "nodes": [
                {
                    "id": 1,
                    "type": UUID_B,
                    "inputs": [{"name": "z", "link": 21}],
                }
            ],
        },
        {
            "id": UUID_B,
            "inputNode": {"id": -10},
            "outputNode": {"id": -20},
            "inputs": [{"name": "z", "linkIds": [31]}],
            "outputs": [{"name": "out", "linkIds": [32]}],
            "links": [
                [31, -10, 0, 2, "value", "ANY"],
                [32, 2, 0, -20, 0, "ANY"],
            ],
            "nodes": [
                {
                    "id": 2,
                    "type": "PassNode",
                    "inputs": [{"name": "value", "link": 31}],
                }
            ],
        },
    ]
    payload["nodes"]["wrapper"]["inputs"] = {"x": ["source", 0]}
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    return payload


def _passthrough_wrapper_cube_payload() -> Payload:
    """Return a wrapper cube fixture that forwards its source input."""

    return {
        "cube_id": "wrapper_cube",
        "version": "1.0.0",
        "nodes": {
            "source": {"class_type": "SourceNode", "inputs": {"value": 1}},
            "wrapper": {
                "class_type": UUID_A,
                "inputs": {
                    "main": ["source", 0],
                },
            },
            "consumer": {
                "class_type": "ConsumerNode",
                "inputs": {
                    "main": ["wrapper", 0],
                },
            },
        },
        "outputs": {"output.main": "consumer"},
        "subgraphs": [
            {
                "id": UUID_A,
                "inputNode": {"id": -10},
                "outputNode": {"id": -20},
                "inputs": [{"name": "main", "linkIds": [41]}],
                "outputs": [{"name": "main", "linkIds": [42]}],
                "links": [
                    [41, -10, 0, 1, "value", "ANY"],
                    [42, 1, 0, -20, 0, "ANY"],
                ],
                "nodes": [
                    {
                        "id": 1,
                        "type": "PassNode",
                        "inputs": [{"name": "value", "link": 41}],
                    }
                ],
            }
        ],
    }


def _write_sink_cube(cube_root: Path) -> None:
    """Write a generic sink cube for connected recipe fixtures."""

    write_cube(
        cube_root / "sink.cube",
        {
            "cube_id": "sink",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"main": None}}},
            "inputs": {"input.main": [["sink", "main"]]},
        },
    )


def _connected_wrapper_script(extra: str = "") -> str:
    """Return a connected wrapper script with optional extra statements."""

    return f"""
use "wrapper_cube" as A
use "sink" as out
connect A.output.main to out.input.main
{extra}
"""


def _expanded_single_widget_node(
    *,
    tmp_path: Path,
    class_type: str,
    definition: Mapping[str, Any],
    widget_values: list[Any],
) -> Mapping[str, Any]:
    """Build a wrapper cube and return its expanded subgraph body node."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": class_type,
            "inputs": [],
            "widgets_values": widget_values,
        }
    ]
    payload["definitions"] = {class_type: definition}
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    return next(node for node in workflow.values() if node["class_type"] == class_type)


def test_spawn_plan_expands_uuid_wrappers(tmp_path: Path) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "wrapper_cube.cube", _wrapper_cube_payload())

    plan = {
        "cube_root": str(cube_root),
        "cubes": [{"cube_id": "wrapper_cube", "alias": "A"}],
        "order": ["A"],
        "connections": [],
        "sets": [],
        "disabled": [],
    }
    workflow = spawn_plan_to_workflow(plan, cube_root=cube_root)

    class_types = [node.get("class_type", "") for node in workflow.values()]
    assert not any(isinstance(ct, str) and UUID_RE.match(ct) for ct in class_types)

    consumer = next(node for node in workflow.values() if node["class_type"] == "ConsumerNode")
    main_ref = consumer["inputs"]["main"]
    aux_ref = consumer["inputs"]["aux"]
    assert main_ref[0] == aux_ref[0]
    assert main_ref[1] == 0
    assert aux_ref[1] == 1


def test_connected_cube_output_rewrites_cross_cube_wrapper_reference(
    tmp_path: Path,
) -> None:
    """Connected cube outputs should not leave downstream links to wrappers."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["outputs"] = {"output.main": "wrapper"}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    sink_node = next(node for node in workflow.values() if node["class_type"] == "Sink")
    sink_ref = sink_node["inputs"]["main"]
    target_node = workflow[sink_ref[0]]
    assert target_node["class_type"] == "DualOut"
    assert sink_ref[1] == 0


def test_spawn_plan_rejects_wrapper_when_subgraph_io_contract_is_missing(
    tmp_path: Path,
) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["subgraphs"][0]["inputs"] = []
    payload["subgraphs"][0]["outputs"] = []
    write_cube(cube_root / "wrapper_cube.cube", payload)

    plan = {
        "cube_root": str(cube_root),
        "cubes": [{"cube_id": "wrapper_cube", "alias": "A"}],
        "order": ["A"],
        "connections": [],
        "sets": [],
        "disabled": [],
    }
    with pytest.raises(RuntimeError, match="cannot map input link"):
        spawn_plan_to_workflow(plan, cube_root=cube_root)


def test_spawn_plan_expands_nested_uuid_wrappers(tmp_path: Path) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "wrapper_cube.cube", _nested_wrapper_cube_payload())

    plan = {
        "cube_root": str(cube_root),
        "cubes": [{"cube_id": "wrapper_cube", "alias": "A"}],
        "order": ["A"],
        "connections": [],
        "sets": [],
        "disabled": [],
    }
    workflow = spawn_plan_to_workflow(plan, cube_root=cube_root)

    class_types = [node.get("class_type", "") for node in workflow.values()]
    assert "PassNode" in class_types
    assert not any(isinstance(ct, str) and UUID_RE.match(ct) for ct in class_types)


def test_spawn_plan_rejects_missing_declared_output_mapping_for_consumed_slot(
    tmp_path: Path,
) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    write_cube(cube_root / "wrapper_cube.cube", payload)

    plan = {
        "cube_root": str(cube_root),
        "cubes": [{"cube_id": "wrapper_cube", "alias": "A"}],
        "order": ["A"],
        "connections": [],
        "sets": [],
        "disabled": [],
    }

    with pytest.raises(RuntimeError, match="missing output mapping for slot\\(s\\): 1"):
        spawn_plan_to_workflow(plan, cube_root=cube_root)


def test_set_on_wrapper_surface_applies_after_expansion(tmp_path: Path) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "wrapper_cube.cube", _wrapper_cube_payload())
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script("set A.wrapper.y = 42"),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    dual = next(node for node in workflow.values() if node["class_type"] == "DualOut")
    assert dual["inputs"]["in_b"] == 42


def test_wildcard_set_applies_to_missing_wrapper_interface_input(
    tmp_path: Path,
) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    del payload["nodes"]["wrapper"]["inputs"]["y"]
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script("set *.*.y = 42"),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    dual = next(node for node in workflow.values() if node["class_type"] == "DualOut")
    assert dual["inputs"]["in_b"] == 42


def test_disable_on_wrapper_surface_passthroughs_source(tmp_path: Path) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "wrapper_cube.cube", _passthrough_wrapper_cube_payload())
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script("disable A.wrapper"),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    class_types = [node.get("class_type", "") for node in workflow.values()]
    assert not any(isinstance(ct, str) and UUID_RE.match(ct) for ct in class_types)
    assert "PassNode" not in class_types

    source_node_id = next(
        node_id for node_id, node in workflow.items() if node.get("class_type") == "SourceNode"
    )
    consumer = next(node for node in workflow.values() if node["class_type"] == "ConsumerNode")
    assert consumer["inputs"]["main"] == [source_node_id, 0]


def test_validate_cube_document_rejects_uuid_wrapper_without_subgraph_body() -> None:
    payload = _wrapper_cube_payload()
    payload["subgraphs"] = [{"id": UUID_A, "nodes": [], "inputs": [], "outputs": []}]

    with pytest.raises(RuntimeError, match="subgraph body is empty"):
        validate_cube_document(current_cube_payload(payload))


def test_validate_cube_document_rejects_wrapper_subgraph_without_inputs_array() -> None:
    payload = _wrapper_cube_payload()
    del payload["subgraphs"][0]["inputs"]

    with pytest.raises(RuntimeError, match="must include an 'inputs' array"):
        validate_cube_document(current_cube_payload(payload))


def test_validate_cube_document_rejects_wrapper_subgraph_without_outputs_array() -> None:
    payload = _wrapper_cube_payload()
    del payload["subgraphs"][0]["outputs"]

    with pytest.raises(RuntimeError, match="must include an 'outputs' array"):
        validate_cube_document(current_cube_payload(payload))


def test_validate_cube_document_allows_non_wrapper_cube_without_subgraphs() -> None:
    payload = {
        "cube_id": "plain_cube",
        "version": "1.0.0",
        "nodes": {"node": {"class_type": "KSampler", "inputs": {"seed": 1}}},
        "outputs": {"output.value": "node"},
    }

    validated = validate_cube_document(current_cube_payload(payload))
    assert validated["cube_id"] == "plain_cube"


def test_spawn_plan_expands_subgraph_widget_values_into_node_inputs(
    tmp_path: Path,
) -> None:
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "RegexExtract",
            "inputs": [{"name": "text", "link": 11}],
            "widgets_values": {
                "case_insensitive": False,
                "dotall": False,
                "regex_pattern": "<([^>]+)>",
                "mode": "first",
                "group_index": 1,
                "multiline": False,
            },
        }
    ]
    payload["definitions"] = {
        "RegexExtract": {
            "input": {
                "required": {
                    "text": ["STRING"],
                    "case_insensitive": ["BOOLEAN"],
                    "dotall": ["BOOLEAN"],
                    "regex_pattern": ["STRING"],
                    "mode": ["STRING"],
                    "group_index": ["INT"],
                    "multiline": ["BOOLEAN"],
                }
            }
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    regex_node = next(node for node in workflow.values() if node["class_type"] == "RegexExtract")
    assert regex_node["inputs"]["case_insensitive"] is False
    assert regex_node["inputs"]["dotall"] is False
    assert regex_node["inputs"]["regex_pattern"] == "<([^>]+)>"
    assert regex_node["inputs"]["mode"] == "first"
    assert regex_node["inputs"]["group_index"] == 1
    assert regex_node["inputs"]["multiline"] is False


def test_spawn_plan_expands_subgraph_widget_values_from_compact_input_order(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should need input_order, not full choice inventories."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "RegexExtract",
            "inputs": [{"name": "text", "link": 11}],
            "widgets_values": [False, False, "<([^>]+)>", "first", 1, False],
        }
    ]
    payload["definitions"] = {
        "RegexExtract": {
            "input_order": {
                "required": [
                    "case_insensitive",
                    "dotall",
                    "regex_pattern",
                    "mode",
                    "group_index",
                    "multiline",
                ]
            },
            "input": {
                "required": {
                    "mode": [["first", "all"], {"default": "first"}],
                    "group_index": ["INT", {"min": 0, "max": 16, "step": 1}],
                }
            },
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    regex_node = next(node for node in workflow.values() if node["class_type"] == "RegexExtract")
    assert regex_node["inputs"]["case_insensitive"] is False
    assert regex_node["inputs"]["dotall"] is False
    assert regex_node["inputs"]["regex_pattern"] == "<([^>]+)>"
    assert regex_node["inputs"]["mode"] == "first"
    assert regex_node["inputs"]["group_index"] == 1
    assert regex_node["inputs"]["multiline"] is False


def test_spawn_plan_maps_subgraph_widget_values_after_linked_socket(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should align widget values to widget-capable fields only."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "ResizeImageToTarget",
            "inputs": [{"name": "image", "link": 11}],
            "widgets_values": [
                "Keep AR",
                "lanczos",
                "gpu",
                1,
                "center",
                "0, 0, 0",
                0,
                3,
                "fp32",
            ],
        }
    ]
    payload["definitions"] = {
        "ResizeImageToTarget": {
            "input_order": {
                "required": [
                    "image",
                    "resize_mode",
                    "sampling",
                    "processor",
                    "divisible_by",
                    "crop_position",
                    "pad_color",
                    "max_batch_size",
                    "sinc_window",
                    "precision",
                ]
            },
            "input": {
                "required": {
                    "image": ["IMAGE"],
                    "resize_mode": [["Stretch", "Keep AR"]],
                    "sampling": [["nearest-exact", "lanczos"]],
                    "processor": [["cpu", "gpu"]],
                    "divisible_by": ["INT"],
                    "crop_position": [["center", "top-left"]],
                    "pad_color": ["STRING"],
                    "max_batch_size": ["INT"],
                    "sinc_window": ["INT"],
                    "precision": [["fp32", "fp16"]],
                }
            },
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    resize_node = next(
        node for node in workflow.values() if node["class_type"] == "ResizeImageToTarget"
    )
    assert resize_node["inputs"]["resize_mode"] == "Keep AR"
    assert resize_node["inputs"]["sampling"] == "lanczos"
    assert resize_node["inputs"]["processor"] == "gpu"
    assert resize_node["inputs"]["divisible_by"] == 1
    assert resize_node["inputs"]["crop_position"] == "center"
    assert resize_node["inputs"]["pad_color"] == "0, 0, 0"
    assert resize_node["inputs"]["max_batch_size"] == 0
    assert resize_node["inputs"]["sinc_window"] == 3
    assert resize_node["inputs"]["precision"] == "fp32"


def test_spawn_plan_preserves_linked_widget_default_when_wrapper_input_missing(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should not replace body widget defaults with None."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    del payload["nodes"]["wrapper"]["inputs"]["y"]
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "UpscaleModelLoader",
            "inputs": [{"name": "model_name", "link": 12}],
            "widgets_values": ["R-ESRGAN 4x+ Anime6B.pth"],
        }
    ]
    payload["definitions"] = {
        "UpscaleModelLoader": {
            "input_order": {"required": ["model_name"]},
            "input": {
                "required": {
                    "model_name": [["R-ESRGAN 4x+ Anime6B.pth", "4x-UltraSharp.pth"]],
                }
            },
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    loader_node = next(
        node for node in workflow.values() if node["class_type"] == "UpscaleModelLoader"
    )
    assert loader_node["inputs"]["model_name"] == "R-ESRGAN 4x+ Anime6B.pth"


def test_spawn_plan_skips_control_after_generate_widget_values(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should ignore UI-only seed control values."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "SimpleSyrup.KSamplerExtras",
            "inputs": [{"name": "model", "link": 11}],
            "widgets_values": [
                123456,
                "randomize",
                12,
                6.5,
                "euler_ancestral",
                "normal",
                0.2,
            ],
        }
    ]
    payload["definitions"] = {
        "SimpleSyrup.KSamplerExtras": {
            "input_order": {
                "required": [
                    "model",
                    "seed",
                    "steps",
                    "cfg",
                    "sampler_name",
                    "scheduler",
                    "denoise",
                ]
            },
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "seed": [
                        "INT",
                        {
                            "default": 0,
                            "control_after_generate": True,
                        },
                    ],
                    "steps": ["INT"],
                    "cfg": ["FLOAT"],
                    "sampler_name": [["euler", "euler_ancestral"]],
                    "scheduler": [["normal", "karras"]],
                    "denoise": ["FLOAT"],
                }
            },
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    sampler_node = next(
        node for node in workflow.values() if node["class_type"] == "SimpleSyrup.KSamplerExtras"
    )
    assert sampler_node["inputs"]["seed"] == 123456
    assert sampler_node["inputs"]["steps"] == 12
    assert sampler_node["inputs"]["cfg"] == 6.5
    assert sampler_node["inputs"]["sampler_name"] == "euler_ancestral"
    assert sampler_node["inputs"]["scheduler"] == "normal"
    assert sampler_node["inputs"]["denoise"] == 0.2


def test_spawn_plan_skips_implicit_int_seed_control_widget_value(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should follow Comfy's implicit INT seed control rule."""

    upscaler_node = _expanded_single_widget_node(
        tmp_path=tmp_path,
        class_type="SeedVR2VideoUpscaler",
        widget_values=[
            182721604,
            "randomize",
            1080,
            0,
            1,
            False,
            "none",
            0,
            0,
            0.025,
            0.025,
            "cpu",
            False,
        ],
        definition={
            "input_order": {
                "required": [
                    "seed",
                    "resolution",
                    "max_resolution",
                    "batch_size",
                    "uniform_batch_size",
                    "color_correction",
                    "temporal_overlap",
                    "prepend_frames",
                    "input_noise_scale",
                    "latent_noise_scale",
                    "offload_device",
                    "enable_debug",
                ]
            },
            "input": {
                "required": {
                    "seed": [
                        "INT",
                        {
                            "default": 42,
                            "min": 0,
                            "max": 4294967295,
                            "step": 1,
                        },
                    ],
                    "resolution": ["INT"],
                    "max_resolution": ["INT"],
                    "batch_size": ["INT"],
                    "uniform_batch_size": ["BOOLEAN"],
                    "color_correction": [
                        ["lab", "wavelet", "wavelet_adaptive", "hsv", "adain", "none"]
                    ],
                    "temporal_overlap": ["INT"],
                    "prepend_frames": ["INT"],
                    "input_noise_scale": ["FLOAT"],
                    "latent_noise_scale": ["FLOAT"],
                    "offload_device": [["none", "cpu", "cuda:0"]],
                    "enable_debug": ["BOOLEAN"],
                }
            },
        },
    )

    inputs = upscaler_node["inputs"]
    assert inputs["seed"] == 182721604
    assert inputs["resolution"] == 1080
    assert inputs["max_resolution"] == 0
    assert inputs["batch_size"] == 1
    assert inputs["uniform_batch_size"] is False
    assert inputs["color_correction"] == "none"
    assert inputs["temporal_overlap"] == 0
    assert inputs["prepend_frames"] == 0
    assert inputs["input_noise_scale"] == 0.025
    assert inputs["latent_noise_scale"] == 0.025
    assert inputs["offload_device"] == "cpu"
    assert inputs["enable_debug"] is False


def test_spawn_plan_skips_implicit_int_noise_seed_control_widget_value(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should skip Comfy controls for INT noise_seed fields."""

    node = _expanded_single_widget_node(
        tmp_path=tmp_path,
        class_type="NoiseSampler",
        widget_values=[123, "increment", 20],
        definition={
            "input_order": {"required": ["noise_seed", "steps"]},
            "input": {
                "required": {
                    "noise_seed": ["INT", {"default": 0}],
                    "steps": ["INT", {"default": 20}],
                }
            },
        },
    )

    assert node["inputs"]["noise_seed"] == 123
    assert node["inputs"]["steps"] == 20


def test_spawn_plan_does_not_skip_control_like_value_after_non_int_seed(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should keep STRING seed values in positional order."""

    node = _expanded_single_widget_node(
        tmp_path=tmp_path,
        class_type="MetadataNode",
        widget_values=["literal-seed", "randomize"],
        definition={
            "input_order": {"required": ["seed", "mode"]},
            "input": {
                "required": {
                    "seed": ["STRING", {"default": ""}],
                    "mode": [["randomize", "fixed"]],
                }
            },
        },
    )

    assert node["inputs"]["seed"] == "literal-seed"
    assert node["inputs"]["mode"] == "randomize"


def test_spawn_plan_does_not_skip_unknown_value_after_int_seed(
    tmp_path: Path,
) -> None:
    """Subgraph expansion should only skip known Comfy control modes."""

    node = _expanded_single_widget_node(
        tmp_path=tmp_path,
        class_type="SeedLabelNode",
        widget_values=[123, "not-a-control-mode"],
        definition={
            "input_order": {"required": ["seed", "label"]},
            "input": {
                "required": {
                    "seed": ["INT", {"default": 0}],
                    "label": ["STRING", {"default": ""}],
                }
            },
        },
    )

    assert node["inputs"]["seed"] == 123
    assert node["inputs"]["label"] == "not-a-control-mode"


def test_spawn_plan_overrides_linked_widget_default_by_interface_name(
    tmp_path: Path,
) -> None:
    """Subgraph links should use interface names when body input names differ."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    payload = _wrapper_cube_payload()
    payload["nodes"]["consumer"]["inputs"] = {"main": ["wrapper", 0]}
    payload["nodes"]["wrapper"]["inputs"]["positive_prompt"] = "real prompt text"
    del payload["nodes"]["wrapper"]["inputs"]["x"]
    payload["subgraphs"][0]["inputs"] = [
        {"name": "positive_prompt", "linkIds": [11]},
        {"name": "y", "linkIds": [12]},
    ]
    payload["subgraphs"][0]["outputs"] = [{"name": "main", "linkIds": [13]}]
    payload["subgraphs"][0]["links"] = [
        [11, -10, 0, 1, "string", "STRING"],
        [13, 1, 0, -20, 0, "STRING"],
    ]
    payload["subgraphs"][0]["nodes"] = [
        {
            "id": 1,
            "type": "RegexExtract",
            "inputs": [{"name": "string", "link": 11}],
            "widgets_values": [
                "",
                "(?:^|>)([^<]+)(?=<|$)",
                "All Matches",
                True,
                False,
                False,
                1,
            ],
        }
    ]
    payload["definitions"] = {
        "RegexExtract": {
            "input_order": {
                "required": [
                    "string",
                    "regex_pattern",
                    "mode",
                    "case_insensitive",
                    "multiline",
                    "dotall",
                    "group_index",
                ]
            },
            "input": {
                "required": {
                    "string": ["STRING"],
                    "regex_pattern": ["STRING"],
                    "mode": [["All Matches", "First Match"]],
                    "case_insensitive": ["BOOLEAN"],
                    "multiline": ["BOOLEAN"],
                    "dotall": ["BOOLEAN"],
                    "group_index": ["INT"],
                }
            },
        }
    }
    write_cube(cube_root / "wrapper_cube.cube", payload)
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        _connected_wrapper_script(),
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    regex_node = next(node for node in workflow.values() if node["class_type"] == "RegexExtract")
    assert regex_node["inputs"]["string"] == "real prompt text"
    assert regex_node["inputs"]["regex_pattern"] == "(?:^|>)([^<]+)(?=<|$)"
