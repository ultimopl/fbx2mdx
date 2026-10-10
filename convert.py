"""Headless Blender entry point: import a model, normalize it for WC3, export MDL.

Run via the `fbx2mdx` wrapper (which also turns the MDL into MDX), or directly:
    blender -b --factory-startup --python convert.py -- IN OUT.mdl [options]
"""
import argparse
import math
import os
import re
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

ADDON = "export_mdl"

# Blender action name (lowercase, first match wins) -> WC3 sequence name.
SEQUENCE_NAMES = [
    (r"^(idle|stand|breath|breathing)", "Stand"),
    (r"^(walk|run|running|jog)", "Walk"),
    (r"(^|\W)(attack|punch|kick|slash|shoot)", "Attack"),
    (r"^(death|die|dying)", "Death"),
    (r"^(spell|cast)", "Spell"),
    (r"^(hit|damage|hurt)", "Stand Hit"),
    (r"^(birth|spawn)", "Birth"),
]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="fbx2mdx")
    p.add_argument("input")
    p.add_argument("output", help=".mdl path to write")
    p.add_argument("--height", type=float, default=None,
                   help="scale the model so its rest-pose height is this many WC3 units "
                        "(0 = keep the imported size; default 120, or 0 for .mdx/.mdl input)")
    p.add_argument("--scale", type=float, default=1.0, help="extra uniform scale after --height")
    p.add_argument("--rot", default=None,
                   help="rotation X,Y,Z in degrees; default 0,0,90 turns Blender's -Y forward into "
                        "WC3's +X (0,0,0 for .mdx/.mdl input)")
    p.add_argument("--offset", default="0,0,0", help="offset X,Y,Z applied last")
    p.add_argument("--no-ground", action="store_true",
                   help="don't move the model so its feet sit at Z=0 centered on the origin "
                        "(implied for .mdx/.mdl input)")
    p.add_argument("--sequences", choices=("auto", "actions", "list"), default="auto",
                   help="'actions': one sequence per Blender action; 'list': the addon's sequence "
                        "list on the scene (what the MDX importer creates); auto picks 'list' when "
                        "it is filled")
    p.add_argument("--texture", default="",
                   help="texture path written for every material (default: "
                        "war3mapImported\\<image or output name>.blp)")
    p.add_argument("--texture-dir", default="war3mapImported",
                   help="in-game folder used for derived texture paths")
    p.add_argument("--keep-names", action="store_true",
                   help="keep action names instead of mapping them to WC3 sequence names")
    p.add_argument("--skip-action", action="append", default=[],
                   help="regex of action names to drop (default drops 'mixamo.com*')")
    p.add_argument("--weight-cutoff", type=float, default=0.3,
                   help="drop bones whose weight is below this fraction of the vertex's strongest "
                        "bone (classic MDX averages a vertex's bones equally)")
    p.add_argument("--max-bones", type=int, default=4, help="max bones per vertex")
    p.add_argument("--anim", action="append", default=[],
                   help="extra animation file (.fbx/.glb) whose actions are added to the model; "
                        "bone names must match. The sequence is named after the file. Repeatable.")
    p.add_argument("--save-blend", default="", help="also save the prepared scene as .blend")
    return p.parse_args(argv)


