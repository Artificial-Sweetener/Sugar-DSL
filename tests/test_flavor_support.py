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
"""Flavor catalog, resolution, and materialization behavior tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.cubes import write_local_flavors
from sugar.catalog.local_flavors import LocalFlavorCatalog
from sugar.catalog.models import validate_cube_document
from sugar.catalog.registry import CubeRegistry
from sugar.compiler.analyzer import analyze_text
from sugar.compiler.codegen import spawn_plan_to_workflow
from sugar.compiler.flavors import compute_surface_signature

Payload = dict[str, Any]


def current_cube_payload() -> Payload:
    """Return the flavored cube fixture used by flavor behavior tests."""

    return {
        "cube_id": "flavored",
        "version": "1.0.0",
        "implementation": {
            "nodes": {
                "ksampler": {
                    "class_type": "KSampler",
                    "inputs": {"cfg": 1, "steps": 20},
                }
            },
            "inputs": {},
            "outputs": {"output.image": "ksampler"},
            "definitions": {},
            "subgraphs": [],
            "layout": {},
        },
        "surface": {
            "default_flavor_id": "default",
            "controls": [
                {
                    "control_id": "ksampler.cfg",
                    "symbol": "ksampler",
                    "input_name": "cfg",
                    "label": "cfg",
                    "class_type": "KSampler",
                    "value_type": "number",
                },
                {
                    "control_id": "ksampler.steps",
                    "symbol": "ksampler",
                    "input_name": "steps",
                    "label": "steps",
                    "class_type": "KSampler",
                    "value_type": "number",
                },
            ],
        },
        "flavors": {
            "authored": [
                {"id": "default", "name": "Default", "values": {"ksampler.cfg": 5}},
                {"id": "portrait", "name": "Portrait", "values": {"ksampler.cfg": 7}},
            ]
        },
    }


def write_cube(root: Path, payload: Payload | None = None) -> Payload:
    """Write the flavored cube fixture to a cube root."""

    payload = payload or current_cube_payload()
    root.mkdir(parents=True, exist_ok=True)
    (root / "flavored.cube").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def write_sink_cube(root: Path) -> None:
    """Write a generic sink cube for connected recipe fixtures."""

    (root / "sink.cube").write_text(
        json.dumps(
            {
                "cube_id": "sink",
                "version": "1.0.0",
                "implementation": {
                    "nodes": {"sink": {"class_type": "Sink", "inputs": {"value": None}}},
                    "inputs": {"input.image": [["sink", "value"]]},
                    "outputs": {},
                    "definitions": {},
                    "subgraphs": [],
                    "layout": {},
                },
                "surface": {"default_flavor_id": "default", "controls": []},
                "flavors": {"authored": [{"id": "default", "name": "Default", "values": {}}]},
            }
        ),
        encoding="utf-8",
    )


def test_validate_cube_document_loads_current_format_without_top_level_nodes() -> None:
    """Current-format cubes load implementation data into compiler fields."""

    payload = current_cube_payload()

    validated = validate_cube_document(payload)

    assert validated["nodes"]["ksampler"]["inputs"]["cfg"] == 1
    assert validated["layout"] == {}
    assert validated["surface"]["default_flavor_id"] == "default"


def test_validate_cube_document_accepts_compact_dynamic_and_fixed_list_definitions() -> None:
    """Compact definitions can carry bare lists, fixed enums, and scalar constraints."""

    payload = current_cube_payload()
    payload["implementation"]["definitions"] = {
        "KSampler": {
            "input": {
                "required": {
                    "sampler_name": ["LIST"],
                    "seed": ["INT", {"min": 0, "max": 999, "step": 1}],
                }
            },
            "input_order": {"required": ["seed", "sampler_name"]},
        },
        "LoadImageMask": {
            "input": {
                "required": {
                    "image": ["LIST", {"image_upload": True}],
                    "channel": [
                        ["alpha", "red", "green", "blue"],
                        {"default": "alpha"},
                    ],
                }
            }
        },
    }

    validated = validate_cube_document(payload)

    assert validated["definitions"]["KSampler"]["input"]["required"]["sampler_name"] == ["LIST"]


def test_validate_cube_document_rejects_malformed_compact_list_metadata() -> None:
    """Compact LIST markers must not carry non-object metadata."""

    payload = current_cube_payload()
    payload["implementation"]["definitions"] = {
        "KSampler": {"input": {"required": {"sampler_name": ["LIST", "bad"]}}}
    }

    with pytest.raises(RuntimeError, match="scalar metadata must be an object"):
        validate_cube_document(payload)


def test_validate_cube_document_rejects_missing_current_format_sections() -> None:
    """Current-format cube validation rejects missing implementation nodes."""

    payload = current_cube_payload()
    del payload["implementation"]["nodes"]

    with pytest.raises(RuntimeError, match="nodes"):
        validate_cube_document(payload)


def test_validate_cube_document_rejects_missing_implementation_layout() -> None:
    """Current-format cube validation requires implementation layout data."""

    payload = current_cube_payload()
    del payload["implementation"]["layout"]

    with pytest.raises(RuntimeError, match="layout"):
        validate_cube_document(payload)


def test_validate_cube_document_rejects_unknown_authored_flavor_control() -> None:
    """Authored flavor values must reference declared surface controls."""

    payload = current_cube_payload()
    payload["flavors"]["authored"][0]["values"]["missing.control"] = 1

    with pytest.raises(RuntimeError, match="unknown surface control"):
        validate_cube_document(payload)


def test_registry_indexes_current_format_cube(tmp_path: Path) -> None:
    """Cube registry indexes current-format cubes by cube id and version."""

    cube_root = tmp_path / "cubes"
    write_cube(cube_root)

    registry = CubeRegistry(cube_root)

    assert registry.get_version("flavored") == "1.0.0"
    assert registry.load_cube("flavored")["nodes"]["ksampler"]["class_type"] == "KSampler"


def test_analyzer_resolves_authored_flavor_and_codegen_applies_explicit_override(
    tmp_path: Path,
) -> None:
    """Authored flavor values apply before explicit DSL set statements."""

    cube_root = tmp_path / "cubes"
    write_cube(cube_root)
    write_sink_cube(cube_root)
    dsl = """use "flavored" with "Portrait" as img
