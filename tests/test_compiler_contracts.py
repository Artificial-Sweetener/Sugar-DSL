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
"""Characterization tests for compiler graph behavior before refactoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from tests.fixtures.cubes import current_cube_payload, write_cube, write_local_flavors
from sugar.api.builder import build_comfy_artifacts_from_text, build_workflow_from_text
from sugar.catalog.models import validate_cube_document
from sugar.compiler.analyzer import analyze_text
from sugar.compiler.codegen import spawn_plan_to_workflow
from sugar.compiler.flavors import compute_surface_signature


def _flavored_cube_payload() -> dict[str, Any]:
    """Return a cube whose surface control maps to one sampler input."""

    return current_cube_payload(
        {
            "cube_id": "flavored",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"seed": 0}}},
            "outputs": {"output.image": "sampler"},
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "seed_control",
                        "symbol": "sampler",
                        "input_name": "seed",
                        "class_type": "KSampler",
                        "value_type": "int",
                    }
                ],
            },
            "flavors": {
                "authored": [
                    {
                        "id": "default",
                        "name": "Default",
                        "values": {"seed_control": 11},
                    },
                    {
                        "id": "cinematic",
                        "name": "Cinematic",
                        "values": {"seed_control": 22},
                    },
                ]
            },
        }
    )


def _write_sink_cube(cube_root: Path, *, input_binding: str = "input.image") -> None:
    """Write a generic sink cube for connected recipe fixtures."""

    write_cube(
        cube_root / "sink.cube",
        {
            "cube_id": "sink",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"value": None}}},
            "inputs": {input_binding: [["sink", "value"]]},
        },
    )


def _wrapper_cube_payload_for_label_validation() -> dict[str, Any]:
    """Return a minimal UUID wrapper cube for catalog label validation."""

    wrapper_id = "94f725d5-39bf-4060-be68-f573214a2055"
    return {
        "cube_id": "wrapper",
        "version": "1.0.0",
        "nodes": {
            "wrapper": {"class_type": wrapper_id, "inputs": {"value": 1}},
        },
        "outputs": {"output.image": "wrapper"},
        "subgraphs": [
            {
                "id": wrapper_id,
                "inputs": [{"name": "value"}],
                "outputs": [{"name": "image"}],
                "nodes": [{"id": 1, "type": "KSampler"}],
            }
        ],
    }


def _seed_field_spec(field_type: str = "INT", *, default: object = 0) -> list[object]:
    """Return a compact Comfy field spec for seed materialization tests."""

    return [
        field_type,
        {
            "default": default,
            "min": 0,
            "max": 0xFFFFFFFFFFFFFFFF,
            "control_after_generate": True,
        },
    ]


def _defaulted_input_cube_payload(
    *,
    class_type: str = "SimpleSyrup.KSamplerExtras",
    node_inputs: dict[str, Any] | None = None,
    required_fields: dict[str, object] | None = None,
    optional_fields: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Return a cube payload with definition-backed input materialization."""

    input_definition: dict[str, object] = {}
    if required_fields is not None:
        input_definition["required"] = required_fields
    if optional_fields is not None:
        input_definition["optional"] = optional_fields
    return current_cube_payload(
        {
            "cube_id": "defaulted_inputs",
            "version": "1.0.0",
            "nodes": {
                "sampler": {
                    "class_type": class_type,
                    "inputs": dict(node_inputs or {}),
                }
            },
            "outputs": {"output.latent": ["sampler", 0]},
            "definitions": {
                class_type: {
                    "input": input_definition,
                    "output": ["LATENT"],
                    "output_name": ["LATENT"],
                }
            },
        }
    )


def _build_defaulted_input_workflow(
    tmp_path: Path,
    payload: dict[str, Any],
    *,
    seed: int = 12345,
) -> dict[str, Any]:
    """Build one connected workflow for input materialization assertions."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "defaulted_inputs.cube", payload)
    _write_sink_cube(cube_root)
    return build_workflow_from_text(
        """
        use "defaulted_inputs" as d
        use "sink" as out
        connect d.output.latent to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        seed_provider=lambda: seed,
    )


def _only_prompt_node_inputs(
    workflow: dict[str, Any], *, class_type: str = "SimpleSyrup.KSamplerExtras"
) -> dict[str, Any]:
    """Return inputs from the only workflow node matching one class type."""

    [node] = [node for node in workflow.values() if node["class_type"] == class_type]
    inputs = node.get("inputs")
    assert isinstance(inputs, dict)
    return inputs


def _connect_to_sink(script: str, *, output_binding: str = "output.image") -> str:
    """Append a sink cube and recipe connection to a fixture script."""

    return f"""
    {script}
    use "sink" as out
    connect f.{output_binding} to out.input.image
    """


def _single_node_input(workflow: dict[str, Any], input_name: str) -> Any:
    """Return an input value from the single-node workflow fixture."""

    nodes = [
        node
        for node in workflow.values()
        if input_name in node.get("inputs", {}) and node["class_type"] != "SugarCubes.CubeOutput"
    ]
    [node] = nodes
    return node["inputs"][input_name]


def _title_by_id(workflow: dict[str, Any]) -> dict[str, str | None]:
    """Return generated prompt titles keyed by numeric node id."""

    return {
        str(node_id): ((node or {}).get("_meta") or {}).get("title")
        for node_id, node in workflow.items()
    }


def _node_by_title(workflow: dict[str, Any], title: str) -> dict[str, Any]:
    """Return one generated prompt node by its materialized title."""

    [node] = [
        node
        for node in workflow.values()
        if ((node or {}).get("_meta") or {}).get("title") == title
    ]
    return cast(dict[str, Any], node)


def _object_provider_inputs(workflow: dict[str, Any]) -> set[Any]:
    """Return all values assigned to model, clip, and VAE object inputs."""

    values: set[Any] = set()
    for node in workflow.values():
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name in ("model", "model_in", "clip", "clip_in", "vae"):
            if input_name not in inputs:
                continue
            value = inputs[input_name]
            if isinstance(value, list):
                values.add(tuple(value))
            else:
                values.add(value)
    return values


