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
"""Abstract syntax tree nodes for the Sugar DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class RangeExpr:
    """Represents an inclusive numeric range like [1-3]."""

    start: int
    end: int


@dataclass(frozen=True)
class PathRef:
    """Represents a dotted path reference in the DSL."""

    parts: list[str]
    range_expr: RangeExpr | None = None


@dataclass(frozen=True)
class WildcardRef:
    """Represents a wildcard set target (cube.*.input or *.*.input)."""

    cube: str
    cls: str
    input_key: str


@dataclass(frozen=True)
class Expr:
    """Base type for all expressions."""


@dataclass(frozen=True)
class LiteralExpr(Expr):
    """Represents a literal value."""

    value: object
    raw: str


@dataclass(frozen=True)
class NameExpr(Expr):
    """Represents a named variable reference."""

    name: str


@dataclass(frozen=True)
class RandomExpr(Expr):
    """Represents the 'random' keyword."""


@dataclass(frozen=True)
class DottedRefExpr(Expr):
    """Represents a dotted reference expression like a.b.c."""

    ref: PathRef


@dataclass(frozen=True)
class UnaryExpr(Expr):
    """Represents a unary expression like -x."""

    op: str
    operand: Expr


@dataclass(frozen=True)
class BinaryExpr(Expr):
    """Represents a binary expression like a + b."""

    left: Expr
    op: str
    right: Expr


@dataclass(frozen=True)
class Stmt:
    """Base type for all statements."""


@dataclass(frozen=True)
class UseStmt(Stmt):
    """Represents a use statement."""

    cube_id: str
    alias: str | None
    version_pin: str | None
    flavor: str | None
    repeat: int | None
    line: int
    col: int


@dataclass(frozen=True)
class ConnectStmt(Stmt):
    """Represents a connect statement."""

    from_ref: PathRef
    to_ref: PathRef
    line: int
    col: int


@dataclass(frozen=True)
class SetStmt(Stmt):
    """Represents a set statement."""

    target: PathRef | WildcardRef
    value: Expr
    line: int
    col: int


@dataclass(frozen=True)
class LetStmt(Stmt):
    """Represents a let statement."""

    name: str
    expr: Expr
    line: int
    col: int


@dataclass(frozen=True)
class EnableStmt(Stmt):
    """Represents a node enable statement."""

    target: PathRef
    line: int
    col: int


@dataclass(frozen=True)
class DisableStmt(Stmt):
    """Represents a disable statement."""

    target: PathRef
    line: int
    col: int


@dataclass(frozen=True)
class Script:
    """Represents a full script of statements."""

    statements: list[Stmt]


ExprType = Union[
    LiteralExpr,
    NameExpr,
    RandomExpr,
    DottedRefExpr,
    UnaryExpr,
    BinaryExpr,
]
