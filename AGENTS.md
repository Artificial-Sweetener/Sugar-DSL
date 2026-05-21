# AGENTS.md

## Mission Statement

This project provides a high-quality Python package for compiling Sugar DSL scripts and SugarCube assets into ComfyUI workflow JSON.

Engineering priority is strict architecture, strong separation of concerns, complete refactors, complete feature integrations, behavior safety during structural change, stable cube identity, strict validation, deterministic compilation, and long-term maintainability.

## Purpose

- This file defines engineering guardrails for this repository.
- This file governs architecture, code quality, typing, testing, observability, runtime safety, DSL behavior, cube catalog behavior, and compiler safety.
- Do not use this file for feature specs or product planning.

## Behavior Boundary

- Preserve existing user-facing behavior unless explicitly approved to change.
- Preserve compatibility for supported Sugar DSL syntax unless explicitly approved to change.
- Preserve compatibility for supported `.cube` document formats, local flavor state, spawn plan structure, and generated ComfyUI workflow JSON unless explicitly approved to change.
- Treat current DSL behavior, cube validation behavior, spawn plan shape, and workflow output as the contract.
- Change internals freely within that boundary.

## Environment and Gate Execution

- All verification commands must run against the repository virtual environment at `.venv`.
- Do not run quality gates with global/system Python.
- If `.venv` is missing or stale, recreate it and install the project plus development tooling before running gates.
- Run all commands from the repository root.

### Required command forms

- Tests: `.\.venv\Scripts\python.exe -m pytest -n auto -q`
- License headers: `.\.venv\Scripts\python.exe tools\add_license_headers.py`
- Lint: `.\.venv\Scripts\ruff.exe check .`
- Format: `.\.venv\Scripts\ruff.exe format .`
- Type check: `.\.venv\Scripts\mypy.exe --strict sugar tests`

If a required tool is missing from `.venv`, install or update development dependencies in `.venv` before verification. Do not substitute global tools.

## Core Engineering Principles

- Use strict object-oriented design where ownership, state, lifecycle, or collaboration boundaries exist.
- Enforce strong separation of concerns as the primary architecture objective.
- Keep modules cohesive and boundaries explicit.
- Assign one authoritative owner per concern.
- Other components may participate in a concern only by using the authoritative owner. They must not re-implement that concern in parallel.
- Reassess ownership before extending an existing structure.
- If a change introduces a distinct responsibility, change cadence, or collaboration boundary, split or extract it as part of the change.
- Complete refactors fully. Update all callsites, remove dead code, remove temporary bridges, and make the new design native to the codebase.
- Complete feature additions fully. Wire the feature through the relevant API, compiler, runtime, tests, typing, and validation paths required by the behavior.
- Do not leave partial implementations, unused code paths, TODO-driven behavior, or follow-up cleanup inside the completed change.
- Do not add internal compatibility layers, internal shims, dual internal paths, legacy fallbacks, or transitional adapters.
- Preserve compatibility only at public or persisted boundaries when required by the behavior contract.
- Favor DRY when it reduces repeated change risk.
- Avoid abstractions that hide intent.

## Architecture Rules

- Organize code into clear layers with one-way dependencies.
- Public API layer: stable package-facing entry points such as `sugar.api.builder`.
- DSL/Language layer: tokenization, parsing, AST definitions, and syntax-only validation.
- Catalog layer: cube discovery, cube document validation, local flavor loading, and asset indexing.
- Compiler/Application layer: semantic analysis, compilation flow, spawn plan construction, workflow code generation, inheritance, flavors, and cube operations.
- Runtime/Adapter layer: ComfyUI HTTP execution, workflow patching, filesystem paths, save-path patching, random seed patching, subprocess boundaries, and network boundaries.
- Shared layer: small cross-layer primitives with no higher-level dependencies.
- Higher-level layers may depend on lower-level layers.
- Lower-level layers must not depend on higher-level layers.
- The DSL parser must not perform catalog IO or semantic cube validation.
- The catalog must not know about DSL syntax or workflow generation.
- The analyzer owns DSL semantic interpretation against catalog data.
- Codegen owns conversion from spawn plans into ComfyUI workflow JSON.
- Runtime adapters own external system interaction.
- Keep ComfyUI HTTP details out of parser, catalog, and core semantic analysis.
- Place code by ownership and dependency direction, not convenience or proximity.
- Avoid god classes and monolithic files.
- Split by responsibility, not convenience.

