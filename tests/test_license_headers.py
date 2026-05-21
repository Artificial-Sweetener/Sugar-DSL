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
"""Test repository license header maintenance."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_TOOLS_MODULE = Path(__file__).resolve().parents[1] / "tools" / "add_license_headers.py"
_REPO_ROOT = _TOOLS_MODULE.parents[1]


def _load_module(path: Path) -> ModuleType:
    """Load the license header tool directly from its repository path."""

    spec = importlib.util.spec_from_file_location("add_license_headers_for_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_license_headers = cast(Any, _load_module(_TOOLS_MODULE))
_copyright_years = _license_headers._copyright_years
_header = _license_headers._header


def test_copyright_years_stays_single_year_during_start_year() -> None:
    """Keep the initial release year compact while it is still current."""

    assert _copyright_years(datetime(2026, 5, 21, tzinfo=UTC)) == "2026"


def test_copyright_years_expands_after_start_year() -> None:
    """Render a range when the tool is rerun in a later year."""

    assert _copyright_years(datetime(2030, 1, 1, tzinfo=UTC)) == "2026 - 2030"


def test_header_uses_project_tagline_and_gpl_v3_or_later() -> None:
    """Keep generated source headers aligned with project licensing."""

    header = _header(path=Path("sugar/__init__.py"))

    assert header.startswith("#    Compose human-readable ComfyUI workflows with SugarCubes")
    assert "Copyright (C) 2026  Artificial Sweetener and contributors" in header
    assert "GNU General Public License" in header
    assert "GNU Affero General Public License" not in header
    assert "either version 3 of the License, or" in header
    assert "(at your option) any later version." in header


def test_project_license_metadata_uses_gpl_v3_or_later() -> None:
    """Keep published package metadata aligned with source file headers."""

    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    license_text = (_REPO_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "AGPL" not in pyproject
    assert "GPL-3.0-only" not in pyproject
    assert 'license = "GPL-3.0-or-later"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
