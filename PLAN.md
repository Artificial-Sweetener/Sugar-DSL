# Plan: Live-Definition-Aware Sugar Compilation

## Purpose

Make Sugar-DSL compile old SugarCube artifacts safely against the current live
ComfyUI node definitions.

The previous migration moved Sugar-DSL execution from SugarSubstitute into
Substitute BackEnd. This plan covers the next behavior slice: Sugar-DSL must use
live Comfy node definitions during resolution, materialization, and prompt
generation so node-pack updates do not create prompts that Comfy rejects.

## Repositories

- Sugar-DSL: `E:\devprojects\Sugar-DSL`
- SugarSubstitute frontend: `E:\devprojects\sugarsubstitute`
- Substitute BackEnd custom node: `E:\comfyui\custom_nodes\substitute-backend`
- SugarCubes reference/custom-node repo: `E:\comfyui\custom_nodes\sugarcubes`

SugarCubes is a reference repo for cube artifact shape and authoring behavior.
Do not change SugarCubes unless implementation proves the cube artifact contract
itself must change.

## Decisions Already Made

1. Sugar-DSL is the execution and compilation owner.
2. SugarSubstitute is the Sugar script authoring owner.
3. Substitute BackEnd is the host that imports and invokes Sugar-DSL.
4. SugarSubstitute must not import or execute `sugar.*`.
5. SugarSubstitute remains responsible for:
   - Sugar Codec script authoring
   - rendering UI fields from live Comfy definitions
   - authoring override lines for fields not present in an old cube artifact
   - app-specific final prompt preparation such as CSV wildcard normalization
     and picker-default hydration
6. The frontend prompt post-processing retained during the migration belongs to
   Substitute. It is not temporary Sugar-DSL behavior.
7. Missing live-only node inputs should materialize from the current Comfy widget
   default when Comfy declares one.
8. Substitute may author Sugar override lines for live-defined fields that are
   absent from the cube artifact.
9. Sugar-DSL should accept those override lines when the target field exists in
   the live Comfy node definition.
10. Sugar-DSL must not invent arbitrary values for required widget inputs with
    no safe live default.
11. Sugar-DSL must not emit stale inputs that the current live Comfy definition
    no longer declares.
12. Sugar-DSL compiler core must not import ComfyUI runtime globals. Sugar-DSL
    runtime adapters may talk to ComfyUI HTTP endpoints or read ComfyUI runtime
    registries when explicitly used by a caller or host.
13. Sugar-DSL owns live Comfy definition normalization. Substitute BackEnd only
    constructs a Sugar-owned runtime provider and passes it into Sugar-DSL.
14. Keep this behavior slice separate from the migration commit.

## Desired Input Priority

For every node input in the final executable prompt, Sugar-DSL should resolve
values in this order:

```text
1. Sugar script override
2. cube-authored value
3. current Comfy widget default
4. omit when the input is optional and omission is valid
5. structured compile failure when a public literal widget is required and no
   safe value exists
6. omit missing graph sockets and expanded subgraph internals when Sugar cannot
   safely synthesize a value or connection
```

This priority applies equally to inputs that existed when the cube was authored
and inputs added later by an updated node pack.

## Target Behavior

### Live-Only Explicit Override

If an old cube has a node `MyNode` and the current Comfy definition for that node
class declares a new widget input named `new_widget`, Substitute may emit:

```text
set Demo.MyNode.new_widget = "chosen value"
```

Sugar-DSL should accept this when:

- `Demo` is a valid cube alias
- `MyNode` resolves to a cube node label/key
- the node's current live Comfy definition declares `new_widget`

Sugar-DSL should still reject:

- unknown aliases
- unknown nodes
- unknown fields absent from cube surface, cube implementation, subgraph
  interfaces, and live definitions

### Live-Only Missing Input

If the Sugar script does not mention `new_widget`, and the old cube does not have
an authored value for it, Sugar-DSL should materialize the current Comfy widget
default.

### Stale Cube Input

If the old cube includes an input that the current live Comfy definition no
longer declares, Sugar-DSL should prune that input from the final API prompt.

This prevents Comfy hard failures from totally undeclared inputs.

If a current Comfy node serializes grouped UI inputs with names such as
`values.a`, Sugar-DSL should preserve that authored prompt socket name when the
live definition declares the containing autogrow group `values`. Current Comfy
validation for `ComfyMathExpression` reports missing input `values.a` when Sugar
emits bare `a`, so Sugar-DSL must not rewrite grouped autogrow names to concrete
bare names.

### Required Widget Input With No Default

If the current live Comfy definition declares a required input that:

- is not set by Sugar script
- is not present in the cube-authored value map
- has no Comfy widget default
- cannot be safely generated
- represents a public literal widget field rather than a graph socket or
  expanded subgraph helper input

Sugar-DSL should fail before queueing with a structured, actionable compile
error.

Required graph sockets and expanded subgraph helper inputs without defaults are
not materialized from live metadata alone. Sugar omits them because it cannot
invent a connection or invisible helper value safely. This preserves old cube
behavior and avoids treating live runtime internals as newly authored Sugar
fields.

## Non-Goals

1. Do not move Substitute's CSV wildcard normalization or picker-default
   hydration into Sugar-DSL.
2. Do not make Sugar-DSL compiler core import ComfyUI. Sugar-DSL runtime
   adapters may integrate with ComfyUI when explicitly configured.
3. Do not make SugarSubstitute import Sugar-DSL again.
4. Do not add backend-local string parsing of Sugar scripts to rediscover
   references. Sugar-DSL remains the parser/compiler owner.
5. Do not silently accept unknown fields.
6. Do not invent model picker values without a real default from Comfy metadata.
7. Do not attempt to recover when a node class no longer exists.
8. Do not reconnect new required linked inputs without authored or inferred
   source information.
9. Do not change persisted cube artifact formats unless tests prove the current
   format cannot represent the required behavior.

## Architecture Overview

Add a live node definition boundary owned by Sugar-DSL and supplied by
Sugar-owned runtime providers.

