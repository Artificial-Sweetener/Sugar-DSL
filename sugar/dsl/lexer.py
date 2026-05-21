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
"""Lexical analysis for the Sugar DSL."""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Token, TokenType


_KEYWORDS = {
    "use": TokenType.USE,
    "as": TokenType.AS,
    "with": TokenType.WITH,
    "connect": TokenType.CONNECT,
    "set": TokenType.SET,
    "let": TokenType.LET,
    "enable": TokenType.ENABLE,
    "disable": TokenType.DISABLE,
    "repeat": TokenType.REPEAT,
    "to": TokenType.TO,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "random": TokenType.RANDOM,
}


@dataclass
class _Cursor:
    """Track the current lexer position for diagnostics."""

    index: int = 0
    line: int = 1
    col: int = 1


class Lexer:
    """Tokenize Sugar DSL text into a stream of tokens."""

    def __init__(self, text: str) -> None:
        """Store source text and initialize the cursor."""

        self._text = text
        self._cursor = _Cursor()

    def tokenize(self) -> list[Token]:
        """Tokenize the input text.

        Returns:
            The list of tokens, including an EOF terminator.
        """

        tokens: list[Token] = []
        while not self._is_at_end():
            ch = self._peek()
            if ch in (" ", "\t"):
                self._advance()
                continue
            if ch in ("\n", "\r"):
                self._consume_newline(tokens)
                continue
            if ch == "#":
                self._consume_comment()
                continue
            if ch in ('"', "'"):
                tokens.append(self._read_string())
                continue
            if ch.isdigit():
                tokens.append(self._read_number())
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._read_identifier())
                continue
            tokens.append(self._read_symbol())

        tokens.append(Token(TokenType.EOF, None, self._cursor.line, self._cursor.col))
        return tokens

    def _is_at_end(self) -> bool:
        """Return whether the cursor has consumed all source text."""

        return self._cursor.index >= len(self._text)

    def _peek(self, offset: int = 0) -> str:
        """Return a character relative to the cursor without consuming it."""

        idx = self._cursor.index + offset
        if idx >= len(self._text):
            return ""
        return self._text[idx]

    def _advance(self) -> str:
        """Consume one character and update line and column counters."""

        ch = self._text[self._cursor.index]
        self._cursor.index += 1
        if ch == "\n":
            self._cursor.line += 1
            self._cursor.col = 1
        else:
            self._cursor.col += 1
        return ch

    def _consume_newline(self, tokens: list[Token]) -> None:
        """Consume a platform newline and append one newline token."""

        line = self._cursor.line
        col = self._cursor.col
        ch = self._advance()
        if ch == "\r" and self._peek() == "\n":
            self._advance()
        tokens.append(Token(TokenType.NEWLINE, None, line, col))

    def _consume_comment(self) -> None:
        """Skip a line comment without consuming the newline."""

        while not self._is_at_end() and self._peek() not in ("\n", "\r"):
            self._advance()

    def _read_string(self) -> Token:
        """Read a quoted string token, including triple-quoted strings."""

        line = self._cursor.line
        col = self._cursor.col
        quote = self._peek()
        if quote == '"' and self._peek(1) == '"' and self._peek(2) == '"':
            return self._read_triple_string()

        self._advance()
        value_chars: list[str] = []
        while not self._is_at_end():
            ch = self._advance()
            if ch == quote:
                return Token(TokenType.STRING, "".join(value_chars), line, col)
            if ch == "\\":
                esc = self._advance() if not self._is_at_end() else ""
                value_chars.append(self._decode_escape(esc))
                continue
            if ch in ("\n", "\r"):
                raise RuntimeError(f"Unterminated string literal at line {line}, col {col}.")
            value_chars.append(ch)

        raise RuntimeError(f"Unterminated string literal at line {line}, col {col}.")

    def _read_triple_string(self) -> Token:
        """Read a triple-quoted string until its closing delimiter."""

        line = self._cursor.line
        col = self._cursor.col
        self._advance()
        self._advance()
        self._advance()
        value_chars: list[str] = []
        while not self._is_at_end():
            if self._peek() == '"' and self._peek(1) == '"' and self._peek(2) == '"':
                self._advance()
                self._advance()
                self._advance()
                return Token(TokenType.STRING, "".join(value_chars), line, col)
            value_chars.append(self._advance())

        raise RuntimeError(f"Unterminated triple-quoted string at line {line}, col {col}.")

    def _decode_escape(self, ch: str) -> str:
        """Decode one recognized string escape sequence."""

        escape_map = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "\\": "\\",
            '"': '"',
            "'": "'",
        }
        return escape_map.get(ch, ch)

    def _read_number(self) -> Token:
        """Read an integer or decimal number token."""

        line = self._cursor.line
        col = self._cursor.col
        digits: list[str] = []
        while self._peek().isdigit():
            digits.append(self._advance())
        if self._peek() == "." and self._peek(1).isdigit():
            digits.append(self._advance())
            while self._peek().isdigit():
                digits.append(self._advance())
        return Token(TokenType.NUMBER, "".join(digits), line, col)

    def _read_identifier(self) -> Token:
        """Read an identifier or keyword token."""

        line = self._cursor.line
        col = self._cursor.col
        chars: list[str] = []
        while True:
            ch = self._peek()
            if not (ch.isalnum() or ch == "_"):
                break
            chars.append(self._advance())
        value = "".join(chars)
        keyword = _KEYWORDS.get(value.lower())
        if keyword:
            return Token(keyword, value, line, col)
        return Token(TokenType.IDENT, value, line, col)

    def _read_symbol(self) -> Token:
        """Read one punctuation token or raise for an unknown character."""

        line = self._cursor.line
        col = self._cursor.col
        ch = self._advance()
        if ch == ".":
            return Token(TokenType.DOT, ch, line, col)
        if ch == ",":
            return Token(TokenType.COMMA, ch, line, col)
        if ch == "=":
            return Token(TokenType.EQUALS, ch, line, col)
        if ch == "*":
            return Token(TokenType.STAR, ch, line, col)
        if ch == "+":
            return Token(TokenType.PLUS, ch, line, col)
        if ch == "/":
            return Token(TokenType.SLASH, ch, line, col)
        if ch == "@":
            return Token(TokenType.AT, ch, line, col)
        if ch == "[":
            return Token(TokenType.LBRACKET, ch, line, col)
        if ch == "]":
            return Token(TokenType.RBRACKET, ch, line, col)
        if ch == "-":
            return Token(TokenType.DASH, ch, line, col)
        if ch == "(":
            return Token(TokenType.LPAREN, ch, line, col)
        if ch == ")":
            return Token(TokenType.RPAREN, ch, line, col)
        raise RuntimeError(f"Unexpected character '{ch}' at line {line}, col {col}.")