def _write_provider_inheritance_cubes(cube_root: Path) -> None:
    """Write source and target cubes for provider inheritance regressions."""

    definitions = _provider_inheritance_definitions()
    write_cube(
        cube_root / "provider_source.cube",
        {
            "cube_id": "provider_source",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "inputs": {"model": "source-model", "clip": "source-clip"},
                },
                "schedule": {
                    "class_type": "Schedule",
                    "inputs": {
                        "model_in": ["provider", 0],
                        "clip_in": ["provider", 1],
                    },
                },
                "vae_consumer": {
                    "class_type": "VaeConsumer",
                    "inputs": {"vae": ["provider", 2]},
                },
                "image": {
                    "class_type": "ImageSource",
                    "inputs": {"model": ["schedule", 0]},
                },
            },
            "outputs": {"output.image": ["image", 0]},
            "definitions": definitions,
        },
    )
    write_cube(
        cube_root / "provider_target.cube",
        {
            "cube_id": "provider_target",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "mode": 4,
                    "inputs": {"model": "auto", "clip": "auto", "vae": "auto"},
                },
                "schedule": {
                    "class_type": "Schedule",
                    "inputs": {
                        "model_in": ["provider", 0],
                        "clip_in": ["provider", 1],
                    },
                },
                "vae_consumer": {
                    "class_type": "VaeConsumer",
                    "inputs": {"vae": ["provider", 2]},
                },
                "model_consumer": {
                    "class_type": "ModelConsumer",
                    "inputs": {"model": ["schedule", 0]},
                },
                "image_sink": {"class_type": "ImageSink", "inputs": {"image": None}},
            },
            "inputs": {"input.image": [["image_sink", "image"]]},
            "definitions": definitions,
        },
    )


def _provider_inheritance_definitions() -> dict[str, Any]:
    """Return compact definitions for provider inheritance fixtures."""

    return {
        "Provider": {
            "input": {
                "required": {
                    "model": ["COMBO"],
                    "clip": ["COMBO"],
                    "vae": ["COMBO"],
                }
            },
            "input_order": {"required": ["model", "clip", "vae"]},
            "output": ["MODEL", "CLIP", "VAE"],
            "output_name": ["MODEL", "CLIP", "VAE"],
        },
        "Schedule": {
            "input": {
                "required": {
                    "model_in": ["MODEL"],
                    "clip_in": ["CLIP"],
                }
            },
            "input_order": {"required": ["model_in", "clip_in"]},
            "output": ["MODEL", "CLIP"],
            "output_name": ["MODEL", "CLIP"],
        },
        "VaeConsumer": {
            "input": {"required": {"vae": ["VAE"]}},
            "input_order": {"required": ["vae"]},
            "output": ["VAE"],
            "output_name": ["VAE"],
        },
        "ModelConsumer": {
            "input": {"required": {"model": ["MODEL"]}},
            "input_order": {"required": ["model"]},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "ImageSource": {
            "input": {"required": {"model": ["MODEL"]}},
            "input_order": {"required": ["model"]},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
        "ImageSink": {
            "input": {"required": {"image": ["IMAGE"]}},
            "input_order": {"required": ["image"]},
            "output": [],
            "output_name": [],
        },
    }


def test_materialization_applies_default_authored_flavor(tmp_path: Path) -> None:
    """Default authored flavor values materialize into generated workflows."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "flavored.cube", _flavored_cube_payload())
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(_connect_to_sink('use "flavored" as f'), cube_root=cube_root)
    )

    assert _single_node_input(workflow, "seed") == 11


def test_materialization_applies_requested_authored_flavor(tmp_path: Path) -> None:
    """Requested authored flavor values override default materialized values."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "flavored.cube", _flavored_cube_payload())
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            _connect_to_sink('use "flavored" with "Cinematic" as f'),
            cube_root=cube_root,
        )
    )

    assert _single_node_input(workflow, "seed") == 22


def test_materialization_applies_requested_local_flavor(tmp_path: Path) -> None:
    """Requested local flavor values materialize through the compiler path."""

    cube_root = tmp_path / "cubes"
    local_root = tmp_path / "local-flavors"
    cube_root.mkdir()
    cube_payload = _flavored_cube_payload()
    write_cube(cube_root / "flavored.cube", cube_payload)
    _write_sink_cube(cube_root)
    write_local_flavors(
        local_root,
        "flavored",
        compute_surface_signature(validate_cube_document(cube_payload)),
        flavor_id="draft",
        name="Draft",
        values={"seed_control": 33},
    )

    workflow = spawn_plan_to_workflow(
        analyze_text(
            _connect_to_sink('use "flavored" with "Draft" as f'),
            cube_root=cube_root,
            local_flavor_root=local_root,
        )
    )

    assert _single_node_input(workflow, "seed") == 33


def test_explicit_set_overrides_flavor_value(tmp_path: Path) -> None:
    """Explicit set operations win over materialized flavor values."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "flavored.cube", _flavored_cube_payload())
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            _connect_to_sink(
                """
            use "flavored" with "Cinematic" as f
            set f.sampler.seed = 44
            """
            ),
            cube_root=cube_root,
        )
    )

    assert _single_node_input(workflow, "seed") == 44


def test_explicit_set_resolves_surface_label_to_machine_key(tmp_path: Path) -> None:
    """Explicit sets use stored surface labels while prompt output keeps machine keys."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "labeled.cube",
        {
            "cube_id": "labeled",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"cfg": 1}}},
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "sampler.cfg",
                        "symbol": "sampler",
                        "input_name": "cfg",
                        "label": "CFG Scale",
                        "class_type": "KSampler",
                        "value_type": "number",
                    }
                ],
            },
            "flavors": {
                "authored": [{"id": "default", "name": "Default", "values": {"sampler.cfg": 1}}]
            },
            "outputs": {"output.image": "sampler"},
        },
    )
    _write_sink_cube(cube_root)

    plan = analyze_text(
        _connect_to_sink(
            """
            use "labeled" as f
            set f.sampler."CFG Scale" = 7
            """
        ),
        cube_root=cube_root,
    )
    workflow = spawn_plan_to_workflow(plan)

    assert plan["sets"][-1]["input"] == "cfg"
    assert _single_node_input(workflow, "cfg") == 7


