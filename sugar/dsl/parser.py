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
"""Parser for the Sugar DSL."""

from __future__ import annotations

from dataclasses import dataclass

from .ast import (
    BinaryExpr,
    ConnectStmt,
    DisableStmt,
    DottedRefExpr,
    EnableStmt,
    Expr,
    LetStmt,
    LiteralExpr,
    ListExpr,
    NameExpr,
    PathRef,
    RandomExpr,
    RangeExpr,
    Script,
    SetStmt,
    Stmt,
    UnaryExpr,
    UseStmt,
    WildcardRef,
)
from .lexer import Lexer
from .tokens import Token, TokenType


@dataclass
class _ParseState:
    """Mutable token cursor state for the recursive-descent parser."""

    tokens: list[Token]
    index: int = 0


def parse_script(text: str) -> Script:
    """Parse DSL text into an AST.

    Args:
        text: The DSL script text.

    Returns:
        The parsed AST script.
    """

    tokens = Lexer(text).tokenize()
    parser = _Parser(tokens)
    return parser.parse_script()


class _Parser:
    """Parse a token stream into Sugar DSL AST nodes."""

    def __init__(self, tokens: list[Token]) -> None:
        """Create a parser over a token sequence."""

        self._state = _ParseState(tokens=tokens)

    def parse_script(self) -> Script:
        """Parse all statements until EOF."""

        statements = []
        while not self._match(TokenType.EOF):
            if self._match(TokenType.NEWLINE):
                self._advance()
                continue
            statements.append(self._parse_statement())
        return Script(statements=statements)

    def _parse_statement(self) -> Stmt:
        """Dispatch to the statement parser for the next keyword."""

        token = self._peek()
        if token.type == TokenType.USE:
            return self._parse_use()
        if token.type == TokenType.CONNECT:
            return self._parse_connect()
        if token.type == TokenType.SET:
            return self._parse_set()
        if token.type == TokenType.LET:
            return self._parse_let()
        if token.type == TokenType.ENABLE:
            return self._parse_enable()
        if token.type == TokenType.DISABLE:
            return self._parse_disable()
        raise self._error(token, "Unexpected statement.")

    def _parse_use(self) -> UseStmt:
        """Parse a cube use statement with optional version, flavor, alias, and repeat."""

        keyword = self._expect(TokenType.USE, "Expected 'use'.")
        cube_token = self._expect_any((TokenType.IDENT, TokenType.STRING), "Expected cube id.")
        cube_id = self._token_value(cube_token)
        version_pin: str | None = None
        flavor: str | None = None
        alias: str | None = None
        repeat: int | None = None

        if self._match(TokenType.AT):
            self._advance()
            version_pin = self._parse_version_pin()

        if self._match(TokenType.WITH):
            self._advance()
            flavor_token = self._expect_any(
                (TokenType.IDENT, TokenType.STRING),
                "Expected flavor name after 'with'.",
            )
            flavor = self._token_value(flavor_token)

        if self._match(TokenType.AS):
            self._advance()
            alias_token = self._expect_any((TokenType.IDENT, TokenType.STRING), "Expected alias.")
            alias = self._token_value(alias_token)

        if self._match(TokenType.REPEAT):
            self._advance()
            count_token = self._expect(TokenType.NUMBER, "Expected repeat count.")
            repeat = self._parse_int_literal(count_token)

        self._consume_line_end()
        return UseStmt(
            cube_id=cube_id,
            alias=alias,
            version_pin=version_pin,
            flavor=flavor,
            repeat=repeat,
            line=keyword.line,
            col=keyword.col,
        )

    def _parse_connect(self) -> ConnectStmt:
        """Parse a connection statement between two path references."""

        keyword = self._expect(TokenType.CONNECT, "Expected 'connect'.")
        from_ref = self._parse_path_ref()
        self._expect(TokenType.TO, "Expected 'to' in connect statement.")
        to_ref = self._parse_path_ref()
        self._consume_line_end()
        return ConnectStmt(
            from_ref=from_ref,
            to_ref=to_ref,
            line=keyword.line,
            col=keyword.col,
        )

    def _parse_set(self) -> SetStmt:
        """Parse an explicit or wildcard set statement."""

        keyword = self._expect(TokenType.SET, "Expected 'set'.")
        if self._match(TokenType.STAR):
            target: PathRef | WildcardRef = self._parse_wildcard_ref()
        else:
            target = self._parse_path_ref()
        self._expect(TokenType.EQUALS, "Expected '=' in set statement.")
        value = self._parse_expression()
        self._consume_line_end()
        return SetStmt(target=target, value=value, line=keyword.line, col=keyword.col)

    def _parse_let(self) -> LetStmt:
        """Parse a local expression binding statement."""

        keyword = self._expect(TokenType.LET, "Expected 'let'.")
        name_token = self._expect(TokenType.IDENT, "Expected variable name.")
        self._expect(TokenType.EQUALS, "Expected '=' in let statement.")
        expr = self._parse_expression()
        self._consume_line_end()
        return LetStmt(
            name=self._token_value(name_token),
            expr=expr,
            line=keyword.line,
            col=keyword.col,
        )

    def _parse_disable(self) -> DisableStmt:
        """Parse a node disable statement."""

        keyword = self._expect(TokenType.DISABLE, "Expected 'disable'.")
        target = self._parse_path_ref()
        self._consume_line_end()
        return DisableStmt(target=target, line=keyword.line, col=keyword.col)

    def _parse_enable(self) -> EnableStmt:
        """Parse a node enable statement."""

        keyword = self._expect(TokenType.ENABLE, "Expected 'enable'.")
        target = self._parse_path_ref()
        self._consume_line_end()
        return EnableStmt(target=target, line=keyword.line, col=keyword.col)

    def _parse_wildcard_ref(self) -> WildcardRef:
        """Parse a wildcard class/input selector used by set statements."""

        self._expect(TokenType.STAR, "Expected '*'.")
        self._expect(TokenType.DOT, "Expected '.' after '*'.")
        cls_token = self._expect_any((TokenType.STAR, TokenType.IDENT), "Expected class selector.")
        cls_value = self._token_value(cls_token)
        self._expect(TokenType.DOT, "Expected '.' after class selector.")
        input_token = self._expect_any((TokenType.IDENT, TokenType.STRING), "Expected input key.")
        input_key = self._token_value(input_token)
        return WildcardRef(cube="*", cls=cls_value, input_key=input_key)

    def _parse_path_ref(self) -> PathRef:
        """Parse a dotted path reference with an optional alias range."""

        head = self._expect_any((TokenType.IDENT, TokenType.STRING), "Expected identifier.")
        parts = [self._token_value(head)]
        range_expr: RangeExpr | None = None
        if self._match(TokenType.LBRACKET):
            range_expr = self._parse_range()
        while self._match(TokenType.DOT):
            self._advance()
            part = self._expect_any((TokenType.IDENT, TokenType.STRING), "Expected path segment.")
            parts.append(self._token_value(part))
        return PathRef(parts=parts, range_expr=range_expr)

    def _parse_range(self) -> RangeExpr:
        """Parse an inclusive numeric range expression."""

        self._expect(TokenType.LBRACKET, "Expected '[' for range.")
        start_token = self._expect(TokenType.NUMBER, "Expected range start.")
        self._expect(TokenType.DASH, "Expected '-' in range.")
        end_token = self._expect(TokenType.NUMBER, "Expected range end.")
        self._expect(TokenType.RBRACKET, "Expected ']' after range.")
        return RangeExpr(
            start=self._parse_int_literal(start_token),
            end=self._parse_int_literal(end_token),
        )

    def _parse_expression(self) -> Expr:
        """Parse an expression using the highest-precedence production."""

        return self._parse_addition()

    def _parse_version_pin(self) -> str:
        """Parse a version pin following a `use` statement."""

        token = self._expect_any(
            (TokenType.IDENT, TokenType.STRING, TokenType.NUMBER),
            "Expected version pin.",
        )
        if token.type == TokenType.STRING:
            return self._token_value(token)
        parts = [self._token_value(token)]
        while self._match(TokenType.DOT):
            dot_token = self._advance()
            if not self._match_any((TokenType.IDENT, TokenType.NUMBER)):
                raise self._error(dot_token, "Expected version segment after '.'.")
            parts.append(self._token_value(self._advance()))
        return ".".join(parts)

    def _parse_addition(self) -> Expr:
        """Parse addition and subtraction expressions."""

        expr = self._parse_multiplication()
        while self._match(TokenType.DASH) or self._match(TokenType.PLUS):
            op_token = self._advance()
            op_value = "-" if op_token.type == TokenType.DASH else "+"
            right = self._parse_multiplication()
            expr = BinaryExpr(left=expr, op=op_value, right=right)
        return expr

    def _parse_multiplication(self) -> Expr:
        """Parse multiplication and division expressions."""

        expr = self._parse_unary()
        while self._match(TokenType.STAR) or self._match(TokenType.SLASH):
            op_token = self._advance()
            op_value = "*" if op_token.type == TokenType.STAR else "/"
            right = self._parse_unary()
            expr = BinaryExpr(left=expr, op=op_value, right=right)
        return expr

    def _parse_unary(self) -> Expr:
        """Parse unary prefix expressions."""

        if self._match(TokenType.DASH):
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="-", operand=operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        """Parse literal, list, name, random, parenthesized, or dotted-ref expressions."""

        token = self._peek()
        if token.type in (TokenType.IDENT, TokenType.STRING) and self._looks_like_path_ref():
            ref = self._parse_path_ref()
            return DottedRefExpr(ref=ref)
        if token.type == TokenType.NUMBER:
            self._advance()
            literal = self._parse_numeric_literal(token)
            return LiteralExpr(value=literal, raw=token.value or "")
        if token.type == TokenType.STRING:
            self._advance()
            return LiteralExpr(value=token.value or "", raw=token.value or "")
        if token.type == TokenType.TRUE:
            self._advance()
            return LiteralExpr(value=True, raw="true")
        if token.type == TokenType.FALSE:
            self._advance()
            return LiteralExpr(value=False, raw="false")
        if token.type == TokenType.NULL:
            self._advance()
            return LiteralExpr(value=None, raw="null")
        if token.type == TokenType.LBRACKET:
            return self._parse_list_expression()
        if token.type == TokenType.RANDOM:
            self._advance()
            return RandomExpr()
        if token.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN, "Expected ')'.")
            return expr
        if token.type == TokenType.IDENT:
            self._advance()
            return NameExpr(name=self._token_value(token))
        raise self._error(token, "Expected expression.")

    def _parse_list_expression(self) -> ListExpr:
        """Parse a comma-delimited ordered expression list."""

        self._expect(TokenType.LBRACKET, "Expected '[' for list literal.")
        items: list[Expr] = []
        if not self._match(TokenType.RBRACKET):
            while True:
                items.append(self._parse_expression())
                if not self._match(TokenType.COMMA):
                    break
                self._advance()
                if self._match(TokenType.RBRACKET):
                    break
        self._expect(TokenType.RBRACKET, "Expected ']' after list literal.")
        return ListExpr(items=items)

    def _looks_like_path_ref(self) -> bool:
        """Return whether the next tokens form a dotted path reference."""

        if not self._match_any((TokenType.IDENT, TokenType.STRING)):
            return False
        next_token = self._peek(1)
        return next_token.type in (TokenType.DOT, TokenType.LBRACKET)

    def _consume_line_end(self) -> None:
        """Consume trailing newlines after a statement."""

        while self._match(TokenType.NEWLINE):
            self._advance()

    def _parse_numeric_literal(self, token: Token) -> int | float:
        """Parse one numeric token into an int or float."""

        raw = token.value or ""
        if "." in raw:
            return float(raw)
        return int(raw)

    def _parse_int_literal(self, token: Token) -> int:
        """Parse one numeric token and require that it is an integer."""

        raw = token.value or ""
        if "." in raw:
            raise self._error(token, "Expected integer value.")
        return int(raw)

    def _expect(self, token_type: TokenType, message: str) -> Token:
        """Consume and return a token of the expected type."""

        token = self._peek()
        if token.type != token_type:
            raise self._error(token, message)
        return self._advance()

    def _expect_any(self, types: tuple[TokenType, ...], message: str) -> Token:
        """Consume and return a token matching any expected type."""

        token = self._peek()
        if token.type not in types:
            raise self._error(token, message)
        return self._advance()

    def _match(self, token_type: TokenType) -> bool:
        """Return whether the current token has the requested type."""

        return self._peek().type == token_type

    def _match_any(self, types: tuple[TokenType, ...]) -> bool:
        """Return whether the current token has one of the requested types."""

        return self._peek().type in types

    def _peek(self, offset: int = 0) -> Token:
        """Return a token relative to the parser cursor without consuming it."""

        index = self._state.index + offset
        if index >= len(self._state.tokens):
            return self._state.tokens[-1]
        return self._state.tokens[index]

    def _advance(self) -> Token:
        """Consume and return the current token."""

        token = self._peek()
        if self._state.index < len(self._state.tokens):
            self._state.index += 1
        return token

    def _token_value(self, token: Token) -> str:
        """Return the semantic string value represented by a token."""

        if token.value is None:
            raise self._error(token, "Expected token value.")
        return token.value

    def _error(self, token: Token, message: str) -> RuntimeError:
        """Build a parser error with source line and column context."""

        return RuntimeError(f"Line {token.line}, col {token.col}: {message}")
