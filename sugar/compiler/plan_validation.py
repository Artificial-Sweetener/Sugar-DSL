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
"""Semantic validation for completed Sugar spawn plans."""

from __future__ import annotations

import logging
from typing import Any, cast

from .ir import SpawnPlan

logger = logging.getLogger(__name__)


def validate_connected_recipe(plan: SpawnPlan | dict[str, Any]) -> None:
    """Reject multi-cube recipes whose declared aliases are not connected."""

    if not isinstance(plan, dict):
        logger.error(
            "Spawn plan has invalid type.",
            extra={
                "operation": "validate_connected_recipe",
                "plan_type": type(plan).__name__,
            },
        )
        raise RuntimeError("Spawn plan must be a dict.")
    typed_plan = cast(SpawnPlan, plan)
    if "schema_version" not in typed_plan:
        return
    aliases = [
        entry.get("alias", "")
        for entry in typed_plan.get("cubes", [])
        if isinstance(entry.get("alias"), str) and entry.get("alias")
    ]
    if len(aliases) <= 1:
        return

    connected_aliases: set[str] = set()
    for connection_entry in typed_plan.get("connections", []):
        _add_connection_endpoint(connected_aliases, connection_entry.get("from", {}))
        _add_connection_endpoint(connected_aliases, connection_entry.get("to", {}))
    for node_link_entry in typed_plan.get("node_links", []):
        _add_connection_endpoint(connected_aliases, node_link_entry.get("from", {}))
        _add_connection_endpoint(connected_aliases, node_link_entry.get("to", {}))

    orphan_aliases = [alias for alias in aliases if alias not in connected_aliases]
    if not orphan_aliases:
        return

    alias = orphan_aliases[0]
    logger.error(
        "Unconnected Sugar cube alias rejected.",
        extra={
            "operation": "validate_connected_recipe",
            "alias": alias,
            "orphan_aliases": orphan_aliases,
        },
    )
    raise RuntimeError(
        f"Cube alias '{alias}' is declared but not connected. "
        "Connect it to another cube or remove it from the script."
    )


def _add_connection_endpoint(aliases: set[str], endpoint: object) -> None:
    """Record one endpoint alias when a spawn-plan edge endpoint is valid."""

    if not isinstance(endpoint, dict):
        return
    alias = endpoint.get("alias")
    if isinstance(alias, str) and alias:
        aliases.add(alias)
