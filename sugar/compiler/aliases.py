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
"""Resolve Sugar cube aliases without losing authored spelling."""

from __future__ import annotations


class AliasRegistry:
    """Own case-insensitive cube-alias lookup for compiler semantics."""

    def __init__(self) -> None:
        """Create an empty alias registry."""

        self._canonical_by_folded: dict[str, str] = {}

    def register(self, alias: str, *, line: int) -> str:
        """Register one canonical alias or fail on case-insensitive collision."""

        folded = alias.casefold()
        existing = self._canonical_by_folded.get(folded)
        if existing is not None:
            if existing == alias:
                raise RuntimeError(f"Line {line}: Alias '{alias}' already used.")
            raise RuntimeError(
                f"Line {line}: Alias '{alias}' conflicts with existing alias "
                f"'{existing}' by case-insensitive match."
            )
        self._canonical_by_folded[folded] = alias
        return alias

    def resolve(self, alias: str, *, line: int, context: str) -> str:
        """Return the canonical alias matching one requested alias."""

        canonical = self._canonical_by_folded.get(alias.casefold())
        if canonical is not None:
            return canonical
        suffix = self._available_alias_suffix()
        raise RuntimeError(f"Line {line}: cube '{alias}' not defined for {context}.{suffix}")

    def available_aliases(self) -> tuple[str, ...]:
        """Return canonical aliases in deterministic display order."""

        return tuple(sorted(self._canonical_by_folded.values()))

    def _available_alias_suffix(self) -> str:
        """Format available aliases for unresolved-reference diagnostics."""

        available = ", ".join(self.available_aliases())
        if not available:
            return ""
        return f" Available aliases: {available}"