```text
SugarSubstitute
  authors Sugar text from cube data + live Comfy UI definitions
  posts Sugar text to Substitute BackEnd

Substitute BackEnd
  selects the Sugar-owned in-process Comfy provider
  calls Sugar-DSL compile API with cube resolver + live definition provider

Sugar-DSL
  parses Sugar text
  resolves targets against cube data and live definitions
  materializes missing live inputs from Comfy defaults
  prunes stale inputs during codegen
  returns prompt/workflow artifacts
```

## Dependency Placement

Sugar-DSL should be installed only where compilation runs:

1. Keep SugarSubstitute's root `requirements.txt` free of `sugar-dsl`.
2. Keep Substitute BackEnd's `pyproject.toml` free of a pinned `sugar-dsl`
   dependency during this unreleased phase.
3. Keep SugarSubstitute tests enforcing that no frontend runtime module imports
   `sugar.*`.
4. Install Sugar-DSL editable into the ComfyUI backend environment used by
   Substitute BackEnd:

```powershell
cd E:\ComfyUI
.\venv\Scripts\python.exe -m pip uninstall -y sugar-dsl
.\venv\Scripts\python.exe -m pip install -e E:\devprojects\Sugar-DSL
```

5. Do not pin a Sugar-DSL version in Substitute BackEnd for this unreleased
   phase. The backend consumes the local editable package while the compile
   contract is still changing.
6. Do not vendor Sugar-DSL source into Substitute BackEnd.

## Sugar-DSL Implementation

### New Public Contract

Create typed live-definition models in Sugar-DSL at:

```text
E:\devprojects\Sugar-DSL\sugar\compiler\live_definitions.py
```

The module should define:

```python
class LiveNodeDefinitionProvider(Protocol):
    def definition_for(self, class_type: str) -> LiveNodeDefinition | None:
        ...
```

Use these domain models:

```python
@dataclass(frozen=True, slots=True)
class LiveNodeInputDefinition:
    name: str
    value_type: str
    required: bool
    default: object | None
    has_default: bool
    choices: tuple[object, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveNodeDefinition:
    class_type: str
    inputs: Mapping[str, LiveNodeInputDefinition]
```

Use `object` only at raw external metadata boundaries. Narrow values before core
logic relies on them. Do not use `Any` in core APIs unless there is no accurate
type alternative and the reason is explicit.

Do not place these models in `sugar.catalog`. The catalog layer owns cube
discovery, cube document validation, flavor loading, and asset indexing. Live
Comfy node definitions are compile-time metadata supplied by a host adapter, so
the protocol belongs with compiler semantics. Sugar-DSL still must not import
ComfyUI or any Substitute BackEnd code.

### Public API Change

Extend Sugar-DSL compile entry points to accept the provider:

- `sugar.api.builder.build_workflow(...)`
- `sugar.api.builder.build_workflow_from_text(...)`
- `sugar.api.builder.build_comfy_artifacts(...)`
- `sugar.api.builder.build_comfy_artifacts_from_text(...)`

New parameter:

```python
live_node_definition_provider: LiveNodeDefinitionProvider | None = None
```

Thread this parameter through:

- `build_workflow(...)`
- `build_workflow_from_text(...)`
- `build_comfy_artifacts(...)`
- `build_comfy_artifacts_from_text(...)`
- internal `_build_workflow_from_script_text(...)`
- internal `_compile_workflow_from_script_text(...)`
- internal `_compile_comfy_artifacts_from_script_text(...)`
- `analyze_script(...)`
- `materialize_recipe(...)`
- `recipe_to_api_prompt(...)`

The provider is runtime metadata and must not be serialized into Sugar scripts,
cube artifacts, persisted recipes, `MaterializedRecipe`, or public spawn-plan
JSON. Pass the provider explicitly into `analyze_script(...)`,
`materialize_recipe(...)`, and `recipe_to_api_prompt(...)`. `materialize_recipe`
may consume the provider to apply live defaults, but the returned recipe should
remain serializable with the same stable data contract it has today.

Maintain backwards compatibility at the public API boundary by making the
provider optional. When it is absent, existing standalone Sugar-DSL behavior
should remain unchanged.

### Resolver Changes

Update these files:

- `sugar/compiler/analyzer.py`
- `sugar/compiler/resolver.py`
- `sugar/compiler/recipe.py`

Current behavior resolves input keys against cube-authored structures. Extend the
resolution path so a node input can resolve when it exists in the live definition
for the node's `class_type`.

Specific resolution targets to update:

1. Explicit `set Alias.Node.input = value` target resolution in analyzer code.
2. Wildcard field resolution in analyzer/resolver code.
3. Input-label resolution helpers in `sugar/compiler/resolver.py`.
4. Dotted-reference behavior. References to live-only fields should resolve
   only after materialization has a real value from script, cube data, or a live
   default. A live declaration alone is not a readable value.

Resolution order should remain deterministic:

1. cube surface controls
2. subgraph interfaces
3. cube implementation input bindings
4. cube-authored node inputs
5. live Comfy node definition inputs

Preserve existing error behavior for unknown aliases, unknown nodes, ambiguous
labels, and unknown fields. Add live-definition context to unknown-field error
messages when useful:

```text
Input 'new_widget' is not declared by cube node 'Demo.MyNode' or live class 'SomeNodeClass'.
```

### Materialization Changes

Update:

- `sugar/compiler/input_materialization.py`

When materializing each node:

1. Start with cube-authored inputs.
2. Apply Sugar script overrides.
3. Look up the live definition for the node class.
4. Add live-defined inputs missing from the materialized map when a safe default
   exists.
5. Do not add missing optional inputs when Comfy accepts omission and no default
   is declared.
6. Fail for missing required public literal widgets with no safe value.
7. Omit missing required graph sockets and expanded subgraph helper inputs when
   no safe value exists.

Reuse the existing materialization helpers instead of creating a parallel
default parser. The implementation should either normalize live input metadata
into the same compact field-spec shape currently consumed by:

- `iter_definition_input_fields(...)`
- `input_type_name(...)`
- `default_from_field_spec(...)`
- `is_randomizable_seed_input(...)`
- `materialize_node_inputs(...)`

