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
from sugar.dsl.ast import (
    ConnectStmt,
    DottedRefExpr,
    EnableStmt,
    LiteralExpr,
    PathRef,
    RangeExpr,
    Script,
    SetStmt,
    UseStmt,
    WildcardRef,
)
from sugar.dsl.parser import parse_script


def test_parse_use_with_version_and_repeat() -> None:
    script = parse_script('use "processor"@1.2.3 as proc repeat 2\n')
    assert isinstance(script, Script)
    assert len(script.statements) == 1
    stmt = script.statements[0]
    assert isinstance(stmt, UseStmt)
    assert stmt.cube_id == "processor"
    assert stmt.alias == "proc"
    assert stmt.version_pin == "1.2.3"
    assert stmt.flavor is None
    assert stmt.repeat == 2


def test_parse_use_with_flavor_and_alias() -> None:
    script = parse_script('use "processor" with "Portrait" as proc\n')
    stmt = script.statements[0]
    assert isinstance(stmt, UseStmt)
    assert stmt.cube_id == "processor"
    assert stmt.flavor == "Portrait"
    assert stmt.alias == "proc"


def test_parse_use_with_version_flavor_alias_and_repeat() -> None:
    script = parse_script('use "processor"@1.2.3 with "Portrait" as proc repeat 2\n')
    stmt = script.statements[0]
    assert isinstance(stmt, UseStmt)
    assert stmt.version_pin == "1.2.3"
    assert stmt.flavor == "Portrait"
    assert stmt.alias == "proc"
    assert stmt.repeat == 2


def test_parse_set_with_wildcard() -> None:
    script = parse_script("set *.KSampler.cfg = 7.5\n")
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.target, WildcardRef)
    assert stmt.target.cube == "*"
    assert stmt.target.cls == "KSampler"
    assert stmt.target.input_key == "cfg"
    assert isinstance(stmt.value, LiteralExpr)
    assert stmt.value.value == 7.5


def test_parse_triple_quoted_string() -> None:
    script = parse_script('set a.b.c = """line1\nline2"""\n')
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.value, LiteralExpr)
    assert stmt.value.value == "line1\nline2"


def test_parse_dotted_ref_expression() -> None:
    script = parse_script("set a.b.c = x.y.z\n")
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.value, DottedRefExpr)
    assert stmt.value.ref.parts == ["x", "y", "z"]


def test_parse_whole_node_link_assignment() -> None:
    """Whole-node link syntax should parse as two-segment target and source refs."""

    script = parse_script('set "diffusion upscale".vectorscopecc = "text to image".vectorscopecc\n')
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.target, PathRef)
    assert stmt.target.parts == ["diffusion upscale", "vectorscopecc"]
    assert isinstance(stmt.value, DottedRefExpr)
    assert stmt.value.ref.parts == ["text to image", "vectorscopecc"]


def test_parse_dotted_ref_expression_with_quoted_alias() -> None:
    script = parse_script(
        'set target.node.input = "text to image".positive_prompt.prompt_template\n'
    )
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.value, DottedRefExpr)
    assert stmt.value.ref.parts == [
        "text to image",
        "positive_prompt",
        "prompt_template",
    ]


def test_parse_string_literal_expression() -> None:
    script = parse_script('set a.b.c = "text to image"\n')
    stmt = script.statements[0]
    assert isinstance(stmt, SetStmt)
    assert isinstance(stmt.value, LiteralExpr)
    assert stmt.value.value == "text to image"


def test_parse_connect_with_range() -> None:
    script = parse_script("connect a[1-3].out to b[1-3].inp\n")
    stmt = script.statements[0]
    assert isinstance(stmt, ConnectStmt)
    assert isinstance(stmt.from_ref.range_expr, RangeExpr)
    assert stmt.from_ref.range_expr.start == 1
    assert stmt.from_ref.range_expr.end == 3
    assert isinstance(stmt.to_ref.range_expr, RangeExpr)
    assert stmt.to_ref.range_expr.start == 1
    assert stmt.to_ref.range_expr.end == 3


def test_parse_connect_with_quoted_aliases() -> None:
    script = parse_script(
        'connect "text to image".output.image to "automask detailer".input.image\n'
    )
    stmt = script.statements[0]
    assert isinstance(stmt, ConnectStmt)
    assert stmt.from_ref.parts == ["text to image", "output", "image"]
    assert stmt.to_ref.parts == ["automask detailer", "input", "image"]


def test_parse_enable_with_quoted_path_segments() -> None:
    script = parse_script('enable "Alias With Space"."node with space"\n')
    stmt = script.statements[0]
    assert isinstance(stmt, EnableStmt)
    assert stmt.target.parts == ["Alias With Space", "node with space"]
