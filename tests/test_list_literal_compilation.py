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
"""Prove authored list literals survive both Comfy artifact projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from sugar.api.builder import build_comfy_artifacts_from_text
from sugar.dsl.ast import ListExpr, LiteralExpr, SetStmt
from sugar.dsl.parser import parse_script
from tests.fixtures.cubes import write_cube


def test_parser_accepts_empty_nested_and_trailing_comma_list_literals() -> None:
    """List syntax should preserve ordered expression structure before analysis."""

    script = parse_script('set Batch.loader.image = ["first.png", [1, true], null,]\n')

    statement = cast(SetStmt, script.statements[0])
    assert isinstance(statement.value, ListExpr)
    assert len(statement.value.items) == 3
    assert isinstance(statement.value.items[0], LiteralExpr)
    assert statement.value.items[0].value == "first.png"
    nested = cast(ListExpr, statement.value.items[1])
    assert [cast(LiteralExpr, item).value for item in nested.items] == [1, True]
    assert cast(LiteralExpr, statement.value.items[2]).value is None
    empty_statement = cast(
        SetStmt,
        parse_script("set Batch.loader.image = []\n").statements[0],
    )
    assert cast(ListExpr, empty_statement.value).items == []


def test_list_literal_compiles_to_wrapped_prompt_and_plain_ui_widget(
    tmp_path: Path,
) -> None:
    """Executable arrays must be wrapped while UI widgets retain plain lists."""

    _write_batch_cube(tmp_path)

    artifacts = build_comfy_artifacts_from_text(
        'use "batch" as Batch\nset Batch.loader.image = ["first.png", "second.png"]\n',
        output_dir=tmp_path / "output",
        cube_root=tmp_path,
        seed_provider=lambda: 1,
    )

    prompt_node = _prompt_node(artifacts["prompt"], "SimpleSyrup.LoadMaskBatch")
    assert prompt_node["inputs"] == {
        "image": {"__value__": ["first.png", "second.png"]},
        "channel": "red",
    }
    ui_node = _ui_node(artifacts["workflow"], "SimpleSyrup.LoadMaskBatch")
    assert ui_node["widgets_values"] == [["first.png", "second.png"], "red"]


def test_link_shaped_list_literal_cannot_be_reinterpreted_as_a_node_link(
    tmp_path: Path,
) -> None:
    """Literal provenance must win even when values match Comfy's link shape."""

    _write_batch_cube(tmp_path)

    artifacts = build_comfy_artifacts_from_text(
        'use "batch" as Batch\nset Batch.loader.image = ["upstream", 0]\n',
        output_dir=tmp_path / "output",
        cube_root=tmp_path,
        seed_provider=lambda: 1,
    )

    prompt_node = _prompt_node(artifacts["prompt"], "SimpleSyrup.LoadMaskBatch")
    assert cast(dict[str, object], prompt_node["inputs"])["image"] == {"__value__": ["upstream", 0]}


def _write_batch_cube(root: Path) -> None:
    """Write the smallest current-format cube containing a multiselect widget."""

    write_cube(
        root / "batch.cube",
        {
            "cube_id": "batch",
            "version": "1.0.0",
            "nodes": {
                "loader": {
                    "class_type": "SimpleSyrup.LoadMaskBatch",
                    "inputs": {"image": [], "channel": "red"},
                }
            },
            "outputs": {"output.mask": ["loader", 0]},
            "definitions": {
                "SimpleSyrup.LoadMaskBatch": {
                    "input": {
                        "required": {
                            "image": [
                                "COMBO",
                                {
                                    "default": [],
                                    "multiselect": True,
                                    "options": ["first.png", "second.png"],
                                },
                            ],
                            "channel": [
                                "COMBO",
                                {
                                    "default": "red",
                                    "options": ["alpha", "red"],
                                },
                            ],
                        }
                    },
                    "input_order": {"required": ["image", "channel"]},
                    "output": ["MASK"],
                    "output_name": ["mask"],
                }
            },
        },
    )


def _prompt_node(prompt: dict[str, Any], class_type: str) -> dict[str, Any]:
    """Return the unique API prompt node for one class."""

    return next(node for node in prompt.values() if node.get("class_type") == class_type)


def _ui_node(workflow: dict[str, Any], class_type: str) -> dict[str, Any]:
    """Return the unique UI workflow node for one class."""

    nodes = cast(list[dict[str, Any]], workflow["nodes"])
    return next(node for node in nodes if node.get("type") == class_type)
