# fbx2mdx (Linux)

A Linux replacement for the Windows-only `Fbx2Mdx.exe`. It uses a portable, headless Blender 5.2 plus the
`export_mdl` addon (WC3 MDL/MDX import + export, ported from export_mdl 3.4 to Blender 5.x).

```
input (.fbx .glb .gltf .obj .dae .blend .mdx .mdl)
  -> Blender importer -> convert.py (scale/orient/materials/sequences)
  -> export_mdl (.mdl) -> mdl2mdx.js (mdx-m3-viewer) -> .mdx
```

## Setup

Nothing to install by hand. The tool needs three dependencies and looks for each one
**on the system first**, then in `deps/`:

| Dependency | System | Portable copy (`setup.sh`) |
|---|---|---|
| Blender ≥ 5 | `blender` on PATH (or `$FBX2MDX_BLENDER`) | `deps/blender`, portable mode, addon symlinked in |
| Node.js ≥ 16 | `node` on PATH | `deps/node` (Node 24 LTS) |
| mdx-m3-viewer | `$MDX_VIEWER_DIR` or a global npm install | `deps/npm` (5.12.0) |

When something is missing in both places, the tool prints a warning and asks whether to
download a portable copy into `deps/`. It downloads only what is missing. Non-interactive
runs just print the `setup.sh` command and exit.

- `--standalone` (or `FBX2MDX_STANDALONE=1`) ignores the system and uses only `deps/`.
  It still offers to install anything missing there.
- `./setup.sh [blender] [node] [viewer]` installs or repairs the portable copies directly.
  Downloads are checked against the official SHA-256 sums. Use `BLENDER_VERSION`,
  `NODE_VERSION` and `VIEWER_VERSION` to pin other versions.
- `FBX2MDX_VERBOSE=1` prints which copy of each dependency was used.
- A full portable install is about 400 MB to download and 1.4 GB on disk. The host only
  needs bash, curl, tar/xz and glibc x86-64.

## Convert

```
./fbx2mdx hero.fbx                         # -> hero.mdx
./fbx2mdx hero.glb out/hero.mdx --height 1 # match an existing 1-unit-tall model
./fbx2mdx "X Bot.fbx" xbot.mdx --anim Running.fbx --anim "Zombie Attack.fbx"
./fbx2mdx models/ out/                     # whole directory
./fbx2mdx --help                           # all options
```

Defaults:
- Scales to 120 units tall, rotates 90° about Z (Blender -Y forward → WC3 +X), and puts the feet at Z=0. MDX/MDL input is left untouched.
- Action names are mapped to WC3 names (`idle`→Stand, `run`→Walk, `attack`→Attack ...). Attack, Death, Spell and similar sequences are non-looping. A model with a single unnamed action gets `Stand`.
- Textures: every BLP the model references is written next to the output `.mdx`, under the in-game path `war3mapImported\<name>.blp` (`--texture-dir` changes the folder):
  - Image textures, external or embedded in the .glb/.fbx, are converted as-is (`<image name>.blp`).
  - Flat material colors and per-face vertex colors go into one small palette, `<model>_colors.blp`.
  - Anything else (smooth vertex colors, procedural nodes, image × color mixes) is baked with Cycles onto a new UV layout, giving `<model>.blp`.

  BLPs are JPEG BLP1 with mipmaps, at most `--texture-size` (512) per side, quality `--texture-quality` (90). Textures with alpha keep an 8-bit alpha channel.
  `--no-textures` only writes the paths. `--texture PATH` uses one path for every material and writes nothing. `--no-vertex-colors` ignores color attributes the material doesn't use (FBX vertex colors are never wired, so by default they're multiplied by the base color).
- Skinning: classic MDX averages a vertex's bones equally. Bones under 30% of the vertex's strongest weight are dropped (`--weight-cutoff`), with at most 4 bones per vertex (`--max-bones`). Geosets that exceed 256 bone groups or 65535 verts are split automatically.

## Examples

Paths are relative to `tools/fbx2mdx`.

**A rigged, animated glTF.** The test unit has flat material colors and three Mixamo actions:

```
$ ./fbx2mdx ../../refs/test-unit/XBOT-ANIMATED.glb out/xbot.mdx
[fbx2mdx] rest height 1.8092 -> scale 66.3264
[fbx2mdx] final bounds [-10.64, -59.86, 0.0] [10.64, 59.86, 120.0]
[fbx2mdx] material Beta_HighLimbsGeoSG3: flat
[fbx2mdx] material Beta_Joints_MAT1: flat
[fbx2mdx] texture xbot_colors.blp (32x32) -> war3mapImported\xbot_colors.blp
[fbx2mdx] action attack -> Attack
[fbx2mdx] action idle -> Stand
[fbx2mdx] dropping action mixamo.com
[fbx2mdx] action running -> Walk
[mdl2mdx] wrote out/xbot.mdx
```

`out/` now holds `xbot.mdx` and `xbot_colors.blp`. The `material ...:` lines say how each material's color was turned into a texture:

