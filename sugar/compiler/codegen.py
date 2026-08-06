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
from collections.abc import Mapping
import logging
from pathlib import Path
from typing import Any

from ..catalog.artifacts import CubeArtifactResolver
from .errors import SugarCompilerError
from .graph import CubeGraph
from .input_materialization import materialize_node_inputs
from .ir import SpawnPlan
from .links import is_comfy_node_link
from .literal_values import (
    comfy_literal_list_value,
    is_authored_literal_list,
    wrap_unlinked_comfy_list,
)
from .live_definitions import LiveNodeDefinitionProvider, LiveNodeInputDefinition
from .recipe import MaterializedRecipe, materialize_recipe
from .resource_optimization import optimize_execution_resources
from ..shared.seed import SeedProvider, generate_comfy_seed

logger = logging.getLogger(__name__)


def spawn_plan_to_workflow(
    plan: SpawnPlan | dict[str, Any],
    cube_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
    live_node_definition_provider: LiveNodeDefinitionProvider | None = None,
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
            live_node_definition_provider=live_node_definition_provider,
        ),
        seed_provider=seed_provider,
        live_node_definition_provider=live_node_definition_provider,
    )


def recipe_to_api_prompt(
    recipe: MaterializedRecipe,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    live_node_definition_provider: LiveNodeDefinitionProvider | None = None,
) -> dict[str, Any]:
    """Lower a materialized Sugar recipe into an executable API prompt."""

    try:
        instances = [recipe.cubes_by_alias[name] for name in recipe.order]
        graphs = [instance.execution_graph for instance in instances]
        for instance in instances:
            materialize_node_inputs(
                instance.execution_graph,
                seed_provider=seed_provider,
                live_node_definition_provider=live_node_definition_provider,
                cube_alias=instance.alias,
                cube_id=instance.cube_id,
            )
        optimize_execution_resources(
            graphs,
            order=recipe.order,
            node_links=recipe.node_links,
        )
        for graph in graphs:
            prune_stale_inputs(
                graph,
                live_node_definition_provider=live_node_definition_provider,
            )
        merged, _name_to_id = merge_cubes(graphs)
    except SugarCompilerError:
        raise
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


def prune_stale_inputs(
    cube: CubeGraph,
    *,
    live_node_definition_provider: LiveNodeDefinitionProvider | None,
) -> None:
    """Remove inputs that the current live Comfy definition no longer declares."""

    if live_node_definition_provider is None:
        return
    nodes = cube.get("nodes")
    if not isinstance(nodes, dict):
        raise RuntimeError("Materialized cube graph is missing a nodes mapping.")
    for node_key, node in nodes.items():
        if not isinstance(node_key, str):
            raise RuntimeError("Materialized cube graph has a non-string node key.")
        if not isinstance(node, dict):
            raise RuntimeError(f"Materialized node '{node_key}' must be an object.")
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue
        live_definition = live_node_definition_provider.definition_for(class_type)
        if live_definition is None:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name in list(inputs):
            if not isinstance(input_name, str):
                del inputs[input_name]
                continue
            prompt_input_name = _live_prompt_input_name(input_name, live_definition.inputs)
            if prompt_input_name is None:
                del inputs[input_name]
                continue
            if prompt_input_name != input_name:
                _rename_node_input(inputs, input_name, prompt_input_name)


def _live_prompt_input_name(
    input_name: str,
    live_inputs: Mapping[str, LiveNodeInputDefinition],
) -> str | None:
    """Return the live prompt input name for a serialized cube input."""

    if input_name in live_inputs:
        return input_name
    if "." not in input_name:
        return None
    group_name, concrete_name = input_name.rsplit(".", maxsplit=1)
    live_group = live_inputs.get(group_name)
    if live_group is not None and _is_autogrow_input(live_group):
        concrete_names = _autogrow_concrete_input_names(live_group)
        if not concrete_names or concrete_name in concrete_names:
            return input_name
        return None
    if concrete_name in live_inputs:
        return concrete_name
    return None


def _rename_node_input(
    inputs: dict[object, object],
    old_name: str,
    new_name: str,
) -> None:
    """Rename one node input while preserving explicit concrete values."""

    if new_name not in inputs:
        inputs[new_name] = inputs[old_name]
    del inputs[old_name]


def _is_autogrow_input(live_input: LiveNodeInputDefinition) -> bool:
    """Return whether a live input represents a Comfy autogrow group."""

    return _is_autogrow_type(live_input.value_type)


def _autogrow_concrete_input_names(live_input: LiveNodeInputDefinition) -> tuple[str, ...]:
    """Return concrete prompt socket names declared by one autogrow input."""

    direct_names = _string_tuple(live_input.raw.get("names"))
    if direct_names:
        return direct_names
    template = live_input.raw.get("template")
    if isinstance(template, Mapping):
        return _string_tuple(template.get("names"))
    return ()


def _string_tuple(value: object) -> tuple[str, ...]:
    """Return string items from a list-like metadata value."""

    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _is_autogrow_type(value_type: str | None) -> bool:
    """Return whether an input type name is a Comfy autogrow group type."""

    return value_type is not None and value_type.upper().startswith("COMFY_AUTOGROW")


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
            if is_authored_literal_list(val):
                new_inputs[key] = comfy_literal_list_value(val)
            elif is_comfy_node_link(val):
                target_sym, port = val
                if target_sym not in name_to_id:
                    raise ValueError(f"Unknown node reference: {target_sym}")
                new_inputs[key] = [name_to_id[target_sym], port]
            elif isinstance(val, list):
                new_inputs[key] = wrap_unlinked_comfy_list(val)
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
