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
- Textures are written as `war3mapImported\<image name>.blp`. Use `--texture` to set the path yourself.
- Skinning: classic MDX averages a vertex's bones equally. Bones under 30% of the vertex's strongest weight are dropped (`--weight-cutoff`), with at most 4 bones per vertex (`--max-bones`). Geosets that exceed 256 bone groups or 65535 verts are split automatically.

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

- BLP textures are not converted. Convert the PNG yourself and put it at the printed path.
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
