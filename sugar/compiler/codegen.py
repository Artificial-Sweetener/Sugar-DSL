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
"""Code generation for executable ComfyUI API prompts."""

from __future__ import annotations

from collections import OrderedDict
import logging
from pathlib import Path
from typing import Any

from ..catalog.artifacts import CubeArtifactResolver
from .graph import CubeGraph
from .input_materialization import materialize_node_inputs
from .ir import SpawnPlan
from .links import is_comfy_node_link
from .recipe import MaterializedRecipe, materialize_recipe
from ..shared.seed import SeedProvider, generate_comfy_seed

logger = logging.getLogger(__name__)


def spawn_plan_to_workflow(
    plan: SpawnPlan | dict[str, Any],
    cube_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> dict[str, Any]:
    """Convert a spawn plan into a ComfyUI workflow JSON.

    Args:
        plan: The spawn plan produced by the analyzer.
        cube_root: Optional cube root directory.
        seed_provider: Callable used to materialize schema-backed seed inputs.

    Returns:
        The merged ComfyUI workflow JSON.
    """

    return recipe_to_api_prompt(
        materialize_recipe(
            plan,
            cube_root,
            cube_artifact_resolver=cube_artifact_resolver,
        ),
        seed_provider=seed_provider,
    )


def recipe_to_api_prompt(
    recipe: MaterializedRecipe,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
) -> dict[str, Any]:
    """Lower a materialized Sugar recipe into an executable API prompt."""

    try:
        graphs = [recipe.cubes_by_alias[name].execution_graph for name in recipe.order]
        for graph in graphs:
            materialize_node_inputs(graph, seed_provider=seed_provider)
        merged, _name_to_id = merge_cubes(graphs)
    except (KeyError, RuntimeError, ValueError) as exc:
        logger.error(
            "Failed to merge materialized cubes.",
            extra={
                "operation": "recipe_to_api_prompt",
                "cube_root": str(recipe.cube_root),
                "order": list(recipe.order),
                "error": str(exc),
            },
        )
        raise RuntimeError(f"Failed to merge cubes: {exc}") from exc

    return merged


def merge_cubes(cubes: list[CubeGraph]) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge symbolic cubes into a numeric-ID workflow for ComfyUI."""

    merged: dict[str, Any] = {}
    name_to_id: dict[str, str] = {}
    id_counter = 0

    for cube in cubes:
        for sym_name in cube["nodes"]:
            node_id = str(id_counter)
            name_to_id[sym_name] = node_id
            id_counter += 1

    for sym_name, node in {
        sym: node for cube in cubes for sym, node in cube["nodes"].items()
    }.items():
        numeric_id = name_to_id[sym_name]
        new_inputs: dict[str, Any] = {}

        for key, val in node.get("inputs", {}).items():
            if is_comfy_node_link(val):
                target_sym, port = val
                if target_sym not in name_to_id:
                    raise ValueError(f"Unknown node reference: {target_sym}")
                new_inputs[key] = [name_to_id[target_sym], port]
            else:
                new_inputs[key] = val

        merged[numeric_id] = OrderedDict(
            [
                ("inputs", new_inputs),
                ("class_type", node.get("class_type")),
                *([("enabled", node["enabled"])] if "enabled" in node else []),
                (
                    "_meta",
                    node.get(
                        "_meta",
                        {"title": sym_name.split(".")[-1].replace("_", " ").title()},
                    ),
                ),
            ]
        )

    return merged, name_to_id
