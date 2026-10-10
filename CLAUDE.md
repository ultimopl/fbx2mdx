# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

fbx2mdx converts 3D models (FBX, glTF, OBJ, DAE, .blend, MDL/MDX) into Warcraft III MDX v800 on Linux. It does this by driving a headless Blender that has a WC3 import/export addon installed. See README.md for user-facing usage and options.

## Commands

```bash
./fbx2mdx IN.glb [OUT.mdx] [convert.py opts]   # convert one file; a directory converts in batch
./edit FILE                                    # Blender GUI with the addon (manual editing)
./setup.sh [blender] [node] [viewer]           # install portable deps into deps/
tests/check.sh IN.fbx [opts]                   # end-to-end check: convert + skinning/animation error report
./mdxinfo.py OUT.mdx                           # dump an MDX summary (chunks, sequences, geosets, bones)
FBX2MDX_VERBOSE=1 ./fbx2mdx ...                # show which blender/node/viewer were picked
```

There is no unit test suite. Verify changes with `tests/check.sh` on a rigged, animated model:
- The `REST match` worst distance should be about 0.
- Per-sequence `mean` vertex error, in WC3 units on a 120-unit model, should stay well under 1. Typical is 0.02–0.15.

The intermediate files land in `work/test/`. Don't point `check.sh` at an input inside `work/test/`, because it overwrites its own source.

`check.sh` calls `convert.py` and `mdl2mdx.js` directly, so it doesn't exercise the `fbx2mdx` bash wrapper (batch mode, output naming, `--anim` handling). Test wrapper changes by running `./fbx2mdx` itself.

## Pipeline

1. **`fbx2mdx` / `edit`** (bash) source `env.sh`. It resolves Blender ≥ 5, Node, and mdx-m3-viewer: system first, then `deps/`. If one is missing from both, it prompts to run `setup.sh`. `--standalone` means `deps/` only.
2. **`convert.py`** runs inside Blender as `blender -b --factory-startup --python convert.py -- IN OUT.mdl [opts]`. It:
   - imports the file;
   - removes object-level animation, which would override the normalization;
   - normalizes the model to `--height` (default 120), rotates it 90° about Z so it faces +X, and grounds it at Z=0;
   - produces textures (`textures.py`) and assigns their WC3 paths into each material's `mdl_layers`. Materials that already have layers are skipped. `textures.classify` follows the shader's Base Color input:
     - an image becomes that image's pixels, converted;
     - a flat color, or vertex colors that are uniform per face, go into a `<out>_colors.blp` palette atlas, with UVs snapped to the cell centers;
     - everything else is baked, Emission → Cycles EMIT at 1 sample, onto a smart-projected `fbx2mdx` UV layer, giving `<out>.blp`. EMIT rather than DIFFUSE keeps metallic materials from baking black.

     A glTF image × COLOR_0 multiply counts as an image when the vertex colors are white.
     `blp.py` is a numpy JPEG encoder for BLP1. WC3 stores raw B,G,R,A bands with no YCbCr, so no stock encoder can produce it.
     BLPs land next to the output MDX. Blender `img.pixels` are stored bottom-up, and shader colors are linear (convert them with `textures.srgb`);
   - renames actions to WC3 sequence names (Stand/Walk/Attack...), dropping `mixamo.com` duplicates;
   - calls `bpy.ops.export.mdl_exporter`.

   Two branches matter here:
   - **MDX/MDL input** is a round-trip. The height, rotation and grounding defaults turn off, and `--sequences auto` takes the importer's scene sequence list rather than the actions. Keep that path untouched when changing normalization.
   - `--anim FILE` imports extra animation files and attaches their actions to the main armature, matched by bone name.

   `convert.py` keeps its own `action_fcurves`, which yields `(channelbag, fcurve)` pairs. It does not import the addon's `utils.action_fcurves`, so a fix to one has to be made in the other too.
3. **`mdl2mdx.js`** turns the MDL into binary MDX with mdx-m3-viewer (`MDX_VIEWER_DIR`).
4. **`scripts/addons/export_mdl/`** is the addon, a Blender 5.x port of export_mdl 3.4. `deps/blender/portable/scripts/addons/export_mdl` is a symlink to it, and a system Blender gets `BLENDER_USER_SCRIPTS=scripts/`, so there is only one copy to edit.
   - Export runs `classes/model_utils/from_scene.py` → `War3Model` → MDL writer.
   - Import lives in `import_stuff/` and is exposed as `bpy.ops.import.mdl_exporter`. Python can only reach it through `getattr(bpy.ops, "import")`.
   - The `export.mdx_exporter` operator writes a temporary MDL and then shells out to `mdl2mdx.js`, finding node via `FBX2MDX_NODE`.

## Format constraints the addon enforces

- **No real skin weights.** MDX v800 matrix groups average a vertex's bones equally. `BpyGeoset.filter_matrix_bones` keeps bones at ≥ `matrix_weight_threshold` (0.3) of the vertex's strongest weight, up to `matrix_max_bones` (4). Changing this trades accuracy against the number of groups.
- **Geoset limits.** GNDX stores the group index as a uint8, so a geoset can have at most 256 matrix groups, and PVTX allows at most 65535 vertices. `make_mesh.split_geoset` splits along triangles when either limit is exceeded.
- **Unweighted vertices** are bound to the first bone (`fix_unweighted`). Without this they silently fall into group 0.
- **Nodes** use pivot-relative TRS. `tests/verify_anim.py` re-implements WC3's skinning rules to compare against Blender's own deformation. Keep it in sync with any change to how bones or matrices are exported.

## Blender 5.x API pitfalls (where most porting bugs came from)

- `action.fcurves` is gone: animation now lives in layers → strips → channelbag(slot). Always use `utils.action_fcurves(action)` and `utils.assign_action(obj, action)`. They create the slot, layer and channelbag when missing.
- Bone groups are gone. Use bone collections plus `bone.color.palette` (`assign_node_type_group`).
- Material and shader changes:
  - `blend_method` is gone; use `surface_render_method`. `shadow_method` is gone too.
  - Principled BSDF sockets were renamed ("Specular IOR Level", "Emission Color"). Use the `set_input(node, names, value)` helper. It is duplicated in `import_stuff/create_material.py` and `import_stuff/War3BpyMaterial.py`, so fix both.
  - `ShaderNodeSeparateRGB` became `SeparateColor`.
- **The Python version differs.** The bundled Blender runs Python 3.13, which evaluates annotations eagerly. The Arch system Blender runs 3.14, which evaluates them lazily. A removed `bpy.types` name used in an annotation therefore crashes only the bundle, so test both: `--standalone` and the default.
- `bpy.ops.export.*` always exists as an attribute, so it can't tell you whether the addon loaded. Check `hasattr(bpy.types.Material, "mdl_layers")` instead.
- Addon preferences can be missing when the addon is enabled without `default_set`, as in headless runs. Read them with `getattr(..., default)`.