or extract a single typed input-spec parser that both cube-embedded definitions
and live definitions use. There must be one source of truth for default
extraction, combo/list handling, optional detection, and seed-like behavior.

Default handling rules:

- If Comfy metadata declares a default, use that exact default.
- If the input is a seed-like integer and the system already has a deterministic
  Sugar seed path for similar seed fields, use the existing seed provider.
- If the input is a combo/list and Comfy metadata declares a default, use that
  default.
- If the input is a combo/list with choices but no declared default, do not pick
  the first choice unless Comfy itself clearly treats it as the widget default.
- Do not create paths, model names, booleans, strings, numeric values, graph
  connections, or internal helper values from type alone.

Structured failure should include:

- cube alias
- cube id
- node key or label
- node class type
- input name
- reason

### Codegen Changes

Update:

- `sugar/compiler/codegen.py`

Before emitting a node's final `inputs` map:

1. Look up the live definition for the node class.
2. If a live definition exists, remove any input not declared by the live
   definition, whether the value is literal or linked.
3. Preserve literal and linked inputs that Comfy still declares.
4. Preserve grouped serialized inputs such as `values.a` when the live
   definition exposes the containing autogrow group `values`; do not rewrite
   them to bare names such as `a`.
5. Preserve existing behavior when no live definition exists.

This is the hard-failure prevention step. A stale cube-authored input should not
survive into the final API prompt when current Comfy no longer declares it.

Perform pruning after all script overrides, cube-authored values, inherited
values, inferred values, links, and live defaults have been applied, and before
the API prompt is returned to the backend. The UI workflow artifact should
continue to describe the authored cube graph according to existing behavior; the
live-definition pruning requirement is for the executable API prompt.

### Error Types

Create a typed compiler error boundary for new live-definition failures in:

```text
E:\devprojects\Sugar-DSL\sugar\compiler\errors.py
```

Sugar-DSL currently uses `RuntimeError` broadly for compiler failures. Preserve
public exception compatibility by making the new base compiler error subclass
`RuntimeError`, then use that typed subclass for live-definition failures. Do not
add unstructured `RuntimeError` failures for new live-definition behavior.

The error should expose:

- stable machine-readable code
- human-readable message
- cube alias
- cube id when available
- node key or label
- node class type
- input name when applicable
- original exception context when caused by unexpected adapter/provider failure

The backend route should be able to map these failures to:

```text
sugar-compile-failed
sugar-live-definition-missing
sugar-live-default-missing
sugar-live-input-invalid
```

Use `sugar-compile-failed` for generic compiler failures that do not match the
specific live-definition cases. Use the live-specific codes for expected
live-definition failures so SugarSubstitute can present actionable messages
without parsing exception text.

## Substitute BackEnd Implementation

### Provider Adapter

Superseded by remediation.

Do not add or keep a backend-owned live-definition normalization adapter.
Substitute BackEnd uses Sugar-DSL's `ComfyRegistryLiveNodeDefinitionProvider`.

### Comfy Definition Source

Use Sugar-DSL's in-process provider as the backend source of truth. The provider
is implemented in Sugar-DSL and lazily reads:

```python
nodes.NODE_CLASS_MAPPINGS
```

For each requested class type, call:

```python
nodes.NODE_CLASS_MAPPINGS[class_type].INPUT_TYPES()
```

This mirrors ComfyUI's `/object_info` implementation in `E:\ComfyUI\server.py`,
where `node_info(...)` reads `nodes.NODE_CLASS_MAPPINGS[node_class]`, calls
`INPUT_TYPES()`, and derives `input_order` from the returned sections. Do not
call Comfy HTTP from Substitute BackEnd for this data when running inside the
same Comfy process.

Implement one Sugar-DSL-owned source reader. Do not duplicate frontend
object-info parsing and do not duplicate Sugar-DSL normalization in
Substitute BackEnd.

If Comfy metadata shape differs from frontend object-info JSON, normalize it in
Sugar-DSL runtime before passing it to compiler core.

Tests should use fake node classes with `INPUT_TYPES()` and an injected registry
mapping. Tests must not import real custom node packs or require a live Comfy
process.

### Backend Compiler Wiring

Update:

```text
E:\comfyui\custom_nodes\substitute-backend\substitute_backend\features\sugar_compile\infrastructure\sugar_dsl_compiler.py
```

Pass the provider into:

```python
build_comfy_artifacts_from_text(
    script_text,
    output_dir=output_dir,
    cube_artifact_resolver=...,
    live_node_definition_provider=ComfyRegistryLiveNodeDefinitionProvider(...),
)
```

Keep Sugar-DSL imports lazy or isolated behind the compiler adapter so tests and
non-Sugar backend features remain usable if Sugar-DSL is not installed.

### Capabilities

Expose live-definition support through the existing versioned `sugarCompile`
capability response:

```json
{
  "sugarCompile": {
    "schemaVersion": 1,
    "available": true,
    "compileRoute": "/substitute/v1/sugar/compile",
    "liveNodeDefinitions": true
  }
}
```

SugarSubstitute does not need to branch behavior on this field for the
unreleased first pass. The field exists so diagnostics, smoke tests, and future
mixed-version handling can verify that backend Sugar compilation is
live-definition-aware.

## SugarSubstitute Implementation

SugarSubstitute should remain mostly unchanged. The current Sugar Codec iterates
`nodes[*].inputs` from the stripped buffers and writes `set` lines for those
entries; it does not need cube schema authority to serialize a field already
present in the buffer. The parser also accepts input `set` lines for known
aliases and writes them back into the node `inputs` map.

Concrete files to inspect first:

```text
E:\devprojects\sugarsubstitute\substitute\domain\recipes\sugar_codec.py
E:\devprojects\sugarsubstitute\substitute\application\recipes\workflow_export_service.py
E:\devprojects\sugarsubstitute\substitute\application\recipes\sugar_label_resolution.py
E:\devprojects\sugarsubstitute\substitute\application\ports\node_definitions.py
E:\devprojects\sugarsubstitute\substitute\infrastructure\external\comfy_object_info_client.py
```

