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
"""Materialized Sugar recipe model shared by output generators."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Mapping, cast

from ..catalog.artifacts import CubeArtifactResolver, FilesystemCubeArtifactResolver
from ..catalog.registry import CubeRegistry
from .graph import CubeGraph, CubeGraphByAlias
from .graph_ops import (
    apply_plan_connections,
    apply_plan_disabled,
    apply_plan_node_links,
    apply_plan_sets,
    apply_plan_ui_disabled_modes,
    apply_plan_ui_enabled_modes,
    apply_plan_ui_inherited_provider_values,
)
from .ir import ConnectionEntry, NodeLinkEntry, SpawnPlan
from .materializer import CubeMaterializer
from .plan_validation import validate_connected_recipe
from .subgraph_expand import expand_cube_subgraph_wrappers

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaterializedCubeInstance:
    """Represent one resolved cube instance in a Sugar recipe."""

    alias: str
    cube_id: str
    version_pin: str | None
    requested_version: str | None
    resolved_version: str
    flavor_name: str | None
    flavor_id: str | None
    flavor_scope: str | None
    ui_graph: CubeGraph
    execution_graph: CubeGraph


@dataclass(frozen=True)
class MaterializedRecipe:
    """Hold a resolved Sugar recipe before output-specific lowering."""

    cube_root: Path
    order: tuple[str, ...]
    cubes_by_alias: Mapping[str, MaterializedCubeInstance]
    connections: tuple[ConnectionEntry, ...]
    node_links: tuple[NodeLinkEntry, ...]
    warnings: tuple[str, ...]
    plan: SpawnPlan


def materialize_recipe(
    plan: SpawnPlan | dict[str, Any],
    cube_root: Path | None = None,
    *,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> MaterializedRecipe:
    """Resolve a spawn plan into materialized cube instances."""

    if not isinstance(plan, dict):
        logger.error(
            "Spawn plan has invalid type.",
            extra={
                "operation": "materialize_recipe",
                "plan_type": type(plan).__name__,
            },
        )
        raise RuntimeError("Spawn plan must be a dict.")
    typed_plan = cast(SpawnPlan, plan)
    validate_connected_recipe(typed_plan)

    root_value = typed_plan.get("cube_root") or cube_root or (Path.cwd() / "cubes")
    resolved_cube_root = Path(root_value).resolve()

    artifact_resolver = cube_artifact_resolver or FilesystemCubeArtifactResolver(
        CubeRegistry(resolved_cube_root)
    )
    materializer = CubeMaterializer(artifact_resolver)
    execution_cubes: CubeGraphByAlias = {}
    ui_cubes: CubeGraphByAlias = {}
    cube_instances: dict[str, MaterializedCubeInstance] = {}
    cube_ids_by_alias: dict[str, str] = {}
    order: list[str] = []
    for entry in typed_plan.get("cubes", []):
        cube_id = entry.get("cube_id")
        alias = entry.get("alias")
        version_pin = entry.get("version_pin")
        if not cube_id or not alias:
            logger.error(
                "Spawn plan cube entry missing identity.",
                extra={
                    "operation": "materialize_recipe",
                    "cube_id": cube_id,
                    "alias": alias,
                },
            )
            raise RuntimeError("Spawn plan cube entry missing cube_id or alias.")
        try:
            instance = materializer.materialize_default_resolved(
                cube_id=cube_id,
                alias=alias,
                version_pin=version_pin,
            )
        except RuntimeError as exc:
            logger.error(
                "Cube materialization failed during recipe materialization.",
                extra={
                    "operation": "materialize_recipe",
                    "cube_root": str(resolved_cube_root),
                    "cube_id": cube_id,
                    "alias": alias,
                    "version_pin": version_pin,
                    "error": str(exc),
                },
            )
            raise
        execution_cubes[alias] = instance.cube
        ui_cubes[alias] = copy.deepcopy(instance.cube)
        cube_ids_by_alias[alias] = cube_id
        cube_instances[alias] = MaterializedCubeInstance(
            alias=alias,
            cube_id=cube_id,
            version_pin=version_pin,
            requested_version=instance.requested_version,
            resolved_version=instance.resolved_version,
            flavor_name=entry.get("flavor"),
            flavor_id=entry.get("flavor_id"),
            flavor_scope=entry.get("flavor_scope"),
            ui_graph=ui_cubes[alias],
            execution_graph=instance.cube,
        )
        order.append(alias)

    if typed_plan.get("order"):
        order = list(typed_plan["order"])

    apply_plan_connections(execution_cubes, typed_plan)
    for cubes in (execution_cubes, ui_cubes):
        apply_plan_sets(cubes, typed_plan, kind="flavor")
        apply_plan_sets(cubes, typed_plan, kind="explicit")
    apply_plan_disabled(execution_cubes, typed_plan)
    apply_plan_sets(execution_cubes, typed_plan, kind="inferred")
    for cubes in (execution_cubes, ui_cubes):
        apply_plan_sets(cubes, typed_plan, kind="wildcard")
        apply_plan_node_links(cubes, typed_plan)
    apply_plan_ui_inherited_provider_values(ui_cubes, typed_plan)
    apply_plan_ui_disabled_modes(ui_cubes, typed_plan)
    apply_plan_ui_enabled_modes(ui_cubes, typed_plan)

    for alias, cube in execution_cubes.items():
        expand_cube_subgraph_wrappers(
            cube,
            cube_alias=alias,
            cube_id=cube_ids_by_alias.get(alias, alias),
            consumer_cubes=(
                candidate
                for candidate_alias, candidate in execution_cubes.items()
                if candidate_alias != alias
            ),
        )

    return MaterializedRecipe(
        cube_root=resolved_cube_root,
        order=tuple(order),
        cubes_by_alias=cube_instances,
        connections=tuple(typed_plan.get("connections", [])),
        node_links=tuple(typed_plan.get("node_links", [])),
        warnings=tuple(str(warning) for warning in typed_plan.get("warnings", [])),
        plan=typed_plan,
    )
