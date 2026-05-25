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
"""Tests for Sugar-owned live Comfy node definition providers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import json

import pytest

from tests.fixtures.cubes import write_cube
from sugar.api.builder import build_comfy_artifacts_from_text
from sugar.compiler.errors import SugarCompilerError
from sugar.runtime.live_definitions import (
    ComfyObjectInfoLiveNodeDefinitionProvider,
    ComfyRegistryLiveNodeDefinitionProvider,
    StaticLiveNodeDefinitionProvider,
    normalize_object_info_payload,
)


class _Response:
    """Minimal context-manager response for object-info urlopen monkeypatches."""

    def __init__(self, body: bytes) -> None:
        """Store response bytes."""

        self._body = body

    def __enter__(self) -> _Response:
        """Return the response for context-manager use."""

        return self

    def __exit__(self, *_args: object) -> None:
        """Close the test response context."""

        return None

    def read(self) -> bytes:
        """Return the configured response body."""

        return self._body


class _RegistryNode:
    """Fake Comfy node class for registry provider tests."""

    @classmethod
    def INPUT_TYPES(cls) -> object:
        """Return Comfy-style input metadata."""

        return {
            "required": {
                "steps": ("INT", {"default": 20}),
                "sampler_name": (["euler", "ddim"], {"default": "ddim"}),
            },
            "optional": {"note": ("STRING", {"default": "hello"})},
        }


def test_object_info_provider_normalizes_comfy_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sugar's HTTP provider should normalize Comfy object-info responses."""

    opened: list[tuple[str, float]] = []

    def _open(url: str, timeout: float) -> _Response:
        """Return a fake object-info response."""

        opened.append((url, timeout))
        return _Response(json.dumps(_object_info_payload()).encode("utf-8"))

    monkeypatch.setattr("sugar.runtime.live_definitions.urllib.request.urlopen", _open)

    provider = ComfyObjectInfoLiveNodeDefinitionProvider(
        server="127.0.0.1:8188",
        timeout=4.0,
    )
    definition = provider.definition_for("LiveNode")

    assert opened == [("http://127.0.0.1:8188/object_info", 4.0)]
    assert definition is not None
    assert definition.inputs["new_widget"].default == "live default"
    assert definition.inputs["new_widget"].has_default is True
    assert definition.inputs["optional_note"].required is False
    assert definition.inputs["sampler_name"].choices == ("euler", "ddim")


def test_registry_provider_normalizes_comfy_input_types() -> None:
    """Sugar's registry provider should own in-process INPUT_TYPES normalization."""

    provider = ComfyRegistryLiveNodeDefinitionProvider(
        registry_source=lambda: {"RegistryNode": _RegistryNode}
    )

    definition = provider.definition_for("RegistryNode")

    assert definition is not None
    assert definition.inputs["steps"].value_type == "INT"
    assert definition.inputs["steps"].default == 20
    assert definition.inputs["note"].required is False
    assert definition.inputs["sampler_name"].value_type == "COMBO"
    assert definition.inputs["sampler_name"].choices == ("euler", "ddim")


def test_standalone_comfy_server_allows_hand_authored_live_only_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Standalone Sugar can compile live-only set lines through object-info."""

    def _open(url: str, timeout: float) -> _Response:
        """Return a fake object-info response for standalone compile."""

        _ = url, timeout
        return _Response(json.dumps(_object_info_payload()).encode("utf-8"))

    monkeypatch.setattr("sugar.runtime.live_definitions.urllib.request.urlopen", _open)
    cube_root = _write_live_cube(tmp_path, node_inputs={})

    artifacts = build_comfy_artifacts_from_text(
        """
        use "live_cube" as Demo
        set Demo.processor.new_widget = "chosen value"
        """,
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        comfy_server="127.0.0.1:8188",
    )

    assert _node_inputs(artifacts["prompt"], "LiveNode")["new_widget"] == "chosen value"


def test_static_provider_from_object_info_applies_defaults_and_prunes_stale(
    tmp_path: Path,
) -> None:
    """Sugar-owned static snapshots should drive defaulting and stale pruning."""

    provider = StaticLiveNodeDefinitionProvider.from_object_info_payload(_object_info_payload())
    cube_root = _write_live_cube(
        tmp_path,
        node_inputs={"old_widget": "drop me"},
    )

    artifacts = build_comfy_artifacts_from_text(
        'use "live_cube" as Demo',
        output_dir=tmp_path / "out",
        cube_root=cube_root,
        live_node_definition_provider=provider,
    )

    inputs = _node_inputs(artifacts["prompt"], "LiveNode")
    assert inputs["new_widget"] == "live default"
    assert "old_widget" not in inputs


def test_object_info_provider_reports_invalid_payload() -> None:
    """Malformed object-info entries should fail closed with live-definition codes."""

    with pytest.raises(SugarCompilerError) as error_info:
        normalize_object_info_payload({"LiveNode": "not an object"})

    assert error_info.value.code == "sugar-live-input-invalid"
    assert error_info.value.node_class_type == "LiveNode"


def _object_info_payload() -> dict[str, object]:
    """Return a Comfy object-info payload with scalar and combo inputs."""

    return {
        "LiveNode": {
            "input": {
                "required": {
                    "new_widget": ["STRING", {"default": "live default"}],
                    "sampler_name": [["euler", "ddim"], {"default": "ddim"}],
                },
                "optional": {
                    "optional_note": ["STRING", {"default": "hello"}],
                },
            }
        }
    }


def _write_live_cube(tmp_path: Path, *, node_inputs: dict[str, Any]) -> Path:
    """Write a single-node cube fixture with intentionally incomplete inputs."""

    cube_root = tmp_path / "cubes"
    cube_root.mkdir()
    write_cube(
        cube_root / "live_cube.cube",
        {
            "cube_id": "live_cube",
            "version": "1.0.0",
            "nodes": {
                "processor": {
                    "class_type": "LiveNode",
                    "inputs": dict(node_inputs),
                }
            },
            "outputs": {"output.image": "processor"},
        },
    )
    return cube_root


def _node_inputs(prompt: Mapping[str, Any], class_type: str) -> Mapping[str, Any]:
    """Return inputs for the only prompt node with the requested class type."""

    nodes = [node for node in prompt.values() if node.get("class_type") == class_type]
    assert len(nodes) == 1
    inputs = nodes[0].get("inputs")
    assert isinstance(inputs, Mapping)
    return inputs
