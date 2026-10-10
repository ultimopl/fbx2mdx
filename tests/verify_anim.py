"""Compare WC3-style skinning of an exported model against Blender's own deformation.

    blender -b SCENE.blend --python verify_anim.py -- MODEL.json [samples-per-sequence]

SCENE.blend is the prepared scene saved by convert.py --save-blend; MODEL.json comes
from mdlx2json.js. For each sequence, the script samples a few frames, evaluates the
MDX skeleton with WC3 rules (pivot-relative TRS, equal-weight matrix groups) and
reports how far the vertices land from Blender's deformed mesh, in WC3 units.
"""
import json
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.kdtree import KDTree


def keys_in(track, start, end):
    return [(f, v) for f, v in zip(track["frames"], track["values"]) if start <= f <= end]


def sample(track, t, start, end, kind):
    if track is None:
        return None
    keys = keys_in(track, start, end)
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f0 <= t <= f1:
            a = (t - f0) / (f1 - f0) if f1 > f0 else 0.0
            if kind == "rot":
                q0 = Quaternion((v0[3], v0[0], v0[1], v0[2]))
                q1 = Quaternion((v1[3], v1[0], v1[1], v1[2]))
                q = q0.slerp(q1, a)
                return [q.x, q.y, q.z, q.w]
            return [x + (y - x) * a for x, y in zip(v0, v1)]
    return keys[-1][1]


def node_matrices(model, t, start, end):
    nodes = {n["id"]: n for n in model["nodes"]}
    pivots = model["pivots"]
    world = {}

    def get(nid):
        if nid in world:
            return world[nid]
        n = nodes[nid]
        p = Vector(pivots[nid])
        tr = sample(n["anim"].get("KGTR"), t, start, end, "vec") or [0, 0, 0]
        ro = sample(n["anim"].get("KGRT"), t, start, end, "rot") or [0, 0, 0, 1]
        sc = sample(n["anim"].get("KGSC"), t, start, end, "vec") or [1, 1, 1]
        local = (Matrix.Translation(p) @ Matrix.Translation(tr)
                 @ Quaternion((ro[3], ro[0], ro[1], ro[2])).to_matrix().to_4x4()
                 @ Matrix.Diagonal((*sc, 1.0)) @ Matrix.Translation(-p))
        parent = n["parent"]
        m = get(parent) @ local if parent in nodes else local
        world[nid] = m
        return m

    for nid in nodes:
        get(nid)
    return world


def wc3_vertices(model, t, start, end):
    world = node_matrices(model, t, start, end)
    out = []
    for g in model["geosets"]:
        groups = []
        idx = 0
        for size in g["matrixGroups"]:
            groups.append(g["matrixIndices"][idx:idx + size])
            idx += size
        verts = g["vertices"]
        for i, grp in enumerate(g["vertexGroups"]):
            v = Vector(verts[i * 3:i * 3 + 3])
            bones = groups[grp]
            acc = Vector()
            for b in bones:
                acc += world[b] @ v
            out.append(acc / len(bones))
    return out


def blender_vertices():
    deps = bpy.context.evaluated_depsgraph_get()
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        out.extend(mw @ v.co for v in mesh.vertices)
        ev.to_mesh_clear()
    return out


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    model = json.load(open(args[0]))
    samples = int(args[1]) if len(args) > 1 else 5
    scene = bpy.context.scene
    f2ms = 1000.0 / scene.render.fps
    arm = next(o for o in scene.objects if o.type == 'ARMATURE')

    # Match exported vertices to Blender vertices by rest position.
    arm.data.pose_position = 'REST'
    bpy.context.view_layer.update()
    rest_b = blender_vertices()
    arm.data.pose_position = 'POSE'
    kd = KDTree(len(rest_b))
    for i, co in enumerate(rest_b):
        kd.insert(co, i)
    kd.balance()
    rest_w = [Vector(g["vertices"][i:i + 3]) for g in model["geosets"]
              for i in range(0, len(g["vertices"]), 3)]
    group_sizes = []
    for g in model["geosets"]:
        sizes = g["matrixGroups"]
        group_sizes.extend(sizes[grp] for grp in g["vertexGroups"])
    match = []
    worst = 0.0
    for co in rest_w:
        _, idx, dist = kd.find(co)
        match.append(idx)
        worst = max(worst, dist)
    print("REST match: %d verts, worst distance %.4f" % (len(match), worst))

    for seq in model["sequences"]:
        action = bpy.data.actions.get(seq["name"])
        if action is None:
            print("SEQ %-10s no matching action" % seq["name"])
            continue
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = action
        if hasattr(arm.animation_data, "action_suitable_slots") and arm.animation_data.action_slot is None:
            arm.animation_data.action_slot = arm.animation_data.action_suitable_slots[0]
        f0, f1 = action.frame_range
        start, end = seq["interval"]
        for k in range(samples):
            frame = f0 + (f1 - f0) * k / max(samples - 1, 1)
            scene.frame_set(int(frame), subframe=frame - int(frame))
            anim_b = blender_vertices()
            t = start + (frame - f0) * f2ms
            anim_w = wc3_vertices(model, t, start, end)
            world = node_matrices(model, t, start, end)
            berr = []
            for n in model["nodes"]:
                pb = arm.pose.bones.get(n["name"])
                if pb is None:
                    continue
                head_b = arm.matrix_world @ pb.head
                head_w = world[n["id"]] @ Vector(model["pivots"][n["id"]])
                berr.append(((head_w - head_b).length, n["name"]))
            berr.sort()
            print("   bones: max %.3f %s | mean %.3f" % (berr[-1][0], berr[-1][1], sum(e for e, _ in berr) / len(berr)))
            by_size = {}
            for i, size in enumerate(group_sizes):
                by_size.setdefault(min(size, 4), []).append((anim_w[i] - anim_b[match[i]]).length)
            print("   by group size:", {k: "n=%d mean=%.2f max=%.2f" % (len(v), sum(v) / len(v), max(v))
                                        for k, v in sorted(by_size.items())})
            errs = sorted((anim_w[i] - anim_b[match[i]]).length for i in range(len(match)))
            mean = sum(errs) / len(errs)
            print("SEQ %-10s frame %7.2f t=%6d  mean %.3f  p95 %.3f  max %.3f" % (
                seq["name"], frame, t, mean, errs[int(len(errs) * 0.95)], errs[-1]))


main()