def test_explicit_set_resolves_node_label_to_machine_key(tmp_path: Path) -> None:
    """Explicit sets use stored node labels while prompt output keeps machine keys."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "labeled_node.cube",
        {
            "cube_id": "labeled_node",
            "version": "1.0.0",
            "nodes": {
                "models": {
                    "class_type": "ModelLoader",
                    "label": "Models",
                    "inputs": {"diffusion_model": "base.safetensors"},
                }
            },
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "models.diffusion_model",
                        "symbol": "models",
                        "input_name": "diffusion_model",
                        "label": "Diffusion Model",
                        "class_type": "ModelLoader",
                        "value_type": "string",
                    }
                ],
            },
            "flavors": {"authored": [{"id": "default", "name": "Default", "values": {}}]},
            "outputs": {"output.image": "models"},
        },
    )
    _write_sink_cube(cube_root)

    plan = analyze_text(
        _connect_to_sink(
            """
            use "labeled_node" as f
            set f.Models."Diffusion Model" = "anime.safetensors"
            """
        ),
        cube_root=cube_root,
    )
    workflow = spawn_plan_to_workflow(plan)

    assert plan["sets"][-1]["node"] == "models"
    assert plan["sets"][-1]["input"] == "diffusion_model"
    assert _single_node_input(workflow, "diffusion_model") == "anime.safetensors"


def test_dotted_ref_resolves_surface_label(tmp_path: Path) -> None:
    """Dotted reference expressions read values through stored labels."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "labeled.cube",
        {
            "cube_id": "labeled",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "KSampler", "inputs": {"cfg": 3}},
                "target": {"class_type": "KSampler", "inputs": {"cfg": 0}},
            },
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "source.cfg",
                        "symbol": "source",
                        "input_name": "cfg",
                        "label": "CFG Scale",
                        "class_type": "KSampler",
                        "value_type": "number",
                    },
                    {
                        "control_id": "target.cfg",
                        "symbol": "target",
                        "input_name": "cfg",
                        "label": "CFG Scale",
                        "class_type": "KSampler",
                        "value_type": "number",
                    },
                ],
            },
            "flavors": {"authored": [{"id": "default", "name": "Default", "values": {}}]},
            "outputs": {"output.image": "target"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            _connect_to_sink(
                """
                use "labeled" as f
                set f.target."CFG Scale" = f.source."CFG Scale"
                """
            ),
            cube_root=cube_root,
        )
    )

    assert _node_by_title(workflow, "f.target")["inputs"]["cfg"] == 3


def test_wildcard_set_resolves_label_to_machine_key(tmp_path: Path) -> None:
    """Wildcard sets resolve the visible label once before recording machine keys."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "labeled.cube",
        {
            "cube_id": "labeled",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"cfg": 1}}},
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "sampler.cfg",
                        "symbol": "sampler",
                        "input_name": "cfg",
                        "label": "CFG Scale",
                        "class_type": "KSampler",
                        "value_type": "number",
                    }
                ],
            },
            "flavors": {"authored": [{"id": "default", "name": "Default", "values": {}}]},
            "outputs": {"output.image": "sampler"},
        },
    )
    _write_sink_cube(cube_root)

    plan = analyze_text(
        _connect_to_sink(
            """
            use "labeled" as f
            set *.KSampler."CFG Scale" = 9
            """
        ),
        cube_root=cube_root,
    )
    workflow = spawn_plan_to_workflow(plan)

    assert plan["sets"][-1]["input"] == "cfg"
    assert _single_node_input(workflow, "cfg") == 9


def test_wildcard_set_applies_after_explicit_set(tmp_path: Path) -> None:
    """Wildcard set operations are applied after explicit set operations."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "flavored.cube", _flavored_cube_payload())
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            _connect_to_sink(
                """
            use "flavored" as f
            set f.sampler.seed = 44
            set *.KSampler.seed = 55
            """
            ),
            cube_root=cube_root,
        )
    )

    assert _single_node_input(workflow, "seed") == 55


def test_schema_seed_materialization_generates_custom_sampler_seed(
    tmp_path: Path,
) -> None:
    """Custom sampler seed inputs should materialize from schema, not class names."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            node_inputs={"steps": 20},
            required_fields={"seed": _seed_field_spec(), "steps": ["INT"]},
        ),
    )

    assert _only_prompt_node_inputs(workflow)["seed"] == 12345


def test_schema_seed_materialization_preserves_explicit_seed(tmp_path: Path) -> None:
    """Concrete authored seed values should win over generated seed policy."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            node_inputs={"seed": 777, "steps": 20},
            required_fields={"seed": _seed_field_spec(), "steps": ["INT"]},
        ),
    )

    assert _only_prompt_node_inputs(workflow)["seed"] == 777


def test_schema_seed_materialization_generates_none_seed(tmp_path: Path) -> None:
    """Null seed values should materialize through the configured seed provider."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            node_inputs={"seed": None, "steps": 20},
            required_fields={"seed": _seed_field_spec(), "steps": ["INT"]},
        ),
    )

    assert _only_prompt_node_inputs(workflow)["seed"] == 12345


def test_schema_seed_materialization_keeps_ksampler_behavior(tmp_path: Path) -> None:
    """Standard KSampler seed materialization should use the same schema policy."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="KSampler",
            node_inputs={"steps": 20},
            required_fields={"seed": _seed_field_spec(), "steps": ["INT"]},
        ),
    )

    assert _only_prompt_node_inputs(workflow, class_type="KSampler")["seed"] == 12345


def test_schema_seed_materialization_does_not_randomize_non_int_seed(
    tmp_path: Path,
) -> None:
    """Non-integer fields named seed should materialize defaults without randomizing."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="MetadataNode",
            required_fields={"seed": ["STRING", {"default": "literal-seed"}]},
        ),
    )

    assert _only_prompt_node_inputs(workflow, class_type="MetadataNode")["seed"] == "literal-seed"


def test_schema_seed_materialization_ignores_nodes_without_seed_definition(
    tmp_path: Path,
) -> None:
    """Nodes without a declared seed input should not receive generated seeds."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="NotASampler",
            required_fields={"steps": ["INT", {"default": 20}]},
        ),
    )
    inputs = _only_prompt_node_inputs(workflow, class_type="NotASampler")

    assert "seed" not in inputs