Known live-definition support already exists in SugarSubstitute through the
`NodeDefinitionGateway` boundary and related editor/projection services. Reuse
that existing boundary for authoring checks. Do not introduce a second live node
definition source inside Sugar Codec.

Verify and test that it can author override lines for live-only fields:

```text
set Demo.MyNode.new_widget = "chosen value"
```

Required frontend checks:

1. Add characterization coverage proving Sugar Codec serializes a node input
   that is present in the buffer but absent from the cube artifact definitions.
2. Add parser coverage proving a `set Alias.Node.live_only = value` line is
   preserved in the parsed buffer for a known alias/node.
3. Field rows/widgets sourced from live Comfy definitions can produce override
   lines.
4. SugarSubstitute continues posting the full script to
   `/substitute/v1/sugar/compile`.
5. SugarSubstitute still does not import `sugar.*`.
6. `WorkflowExportService` keeps Substitute-owned final prompt preparation:
   - `normalize_csv_wildcard_nodes`
   - `hydrate_prompt_picker_defaults`

Sugar Codec must not gain schema validation that rejects live-only fields. If a
higher-level editor/projection authoring path blocks live-only fields before
they enter the buffer, fix that path by using the existing `NodeDefinitionGateway`
data to recognize current live fields.

The frontend should still send Sugar text to Substitute BackEnd unchanged. It
should not pre-materialize live defaults for missing inputs merely to compensate
for old cubes; missing live default materialization belongs to Sugar-DSL during
backend compilation. SugarSubstitute may author explicit override lines for
live-only fields when the user changes those fields.

## SugarCubes Implementation

No planned code changes.

Use SugarCubes only to confirm:

1. Loaded cube artifacts include cube-authored node inputs and class types.
2. Old cube artifacts may lack fields that current live node definitions now
   declare.
3. Cube artifacts should remain authored graph/default/link carriers, not the
   final authority for every live node input.

## Test Plan

### Sugar-DSL Tests

Add tests at the narrowest useful compiler level first, then integration tests
through `build_comfy_artifacts_from_text`.

Create or update these test files:

```text
E:\devprojects\Sugar-DSL\tests\test_live_node_definitions.py
E:\devprojects\Sugar-DSL\tests\test_live_input_materialization.py
```

Required tests:

1. Explicit override to a live-only node input succeeds.
2. Explicit override to a field absent from cube and live definition still
   fails.
3. Missing live-only input uses Comfy's live widget default.
4. Sugar script override wins over cube-authored value.
5. Cube-authored value wins over live default when no script override exists.
6. Required public literal widget without safe default fails before
   codegen/queue.
7. Optional live input without default is omitted when omission is valid.
8. Stale cube-authored input is pruned from final API prompt.
9. Existing compile behavior remains unchanged when no live provider is supplied.
10. Missing required graph socket without safe default is omitted.
11. Missing required expanded subgraph helper input without safe default is
    omitted.
12. Grouped autogrow inputs such as `values.a` are preserved when the live
    definition declares the autogrow group, instead of being pruned or rewritten
    to bare names.
13. Repeated aliases and version-pinned artifacts still resolve deterministically
    with a live provider.
14. Subgraph wrapper expansion still works with live definitions.
15. Seed-like live inputs use the existing seed provider when allowed.

Use small in-memory cube payloads and fake live definition providers. Do not
depend on a live Comfy process for Sugar-DSL tests.

### Substitute BackEnd Tests

Create or update this test file:

```text
E:\comfyui\custom_nodes\substitute-backend\tests\test_sugar_live_node_definitions.py
```

Required tests:

1. Backend adapter converts simple Comfy required input metadata into
   `LiveNodeInputDefinition`.
2. Backend adapter converts optional input metadata.
3. Backend adapter preserves Comfy widget defaults.
4. Backend adapter handles combo/list choices and default values.
5. Backend adapter returns `None` for unknown class types.
6. Backend compiler passes `live_node_definition_provider` into Sugar-DSL.
7. Missing Sugar-DSL still returns the existing unavailable capability/503 path.
8. Compile route maps live-definition compile failures to structured backend
   errors.
9. Top-level capabilities include `sugarCompile.liveNodeDefinitions = true`
   when Sugar compilation is available.

Use fake Comfy node classes with `INPUT_TYPES()` rather than importing real
custom nodes in tests.

### SugarSubstitute Tests

Update these tests:

```text
E:\devprojects\sugarsubstitute\tests\test_backend_sugar_workflow_compiler.py
E:\devprojects\sugarsubstitute\tests\test_sugar_codec_*.py
E:\devprojects\sugarsubstitute\tests\test_workflow_export_service.py
```

Required tests:

1. SugarSubstitute can author an override line for a live field missing from the
   cube artifact.
2. Backend compile client still sends the full script text unchanged.
3. Static runtime package check confirms no `sugar.*` imports exist.
4. Existing `WorkflowExportService` CSV wildcard normalization still runs after
   backend compile.
5. Existing picker-default hydration still runs after backend compile.

Frontend code changes should be limited to the higher-level authoring path that
blocks live-defined fields, if such a block exists. Do not change Sugar Codec
when characterization tests prove it already serializes and parses live-only
input names correctly.

## Implementation Sequence

### Phase 0: Confirm Baseline

Status: complete.

Landing notes:

- Existing migration work was already present in SugarSubstitute and Substitute
  BackEnd worktrees; this slice built on those changes without reverting them.
- Confirmed SugarSubstitute `.venv` does not have `sugar-dsl` installed.
- Installed Sugar-DSL editable into the ComfyUI venv with
  `..\..\venv\Scripts\python.exe -m pip install -e E:\devprojects\Sugar-DSL`.
- Confirmed no pinned `sugar-dsl` dependency appears in SugarSubstitute
  `requirements.txt` or Substitute BackEnd `pyproject.toml`.

Completed items:

1. Verify the previous migration is committed or otherwise intentionally staged.
2. Run focused tests around current backend compile route and frontend client.
3. Confirm SugarSubstitute frontend venv does not have `sugar-dsl` installed.
4. Confirm backend/Comfy venv has Sugar-DSL installed editable.
5. Confirm SugarSubstitute root `requirements.txt` and Substitute BackEnd
   `pyproject.toml` remain free of a pinned `sugar-dsl` dependency.