def vec3(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 3:
        raise SystemExit("expected X,Y,Z, got " + s)
    return v


def log(*a):
    print("[fbx2mdx]", *a, flush=True)


def enable_addon():
    mod = addon_utils.enable(ADDON, default_set=True, persistent=True)
    if mod is None or not hasattr(bpy.types.Material, "mdl_layers"):
        raise SystemExit("[fbx2mdx] export_mdl addon failed to load (see traceback above)")


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
        enable_addon()
    elif ext in (".mdx", ".mdl"):
        getattr(bpy.ops, "import").mdl_exporter(filepath=path)
    else:
        raise SystemExit("unsupported input format: " + ext)


def import_animation(path):
    """Import the actions of an animation-only file and discard its objects."""
    before_objs = set(bpy.data.objects)
    before_actions = set(bpy.data.actions)
    import_model(path)
    new_actions = [a for a in bpy.data.actions if a not in before_actions]
    for obj in set(bpy.data.objects) - before_objs:
        bpy.data.objects.remove(obj, do_unlink=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    for i, action in enumerate(new_actions):
        action.name = stem if len(new_actions) == 1 else "%s|%s" % (stem, action.name)
        action.use_fake_user = True
    log("animation %s: %d action(s)" % (path, len(new_actions)))
    return new_actions


def drop_hidden_objects():
    # Importers sometimes bring in hidden helper geometry; the exporter ignores
    # invisible objects anyway, removing them keeps the bounds honest.
    for obj in list(bpy.context.scene.objects):
        if not obj.visible_get():
            bpy.data.objects.remove(obj, do_unlink=True)


def action_fcurves(action):
    """(channelbag, fcurve) pairs of an action, for both slotted and legacy actions."""
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in list(bag.fcurves):
                        yield bag, fc
    else:
        for fc in list(action.fcurves):
            yield action, fc


OBJECT_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
                   "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")


def strip_object_animation():
    """Remove object-level transform keys from animated armatures/meshes.

    FBX exports often key the armature object itself (e.g. a constant 0.01 scale).
    Those keys would override the normalization below, and the exporter only reads
    bone animation anyway. Constant keys are frozen; moving keys (root motion) are
    dropped so the animation plays in place, which is what WC3 expects.
    """
    for action in bpy.data.actions:
        static = {}
        for bag, fc in action_fcurves(action):
            if fc.data_path not in OBJECT_CHANNELS:
                continue
            values = [k.co[1] for k in fc.keyframe_points]
            if values and max(values) - min(values) > 1e-4:
                log("warning: action %s has root motion on %s[%d]; dropping it (in-place animation)"
                    % (action.name, fc.data_path, fc.array_index))
            static[(fc.data_path, fc.array_index)] = fc.evaluate(action.frame_range[0])
            bag.fcurves.remove(fc)
        if not static:
            continue
        for obj in bpy.context.scene.objects:
            ad = obj.animation_data
            if ad is None or ad.action != action:
                continue
            for (path, index), value in static.items():
                getattr(obj, path)[index] = value
            log("froze object animation of %s from action %s" % (obj.name, action.name))
    bpy.context.view_layer.update()


def rest_bounds():
    """World-space bounds of all meshes with armatures in rest pose."""
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    saved = [(a, a.data.pose_position) for a in arms]
    for a in arms:
        a.data.pose_position = 'REST'
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        for v in mesh.vertices:
            co = mw @ v.co
            lo = Vector(map(min, lo, co))
            hi = Vector(map(max, hi, co))
        ev.to_mesh_clear()
    for a, pos in saved:
        a.data.pose_position = pos
    bpy.context.view_layer.update()
    if lo.x == math.inf:
        return Vector(), Vector()
    return lo, hi


def transform_roots(matrix):
    for obj in bpy.context.scene.objects:
        if obj.parent is None:
            obj.matrix_world = matrix @ obj.matrix_world
    bpy.context.view_layer.update()


def normalize_transform(args):
    rx, ry, rz = (math.radians(v) for v in vec3(args.rot))
    rot = (Matrix.Rotation(rz, 4, 'Z') @ Matrix.Rotation(ry, 4, 'Y') @ Matrix.Rotation(rx, 4, 'X'))
    transform_roots(rot)

    lo, hi = rest_bounds()
    height = hi.z - lo.z
    scale = args.scale
    if args.height > 0 and height > 0:
        scale *= args.height / height
    log("rest height %.4f -> scale %.4f" % (height, scale))
    transform_roots(Matrix.Scale(scale, 4))

    if not args.no_ground:
        lo, hi = rest_bounds()
        center = (lo + hi) / 2
        transform_roots(Matrix.Translation((-center.x, -center.y, -lo.z)))
    transform_roots(Matrix.Translation(vec3(args.offset)))
    lo, hi = rest_bounds()
    log("final bounds", [round(v, 2) for v in lo], [round(v, 2) for v in hi])


def image_of(material):
    if material is None or not material.node_tree:
        return None
    for node in material.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image is not None:
            return node.image
    return None


def setup_materials(args, out_stem):
    """Give every mesh a material whose single MDL layer points at a WC3 texture path."""
    def wc3_path(stem):
        return "%s\\%s.blp" % (args.texture_dir, stem) if args.texture_dir else stem + ".blp"

    fallback = bpy.data.materials.get("war3_" + out_stem) or bpy.data.materials.new("war3_" + out_stem)
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not obj.data.materials or all(m is None for m in obj.data.materials):
            obj.data.materials.clear()
            obj.data.materials.append(fallback)
        for i, m in enumerate(obj.data.materials):
            if m is None:
                obj.data.materials[i] = fallback

    for mat in {m for o in bpy.context.scene.objects if o.type == 'MESH' for m in o.data.materials}:
        if len(mat.mdl_layers):
            continue  # already configured by hand in Blender
        if args.texture:
            path = args.texture
        else:
            img = image_of(mat)
            stem = os.path.splitext(bpy.path.basename(img.filepath or img.name))[0] if img else out_stem
            path = wc3_path(stem)
        layer = mat.mdl_layers.add()
        layer.name = "Layer 0"
        layer.texture_type = '0'
        layer.path = path
        log("material %s -> %s" % (mat.name, path))


GENERIC_ACTION_PARTS = re.compile(
    r"^(mixamo\.com(\.\d+)?|layer\d*|base ?layer|take ?\d*|rigaction|action(\.\d+)?|"
    r"armature(\.\d+)?|root|rig|scene|default)$", re.I)


def action_label(action, fallback):
    """Readable name from an imported action: 'Armature|Running|Layer0' -> 'Running'."""
    names = {o.name.lower() for o in bpy.context.scene.objects}
    for part in reversed(action.name.split("|")):
        part = part.strip()
        if part and not GENERIC_ACTION_PARTS.match(part) and part.lower() not in names:
            return part
    return fallback


def setup_actions(args, src_stem):
    actions = list(bpy.data.actions)
    skip = args.skip_action
    if not skip and len(actions) > 1:
        # Mixamo leaves a tiny 'mixamo.com' action next to the real ones.
        skip = [r"(^|\|)mixamo\.com(\.\d+)?(\||$)"]
    used = set()
    for action in actions:
        if any(re.search(p, action.name, re.I) for p in skip):
            log("dropping action", action.name)
            bpy.data.actions.remove(action)
            continue
        label = action_label(action, src_stem)
        name = label
        if not args.keep_names:
            for pattern, wc3 in SEQUENCE_NAMES:
                if re.search(pattern, label.lower()):
                    name = wc3
                    break
            else:
                if len(actions) == 1:
                    name = "Stand"  # a lone unrecognized animation becomes the idle
        base, n = name, 2
        while name in used:
            name = "%s %d" % (base, n)
            n += 1
        used.add(name)
        if name != action.name:
            log("action %s -> %s" % (action.name, name))
            action.name = name


def apply_format_defaults(args, src):
    wc3 = os.path.splitext(src)[1].lower() in (".mdx", ".mdl")
    if args.rot is None:
        args.rot = "0,0,0" if wc3 else "0,0,90"
    if args.height is None:
        args.height = 0.0 if wc3 else 120.0
    if wc3:
        args.no_ground = True


def main():
    args = parse_args()
    src = os.path.abspath(args.input)
    apply_format_defaults(args, src)
    out = os.path.abspath(args.output)
    out_stem = os.path.splitext(os.path.basename(out))[0]
    if out_stem.endswith(".tmp"):  # fbx2mdx writes <name>.tmp.mdl before MDX conversion
        out_stem = out_stem[:-4]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    enable_addon()
    import_model(src)
    drop_hidden_objects()
    if not any(o.type == 'MESH' for o in bpy.context.scene.objects):
        raise SystemExit("[fbx2mdx] %s has no meshes (animation-only file? pass it with --anim)" % src)
    for anim in args.anim:
        import_animation(os.path.abspath(anim))
    strip_object_animation()
    log("imported", [(o.name, o.type) for o in bpy.context.scene.objects])

    normalize_transform(args)
    setup_materials(args, out_stem)
    use_actions = args.sequences == "actions" or (
        args.sequences == "auto" and not len(bpy.context.scene.war3_mdl_sequences.mdl_sequences))
    log("sequences from", "actions" if use_actions else "scene sequence list")
    if use_actions:
        setup_actions(args, os.path.splitext(os.path.basename(src))[0])
    for action in bpy.data.actions:
        action.use_fake_user = True  # keep actions alive in saved .blend files
    bpy.context.scene.frame_set(0)

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))
        log("saved", args.save_blend)

    result = bpy.ops.export.mdl_exporter(filepath=out, use_actions=use_actions,
                                         matrix_weight_threshold=args.weight_cutoff,
                                         matrix_max_bones=args.max_bones)
    if result != {'FINISHED'} or not os.path.exists(out):
        raise SystemExit("[fbx2mdx] export failed (%s)" % ", ".join(result))
    log("wrote", out)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
