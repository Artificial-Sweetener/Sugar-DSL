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
"""Tests for execution-only Sugar graph resource optimization."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_comfy_artifacts_from_text
from sugar.compiler.analyzer import analyze_text
from sugar.compiler.codegen import spawn_plan_to_workflow

Payload = dict[str, Any]


def test_prompt_identity_rewrites_api_prompt_but_preserves_ui_prompt_boxes(
    tmp_path: Path,
) -> None:
    """Explicit prompt identity should optimize execution only."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_prompt_cubes(cube_root)

    artifacts = build_comfy_artifacts_from_text(
        """
        use "prompt_stage" as A
        use "prompt_stage" as B
        use "conditioning_collector" as Out
        set A.positive.value = "shared <lora:Anima/anima-turbo-lora-v0.1:1.00>"
        set B.positive.value = "local before link"
        set B.positive = A.positive
        connect A.output.conditioning to Out.input.a
        connect B.output.conditioning to Out.input.b
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    prompt = artifacts["prompt"]
    workflow = artifacts["workflow"]

    assert _api_titles_by_class(prompt, "PrimitiveStringMultiline") == ["A.positive"]
    b_lora = _api_node_by_title(prompt, "B.lora")
    b_encode = _api_node_by_title(prompt, "B.encode")
    assert _api_title_for_input(prompt, b_lora, "text") == "A.positive"
    assert _api_title_for_input(prompt, b_encode, "text") == "A.positive"

    ui_prompt_nodes = [
        node for node in workflow["nodes"] if node["type"] == "PrimitiveStringMultiline"
    ]
    assert len(ui_prompt_nodes) == 2
    assert sorted(node["widgets_values"][0] for node in ui_prompt_nodes) == [
        "shared <lora:Anima/anima-turbo-lora-v0.1:1.00>",
        "shared <lora:Anima/anima-turbo-lora-v0.1:1.00>",
    ]


def test_exact_primitive_prompt_values_intern_in_api_prompt(tmp_path: Path) -> None:
    """Identical primitive prompt providers should share one API node."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_prompt_cubes(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "prompt_stage" as A
            use "prompt_stage" as B
            use "conditioning_collector" as Out
            set A.positive.value = "same prompt"
            set B.positive.value = "same prompt"
            connect A.output.conditioning to Out.input.a
            connect B.output.conditioning to Out.input.b
            """,
            cube_root=cube_root,
        ),
        cube_root=cube_root,
    )

    assert _api_titles_by_class(workflow, "PrimitiveStringMultiline") == ["A.positive"]
    assert _api_title_for_input(workflow, _api_node_by_title(workflow, "B.encode"), "text") == (
        "A.positive"
    )


def test_same_lora_schedule_with_different_prompt_prose_stays_unoptimized_in_sugar(
    tmp_path: Path,
) -> None:
    """Prompt-Control-specific LoRA schedule sharing belongs to Substitute BackEnd."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_prompt_cubes(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "prompt_stage" as A
            use "prompt_stage_consumer" as B
            use "conditioning_collector" as Out
            set A.positive.value = "cat <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            set B.positive.value = "dog <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            connect A.output.model to B.input.model
            connect A.output.clip to B.input.clip
            connect A.output.conditioning to Out.input.a
            connect B.output.conditioning to Out.input.b
            """,
            cube_root=cube_root,
        ),
        cube_root=cube_root,
    )

    assert _api_titles_by_class(workflow, "PrimitiveStringMultiline") == [
        "A.positive",
        "B.positive",
    ]
    assert _api_titles_by_class(workflow, "PCLazyLoraLoader") == ["A.lora", "B.lora"]
    assert _api_titles_by_class(workflow, "PCLazyTextEncode") == ["A.encode", "B.encode"]
    assert _api_title_for_input(workflow, _api_node_by_title(workflow, "B.encode"), "clip") == (
        "B.lora"
    )
    assert _api_title_for_input(workflow, _api_node_by_title(workflow, "B.encode"), "text") == (
        "B.positive"
    )


def test_equal_prompt_text_shares_text_conditioning(tmp_path: Path) -> None:
    """Exact prompt equality should share only primitive prompt providers in Sugar."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_prompt_cubes(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "prompt_stage" as A
            use "prompt_stage_consumer" as B
            use "conditioning_collector" as Out
            set A.positive.value = "same <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            set B.positive.value = "same <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            connect A.output.model to B.input.model
            connect A.output.clip to B.input.clip
            connect A.output.conditioning to Out.input.a
            connect B.output.conditioning to Out.input.b
            """,
            cube_root=cube_root,
        ),
        cube_root=cube_root,
    )

    assert _api_titles_by_class(workflow, "PrimitiveStringMultiline") == ["A.positive"]
    assert _api_titles_by_class(workflow, "PCLazyLoraLoader") == ["A.lora", "B.lora"]
    assert _api_titles_by_class(workflow, "PCLazyTextEncode") == ["A.encode", "B.encode"]
    assert _api_title_for_input(workflow, _api_node_by_title(workflow, "B.encode"), "text") == (
        "A.positive"
    )


def test_same_lora_schedule_against_different_model_branches_does_not_share(
    tmp_path: Path,
) -> None:
    """LoRA branches must keep distinct upstream model and clip identities."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_prompt_cubes(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "prompt_stage" as A
            use "prompt_stage" as B
            use "conditioning_collector" as Out
            set A.positive.value = "cat <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            set B.positive.value = "dog <lora:Anima/anima-turbo-lora-v0.1:1.00>"
            set B.model.name = "other-model"
            connect A.output.conditioning to Out.input.a
            connect B.output.conditioning to Out.input.b
            """,
            cube_root=cube_root,
        ),
        cube_root=cube_root,
    )

    assert _api_titles_by_class(workflow, "PCLazyLoraLoader") == ["A.lora", "B.lora"]


def test_sampler_nodes_do_not_intern_even_when_identical(tmp_path: Path) -> None:
    """Non-allowlisted runtime nodes should keep their authored execution shape."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "sampler_stage.cube", _sampler_stage_cube())
    write_cube(cube_root / "latent_collector.cube", _latent_collector_cube())

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "sampler_stage" as A
            use "sampler_stage" as B
            use "latent_collector" as Out
            connect A.output.latent to Out.input.a
            connect B.output.latent to Out.input.b
            """,
            cube_root=cube_root,
        ),
        cube_root=cube_root,
    )

    assert _api_titles_by_class(workflow, "KSampler") == ["A.sampler", "B.sampler"]


def _write_prompt_cubes(cube_root: Path) -> None:
    """Write compact prompt-stage fixtures used by optimizer tests."""

    write_cube(cube_root / "prompt_stage.cube", _prompt_stage_cube())
    write_cube(cube_root / "prompt_stage_consumer.cube", _prompt_stage_consumer_cube())
    write_cube(cube_root / "conditioning_collector.cube", _conditioning_collector_cube())


def _prompt_stage_cube() -> Payload:
    """Return a Prompt Control style cube fixture without real model assets."""

    return {
        "cube_id": "prompt_stage",
        "version": "1.0.0",
        "nodes": {
            "model": {"class_type": "ModelProvider", "inputs": {"name": "base-model"}},
            "clip": {"class_type": "ClipProvider", "inputs": {"name": "base-clip"}},
            "positive": {
                "class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "default prompt"},
            },
            "lora": {
                "class_type": "PCLazyLoraLoader",
                "inputs": {
                    "model": ["model", 0],
                    "clip": ["clip", 0],
                    "text": ["positive", 0],
                },
            },
            "encode": {
                "class_type": "PCLazyTextEncode",
                "inputs": {
                    "clip": ["lora", 1],
                    "text": ["positive", 0],
                },
            },
            "sink": {
                "class_type": "ConditioningSink",
                "inputs": {
                    "conditioning": ["encode", 0],
                    "model": ["lora", 0],
                },
            },
        },
        "outputs": {
            "output.conditioning": ["sink", 0],
            "output.model": ["model", 0],
            "output.clip": ["clip", 0],
        },
        "definitions": _prompt_stage_definitions(),
    }


def _prompt_stage_consumer_cube() -> Payload:
    """Return a prompt-stage variant whose model and clip can be connected."""

    payload = copy.deepcopy(_prompt_stage_cube())
    payload["cube_id"] = "prompt_stage_consumer"
    payload["inputs"] = {
        "input.model": [["lora", "model"]],
        "input.clip": [["lora", "clip"]],
    }
    return payload


def _prompt_stage_definitions() -> Payload:
    """Return node definitions for compact Prompt Control fixtures."""

    return {
        "ModelProvider": {
            "input": {"required": {"name": ["STRING", {"default": "base-model"}]}},
            "input_order": {"required": ["name"]},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "ClipProvider": {
            "input": {"required": {"name": ["STRING", {"default": "base-clip"}]}},
            "input_order": {"required": ["name"]},
            "output": ["CLIP"],
            "output_name": ["CLIP"],
        },
        "PrimitiveStringMultiline": {
            "input": {"required": {"value": ["STRING", {"default": ""}]}},
            "input_order": {"required": ["value"]},
            "output": ["STRING"],
            "output_name": ["STRING"],
        },
        "PCLazyLoraLoader": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "clip": ["CLIP"],
                    "text": ["STRING", {"default": ""}],
                }
            },
            "input_order": {"required": ["model", "clip", "text"]},
            "output": ["MODEL", "CLIP"],
            "output_name": ["MODEL", "CLIP"],
        },
        "PCLazyTextEncode": {
            "input": {
                "required": {
                    "clip": ["CLIP"],
                    "text": ["STRING", {"default": ""}],
                }
            },
            "input_order": {"required": ["clip", "text"]},
            "output": ["CONDITIONING"],
            "output_name": ["CONDITIONING"],
        },
        "ConditioningSink": {
            "input": {
                "required": {
                    "conditioning": ["CONDITIONING"],
                    "model": ["MODEL"],
                }
            },
            "input_order": {"required": ["conditioning", "model"]},
            "output": ["CONDITIONING"],
            "output_name": ["CONDITIONING"],
        },
    }


def _sampler_stage_cube() -> Payload:
    """Return a fixture with an intentionally non-allowlisted sampler node."""

    return {
        "cube_id": "sampler_stage",
        "version": "1.0.0",
        "nodes": {
            "sampler": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 123,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                },
            }
        },
        "outputs": {"output.latent": ["sampler", 0]},
        "definitions": {
            "KSampler": {
                "input": {
                    "required": {
                        "seed": ["INT", {"default": 0}],
                        "steps": ["INT", {"default": 20}],
                        "cfg": ["FLOAT", {"default": 7.0}],
                        "sampler_name": [["euler", "dpmpp_2m"]],
                        "scheduler": [["normal", "simple"]],
                    }
                },
                "input_order": {
                    "required": [
                        "seed",
                        "steps",
                        "cfg",
                        "sampler_name",
                        "scheduler",
                    ]
                },
                "output": ["LATENT"],
                "output_name": ["LATENT"],
            }
        },
    }


def _conditioning_collector_cube() -> Payload:
    """Return a sink fixture that keeps two prompt stages connected."""

    return {
        "cube_id": "conditioning_collector",
        "version": "1.0.0",
        "nodes": {
            "collector": {
                "class_type": "ConditioningCollector",
                "inputs": {"a": None, "b": None},
            }
        },
        "inputs": {
            "input.a": [["collector", "a"]],
            "input.b": [["collector", "b"]],
        },
        "definitions": {
            "ConditioningCollector": {
                "input": {
                    "required": {
                        "a": ["CONDITIONING"],
                        "b": ["CONDITIONING"],
                    }
                },
                "input_order": {"required": ["a", "b"]},
                "output": [],
                "output_name": [],
            }
        },
    }


def _latent_collector_cube() -> Payload:
    """Return a sink fixture that keeps two sampler stages connected."""

    return {
        "cube_id": "latent_collector",
        "version": "1.0.0",
        "nodes": {
            "collector": {
                "class_type": "LatentCollector",
                "inputs": {"a": None, "b": None},
            }
        },
        "inputs": {
            "input.a": [["collector", "a"]],
            "input.b": [["collector", "b"]],
        },
        "definitions": {
            "LatentCollector": {
                "input": {"required": {"a": ["LATENT"], "b": ["LATENT"]}},
                "input_order": {"required": ["a", "b"]},
                "output": [],
                "output_name": [],
            }
        },
    }


def _api_titles_by_class(workflow: Payload, class_type: str) -> list[str]:
    """Return API node titles for one Comfy class type."""

    return sorted(
        str(node["_meta"]["title"])
        for node in workflow.values()
        if node.get("class_type") == class_type
    )


def _api_node_by_title(workflow: Payload, title: str) -> Payload:
    """Return one API node by its materialized title."""

    return next(node for node in workflow.values() if node["_meta"]["title"] == title)


def _api_title_for_input(workflow: Payload, node: Payload, input_name: str) -> str:
    """Return the title of the node linked to one API node input."""

    link = node["inputs"][input_name]
    linked_id = str(link[0])
    return str(workflow[linked_id]["_meta"]["title"])