### Phase 1: Sugar-DSL Contract And Characterization

Status: complete.

Landing notes:

- Added `sugar.compiler.live_definitions` with typed live node definition models
  and provider protocol.
- Added live-definition-aware regression tests in
  `tests/test_live_node_definitions.py`.
- Threaded the optional provider through the public builder APIs and compile
  orchestration.
- Focused verification completed:
  `.\.venv\Scripts\python.exe -m pytest tests\test_live_node_definitions.py -q`,
  `.\.venv\Scripts\python.exe -m pytest tests\test_compiler_contracts.py -q`,
  and `.\.venv\Scripts\mypy.exe --strict sugar tests\test_live_node_definitions.py`.

Completed items:

1. Add tests proving current behavior fails for live-only override without a live
   provider.
2. Add the live definition models and provider protocol.
3. Add optional provider parameters to public builder APIs.
4. Thread the provider through compile orchestration without changing behavior.
5. Run Sugar-DSL focused tests.

### Phase 2: Sugar-DSL Resolution

Status: complete.

Landing notes:

- Extended explicit set, wildcard set, and dotted-reference input resolution to
  consult live node definitions after cube-authored labels and inputs.
- Dotted references to live-only fields still require a materialized value; a
  declaration alone does not make the input readable.

Completed items:

1. Teach target resolution about live-defined node inputs.
2. Keep unknown-field failures strict.
3. Add tests for live-only explicit overrides and unknown live fields.
4. Run Sugar-DSL focused tests.

### Phase 3: Sugar-DSL Materialization

Status: complete.

Landing notes:

- Extended `sugar.compiler.input_materialization` so live inputs reuse the same
  field-spec default parser used by cube-embedded definitions.
- Added `SugarCompilerError` metadata for required public literal widgets with
  no safe value using code `sugar-live-default-missing`.
- Tightened missing-required behavior after manual smoke found an expanded
  subgraph helper input (`.__sg_...values`) being treated as a user-authored
  widget. Sugar now omits missing required graph sockets and expanded subgraph
  helper inputs when no safe value exists.
- Existing standalone behavior remains unchanged when no live provider is
  supplied.

Completed items:

1. Materialize missing live inputs from Comfy defaults.
2. Preserve script override and cube-authored priority.
3. Add structured failures for required public literal widgets with no safe
   default.
4. Add tests for defaults, optional omission, required widget failures, graph
   socket omission, and expanded subgraph helper omission.
5. Run Sugar-DSL focused tests.

### Phase 4: Sugar-DSL Codegen Pruning

Status: complete.

Landing notes:

- Added final API prompt pruning in `sugar.compiler.codegen` after
  materialization and resource optimization and before numeric prompt merge.
- Pruning is active only when a live definition exists for the node class; no
  provider preserves current behavior.
- Corrected grouped autogrow handling after trace logs showed
  `ComfyMathExpression` validation expects `values.a`, not bare `a`. Sugar now
  preserves links authored as `values.a` when the live prompt definition
  declares the containing autogrow group `values`.

Completed items:

1. Prune stale inputs absent from current live definitions.
2. Preserve grouped serialized autogrow input names that live definitions still
   declare through their containing group.
3. Preserve existing behavior when no live provider is supplied.
4. Add integration tests around final API prompt shape.
5. Run Sugar-DSL full gates.

### Phase 5: Substitute BackEnd Provider

Status: complete.

Landing notes:

- The initial backend-owned `ComfyNodeDefinitionProvider` was removed during
  remediation.
- `SugarDslWorkflowCompiler` now uses Sugar-DSL's
  `ComfyRegistryLiveNodeDefinitionProvider`.
- Mapped typed Sugar-DSL compiler errors into backend `SugarCompileError`
  responses while preserving stable live-definition error codes.
- Added `liveNodeDefinitions` to the versioned Sugar compile capability payload.
- Focused verification completed:
  `..\..\venv\Scripts\python.exe -m pytest tests\test_sugar_live_node_definitions.py tests\test_sugar_compile.py tests\test_capabilities_and_routes.py -q`
  and
  `..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend\features\sugar_compile tests\test_sugar_live_node_definitions.py`.

Completed items:

1. Add the Comfy live node definition adapter. Superseded by Sugar-owned
   provider remediation.
2. Add fake-node tests for metadata normalization. Moved to Sugar-DSL runtime
   tests.
3. Wire the provider into `SugarDslWorkflowCompiler`.
4. Add `live_node_definitions` support to `SugarCompileCapabilities` and
   `to_payload()`.
5. Add route/service tests for live compile behavior, capability payload, and
   error mapping.
6. Run Substitute BackEnd full gates.

### Phase 6: SugarSubstitute Authoring Verification

Status: complete.

Landing notes:

- Sugar Codec already serializes whatever active node inputs are present in the
  buffer and parses `set Alias.Node.live_only = value` back into node inputs.
- Added characterization coverage for live-only field serialization and parsing
  in `tests/test_sugar_codec.py`.
- Updated the backend compile client fixture to accept the backend's
  `liveNodeDefinitions` capability while keeping request posting unchanged.
- Focused verification completed:
  `.\.venv\Scripts\python.exe -m pytest tests\test_sugar_codec.py tests\test_backend_sugar_workflow_compiler.py tests\test_workflow_export_service.py -q`.
- SugarSubstitute full format, lint, strict mypy, and parallel tests pass.

Completed items:

1. Audit Sugar Codec authoring paths for filters that reject live-only fields.
2. Add or update tests proving live-only override lines can be authored.
3. Keep backend compile client request behavior unchanged.
4. Run SugarSubstitute full gates.

### Phase 7: Manual Smoke Test

Status: deferred.

Landing notes:

- Automated Sugar-DSL, Substitute BackEnd, and SugarSubstitute gates pass.
- Automated standalone Sugar-DSL tests now cover live-only overrides, live
  defaults, and stale input pruning with Sugar-owned providers.
