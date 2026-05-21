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
"""Golden workflow characterization tests for Sugar compilation."""

from pathlib import Path
from unittest import mock

import pytest

from tests.fixtures.cubes import assert_json_snapshot, write_cube
from sugar.api.builder import build_workflow_from_text


# --- Fixtures ---


@pytest.fixture
def cubes_catalog(tmp_path: Path) -> Path:
    """
    Sets up a realistic 'cubes' directory with several components.
    """
    cube_root = tmp_path / "cubes"
    cube_root.mkdir()

    # 1. A basic processor cube
    write_cube(
        cube_root / "processor.cube",
        {
            "cube_id": "processor",
            "version": "1.0.0",
            "nodes": {
                "loader": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "default.ckpt"},
                },
                "sampler": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 0,
                        "steps": 20,
                        "cfg": 8.0,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                        "latents": ["loader", 0],
                        "model": ["loader", 0],
                    },
                },
            },
            "inputs": {
                "input.model": [["loader", "ckpt_name"]],
                "input.steps": [["sampler", "steps"]],
                "input.latent": [["sampler", "latents"]],
            },
            "outputs": {"output.image": "sampler"},
        },
    )

    # 2. A simple input source
    write_cube(
        cube_root / "source.cube",
        {
            "cube_id": "source",
            "version": "1.0.0",
            "nodes": {
                "empty_latent": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": 512, "height": 512, "batch_size": 1},
                }
            },
            "outputs": {"output.latent": "empty_latent"},
        },
    )

    # 3. An output sink
    write_cube(
        cube_root / "saver.cube",
        {
            "cube_id": "saver",
            "version": "1.0.0",
            "nodes": {
                "save": {
                    "class_type": "FL_SaveImages",
                    "inputs": {"filename_prefix": "Sugar", "images": None},
                }
            },
            "inputs": {"input.image": [["save", "images"]]},
        },
    )

    return cube_root


# --- Golden Master Tests ---