def test_schema_input_materialization_uses_non_seed_defaults(tmp_path: Path) -> None:
    """Required non-seed inputs with schema defaults should materialize safely."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="DefaultedNode",
            required_fields={"steps": ["INT", {"default": 20}]},
        ),
    )

    assert _only_prompt_node_inputs(workflow, class_type="DefaultedNode")["steps"] == 20


def test_schema_input_materialization_leaves_unsafe_required_input_absent(
    tmp_path: Path,
) -> None:
    """Required inputs without defaults or policy should remain Comfy-validated."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="UnsafeRequiredNode",
            required_fields={"cfg": "FLOAT"},
        ),
    )

    assert "cfg" not in _only_prompt_node_inputs(workflow, class_type="UnsafeRequiredNode")


def test_schema_input_materialization_does_not_invent_compact_list_default(
    tmp_path: Path,
) -> None:
    """Compact LIST definitions without metadata should not synthesize values."""

    workflow = _build_defaulted_input_workflow(
        tmp_path,
        _defaulted_input_cube_payload(
            class_type="ListNode",
            required_fields={"sampler_name": ["LIST"]},
        ),
    )

    assert "sampler_name" not in _only_prompt_node_inputs(workflow, class_type="ListNode")


def test_connection_error_reports_available_bindings(tmp_path: Path) -> None:
    """Invalid binding diagnostics include the available binding names."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.image": "node"},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Target", "inputs": {"image": None}}},
            "inputs": {"input.image": [["node", "image"]]},
        },
    )

    with pytest.raises(RuntimeError, match=r"Available: output\.image"):
        analyze_text(
            """
            use "source" as s
            use "target" as t
            connect s.output.missing to t.input.image
            """,
            cube_root=cube_root,
        )


def test_connection_preserves_list_shaped_output_port(tmp_path: Path) -> None:
    """Connections preserve non-zero output slots from cube output bindings."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.second": ["node", 1]},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"image": None}}},
            "inputs": {"input.image": [["sink", "image"]]},
        },
    )

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "source" as s
            use "target" as t
            connect s.output.second to t.input.image
            """,
            cube_root=cube_root,
        )
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [source_node_id, 1]


def test_declared_outputs_compile_to_cube_output_nodes(tmp_path: Path) -> None:
    """Canonical cube outputs should create executable workflow output nodes."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "metadata": {"default_alias": "Source Default"},
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.image": ["node", 1]},
        },
    )
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "source" as RuntimeSource
            use "sink" as out
            connect RuntimeSource.output.image to out.input.image
            """,
            cube_root=cube_root,
        )
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    output_node = next(
        node for node in workflow.values() if node["class_type"] == "SugarCubes.CubeOutput"
    )

    assert output_node["inputs"] == {
        "value": [source_node_id, 1],
        "cube_id": "source",
        "default_alias": "Source Default",
        "instance_alias": "RuntimeSource",
        "instance_id": "RuntimeSource",
    }


def test_connection_uses_declared_output_source_not_output_boundary(
    tmp_path: Path,
) -> None:
    """Cube-to-cube connections should keep using the canonical output source."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.image": "node"},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"image": None}}},
            "inputs": {"input.image": [["sink", "image"]]},
        },
    )

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "source" as s
            use "target" as t
            connect s.output.image to t.input.image
            """,
            cube_root=cube_root,
        )
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    output_node_id = next(
        node_id
        for node_id, node in workflow.items()
        if node["class_type"] == "SugarCubes.CubeOutput"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [source_node_id, 0]
    assert sink["inputs"]["image"] != [output_node_id, 0]


def test_connection_resolves_serialized_binding_sentinel(tmp_path: Path) -> None:
    """Cube input sentinels resolve through declared input binding targets."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.image": "node"},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {
                "sink": {
                    "class_type": "Sink",
                    "inputs": {"image": ["@binding", "input.image"]},
                }
            },
            "inputs": {"input.image": [["sink", "image"]]},
        },
    )

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "source" as s
            use "target" as t
            connect s.output.image to t.input.image
            """,
            cube_root=cube_root,
        )
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [source_node_id, 0]


def test_connection_rejects_invalid_output_slot(tmp_path: Path) -> None:
    """Malformed output binding slots fail before workflow generation."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Source", "inputs": {}}},
            "outputs": {"output.image": ["node", True]},
        },
    )
    write_cube(
        cube_root / "target.cube",
        {
            "cube_id": "target",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"image": None}}},
            "inputs": {"input.image": [["sink", "image"]]},
        },
    )

    with pytest.raises(RuntimeError, match="invalid boolean slot"):
        analyze_text(
            """
            use "source" as s
            use "target" as t
            connect s.output.image to t.input.image
            """,
            cube_root=cube_root,
        )


def test_disable_passthrough_rewires_matching_downstream_input(
    tmp_path: Path,
) -> None:
    """Disabling a node forwards a same-named upstream input to consumers."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {"class_type": "Middle", "inputs": {"image": ["source", 0]}},
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "chain" as c
            use "sink" as out
            connect c.output.image to out.input.image
            disable c.middle
            """,
            cube_root=cube_root,
        )
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [source_node_id, 0]


def test_disable_passthrough_without_matching_input_sets_none(
    tmp_path: Path,
) -> None:
    """Disabling a node without a same-named upstream value clears consumers."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {"class_type": "Middle", "inputs": {"model": ["source", 0]}},
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = spawn_plan_to_workflow(
        analyze_text(
            """
            use "chain" as c
            use "sink" as out
            connect c.output.image to out.input.image
            disable c.middle
            """,
            cube_root=cube_root,
        )
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] is None


def test_authored_bypass_mode_reuses_disable_passthrough(
    tmp_path: Path,
) -> None:
    """Authored LiteGraph bypass mode should disable execution like Sugar disable."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {
                    "class_type": "Middle",
                    "mode": 4,
                    "inputs": {"image": ["source", 0]},
                },
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "chain" as c
        use "sink" as out
        connect c.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    source_node_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert all(node["class_type"] != "Middle" for node in workflow.values())
    assert sink["inputs"]["image"] == [source_node_id, 0]