- Manual GUI smoke with running ComfyUI and SugarSubstitute was not launched in
  this implementation pass. Run the listed steps before release validation.

Deferred release-validation items:

1. Start ComfyUI with Substitute BackEnd enabled.
2. Start SugarSubstitute.
3. Use a cube whose node class has a current live widget absent from the cube
   artifact.
4. Generate with no explicit override for that widget.
5. Confirm final prompt includes Comfy's widget default.
6. Change that widget in Substitute.
7. Confirm SugarSubstitute authors an override line for the live-only field.
8. Generate again.
9. Confirm final prompt uses the explicit override.
10. Use a cube containing an input removed from the current live node definition.
11. Confirm final prompt prunes the stale input.
12. Confirm no Comfy validation hard failure occurs.

## Verification Results

Completed:

- Sugar-DSL:
  - `.\.venv\Scripts\python.exe tools\add_license_headers.py`
  - `.\.venv\Scripts\ruff.exe format .`
  - `.\.venv\Scripts\ruff.exe check .`
  - `.\.venv\Scripts\mypy.exe --strict sugar tests`
  - `.\.venv\Scripts\python.exe -m pytest -n auto -q`
  - Follow-up smoke regression for expanded subgraph helper inputs:
    `.\.venv\Scripts\python.exe -m pytest tests\test_live_node_definitions.py -q`
  - Follow-up full regression after tightening missing-required policy:
    `.\.venv\Scripts\python.exe -m pytest -n auto -q` passed with
    `198 passed`.
  - Follow-up smoke regression for grouped autogrow prompt sockets:
    `.\.venv\Scripts\python.exe -m pytest tests\test_live_node_definitions.py -q`
  - Follow-up full regression after grouped-input handling:
    `.\.venv\Scripts\python.exe -m pytest -n auto -q` passed with
    `199 passed`.
- Direct compile smoke against
  `E:\comfyui\custom_nodes\sugarcubes\.sugarcubes\Artificial-Sweetener\Base-Cubes\Anima\Diffusion Upscale.cube@2.2.0`
  originally appeared to support emitting bare `a` and `b`, but live Comfy
  validation logs disproved that assumption.
- Follow-up regression for the running `046_untitled_workflow_text_to_image`
  failure showed SugarSubstitute and Substitute BackEnd were queueing bare `a`
  and `b`, while Comfy validation reported missing `values.a`. Sugar-DSL codegen
  now preserves grouped autogrow prompt sockets such as `values.a` and
  `values.b`.
- Direct compile regression now emits `ComfyMathExpression` inputs
  `expression`, `values.a`, and `values.b` for grouped autogrow math nodes.
- Follow-up full regression after preserving grouped autogrow prompt sockets:
  `.\.venv\Scripts\python.exe -m pytest -n auto -q` passed with
  `200 passed`.
- Substitute BackEnd:
  - `..\..\venv\Scripts\python.exe tools\add_license_headers.py`
  - `..\..\venv\Scripts\python.exe -m ruff format .`
  - `..\..\venv\Scripts\python.exe -m ruff check .`
  - `..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend tests tools`
  - `..\..\venv\Scripts\python.exe -m pytest -n auto -q`
- SugarSubstitute:
  - `.\.venv\Scripts\ruff.exe format .`
  - `.\.venv\Scripts\ruff.exe check .`
  - `.\.venv\Scripts\mypy.exe --strict substitute tests`
  - Focused live-authoring/client/export tests:
    `.\.venv\Scripts\python.exe -m pytest tests\test_sugar_codec.py tests\test_backend_sugar_workflow_compiler.py tests\test_workflow_export_service.py -q`
  - `.\.venv\Scripts\python.exe -m pytest -n auto -q`

## Verification Commands

Run from each repository root.

### Sugar-DSL

```powershell
cd E:\devprojects\Sugar-DSL
.\.venv\Scripts\python.exe tools\add_license_headers.py
.\.venv\Scripts\ruff.exe format .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe --strict sugar tests
.\.venv\Scripts\python.exe -m pytest -n auto -q
```

### Substitute BackEnd

```powershell
cd E:\comfyui\custom_nodes\substitute-backend
..\..\venv\Scripts\python.exe tools\add_license_headers.py
..\..\venv\Scripts\python.exe -m ruff format .
..\..\venv\Scripts\python.exe -m ruff check .
..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend tests tools
..\..\venv\Scripts\python.exe -m pytest -n auto -q
```

### SugarSubstitute

```powershell
cd E:\devprojects\sugarsubstitute
.\.venv\Scripts\ruff.exe format .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe --strict substitute tests
.\.venv\Scripts\python.exe -m pytest -n auto -q
```

Do not report completion while any blocking gate fails. If a full GUI test run
hits a transient Qt worker crash, rerun the failing test in isolation and rerun
the full suite once before classifying it as unrelated.

## Completion Criteria

The live-definition slice is complete when:

1. Sugar-DSL accepts explicit overrides for live-defined inputs absent from old
   cube artifacts.
2. Sugar-DSL rejects truly unknown inputs.
3. Sugar-DSL materializes missing live-defined inputs from current Comfy widget
   defaults.
4. Sugar-DSL fails before queueing for required public literal widgets with no
   safe value.
5. Sugar-DSL prunes stale cube-authored inputs absent from current live
   definitions.
6. Substitute BackEnd passes live Comfy definitions into Sugar-DSL compile calls.
7. SugarSubstitute can author live-only override lines without importing
   Sugar-DSL.
8. Existing Substitute-owned final prompt preparation remains in Substitute.
9. All tests and required gates pass in every touched repo.
10. Manual smoke test confirms old cubes survive node-pack input additions and
    removals without Comfy hard failures.

## Risks And Mitigations

1. Comfy metadata shape is inconsistent across custom nodes.
   - Normalize in Sugar-DSL runtime and keep raw metadata at the boundary for
     diagnostics.
2. Some required widgets may not have defaults.
   - Fail before queueing with a structured compile error instead of guessing.