## Structural Change Rules

- For behavior-critical areas, work in two steps:
  1. Add characterization/regression tests for existing behavior.
  2. Perform structural changes behind those tests.
- Behavior-critical areas include DSL parsing, cube validation, flavor resolution, spawn plan generation, workflow codegen, subgraph expansion, inheritance, disable rewiring, random seed behavior, and ComfyUI execution behavior.
- Do not start structural changes in an area without behavior safeguards for that area.
- When behavior spans multiple components, trace the current ownership and data flow before editing.
- Correct the ownership model instead of layering compensating patches across consumers.
- Land structural changes as complete vertical slices.
- Do not land large unverified rewrites.
- If behavior changes are intentional, explicitly call them out and test them as new behavior.
- Current module layout does not constrain improvement.
- Reorganize modules when it improves architecture.
- Align touched modules with the ownership and dependency rules in this file.

## Code Organization and Readability

- Write self-documenting code with expressive, concise names.
- Place new code deliberately in the module where it naturally belongs.
- Keep files intentionally organized so reading order reflects design intent.
- Do not place code opportunistically "where it works".
- Remove obsolete code paths when replacements are complete.
- Keep DSL syntax concerns in `sugar.dsl`.
- Keep cube schema and catalog concerns in `sugar.catalog`.
- Keep compile-time semantic and workflow concerns in `sugar.compiler`.
- Keep ComfyUI runtime communication and workflow patching in `sugar.runtime`.

## Docstrings and Comments

- Docstrings are mandatory for all new and changed modules, classes, functions, and methods.
- Use concise imperative docstrings for simple logic.
- Use Google-style docstrings for complex logic.
- Docstrings must explain rationale, constraints, and intent.
- Docstrings must not restate obvious mechanics.
- Inline comments are allowed only for non-obvious behavior, invariants, edge cases, or external constraints.

## Documentation Policy

- Do not create new docs files, README variants, design docs, ADRs, roadmap files, or notes unless explicitly requested by the maintainer.
- Required context must live in code, type hints, tests, and docstrings.
- Documentation and explanatory writing must describe the product directly as it exists now.
- Do not document against removed features, imagined alternatives, or non-existent choices.

## Typing Policy

- Strong typing is required for all new code.
- Modified code must be typed as part of the change.
- Type hints are mandatory on function signatures and key internal state.
- Use explicit domain types, dataclasses, TypedDicts, Protocols, and type narrowing instead of `Any`.
- `Any` is allowed only at external JSON/dynamic boundaries and must be narrowed before core logic relies on it.
- Run `mypy --strict` for type verification.
- Temporary typing relaxations are allowed only when explicitly justified inline and tracked for removal.

## Logging, Errors, and Observability

- Observability is mandatory.
- Use structured, actionable logging with context identifiers where relevant.
- Include enough context to diagnose failures quickly, such as script path, cube root, cube ID, cube alias, version pin, flavor name, node key, binding name, prompt ID, output path, and operation.
- Use log levels consistently: `debug`, `info`, `warning`, `error`.
- Preserve exception context and stack traces for unexpected failures.
- `print` is not allowed for runtime diagnostics.
- Bare `except:` is not allowed.
- `except Exception` must be narrow, intentional, and log context plus failure reason.
- Silent exception swallowing is not allowed.
- Errors exposed from parser, analyzer, catalog, codegen, and runtime boundaries must be explicit and actionable.

## Desktop Security and Safety Rules

