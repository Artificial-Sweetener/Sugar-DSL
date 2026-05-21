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
"""Shared random seed generation utilities."""

from __future__ import annotations

from collections.abc import Callable
import logging
import random

logger = logging.getLogger(__name__)

SeedProvider = Callable[[], int]


def generate_comfy_seed() -> int:
    """Generate a seed matching ComfyUI's expected format."""

    try:
        return random.randint(10**13, 10**14 - 1)
    except (OverflowError, ValueError) as exc:
        logger.error("Failed to generate seed.", extra={"error": str(exc)})
        raise RuntimeError(f"Failed to generate ComfyUI seed: {exc}") from exc