3. Some live definitions expose required graph sockets or internal helper
   inputs that Sugar cannot author from an old cube.
   - Materialize defaults only when they are explicit. Omit non-widget sockets
     and expanded subgraph internals when no safe value exists.
4. Combo/list default semantics may be ambiguous.
   - Use only explicit Comfy defaults unless the metadata contract proves the
     first choice is the widget default.
5. Stale input pruning could remove values needed by custom validation quirks.
   - Prune only when a live definition exists and the input is not declared.
     Preserve current standalone behavior without a provider.
6. Frontend authoring may currently filter to cube-authored fields.
   - Add focused Sugar Codec tests, then remove only the filter that blocks
     live-defined fields.
7. Backend compile route may block during definition collection.
   - Snapshot definitions cheaply per compile first. Move to caching/executor
     only if measurement shows blocking is material.

## Remediation: Make Sugar-DSL The Sole Live-Definition Owner

### Problem

The first implementation slice made the compiler core live-definition-aware, but
placed the only real Comfy live-definition provider in Substitute BackEnd. That
does not satisfy the product goal for Sugar-DSL itself:

- Sugar-DSL must be usable stand-alone with hand-authored Sugar scripts.
- Stand-alone Sugar-DSL must be able to adapt when node packs add or remove node
  inputs after a cube was authored.
- Substitute BackEnd must not own the same live-definition normalization feature
  separately from Sugar-DSL.

The provider boundary is still correct. The ownership placement is not.

### Corrected Decision

Sugar-DSL is the single owner of live-definition compilation behavior and live
Comfy definition normalization.

Substitute BackEnd is only a host/invoker. It may provide access to the active
Comfy runtime, but it must not own duplicate live-definition parsing,
normalization, default extraction, or stale-input policy.

Replace these earlier plan statements:

- "Sugar-DSL must not import ComfyUI or depend on Comfy runtime globals."
- "Substitute BackEnd owns the Comfy runtime adapter that reads live node
  definitions and passes normalized data into Sugar-DSL."
- "Normalize in Substitute BackEnd..."

with:

- Sugar-DSL compiler core must not import ComfyUI globals.
- Sugar-DSL runtime adapters may talk to ComfyUI HTTP endpoints or read ComfyUI
  runtime registries when explicitly used by a host or standalone caller.
- Sugar-DSL owns normalization from Comfy metadata into
  `LiveNodeDefinition`/`LiveNodeInputDefinition`.
- Substitute BackEnd selects a Sugar-DSL provider appropriate for its runtime and
  passes it into Sugar-DSL.

### Target Ownership

Sugar-DSL owns:

1. `LiveNodeDefinition`, `LiveNodeInputDefinition`, and
   `LiveNodeDefinitionProvider`.
2. Normalization of Comfy `INPUT_TYPES()` metadata.
3. Normalization of Comfy `/object_info` JSON metadata.
4. Stand-alone live-definition providers.
5. Live-only input resolution.
6. Missing live input materialization from Comfy defaults.
7. Required public literal widget failures.
8. Stale input pruning.
9. Public API/CLI affordances for live-safe compilation.

Substitute BackEnd owns:

1. Importing and invoking Sugar-DSL from inside Comfy.
2. Constructing a Sugar-DSL provider for the active Comfy runtime.
3. Passing that provider into Sugar-DSL compile APIs.
4. Mapping Sugar-DSL compiler errors to backend HTTP errors.
5. Backend capability reporting.

SugarSubstitute owns:

1. Authoring Sugar text.
2. Rendering current live Comfy fields in the UI.
3. Sending Sugar text to Substitute BackEnd.
4. Substitute-specific prompt preparation after backend compile.

### Sugar-DSL Remediation Work

Status: complete.

Landing notes:

- Added `sugar.runtime.live_definitions` as the single Sugar-owned
  normalization and provider module.
- Added `ComfyObjectInfoLiveNodeDefinitionProvider` for standalone
  `/object_info` use.
- Added `ComfyRegistryLiveNodeDefinitionProvider` for hosts running inside
  Comfy, including Substitute BackEnd.
- Added `StaticLiveNodeDefinitionProvider` for normalized snapshots and tests.
- Moved Comfy `INPUT_TYPES()` normalization semantics out of Substitute BackEnd
  and into Sugar-DSL runtime.

Add a Sugar-DSL runtime module:

```text
E:\devprojects\Sugar-DSL\sugar\runtime\live_definitions.py
```

This module should expose:

1. `ComfyObjectInfoLiveNodeDefinitionProvider`
   - Fetches `GET /object_info` from a configured Comfy server.
   - Accepts server values in the same style as existing runtime executor
     helpers, such as `127.0.0.1:8188`.
   - Uses explicit timeouts.
   - Fails with typed/actionable runtime or compiler errors when the endpoint is
     unreachable or returns invalid metadata.
2. `ComfyRegistryLiveNodeDefinitionProvider`
   - Lazily imports Comfy's `nodes` module only when constructed or first used.
   - Reads `nodes.NODE_CLASS_MAPPINGS`.
   - Calls `INPUT_TYPES()` for requested class types.
   - Is appropriate for hosts running inside Comfy, including Substitute
     BackEnd.
3. `StaticLiveNodeDefinitionProvider`
   - Accepts already-normalized definitions or object-info snapshots.
   - Supports tests and offline/reproducible compilation scenarios.
4. Shared normalization helpers for:
   - required inputs
   - optional inputs
   - hidden inputs when they affect prompt validity
   - scalar field specs
   - combo/list choices
   - explicit defaults
   - labels/localized names
   - raw metadata preservation for diagnostics

The normalization logic currently added under Substitute BackEnd should move
into this Sugar-DSL runtime module. Sugar-DSL should have one implementation of
Comfy metadata normalization.

### Sugar-DSL Public API Remediation

Status: complete.

Landing notes:

- Added `comfy_server` to Sugar-DSL public build APIs.
- Public APIs prefer an explicit `live_node_definition_provider` when supplied.
- When `comfy_server` is supplied without a provider, Sugar-DSL constructs its
  own `ComfyObjectInfoLiveNodeDefinitionProvider`.