| Log | Source | Output |
|---|---|---|
| `image` | an image texture, external or embedded in the .glb/.fbx | `<image name>.blp` |
| `flat` / `atlas` | a flat material color, or vertex colors that are uniform per face | `<model>_colors.blp`, shared |
| `baked` | smooth vertex colors, procedural nodes, image × color | `<model>.blp`, rendered with Cycles |

**A unit for the mod.** Write the model and its textures straight into `content/art`. Point the texture paths at the same folder so they match the in-game layout:

```
./fbx2mdx drone.glb ../../content/art/units/drone/drone.mdx --texture-dir 'units\drone'
../../content/build_mpq.sh
../../src/open-realm/build/bin/mdxtool -mpq ../../content/swarmqueen.mpq -model 'units\drone\drone.mdx' --info
```

**Animations kept in separate files** (the usual Mixamo export). Bone names must match. Each sequence is named after its file and then mapped to a WC3 name:

```
./fbx2mdx "X Bot.fbx" xbot.mdx --anim Idle.fbx --anim Running.fbx --anim "Zombie Attack.fbx"
```

**Size and orientation.** By default the model is scaled to 120 units and turned so Blender's front (-Y) faces WC3's +X. For a model that should stand 60 units tall and already faces +X:

```
./fbx2mdx boss.fbx boss.mdx --height 60 --rot 0,0,0
./fbx2mdx prop.obj prop.mdx --height 0 --no-ground   # keep the imported size and position
```

**Textures:**

```
./fbx2mdx painted.glb painted.mdx --texture-size 1024              # bakes and images up to 1024 px (the color palette stays small)
./fbx2mdx painted.glb painted.mdx --texture-quality 75             # smaller BLPs
./fbx2mdx hero.fbx hero.mdx --no-vertex-colors                     # FBX has stray vertex colors; use the material color
./fbx2mdx hero.fbx hero.mdx --texture 'units\hero\hero.blp'        # you made the BLP yourself; write nothing
./fbx2mdx hero.fbx hero.mdx --no-textures                          # paths only, as before texture generation
```

**Sequences:**

```
./fbx2mdx hero.glb hero.mdx --keep-names                  # keep the original action names, no Stand/Walk/... mapping
./fbx2mdx hero.glb hero.mdx --skip-action 'T-?Pose' --skip-action 'mixamo\.com'   # replaces the default mixamo.com filter, so repeat it
```

**Skinning that looks wrong.** Shoulders collapse, or vertices follow the wrong bone. Run the checker first, then lower the cutoff so more bones are kept:

```
tests/check.sh hero.fbx                                   # per-sequence vertex error, in WC3 units
./fbx2mdx hero.fbx hero.mdx --weight-cutoff 0.15
```

**Batch, round-trip and hand edits:**

```
./fbx2mdx models/ out/                                    # every .fbx/.glb/.gltf/.obj/.dae in the folder
./fbx2mdx old.mdx fixed.mdx                               # MDX in: no rescale, textures and sequences kept
./fbx2mdx hero.glb hero.mdx --save-blend hero.blend && ./edit hero.blend
```

## Edit by hand

```
./edit model.mdx      # or .fbx/.glb/.blend: opens the Blender GUI with the addon enabled
```

In Blender, use File → Export → **Warcraft 3 MDX (.mdx)** or **MDL (.mdl)**. Import is under
File → Import → WC3 MDL/MDX. To pick up where the converter left off, run
`./fbx2mdx in.fbx out.mdx --save-blend out.blend` and then `./edit out.blend`.

## Tests

`tests/check.sh INPUT [opts]` runs convert → mdx → `mdxinfo.py` → `tests/verify_anim.py`. The last step
compares WC3-rule skinning against Blender's deformation and prints the per-sequence vertex error in WC3 units.
`./mdxinfo.py file.mdx` prints a quick summary of any MDX.

## Limitations

- Generated textures are JPEG only (no paletted BLP), and baking needs Cycles (any Blender has it). Materials already set up with MDL layers, as in MDX/MDL round-trips, are left alone.
- No real skin weights (v800 format), so heavily blended areas such as shoulders deform a little differently.
- Root motion on the armature object is frozen. Only bone animation is exported.
- Re-importing an MDX turns attachments and helpers into bones, and can add a small white collision geoset.
- No geoset optimizer yet. Sanity checkers warn about geosets with more than about 7.8k vertices, but they load fine.

## License

GPL-3.0, see [LICENSE.md](LICENSE.md). `scripts/addons/export_mdl` is a Blender 5.x port of
export_mdl 3.4 (twilac), which builds on [mdl-exporter](https://github.com/khalv/mdl-exporter) by
Kalle Halvarsson (GPL-3.0). Its MDX importer comes from
[Blender_WarCraft-3](https://github.com/tw1lac/Blender_WarCraft-3) by Pavel_Blend and twilac.
Blender, Node.js and mdx-m3-viewer are not part of this repository; `setup.sh` downloads them.
