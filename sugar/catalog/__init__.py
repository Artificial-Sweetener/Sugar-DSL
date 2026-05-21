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
"""Catalog package for cube assets."""

from .models import CubeDocument, CubeNodeSpec, validate_cube_document
from .local_flavors import LocalFlavorCatalog
from .registry import CubeRegistry

__all__ = [
    "CubeDocument",
    "CubeNodeSpec",
    "CubeRegistry",
    "LocalFlavorCatalog",
    "validate_cube_document",
]