use "sink" as out
connect img.output.image to out.input.image
set img.ksampler.cfg = 9"""

    plan = analyze_text(dsl, cube_root=cube_root)
    workflow = spawn_plan_to_workflow(plan, cube_root=cube_root)
    sampler = next(node for node in workflow.values() if node["class_type"] == "KSampler")

    assert plan["cubes"][0]["flavor"] == "Portrait"
    assert plan["cubes"][0]["flavor_id"] == "portrait"
    assert plan["cubes"][0]["flavor_scope"] == "authored"
    assert sampler["inputs"]["cfg"] == 9


def test_codegen_preserves_authored_picker_preference_without_inventory(
    tmp_path: Path,
) -> None:
    """Authored picker values should compile while definitions stay compact."""

    cube_root = tmp_path / "cubes"
    payload = current_cube_payload()
    payload["implementation"]["nodes"]["ksampler"]["inputs"] = {}
    payload["implementation"]["definitions"] = {
        "KSampler": {
            "input": {"required": {"sampler_name": ["LIST"]}},
            "input_order": {"required": ["sampler_name"]},
        }
    }
    payload["surface"]["controls"] = [
        {
            "control_id": "ksampler.sampler_name",
            "symbol": "ksampler",
            "input_name": "sampler_name",
            "label": "sampler_name",
            "class_type": "KSampler",
            "value_type": "string",
        }
    ]
    payload["flavors"]["authored"] = [
        {
            "id": "default",
            "name": "Default",
            "values": {"ksampler.sampler_name": "euler_ancestral"},
        }
    ]
    write_cube(cube_root, payload)

    workflow = spawn_plan_to_workflow(
        analyze_text('use "flavored" as img', cube_root=cube_root),
        cube_root=cube_root,
    )
    sampler = next(node for node in workflow.values() if node["class_type"] == "KSampler")

    assert sampler["inputs"]["sampler_name"] == "euler_ancestral"


def test_codegen_leaves_missing_picker_preference_absent(
    tmp_path: Path,
) -> None:
    """Missing compact picker values remain absent for Substitute local fallback."""

    cube_root = tmp_path / "cubes"
    payload = current_cube_payload()
    payload["implementation"]["nodes"]["ksampler"]["inputs"] = {}
    payload["implementation"]["definitions"] = {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": ["LIST"]}},
            "input_order": {"required": ["ckpt_name"]},
        }
    }
    payload["implementation"]["nodes"]["ksampler"]["class_type"] = "CheckpointLoaderSimple"
    payload["surface"]["controls"] = [
        {
            "control_id": "ksampler.ckpt_name",
            "symbol": "ksampler",
            "input_name": "ckpt_name",
            "label": "ckpt_name",
            "class_type": "CheckpointLoaderSimple",
            "value_type": "string",
        }
    ]
    payload["flavors"]["authored"] = [{"id": "default", "name": "Default", "values": {}}]
    write_cube(cube_root, payload)

    workflow = spawn_plan_to_workflow(
        analyze_text('use "flavored" as img', cube_root=cube_root),
        cube_root=cube_root,
    )
    loader = next(
        node for node in workflow.values() if node["class_type"] == "CheckpointLoaderSimple"
    )

    assert "ckpt_name" not in loader["inputs"]
    assert "" not in loader["inputs"].values()


def test_analyzer_resolves_local_flavor_from_explicit_root(tmp_path: Path) -> None:
    """Explicit local flavor roots provide local flavors to semantic analysis."""

    cube_root = tmp_path / "cubes"
    payload = write_cube(cube_root)
    local_root = tmp_path / "flavors"
    write_local_flavors(
        local_root,
        "flavored",
        compute_surface_signature(validate_cube_document(payload)),
        values={"ksampler.steps": 12},
    )

    plan = analyze_text(
        'use "flavored" with "Draft" as img',
        cube_root=cube_root,
        local_flavor_root=local_root,
    )

    assert plan["cubes"][0]["flavor_id"] == "draft"
    assert plan["cubes"][0]["flavor_scope"] == "local"
    assert any(
        entry["input"] == "steps" and entry["value"] == 12 and entry["metadata"]["kind"] == "flavor"
        for entry in plan["sets"]
    )


def test_analyzer_rejects_local_flavor_with_unknown_surface_control(
    tmp_path: Path,
) -> None:
    """Local flavor values must fail closed when they target unknown controls."""

    cube_root = tmp_path / "cubes"
    payload = write_cube(cube_root)
    local_root = tmp_path / "flavors"
    write_local_flavors(
        local_root,
        "flavored",
        compute_surface_signature(validate_cube_document(payload)),
        values={"missing.control": 12},
    )

    with pytest.raises(RuntimeError, match="unknown surface control"):
        analyze_text(
            'use "flavored" with "Draft" as img',
            cube_root=cube_root,
            local_flavor_root=local_root,
        )


def test_local_flavor_catalog_deep_copies_nested_values() -> None:
    """Catalog validation returns local flavor values detached from parsed state."""

    source_values: dict[str, Any] = {"ksampler.cfg": {"nested": ["original"]}}
    catalog = LocalFlavorCatalog(None)

    flavor = catalog._validate_flavor({"id": "draft", "name": "Draft", "values": source_values})
    nested_value = flavor["values"]["ksampler.cfg"]
    assert isinstance(nested_value, dict)
    nested_items = nested_value["nested"]
    assert isinstance(nested_items, list)
    nested_items.append("changed")

    assert source_values == {"ksampler.cfg": {"nested": ["original"]}}


def test_analyzer_rejects_unknown_flavor_with_available_names(tmp_path: Path) -> None:
    """Unknown flavor requests report authored and local candidates."""

    cube_root = tmp_path / "cubes"
    write_cube(cube_root)

    with pytest.raises(RuntimeError, match="Available: Default, Portrait"):
        analyze_text('use "flavored" with "Missing" as img', cube_root=cube_root)


def test_local_flavor_catalog_rejects_authored_collision_data(tmp_path: Path) -> None:
    """Local flavor entries may not collide with authored flavor identity."""

    cube_root = tmp_path / "cubes"
    payload = write_cube(cube_root)
    local_root = tmp_path / "flavors"
    write_local_flavors(
        local_root,
        "flavored",
        compute_surface_signature(validate_cube_document(payload)),
        flavor_id="portrait",
        name="Portrait",
        values={"ksampler.steps": 12},
    )

    with pytest.raises(RuntimeError, match="collides"):
        analyze_text(
            'use "flavored" with "Portrait" as img',
            cube_root=cube_root,
            local_flavor_root=local_root,
        )
