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
"""Token definitions for the Sugar DSL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Enumeration of supported token types."""

    IDENT = auto()
    STRING = auto()
    NUMBER = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    RANDOM = auto()
    USE = auto()
    AS = auto()
    WITH = auto()
    CONNECT = auto()
    SET = auto()
    LET = auto()
    ENABLE = auto()
    DISABLE = auto()
    REPEAT = auto()
    TO = auto()
    DOT = auto()
    COMMA = auto()
    EQUALS = auto()
    STAR = auto()
    PLUS = auto()
    SLASH = auto()
    AT = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    DASH = auto()
    LPAREN = auto()
    RPAREN = auto()
    NEWLINE = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    """A single token emitted by the lexer.

    Args:
        type: The token type.
        value: The raw token value, if any.
        line: 1-based line number.
        col: 1-based column number.
    """

    type: TokenType
    value: str | None
    line: int
    col: int
