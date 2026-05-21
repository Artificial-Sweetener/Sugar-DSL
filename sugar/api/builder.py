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
"""Public workflow build entry points for Sugar DSL scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from ..catalog.artifacts import CubeArtifactResolver
from ..compiler.analyzer import analyze_script
from ..compiler.codegen import recipe_to_api_prompt
from ..compiler.recipe import materialize_recipe
from ..compiler.ui_workflow import recipe_to_ui_workflow
from ..dsl.parser import parse_script
from ..runtime.modifiers import apply_hooks, patch_random_seeds, patch_save_paths
from ..runtime.normalization import sanitize_inputs
from ..shared.seed import SeedProvider, generate_comfy_seed

Workflow = dict[str, Any]


class ComfyArtifacts(TypedDict):
    """Compiled Sugar artifacts for ComfyUI execution and metadata."""

    prompt: dict[str, Any]
    workflow: dict[str, Any]


def build_workflow(
    script_path: Path,
    output_dir: Path,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> Workflow:
    """Build a ComfyUI workflow from a Sugar script file."""

    try:
        text = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read script file '{script_path}': {exc}") from exc

    return _build_workflow_from_script_text(
        text,
        output_dir=output_dir,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )


def build_workflow_from_text(
    script_text: str,
    output_dir: Path,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> Workflow:
    """Build a ComfyUI workflow from Sugar DSL text."""

    return _build_workflow_from_script_text(
        script_text,
        output_dir=output_dir,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )


def build_comfy_artifacts(
    script_path: Path,
    output_dir: Path,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> ComfyArtifacts:
    """Build executable and placed ComfyUI artifacts from a Sugar script file."""

    try:
        text = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read script file '{script_path}': {exc}") from exc

    return build_comfy_artifacts_from_text(
        text,
        output_dir=output_dir,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )


def build_comfy_artifacts_from_text(
    script_text: str,
    output_dir: Path,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> ComfyArtifacts:
    """Build executable and placed ComfyUI artifacts from Sugar DSL text."""

    artifacts = _compile_comfy_artifacts_from_script_text(
        script_text,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )
    _prepare_runtime_workflow(
        artifacts["prompt"],
        output_dir=output_dir,
        seed_provider=seed_provider,
    )
    return artifacts


def _build_workflow_from_script_text(
    script_text: str,
    *,
    output_dir: Path,
    cube_root: Path | None,
    local_flavor_root: Path | None,
    seed_provider: SeedProvider,
    cube_artifact_resolver: CubeArtifactResolver | None,
) -> Workflow:
    """Run the API orchestration pipeline for one script payload."""

    workflow = _compile_workflow_from_script_text(
        script_text,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )
    _prepare_runtime_workflow(
        workflow,
        output_dir=output_dir,
        seed_provider=seed_provider,
    )
    return workflow


def _compile_workflow_from_script_text(
    script_text: str,
    *,
    cube_root: Path | None,
    local_flavor_root: Path | None,
    seed_provider: SeedProvider,
    cube_artifact_resolver: CubeArtifactResolver | None,
) -> Workflow:
    """Compile Sugar DSL text into workflow JSON before runtime patching."""

    return _compile_comfy_artifacts_from_script_text(
        script_text,
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )["prompt"]


def _compile_comfy_artifacts_from_script_text(
    script_text: str,
    *,
    cube_root: Path | None,
    local_flavor_root: Path | None,
    seed_provider: SeedProvider,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> ComfyArtifacts:
    """Compile Sugar DSL text into executable and UI workflow artifacts."""

    script = parse_script(script_text)
    plan = analyze_script(
        script,
        cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )
    recipe = materialize_recipe(
        plan,
        cube_root,
        cube_artifact_resolver=cube_artifact_resolver,
    )
    return {
        "prompt": recipe_to_api_prompt(recipe, seed_provider=seed_provider),
        "workflow": recipe_to_ui_workflow(recipe),
    }


def _prepare_runtime_workflow(
    workflow: Workflow,
    *,
    output_dir: Path,
    seed_provider: SeedProvider,
) -> None:
    """Apply runtime-only workflow mutations before ComfyUI execution."""

    apply_hooks(
        workflow,
        [
            lambda active_workflow: patch_save_paths(active_workflow, output_dir),
            lambda active_workflow: patch_random_seeds(
                active_workflow, seed_provider=seed_provider
            ),
        ],
    )
    sanitize_inputs(workflow)
