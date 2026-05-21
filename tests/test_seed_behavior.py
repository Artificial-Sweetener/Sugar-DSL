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
"""Seed generation and random DSL behavior tests."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_workflow, build_workflow_from_text
from sugar.compiler.analyzer import analyze_text
from sugar.runtime.modifiers import patch_random_seeds, patch_save_paths
from sugar.shared.seed import generate_comfy_seed


def test_generate_comfy_seed_raises_on_generator_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed generation failures fail closed instead of returning `None`."""

    def _raise_value_error(_start: int, _end: int) -> int:
        """Raise the generator failure under test."""

        raise ValueError("bad range")

    monkeypatch.setattr(random, "randint", _raise_value_error)

    with pytest.raises(RuntimeError, match="Failed to generate ComfyUI seed"):
        generate_comfy_seed()


def test_analyzer_random_expression_uses_seed_provider(tmp_path: Path) -> None:
    """DSL `random` expressions resolve through the configured seed provider."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "randomizer.cube",
        {
            "cube_id": "randomizer",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"seed": 0}}},
        },
    )

    plan = analyze_text(
        """
        use "randomizer" as r
        set r.sampler.seed = random
        """,
        cube_root=cube_root,
        seed_provider=lambda: 12345,
    )

    explicit_seed_sets = [
        entry
        for entry in plan["sets"]
        if entry["metadata"].get("kind") == "explicit" and entry["input"] == "seed"
    ]
    assert explicit_seed_sets[0]["value"] == 12345


def test_build_workflow_schema_seed_materialization_uses_seed_provider(
    tmp_path: Path,
) -> None:
    """Schema-backed missing seed materialization uses the configured provider."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "sampler.cube",
        {
            "cube_id": "sampler",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {}}},
            "outputs": {"output.image": "sampler"},
            "definitions": {
                "KSampler": {
                    "input": {
                        "required": {
                            "seed": [
                                "INT",
                                {
                                    "default": 0,
                                    "min": 0,
                                    "max": 0xFFFFFFFFFFFFFFFF,
                                },
                            ]
                        }
                    }
                }
            },
        },
    )
    write_cube(
        cube_root / "sink.cube",
        {
            "cube_id": "sink",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"value": None}}},
            "inputs": {"input.image": [["sink", "value"]]},
        },
    )

    workflow = build_workflow_from_text(
        """
        use "sampler" as s
        use "sink" as out
        connect s.output.image to out.input.image
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        seed_provider=lambda: 67890,
    )

    sampler = next(node for node in workflow.values() if node["class_type"] == "KSampler")
    assert sampler["inputs"]["seed"] == 67890


def test_build_workflow_reads_script_files_as_utf8(tmp_path: Path) -> None:
    """Script file builds read Sugar DSL files with explicit UTF-8 encoding."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "prompt.cube",
        {
            "cube_id": "prompt",
            "version": "1.0.0",
            "nodes": {
                "positive": {
                    "class_type": "PromptNode",
                    "inputs": {"text": ""},
                }
            },
            "outputs": {"output.image": "positive"},
        },
    )
    write_cube(
        cube_root / "sink.cube",
        {
            "cube_id": "sink",
            "version": "1.0.0",
            "nodes": {"sink": {"class_type": "Sink", "inputs": {"value": None}}},
            "inputs": {"input.image": [["sink", "value"]]},
        },
    )
    script_path = tmp_path / "recipe.sugar"
    script_path.write_text(
        (
            'use "prompt" as p\n'
            'use "sink" as out\n'
            "connect p.output.image to out.input.image\n"
            'set p.positive.text = "caf\u00e9"\n'
        ),
        encoding="utf-8",
    )

    workflow = build_workflow(
        script_path,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
    )

    prompt_node = next(node for node in workflow.values() if node["class_type"] == "PromptNode")
    assert prompt_node["inputs"]["text"] == "caf\u00e9"


def test_patch_save_paths_accepts_missing_output_directory(tmp_path: Path) -> None:
    """Save path patching injects resolved paths without creating directories."""

    output_dir = tmp_path / "missing-output"
    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "class_type": "FL_SaveImages",
            "inputs": {"filename_prefix": "Sugar"},
        }
    }

    patch_save_paths(workflow, output_dir)

    assert workflow["1"]["inputs"]["base_directory"] == str(output_dir.resolve())
    assert not output_dir.exists()


def test_patch_random_seeds_raises_on_seed_provider_failure() -> None:
    """Runtime seed patching reports seed provider failures with node context."""

    workflow = {"1": {"class_type": "CustomSampler", "inputs": {"seed": None}}}

    def _raise_seed_error() -> int:
        """Raise the runtime seed provider failure under test."""

        raise RuntimeError("no entropy")

    with pytest.raises(RuntimeError, match="Failed to generate seed for node '1'"):
        patch_random_seeds(workflow, seed_provider=_raise_seed_error)