@mock.patch("sugar.runtime.modifiers.generate_comfy_seed", return_value=1234567890)
def test_golden_master_basic_flow(
    _mock_seed: mock.MagicMock,
    cubes_catalog: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """
    Scenario 1: Baseline Pipeline
    - Basic 'use'
    - 'connect' (output->input)
    - 'set' (explicit value)
    """
    script = """
    use "source" as src
    use "processor" as proc
    use "saver" as out
    
    connect src.output.latent to proc.input.latent
    connect proc.output.image to out.input.image
    
    set proc.sampler.steps = 30
    set proc.loader.ckpt_name = "model.safetensors"
    set out.save.filename_prefix = "GoldenTest"
    """

    output_dir = tmp_path / "output"
    workflow = build_workflow_from_text(script, output_dir=output_dir, cube_root=cubes_catalog)

    # We strip the absolute path from the result to keep the snapshot portable
    # because 'patch_save_paths' injects absolute paths.
    for node in workflow.values():
        if node.get("class_type") == "FL_SaveImages":
            if "base_directory" in node["inputs"]:
                node["inputs"]["base_directory"] = "/MOCKED/PATH/output"

    assert_json_snapshot(request, workflow)


@mock.patch("sugar.runtime.modifiers.generate_comfy_seed", return_value=1234567890)
def test_golden_master_advanced_logic(
    _mock_seed: mock.MagicMock,
    cubes_catalog: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """
    Scenario 2: Advanced Logic
    - Loops (repeat)
    - Aliasing (as)
    - Variables (let)
    - Wildcards (set *)
    - Disabling (disable) - REMOVED due to cross-cube limitation
    """
    script = """
    use "source" as src
    
    # Repeat creates proc1, proc2
    use "processor" as proc repeat 2

    # Variable usage
    let base_steps = 25
    
    # Connect source to both processors
    connect src.output.latent to proc1.input.latent
    connect src.output.latent to proc2.input.latent

    # Wildcard set: Any KSampler node with 'cfg' gets 7.5
    set *.KSampler.cfg = 7.5
    set *.CheckpointLoaderSimple.ckpt_name = "model.safetensors"

    # Explicit loop set using variable
    set proc1.sampler.steps = base_steps
    set proc2.sampler.steps = 50
    
    use "saver" as out
    connect proc1.output.image to out.input.image
    """

    output_dir = tmp_path / "output"
    workflow = build_workflow_from_text(script, output_dir=output_dir, cube_root=cubes_catalog)

    # Sanitization for snapshot
    for node in workflow.values():
        if node.get("class_type") == "FL_SaveImages":
            if "base_directory" in node["inputs"]:
                node["inputs"]["base_directory"] = "/MOCKED/PATH/output"

    assert_json_snapshot(request, workflow)


@mock.patch("sugar.runtime.modifiers.generate_comfy_seed", return_value=1234567890)
def test_golden_master_data_types(
    _mock_seed: mock.MagicMock,
    cubes_catalog: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """
    Scenario 3: Data Types
    - Strings, Triple-Quoted Strings
    - Booleans, Nulls
    """
    # Create a dummy cube that accepts various types
    write_cube(
        cubes_catalog / "types.cube",
        {
            "cube_id": "types",
            "version": "1.0.0",
            "nodes": {
                "tester": {
                    "class_type": "DataTypeTester",
                    "inputs": {
                        "str_val": "",
                        "text_val": "",
                        "bool_val": False,
                        "null_val": "something",
                        "int_val": 0,
                    },
                }
            },
            "outputs": {"output.image": "tester"},
        },
    )

    script = '''
    use "types" as t
    use "saver" as out
    connect t.output.image to out.input.image
    
    set t.tester.str_val = "simple string"
    set t.tester.bool_val = true
    set t.tester.null_val = null
    # Parser should convert float 10.0 to int 10 if it's in the INT_FIELDS list
    # but 'int_val' isn't in that hardcoded list in builder.py. 
    # Let's test standard JSON number parsing:
    set t.tester.int_val = 42
    
    set t.tester.text_val = """
    This is a
    multi-line
    string.
    """
    '''

    output_dir = tmp_path / "output"
    workflow = build_workflow_from_text(script, output_dir=output_dir, cube_root=cubes_catalog)
    for node in workflow.values():
        if node.get("class_type") == "FL_SaveImages":
            node["inputs"]["base_directory"] = "/MOCKED/PATH/output"
    assert_json_snapshot(request, workflow)


@mock.patch("sugar.runtime.modifiers.generate_comfy_seed", return_value=1234567890)
def test_golden_master_disable_features(
    _mock_seed: mock.MagicMock,
    cubes_catalog: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """
    Scenario 4: Disable Feature
    Verifies that 'disable' correctly removes a node and rewires the graph
    assuming input names match (current implementation limitation).
    """
    # Create a linear chain cube: A -> B -> C
    write_cube(
        cubes_catalog / "chain.cube",
        {
            "cube_id": "chain",
            "version": "1.0.0",
            "nodes": {
                "nodeA": {"class_type": "NodeA", "inputs": {}},
                "nodeB": {"class_type": "NodeB", "inputs": {"data": ["nodeA", 0]}},
                "nodeC": {"class_type": "NodeC", "inputs": {"data": ["nodeB", 0]}},
            },
            "outputs": {"output.image": "nodeC"},
        },
    )

    script = """
    use "chain" as c
    use "saver" as out
    connect c.output.image to out.input.image
    disable c.nodeB
    """

    # Expected result: nodeB is gone, nodeC.data points to nodeA

    output_dir = tmp_path / "output"
    workflow = build_workflow_from_text(script, output_dir=output_dir, cube_root=cubes_catalog)
    for node in workflow.values():
        if node.get("class_type") == "FL_SaveImages":
            node["inputs"]["base_directory"] = "/MOCKED/PATH/output"
    assert_json_snapshot(request, workflow)


def test_golden_master_random_keyword(
    cubes_catalog: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """
    Scenario 5: Random Keyword
    Verifies 'set ... = random' invokes the seed generator.
    """
    write_cube(
        cubes_catalog / "randomizer.cube",
        {
            "cube_id": "randomizer",
            "version": "1.0.0",
            "nodes": {"sampler": {"class_type": "KSampler", "inputs": {"seed": 0}}},
            "outputs": {"output.image": "sampler"},
        },
    )

    script = """
    use "randomizer" as r
    use "saver" as out
    connect r.output.image to out.input.image
    set r.sampler.seed = random
    """

    output_dir = tmp_path / "output"
    workflow = build_workflow_from_text(
        script,
        output_dir=output_dir,
        cube_root=cubes_catalog,
        seed_provider=lambda: 999999,
    )
    for node in workflow.values():
        if node.get("class_type") == "FL_SaveImages":
            node["inputs"]["base_directory"] = "/MOCKED/PATH/output"

    # We expect the seed to be the mocked value (999999)
    # The snapshot will confirm this.
    assert_json_snapshot(request, workflow)


def test_golden_master_error_handling(cubes_catalog: Path, tmp_path: Path) -> None:
    """
    Scenario 6: Error Handling
    Ensures invalid scripts raise RuntimeError (or specific exceptions).
    """
    output_dir = tmp_path / "output"

    # Case 1: Use unknown cube
    script_unknown = 'use "ghost_cube" as g'
    with pytest.raises(RuntimeError) as excinfo:
        build_workflow_from_text(script_unknown, output_dir=output_dir, cube_root=cubes_catalog)
    assert "Cube 'ghost_cube' not found" in str(excinfo.value)

    # Case 2: Connect mismatch
    script_connect = """
    use "processor" as p
    connect p.output.image to p.input.missing
    """
    with pytest.raises(RuntimeError) as excinfo:
        build_workflow_from_text(script_connect, output_dir=output_dir, cube_root=cubes_catalog)
    assert "Could not resolve input" in str(excinfo.value)

    # Case 3: Set unknown node
    script_set = """
    use "processor" as p
    set p.imaginary.val = 1
    """
    with pytest.raises(RuntimeError) as excinfo:
        build_workflow_from_text(script_set, output_dir=output_dir, cube_root=cubes_catalog)
    assert "Node 'imaginary' not found" in str(excinfo.value)
