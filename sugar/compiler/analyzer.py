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
"""Semantic analysis for the Sugar DSL."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from ..catalog.artifacts import CubeArtifactResolver, FilesystemCubeArtifactResolver
from ..catalog.models import CubeDocument
from ..catalog.registry import CubeRegistry
from ..catalog.local_flavors import LocalFlavorCatalog
from ..dsl.ast import (
    BinaryExpr,
    ConnectStmt,
    DisableStmt,
    DottedRefExpr,
    EnableStmt,
    Expr,
    LetStmt,
    LiteralExpr,
    NameExpr,
    PathRef,
    RandomExpr,
    RangeExpr,
    Script,
    SetStmt,
    UnaryExpr,
    UseStmt,
    WildcardRef,
)
from ..dsl.parser import parse_script
from ..shared.seed import SeedProvider, generate_comfy_seed
from .aliases import AliasRegistry
from .graph import CubeGraph, CubeGraphByAlias
from .graph_ops import (
    apply_plan_inheritance,
    apply_set,
    connect_binding_target,
    disable_node_passthrough,
    validate_node_link_compatibility,
)
from .ir import (
    SpawnPlan,
    add_connection,
    add_cube,
    add_disabled,
    add_enabled,
    add_node_link,
    add_set,
    create_spawn_plan,
)
from .materializer import CubeMaterializer
from .resolver import (
    require_mapping,
    resolve_connection_mapping,
    resolve_input_key,
    resolve_input_label_for_node,
    resolve_node_key,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ExplicitSet:
    """Deferred explicit set statement with source line context."""

    line: int
    target: PathRef
    value: Expr


@dataclass(frozen=True)
class _WildcardSet:
    """Deferred wildcard set statement with source line context."""

    line: int
    target: WildcardRef
    value: Expr


@dataclass(frozen=True)
class _Disable:
    """Deferred disable statement with source line context."""

    line: int
    target: PathRef


@dataclass(frozen=True)
class _Enable:
    """Deferred enable statement with source line context."""

    line: int
    target: PathRef


@dataclass(frozen=True)
class _ResolvedDisable:
    """Resolved disable target using canonical alias identity."""

    alias: str
    node_key: str
    line: int


@dataclass(frozen=True)
class _ResolvedEnable:
    """Resolved enable target using canonical alias identity."""

    alias: str
    node_key: str
    line: int


@dataclass(frozen=True)
class _EffectiveDisabled:
    """Effective disabled-node state after authored defaults and overrides."""

    alias: str
    node_key: str
    source_line: int | None
    reason: str


def analyze_text(
    text: str,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> SpawnPlan:
    """Analyze DSL text into a spawn plan.

    Args:
        text: The DSL script text.
        cube_root: Optional cube root directory.

    Returns:
        The spawn plan dictionary.
    """

    return analyze_script(
        parse_script(text),
        cube_root=cube_root,
        local_flavor_root=local_flavor_root,
        seed_provider=seed_provider,
        cube_artifact_resolver=cube_artifact_resolver,
    )


def analyze_script(
    script: Script,
    cube_root: Path | None = None,
    local_flavor_root: Path | None = None,
    *,
    seed_provider: SeedProvider = generate_comfy_seed,
    cube_artifact_resolver: CubeArtifactResolver | None = None,
) -> SpawnPlan:
    """Analyze a parsed script into a spawn plan.

    Args:
        script: The parsed AST script.
        cube_root: Optional cube root directory.
        local_flavor_root: Optional local flavor state root.
        seed_provider: Callable used to resolve DSL `random` expressions.

    Returns:
        The spawn plan dictionary.
    """

    root = Path(cube_root or Path.cwd() / "cubes").resolve()
    artifact_resolver = cube_artifact_resolver or FilesystemCubeArtifactResolver(CubeRegistry(root))
    local_flavors = LocalFlavorCatalog(local_flavor_root)
    materializer = CubeMaterializer(artifact_resolver, local_flavors)
    plan = create_spawn_plan(str(root))

    cubes: CubeGraphByAlias = {}
    alias_registry = AliasRegistry()
    order: list[str] = []
    aliases: dict[str, Any] = {}
    repeat_counters: dict[str, int] = {}
    deferred_sets: list[_ExplicitSet] = []
    deferred_wildcards: list[_WildcardSet] = []
    deferred_disable: list[_Disable] = []
    deferred_enable: list[_Enable] = []

    def add_cube_instance(
        cube_id: str,
        alias: str,
        line: int,
        version_pin: str | None,
        flavor_name: str | None,
    ) -> None:
        """Materialize one cube instance and record it in the spawn plan."""

        try:
            canonical_alias = alias_registry.register(alias, line=line)
        except RuntimeError as exc:
            logger.error(
                "Alias collision during Sugar analysis.",
                extra={
                    "operation": "analyze_script",
                    "cube_id": cube_id,
                    "alias": alias,
                    "source_line": line,
                    "error": str(exc),
                },
            )
            raise
        try:
            instance = materializer.materialize_resolved(
                cube_id=cube_id,
                alias=canonical_alias,
                version_pin=version_pin,
                flavor_name=flavor_name,
            )
        except RuntimeError as exc:
            logger.error(
                "Cube materialization failed during Sugar analysis.",
                extra={
                    "operation": "analyze_script",
                    "cube_root": str(root),
                    "cube_id": cube_id,
                    "alias": canonical_alias,
                    "version_pin": version_pin,
                    "flavor_name": flavor_name,
                    "source_line": line,
                    "error": str(exc),
                },
            )
            raise
        cubes[canonical_alias] = instance.cube
        order.append(canonical_alias)
        add_cube(
            plan,
            cube_id,
            canonical_alias,
            line,
            version_pin,
            flavor=flavor_name,
            requested_version=instance.requested_version,
            resolved_version=instance.resolved_version,
            flavor_id=instance.flavor_id,
            flavor_scope=instance.flavor_scope,
        )
        _add_flavor_sets(plan, canonical_alias, instance.raw_cube, instance.flavor_values)

    for stmt in script.statements:
        if isinstance(stmt, UseStmt):
            alias = stmt.alias or stmt.cube_id
            if stmt.repeat:
                start_index = repeat_counters.get(alias, 0) + 1
                for i in range(start_index, start_index + stmt.repeat):
                    add_cube_instance(
                        stmt.cube_id,
                        f"{alias}{i}",
                        stmt.line,
                        stmt.version_pin,
                        stmt.flavor,
                    )
                repeat_counters[alias] = start_index + stmt.repeat - 1
            else:
                add_cube_instance(stmt.cube_id, alias, stmt.line, stmt.version_pin, stmt.flavor)
            continue

        if isinstance(stmt, LetStmt):
            aliases[stmt.name] = _eval_expr(
                stmt.expr,
                aliases,
                cubes,
                alias_registry,
                stmt.line,
                seed_provider,
            )
            continue

        if isinstance(stmt, SetStmt):
            if isinstance(stmt.target, WildcardRef):
                deferred_wildcards.append(
                    _WildcardSet(line=stmt.line, target=stmt.target, value=stmt.value)
                )
            else:
                deferred_sets.append(
                    _ExplicitSet(line=stmt.line, target=stmt.target, value=stmt.value)
                )
            continue

        if isinstance(stmt, DisableStmt):
            deferred_disable.append(_Disable(line=stmt.line, target=stmt.target))
            continue

        if isinstance(stmt, EnableStmt):
            deferred_enable.append(_Enable(line=stmt.line, target=stmt.target))
            continue

        if isinstance(stmt, ConnectStmt):
            _apply_connect(stmt, cubes, alias_registry, plan)
            continue

        raise RuntimeError(f"Line {getattr(stmt, 'line', '?')}: Unsupported statement '{stmt}'.")

    for set_entry in deferred_sets:
        _apply_explicit_set(set_entry, aliases, cubes, alias_registry, plan, seed_provider)

    resolved_enables = _resolve_enable_entries(deferred_enable, cubes, alias_registry)
    resolved_disables = _resolve_disable_entries(deferred_disable, cubes, alias_registry)
    _validate_activation_conflicts(resolved_enables, resolved_disables)
    for resolved in resolved_enables:
        add_enabled(plan, resolved.alias, resolved.node_key, resolved.line)

    disabled_nodes: set[str] = set()
    effective_disabled = _effective_disabled_nodes(
        cubes=cubes,
        resolved_enables=resolved_enables,
        resolved_disables=resolved_disables,
    )
    for disabled_entry in effective_disabled:
        disable_node_passthrough(
            cubes[disabled_entry.alias],
            disabled_entry.alias,
            disabled_entry.node_key,
        )
        disabled_nodes.add(disabled_entry.node_key)
        add_disabled(
            plan,
            disabled_entry.alias,
            disabled_entry.node_key,
            disabled_entry.source_line,
            reason=disabled_entry.reason,
        )

    def record_inferred_set(cube_name: str, node_key: str, input_key: str, value: Any) -> None:
        """Record an inheritance-inferred value in the spawn plan."""

        add_set(plan, cube_name, node_key, input_key, value, None, "inferred")

    apply_plan_inheritance(cubes, order, disabled_nodes, on_set=record_inferred_set)

    for wildcard_entry in deferred_wildcards:
        _apply_wildcard_set(wildcard_entry, aliases, cubes, alias_registry, plan, seed_provider)

    return plan


def _add_flavor_sets(
    plan: SpawnPlan,
    alias: str,
    raw_cube: CubeDocument,
    flavor_values: dict[str, Any],
) -> None:
    """Record flavor-applied values in the spawn plan before explicit sets."""

    controls = raw_cube.get("surface", {}).get("controls", [])
    for control in controls:
        if not isinstance(control, dict):
            continue
        control_id = str(control.get("control_id") or "")
        if control_id not in flavor_values:
            continue
        symbol = str(control.get("symbol") or "")
        input_name = str(control.get("input_name") or "")
        if not symbol or not input_name:
            continue
        node_key = f"{alias}.{symbol}"
        add_set(
            plan,
            alias,
            node_key,
            input_name,
            flavor_values[control_id],
            None,
            "flavor",
        )


def _apply_connect(
    stmt: ConnectStmt,
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    plan: SpawnPlan,
) -> None:
    """Apply one semantic connect statement to materialized cubes and the plan."""

    from_ref = _expand_path_ref(stmt.from_ref)
    to_ref = _expand_path_ref(stmt.to_ref)
    if len(from_ref) != len(to_ref):
        raise RuntimeError(
            f"Line {stmt.line}: Connect ranges mismatch: {stmt.from_ref} -> {stmt.to_ref}"
        )

    for left, right in zip(from_ref, to_ref, strict=True):
        from_parts = left.parts
        to_parts = right.parts
        if len(from_parts) < 2:
            raise RuntimeError(
                f"Line {stmt.line}: Connect source must include an output: '{'.'.join(from_parts)}'"
            )
        if len(to_parts) < 2:
            raise RuntimeError(
                f"Line {stmt.line}: Connect target must include an input: '{'.'.join(to_parts)}'"
            )

        from_cube = alias_registry.resolve(
            from_parts[0],
            line=stmt.line,
            context="connect source",
        )
        to_cube = alias_registry.resolve(
            to_parts[0],
            line=stmt.line,
            context="connect target",
        )

        from_binding, from_node, _input_key = resolve_connection_mapping(
            require_mapping(cubes[from_cube], "outputs", from_cube),
            from_cube,
            from_parts[1:],
            "output",
        )
        to_binding, to_targets, input_key = resolve_connection_mapping(
            require_mapping(cubes[to_cube], "inputs", to_cube),
            to_cube,
            to_parts[1:],
            "input",
        )
        try:
            connect_binding_target(
                cubes[to_cube],
                to_cube,
                to_targets,
                input_key,
                from_node,
                source_alias=from_cube,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"Line {stmt.line}: {exc}") from exc

        add_connection(
            plan,
            from_cube,
            from_binding,
            to_cube,
            to_binding,
            input_key,
            stmt.line,
        )


def _apply_explicit_set(
    entry: _ExplicitSet,
    aliases: dict[str, Any],
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    plan: SpawnPlan,
    seed_provider: SeedProvider,
) -> None:
    """Apply one deferred explicit set statement to cubes and the plan."""

    for ref in _expand_path_ref(entry.target):
        parts = ref.parts
        if len(parts) == 2:
            _apply_node_link(entry, cubes, alias_registry, plan, ref)
            continue
        if len(parts) < 3:
            raise RuntimeError(f"Line {entry.line}: Set target must include cube, node, and input.")

        cube_name = alias_registry.resolve(parts[0], line=entry.line, context="set")
        node_name = ".".join(parts[1:-1])
        matching_node, input_key = resolve_input_key(
            cubes[cube_name], cube_name, node_name, parts[-1]
        )
        value = _eval_expr(
            entry.value,
            aliases,
            cubes,
            alias_registry,
            entry.line,
            seed_provider,
        )
        apply_set(cubes[cube_name], cube_name, matching_node, input_key, value)
        add_set(plan, cube_name, matching_node, input_key, value, entry.line, "explicit")


def _apply_node_link(
    entry: _ExplicitSet,
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    plan: SpawnPlan,
    target: PathRef,
) -> None:
    """Apply one deferred whole-node link statement to the spawn plan."""

    if not isinstance(entry.value, DottedRefExpr):
        raise RuntimeError(f"Line {entry.line}: Node-link value must be a source node reference.")
    source_ref = entry.value.ref
    if source_ref.range_expr is not None:
        raise RuntimeError(f"Line {entry.line}: Range references are not valid here.")
    if len(source_ref.parts) != 2:
        raise RuntimeError(
            f"Line {entry.line}: Node-link value must be cube.node "
            f"(got '{'.'.join(source_ref.parts)}')."
        )

    target_alias = alias_registry.resolve(
        target.parts[0],
        line=entry.line,
        context="node link",
    )
    target_node_name = target.parts[1]
    source_alias = alias_registry.resolve(
        source_ref.parts[0],
        line=entry.line,
        context="node link",
    )
    source_node_name = source_ref.parts[1]
    source_node_key = resolve_node_key(
        cubes[source_alias],
        source_alias,
        source_node_name,
    )
    target_node_key = resolve_node_key(
        cubes[target_alias],
        target_alias,
        target_node_name,
    )
    source_node = require_mapping(cubes[source_alias], "nodes", source_alias).get(source_node_key)
    target_node = require_mapping(cubes[target_alias], "nodes", target_alias).get(target_node_key)
    if not isinstance(source_node, dict) or not isinstance(target_node, dict):
        raise RuntimeError(f"Line {entry.line}: Node-link endpoint is not a valid node.")
    try:
        validate_node_link_compatibility(
            source_node=source_node,
            source_alias=source_alias,
            source_node_key=source_node_key,
            target_node=target_node,
            target_alias=target_alias,
            target_node_key=target_node_key,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Line {entry.line}: {exc}") from exc
    add_node_link(
        plan,
        source_alias,
        source_node_key,
        target_alias,
        target_node_key,
        entry.line,
    )


def _apply_wildcard_set(
    entry: _WildcardSet,
    aliases: dict[str, Any],
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    plan: SpawnPlan,
    seed_provider: SeedProvider,
) -> None:
    """Apply one wildcard set to matching node inputs across all cubes."""

    target = entry.target
    value = _eval_expr(
        entry.value,
        aliases,
        cubes,
        alias_registry,
        entry.line,
        seed_provider,
    )

    resolved_matches: list[tuple[str, str, str]] = []
    for cube_name, cube in cubes.items():
        for node_key, node in cube["nodes"].items():
            if not isinstance(node, dict):
                continue
            if target.cls != "*" and node.get("class_type") != target.cls:
                continue
            input_key = _resolve_wildcard_input(cube, cube_name, node_key, target.input_key)
            if input_key is None:
                continue
            resolved_matches.append((cube_name, node_key, input_key))

    matched_keys = {input_key for _, _, input_key in resolved_matches}
    if len(matched_keys) > 1:
        choices = ", ".join(sorted(matched_keys))
        raise RuntimeError(
            f"Line {entry.line}: Wildcard input label '{target.input_key}' is ambiguous: {choices}."
        )

    for cube_name, node_key, input_key in resolved_matches:
        node = cubes[cube_name]["nodes"][node_key]
        if not isinstance(node, dict):
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            raise RuntimeError(f"Line {entry.line}: Node '{node_key}' has invalid inputs.")
        inputs[input_key] = value
        add_set(
            plan,
            cube_name,
            node_key,
            input_key,
            value,
            entry.line,
            "wildcard",
        )


def _resolve_wildcard_input(
    cube: CubeGraph,
    alias: str,
    node_key: str,
    input_label: str,
) -> str | None:
    """Resolve a wildcard input label against one candidate node."""

    return resolve_input_label_for_node(cube, alias, node_key, input_label)


def _resolve_disable(
    entry: _Disable,
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    target: PathRef,
) -> _ResolvedDisable:
    """Resolve a disable target to an alias-qualified materialized node key."""

    parts = target.parts
    if len(parts) < 2:
        raise RuntimeError(f"Line {entry.line}: Disable target missing node reference.")
    cube_name = alias_registry.resolve(parts[0], line=entry.line, context="disable")
    node_name = ".".join(parts[1:])
    return _ResolvedDisable(
        alias=cube_name,
        node_key=resolve_node_key(cubes[cube_name], cube_name, node_name),
        line=entry.line,
    )


def _resolve_enable(
    entry: _Enable,
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    target: PathRef,
) -> _ResolvedEnable:
    """Resolve an enable target to an alias-qualified materialized node key."""

    parts = target.parts
    if len(parts) < 2:
        raise RuntimeError(f"Line {entry.line}: Enable target missing node reference.")
    cube_name = alias_registry.resolve(parts[0], line=entry.line, context="enable")
    node_name = ".".join(parts[1:])
    return _ResolvedEnable(
        alias=cube_name,
        node_key=resolve_node_key(cubes[cube_name], cube_name, node_name),
        line=entry.line,
    )


def _resolve_enable_entries(
    entries: list[_Enable],
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
) -> list[_ResolvedEnable]:
    """Resolve all deferred enable statements to canonical node keys."""

    resolved: list[_ResolvedEnable] = []
    for entry in entries:
        for target in _expand_path_ref(entry.target):
            resolved.append(_resolve_enable(entry, cubes, alias_registry, target))
    return resolved


def _resolve_disable_entries(
    entries: list[_Disable],
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
) -> list[_ResolvedDisable]:
    """Resolve all deferred disable statements to canonical node keys."""

    resolved: list[_ResolvedDisable] = []
    for entry in entries:
        for target in _expand_path_ref(entry.target):
            resolved.append(_resolve_disable(entry, cubes, alias_registry, target))
    return resolved


def _validate_activation_conflicts(
    enables: list[_ResolvedEnable],
    disables: list[_ResolvedDisable],
) -> None:
    """Reject recipes that enable and disable the same materialized node."""

    enabled_lines = {entry.node_key: entry.line for entry in enables}
    for disable_entry in disables:
        enable_line = enabled_lines.get(disable_entry.node_key)
        if enable_line is None:
            continue
        raise RuntimeError(
            f"Node '{disable_entry.node_key}' is both enabled and disabled "
            f"(enable line {enable_line}, disable line {disable_entry.line})."
        )


def _effective_disabled_nodes(
    *,
    cubes: CubeGraphByAlias,
    resolved_enables: list[_ResolvedEnable],
    resolved_disables: list[_ResolvedDisable],
) -> list[_EffectiveDisabled]:
    """Return disabled nodes from authored bypass defaults and explicit disables."""

    enabled_node_keys = {entry.node_key for entry in resolved_enables}
    disabled_by_key: dict[str, _EffectiveDisabled] = {}
    for alias, cube in cubes.items():
        nodes = require_mapping(cube, "nodes", alias)
        for node_key, node in nodes.items():
            if not isinstance(node, dict):
                raise RuntimeError(f"Node '{node_key}' in cube '{alias}' is invalid.")
            if node_key in enabled_node_keys:
                continue
            if _is_authored_bypass_mode(node.get("mode")):
                disabled_by_key[node_key] = _EffectiveDisabled(
                    alias=alias,
                    node_key=node_key,
                    source_line=None,
                    reason="authored-bypass",
                )

    for entry in resolved_disables:
        disabled_by_key[entry.node_key] = _EffectiveDisabled(
            alias=entry.alias,
            node_key=entry.node_key,
            source_line=entry.line,
            reason="explicit",
        )
    return list(disabled_by_key.values())


def _is_authored_bypass_mode(value: object) -> bool:
    """Return whether a LiteGraph node mode represents authored bypass."""

    return isinstance(value, int) and not isinstance(value, bool) and value == 4


def _expand_path_ref(ref: PathRef) -> list[PathRef]:
    """Expand an optional alias range into concrete path references."""

    if ref.range_expr is None:
        return [ref]
    return _expand_range(ref.parts, ref.range_expr)


def _expand_range(parts: list[str], range_expr: RangeExpr) -> list[PathRef]:
    """Expand the first path segment across an inclusive numeric range."""

    if not parts:
        return []
    expanded: list[PathRef] = []
    for i in range(range_expr.start, range_expr.end + 1):
        expanded.append(PathRef(parts=[f"{parts[0]}{i}"] + parts[1:]))
    return expanded


def _eval_expr(
    expr: Expr,
    aliases: dict[str, Any],
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    line: int,
    seed_provider: SeedProvider,
) -> Any:
    """Evaluate a Sugar expression against aliases and materialized cube inputs."""

    if isinstance(expr, LiteralExpr):
        value = expr.value
        if isinstance(value, str) and "\n" in value:
            return _normalize_multiline_string(value)
        return value
    if isinstance(expr, NameExpr):
        if expr.name not in aliases:
            raise RuntimeError(f"Line {line}: Unknown variable '{expr.name}'.")
        return aliases[expr.name]
    if isinstance(expr, RandomExpr):
        return seed_provider()
    if isinstance(expr, DottedRefExpr):
        return _resolve_dotted_ref(expr.ref, cubes, alias_registry, line)
    if isinstance(expr, UnaryExpr):
        value = _eval_expr(
            expr.operand,
            aliases,
            cubes,
            alias_registry,
            line,
            seed_provider,
        )
        if expr.op == "-":
            _ensure_number(value, line, "unary '-' expression")
            return -value
        raise RuntimeError(f"Line {line}: Unsupported unary operator '{expr.op}'.")
    if isinstance(expr, BinaryExpr):
        left = _eval_expr(
            expr.left,
            aliases,
            cubes,
            alias_registry,
            line,
            seed_provider,
        )
        right = _eval_expr(
            expr.right,
            aliases,
            cubes,
            alias_registry,
            line,
            seed_provider,
        )
        return _apply_binary(expr.op, left, right, line)
    raise RuntimeError(f"Line {line}: Unsupported expression '{expr}'.")


def _resolve_dotted_ref(
    ref: PathRef,
    cubes: CubeGraphByAlias,
    alias_registry: AliasRegistry,
    line: int,
) -> Any:
    """Resolve a `cube.node.input` expression to the current input value."""

    if ref.range_expr is not None:
        raise RuntimeError(f"Line {line}: Range references are not valid here.")
    if len(ref.parts) != 3:
        raise RuntimeError(
            f"Line {line}: Reference must be cube.node.input (got '{'.'.join(ref.parts)}')."
        )
    cube_name = alias_registry.resolve(ref.parts[0], line=line, context="reference")
    node_name = ref.parts[1]
    node_key, input_key = resolve_input_key(cubes[cube_name], cube_name, node_name, ref.parts[2])
    nodes = require_mapping(cubes[cube_name], "nodes", cube_name)
    node = nodes.get(node_key, {})
    if not isinstance(node, dict):
        raise RuntimeError(f"Line {line}: Referenced node '{node_name}' is invalid.")
    inputs = node.get("inputs", {})
    if input_key not in inputs:
        raise RuntimeError(
            f"Line {line}: Referenced input '{input_key}' not found on '{cube_name}.{node_name}'."
        )
    return inputs[input_key]


def _ensure_number(value: Any, line: int, context: str) -> None:
    """Require a numeric expression operand for arithmetic evaluation."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Line {line}: Expected number for {context}.")


def _apply_binary(op: str, left: Any, right: Any, line: int) -> Any:
    """Apply a validated binary operator to two evaluated operands."""

    if op == "+":
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        _ensure_number(left, line, "'+' expression")
        _ensure_number(right, line, "'+' expression")
        return left + right
    if op == "-":
        _ensure_number(left, line, "'-' expression")
        _ensure_number(right, line, "'-' expression")
        return left - right
    if op == "*":
        _ensure_number(left, line, "'*' expression")
        _ensure_number(right, line, "'*' expression")
        return left * right
    if op == "/":
        _ensure_number(left, line, "'/' expression")
        _ensure_number(right, line, "'/' expression")
        return left / right
    raise RuntimeError(f"Line {line}: Unsupported operator '{op}'.")


def _normalize_multiline_string(value: str) -> str:
    """Trim surrounding blank lines and common edge whitespace from DSL strings."""

    lines = value.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.strip() for line in lines)
