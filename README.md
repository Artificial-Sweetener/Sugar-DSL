# Sugar DSL

Sugar DSL lets you write ComfyUI workflows as small, readable text files.

Instead of rebuilding the same graph by hand every time you want to reuse an idea, you can compose SugarCubes with plain statements: use this cube, connect that output, set this prompt. The result is still normal ComfyUI workflow JSON, but the source is something you can read, edit, diff, version, and share.

ComfyUI graphs are powerful, but a finished workflow can bury its intent inside node positions, widget values, and long chains of links. Sugar puts that intent back on the page.

## What Writing A Workflow Looks Like

This script uses real base cubes from a SugarCubes library:

```sugar
use "Artificial-Sweetener/Base-Cubes/SDXL/Text to Image.cube" as base
use "Artificial-Sweetener/Base-Cubes/SDXL/Diffusion Upscale.cube" as upscale
use "Artificial-Sweetener/Base-Cubes/SDXL/Automask Detailer.cube" as detail

connect base.output.image to upscale.input.value
connect upscale.output.value to detail.input.value

set base.positive_prompt.value = "a glass city at sunrise, cinematic light"
set base.negative_prompt.value = "low quality, blurry"

set upscale.positive_prompt.value = base.positive_prompt.value
set detail.positive_prompt.value = base.positive_prompt.value
```

That is the shape of the workflow in human terms:

- start with an SDXL text-to-image cube
- pass its image into a diffusion upscale cube
- pass the upscaled image into an automask detailer cube
- write the prompt once and reuse it downstream

Sugar compiles that text into ComfyUI artifacts:

- an executable API prompt with numeric node IDs
- a placed ComfyUI UI workflow that keeps SugarCubes groups, markers, layout, and metadata

