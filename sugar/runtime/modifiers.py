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
"""Runtime workflow patchers for filesystem paths and generated seeds."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..shared.seed import SeedProvider, generate_comfy_seed

Workflow = dict[str, Any]
WorkflowHook = Callable[[Workflow], None]

logger = logging.getLogger(__name__)


def apply_hooks(workflow: Workflow, hooks: Iterable[WorkflowHook]) -> None:
    """Apply runtime workflow patch hooks in order."""

    for index, hook in enumerate(hooks):
        try:
            hook(workflow)
        except Exception as exc:
            hook_name = getattr(hook, "__name__", f"<unnamed_hook_{index}>")
            logger.error(
                "Workflow hook failed.",
                extra={"hook_name": hook_name, "error": str(exc)},
            )
            raise RuntimeError(f"Workflow hook '{hook_name}' failed: {exc}") from exc


def patch_save_paths(workflow: Workflow, output_dir: str | os.PathLike[str]) -> None:
    """Inject output directory paths into all `FL_SaveImages` nodes."""

    try:
        resolved_path = str(Path(output_dir).resolve())
    except OSError as exc:
        logger.error(
            "Failed to resolve output directory path.",
            extra={"output_dir": str(output_dir), "error": str(exc)},
        )
        raise RuntimeError(
            f"Failed to resolve output directory path '{output_dir}': {exc}"
        ) from exc

    for node_id, node in workflow.items():
        if not isinstance(node, dict) or node.get("class_type") != "FL_SaveImages":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise RuntimeError(f"Node '{node_id}' has invalid or missing inputs.")
        inputs["base_directory"] = resolved_path


def patch_random_seeds(
    workflow: Workflow, *, seed_provider: SeedProvider = generate_comfy_seed
) -> None:
    """Fill present null seed inputs after compile-time schema materialization."""

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise RuntimeError(f"Node '{node_id}' has invalid or missing inputs.")
        if "seed" in inputs and inputs["seed"] is None:
            try:
                inputs["seed"] = seed_provider()
            except Exception as exc:
                logger.error(
                    "Failed to generate seed.",
                    extra={"node_id": node_id, "error": str(exc)},
                )
                raise RuntimeError(f"Failed to generate seed for node '{node_id}': {exc}") from exc