def test_enable_restores_authored_bypass_node_execution(
    tmp_path: Path,
) -> None:
    """Enable should opt an authored bypass node back into execution."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {
                    "class_type": "Middle",
                    "mode": 4,
                    "inputs": {"image": ["source", 0]},
                },
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "chain" as c
        use "sink" as out
        connect c.output.image to out.input.image
        enable c.middle
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    middle_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Middle"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [middle_id, 0]


def test_authored_invalid_mode_does_not_disable_execution(
    tmp_path: Path,
) -> None:
    """Non-integer authored mode values should not affect prompt execution."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {
                    "class_type": "Middle",
                    "mode": "4",
                    "inputs": {"image": ["source", 0]},
                },
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "chain" as c
        use "sink" as out
        connect c.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    assert any(node["class_type"] == "Middle" for node in workflow.values())


def test_boolean_mode_four_does_not_disable_execution(
    tmp_path: Path,
) -> None:
    """Boolean mode values should not count as authored bypass metadata."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "middle": {
                    "class_type": "Middle",
                    "mode": True,
                    "inputs": {"image": ["source", 0]},
                },
                "sink": {"class_type": "Sink", "inputs": {"image": ["middle", 0]}},
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "chain" as c
        use "sink" as out
        connect c.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    assert any(node["class_type"] == "Middle" for node in workflow.values())


def test_authored_bypass_provider_inherits_model_clip_and_vae_links(
    tmp_path: Path,
) -> None:
    """Authored bypass providers should inherit nearest live provider outputs."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_provider_inheritance_cubes(cube_root)

    workflow = build_workflow_from_text(
        """
        use "provider_source" as A
        use "provider_target" as B
        connect A.output.image to B.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    title_by_id = _title_by_id(workflow)
    assert "B.provider" not in title_by_id.values()

    source_provider_id = next(
        node_id for node_id, title in title_by_id.items() if title == "A.provider"
    )
    target_schedule_id = next(
        node_id for node_id, title in title_by_id.items() if title == "B.schedule"
    )
    target_schedule = _node_by_title(workflow, "B.schedule")
    target_model_consumer = _node_by_title(workflow, "B.model_consumer")
    target_vae_consumer = _node_by_title(workflow, "B.vae_consumer")

    assert target_schedule["inputs"]["model_in"] == [source_provider_id, 0]
    assert target_schedule["inputs"]["clip_in"] == [source_provider_id, 1]
    assert target_model_consumer["inputs"]["model"] == [target_schedule_id, 0]
    assert target_vae_consumer["inputs"]["vae"] == [source_provider_id, 2]
    assert _object_provider_inputs(workflow).isdisjoint({"auto"})


def test_enabled_authored_bypass_provider_uses_local_provider_links(
    tmp_path: Path,
) -> None:
    """Enable should keep an authored bypass provider in the executable graph."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    _write_provider_inheritance_cubes(cube_root)

    workflow = build_workflow_from_text(
        """
        use "provider_source" as A
        use "provider_target" as B
        connect A.output.image to B.input.image
        enable B.provider
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    title_by_id = _title_by_id(workflow)
    provider_id = next(node_id for node_id, title in title_by_id.items() if title == "B.provider")
    target_schedule_id = next(
        node_id for node_id, title in title_by_id.items() if title == "B.schedule"
    )
    target_schedule = _node_by_title(workflow, "B.schedule")
    target_model_consumer = _node_by_title(workflow, "B.model_consumer")
    target_vae_consumer = _node_by_title(workflow, "B.vae_consumer")

    assert target_schedule["inputs"]["model_in"] == [provider_id, 0]
    assert target_schedule["inputs"]["clip_in"] == [provider_id, 1]
    assert target_model_consumer["inputs"]["model"] == [target_schedule_id, 0]
    assert target_vae_consumer["inputs"]["vae"] == [provider_id, 2]


def test_inheritance_never_uses_target_cube_as_provider(tmp_path: Path) -> None:
    """Missing provider inputs should not inherit from target-side consumers."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    definitions = {
        "Provider": {
            "input": {"required": {"model": ["COMBO"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Schedule": {
            "input": {"required": {"model_in": ["MODEL"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Processor": {
            "input": {"required": {"model": ["MODEL"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Consumer": {
            "input": {"required": {"model": ["MODEL"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
        "ImageSink": {
            "input": {"required": {"image": ["IMAGE"]}},
            "output": [],
            "output_name": [],
        },
    }
    write_cube(
        cube_root / "provider_source.cube",
        {
            "cube_id": "provider_source",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "inputs": {"model": "source-model"},
                },
                "image": {
                    "class_type": "Consumer",
                    "inputs": {"model": ["provider", 0]},
                },
            },
            "outputs": {"output.image": ["image", 0]},
            "definitions": definitions,
        },
    )
    write_cube(
        cube_root / "provider_target.cube",
        {
            "cube_id": "provider_target",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "mode": 4,
                    "inputs": {"model": "target-model"},
                },
                "schedule": {
                    "class_type": "Schedule",
                    "inputs": {"model_in": ["provider", 0]},
                },
                "processor": {
                    "class_type": "Processor",
                    "inputs": {"model": ["schedule", 0]},
                },
                "consumer": {
                    "class_type": "Consumer",
                    "inputs": {"model": ["processor", 0]},
                },
                "image_sink": {"class_type": "ImageSink", "inputs": {"image": None}},
            },
            "inputs": {"input.image": [["image_sink", "image"]]},
            "definitions": definitions,
        },
    )

    workflow = build_workflow_from_text(
        """
        use "provider_source" as A
        use "provider_target" as B
        connect A.output.image to B.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    title_by_id = _title_by_id(workflow)
    source_provider_id = next(
        node_id for node_id, title in title_by_id.items() if title == "A.provider"
    )
    target_schedule = _node_by_title(workflow, "B.schedule")
    plan = analyze_text(
        """
        use "provider_source" as A
        use "provider_target" as B
        connect A.output.image to B.input.image
        """,
        cube_root=cube_root,
    )
    inferred_model_sets = [
        set_entry
        for set_entry in plan["sets"]
        if set_entry.get("input") == "model_in"
        and (set_entry.get("metadata") or {}).get("node_key") == "B.schedule"
    ]

    assert target_schedule["inputs"]["model_in"] == [source_provider_id, 0]
    assert inferred_model_sets == [
        {
            "alias": "B",
            "node": "schedule",
            "input": "model_in",
            "value": ["A.provider", 0],
            "metadata": {"kind": "inferred", "node_key": "B.schedule"},
        }
    ]


def test_disabled_model_filter_preserves_local_passthrough_chain(
    tmp_path: Path,
) -> None:
    """Local disable passthrough should not root-rewrite model chains."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    definitions = {
        "Provider": {
            "input": {"required": {"model": ["COMBO"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Schedule": {
            "input": {"required": {"model_in": ["MODEL"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Vectorscope": {
            "input": {"required": {"model": ["MODEL"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "Mahiro": {
            "input": {"required": {"model": ["MODEL"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
    }
    write_cube(
        cube_root / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "checkpoint": {
                    "class_type": "Provider",
                    "inputs": {"model": "base-model"},
                },
                "schedule": {
                    "class_type": "Schedule",
                    "inputs": {"model_in": ["checkpoint", 0]},
                },
                "vectorscope": {
                    "class_type": "Vectorscope",
                    "inputs": {"model": ["schedule", 0]},
                },
                "mahiro": {
                    "class_type": "Mahiro",
                    "inputs": {"model": ["vectorscope", 0]},
                },
            },
            "outputs": {"output.model": ["mahiro", 0]},
            "definitions": definitions,
        },
    )

    workflow = build_workflow_from_text(
        """
        use "chain" as c
        disable c.vectorscope
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    title_by_id = _title_by_id(workflow)
    schedule_id = next(node_id for node_id, title in title_by_id.items() if title == "c.schedule")
    mahiro = _node_by_title(workflow, "c.mahiro")

    assert mahiro["inputs"]["model"] == [schedule_id, 0]


def test_vae_switch_inherits_selected_live_provider(tmp_path: Path) -> None:
    """VAE inheritance should follow the selected live switch source."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    definitions = {
        "Checkpoint": {
            "input": {"required": {"ckpt_name": ["LIST"]}},
            "output": ["MODEL", "CLIP", "VAE"],
            "output_name": ["MODEL", "CLIP", "VAE"],
        },
        "VAELoader": {
            "input": {"required": {"vae_name": ["LIST"]}},
            "output": ["VAE"],
            "output_name": ["VAE"],
        },
        "AnySwitch": {
            "input": {"required": {"0": ["*"], "1": ["*"]}},
            "output": ["*"],
            "output_name": ["*"],
        },
        "VAEDecode": {
            "input": {"required": {"vae": ["VAE"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
        "VaeConsumer": {
            "input": {"required": {"vae": ["VAE"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
    }
    write_cube(
        cube_root / "vae_source.cube",
        {
            "cube_id": "vae_source",
            "version": "1.0.0",
            "nodes": {
                "checkpoint": {
                    "class_type": "Checkpoint",
                    "inputs": {"ckpt_name": "base.safetensors"},
                },
                "vae_override": {
                    "class_type": "VAELoader",
                    "mode": 4,
                    "inputs": {"vae_name": "override.vae.safetensors"},
                },
                "vae_switch": {
                    "class_type": "AnySwitch",
                    "inputs": {"0": ["vae_override", 0], "1": ["checkpoint", 2]},
                },
                "decoder": {
                    "class_type": "VAEDecode",
                    "inputs": {"vae": ["vae_switch", 0]},
                },
            },
            "outputs": {"output.image": ["decoder", 0]},
            "definitions": definitions,
        },
    )
    write_cube(
        cube_root / "vae_target.cube",
        {
            "cube_id": "vae_target",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "VAELoader",
                    "mode": 4,
                    "inputs": {"vae_name": "target.vae.safetensors"},
                },
                "consumer": {
                    "class_type": "VaeConsumer",
                    "inputs": {"vae": ["provider", 0]},
                },
                "image_sink": {"class_type": "VaeConsumer", "inputs": {"vae": None}},
            },
            "inputs": {"input.image": [["image_sink", "vae"]]},
            "definitions": definitions,
        },
    )

    default_workflow = build_workflow_from_text(
        """
        use "vae_source" as A
        use "vae_target" as B
        connect A.output.image to B.input.image
        """,
        output_dir=tmp_path / "default",
        cube_root=cube_root,
    )
    default_title_by_id = _title_by_id(default_workflow)
    default_checkpoint_id = next(
        node_id for node_id, title in default_title_by_id.items() if title == "A.checkpoint"
    )
    default_consumer = _node_by_title(default_workflow, "B.consumer")

    enabled_workflow = build_workflow_from_text(
        """
        use "vae_source" as A
        use "vae_target" as B
        connect A.output.image to B.input.image
        enable A.vae_override
        """,
        output_dir=tmp_path / "enabled",
        cube_root=cube_root,
    )
    enabled_title_by_id = _title_by_id(enabled_workflow)
    enabled_override_id = next(
        node_id for node_id, title in enabled_title_by_id.items() if title == "A.vae_override"
    )
    enabled_consumer = _node_by_title(enabled_workflow, "B.consumer")

    assert default_consumer["inputs"]["vae"] == [default_checkpoint_id, 2]
    assert enabled_consumer["inputs"]["vae"] == [enabled_override_id, 0]


def test_inheritance_walks_back_past_cubes_without_live_provider(
    tmp_path: Path,
) -> None:
    """Inheritance should keep searching when a nearer cube has no provider."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    definitions = {
        "Provider": {
            "input": {"required": {"model": ["COMBO"]}},
            "output": ["MODEL"],
            "output_name": ["MODEL"],
        },
        "ModelConsumer": {
            "input": {"required": {"model": ["MODEL"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
        "ImagePassthrough": {
            "input": {"required": {"image": ["IMAGE"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
        "Wrapper": {
            "input": {"required": {"model_in": ["MODEL"], "image": ["IMAGE"]}},
            "output": ["IMAGE"],
            "output_name": ["IMAGE"],
        },
    }
    write_cube(
        cube_root / "first.cube",
        {
            "cube_id": "first",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "inputs": {"model": "first-model"},
                },
                "image": {
                    "class_type": "ModelConsumer",
                    "inputs": {"model": ["provider", 0]},
                },
            },
            "outputs": {"output.image": ["image", 0]},
            "definitions": definitions,
        },
    )
    write_cube(
        cube_root / "middle.cube",
        {
            "cube_id": "middle",
            "version": "1.0.0",
            "nodes": {
                "passthrough": {
                    "class_type": "ImagePassthrough",
                    "inputs": {"image": None},
                }
            },
            "inputs": {"input.image": [["passthrough", "image"]]},
            "outputs": {"output.image": ["passthrough", 0]},
            "definitions": definitions,
        },
    )
    write_cube(
        cube_root / "last.cube",
        {
            "cube_id": "last",
            "version": "1.0.0",
            "nodes": {
                "provider": {
                    "class_type": "Provider",
                    "mode": 4,
                    "inputs": {"model": "last-model"},
                },
                "wrapper": {
                    "class_type": "Wrapper",
                    "inputs": {"model_in": ["provider", 0], "image": None},
                },
            },
            "inputs": {"input.image": [["wrapper", "image"]]},
            "outputs": {"output.image": ["wrapper", 0]},
            "definitions": definitions,
        },
    )

    workflow = build_workflow_from_text(
        """
        use "first" as A
        use "middle" as B
        use "last" as C
        connect A.output.image to B.input.image
        connect B.output.image to C.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    title_by_id = _title_by_id(workflow)
    source_provider_id = next(
        node_id for node_id, title in title_by_id.items() if title == "A.provider"
    )
    wrapper = _node_by_title(workflow, "C.wrapper")

    assert wrapper["inputs"]["model_in"] == [source_provider_id, 0]


def test_authored_bypassed_vae_override_is_omitted_from_execution_prompt(
    tmp_path: Path,
) -> None:
    """Bypassed provider overrides should remain visible but not execute."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "vae_override.cube",
        {
            "cube_id": "vae_override",
            "version": "1.0.0",
            "nodes": {
                "checkpoint": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "base.safetensors"},
                },
                "vae_override": {
                    "class_type": "VAELoader",
                    "mode": 4,
                    "inputs": {"vae_name": "override.vae.safetensors"},
                },
                "vae_switch": {
                    "class_type": "AnySwitch",
                    "inputs": {
                        "0": ["vae_override", 0],
                        "1": ["checkpoint", 2],
                    },
                },
                "decoder": {
                    "class_type": "VAEDecode",
                    "inputs": {"vae": ["vae_switch", 0]},
                },
            },
            "outputs": {"output.image": "decoder"},
            "definitions": {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": ["LIST"]}},
                    "output": ["MODEL", "CLIP", "VAE"],
                    "output_name": ["MODEL", "CLIP", "VAE"],
                },
                "VAELoader": {
                    "input": {"required": {"vae_name": ["LIST"]}},
                    "output": ["VAE"],
                    "output_name": ["VAE"],
                },
                "AnySwitch": {
                    "input": {"required": {"0": ["*"], "1": ["*"]}},
                    "output": ["*"],
                    "output_name": ["*"],
                },
                "VAEDecode": {
                    "input": {"required": {"vae": ["VAE"]}},
                    "output": ["IMAGE"],
                    "output_name": ["IMAGE"],
                },
            },
        },
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "vae_override" as v',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    prompt = artifacts["prompt"]
    workflow = artifacts["workflow"]
    switch = next(node for node in prompt.values() if node["class_type"] == "AnySwitch")
    checkpoint_id = next(
        node_id
        for node_id, node in prompt.items()
        if node["class_type"] == "CheckpointLoaderSimple"
    )
    ui_vae_override = next(node for node in workflow["nodes"] if node["type"] == "VAELoader")

    assert all(node["class_type"] != "VAELoader" for node in prompt.values())
    assert switch["inputs"]["0"] is None
    assert switch["inputs"]["1"] == [checkpoint_id, 2]
    assert ui_vae_override["mode"] == 4


def test_unresolved_disable_target_is_fatal(tmp_path: Path) -> None:
    """Disable statements fail when the target node cannot be resolved."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(cube_root / "flavored.cube", _flavored_cube_payload())

    with pytest.raises(RuntimeError, match="Node 'missing' not found"):
        analyze_text(
            """
            use "flavored" as f
            disable f.missing
            """,
            cube_root=cube_root,
        )


def test_valid_cube_binding_shapes_are_accepted() -> None:
    """Catalog validation accepts supported input and output binding shapes."""

    validate_cube_document(
        current_cube_payload(
            {
                "cube_id": "valid_bindings",
                "version": "1.0.0",
                "nodes": {
                    "source": {"class_type": "Source", "inputs": {}},
                    "target": {"class_type": "Target", "inputs": {"image": None}},
                },
                "inputs": {
                    "input.image": [["target", "image"]],
                    "input.mask": {"targets": [["target", "image"]]},
                },
                "outputs": {
                    "output.image": "source",
                    "output.second": ["source", 1],
                },
            }
        )
    )


def test_validate_cube_document_rejects_surface_control_without_label() -> None:
    """Catalog validation requires current-format surface control labels."""

    payload = current_cube_payload(
        {
            "cube_id": "missing_label",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"cfg": 1}}},
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "sampler.cfg",
                        "symbol": "sampler",
                        "input_name": "cfg",
                        "class_type": "KSampler",
                        "value_type": "number",
                    }
                ],
            },
            "flavors": {"authored": [{"id": "default", "name": "Default", "values": {}}]},
        }
    )
    del payload["surface"]["controls"][0]["label"]

    with pytest.raises(RuntimeError, match="label"):
        validate_cube_document(payload)


def test_validate_cube_document_rejects_subgraph_input_without_label() -> None:
    """Catalog validation requires current-format public subgraph labels."""

    payload = current_cube_payload(_wrapper_cube_payload_for_label_validation())
    del payload["implementation"]["subgraphs"][0]["inputs"][0]["label"]

    with pytest.raises(RuntimeError, match="label"):
        validate_cube_document(payload)


def test_invalid_cube_input_mapping_structure_is_fatal(tmp_path: Path) -> None:
    """Invalid cube input target entries fail during catalog validation."""

    cube_root = tmp_path / "cubes"
    output_dir = tmp_path / "out"
    cube_root.mkdir()
    output_dir.mkdir()
    write_cube(
        cube_root / "invalid.cube",
        {
            "cube_id": "invalid",
            "version": "1.0.0",
            "nodes": {"node": {"class_type": "Target", "inputs": {"image": None}}},
            "inputs": {"input.image": [["node"]]},
        },
    )

    with pytest.raises(
        RuntimeError,
        match=r"Cube input binding 'input\.image' target #1 must be \[node, input\]",
    ):
        build_workflow_from_text(
            'use "invalid" as i',
            output_dir=output_dir,
            cube_root=cube_root,
        )


def test_validate_cube_document_rejects_inherit_input_kind() -> None:
    """Reject legacy SugarCubes inherit marker bindings at the catalog boundary."""

    with pytest.raises(
        RuntimeError,
        match=r"Cube input binding 'input\.model' has unsupported kind 'inherit'",
    ):
        validate_cube_document(
            current_cube_payload(
                {
                    "cube_id": "invalid",
                    "version": "1.0.0",
                    "nodes": {"node": {"class_type": "Target", "inputs": {"model": None}}},
                    "inputs": {
                        "input.model": {
                            "kind": "inherit",
                            "targets": [["node", "model"]],
                        }
                    },
                    "outputs": {"output.model": "node"},
                }
            )
        )


def test_dotted_node_keys_remain_distinct_during_compilation(
    tmp_path: Path,
) -> None:
    """Materialization preserves full dotted node identity under the alias."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "dotted.cube",
        {
            "cube_id": "dotted",
            "version": "1.0.0",
            "nodes": {
                "group.source": {"class_type": "SourceA", "inputs": {}},
                "other.source": {"class_type": "SourceB", "inputs": {}},
                "sink": {
                    "class_type": "Sink",
                    "inputs": {
                        "a": ["group.source", 0],
                        "b": ["other.source", 0],
                    },
                },
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "dotted" as d
        use "sink" as out
        connect d.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    source_a_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "SourceA"
    )
    source_b_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "SourceB"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["a"] == [source_a_id, 0]
    assert sink["inputs"]["b"] == [source_b_id, 0]


def test_explicit_set_targets_dotted_node_key(tmp_path: Path) -> None:
    """Explicit set statements resolve full dotted node names."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "dotted.cube",
        {
            "cube_id": "dotted",
            "version": "1.0.0",
            "nodes": {
                "group.sampler": {
                    "class_type": "KSampler",
                    "inputs": {"cfg": 1},
                }
            },
            "outputs": {"output.image": "group.sampler"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "dotted" as d
        use "sink" as out
        connect d.output.image to out.input.image
        set d.group.sampler.cfg = 7
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    sampler = next(node for node in workflow.values() if node["class_type"] == "KSampler")
    assert sampler["inputs"]["cfg"] == 7


def test_flavor_values_target_dotted_surface_symbols(tmp_path: Path) -> None:
    """Flavor values apply to full dotted surface control symbols."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "dotted.cube",
        {
            "cube_id": "dotted",
            "version": "1.0.0",
            "nodes": {
                "group.sampler": {
                    "class_type": "KSampler",
                    "inputs": {"cfg": 1},
                }
            },
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": "group.sampler.cfg",
                        "symbol": "group.sampler",
                        "input_name": "cfg",
                        "class_type": "KSampler",
                        "value_type": "number",
                    }
                ],
            },
            "flavors": {
                "authored": [
                    {
                        "id": "default",
                        "name": "Default",
                        "values": {"group.sampler.cfg": 9},
                    }
                ]
            },
            "outputs": {"output.image": "group.sampler"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "dotted" as d
        use "sink" as out
        connect d.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    sampler = next(node for node in workflow.values() if node["class_type"] == "KSampler")
    assert sampler["inputs"]["cfg"] == 9


def test_disable_targets_dotted_node_key(tmp_path: Path) -> None:
    """Disable statements resolve dotted node names without suffix fallback."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "dotted.cube",
        {
            "cube_id": "dotted",
            "version": "1.0.0",
            "nodes": {
                "source": {"class_type": "Source", "inputs": {}},
                "group.middle": {
                    "class_type": "Middle",
                    "inputs": {"image": ["source", 0]},
                },
                "sink": {
                    "class_type": "Sink",
                    "inputs": {"image": ["group.middle", 0]},
                },
            },
            "outputs": {"output.image": "sink"},
        },
    )
    _write_sink_cube(cube_root)

    workflow = build_workflow_from_text(
        """
        use "dotted" as d
        use "sink" as out
        connect d.output.image to out.input.image
        disable d.group.middle
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )
    source_id = next(
        node_id for node_id, node in workflow.items() if node["class_type"] == "Source"
    )
    sink = next(node for node in workflow.values() if node["class_type"] == "Sink")

    assert sink["inputs"]["image"] == [source_id, 0]


def test_suffix_only_reference_to_dotted_node_is_fatal(tmp_path: Path) -> None:
    """Dotted node lookup does not fall back to lossy suffix matching."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "dotted.cube",
        {
            "cube_id": "dotted",
            "version": "1.0.0",
            "nodes": {
                "group.source": {
                    "class_type": "Source",
                    "inputs": {"value": 0},
                }
            },
        },
    )

    with pytest.raises(RuntimeError, match="Node 'source' not found"):
        build_workflow_from_text(
            """
            use "dotted" as d
            set d.source.value = 1
            """,
            output_dir=tmp_path / "out",
            cube_root=cube_root,
        )