The cubes in this example come from [Base-Cubes](https://github.com/Artificial-Sweetener/Base-Cubes), the public cube library built for Sugar. Cubes are authored with the [SugarCubes ComfyUI extension](https://github.com/Artificial-Sweetener/SugarCubes), which turns reusable ComfyUI graph sections into `.cube` assets with stable inputs, outputs, controls, layout, and metadata.

## Installation

Sugar requires Python 3.10 or newer.

Install the package from PyPI:

```powershell
pip install sugar-dsl
```

When you are working on the repository itself, install it in editable mode with development tooling:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Compiling A Script

Use `build_comfy_artifacts_from_text()` when you want both the executable prompt and the visual workflow artifact.

```python
from pathlib import Path

from sugar.api.builder import build_comfy_artifacts_from_text

script = """
use "Artificial-Sweetener/Base-Cubes/SDXL/Text to Image.cube" as base
use "Artificial-Sweetener/Base-Cubes/SDXL/Diffusion Upscale.cube" as upscale
use "Artificial-Sweetener/Base-Cubes/SDXL/Automask Detailer.cube" as detail

connect base.output.image to upscale.input.value
connect upscale.output.value to detail.input.value

set base.positive_prompt.value = "a glass city at sunrise, cinematic light"
set base.negative_prompt.value = "low quality, blurry"

set upscale.positive_prompt.value = base.positive_prompt.value
set detail.positive_prompt.value = base.positive_prompt.value
"""

artifacts = build_comfy_artifacts_from_text(
    script,
    output_dir=Path(r"E:\ComfyUI_output"),
    cube_root=Path(
        r"E:\ComfyUI\custom_nodes\SugarCubes\.sugarcubes"
        r"\Artificial-Sweetener\Base-Cubes"
    ),
)

prompt = artifacts["prompt"]
workflow = artifacts["workflow"]
```

Use `build_workflow_from_text()` when you only need the executable ComfyUI API prompt:

```python
from pathlib import Path

from sugar.api.builder import build_workflow_from_text

prompt = build_workflow_from_text(
    script,
    output_dir=Path(r"E:\ComfyUI_output"),
    cube_root=Path(r"E:\ComfyUI\custom_nodes\SugarCubes\.sugarcubes"),
)
```

The cube root is scanned recursively, so it can point at a specific base-cube checkout or at a broader SugarCubes library directory.

To author your own cubes, install the [SugarCubes ComfyUI extension](https://github.com/Artificial-Sweetener/SugarCubes). To start with ready-made cubes, use [Base-Cubes](https://github.com/Artificial-Sweetener/Base-Cubes).

## Sugar Scripts

Sugar scripts are line-oriented. Each statement says one thing about the workflow.

### Use Cubes

```sugar
use "Artificial-Sweetener/Base-Cubes/SDXL/Text to Image.cube" as base
use "Artificial-Sweetener/Base-Cubes/SDXL/Diffusion Upscale.cube" as upscale
```

Aliases are the names you use inside the script. They are case-insensitive for lookup, but Sugar keeps the spelling you authored in generated metadata.

Version pins are supported:

```sugar
use "Artificial-Sweetener/Base-Cubes/SDXL/Text to Image.cube"@1.0.0 as base
```

Repeat expansion is supported:

```sugar
use "Artificial-Sweetener/Base-Cubes/SDXL/Diffusion Upscale.cube" as pass repeat 2
```

That creates `pass1` and `pass2`.

### Connect Cubes

```sugar
connect base.output.image to upscale.input.value
connect upscale.output.value to detail.input.value
```

Connections use the public bindings declared by the cube. The SDXL text-to-image base cube exposes `output.image`; the SDXL diffusion upscale and automask detailer cubes accept `input.value` and expose `output.value`.

### Set Values

```sugar
set base.positive_prompt.value = "a glass city at sunrise"
set base.negative_prompt.value = "low quality, blurry"
set upscale.ksampler.cfg = 6.5
```

Set statements target readable cube node names and input labels. Cube surfaces can provide friendly labels while the compiler still writes the correct ComfyUI machine input keys.

### Reuse Values

```sugar
set upscale.positive_prompt.value = base.positive_prompt.value
set detail.positive_prompt.value = base.positive_prompt.value
```

References let later cubes inherit authored intent from earlier cubes without duplicating text.

Local variables are supported too:

```sugar
let prompt = "a glass city at sunrise, cinematic light"

set base.positive_prompt.value = prompt
set upscale.positive_prompt.value = prompt
```

### Enable And Disable Nodes

```sugar
enable base.vae_override
disable upscale.vae_override
```

ComfyUI bypass state can be authored in the cube and changed from the script. Disabled nodes are removed from the executable prompt and represented appropriately in the UI workflow artifact.

## SugarCubes

Sugar compiles against `.cube` documents exported by SugarCubes.

A cube gives a ComfyUI graph a stable public surface:

- `cube_id` identifies the cube
- `version` pins the cube contract
- `implementation.nodes` stores the internal ComfyUI graph
- `implementation.inputs` and `implementation.outputs` define the public binding points
- `surface.controls` define script-facing editable controls
- `layout` and `definitions` preserve ComfyUI UI behavior

That surface is what makes a script readable. You do not have to know every internal node link to understand the workflow. You only need the cube names, the public bindings, and the controls you want to change.

## Generated Artifacts

`build_comfy_artifacts_from_text()` returns:

```python
{
    "prompt": {...},
    "workflow": {...},
}
```

`prompt` is the executable ComfyUI API prompt. Sugar expands execution-only details such as subgraph wrappers, resolves aliases into numeric node IDs, applies runtime seed behavior, and sanitizes known integer inputs.

`workflow` is the placed ComfyUI UI workflow. It keeps SugarCubes marker nodes, groups, authored layout, node titles, widget values, and subgraph definitions so the result can still be opened and understood visually.

## Runtime Helpers

Sugar includes small ComfyUI runtime helpers:

- queue a prompt with ComfyUI's HTTP API
- fetch prompt history
- download output images
- poll until generated images appear

```python
from sugar.runtime.executor import poll_for_images, queue_prompt

response = queue_prompt(prompt)
prompt_id = response["prompt_id"]

for images in poll_for_images(prompt_id):
    print(images)
```

Runtime HTTP calls default to `127.0.0.1:8188`.

## Development

Run verification from the repository root with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -n auto -q
.\.venv\Scripts\python.exe tools\add_license_headers.py
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format .
.\.venv\Scripts\mypy.exe --strict sugar tests
```

The test suite covers parser behavior, spawn-plan contracts, cube validation, subgraph expansion, generated workflow snapshots, runtime execution helpers, and UI workflow output.

## License

Sugar DSL is distributed under the GNU General Public License v3.0 or later.

Please read the full [LICENSE](LICENSE) included with this repository.