- No-provider behavior remains unchanged for backwards compatibility.

Keep the existing provider parameter:

```python
live_node_definition_provider: LiveNodeDefinitionProvider | None = None
```

Add convenience API support so stand-alone callers do not have to manually
construct providers for the common case:

```python
build_comfy_artifacts_from_text(
    script_text,
    output_dir=output_dir,
    cube_root=cube_root,
    comfy_server="127.0.0.1:8188",
)
```

Rules:

1. If `live_node_definition_provider` is supplied, use it.
2. Else if `comfy_server` is supplied, construct
   `ComfyObjectInfoLiveNodeDefinitionProvider`.
3. Else preserve current no-provider behavior for backwards compatibility.
4. Do not silently contact Comfy unless the caller supplies a server or provider.
5. If a caller opts into live-safe compilation and live definitions cannot be
   fetched, fail before queueing with an actionable error.

If Sugar-DSL has or gains CLI coverage, expose the same capability:

```powershell
sugar compile recipe.sugar --cube-root E:\cubes --comfy-server 127.0.0.1:8188
```

The CLI should use Sugar-DSL's HTTP object-info provider, not Substitute BackEnd.

### Substitute BackEnd Remediation Work

Status: complete.

Landing notes:

- Removed the backend-owned `comfy_node_definitions.py` normalization module.
- Updated `SugarDslWorkflowCompiler` to instantiate Sugar-DSL's
  `ComfyRegistryLiveNodeDefinitionProvider`.
- Updated backend tests so they no longer assert backend-local normalization.
  Backend now verifies that a Sugar-owned provider is passed to Sugar-DSL and
  that Sugar-DSL live-definition errors are mapped to backend errors.

Remove the backend-owned normalization module:

```text
E:\comfyui\custom_nodes\substitute-backend\substitute_backend\features\sugar_compile\infrastructure\comfy_node_definitions.py
```

Replace it with direct use of Sugar-DSL's runtime provider:

```python
from sugar.runtime.live_definitions import ComfyRegistryLiveNodeDefinitionProvider

provider = ComfyRegistryLiveNodeDefinitionProvider(logger=self._logger)
build_comfy_artifacts_from_text(
    script_text,
    output_dir=output_dir,
    cube_artifact_resolver=BackendCubeArtifactResolver(...),
    live_node_definition_provider=provider,
)
```

Backend tests should change accordingly:

1. Do not test backend-local Comfy metadata normalization.
2. Test that backend passes a Sugar-DSL provider into Sugar-DSL.
3. Test backend maps Sugar-DSL live-definition errors to HTTP errors.
4. Test capability payload still includes `liveNodeDefinitions: true`.

Backend may keep a tiny factory if needed for dependency isolation, but that
factory must not parse or normalize Comfy input metadata.

### SugarSubstitute Remediation Work

Status: complete.

Landing notes:

- No remediation code change was needed in SugarSubstitute.
- Existing characterization tests continue to verify live-only override
  authoring and no Sugar-DSL imports.

No ownership change.

SugarSubstitute still:

1. Authors Sugar text with live-only override lines when the UI buffer contains
   those fields.
2. Sends Sugar text to Substitute BackEnd.
3. Does not import Sugar-DSL.
4. Does not pre-materialize missing live defaults.

Existing characterization tests for live-only override authoring remain valid.

### Remediation Tests

Status: complete.

Landing notes:

- Added `tests/test_runtime_live_definitions.py` in Sugar-DSL for object-info,
  registry, static snapshot, standalone `comfy_server`, invalid payload, default
  materialization, and stale pruning coverage.
- Updated Substitute BackEnd live-definition tests to verify orchestration only.

Add Sugar-DSL tests for:

1. `ComfyObjectInfoLiveNodeDefinitionProvider` normalizes object-info JSON.
2. `ComfyRegistryLiveNodeDefinitionProvider` normalizes fake `INPUT_TYPES()`
   classes.
3. Hand-authored Sugar can set a live-only field using Sugar's own provider.
4. Missing live-only fields materialize from defaults using Sugar's own provider.
5. Stale authored inputs prune using Sugar's own provider.
6. Object-info request failures produce actionable errors.
7. Invalid object-info payloads fail closed.
8. No-provider standalone behavior remains unchanged.

Update Substitute BackEnd tests so they verify orchestration only, not metadata
normalization.

### Remediation Verification

Status: complete for automated gates.

Landing notes:

- Sugar-DSL, Substitute BackEnd, and SugarSubstitute required automated gates
  pass.
- Manual running-app smoke remains deferred to release validation.

Run the same gates as the main implementation:

```powershell
cd E:\devprojects\Sugar-DSL
.\.venv\Scripts\python.exe tools\add_license_headers.py
.\.venv\Scripts\ruff.exe format .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe --strict sugar tests
.\.venv\Scripts\python.exe -m pytest -n auto -q
```

```powershell
cd E:\comfyui\custom_nodes\substitute-backend
..\..\venv\Scripts\python.exe tools\add_license_headers.py
..\..\venv\Scripts\python.exe -m ruff format .
..\..\venv\Scripts\python.exe -m ruff check .
..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend tests tools
..\..\venv\Scripts\python.exe -m pytest -n auto -q
```

```powershell
cd E:\devprojects\sugarsubstitute
.\.venv\Scripts\ruff.exe format .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe --strict substitute tests
.\.venv\Scripts\python.exe -m pytest -n auto -q
```

### Remediation Completion Criteria

Status: complete for implementation and automated verification.

The remediation is complete when:

1. Sugar-DSL owns all Comfy live-definition normalization code.
2. Substitute BackEnd no longer contains a duplicate live-definition
   normalization implementation.
3. Stand-alone Sugar-DSL can compile hand-authored Sugar against live Comfy
   definitions by using a Sugar-owned provider or `comfy_server` option.
4. Backend compilation still works by passing Sugar-DSL's in-process Comfy
   registry provider.
5. SugarSubstitute remains free of Sugar-DSL imports.
6. Tests prove old cubes survive node-pack input additions and removals in
   standalone Sugar-DSL and through Substitute BackEnd.