- Treat cube loading, local flavor loading, workflow generation, filesystem paths, ComfyUI HTTP calls, subprocess execution, and network access as security-sensitive.
- Never execute untrusted code paths from cube files, local flavor files, scripts, or generated workflow data.
- Validate and sanitize external paths and user-provided file references.
- Use structured JSON parsing and validation for `.cube` and local flavor files.
- Use subprocess argument lists, never shell-string execution.
- Set explicit timeouts for network operations.
- Fail closed when trust, schema validation, path validation, or version validation is uncertain.
- Never log secrets, tokens, credentials, or sensitive local paths beyond what is necessary for diagnosis.
- Do not silently continue after invalid cube metadata, duplicate cube IDs, invalid flavor state, unresolved aliases, unresolved nodes, or invalid bindings.

## DSL and Compiler Rules

- The parser must remain syntax-only.
- Semantic checks must live in compiler analysis, not in tokenization or parsing.
- Cube identity is `cube_id`.
- Alias is instance identity within a script.
- Alias collisions are fatal.
- Version pin mismatches are fatal.
- Missing cube IDs are fatal and must report available IDs when practical.
- Plan entries must carry cube identity and alias explicitly.
- Internal references during workflow construction must use aliases and normalized node keys, not filenames.
- Deprecated internal paths must be removed after replacement.
- Do not keep compatibility shims inside the compiler.
- Do not preserve old internal DSL, catalog, compiler, or runtime paths after their replacements are complete.

## Testing Policy

- Add or update tests for every behavior change and every bug fix.
- Add characterization tests before structural changes to behavior-critical areas.
- New behavior must not be unverified.
- Include success and failure path coverage.
- Include regression tests for fixed bugs.
- Keep tests deterministic and isolated.
- Use real behavior tests over excessive mocking.
- Mock only external boundaries such as HTTP calls, filesystem errors, random seed generation, and time.
- Compiler behavior must be tested at the narrowest useful level and through integration/golden tests when output shape matters.
- DSL changes require parser tests and analyzer or workflow tests when semantics change.
- Cube schema changes require catalog validation tests.
- Runtime HTTP behavior requires tests for success and failure paths.

## Test Execution Rules

- Run tests in parallel using xdist.
- Default command: `.\.venv\Scripts\python.exe -m pytest -n auto -q`.
- If running a focused subset during development, run the full suite before completion.
- Failing tests are blocking.

## Python Toolchain

- Formatter: `ruff format`
- Linter: `ruff check`
- Type checker: `mypy --strict`
- Test runner: `pytest -n auto -q`

## Verification Workflow

- Run focused checks continuously while implementing.
- Verify the specific reported behavior directly when feasible.
- Do not declare a compiler, DSL, workflow, or runtime issue fixed from code inspection alone when a direct test is feasible.
- Run full gates before reporting completion.
- Distinguish observed results from inferred results in updates and completion reports.
- Do not introduce new lint/type failures in modified files.
- Do not report completion if any blocking gate fails.
- If a gate is intentionally deferred, explicitly state the reason and risk.

## Definition of Done

Per change, all of the following are required:

- Behavior is safeguarded by tests.
- New/modified code follows architecture boundaries.
- New/modified code placement reflects ownership and dependency rules in this file.
- Refactors are complete, with callsites updated and obsolete internal paths removed.
- Features are complete, with API, compiler, runtime, validation, typing, and tests updated wherever the behavior requires them.
- New/modified code is typed.
- Required docstrings are present and meaningful.
- Logging/error handling is actionable.
- Security-sensitive boundaries validate inputs and fail closed.
- `ruff format` passes.
- `ruff check` passes.
- `mypy --strict` passes for the enforced scope.
- `pytest -n auto -q` passes.

## Commit Policy

- Use Conventional Commits: `type(scope): subject`.
- Allowed types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `build`, `ci`.
- Keep commits atomic and cohesive.
- Breaking structural changes must be clearly labeled.

## Maintainer Authority

- Maintainer instructions override this file.
- If constraints conflict, pause and ask for maintainer direction before proceeding.
